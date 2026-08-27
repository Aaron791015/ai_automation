"""Claude 用量統計：掃 `~/.claude/projects/**/*.jsonl` 的 `usage` 欄位，切成小時／日桶。

用途：#/ 總覽狀態列的「Claude 用量」段、#/settings/claude 的用量明細。
使用方式：
    from core.claude_usage import usage_summary
    usage_summary()                  # 讀快取，過期就開背景執行緒增量重掃（不阻塞請求）
    usage_summary(refresh=True)      # 強制整份重建
    python -m core.claude_usage      # 命令列自檢，印出各窗口與明細

前置條件／踩坑（2026-08-25 本機實測，每一條都量過）：
    · ⛔ **同一則 assistant 訊息會寫成多行**（每個 content block 一行），`usage` 原封重複 ——
      不去重會**多算 2.25 倍**（單一 session 實測：raw 2,080,350 → dedup 922,875 output tokens）。
      重複行永遠**相鄰**（實測 non-adjacent repeats = 0），故只需記「上一個 message.id」，
      不必保存全部 id —— 這也是增量掃描能成立的原因。
    · message.id **不跨檔重複**（實測 40 檔 25,823 個 id，跨檔重複 0）→ 不必做全域去重。
    · 全部 transcript 近 1 GB，全掃約 11 秒（實測 91 MB/s）→ **一定要增量**：
      每檔記 (size, offset, last_id, head)，只讀新增的位元組。
      ⛔ 增量的前提是「只會 append」——檔案被換掉時 offset 會指到中段，**parse 出半行垃圾而不報錯**。
      所以每次比一次開頭 120 位元組的雜湊，不一樣就整份重讀。
    · **官方額度百分比有兩個來源**（使用者 2026-08-25 裁示要即時的）：
      ① ⭐ **即時**：`fetch_live_quota()` 打 `GET https://api.anthropic.com/api/oauth/usage`，
         5 分鐘節流。token 取自 `~/.claude/.credentials.json` 的 `claudeAiOauth.accessToken`，
         ⛔ **只在記憶體流動：不回傳前端、不落檔、不進 log、不進錯誤訊息**。
         端點是從 `claude.exe` 撈到的（`fetchUtilization: GET /api/oauth/usage`，
         beta header `oauth-2025-04-20`）—— **未公開，改版就可能變**，所以任何失敗都安靜退回 ②。
      ② **本機快照**：`~/.claude.json` 的 `cachedUsageUtilization`（Claude Code 自己抓完存的）。
         ⚠️ 它**不會自己更新** —— 本機實測曾 54.5 小時沒動，`five_hour.resets_at` 早就過期。
         唯一能更新它的是**在 Claude Code 裡打 `/usage`**（本機指令、不消耗額度，實測有效）。
      兩者回應**同形**（都是 `five_hour` / `seven_day` / `limits[]`），故共用 `_parse_utilization()`。
      ⚠️ 反面測過三條，別再試：**headless `claude -p` 不會更新快照**（任務 session 跑過整天，
      `fetchedAtMs` 一動也沒動）；**`claude -p "/usage"` 也不會**（slash 指令在 print 模式不執行，
      只會白燒額度）；`claude usage/limits/quota` 不是子命令。
      **過期的百分比比沒有百分比更糟**（會被當成現況），所以本模組一律附上抓取時間，
      並在窗口已重置或快取太舊時**明確標成過期、不畫進度條**。
      📝 2026-08-25 兩次更正：本檔原斷言「CLI 與本機檔案都拿不到」（漏查 `~/.claude.json`），
      後又斷言「平台不會去打 API」（使用者裁示改為要打）。
    · **transcript 統計與官方百分比是兩件事，都要留**：前者永遠是即時的、但沒有分母；
      後者有分母、但可能是幾天前的快照。
    · 週限額**依方案而定**：訂閱制（Pro／Max／Team／Enterprise）有週額度，
      API 金鑰／Bedrock／Vertex 是按量計費、沒有週限額 —— 見 `plan_of()`，UI 依此分流。
    · 時間一律換算成**本機時區**再分桶（transcript 存的是 UTC）；換時區後舊桶不會重算。
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta

from core.claude_probe import probe_claude
from core.config import load_config
from core.jsonio import read_json, write_json_atomic
from core.paths import CACHE_DIR, REPO_ROOT

CACHE_FILE = os.path.join(CACHE_DIR, "claude_usage.json")
VERSION = 3
HOUR_KEEP_DAYS = 10          # 小時桶只給「近 5 小時」用，留 10 天綽綽有餘
DAY_KEEP_DAYS = 60           # 日桶給週／月／趨勢用
MAX_AGE_SEC = 45             # 快取超過這個秒數就開背景重掃（總覽輪詢是 60 秒）
QUOTA_FRESH_SEC = 30 * 60    # 官方額度快照超過這個秒數就標成「過舊」，不當現況顯示
QUOTA_LIVE_TTL = 5 * 60      # 即時額度的節流：5 分鐘內不重打（使用者 2026-08-25 指定）
QUOTA_API = "https://api.anthropic.com/api/oauth/usage"
QUOTA_BETA = "oauth-2025-04-20"
CRED_PATH = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")

# 即時額度的行程內快取。⛔ **只存結果，不存 token。**
_live = {"ts": 0.0, "data": None, "error": None, "running": False}

# 有週限額的方案（`claude auth status` 的 subscriptionType）
WEEKLY_PLANS = {"pro", "max", "team", "enterprise"}
PLAN_LABEL = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise", "free": "Free"}

_lock = threading.Lock()
_build = {"running": False, "started_at": 0.0, "error": None}


# ────────────────────────────────── 路徑

def projects_dir() -> str:
    """transcript 根目錄。可用 config 的 claude.projects_dir 覆寫（測試會用到）。"""
    cfg = (load_config().get("claude") or {}).get("projects_dir")
    if cfg:
        return os.path.expandvars(os.path.expanduser(str(cfg)))
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def project_key(path: str) -> str:
    """把工作區路徑轉成 Claude Code 的 project 目錄名（`C:\\GitLab\\Automation` → `c--GitLab-Automation`）。

    ⚠️ 磁碟機代號大小寫不一定一致，比對時一律 `.lower()`。
    """
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "-" for ch in os.path.abspath(path))


# ────────────────────────────────── 桶

def _blank() -> list[int]:
    return [0, 0, 0, 0, 0]      # input / output / cache_write / cache_read / messages


def _add(dst: list[int], u: dict) -> None:
    dst[0] += int(u.get("input_tokens") or 0)
    dst[1] += int(u.get("output_tokens") or 0)
    dst[2] += int(u.get("cache_creation_input_tokens") or 0)
    dst[3] += int(u.get("cache_read_input_tokens") or 0)
    dst[4] += 1


def _merge(dst: list[int], src: list[int]) -> list[int]:
    for i in range(5):
        dst[i] += int(src[i] or 0)
    return dst


def _total(v: list[int]) -> int:
    return int(v[0]) + int(v[1]) + int(v[2]) + int(v[3])


def _to_local(ts: str) -> datetime | None:
    """UTC ISO（`2026-08-24T18:50:12.345Z`）→ 本機時間。

    手工切字串而不用 strptime —— 後者每次約 25µs，首建要跑十幾萬次就差好幾秒。
    """
    try:
        y, mo, d = int(ts[0:4]), int(ts[5:7]), int(ts[8:10])
        h, mi, s = int(ts[11:13]), int(ts[14:16]), int(ts[17:19])
        return datetime.fromtimestamp(calendar.timegm((y, mo, d, h, mi, s, 0, 1, -1)))
    except (ValueError, IndexError, OverflowError, OSError):
        return None


# ────────────────────────────────── 掃描

def _scan_file(path: str, meta: dict) -> dict | None:
    """增量掃一個 transcript，把 usage 累加進**這個檔自己的**桶。回傳更新後的 meta。

    ⛔ 桶必須**掛在檔案底下**，不可以直接累加到全域 —— 否則任何一次「整份重讀」
       （版本換代、檔案被換掉、檔案縮水）都會把同一批訊息**再加一次**，數字直接翻倍，
       而且沒有任何錯誤訊息。（2026-08-25 實際踩到：加了開頭雜湊 → 全部重讀 →
       近 7 天 10.3B 變 20.7B。）全域的 hours／days 一律由 `_merge_all()` 從各檔重算。
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    start = int(meta.get("offset") or 0)
    last_id = meta.get("last_id")
    # ⛔ 增量的前提是「這個檔只會 append」。檔案被**換掉**時 offset 會指到新內容的中段，
    #    parse 出來的是半行垃圾 —— 而它不會報錯，只會讓數字悄悄失真。
    #    所以每次都比一次開頭 120 位元組（OS 有快取，幾乎不花錢），不一樣就整份重讀。
    try:
        with open(path, "rb") as fh:
            head = fh.read(120)
    except OSError:
        return None
    head_sig = hashlib.sha1(head).hexdigest()[:12]
    if meta.get("version") != VERSION or size < start or meta.get("head") != head_sig:
        start, last_id = 0, None
        meta["hours"], meta["days"] = {}, {}      # ★ 重讀＝這個檔的桶整個作廢重算
    hours = meta.setdefault("hours", {})
    days = meta.setdefault("days", {})
    meta["project"] = os.path.basename(os.path.dirname(path))
    if size == start:
        meta.update(version=VERSION, offset=start, size=size, last_id=last_id, head=head_sig)
        return meta
    with open(path, "rb") as fh:
        fh.seek(start)
        buf = fh.read()
    nl = buf.rfind(b"\n")
    if nl < 0:
        return meta                          # 新增的位元組還湊不成一整行，下次再說
    for raw in buf[: nl + 1].split(b"\n"):
        # 先用最便宜的子字串濾掉九成的行（user／tool_result 動輒好幾 MB，全部 json.loads 太貴）。
        # ⚠️ 不可以濾 `b'"type":"assistant"'` —— 那預設了序列化時冒號後**沒有空格**；
        #    真實 transcript 確實是緊湊格式，但這種隱含耦合正是「換個寫法就靜默歸零」的來源。
        if not raw or b'"assistant"' not in raw:
            continue
        try:
            o = json.loads(raw.decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if o.get("type") != "assistant":
            continue
        m = o.get("message") or {}
        u = m.get("usage")
        if not isinstance(u, dict):
            continue
        mid = m.get("id")
        if mid and mid == last_id:
            continue                         # ⭐ 同一則訊息的第二個以後的 content block
        last_id = mid
        lt = _to_local(str(o.get("timestamp") or ""))
        if lt is None:
            continue
        dk = lt.strftime("%Y-%m-%d")
        _add(hours.setdefault("%sT%02d" % (dk, lt.hour), _blank()), u)
        day = days.setdefault(dk, {"t": _blank(), "m": {}})
        _add(day["t"], u)
        _add(day["m"].setdefault(str(m.get("model") or "?"), _blank()), u)
    meta.update(version=VERSION, offset=start + nl + 1, size=size, last_id=last_id, head=head_sig)
    return meta


def _fold(dst_hours: dict, dst_days: dict, src_hours, src_days, project) -> None:
    """把一份（檔案或孤兒）的桶折進目標桶。"""
    for k, v in (src_hours or {}).items():
        _merge(dst_hours.setdefault(k, _blank()), v)
    for k, d in (src_days or {}).items():
        day = dst_days.setdefault(k, {"t": _blank(), "m": {}, "p": {}})
        _merge(day["t"], d.get("t") or _blank())
        for name, v in (d.get("m") or {}).items():
            _merge(day["m"].setdefault(name, _blank()), v)
        if project and "p" in day:
            _merge(day["p"].setdefault(project, _blank()), d.get("t") or _blank())


def _merge_all(files: dict, orphan: dict) -> tuple[dict, dict]:
    """把各檔（＋已消失的檔留下的孤兒桶）合成全域的 hours／days。

    每次 rebuild 都**重算**（不是累加）—— 這就是「重讀不會翻倍」的保證。
    """
    hours: dict = {}
    days: dict = {}
    for meta in files.values():
        _fold(hours, days, meta.get("hours"), meta.get("days"), meta.get("project"))
    for project, o in (orphan or {}).items():
        _fold(hours, days, o.get("hours"), o.get("days"), project)
    return hours, days


def _prune(hours: dict, days: dict) -> None:
    hcut = (datetime.now() - timedelta(days=HOUR_KEEP_DAYS)).strftime("%Y-%m-%dT%H")
    dcut = (datetime.now() - timedelta(days=DAY_KEEP_DAYS)).strftime("%Y-%m-%d")
    for k in [k for k in hours if k < hcut]:
        hours.pop(k)
    for k in [k for k in days if k < dcut]:
        days.pop(k)


def _prune_files(files: dict, orphan: dict) -> None:
    """各檔自己的桶也要修剪，否則快取檔會無限長大。"""
    hcut = (datetime.now() - timedelta(days=HOUR_KEEP_DAYS)).strftime("%Y-%m-%dT%H")
    dcut = (datetime.now() - timedelta(days=DAY_KEEP_DAYS)).strftime("%Y-%m-%d")
    for m in list(files.values()) + list(orphan.values()):
        for k in [k for k in (m.get("hours") or {}) if k < hcut]:
            m["hours"].pop(k)
        for k in [k for k in (m.get("days") or {}) if k < dcut]:
            m["days"].pop(k)
    for name in [n for n, o in orphan.items() if not o.get("hours") and not o.get("days")]:
        orphan.pop(name)


def rebuild(force: bool = False) -> dict:
    """增量（或整份）重建索引並寫回快取。⚠️ 會阻塞，正常路徑走 `usage_summary()` 的背景執行緒。"""
    with _lock:
        idx = read_json(CACHE_FILE, default=None) or {}
        if force or idx.get("version") != VERSION:
            idx = {"version": VERSION, "files": {}, "orphan": {}}
        root = projects_dir()
        idx.setdefault("files", {})
        idx.setdefault("orphan", {})
        t0 = time.time()
        if not os.path.isdir(root):
            idx.update(available=False, root=root, hours={}, days={},
                       scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            write_json_atomic(CACHE_FILE, idx)
            return idx
        files, orphan = idx["files"], idx["orphan"]
        seen = set()
        for dirpath, _dirs, names in os.walk(root):
            for n in names:
                if not n.endswith(".jsonl"):
                    continue
                p = os.path.join(dirpath, n)
                seen.add(p)
                meta = _scan_file(p, dict(files.get(p) or {}))
                if meta is not None:
                    files[p] = meta
        # 檔案被刪（Claude Code 有 30 天自動清理）：meta 丟掉，但桶折進 orphan，歷史不會憑空消失
        for p in [p for p in files if p not in seen]:
            meta = files.pop(p)
            o = orphan.setdefault(meta.get("project") or "?", {"hours": {}, "days": {}})
            _fold(o["hours"], o["days"], meta.get("hours"), meta.get("days"), None)
        hours, days = _merge_all(files, orphan)
        _prune(hours, days)
        _prune_files(files, orphan)
        idx.update(available=True, root=root, files_count=len(files), hours=hours, days=days,
                   scan_ms=int((time.time() - t0) * 1000),
                   scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        write_json_atomic(CACHE_FILE, idx)
        return idx


def _bg(force: bool) -> None:
    try:
        rebuild(force)
        _build["error"] = None
    except Exception as e:                                   # noqa: BLE001 背景執行緒不能讓例外逃走
        _build["error"] = f"{type(e).__name__}: {e}"
    finally:
        _build["running"] = False


def _kick(force: bool = False) -> None:
    if _build["running"]:
        return
    _build.update(running=True, started_at=time.time())
    threading.Thread(target=_bg, args=(force,), daemon=True, name="claude-usage").start()


# ────────────────────────────────── 官方額度百分比（快取，會過期）

TIER_LABEL = {"default_claude_max_5x": "Max 5×", "default_claude_max_20x": "Max 20×",
              "default_claude_pro": "Pro", "default_claude_free": "Free"}


def claude_json_path() -> str:
    cfg = (load_config().get("claude") or {}).get("config_json")
    if cfg:
        return os.path.expandvars(os.path.expanduser(str(cfg)))
    return os.path.join(os.path.expanduser("~"), ".claude.json")


def _iso_epoch(s):
    """`2026-08-26T00:00:00.144333+00:00` → epoch 秒。解不出來回 None。"""
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except (TypeError, ValueError):
        return None


def _bar(raw, now, label, kind):
    """把一段 utilization 轉成 UI 直接可用的形狀。

    ⛔ `expired` 是**這一格自己的**判準：`resets_at` 已經過了，代表那個窗口早就重置，
       快照裡的百分比講的是上一個窗口 —— 顯示它等於報一個假的現況。
    """
    if not isinstance(raw, dict) or raw.get("utilization") is None:
        return None
    reset = _iso_epoch(raw.get("resets_at"))
    return {"kind": kind, "label": label, "percent": int(raw.get("utilization") or 0),
            "resets_at": raw.get("resets_at"),
            "resets_in_sec": int(reset - now) if reset else None,
            "expired": bool(reset and reset <= now)}


def live_quota_enabled() -> bool:
    """預設開啟；`platform_config.local.json` 的 `claude.live_quota: false` 可關掉。"""
    v = (load_config().get("claude") or {}).get("live_quota")
    return True if v is None else bool(v)


def _oauth_token() -> tuple[str | None, float, str | None]:
    """回 (token, expiresAt 秒, 錯誤說明)。⛔ token 只在記憶體裡流動，**不回傳給前端、不寫檔、不進 log**。"""
    try:
        with open(CRED_PATH, encoding="utf-8") as f:
            o = (json.load(f) or {}).get("claudeAiOauth") or {}
    except (OSError, json.JSONDecodeError):
        return None, 0.0, "找不到或讀不了 ~/.claude/.credentials.json"
    tok = o.get("accessToken")
    exp = float(o.get("expiresAt") or 0) / 1000.0
    if not tok:
        return None, exp, "憑證檔裡沒有 accessToken（可能是 API key 或企業代理模式）"
    if exp and exp <= time.time():
        return None, exp, "OAuth token 已過期 —— 在 Claude Code 用一下就會自動續期"
    return tok, exp, None


def _redact(msg: str, tok: str | None) -> str:
    """把 token 從任何要外流的字串裡挖掉。⛔ 錯誤訊息是最常見的洩漏途徑。"""
    out = str(msg or "")
    if tok:
        out = out.replace(tok, "***")
        if len(tok) > 12:                       # 連前綴片段也一起遮，免得被拼回去
            out = out.replace(tok[:12], "***")
    return out


def fetch_live_quota(force: bool = False) -> dict | None:
    """打官方端點拿即時額度。回傳 `utilization` 形狀的 dict；失敗回 None（呼叫端要能退回快照）。

    ⛔ 三條紀律：
      · token 只在這個函式裡出現，**不回傳、不落檔、不進錯誤訊息**（例外訊息一律自己組）
      · `QUOTA_LIVE_TTL` 節流 —— 總覽每 60 秒問一次，但真正打出去最多 5 分鐘一次
      · 任何失敗都**安靜退回本機快照**，不讓一個看板數字把整頁弄壞

    ⚠️ `/api/oauth/usage` 是**未公開端點**（從 claude.exe 撈到 `fetchUtilization: GET /api/oauth/usage`）。
       Claude Code 改版就可能變 —— 所以這裡只當「錦上添花」，本機快照仍是保底。
    """
    if not live_quota_enabled():
        return None
    now = time.time()
    if not force and _live["data"] and now - _live["ts"] < QUOTA_LIVE_TTL:
        return _live["data"]
    tok, _exp, err = _oauth_token()
    if not tok:
        _live.update(ts=now, error=err)
        return _live["data"]                     # 有舊的就先用舊的
    try:
        import requests                          # 延後匯入：沒裝也不該讓整個模組掛掉
        r = requests.get(QUOTA_API, timeout=12, headers={
            "Authorization": "Bearer %s" % tok,
            "anthropic-beta": QUOTA_BETA,
            "Content-Type": "application/json",
            "User-Agent": "test-platform (reads own account usage)",
        })
    except Exception as e:                        # noqa: BLE001 網路錯誤百百種，一律降級
        # ⛔ 例外原文**可能夾帶 token**（有些函式庫會把整串 URL／header 印進錯誤裡），
        #    而這個字串會一路回到瀏覽器 —— 一律先遮罩。（2026-08-25 由測試抓到的真洩漏。）
        _live.update(ts=now, error=_redact("%s: %s" % (type(e).__name__, str(e)[:120]), tok))
        return _live["data"]
    if r.status_code != 200:
        _live.update(ts=now, error="HTTP %d%s" % (r.status_code, "（token 可能失效，去 Claude Code 用一下）" if r.status_code in (401, 403) else ""))
        return _live["data"]
    try:
        body = r.json()
    except ValueError:
        _live.update(ts=now, error="回應不是 JSON")
        return _live["data"]
    # 回應與 `cachedUsageUtilization.utilization` **同形**（2026-08-25 實測），所以解析可以共用
    if not isinstance(body, dict) or not body.get("five_hour"):
        _live.update(ts=now, error="回應少了 five_hour —— 端點可能改版了")
        return _live["data"]
    _live.update(ts=now, data=body, error=None)
    return body


def _parse_utilization(u: dict, now: float, out: dict) -> None:
    """把 `utilization` 形狀的 dict 攤成 UI 要的 bars／scoped。快照與即時共用同一份。"""
    for key, label, kind in (("five_hour", "5 小時窗口", "five_hour"), ("seven_day", "週額度", "seven_day")):
        b = _bar(u.get(key), now, label, kind)
        if b:
            out["bars"].append(b)
    # 逐模型的週額度（`weekly_scoped`）—— 有就列，沒有不強求
    for L in u.get("limits") or []:
        if L.get("kind") != "weekly_scoped" or L.get("percent") is None:
            continue
        name = (((L.get("scope") or {}).get("model") or {}).get("display_name")) or "（不具名）"
        reset = _iso_epoch(L.get("resets_at"))
        out["scoped"].append({"label": name, "percent": int(L.get("percent")),
                              "resets_at": L.get("resets_at"),
                              "expired": bool(reset and reset <= now)})


def read_utilization(force: bool = False) -> dict:
    """官方額度百分比。**唯讀** `~/.claude.json` 的 `cachedUsageUtilization`。

    ⛔ 平台**不會**去打 API、也不碰 `~/.claude/.credentials.json` ——
       這裡讀的是 Claude Code 自己抓完存下來的快照，所以：

       · `fetched_at` 一定要跟著顯示；
       · `stale`（快照太舊）與每一格的 `expired`（那個窗口已重置）**是兩回事**，兩個都要擋；
       · 兩者任一成立時 `usable` 為 False —— UI 就不該把它當現況畫進度條。

    回傳恆為 dict，`available` 為 False 時其餘欄位為空（同事沒登入、或還沒抓過）。
    """
    now = time.time()
    out = {"available": False, "usable": False, "stale": None, "fetched_at": None,
           "age_sec": None, "bars": [], "scoped": [], "tier": None, "tier_label": None,
           "live": False, "live_error": None,
           "source": "~/.claude.json · cachedUsageUtilization（Claude Code 自己抓的快照）"}
    # ⭐ 先試即時（5 分鐘節流）。⛔ 失敗一律安靜退回下面的本機快照 ——
    #    一個看板數字不值得把整頁弄壞，而快照至少還帶著自己的抓取時間。
    body = fetch_live_quota(force)
    out["live_error"] = _live["error"]
    if body:
        out.update(available=True, live=True, stale=False,
                   age_sec=int(now - _live["ts"]),
                   fetched_at=datetime.fromtimestamp(_live["ts"]).strftime("%Y-%m-%d %H:%M"),
                   source="api.anthropic.com/api/oauth/usage（平台即時查詢，5 分鐘節流）")
        _parse_utilization(body, now, out)
        tier = _plan_tier_from_cred()
        out["tier"], out["tier_label"] = tier, TIER_LABEL.get(tier or "", (tier or "").replace("default_claude_", "").replace("_", " ").title() or None)
        out["usable"] = bool(out["bars"]) and not all(b["expired"] for b in out["bars"])
        return out
    try:
        with open(claude_json_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return out
    cache = d.get("cachedUsageUtilization") or {}
    u = cache.get("utilization") or {}
    if not u:
        return out
    fetched = (cache.get("fetchedAtMs") or 0) / 1000.0
    age = now - fetched if fetched else None
    out.update(available=True, age_sec=int(age) if age is not None else None,
               fetched_at=(datetime.fromtimestamp(fetched).strftime("%Y-%m-%d %H:%M")
                           if fetched else None),
               stale=(age is None or age > QUOTA_FRESH_SEC))
    tier = ((d.get("oauthAccount") or {}).get("organizationRateLimitTier")
            or (d.get("oauthAccount") or {}).get("userRateLimitTier"))
    out["tier"] = tier
    out["tier_label"] = TIER_LABEL.get(tier or "", (tier or "").replace("default_claude_", "").replace("_", " ").title() or None)
    _parse_utilization(u, now, out)
    out["usable"] = bool(out["bars"]) and not out["stale"] and not all(b["expired"] for b in out["bars"])
    return out


def _plan_tier_from_cred() -> str | None:
    """即時模式下的額度層級：憑證檔就有（`rateLimitTier`），不必再去讀 ~/.claude.json。"""
    try:
        with open(CRED_PATH, encoding="utf-8") as f:
            o = (json.load(f) or {}).get("claudeAiOauth") or {}
    except (OSError, json.JSONDecodeError):
        return None
    return o.get("rateLimitTier")


# ────────────────────────────────── 方案

def plan_of(auth: dict | None) -> dict:
    """從 `claude auth status` 判斷方案與**有沒有週限額**。

    回傳的 `short` 是**狀態列角標**用的（右上角只有約 40px），`label` 才是設定頁的全名。

    ⭐ 這就是使用者說的「有些人有週使用量、有些人沒有」——
       訂閱制才有週額度；API 金鑰／Bedrock／Vertex 是按量計費。
    """
    a = auth or {}
    sub = str(a.get("subscriptionType") or "").lower()
    method = str(a.get("authMethod") or "").lower()
    provider = str(a.get("apiProvider") or "").lower()
    if not a.get("loggedIn") and not method:
        return {"label": "未登入", "short": "—", "kind": "none", "has_weekly": False,
                "note": "尚未登入 Claude Code，統計只涵蓋過去留下的紀錄"}
    if sub in WEEKLY_PLANS:
        lbl = PLAN_LABEL.get(sub, sub.title())
        return {"label": lbl, "short": lbl, "kind": "subscription", "has_weekly": True,
                "note": "訂閱制：有 5 小時窗口與週額度"}
    if provider and provider != "firstparty":
        lbl = {"bedrock": "Bedrock", "vertex": "Vertex", "foundry": "Foundry"}.get(provider, provider.title())
        return {"label": lbl, "short": lbl, "kind": "byo", "has_weekly": False,
                "note": "自帶雲端供應商：依用量計費，無週限額"}
    if "key" in method or sub in {"", "none"}:
        return {"label": "API 金鑰", "short": "API", "kind": "api", "has_weekly": False,
                "note": "按量計費：無週限額，數字即實際消耗"}
    lbl = PLAN_LABEL.get(sub, sub.title() or "訂閱")
    return {"label": lbl, "short": lbl, "kind": "subscription", "has_weekly": True,
            "note": "訂閱制：有 5 小時窗口與週額度"}


# ────────────────────────────────── 彙總

def _window(rows: list[list[int]]) -> dict:
    t = _blank()
    for r in rows:
        _merge(t, r)
    return {"total": _total(t), "input": t[0], "output": t[1],
            "cache_write": t[2], "cache_read": t[3], "messages": t[4]}


def _day_keys(n: int, offset: int = 0) -> list[str]:
    base = datetime.now() - timedelta(days=offset)
    return [(base - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def usage_summary(refresh: bool = False, wait: bool = False, quota_force: bool = False) -> dict:
    """回總覽與設定頁要的用量摘要。**不阻塞** —— 快取過期就丟給背景執行緒。

    wait=True 只給命令列與測試用（同步重建）。
    """
    if wait or refresh:
        if wait:
            rebuild(refresh)
        else:
            _kick(True)
    idx = read_json(CACHE_FILE, default=None)
    if not idx:
        _kick(False)
        return {"ready": False, "building": True, "available": None,
                "hint": "首次統計中（約十秒），完成後自動出現"}
    try:
        age = time.time() - os.path.getmtime(CACHE_FILE)
    except OSError:
        age = 1e9
    if age > MAX_AGE_SEC and not wait:
        _kick(False)

    hours, days = idx.get("hours") or {}, idx.get("days") or {}
    now = datetime.now()
    h_keys = {(now - timedelta(hours=i)).strftime("%Y-%m-%dT%H") for i in range(5)}
    d7, d7prev, d30 = _day_keys(7), _day_keys(7, 7), _day_keys(30)
    today = now.strftime("%Y-%m-%d")

    def day_tot(k):
        return ((days.get(k) or {}).get("t")) or _blank()

    # 近 7 天的模型／專案分佈
    models: dict[str, list[int]] = {}
    projects: dict[str, list[int]] = {}
    for k in d7:
        d = days.get(k) or {}
        for name, v in (d.get("m") or {}).items():
            _merge(models.setdefault(name, _blank()), v)
        for name, v in (d.get("p") or {}).items():
            _merge(projects.setdefault(name, _blank()), v)

    here = project_key(REPO_ROOT).lower()
    ws = _blank()
    for name, v in projects.items():
        if name.lower() == here:
            _merge(ws, v)

    spark = [{"day": k, "total": _total(day_tot(k))} for k in reversed(_day_keys(14))]
    info = probe_claude()
    plan = plan_of(info.get("auth"))

    return {
        "ready": True,
        "building": _build["running"],
        "available": bool(idx.get("available")),
        "root": idx.get("root"),
        "files": idx.get("files_count"),
        "scanned_at": idx.get("scanned_at"),
        "scan_ms": idx.get("scan_ms"),
        "age_sec": int(age),
        "error": _build["error"],
        "plan": plan,
        "logged_in": bool(info.get("logged_in")),
        "windows": {
            "h5": _window([v for k, v in hours.items() if k in h_keys]),
            "today": _window([day_tot(today)]),
            "week": _window([day_tot(k) for k in d7]),
            "prev_week": _window([day_tot(k) for k in d7prev]),
            "month": _window([day_tot(k) for k in d30]),
        },
        "spark": spark,
        # 過濾 total=0 的條目 —— `<synthetic>` 這種佔位模型會混進來，列出來只是雜訊
        "by_model": [x for x in sorted(({"name": k, **_window([v])} for k, v in models.items()),
                                       key=lambda x: -x["total"]) if x["total"]][:6],
        "by_project": [x for x in sorted(({"name": k, "here": k.lower() == here, **_window([v])} for k, v in projects.items()),
                                         key=lambda x: -x["total"]) if x["total"]][:8],
        "workspace": {**_window([ws]), "key": here},
        # ⭐ 官方額度百分比（快取）。與上面的 transcript 統計是**互補**的兩件事：
        #    這裡有分母但可能過期，上面永遠即時但沒有分母。
        "quota": read_utilization(quota_force),
        "source": "本機 transcript（~/.claude/projects）",
        "caveat": "token 數字是本機 transcript 的實際消耗；額度百分比另取自 Claude Code 的本機快照（會過期，見 quota.fetched_at）",
    }


def main(argv=None) -> int:
    t0 = time.time()
    s = usage_summary(wait=True, refresh="--rebuild" in (argv or sys.argv[1:]))
    if not s.get("available"):
        print("找不到 transcript 目錄：", s.get("root") or projects_dir())
        return 1
    print(f"掃描 {s['files']} 檔，{s.get('scan_ms')} ms（本次總耗時 {int((time.time()-t0)*1000)} ms）")
    print(f"方案：{s['plan']['label']}　週限額：{'有' if s['plan']['has_weekly'] else '無'}　{s['plan']['note']}")
    for k, label in [("h5", "近 5 小時"), ("today", "今日"), ("week", "近 7 天"), ("prev_week", "前 7 天"), ("month", "近 30 天")]:
        w = s["windows"][k]
        print(f"  {label:<8} 總 {w['total']:>13,}　輸入 {w['input']:>11,}　輸出 {w['output']:>10,}　"
              f"快取寫 {w['cache_write']:>12,}　快取讀 {w['cache_read']:>13,}　訊息 {w['messages']:>6,}")
    q = s.get("quota") or {}
    if q.get("available"):
        print(f"官方額度快照（{q['fetched_at']}，{'可用' if q['usable'] else '⚠️ 不可當現況'}）："
              + "　".join(f"{b['label']} {b['percent']}%{'（已重置）' if b['expired'] else ''}" for b in q["bars"]))
        for x in q["scoped"]:
            print(f"    逐模型：{x['label']} {x['percent']}%")
    else:
        print("官方額度快照：本機沒有（~/.claude.json 沒有 cachedUsageUtilization）")
    print("模型（近 7 天）：", ", ".join(f"{m['name']} {m['total']:,}" for m in s["by_model"]))
    print("專案（近 7 天）：", ", ".join(f"{p['name']}{'★' if p['here'] else ''} {p['total']:,}" for p in s["by_project"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
