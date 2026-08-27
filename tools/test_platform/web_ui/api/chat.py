"""/api/chat —— 對話面板（Demo：規則式假回覆；M6 接真 claude.exe headless session ＋ SSE）。

⚠️ Demo 的回覆是**規則式模板，不是 LLM** —— UI 上會標「DEMO 模擬回覆」。
唯一保留的真機制：propose_run（Claude 只能提議，UI 出確認卡，人按才跑）—— Demo 也走同一條路。
"""
from __future__ import annotations

import re
import time

from flask import Blueprint, Response, request, stream_with_context

from collect.case_index import build_or_load
from core import run_index
from core.bug_index import build_bug_index
from core.claude_session import available as claude_available
from core.claude_session import ask as claude_ask
from core import session_compact
from core.registry import get_registry
from web_ui.api import fail, ok
from web_ui.api.knowledge import _memoize
from core import worktree
from web_ui.api.sessions import (append_message, get_meta, mark_done,
                                 mark_running, note_tool, save_meta)

bp = Blueprint("chat", __name__)


#: MCP 的提議工具名（`--mcp-config` 註冊的 server 名會變成前綴）
_PROPOSE_SUFFIX = "propose_run"


def _as_proposal(ev: dict) -> dict | None:
    """tool 事件 → 提議（如果那是 `propose_run` 的話）。

    ★ 2026-08-24 補上的斷鏈：前端讀 `done` 事件的 `proposal`，
      而後端從來沒有產生過那個欄位 —— **確認卡因此從未出現過**。
      而 `perf` 任務唯一的產出就是提議。

    ⛔ 提議仍然只是提議 —— 平台不會替人執行（`ARCHITECTURE.md` 決策 8）。
    """
    if not str(ev.get("name") or "").endswith(_PROPOSE_SUFFIX):
        return None
    a = ev.get("input") or {}
    tid, cid = a.get("tool_id"), a.get("command_id")
    if not tid or not cid:
        return None
    spec = get_registry().tools.get(tid)
    cmd = spec.command(cid) if spec else None
    return {
        "tool_id": tid, "tool_name": spec.name if spec else tid,
        "command_id": cid, "command_label": (cmd or {}).get("label") or cid,
        "params": a.get("params") or {},
        "selection": a.get("selection") or [],
        "reason": a.get("reason", ""),
        "danger": ((cmd or {}).get("danger") or (spec.danger if spec else {}) or {}).get("level", "low"),
    }


def _tool_label(ev: dict) -> str:
    """工具名 → 紀錄用的標籤。`Skill` 展開成 `Skill:<名稱>`，其餘原樣。

    ⭐ 「skill 是平台的大腦」，所以**載了哪一支**是最該留的紀錄之一 ——
       而在這之前它是唯一查不到的（只記工具名，要翻 claude 的原生 transcript）。
    ⛔ 只展開 `Skill`：`Bash` 的指令、`Write` 的內容可能含帳密或大量文字，
       記進 `messages.jsonl` 就是多開一個外洩面。
    """
    name = ev.get("name") or ""
    if name != "Skill":
        return name
    got = (ev.get("input") or {}).get("skill")
    return "Skill:%s" % got if got else name


def _verify_written(draft: dict, paths: list) -> dict:
    """session 已經寫好的檔案 —— 驗收而不是落檔。

    ⛔ **收不到不還原** —— 檔是 session 寫的、它自己跑過，還原等於把成果丟掉。
       大聲回報，由人決定（與「平台代寫」那條路的處置刻意不同）。
    """
    import os

    from core import case_writer
    from core.paths import REPO_ROOT
    ok, collected, nodeids, errs = True, 0, [], []
    for rel in paths:
        p = rel if os.path.isabs(rel) else os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        if not os.path.exists(p):
            ok = False
            errs.append("%s：session 說寫在這裡，但檔案不存在" % rel)
            continue
        r = case_writer.collect_check(p)
        if not r["ok"]:
            ok = False
            errs.append("%s：collect 不到 —— %s" % (rel, (r.get("error") or "")[:200]))
            continue
        collected += r["collected"]
        nodeids += r["nodeids"]
    return {"ok": ok, "path": paths[0] if paths else "", "paths": paths,
            "collected": collected, "nodeids": nodeids, "errors": errs,
            "by_session_files": True, "restored": False,
            "warnings": (["⚠️ 這批是 session 自己寫進 repo 的（邊寫邊測），"
                          "平台沒有覆寫也沒有還原 —— 出問題要人處理"] if ok else []) + errs}


def _verify_run(nodeids, runs=None) -> dict:
    """新寫入的案例**真的跑一次**，回 {run_id} 或 {skipped: 原因}。

    ⛔ `--collect-only` 只證明「語法對、import 得到、收得到」——
       **證明不了跑起來會過**，而那才是「案例寫好了」的意思。
       在這之前，`verified: yes` 是 session 自己說的、沒有任何一步查證
       （2026-08-26 使用者問「案例生成過程中，沒有去做測試嗎？」）。

    ⭐ 走 `manager.start()` 而不是自己 `subprocess.run`：本函式在**對話回合裡**被呼叫，
       22 條 UI 案例會把回合擋死；run 機制非同步，還附帶進度、log、allure 與併發控制。
    ⚠️ 它會真的開瀏覽器操作 QAT（CLAUDE.md §5 已預先授權，session 剛才也做過同樣的操作）。
    ⛔ 任何失敗都只回報、不拋 —— 檔已經寫好了，跑不跑得起來是另一件事。
    """
    if not nodeids:
        return {"skipped": "沒有 nodeid 可跑"}
    try:
        from core.registry import get_registry
        from runner import manager
        spec = get_registry().tools.get("ui_tests")
        if not spec:
            return {"skipped": "registry 裡沒有 ui_tests"}
        cmd = next((c for c in spec.commands if c.get("id") == "run_cases"), None)
        if not cmd:
            return {"skipped": "ui_tests 沒有 run_cases 命令"}
        # ⭐ 把 session 宣告的 `known_fail` 放進備註 —— 人看 run 結果時要對照得到
        #    「它說會紅的是這幾條」。⛔ 平台不代替人判定紅得對不對。
        kf = "；".join(r.get("known_fail") for r in (runs or []) if r.get("known_fail"))
        remark = "新寫入案例的首次驗證（%d 條）" % len(nodeids)
        if kf:
            remark += "｜session 宣告本來就該紅：%s" % kf
        st = manager.start(spec, cmd, {}, selection=list(nodeids), remark=remark)
        return {"run_id": st.get("run_id"), "count": len(nodeids)}
    except Exception as e:                  # noqa: BLE001
        # ⚠️ 併發被擋（別的 run 正在跑）也走這裡 —— 講出原因，不要靜靜地不跑。
        return {"skipped": "%s: %s" % (type(e).__name__, str(e)[:160])}


def _absorb_drafts(sid: str, meta: dict, text: str) -> dict:
    """★ 動線的最後一段：把回覆裡的草稿區塊存進草稿倉。

    ⚠️ 沒有這一步，「草稿／寫檔兩段式」在**最後一步斷掉** ——
       session 交出格式完全正確的草稿，而 `/api/bug-drafts` 回 0，
       產出只活在對話文字裡（2026-08-23 範本實跑 CRUX 時實測到）。

    ⛔ 只對 `writes == "draft"` 的任務 session 做 —— 一般對話不該無意間
       產出草稿（那會讓「待落單」清單塞滿閒聊的殘渣）。
    ⛔ 解析失敗一律吞掉不影響對話 —— 草稿是加值，不是對話的前提。
    """
    if (meta or {}).get("writes") != "draft":
        return {}
    try:
        from core import draft_parse
        got = draft_parse.absorb(sid, (meta or {}).get("product") or "", text)
    except Exception:                       # noqa: BLE001
        return {}
    # ⭐ 低風險的產出**自動落檔**（2026-08-23 使用者裁示後改）——
    #    交接檔附加列／機制文件附加節／驗證報告都是「錯了刪掉就好」，
    #    要人一筆筆按只是把 skill 已經定好的規範再問一次。
    #    ⛔ 仍要人按的只有兩種：**Bug 落單**（燒永不回收的 ID）與
    #       **機制文件整檔覆寫**（蓋掉別人寫的內容）。
    # ⭐ session 判定的缺陷**自動開單** —— 人的角色是在 Bug 列表檢視，
    #    不是審核未完成的任務（2026-08-23 使用者裁示）。
    #    ⛔ run 失敗來源仍留草稿（測試失敗 ≠ 缺陷）。
    if got.get("bugs"):
        try:
            from web_ui.api.bugs_file import auto_file_session_bugs
            res = auto_file_session_bugs(sid)
            got["filed"] = [r for r in res if r.get("ok")]
            got["bugs_pending"] = [r for r in res if r.get("skipped")]
        except Exception:                   # noqa: BLE001
            pass
    # ⭐ 案例也自動落檔 —— 人到**案例瀏覽器**的「新寫入待確認」逐份看過。
    #    ⛔ 安全網還在：`case_writer.commit()` 會真的跑 `--collect-only`，收不到就自動還原。
    if got.get("cases") and got.get("spec_draft_id"):
        try:
            from core import case_writer, spec_draft
            d = spec_draft.get(got["spec_draft_id"])
            # ★ session 自己寫好並跑過的（`wrote`）→ **不覆蓋**，改成驗收。
            #   ⛔ 再 commit 一次會用草稿的 `code` 蓋掉它調到綠燈的那份
            #      —— 邊寫邊測的成果就沒了（2026-08-26 使用者裁示比照終端機 session）。
            wrote = sorted({c["wrote"] for c in (d or {}).get("cases") or [] if c.get("wrote")})
            res = (_verify_written(d, wrote) if wrote
                   else (case_writer.commit(d) if d else {"ok": False,
                                                          "errors": ["找不到案例草稿"]}))
            if res.get("ok"):
                # ⚠️ `at` 一定要記 —— 案例瀏覽器的「新寫入待確認」用它排序，
                #    少了它整批會沉到清單底部（人最該先看的反而最難看到）。
                d.setdefault("committed", []).append(
                    {"path": res["path"], "collected": res.get("collected"),
                     "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                spec_draft.save(d)
                # 索引重建，讓新案例當場出現在案例瀏覽器
                try:
                    from adapters import get_adapter
                    from core.registry import get_registry
                    spec = get_registry().tools.get("ui_tests")
                    if spec:
                        get_adapter(spec).list_cases(refresh=True)
                except Exception:           # noqa: BLE001
                    pass
                res["verify_run"] = _verify_run(res.get("nodeids"),
                                                got.get("runs") or [])
                res["runs"] = got.get("runs") or []
            got["cases_written"] = res
        except Exception as e:              # noqa: BLE001
            got["cases_written"] = {"ok": False, "errors": [str(e)]}
    if got.get("docs"):
        try:
            from core import doc_draft
            # ⛔ **只能呼叫一次** —— 它會真的寫檔（report 還走 `--reserve` 建檔），
            #    叫兩次就寫兩份。
            res = doc_draft.auto_commit_all({"kind": "session", "id": sid})
            got["written"] = [r for r in res if r.get("ok")]
            got["needs_review"] = [r for r in res if r.get("skipped")]
            got["write_failed"] = [r for r in res
                                   if not r.get("ok") and not r.get("skipped")]
        except Exception:                   # noqa: BLE001
            pass
    # ⛔ 自動落檔之後一定要清索引快取 —— 否則人切到 Bug 列表／待辦／案例
    #    看到的是最多 60 秒前的舊資料，等於「落了檔卻看不到」。
    if any(got.get(k) for k in ("filed", "written", "cases_written")):
        try:
            from web_ui.api.knowledge import invalidate
            invalidate("bugs", "todos", "knowledge")
        except Exception:                   # noqa: BLE001
            pass
    return got


def _timeout_kw(meta: dict) -> dict:
    """任務帶來的時間盒（秒）。⚠️ 沒有就**不要傳** —— 傳 None 會蓋掉預設值。"""
    sec = (meta or {}).get("timeout_sec")
    return {"timeout": int(sec)} if sec else {}




@bp.post("/api/chat/<sid>")
def chat(sid):
    m = get_meta(sid)
    if not m or m.get("deleted"):
        return fail("找不到 session", 404)
    if m.get("state") != "active":
        return fail("session 已關閉，請先續接", 409)
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("空訊息")
    append_message(sid, "user", text)
    mark_running(sid, text)          # ⭐ 讓總覽的「運行中」看得到它（2026-08-24）
    # ⭐ 跑之前先記下工作區的樣子 —— session 有 shell 之後，它直接改的檔
    #    草稿模型完全看不見；靠前後比對補上（見 `core/worktree.py`）。
    _before = worktree.snapshot()
    okay, why = claude_available()
    if not okay:
        return fail(why, 503)          # 503：服務暫時不可用（不是 501 未實作）
    # ★ 邊界壓縮（2026-08-26）—— 就在把訊息交給 claude 之前。
    #   ⚠️ 種子**只前置到送出的提示**，不寫進訊息紀錄：那是給 claude 的
    #     工作記憶，不是人講的話（寫進去的話對話畫面會多出好幾千字）。
    seed, _note = _take_seed(sid, m)
    prompt = seed + text
    parts, tools, meta, err = [], [], {}, ""
    proposal = None
    # ⚠️ `allowed_tools` 一定要傳 —— 不傳的話任務宣告的 MCP 是「填了不生效」
    #    （2026-08-23 範本端到端驗收：探索任務拿不到瀏覽器）。
    for ev in claude_ask(prompt, session_id=sid, model=m.get("model"),
                         resume=m.get("claude_session_id"),
                         allow_tools=m.get("allowed_tools") or None,
                         **_timeout_kw(m)):
        if ev["type"] == "text":
            parts.append(ev["text"])
        elif ev["type"] == "tool" and ev["name"] != "_init":
            tools.append(_tool_label(ev))
            proposal = _as_proposal(ev) or proposal
        elif ev["type"] == "tool":
            # ⭐ `_init` 一起來就記住 claude 那側的 session id ——
            #    **被殺的程序沒有 done 事件**，只在 done 裡記的話，
            #    逾時之後就接不回前文了（2026-08-23 實跑逾時抓到）。
            _remember_claude_session(sid, ev.get("input") or {})
        elif ev["type"] == "done":
            meta = ev
        elif ev["type"] == "error":
            # ⛔ **不可以直接 return** —— 前面已經收到的文字會一個字都不留。
            #    逾時是最貴的失敗模式（跑了幾十分鐘），把走到一半的產出丟掉
            #    等於那段時間白花。SSE 路徑本來就會保留，兩條路要一致。
            err = ev["message"]
            break
    _remember_claude_session(sid, meta)
    text = "".join(parts)
    if err:
        # 產出先留著，錯誤附在後面 —— 人才看得出「這是被中斷的半份」
        text = (text + ("\n\n---\n⚠️ " + err) if text else err)
    text = text or "（沒有輸出）"
    msg = append_message(sid, "assistant", text,
                         tools=tools, usage=meta.get("usage"))
    got = _absorb_drafts(sid, m, text)
    got["changed"] = worktree.changed_since(_before)
    if err and not parts:
        return fail(err, 502)               # 真的什麼都沒產出才算失敗
    mark_done(sid, got, proposal=proposal)     # ⭐ 收尾 ＋ 留一筆待確認
    return ok(message=msg, drafts=got, error=err or None, proposal=proposal)


def _compact_plan(m):
    """便宜的預判（只讀 transcript 檔尾）—— 讓 SSE **先**送出進度事件。

    ⛔ 沒有這一支的話，只能等 `_compact_if_needed` 跑完才知道有沒有壓縮，
       而那一步要跑一整回合摘要（509k 的 context 實測一分多鐘），
       期間畫面完全靜止、看起來像卡死（2026-08-26 首次實跑抓到）。
    """
    try:
        return session_compact.plan(m)
    except Exception:                           # noqa: BLE001
        return None


def _compact_if_needed(sid, m, p=None):
    """★ 邊界壓縮：回 `(要前置的種子, 給人看的一句話)`；不壓縮時回 `("", "")`。

    ⚠️ **會就地改 `m`** —— 壓縮成功時把 `claude_session_id` 清成 None，
       於是後面那句 `resume=m.get("claude_session_id")` 自然就開新的了。
       兩條路徑（非串流／SSE）都靠這個副作用，不必各改一次。

    ⛔ 失敗一律回 ""（見 `session_compact` 紀律 1）—— 照常 `--resume`。
    """
    try:
        p = p or session_compact.plan(m)
        if not p:
            return "", ""
        # ⛔ **不可以傳 `save_meta`** —— `m` 是本輪開頭的快照，而 `append_message`
        #    與 `mark_running` 已經各自「重讀→改→存」過了。整份存回去會蓋掉
        #    `activity="running"` 與 `message_count`，而 `note_tool` 檢查
        #    `activity != "running"` 就直接 return → **整輪的工具進度都不會記錄**。
        #    （`commit` skill §8.4 記載的先讀後寫競態，這裡踩到同一顆。）
        seed = session_compact.maybe_compact(sid, m, ask=claude_ask, save=None)
        if not seed:
            return "", ""
    except Exception:                           # noqa: BLE001
        return "", ""                           # 壓縮是加值，不能讓對話掛掉
    try:
        _persist_compact(sid, m, seed)
    except Exception:                           # noqa: BLE001
        # ⛔ **一定要還原 `m`** —— `maybe_compact` 已經把 `claude_session_id`
        #    清成 None 了。就這樣回 "" 的話，這一輪會用 `resume=None` 開一個
        #    **零脈絡**的新 session，而種子也沒落檔 —— 正好就是這次要修的缺陷②，
        #    只是換成由「落檔失敗」觸發（2026-08-26 冒煙測試當場抓到）。
        #    ⭐ 白花一次摘要回合，換「照常 --resume 舊 session」，這筆划算。
        m["claude_session_id"] = m.get("compacted_from")
        return "", ""
    return seed, ("🗜️ 換一份較短的工作記憶（context 已達 %dk，門檻 %dk）"
                  % (p["tokens"] // 1000, p["threshold"] // 1000))


#: 壓縮會寫進 meta 的欄位（**只有這幾個**，其餘一律以磁碟上的為準）
_COMPACT_KEYS = ("compact_count", "compacted_at_tokens", "compacted_from",
                 "claude_session_id")


def _persist_compact(sid, m, seed):
    """把壓縮結果落進 meta —— **重讀後只改自己那幾欄**（缺陷①）。

    ⭐ `pending_seed` 是缺陷②的解：種子只前置到那一則提示，
       若該回合在 `_init` 之前就死掉，cid 記不到、種子也沒了，
       下一則就會開一個**零脈絡**的新 session。存起來，接上了才清。
    """
    mm = get_meta(sid) or {}
    for k in _COMPACT_KEYS:
        mm[k] = m.get(k)
    mm["pending_seed"] = seed
    save_meta(mm)
    # ⚠️ 摘要是這次交接的唯一產物 —— 不留下來的話，交接漏了什麼就無從查證。
    #    ⛔ 存進 messages 而不是 meta：meta 每輪都整份讀寫，塞長文會愈來愈慢。
    summary = (m.get("last_summary") or "").strip()
    if summary:
        append_message(sid, "system",
                       "🗜️ **換了一份較短的工作記憶**（壓縮前 %s token）。"
                       "以下是交給接手那一段的摘要：\n\n%s"
                       % (m.get("compacted_at_tokens"), summary))


def _take_seed(sid, m, p=None):
    """本輪要前置的種子：這次壓縮產生的，或**上次沒送達**的（缺陷②）。"""
    seed, note = _compact_if_needed(sid, m, p)
    if seed:
        return seed, note
    if not m.get("claude_session_id") and m.get("pending_seed"):
        return m["pending_seed"], "🗜️ 沿用上一次的接手摘要（上一輪沒送達）"
    return "", ""


def _remember_claude_session(sid, meta):
    """記住 claude 那一側的 session id，下一則訊息才接得上前文。

    ⚠️ 兩個 session id 是不同東西：平台的 `sid` 是我們自己的檔案目錄，
      claude 的是它自己的對話狀態。不記住的話每一句都是全新的對話。
    """
    cid = (meta or {}).get("session_id")
    if not cid:
        return
    mm = get_meta(sid) or {}
    # ⭐ 接上新 session ＝ 種子已經送達，可以清掉了（缺陷②）。
    #   ⛔ 在這之前不能清 —— 這一輪若死在半路，下一輪還要靠它。
    if mm.get("claude_session_id") != cid or mm.get("pending_seed"):
        mm["claude_session_id"] = cid
        mm.pop("pending_seed", None)
        save_meta(mm)


@bp.route("/api/chat/<sid>/stream", methods=["GET", "POST"])
def chat_stream(sid):
    """SSE 串流：一邊產生一邊送，不必等整段講完。

    ⚠️ 原本是 `time.sleep(0.4)` 後一次回傳。長回答（尤其它會先查好幾個 MCP 工具）
      在非串流下要等十幾秒，畫面完全沒有反應。

    ⛔ **一定要收 POST** —— 任務的提示有兩千多字，塞進 query string
       之後 URL 破四千字元、直接 500，於是按下任務的「開始」等於什麼都沒發生
       （2026-08-23 UI 走查；先前全部用非串流 API 驗，那條路不經過 query）。
    """
    m = get_meta(sid)
    if not m or m.get("deleted"):
        return fail("找不到 session", 404)
    if m.get("state") != "active":
        return fail("session 已關閉，請先續接", 409)
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or request.args.get("text") or "").strip()
    if not text:
        return fail("空訊息")
    append_message(sid, "user", text)
    mark_running(sid, text)          # ⭐ 同上；⛔ 收尾在 `guarded()` 的 finally
    _before = worktree.snapshot()    # ⭐ 同上：這一輪動了哪些檔，要看得見
    # ⛔ **閉包內不可以再對 `text` 賦值** —— 那會讓它變成區域變數，
    #    於是迴圈開頭讀外層的 `text` 直接 `UnboundLocalError` → 500。
    #    ⚠️ 這條路**從來沒有成功過**：先前 GET 的 URL 太長也是 500，
    #    前端每次都靜默退回非串流，所以沒有人發現串流其實是壞的
    #    （2026-08-23 UI 走查才挖出來）。
    def gen(prompt=text, _state=None):
        okay, why = claude_available()
        if not okay:
            yield _sse({"type": "error", "message": why})
            return
        # ★ 邊界壓縮 —— 放在 `gen()` 裡面，而且**進度事件要先送**。
        #   ⛔ 2026-08-26 首次實跑抓到：先前是壓縮跑完才送事件，於是整段
        #      壓縮期間畫面完全靜止（實測 509k 的 context 跑了一分多鐘）——
        #      而「畫面完全沒有反應」正是這條路當初改成串流要解決的問題。
        #   ⚠️ `_compact_plan` 只讀 transcript 檔尾，很便宜，可以先問一次。
        _p = _compact_plan(m)
        if _p:
            yield _sse({"type": "tool", "name": (
                "🗜️ context 已達 %dk（門檻 %dk）—— 正在換一份較短的工作記憶。"
                "這一步要先跑一回合摘要，請稍候"
                % (_p["tokens"] // 1000, _p["threshold"] // 1000))})
        seed, note = _take_seed(sid, m, _p)
        if seed:
            yield _sse({"type": "tool", "name": note})
            prompt = seed + prompt
        elif _p:
            # ⭐ 沒成功也要講 —— 否則畫面只會停在「正在換」，看起來像卡死。
            yield _sse({"type": "tool", "name":
                        "⚠️ 換工作記憶沒成功 —— 照原本的方式繼續，任務不受影響"})
        st = _state if _state is not None else {"parts": [], "tools": [],
                                                "meta": {}, "saved": [], "proposal": None}
        parts, tools, saved = st["parts"], st["tools"], st["saved"]
        meta = st["meta"]
        for ev in claude_ask(prompt, session_id=sid, model=m.get("model"),
                             resume=m.get("claude_session_id"),
                             allow_tools=m.get("allowed_tools") or None,
                             **_timeout_kw(m)):
            if ev["type"] == "text":
                parts.append(ev["text"])
            elif ev["type"] == "tool" and ev["name"] != "_init":
                tools.append(_tool_label(ev))
                # ⚠️ 用 `st` 不是 `_state` —— 後者可能是 None（見上面的 fallback）
                p2 = _as_proposal(ev)
                if p2:
                    st["proposal"] = p2
                # ⭐ 工具動作就是 session 的「進度」—— session 沒有可預估的總量，
                #    而「它現在在讀檔／開瀏覽器／載 skill」正是人想知道的事。
                try:
                    note_tool(sid, ev["name"])
                except Exception:       # noqa: BLE001 —— 進度壞掉不可以影響任務本身
                    pass
            elif ev["type"] == "tool":
                _remember_claude_session(sid, ev.get("input") or {})
            elif ev["type"] == "done":
                meta = ev
                # ⭐ 把提議掛上 `done` —— 前端的確認卡讀的就是這裡（先前一直是 undefined）
                if st.get("proposal"):
                    ev = {**ev, "proposal": st["proposal"]}
                    meta = ev
                if _state is not None:
                    _state["meta"] = ev
            yield _sse(ev)
        _remember_claude_session(sid, meta)
        got = _persist(parts, tools, meta, saved)
        # ⚠️ 案例草稿與「自動寫了什麼」也要送 —— 先前條件只看 bugs／docs，
        #    `write_cases` 那種只產案例的任務，前端什麼都收不到（2026-08-23）。
        if any(got.get(k) for k in ("bugs", "docs", "cases", "written",
                                    "needs_review", "write_failed",
                                    "filed", "bugs_pending", "cases_written")):
            yield _sse({"type": "drafts", **got})

    def _persist(parts, tools, meta, saved):
        """把已經產出的內容存下來。**只做一次**。

        ⛔ 這一段一定要在 `finally` 也跑得到 —— client 斷線時
           generator 收到 `GeneratorExit`，迴圈後面那幾行永遠不會執行，
           於是跑了幾十分鐘的產出**一個字都不留**（2026-08-23 實測：
           我在任務跑到一半重啟平台，那一輪整段消失）。
        """
        if saved:
            # ⚠️ 已經存過就把**上次的結果**回去 —— `guarded()` 的 finally 要靠它
            #    寫「待確認」。回 `{}` 的話正常結束的那一輪會沒有產出摘要
            #    （2026-08-24 接狀態時踩到）。
            return saved[0] if isinstance(saved[0], dict) else {}
        saved.append(True)
        reply = "".join(parts) or "（沒有輸出）"
        append_message(sid, "assistant", reply,
                       tools=tools, usage=(meta or {}).get("usage"))
        got_ = _absorb_drafts(sid, m, reply)
        # ⭐ session 用 shell 直接改的檔，草稿模型看不見 —— 靠前後快照補上
        got_["changed"] = worktree.changed_since(_before)
        saved[0] = got_                 # 讓重入時回得出同一份
        return got_

    def guarded():
        """把 `gen()` 包起來，斷線時仍然落檔。"""
        state = {"parts": [], "tools": [], "meta": {}, "saved": [], "proposal": None}
        try:
            for chunk in gen(_state=state):
                yield chunk
        finally:
            # 正常結束時 gen 自己已經存過（`saved` 有值），這裡就不會重複
            got = _persist(state["parts"], state["tools"], state["meta"],
                           state["saved"])
            # ⛔ 收尾**一定要在 finally** —— client 斷線時 generator 收到
            #    `GeneratorExit`，迴圈後面永遠不會執行，狀態會**永遠卡在 running**
            #    （與 `_persist()` 同一條理由）。
            try:
                mark_done(sid, got or {}, proposal=state.get("proposal"))
            except Exception:           # noqa: BLE001
                pass

    return Response(stream_with_context(guarded()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(obj):
    import json as _j
    return "data: %s\n\n" % _j.dumps(obj, ensure_ascii=False)
