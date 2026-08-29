"""/api/chat —— 對話面板（Demo：規則式假回覆；M6 接真 claude.exe headless session ＋ SSE）。

⚠️ Demo 的回覆是**規則式模板，不是 LLM** —— UI 上會標「DEMO 模擬回覆」。
唯一保留的真機制：propose_run（Claude 只能提議，UI 出確認卡，人按才跑）—— Demo 也走同一條路。
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time

from flask import Blueprint, Response, request, stream_with_context

from collect.case_index import build_or_load
from core import run_index
from core.bug_index import build_bug_index
from core.claude_session import available as claude_available
from core.claude_session import ask as claude_ask
from core import session_compact
from core import tasks
from core.paths import SESSIONS_DIR
from core.proc import kill_tree
from core import session_bus
from core import transcript
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
    _t0 = _utc_now()                 # ⭐ 補救時用來濾掉「上一輪」的段落
    okay, why = claude_available()
    if not okay:
        return fail(why, 503)          # 503：服務暫時不可用（不是 501 未實作）
    # ★ 邊界壓縮（2026-08-26）—— 就在把訊息交給 claude 之前。
    #   ⚠️ 種子**只前置到送出的提示**，不寫進訊息紀錄：那是給 claude 的
    #     工作記憶，不是人講的話（寫進去的話對話畫面會多出好幾千字）。
    seed, _note = _take_seed(sid, m)
    # ⭐ 非任務對話的平台前言（任務那側由 `tasks.render()` 帶）——
    #    ⚠️ 順序是「前言 → 壓縮種子 → 使用者的話」：兩者不會同時出現在第一輪，
    #    但真的同時出現時，規則要在工作記憶之前。
    prompt = _chat_preamble(sid, m) + seed + text
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
    # ⭐ 沒有 `done` ＝ 這一輪不是正常結束（見 `_recover_truncated`）
    #    ⚠️ **有 `err` 也要補救** —— 逾時正是最該撿回產出的情境（跑了幾十分鐘）。
    #    原本寫成 `and not err` 會讓 POST 路徑跳過，而 SSE 路徑照補，兩條路行為不一致。
    truncated = not meta
    if truncated:
        _lost, _trunc_note = _recover_truncated(sid, parts, _t0, had_error=bool(err))
        parts.extend(_lost)
        if _trunc_note:
            err = (err + "\n\n" + _trunc_note) if err else _trunc_note
    text = "".join(parts)
    if err:
        # 產出先留著，錯誤附在後面 —— 人才看得出「這是被中斷的半份」
        text = (text + ("\n\n---\n⚠️ " + err) if text else err)
    text = text or "（沒有輸出）"
    msg = append_message(sid, "assistant", text,
                         tools=tools, usage=meta.get("usage"))
    got = _absorb_drafts(sid, m, text)
    got["changed"] = worktree.changed_since(_before)
    if truncated:
        got["truncated"] = True         # ⭐ 讓「結果確認」也留得住（見 `_output_summary`）
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


def _product_line(m: dict) -> str:
    u"""選了產品才加的那一句：叫它載入該產品的 skill。

    ⭐ 使用者 2026-08-28 裁示：**產品欄選填，不選就是乾淨 session**
      —— 只有 `CLAUDE.md` 與 memory，適合臨時問一件事（近期的非任務對話
      「CRUX-124 確認」「更新知識」都屬這類，套不進任何一支任務）。

    ⛔ 不選時**一個字都不加** —— 「順便提一下有哪些產品」看似無害，
       實際上是替它決定了框架，而那正是使用者要的「乾淨」的反面。
    """
    pid = str(m.get("product") or "").strip()
    if not pid:
        return ""
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if pid in (p.get("id"), p.get("product_id"), p.get("label")):
                skill = p.get("skill")
                name = p.get("product_id") or p.get("label") or pid
                if not skill:
                    return ""          # 虛擬產品（共通）沒有 skill，不硬湊
                return (u"> · 本次的產品是 **%s** —— 請先載入 `/%s`"
                        u"（意圖對照表與必記不變量都在那裡）。\n" % (name, skill))
    except Exception:                   # noqa: BLE001 認不得就不加，別讓前言掛掉
        pass
    return ""


def _chat_preamble(sid: str, m: dict) -> str:
    """**非任務對話**要前置的平台前言（只在起 claude session 的那一輪）。

    ⚠️ 2026-08-27 之前這條路送出的就是「壓縮種子 ＋ 使用者打的字」，
      **一個字的規則都沒有** —— 任務那側靠 `tasks.render()` 帶前言，對話這側沒有對應物。
      實測後果（session `29bc6a46`）：整則回覆與過程敘述都是英文；
      而語言只是最表層的，同一份前言還負責「沒有人能批准你」「git 寫入會被擋」
      「暫存檔寫哪裡」這三件會讓 session 卡住或弄髒 repo 的事。

    ⭐ 判準用 `claude_session_id`（**不是**訊息數）——
      它為空就代表這一輪會開一個全新的 claude session，正好是需要前言的時候；
      而且第一輪失敗（沒拿到 id）時下一輪會自動再送一次，不必另外記旗標。
    """
    if m.get("task_id") or m.get("claude_session_id"):
        return ""
    # 前言裡的 `work/` 路徑要真的存在。正常情況 `api_create_session()` 已經建好了，
    # 這裡只補「改版前就存在的舊 session」。
    # ⛔ **先確認 session 目錄真的在** —— 無條件 makedirs 會讓拿假 sid 的測試
    #    在真的 `logs/sessions/` 底下長出 `x/`、`xyz/`（2026-08-27 實際發生過）。
    #    算字串的函式不該有副作用，這一行是唯一的例外，所以要夾緊。
    d = os.path.join(SESSIONS_DIR, sid)
    if os.path.isdir(d):
        for sub in ("shots", "work"):
            os.makedirs(os.path.join(d, sub), exist_ok=True)
    pre = tasks.CHAT_PREAMBLE.replace("__SID__", sid)
    line = _product_line(m)
    if not line:
        return pre               # ⛔ 沒選產品就一個字都不加（見 `_product_line`）
    # ⚠️ 要接進**同一個引用區塊**裡 —— 前言結尾有一個空行，直接接上去會變成
    #    兩塊分開的 blockquote，讀起來像是另一段話。
    return pre.rstrip("\n") + "\n" + line + "\n"


def _utc_now():
    """UTC ISO（比到秒）。⚠️ 往前留 5 秒的餘裕 —— 兩邊的時鐘不保證同步，
    抓太緊會把這一輪最前面的段落濾掉。"""
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S")


def _recover_truncated(sid, parts, since_utc, had_error=False):
    """**這一輪沒有 `done` 事件**時的補救：回傳 (補回來的段落, 要告訴人的話)。

    ★ 2026-08-27 使用者回報「非任務對話沒有回應任何結果」。查證 session `29bc6a46`：
      claude **寫出了完整的中文結論**（transcript 09:21:40.967Z），
      平台落檔的訊息卻只有工具之間的四句英文旁白、`usage` 是 `null`
      —— `null` ＝ `meta` 空的 ＝ **整輪沒收到 `done`**。Flask 行程沒重啟過。
      也就是：**答案產出了，只是沒走到平台這一側，而平台什麼都沒說。**

    ⛔ 在這之前這是一條**完全靜默**的路：`claude_session.ask()` 只在
       「exit code 非 0 **且** stderr 有東西」時才報錯。乾淨退出卻沒有 result、
       或 client 斷線，兩種都不會有任何訊息 —— 使用者看到最後一句旁白然後沒有下文。

    ⚠️ 放在 `_persist()` 裡（唯一的落檔漏斗），**不是**放在迴圈後面 ——
       client 斷線時迴圈後面的程式碼永遠不會執行，而那正是最需要補救的情境。
    """
    cid = (get_meta(sid) or {}).get("claude_session_id")
    have = "".join(parts)
    lost = []
    for t in transcript.texts_since(cid, since_utc):
        if t and t not in have and t not in lost:
            lost.append(t)
    if had_error:
        # ⛔ 這一輪**已經有錯誤訊息**（逾時、claude 那側報錯）——
        #    再講一次「串流在中途斷了（關掉分頁…）」會把原因說成別的事。
        #    這裡只補「撿回來了」，原因留給那一則錯誤自己講。
        note = (u"⭐ 已從 claude 自己的 transcript 把中止前的最後一段補回來（上面）。"
                if lost else u"")
        return lost, note
    note = (u"⚠️ 這一輪**沒有收到結束訊號** —— 串流在中途斷了"
            u"（關掉分頁、重整、或 claude 那側非正常結束都會這樣）。")
    note += (u"已從 claude 自己的 transcript 把結尾補回來（上面最後一段）。" if lost
             else u"transcript 裡也沒有更多內容，上面就是中止前產出的全部。")
    note += (u"要接下去的話**直接再送一則訊息**（例如「接著剛才的繼續」）"
             u"—— 它會帶著完整脈絡接下去，不必從頭講一次。")
    return lost, note


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


# ── 一條 session ＝ 一條事件匯流排 ＋ 一個佇列 ＋ 至多一個 pump ──────────
#
# ⛔ 2026-08-28 之前是「**一個 POST 自帶一條串流**」，三個症狀同一個根因
#    （產出綁在連線上）：重整就看不到過程、兩個分頁各看各的、
#    同一個 session 不能連送兩則。改成匯流排＋佇列之後三個一起消失。
#
# ⚠️ 佇列**只在記憶體裡**：平台重啟時還沒開跑的那幾則會消失（它們根本還沒送出去），
#    而 `reconcile.on_startup()` 會把卡住的 `running` 收乾淨。
#    ⛔ 不做成落檔的原因：重啟後自動補跑使用者半小時前打的字，比丟掉更難預期。
_PUMP_LOCK = threading.Lock()
#: sid -> {"thread", "inbox": [下一則…], "proc": [Popen…], "st": 這一輪的 state,
#:         "stopped": 被中止}
#: ⭐ **有這一筆 ＝ 這個 session 有人在跑**（`_take_next()` 收工時才移除）。
_PUMPS = {}


def _new_turn_state():
    """一輪的所有中間狀態。⚠️ **每輪都要新的** —— 共用會把上一輪的產出算進來。"""
    return {"parts": [], "tools": [], "meta": {}, "saved": [], "proposal": None,
            "err": "", "proc": [], "t0": _utc_now(), "before": worktree.snapshot()}


def _turn_events(sid, m, prompt, st):
    """跑一輪，逐個 yield SSE 字串。

    ⚠️ 這裡**不決定要送給誰** —— 送給誰是 `session_bus` 的事。
    """
    okay, why = claude_available()
    if not okay:
        yield _sse({"type": "error", "message": why})
        return
    # ★ 邊界壓縮 —— **進度事件要先送**。
    #   ⛔ 2026-08-26 首次實跑抓到：先前是壓縮跑完才送事件，於是整段壓縮期間
    #      畫面完全靜止（實測 509k 的 context 跑了一分多鐘）——
    #      而「畫面完全沒有反應」正是這條路當初改成串流要解決的問題。
    #   ⚠️ `_compact_plan` 只讀 transcript 檔尾，很便宜，可以先問一次。
    _p = _compact_plan(m)
    if _p:
        yield _sse({"type": "notice",
                    "text": ("🗜️ context 已達 %dk（門檻 %dk）—— 正在換一份較短的"
                             "工作記憶。這一步要先跑一回合摘要，請稍候"
                             % (_p["tokens"] // 1000, _p["threshold"] // 1000)),
                    "label": "正在換一份較短的工作記憶"})
    seed, note = _take_seed(sid, m, _p)
    pre = _chat_preamble(sid, m)
    if seed:
        yield _sse({"type": "notice", "text": note, "label": "換好了，接著跑"})
        prompt = seed + prompt
    elif _p:
        # ⭐ 沒成功也要講 —— 否則畫面只會停在「正在換」，看起來像卡死。
        yield _sse({"type": "notice",
                    "text": "⚠️ 換工作記憶沒成功 —— 照原本的方式繼續，任務不受影響",
                    "label": "照原本的方式繼續"})
    prompt = pre + prompt          # ⚠️ 一定要在 if/elif **之後**，否則斷開那條鏈
    parts, tools = st["parts"], st["tools"]
    meta = st["meta"]
    for ev in claude_ask(prompt, session_id=sid, model=m.get("model"),
                         resume=m.get("claude_session_id"),
                         allow_tools=m.get("allowed_tools") or None,
                         _handle=st["proc"], **_timeout_kw(m)):
        if ev["type"] == "text":
            parts.append(ev["text"])
        elif ev["type"] == "tool" and ev["name"] != "_init":
            tools.append(_tool_label(ev))
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
        elif ev["type"] == "error":
            # ⭐ 記下來 —— `_persist_turn()` 要靠它判斷「補救的說法該講哪一種」
            st["err"] = ev.get("message") or "?"
        elif ev["type"] == "done":
            # ⭐ 把提議掛上 `done` —— 前端的確認卡讀的就是這裡
            if st.get("proposal"):
                ev = {**ev, "proposal": st["proposal"]}
            meta = ev
            st["meta"] = ev
        yield _sse(ev)
    _remember_claude_session(sid, meta)
    got = _persist_turn(sid, m, st)
    # ⭐ 把補回來的結尾與「這一輪被截斷」一起送出去
    for _t in got.get("recovered") or []:
        yield _sse({"type": "text", "text": _t})
    if got.get("stream_note"):
        yield _sse({"type": "error", "message": got["stream_note"]})
    # ⚠️ 案例草稿與「自動寫了什麼」也要送 —— 先前條件只看 bugs／docs，
    #    `write_cases` 那種只產案例的任務，前端什麼都收不到（2026-08-23）。
    if any(got.get(k) for k in ("bugs", "docs", "cases", "written",
                                "needs_review", "write_failed",
                                "filed", "bugs_pending", "cases_written")):
        yield _sse({"type": "drafts", **got})


def _persist_turn(sid, m, st):
    """把這一輪已經產出的內容存下來。**只做一次**。

    ⛔ 一定要在 `finally` 也跑得到 —— 這一輪可能被中止、可能死在半路，
       跑了幾十分鐘的產出不能因為收尾沒跑到就全丟。
    """
    saved = st["saved"]
    if saved:
        # ⚠️ 已經存過就把**上次的結果**回去 —— pump 的 finally 要靠它寫「待確認」。
        return saved[0] if isinstance(saved[0], dict) else {}
    saved.append(True)
    parts, meta = st["parts"], st["meta"]
    lost, note, truncated = [], "", not meta
    if truncated:
        lost, note = _recover_truncated(sid, parts, st["t0"],
                                        had_error=bool(st.get("err")))
        parts = list(parts) + lost
    if st.get("interrupted"):
        # ⭐ 一定要在 `lost` **之後** —— 見 `chat_interrupt()` 的說明
        丟掉 = st.get("dropped") or 0
        parts = list(parts) + [
            u"\n\n⛔ **這一輪由使用者中止**（已產出的內容保留在上面）。"
            + (u"排隊中的 **%d 則**也一併丟掉了 —— 上面那幾則使用者訊息**沒有送出去**，"
               u"要的話重送一次。" % 丟掉 if 丟掉 else u"")]
    reply = "".join(parts) or "（沒有輸出）"
    # ⚠️ 警語也要進**落檔的訊息** —— 只送 SSE 的話，等一下重開這個 session
    #    看到的就是一段沒頭沒尾的內容，而且看起來像是它正常講完的。
    if note:
        reply = reply + "\n\n---\n" + note
    append_message(sid, "assistant", reply,
                   tools=st["tools"], usage=(meta or {}).get("usage"))
    got_ = _absorb_drafts(sid, m, reply)
    # ⭐ session 用 shell 直接改的檔，草稿模型看不見 —— 靠前後快照補上
    got_["changed"] = worktree.changed_since(st["before"])
    if truncated:
        got_["truncated"] = True        # ⭐ 讓「結果確認」也留得住
    if note:
        got_["recovered"], got_["stream_note"] = lost, note
    saved[0] = got_
    return got_


def _take_next(sid):
    """取佇列裡的下一則；沒有就**當場交出這個 session 的所有權**。

    ⚠️ 「取下一則」與「登出 pump」必須在同一個鎖裡 —— 否則中間送進來的訊息
       會排進一個正在收工的 pump，然後永遠不會被跑。
    """
    with _PUMP_LOCK:
        p = _PUMPS.get(sid)
        if not p or p.get("stopped") or not p["inbox"]:
            _PUMPS.pop(sid, None)
            return None
        return p["inbox"].pop(0)


def _pump(sid, text):
    """一輪接一輪地跑，直到佇列空掉 —— **與瀏覽器的連線完全無關**。

    ⛔ 2026-08-28 查出的缺陷的正解：先前這段掛在 response generator 上，
       **分頁一重整就整條崩掉** ——
       ① werkzeug 關掉 generator → `GeneratorExit`；
       ② 展開時**內層 `claude_ask()` 的 finally 先跑**（實測順序如此，不是外層先），
          它 `proc.stdout.close()` 之後 `proc.wait()` **卡住**；
       ③ claude 那側不理會 stdout 的 EPIPE，**照樣跑完**（實測還跑了 58 分鐘）；
       ④ 等它結束才輪到落檔，而 `meta` 是空的 → 完整的一輪被標成「串流在中途斷了」。
       實測 session `7a458300` 兩輪都是這樣：平台在第 12 個工具就瞎了，
       claude 那側實際做了 339 個。
    """
    try:
        while text is not None:
            m = get_meta(sid) or {}     # ⚠️ 每輪重讀 —— 上一輪換過 claude_session_id
            st = _new_turn_state()
            # ⭐ 每輪開頭立一個標記並記下序號 —— 中途加入的畫面只補**這一輪**。
            #    ⛔ 補整段 backlog 會把上一輪的事件再畫一次，
            #       而那一輪早就落檔了（畫面會出現兩份同樣的內容）。
            seq0 = session_bus.publish(sid, _sse({"type": "turn_start"}))
            with _PUMP_LOCK:
                p = _PUMPS.get(sid)
                if p is not None:
                    p["st"], p["proc"], p["seq0"] = st, st["proc"], seq0
            try:
                for chunk in _turn_events(sid, m, text, st):
                    session_bus.publish(sid, chunk)
            except Exception as e:      # noqa: BLE001
                # ⛔ 不可以靜默 —— 移進執行緒之前，例外會直接冒到 client。
                #    現在要自己送出去，並且**寫進落檔的訊息**，否則只剩一句
                #    「串流在中途斷了」，把平台自己的 bug 說成使用者重整了頁面。
                import traceback as _tb
                import sys as _s
                _tb.print_exc(file=_s.stderr)
                st["err"] = u"平台這一側出錯：%r" % e
                st["parts"].append(u"\n\n⚠️ 這一輪在**平台這一側**出錯了：%r" % e)
                session_bus.publish(sid, _sse({"type": "error", "message": st["err"]}))
            finally:
                try:
                    got = _persist_turn(sid, m, st)
                except Exception as e:  # noqa: BLE001
                    import sys as _s
                    print("⚠️ chat pump 落檔失敗：%r" % e, file=_s.stderr)
                    got = {}
                # ⛔ 收尾**一定要在 finally** —— 不然狀態會永遠卡在 running
                try:
                    mark_done(sid, got or {}, proposal=st.get("proposal"))
                except Exception:       # noqa: BLE001
                    pass
            text = _take_next(sid)
            if text is not None:
                mark_running(sid, text)
                session_bus.publish(sid, _sse({"type": "notice",
                                               "text": "▶️ 接著跑排隊中的下一則",
                                               "label": "接著跑下一則"}))
    finally:
        # ⛔ 一定要移除 —— 留著的話這個 session 會永遠被判成「有人在跑」，
        #    之後每一則訊息都只會排隊、再也不會開跑。
        with _PUMP_LOCK:
            _PUMPS.pop(sid, None)
        session_bus.publish(sid, _idle())


def _start_or_queue(sid, text):
    """開跑，或排進佇列。回傳 (資訊, 那條 pump 執行緒)。"""
    # ⚠️ 執行緒物件要**在鎖裡就建好並掛上去** —— 先建條目、之後才填 thread 的話，
    #    這兩步之間進來的第二則會拿到 `None`（測試偶發、畫面也少一個把手）。
    with _PUMP_LOCK:
        p = _PUMPS.get(sid)
        if p is not None:
            p["inbox"].append(text)
            n, th = len(p["inbox"]), p.get("thread")
        else:
            th = threading.Thread(target=_pump, args=(sid, text), daemon=True,
                                  name="chat-%s" % sid[:8])
            _PUMPS[sid] = {"thread": th, "inbox": [], "proc": [],
                           "st": None, "stopped": False}
            n = 0
    # ⭐ 排隊的也要先落檔 —— 不然重整之後看不到自己剛剛打了什麼
    append_message(sid, "user", text)
    if n:
        session_bus.publish(sid, _sse({"type": "queued", "n": n, "text": text}))
        return {"queued": n}, th
    mark_running(sid, text)
    th.start()
    return {"started": True}, th


def _relay(sid, q, replay, stop_on_idle):
    """把匯流排的事件轉成 SSE。`stop_on_idle` ＝ 跑完就收線（`/stream` 用）。"""
    idle = _idle()
    try:
        for seq, payload in replay:
            yield "id: %d\n%s" % (seq, payload)
        while True:
            try:
                item = q.get(timeout=20)
            except queue.Empty:
                yield ": ping\n\n"     # ⭐ 沒有心跳，閒置久了連線會被中間層砍掉
                continue
            if item is None:           # session 關掉了
                break
            seq, payload = item
            yield "id: %d\n%s" % (seq, payload)
            if stop_on_idle and payload == idle:
                break
    finally:
        session_bus.unsubscribe(sid, q)


def _sse_response(gen_, sid, q):
    """⛔ 一定要掛 `call_on_close` 退訂 —— `_relay()` 的 finally **不保證會跑**：
    response body 一次都沒被讀過時（連線在讀之前就沒了），那個 generator
    從未啟動，`close()` 不會執行 finally，於是那個訂閱者永遠留在匯流排上，
    塞滿 2000 個事件才會被丟掉。WSGI 一定會對 response iterable 呼叫 `close()`。
    """
    resp = Response(stream_with_context(gen_), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    resp.call_on_close(lambda: session_bus.unsubscribe(sid, q))
    return resp


def _since_of(sid, req):
    """從哪裡開始補播。

    · 有 `Last-Event-ID`（SSE 自動重連）或 `?since=` → 就從那裡接下去
    · 這個 session **正在跑** → 從**這一輪的開頭**補（中途加入也看得到全程）
    · 沒有在跑 → 從現在開始，**一個字都不補** ——
      ⛔ 補了會與已經落檔的訊息重複，畫面出現兩份一樣的內容。
    """
    raw = req.headers.get("Last-Event-ID") or req.args.get("since") or ""
    if str(raw).isdigit():
        return int(raw)
    with _PUMP_LOCK:
        p = _PUMPS.get(sid)
        seq0 = p.get("seq0") if p else None
    return (seq0 - 1) if seq0 else session_bus.tip(sid)


@bp.route("/api/chat/<sid>/stream", methods=["GET", "POST"])
def chat_stream(sid):
    """送一則訊息並看著它跑（正在跑就排隊，跑完自動接著跑）。

    ⛔ **一定要收 POST** —— 任務的提示有兩千多字，塞進 query string
       之後 URL 破四千字元、直接 500，於是按下任務的「開始」等於什麼都沒發生
       （2026-08-23 UI 走查）。
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
    # ⚠️ **先訂閱再送出** —— 反過來的話，開跑到訂閱之間的事件會整個漏掉
    #    （壓縮提示就在那一段，而它正是最需要立刻看到的東西）。
    q, replay = session_bus.subscribe(sid, since=_since_of(sid, request))
    try:
        _info, th = _start_or_queue(sid, text)
    except Exception:                   # noqa: BLE001
        # ⛔ 這裡炸掉的話 Response 根本沒建出來，`call_on_close` 也就不會掛 ——
        #    那個訂閱者會**永遠**留在匯流排上（而且有訂閱者的匯流排不會被淘汰）。
        session_bus.unsubscribe(sid, q)
        raise
    resp = _sse_response(_relay(sid, q, replay, stop_on_idle=True), sid, q)
    resp.pump = th          # ⭐ 掛出來讓測試等得到那一輪跑完（正式路徑不會用到）
    return resp


@bp.route("/api/chat/<sid>/send", methods=["POST"])
def chat_send(sid):
    """只送訊息，**不帶串流** —— 畫面靠 `/events` 那一條訂閱看。

    ⭐ 這是「同一則事件被畫兩次」的正解：先前 `send()` 每次都開一條新串流，
       同一個面板掛著兩條訂閱（2026-08-28 瀏覽器走查抓到）。
    """
    m = get_meta(sid)
    if not m or m.get("deleted"):
        return fail("找不到 session", 404)
    if m.get("state") != "active":
        return fail("session 已關閉，請先續接", 409)
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("空訊息")
    info, _th = _start_or_queue(sid, text)
    return ok(**info)


@bp.route("/api/chat/<sid>/events")
def chat_events(sid):
    """**只看不送**：訂閱這個 session 的事件。

    ⭐ 這就是「重整之後還看得到過程」與「兩個分頁看到同一份」的那條路 ——
       它不送訊息、也不會因為某一輪跑完就收線。
    """
    m = get_meta(sid)
    if not m or m.get("deleted"):
        return fail("找不到 session", 404)
    q, replay = session_bus.subscribe(sid, since=_since_of(sid, request))
    return _sse_response(_relay(sid, q, replay, stop_on_idle=False), sid, q)


@bp.route("/api/chat/<sid>/interrupt", methods=["POST"])
def chat_interrupt(sid):
    """⛔ 中止這一輪（終端機的 Esc）—— **已經產出的內容照樣留下**。

    ⚠️ 排隊中的訊息一併丟掉並回報數量：中止之後還自動跑下一則，
       是使用者最不會預期的行為。
    """
    with _PUMP_LOCK:
        p = _PUMPS.get(sid)
        if not p:
            return fail("這個 session 現在沒有在跑", 409)
        p["stopped"] = True
        dropped, procs, st = len(p["inbox"]), list(p.get("proc") or []), p.get("st")
        p["inbox"] = []
    if st is not None:
        # ⭐ 讓補救走「已經有錯誤訊息」那一支 —— 否則會補上「串流在中途斷了
        #    （關掉分頁、重整…）」，把使用者自己按的中止說成別的事。
        st["err"] = u"使用者中止"
        # ⛔ 這句話**不能現在就 append** —— 落檔時還會從 transcript 把中止前的
        #    最後一段撿回來接在後面，於是「已中止」會夾在內容中間
        #    （2026-08-28 實測畫面：「已中止…。28 份 .md 檔，逐一讀取前 30 行。」）。
        st["interrupted"] = True
        st["dropped"] = dropped
    for proc in procs:
        try:
            kill_tree(proc.pid, force=True)
        except Exception:               # noqa: BLE001
            pass
    more = u"，並丟掉排隊中的 %d 則" % dropped if dropped else u""
    session_bus.publish(sid, _sse(
        {"type": "error",
         "message": u"⛔ 已中止這一輪%s。要接下去的話直接再送一則。" % more}))
    return ok(dropped=dropped, killed=len(procs))


def _sse(obj):
    import json as _j
    return "data: %s\n\n" % _j.dumps(obj, ensure_ascii=False)


def _idle():
    """全部跑完的訊號。`/stream` 收到就收線；`/events` 只轉發、不收線。

    ⚠️ 用「同一個字串比對」而不是解析 JSON —— 匯流排裡放的是已經序列化好的
       SSE 字串，為了一個控制訊號去解析每一筆，成本與出錯面都不划算。
    """
    return _sse({"type": "idle"})

