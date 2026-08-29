"""/api/sessions —— Claude 對話 session 的管理（索引與紀錄是真的；對話內容在 Demo 為假回覆）。

session 是伺服器端物件，瀏覽器分頁只是檢視器。索引存 logs/sessions/index.jsonl；每個 session 一個目錄
logs/sessions/<id>/{meta.json, messages.jsonl}。「關閉」＝結束 headless 程序但保留紀錄；「刪除」才移除。
M6 接真 claude.exe（--print --output-format stream-json --resume ...）時，本檔的資料結構不變。
"""
from __future__ import annotations

import os
import shutil
import time
import uuid

from flask import Blueprint, request

from core.config import load_config
from core.jsonio import append_jsonl, read_json, read_jsonl, write_json_atomic
from core.paths import SESSIONS_DIR
from web_ui.api import fail, ok

bp = Blueprint("sessions", __name__)


def _dir(sid: str) -> str:
    return os.path.join(SESSIONS_DIR, sid)


def _meta_path(sid: str) -> str:
    return os.path.join(_dir(sid), "meta.json")


def _msgs_path(sid: str) -> str:
    return os.path.join(_dir(sid), "messages.jsonl")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def list_sessions() -> list[dict]:
    if not os.path.isdir(SESSIONS_DIR):
        return []
    out = []
    for sid in os.listdir(SESSIONS_DIR):
        m = read_json(_meta_path(sid))
        if not m or m.get("deleted"):
            continue
        # ⛔ 殘缺的紀錄不要列出來 —— 沒有 `created_at` 就不是正常建立的 session，
        #    畫面上會出現一列「沒有標題、0 則、最後活動 —」的幽靈
        #    （2026-08-24 走查抓到：`logs/sessions/xyz/` 是跑測試留下的）。
        if not m.get("created_at"):
            continue
        m.setdefault("title", "未命名")
        out.append(m)
    out.sort(key=lambda m: m.get("last_active") or "", reverse=True)
    return out


def get_meta(sid: str) -> dict | None:
    return read_json(_meta_path(sid))


# ── 執行狀態（2026-08-24）────────────────────────────────
#: 一個 session 同時只會有一輪在跑，所以狀態直接掛在 meta 上，不另立 store。
#: ⛔ 一律寫**伺服器端** —— 關掉視窗、重開平台都要看得到，否則等於沒做。


def mark_running(sid: str, prompt: str = "") -> None:
    """這一輪開始跑了。"""
    m = get_meta(sid)
    if not m:
        return
    m["activity"] = "running"
    m["activity_started_at"] = _now()
    m["activity_ended_at"] = ""
    m["activity_tools"] = []
    # 交出去的那一句（截斷）—— 讓「運行中」列得出「它在做什麼」而不只是 session 名字
    m["activity_prompt"] = (prompt or "").strip().split("\n")[0][:80]
    save_meta(m)


def note_tool(sid: str, name: str) -> None:
    """記一個工具動作，當作進度。

    ⚠️ **只留最近 8 個且去重** —— 一輪任務可以呼叫上百次工具，
       全存會讓 meta 檔愈長愈大，而人要看的只有「現在在做什麼」。
    """
    m = get_meta(sid)
    if not m or m.get("activity") != "running":
        return
    tools = [t for t in (m.get("activity_tools") or []) if t != name]
    tools.append(name)
    m["activity_tools"] = tools[-8:]
    save_meta(m)


def mark_done(sid: str, outputs: dict | None = None, *, proposal: dict | None = None) -> None:
    """這一輪結束了；有產出就留一筆**待確認**。

    ⛔ 一定要在 `finally` 呼叫 —— 斷線時 generator 收到 `GeneratorExit`，
       不然狀態會**永遠卡在 running**。
    """
    m = get_meta(sid)
    if not m:
        return
    m["activity"] = "idle"
    m["activity_ended_at"] = _now()
    summary = _output_summary(outputs or {}, sid)
    # ⭐ 提議也是產出 —— 而且是 `perf` 任務**唯一**的產出（`writes: none`）。
    #    先前它只活在對話訊息裡，總覽完全看不到「有一個提議在等你按」。
    #    ⛔ 提議仍然只是提議：這裡放的是**提醒**，執行還是要人在確認卡上按。
    if proposal:
        summary.insert(0, {
            "kind": "proposal",
            "text": "提議執行：%s · %s（需要你確認）" % (
                proposal.get("tool_name") or proposal.get("tool_id"),
                proposal.get("command_label") or proposal.get("command_id")),
            "href": "#/tool/%s" % (proposal.get("tool_id") or ""),
        })
    if summary:
        m["pending_review"] = {"at": _now(), "items": summary}
    save_meta(m)


def _output_summary(got: dict, sid: str = "") -> list:
    """把 `_absorb_drafts()` 的回傳整理成「人要看什麼、去哪看」。

    ★ 這就是**結果確認**的內容 —— 與對話串流裡那段 `drafts` 訊息同源，
      差別在於它**留得住**：關掉視窗、隔天再來都還在。

    ⭐ **每一個連結都要走得到產出物本身**（2026-08-24 使用者裁示：
      「確認完結果，要可以接續下一步」）。標準是「已開單」那一條：
      `?focus=` 會捲到那一列並高亮，點開就是完整描述。
      ⛔ 不可以只給 `#/sessions` —— **對話列表不是產出物**，
         人到了那裡還要自己找，等於沒接上。
    """
    out = []
    # ★ 「這一輪沒有正常結束」要排在最前面 —— 它會改變下面每一條的可信度
    #   （產出可能只做到一半）。而這一格**正是為它而設**：本函式的產物
    #   「留得住：關掉視窗、隔天再來都還在」，而截斷最常見的成因就是關掉視窗。
    if got.get("truncated"):
        out.append({"kind": "warn",
                    "text": "⚠️ 這一輪**沒有收到結束訊號**（關掉分頁、重整、"
                            "或 claude 那側非正常結束）—— 下面的產出可能只做到一半。"
                            "送一則「接著剛才的繼續」就會帶著完整脈絡接下去",
                    "href": _sess_href(sid, "chat")})
    for b in got.get("filed") or []:
        out.append({"kind": "bug", "text": "已開單 %s" % b.get("bug_id"),
                    "href": "#/product/%s?tab=bugs&focus=%s" % (
                        (b.get("product") or "").lower(), b.get("bug_id") or "")})
    if got.get("bugs") and not (got.get("filed") or []):
        out.append({"kind": "bug_draft", "text": "%d 筆 Bug 草稿等你判斷" % got["bugs"],
                    "href": _sess_href(sid, "bugs")})
    cw = got.get("cases_written") or {}
    if cw.get("ok"):
        # ⭐ 帶檔案路徑 —— `#/cases?write=<路徑>` 會展開「新寫入待確認」
        #    並自動打開這一批。只給 `#/cases` 的話人要在 1,201 條裡自己找。
        out.append({"kind": "cases", "text": "寫入 %s 條案例" % cw.get("collected"),
                    "href": "#/cases?write=%s" % (cw.get("path") or "")})
        # ★ session 有沒有**自己整檔跑過** —— 逐條跑抓不到互相影響，
        #   跑一次抓不到「不可反覆執行」（使用者 2026-08-26 裁示）。
        runs = cw.get("runs") or []
        if not runs:
            out.append({"kind": "warn",
                        "text": "session **沒有交整檔執行結果** —— "
                                "逐條跑抓不到互相影響（共用 fixture、前一條沒還原站台狀態）",
                        "href": _sess_href(sid, "cases")})
        for r in runs:
            if not r.get("rerun"):
                out.append({"kind": "warn",
                            "text": "只跑了一次 —— 第二次才看得出「不可反覆執行」"
                                    "（資料殘留、名稱撞號、狀態沒收）",
                            "href": _sess_href(sid, "cases")})
            elif "不一致" in r["rerun"] or "不同" in r["rerun"]:
                out.append({"kind": "warn",
                            "text": "兩次執行結果不一致：%s —— 案例沒收乾淨，那是要修的"
                                    % r["rerun"][:60],
                            "href": _sess_href(sid, "cases")})
            if r.get("known_fail"):
                # ⛔ 這幾條**本來就該紅**（判準對、系統錯）。平台不判定對不對，
                #    但一定要讓人看見 —— 否則「硬把 FAIL 改成 PASS」沒有人擋得住。
                out.append({"kind": "known_fail",
                            "text": "session 宣告這幾條本來就該紅（抓到缺陷）：%s"
                                    " —— ⚠️ 請核對，別讓它把判準改到綠" % r["known_fail"][:80],
                            "href": _sess_href(sid, "cases")})
        # ⭐ 「寫入了」跟「跑得過」是兩件事 —— `--collect-only` 只證明收得到。
        vr = cw.get("verify_run") or {}
        if vr.get("run_id"):
            out.append({"kind": "run", "text": "首次驗證執行中（%s 條）" % vr.get("count"),
                        "href": "#/run/%s" % vr["run_id"]})
        else:
            # ⛔ 沒跑成要講原因（併發被擋、registry 缺工具…），不可以靜靜地略過 ——
            #    人會以為跑過了。
            out.append({"kind": "warn",
                        "text": "這批**沒有實際執行過**（%s）—— 收得到 ≠ 跑得過"
                                % (vr.get("skipped") or "原因不明"),
                        "href": "#/cases?write=%s" % (cw.get("path") or "")})
    elif got.get("cases"):
        # ⚠️ 走到這裡＝案例**沒寫成功**（有 cases 但沒有 cases_written）——
        #    寫檔失敗會另外進 write_failed，這裡是「解析到了但落檔那步沒跑」。
        out.append({"kind": "case_draft", "text": "%d 條案例沒有寫成檔案" % got["cases"],
                    "href": _sess_href(sid, "cases")})
    for w in got.get("written") or []:
        out.append({"kind": "doc", "text": "已寫入 %s" % w.get("path"),
                    "href": "#/doc?path=%s" % (w.get("path") or "")})
    for r in got.get("needs_review") or []:
        out.append({"kind": "needs_review",
                    "text": "「%s」沒有自動寫 —— %s" % (r.get("title") or "", r.get("why") or ""),
                    "href": _sess_href(sid, "docs")})
    for f in got.get("write_failed") or []:
        out.append({"kind": "failed",
                    "text": "「%s」寫入失敗：%s" % (f.get("title") or "",
                                                "；".join(f.get("errors") or [])),
                    "href": _sess_href(sid, "docs")})
    # ⭐ 截圖是**唯一一種平台不代勞的產出**（`stamp_shots.py` 的前置是「已經在瀏覽器裡標注過」，
    #    平台代蓋等於騙過 lint）。既然不代勞，就更要**留得住這筆提醒** ——
    #    先前它只出現在落單當下的 API 回應裡，人隔天回來看結果確認完全看不到
    #    （2026-08-25：8 張佐證截圖沒有人去搬，而共用暫存目錄先被清掉了）。
    # ⭐ session 有 shell 之後，它**直接改的檔**草稿模型看不見 ——
    #    這是「給了寫入能力」唯一的問責機制：改了什麼，人看得到。
    #    ⚠️ 措辭是「工作區的異動」不是「它改的」：同一台機器多個 session 共用一份
    #       working tree，這裡分不出是誰動的（`core/worktree.py` 有說明）。
    # ⛔ **接不住就要講** —— 2026-08-25：session 交了三筆格式正確的草稿，
    #    因為它把收尾圍欄與後文寫在同一行，圍欄配對錯位、三筆全被吃掉，
    #    而畫面上**一個字都沒有**。產出可以解析失敗，但不可以無聲消失。
    if got.get("missed"):
        out.append({"kind": "failed",
                    "text": "⚠️ 有 %d 筆草稿沒被接住（區塊格式不合）—— "
                            "內容還在對話裡，需要人看一下" % got["missed"],
                    "href": _sess_href(sid, "docs")})
    ch = got.get("changed") or []
    if ch:
        out.append({"kind": "changed",
                    "text": "這段期間工作區有 %d 個檔案異動：%s%s（由你決定要不要提交）"
                            % (len(ch), "、".join(ch[:4]),
                               "…" if len(ch) > 4 else ""),
                    "href": _sess_href(sid, "docs")})
    n = _shot_count(sid)
    if n:
        out.append({"kind": "shots",
                    "text": "%d 張佐證截圖待標注搬移 —— 在 logs/sessions/%s/shots/，"
                            "標注後用 scripts/stamp_shots.py 搬進 bugs/shots/" % (n, sid),
                    "href": _sess_href(sid, "docs")})
    return out


def _shot_count(sid: str) -> int:
    """這個 session 拍了幾張**還沒歸位**的截圖。取不到一律回 0（提醒缺席勝過整頁壞掉）。

    ⚠️ 判準是「有沒有 `.filed` 記號」，不是「目錄裡有幾個檔」——
       `stamp_shots.py` 是**複製**不是搬移，原檔會留在這裡。
       只數檔案的話，已經歸位的圖會一直被報成待辦，而**假的待辦會讓人開始忽略真的**
       （2026-08-25 補拍任務實跑撞到）。
    """
    if not sid:
        return 0
    d = os.path.join(SESSIONS_DIR, sid, "shots")
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    done = {n[:-len(".filed")] for n in names if n.endswith(".filed")}
    return len([f for f in names
                if f.lower().endswith((".png", ".jpg", ".jpeg")) and f not in done])


def _sess_href(sid: str, panel: str) -> str:
    """指到**那一個 session 的那一塊面板**，不是對話列表首頁。

    ⚠️ 沒有 sid 時退回 `#/sessions` —— 那是最後手段，不是預設。
    """
    return "#/sessions?focus=%s&panel=%s" % (sid, panel) if sid else "#/sessions"


def save_meta(m: dict) -> None:
    write_json_atomic(_meta_path(m["id"]), m)


def append_message(sid: str, role: str, text: str, **extra) -> dict:
    msg = {"role": role, "text": text, "at": _now(), **extra}
    append_jsonl(_msgs_path(sid), msg)
    m = get_meta(sid) or {}
    m["message_count"] = m.get("message_count", 0) + 1
    m["last_active"] = _now()
    if role == "user" and not m.get("title_locked") and m.get("message_count", 0) <= 1:
        m["title"] = text[:24] + ("…" if len(text) > 24 else "")
    save_meta(m)
    return msg


@bp.get("/api/sessions/active")
def active_sessions():
    """進行中的 session ＋ 有產出等人確認的 session。

    ★ 與 `/api/runs/active` 對稱 —— 總覽的「運行中」卡把兩者並排，
      因為對使用者來說它們是同一件事：**我按下去的東西現在怎麼樣了**。
    """
    rows = list_sessions()
    running, review = [], []
    for m in rows:
        item = {
            "id": m.get("id"), "title": m.get("title"), "model": m.get("model"),
            "task": (m.get("context") or {}).get("task"),
            "task_label": (m.get("context") or {}).get("task_label"),
            "product": m.get("product") or (m.get("context") or {}).get("product"),
            "started_at": m.get("activity_started_at"),
            "ended_at": m.get("activity_ended_at"),
            "prompt": m.get("activity_prompt"),
            "tools": m.get("activity_tools") or [],
        }
        if m.get("activity") == "running":
            running.append(item)
        elif m.get("pending_review"):
            review.append({**item, "review": m["pending_review"]})
    running.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    review.sort(key=lambda x: (x.get("review") or {}).get("at") or "", reverse=True)
    return ok(running=running, review=review)


@bp.post("/api/sessions/<sid>/reviewed")
def mark_reviewed(sid):
    """人看過了 —— 清掉待確認。

    ⚠️ **不刪掉產出本身**，只清掉「提醒」。產出在 Bug 單／案例／文件裡，
       各有自己的生命週期；這裡管的只是「我看過了沒」。
    """
    m = get_meta(sid)
    if not m or m.get("deleted"):
        return fail("找不到 session", 404)
    m.pop("pending_review", None)
    save_meta(m)
    return ok(reviewed=True)


@bp.get("/api/sessions")
def api_list():
    q = (request.args.get("q") or "").strip().lower()
    rows = list_sessions()
    if q:
        hits = []
        for m in rows:
            if q in (m.get("title") or "").lower():
                hits.append(m); continue
            # 全文搜尋對話內容
            for msg in read_jsonl(_msgs_path(m["id"])):
                if q in (msg.get("text") or "").lower():
                    hits.append({**m, "hit": msg.get("text", "")[:120]}); break
        rows = hits
    # ⛔ **不要對 `active`／`closed` 截斷**（2026-08-27 移除 `[:10]`）——
    #    完整的 `sessions` 本來就在同一個回應裡，截斷**省不到任何頻寬**，
    #    只造成兩個 bug：
    #      ① 總覽的對話入口顯示「10 條進行中」（實際 14）—— 它拿這個清單的長度當計數
    #      ② 對話面板的下拉**只列得出 10 條**，第 11 條之後**根本選不到**（更嚴重）
    # ⭐ 另外回傳**明確的計數**：要顯示數量的地方一律用它，不要再用清單長度 ——
    #    日後若真的需要截斷（幾百條 session），計數也不會跟著錯。
    active = [m for m in rows if m.get("state") == "active"]
    closed = [m for m in rows if m.get("state") == "closed"]
    return ok(sessions=rows, active=active, closed=closed,
              active_count=len(active), closed_count=len(closed))


def _product_label(pid: str) -> str:
    """slug → 人看得懂的產品名（`crux` → `CRUX`、`wbot` → `投注機器人`）。

    ⚠️ 平台內部一律用小寫 slug 當鍵，但**講給人聽的地方要用權威名稱** ——
       不然對話最上面會寫「產品 crux」，跟 Bug 單上的 `CRUX-nnn` 對不起來。
    """
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if pid in (p.get("id"), p.get("product_id"), p.get("label")):
                return p.get("product_id") or p.get("label") or pid
    except Exception:                           # noqa: BLE001
        pass
    return pid


def _context_line(ctx: dict) -> str:
    """上下文收成**一行**。

    ⚠️ 先前是 `f"帶入上下文：{ctx}"` —— 把整個 dict（含收尾體檢的
       findings 全文）原樣攤在對話最上面，比回覆還長（2026-08-23 UI 走查）。
       人要看的是「這個 session 是為什麼開的」，不是 dict 的 repr。

    ⛔ 2026-08-24 再修兩件講錯話的事（實測時看到的）：
       ① 從對話視窗開的 session 也寫「**由平台任務開啟**」—— 它不是任務開的。
       ② 只帶了 `hash` 時印成「**另有 hash**」—— 那是欄位名，不是資訊。
          未知欄位只列鍵名沒有意義，改成「連值一起講」，講不清楚就不講。
    """
    ctx = ctx or {}
    bits = []
    for k, label in (("product", "產品"), ("area", "區塊"), ("topic", "主題"),
                     ("tickets", "單號"), ("boundary", "邊界"), ("account", "帳號")):
        v = str(ctx.get(k) or "").strip()
        if k == "product" and v:
            v = _product_label(v)          # 對人講產品名，不要講內部 slug
        if v:
            bits.append("%s %s" % (label, " ".join(v.split())[:40]))
    if ctx.get("hash"):
        bits.append("開啟位置 %s" % str(ctx["hash"])[:40])
    if ctx.get("selection_count"):
        bits.append("已選 %s 條案例" % ctx["selection_count"])
    runs = ctx.get("active_runs") or []
    if runs:
        bits.append("正在跑 %s" % "、".join(str(r) for r in runs[:2]))
    if ctx.get("findings"):
        bits.append("已帶入平台的跨 session 發現")
    head = ("本 session 由平台任務開啟：%s" % ctx["task_label"]) if ctx.get("task_label")         else "本 session 由平台的對話視窗開啟"
    return head + ("　——　" + "｜".join(bits) if bits else "")


def api_create_session(body: dict) -> dict:
    """建 session（**可直接呼叫**，不必經 HTTP）。

    ★ 抽出來給任務啟動器用（`web_ui/api/tasks_api.py`）——
      HTTP handler 內聯的話，別的模組要建 session 就得自己複製一份欄位定義。
    """
    cfg = load_config().get("claude") or {}
    sid = str(uuid.uuid4())
    m = {"id": sid, "title": body.get("title") or "新對話", "title_locked": bool(body.get("title")),
         "model": body.get("model") or cfg.get("default_model", "sonnet"),
         "fallback_model": cfg.get("fallback_model"), "created_at": _now(), "last_active": _now(),
         "state": "active", "message_count": 0, "context": body.get("context") or {},
         "product": body.get("product"), "run_id": body.get("run_id"),
         "forked_from": body.get("forked_from"),
         # 任務啟動器帶進來的（`tasks_api.launch`）——
         # `allowed_tools`／`writes` 決定這個 session 能做什麼
         "task_id": body.get("task_id"),
         "allowed_tools": body.get("allowed_tools") or [],
         # ⏱ 任務帶來的單次上限（秒）；沒有就用 claude_session 的預設
         "timeout_sec": body.get("timeout_sec") or None,
         "writes": body.get("writes", "none")}
    os.makedirs(_dir(sid), exist_ok=True)
    # ⭐ 提示會叫 session 把截圖與暫存檔寫進這兩個子目錄 —— 先建好。
    #    ⚠️ MCP 的 `filename` 遇到不存在的中間目錄不保證會自己建，而截圖失敗的症狀是
    #       「工具回了路徑、檔案卻不在」（2026-08-25 那場事故的形狀）。
    #    任務那側 `tasks_api.launch` 也建一次（那裡的 sid 更晚才有），重複無害。
    for sub in ("shots", "work"):
        os.makedirs(os.path.join(_dir(sid), sub), exist_ok=True)
    save_meta(m)
    if body.get("context"):
        append_message(sid, "system", _context_line(body["context"]))
    return m


@bp.post("/api/sessions")
def api_create():
    return ok(session=api_create_session(
        request.get_json(force=True, silent=True) or {}))


@bp.get("/api/sessions/<sid>")
def api_get(sid):
    m = get_meta(sid)
    if not m or m.get("deleted"):
        return fail("找不到 session", 404)
    return ok(session=m, messages=read_jsonl(_msgs_path(sid)))


@bp.patch("/api/sessions/<sid>")
def api_patch(sid):
    m = get_meta(sid)
    if not m:
        return fail("找不到 session", 404)
    body = request.get_json(force=True, silent=True) or {}
    if "title" in body:
        m["title"] = body["title"]; m["title_locked"] = True
    if body.get("action") == "close":
        m["state"] = "closed"; m["closed_at"] = _now()
    if body.get("action") == "resume":
        m["state"] = "active"; m["resumed_at"] = _now(); m["resume_count"] = m.get("resume_count", 0) + 1
        append_message(sid, "system", f"（已續接：重新載入 {m.get('message_count', 0)} 則對話脈絡）")
    save_meta(m)
    return ok(session=m)


@bp.post("/api/sessions/<sid>/fork")
def api_fork(sid):
    m = get_meta(sid)
    if not m:
        return fail("找不到 session", 404)
    new_id = str(uuid.uuid4())
    os.makedirs(_dir(new_id), exist_ok=True)
    if os.path.isfile(_msgs_path(sid)):
        shutil.copyfile(_msgs_path(sid), _msgs_path(new_id))
    nm = {**m, "id": new_id, "title": f"{m.get('title')}（分叉）", "created_at": _now(), "last_active": _now(),
          "state": "active", "forked_from": sid}
    save_meta(nm)
    return ok(session=nm)


@bp.delete("/api/sessions/<sid>")
def api_delete(sid):
    if not os.path.isdir(_dir(sid)):
        return fail("找不到 session", 404)
    shutil.rmtree(_dir(sid), ignore_errors=True)
    return ok()
