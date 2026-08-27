"""/api/drafts/* —— 案例草稿的儲存、產碼與落檔。

## ⚠️ 2026-08-24：`#/require` 已移除，這裡的角色變了

原本這支檔服務的是「需求 → 案例清單 → 人工調整 → 產碼 → 寫檔」那一頁。
使用者裁示「**需求頁面直接移除，案例草稿確認等於多了一個步驟**」之後，
**寫檔改由 `chat.py` 在 session 交出草稿的當下自動執行**，而人的確認移到
案例瀏覽器的「新寫入待確認」（`GET /api/case-writes`）。

於是 `POST /api/drafts`、`PUT .../cases`、`POST .../code`、`POST .../commit`
**目前沒有 UI 呼叫端**。刻意保留，因為：

· `commit`／`code` 是 `case_writer` 的 HTTP 入口 —— 腳本與 MCP 都可能用到，
  而它們的行為（寫檔 → 真的跑 `--collect-only` → 收不到就還原）是對的
· 移除等於把「不經 session 也能落一批案例」這條路封死，而那是範本情境的退路
  （`claude.exe` 沒裝的人）

⛔ 但**不要再為它們加 UI** —— 那就是被移掉的那一頁。
"""
from __future__ import annotations

import time

from flask import Blueprint, request

from adapters import get_adapter
from core import case_writer, spec_draft
from core.pom_index import build_pom_index, flat_methods
from core.registry import get_registry
from web_ui.api import fail, ok

bp = Blueprint("drafts", __name__)


def _code_generator(req):
    """產碼要用哪一支。

    ★ 預設 **claude** —— 使用者裁示「由 session 依照清單項目去生成自動化測試案例」。
      規則式仍留著當**退路**：`?generator=rulebased`，以及 `claude.exe` 沒裝時。
      ⛔ 不要因為慢就偷偷退回規則式 —— 那會讓人以為「Claude 寫的」而其實不是，
         判準的可信度完全不同。要退回就明講。
    """
    from generators import get_generator
    want = (req.args.get("generator") or "").strip() or "claude"
    try:
        return get_generator(want)
    except ValueError:
        return get_generator("rulebased")


@bp.get("/api/drafts")
def list_drafts():
    return ok(drafts=spec_draft.recent(int(request.args.get("limit", 20))))


@bp.get("/api/case-writes")
def case_writes():
    """**已寫入 `tests/` 的案例批次**，新的在前。

    ★ 這是「自動寫檔」的另一半：檔案自己會寫進去，但**沒有人看過**
      等於沒有品質保證。這份清單就是人逐批看過去的地方
      （`#/cases` 的「新寫入待確認」）。

    ⚠️ 一個 draft 可能 commit 過**很多次**（重跑任務、改完再寫）——
       每一次都是一列，因為每一次的內容都不同，確認狀態也該分開。
       但**同一個檔案路徑**只認最後一次：`acks` 以路徑為鍵，
       而檔案裡就只有最後那一版。
    """
    import os

    from core import acks, spec_draft
    from core.paths import REPO_ROOT
    rows, seen = [], set()
    for meta in spec_draft.recent(int(request.args.get("limit", 40))):
        if not meta.get("committed"):
            continue
        # ⚠️ `recent()` 列的是**目錄裡的任何 .json**，而 `get()` 對不合法的
        #    draft_id 直接拋 `ValueError` —— 手動放進去的檔、舊格式的檔，
        #    都會讓**整支端點 500**（畫面上就是「新寫入待確認」整塊消失）。
        #    一份壞掉的草稿不該拖垮整份清單。
        try:
            d = spec_draft.get(meta["id"]) or {}
        except ValueError:
            continue
        cases = [{"id": c.get("id"), "title": c.get("title"),
                  "verified": c.get("verified") or "no",
                  "confidence": c.get("confidence"), "markers": c.get("markers") or [],
                  "note": c.get("note")} for c in (d.get("cases") or [])]
        for w in reversed(d.get("committed") or []):
            path = w.get("path")
            if not path or path in seen:      # 同一個檔只留最新那一次
                continue
            seen.add(path)
            # ⚠️ **檔案沒了就不列** —— draft 是永久紀錄，案例檔卻會被刪、被搬
            #    （demo 目錄整個移除過、驗證用的臨時案例會被清掉）。
            #    列一個點下去只會拿到 404 的項目，比不列更糟。
            if not os.path.isfile(os.path.join(REPO_ROOT, *path.split("/"))):
                continue
            rows.append({
                "path": path, "collected": w.get("collected"), "at": w.get("at"),
                "draft_id": d.get("id"), "title": d.get("title"),
                "product": d.get("product"), "generated_by": d.get("generated_by"),
                "source_ref": d.get("source_ref"), "cases": cases,
                # ⭐ 這一批有幾條是**沒在站台上跑過**的 —— 人最該先看那幾條
                "unverified": sum(1 for c in cases if c.get("verified") != "yes"),
            })
    # ⚠️ **`at` 會撞名** —— `acks` 的 `at` 是「確認時間」，而這一列的 `at` 是
    #    「寫檔時間」。直接 `update` 會被空字串洗掉，畫面上寫入時間整欄消失
    #    （而清單正是靠它排序的）。改名成 `ack_at` 再併。
    st = acks.status([r["path"] for r in rows])
    for r in rows:
        a = dict(st.get(r["path"]) or {})
        r["acked"] = a.get("acked", False)
        r["stale"] = a.get("stale", False)
        r["ack_at"] = a.get("at", "")
    rows.sort(key=lambda r: (bool(r.get("acked")), r.get("at") or ""), reverse=False)
    rows.reverse()                             # 未確認的在前，各自新的在前
    rows.sort(key=lambda r: bool(r.get("acked")))
    return ok(writes=rows, pending=sum(1 for r in rows if not r.get("acked")))


@bp.post("/api/case-writes/ack")
def ack_case_write():
    """勾選／取消「已確認」。與驗證報告共用 `core/acks.py`。"""
    from core import acks
    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    if not path:
        return fail("缺少 path")
    return ok(**acks.set_ack(path, bool(body.get("acked"))))


@bp.get("/api/drafts/<draft_id>")
def get_draft(draft_id):
    try:
        d = spec_draft.get(draft_id)
    except ValueError as e:
        return fail(str(e))
    return ok(draft=d) if d else fail("找不到 draft", 404)


@bp.delete("/api/drafts/<draft_id>")
def del_draft(draft_id):
    try:
        return ok(deleted=spec_draft.delete(draft_id))
    except ValueError as e:
        return fail(str(e))


@bp.post("/api/drafts")
def create_draft():
    """建一份**空草稿**，讓人自己列案例。

    ★ 2026-08-24 流程重設計後新增。先前這一頁只能靠 `POST /api/drafts/generate`
      生出草稿，而那條路已依使用者裁示移除（「只有交給 session 推導」）。

    ⛔ 沒有這個端點的話，**`claude.exe` 沒裝的人在這一頁一件事都做不了** ——
       那是範本情境的常態（同事可能只想用索引與執行）。
       有了它，他可以「＋手動新增」逐條列，照樣走產碼與寫檔。
    """
    body = request.get_json(force=True, silent=True) or {}
    d = spec_draft.create(
        requirement=(body.get("requirement") or "").strip(),
        product=body.get("product") or "crux",
        source_ref=body.get("source_ref", ""),
        title=body.get("title", ""))
    return ok(draft=d)


@bp.put("/api/drafts/<draft_id>/cases")
def put_cases(draft_id):
    """②：人工檢視／調整／新增後存回。前端是唯一權威，整批覆蓋。"""
    body = request.get_json(force=True, silent=True) or {}
    try:
        d = spec_draft.put_cases(draft_id, body.get("cases") or [])
    except ValueError as e:
        return fail(str(e), 404)
    return ok(draft=d)


@bp.post("/api/drafts/<draft_id>/code")
def code_preview(draft_id):
    """③：產碼預覽（不寫檔）。"""
    d = spec_draft.get(draft_id)
    if not d:
        return fail("找不到 draft", 404)
    # ⭐ 2026-08-24 使用者裁示：「使用者確認沒問題，則**由 session 依照清單項目
    #    去生成自動化測試案例**」—— 產碼一律交給 Claude，不再用規則式拼範本。
    #    ⚠️ 規則式的產出是「既有已驗證程式碼的重組」，全新玩法它生不出來；
    #       而人在這一步已經**確認過清單**了，值得讓它真的讀懂再寫。
    #    ⚠️ 慢：一條案例一次呼叫（實測 12 條約 422 秒）—— 前端要講明並放寬 timeout。
    gen = _code_generator(request)
    try:
        pv = case_writer.preview(d, gen)
    except Exception as e:
        return fail(f"產碼失敗：{e}", 500)
    # ⚠️ 一定要存回 —— `preview()` 把產碼結果快取在 draft 上，不存的話
    #    ④寫檔會再產一次。Claude 供應者是一條案例一次 API 呼叫，
    #    實測 12 條要 422 秒，白白再等一輪（2026-08-23）。
    spec_draft.save(d)
    pv.pop("abs", None)
    return ok(**pv)


@bp.post("/api/drafts/<draft_id>/commit")
def commit(draft_id):
    """④：寫檔 → 真的跑 pytest --collect-only 驗證 → 收不到就還原。"""
    d = spec_draft.get(draft_id)
    if not d:
        return fail("找不到 draft", 404)
    res = case_writer.commit(d, _code_generator(request))
    if res.get("ok"):
        d.setdefault("committed", []).append({"path": res["path"], "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                              "collected": res["collected"]})
        spec_draft.save(d)
        # 案例索引重建，讓新案例當場出現在案例瀏覽器
        try:
            spec = get_registry().tools.get("ui_tests")
            if spec:
                get_adapter(spec).list_cases(refresh=True)
        except Exception:
            pass
    # ⚠️ 這裡原本回 `sandbox=True` —— Demo 沙箱移除後那是**假的**：
    #    案例真的寫進 `tests/<產品>/`，會被索引收進來、會被 pytest 跑到。
    #    回一個已經不成立的旗標，前端就會照著它顯示「這只是沙箱」（2026-08-23）。
    return ok(**res)


@bp.get("/api/pom")
def pom():
    """POM 索引：UI 上讓人看得到「產碼只能呼叫這些方法」。"""
    idx = build_pom_index(refresh=bool(request.args.get("refresh")))
    product = request.args.get("product")
    if product:
        return ok(product=product, methods=flat_methods(product, idx))
    return ok(summary={pid: {"files": len(b["files"]), "classes": b["class_count"],
                             "methods": b["method_count"]}
                       for pid, b in idx["products"].items()},
              total=idx["total_methods"])
