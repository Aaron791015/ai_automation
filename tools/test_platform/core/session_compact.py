# -*- coding: utf-8 -*-
"""邊界壓縮：只在「回覆結束、交還給人」那一刻壓縮 session 的 context。

用途：`web_ui/api/chat.py` 送出下一則訊息**之前**呼叫一次。
使用方式：
    from core import session_compact
    seed = session_compact.maybe_compact(sid, meta, ask=claude_ask, save=save_meta)
    #  seed 是要前置到下一則訊息的接手文字；不需要壓縮時回 ""

★ 為什麼要有這一層（2026-08-26 使用者提案，實測支持）

  平台 session 的 context 只長不縮：實測一支探索任務 280 輪、峰值 507k、
  輸入面累計 83.5M token。成本是**複利**的 —— 第 k 輪進 context 的東西，
  之後每一輪都要重讀一次。

  `claude` 的 `--autocompact` 一過門檻就觸發，**會落在任務途中** ——
  而探索與驗 JIRA 的產出就是證據鏈（`CLAUDE.md` §5「案例須留驗證過程與佐證」），
  草稿又是收工才交，途中壓掉的量測值再也回不來。

  ⭐ 改成只在邊界壓，同一條真實軌跡上模擬的結果是**兩個軸都更好**：

      門檻    autocompact（隨時）        邊界壓縮（本模組）
      150k    省 56%，途中壓縮 5 次      省 49%，途中 0 次
      200k    省 48%，途中壓縮 3 次      省 47%，途中 0 次
      250k    省 39%，途中壓縮 2 次      省 39%，途中 0 次

  ⭐ **邊界壓縮在 150k（省 49%）勝過 autocompact 在 250k（省 39%）** ——
  因為風險沒了，門檻反而可以壓得更低。這不是取捨，是直接更好。

  ★ **實測校正（2026-08-26 首次真跑）**：509,312 → 49,119，**壓縮比 0.10**
  （先前模擬假設 0.40，偏保守）。壓縮後的量趨近該 session 原本的起始 context
  （41k），可見它壓到的是「系統提示＋任務提示＋摘要」這個**地板**、與門檻無關 ——
  所以門檻只決定「多久壓一次」，不決定「壓到多小」。
  ⚠️ 摘要回合本身在 509k 的 context 上跑了**約兩分鐘**（冷啟動要重寫整份快取）。
     context 越小越快，但這一步天生會讓人等，所以 SSE 一定要先送進度事件。

  前提（先量過才敢做）：成長要分散在多段之間，邊界才踩得到。實測那支 session
  切成 8 段，最大一段只佔 25%，符合。

⚠️ 它救不到的失效模式：**單段失控**（一則訊息內跑幾百輪）。那一段中間沒有邊界。
   所以 `claude_session.build_argv` 另外下一個**很高**的 `--autocompact` 當安全網 ——
   兩者角色不同：本模組負責省，那個只負責「不要失控」。

四條紀律：

  1. ⛔ **壓縮失敗絕不能讓任務中斷** —— 任何一步出錯就回 ""（照常 `--resume`）。
     省 token 是加值，把任務弄死不是。
  2. ⛔ **transcript 動輒數百 MB，只讀檔尾** —— 整份讀會讓每則訊息卡好幾秒。
  3. **種子從 session 的第一則訊息重建** —— 那就是完整的任務提示（含前言與
     草稿區塊格式）。⚠️ 不可以只給摘要：新 session 不知道區塊格式就交不出草稿。
  4. **已交的草稿不必進種子** —— `chat.py` 的 `_absorb_drafts` 早就存進草稿倉了
     （以 `sid` 為鍵，不隨 claude 那側的 session 走）。種子只要講「已經交過的還在」。
"""
from __future__ import annotations

import io
import json
import os

from core.config import load_config
from core.paths import REPO_ROOT

#: 預設門檻（token）。0 ＝ 關閉邊界壓縮。
#: ⭐ 150k 是模擬裡效益最好又零風險的點；比它更低會讓壓縮太頻繁，
#:    而每次壓縮本身也要付「讀完整 context ＋ 產摘要」的錢。
DEFAULT_THRESHOLD = 150_000

#: 摘要至少要有這幾節裡的**兩節**，才算是一份真的接手摘要。
#: ⭐ 判「結構」比判「長度」可靠得多 —— 2026-08-26 實作時連續兩次踩到：
#:    我自己寫的、內容完整的六節範例摘要只有 159 字（中文密度高），
#:    純長度門檻會把**合格的摘要一起擋掉**，於是這個功能永遠不會觸發。
_SECTIONS = (u"進度", u"已確認", u"已排除", u"環境現況", u"下一步")

#: 長度底線（搭配結構判斷用，不單獨判）。擋的是「## 進度\n做了一些」這種空殼。
MIN_SUMMARY = 120


def looks_like_summary(text):
    """這份回覆像不像一份可以拿來接手的摘要。

    ⭐ 兩個條件都要：**有結構**（至少兩節）＋ **不是空殼**（長度底線）。
       單看任一個都會誤判 —— 只看長度會擋掉密度高的中文，
       只看結構會放行「## 進度\\n做了一些\\n## 下一步\\n繼續」。
    """
    t = (text or "").strip()
    if len(t) < MIN_SUMMARY:
        return False
    return sum(1 for s in _SECTIONS if s in t) >= 2

#: 讀檔尾的長度。一輪的 usage 行遠小於此，256 KB 綽綽有餘。
_TAIL_BYTES = 256 * 1024


def _transcript(cid):
    """claude 那側的 session id → transcript 檔路徑。找不到回 None。"""
    if not cid:
        return None
    try:
        from core.claude_usage import project_key, projects_dir
        p = os.path.join(projects_dir(), project_key(REPO_ROOT), "%s.jsonl" % cid)
        return p if os.path.exists(p) else None
    except Exception:                          # noqa: BLE001
        return None


def context_tokens(cid):
    """目前的 context 有多大（token）。讀不到一律回 0 ＝ 不壓縮。

    ⚠️ **只讀檔尾**（紀律 2）—— 本機最大的 transcript 有 300 MB，
       整份讀會讓每一則訊息都卡住。
    ⚠️ 檔尾切下來的第一行**可能是半行**，一律丟掉。
    """
    path = _transcript(cid)
    if not path:
        return 0
    try:
        size = os.path.getsize(path)
        with io.open(path, "rb") as f:
            if size > _TAIL_BYTES:
                f.seek(size - _TAIL_BYTES)
            raw = f.read()
        lines = raw.decode("utf-8", "replace").splitlines()
        if size > _TAIL_BYTES and lines:
            lines = lines[1:]                  # 半行
        for line in reversed(lines):
            if '"usage"' not in line:
                continue
            try:
                u = (json.loads(line).get("message") or {}).get("usage") or {}
            except ValueError:
                continue
            n = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                 + u.get("cache_creation_input_tokens", 0))
            if n:
                return int(n)
    except Exception:                          # noqa: BLE001
        return 0
    return 0


def threshold(meta=None):
    """門檻：session meta ＞ 設定檔 ＞ 預設。0 或負數 ＝ 關閉。

    ⭐ 讓任務自己宣告（`tasks/*.json` 的 `compact_tokens`），因為不同任務
       對「丟細節」的容忍度差很多：`write_cases` 邊寫邊落檔（證據在
       `tests/` 裡，不在 context），可以壓得比 `explore` 兇。
    """
    m = meta or {}
    if m.get("compact_tokens") is not None:
        try:
            return max(0, int(m["compact_tokens"]))
        except (TypeError, ValueError):
            pass
    try:
        cfg = (load_config().get("claude") or {}).get("compact_tokens")
    except Exception:                          # noqa: BLE001
        cfg = None
    if cfg is not None:
        try:
            return max(0, int(cfg))
        except (TypeError, ValueError):
            pass
    return DEFAULT_THRESHOLD


def plan(meta):
    """要不要壓縮？回 `{"tokens":…, "threshold":…}`，不必壓縮回 None。"""
    m = meta or {}
    cid = m.get("claude_session_id")
    if not cid:
        return None                            # 還沒接上前文，沒東西可壓
    t = threshold(m)
    if t <= 0:
        return None
    n = context_tokens(cid)
    return {"tokens": n, "threshold": t} if n > t else None


#: 要它交出來的接手摘要。
#: ⛔ 刻意**不要**它重述已經交過的草稿（紀律 4）—— 那些在草稿倉裡，
#:    重述一次只是把剛要丟掉的東西再抄一遍。
#: ⭐ 要的是「**接手的人需要知道、而看不到前文就會重做**」的東西。
SUMMARY_PROMPT = u"""> **平台要為你換一份較短的工作記憶**（context 已達 {tokens} token）。
> 這一則**不要做任何新工作、不要用工具**，只要交出接手摘要。

請用下列格式寫。接手的那一位**看不到目前為止的對話**，只會看到任務提示與這份摘要：

## 進度
做到哪了（對照任務目標，一句一項）

## 已確認的事實
量到的值、驗證過的規則、站台上的實際行為 —— 帶上**具體數字**與頁面／API 名稱

## 已排除
試過而不成立的方向，以及**為什麼** —— 沒有這段，接手的人會重做一遍

## 環境現況
用哪個站台與子帳號、建立或改動了哪些測試資料（還原了沒）

## 下一步
接下來要做什麼，第一個動作是什麼

⚠️ 已經交出去的草稿區塊**不必重述** —— 平台已經存起來了，不會因為換記憶而遺失。
⛔ 不確定的事寫「未確認」，**不要憑印象補完**：接手的人會把這份當事實用。
"""


def _first_user_message(sid):
    """session 的第一則使用者訊息 ＝ 完整的任務提示（紀律 3）。

    ⚠️ 平台不另外存任務提示（`tasks_api.launch` 是回給前端、由前端送出的），
       所以訊息紀錄就是唯一的來源。
    """
    try:
        from core.jsonio import read_jsonl
        from web_ui.api.sessions import _msgs_path
        for msg in read_jsonl(_msgs_path(sid)) or []:
            if msg.get("role") == "user" and (msg.get("text") or "").strip():
                return msg["text"]
    except Exception:                          # noqa: BLE001
        pass
    return ""


def build_seed(sid, summary):
    """組出要前置到下一則訊息的接手文字。"""
    task = _first_user_message(sid)
    parts = [u"> ⭐ **你是接手的。** 上一段工作記憶太長，平台把它換成了下面的摘要 ——",
             u"> 這是**同一個任務的延續**，不是新任務。照原本的規則繼續做，",
             u"> ⛔ 不要從頭再來一次，也不要重複已經確認過的事。",
             u"> ⚠️ 已經交過的草稿平台都留著了，**不必重交**；只交這一段新產生的。",
             u""]
    if task:
        parts += [u"---", u"", u"## 原本的任務提示（原文）", u"", task, u""]
    parts += [u"---", u"", u"## 前一段的接手摘要", u"", (summary or "").strip(), u"",
              u"---", u""]
    return u"\n".join(parts)


def maybe_compact(sid, meta, *, ask, save=None):
    """★ 在邊界壓縮。回傳要前置到下一則訊息的種子；不壓縮時回 ""。

    `ask` 傳 `claude_session.ask`（注入是為了測試不必真的起 claude）。

    ⛔ 任何一步失敗都回 ""（紀律 1）—— 照常 `--resume`，任務不受影響。
    """
    p = plan(meta)
    if not p:
        return ""
    try:
        summary = _collect(ask, meta, p)
    except Exception:                          # noqa: BLE001
        return ""
    if not looks_like_summary(summary):
        # ⚠️ 不像一份摘要，八成是出錯了（被拒答／逾時／只回一句「好的」）。
        #    ⛔ 這時**絕不能**丟掉舊 session —— 否則等於把整段工作記憶
        #    換成一句廢話，比不壓縮糟糕得多。
        #    ⭐ 門檻寧可**偏嚴** —— 判錯的兩個方向代價不對稱：
        #    誤判成「太短」只是這次不壓縮（照常 --resume，毫無損失）；
        #    誤放行一份殘缺的摘要，整段工作記憶就沒了。
        return ""
    seed = build_seed(sid, summary)
    # ⭐ 摘要是這次交接的**唯一產物** —— 交接漏了東西時要查得到它說了什麼。
    #    放在 meta 上供呼叫端取用（`chat.py` 會寫成一則 system 訊息）；
    #    ⛔ 呼叫端不要把它存進 meta，那會讓 meta 愈長愈大。
    meta["last_summary"] = summary.strip()
    meta["compacted_at_tokens"] = p["tokens"]
    meta["compact_count"] = int(meta.get("compact_count") or 0) + 1
    meta["compacted_from"] = meta.get("claude_session_id")
    meta["claude_session_id"] = None           # ★ 下一則就會開新的 claude session
    if save:
        save(meta)
    return seed


def _collect(ask, meta, p):
    """跑一次摘要回合，收集文字。"""
    out = []
    for ev in ask(SUMMARY_PROMPT.format(tokens=p["tokens"]),
                  session_id=meta.get("id"), model=meta.get("model"),
                  resume=meta.get("claude_session_id"),
                  allow_tools=None):
        if ev.get("type") == "text":
            out.append(ev.get("text") or "")
        elif ev.get("type") == "error":
            return ""
    return "".join(out)
