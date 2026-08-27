# -*- coding: utf-8 -*-
"""/api/tasks —— 任務啟動器（階段 E-2，2026-08-23）。

用途：按下任務按鈕 → 建一個帶 context 的 session → 送第一則提示 → 導到對話。

    GET  /api/tasks                 列出可用任務（內建 ＋ custom）
    GET  /api/tasks/<id>            單一任務（含欄位定義，供表單渲染）
    POST /api/tasks/<id>/launch     建 session 並回 {session_id, prompt}

⛔ **啟動只建 session、不送訊息** —— 送訊息由前端走 `/api/chat/<sid>/stream`，
   這樣使用者才看得到串流過程，也才有機會在送出前改提示。

⭐ **2026-08-25：session 有 shell 與寫檔了** —— 目標是「做得到與終端機幾乎相同的事」，
   否則它跑不了 `gen_bug_index --next-id`／`stamp_shots.py`／`lint_docs.py`，
   等於做不到 skill 的規範（截圖整批遺失、知識回寫做不完都是這樣來的）。
   邊界改由 `guard/pretool_guard.py`（PreToolUse）守：⛔ git 寫入、⛔ 刪到自己家以外。
   草稿／落檔那條動線仍然保留 —— 它管的是**判斷**（Bug ID 不可回收），不是「能不能寫檔」。

⭐ 模型（2026-08-24）：`launch` 收 body 的 `model`，三段回退見 `pick_model()`。
   ⚠️ 這條線**後端本來就通**（→ `api_create_session` → `chat.py` 的 `--model`），
      缺的一直是前端沒送值 —— 每個任務因此都吃 config 的 `default_model`。
"""
from __future__ import annotations

import os

from flask import Blueprint, request

from core import tasks as T
from core.claude_session import available as claude_available
from core.paths import SESSIONS_DIR
from core.registry import get_registry
from web_ui.api import fail, ok
from web_ui.api.sessions import api_create_session

bp = Blueprint("tasks", __name__)


def _product_skill(product_id: str) -> str:
    """權威 id（`CRUX`）→ 產品 skill 名（`crux`）。找不到就原樣回。"""
    for p in get_registry().products:
        if product_id in (p.get("product_id"), p.get("id"), p.get("label")):
            return p.get("skill") or p.get("id") or product_id
    return product_id


@bp.get("/api/tasks")
def list_tasks():
    okay, why = claude_available()
    items = []
    for t in T.load():
        items.append({k: t.get(k) for k in
                      ("id", "label", "icon", "subtitle", "order", "scope",
                       "entry", "writes", "builtin", "skills")})
    # ⚠️ 一併回報「能不能用」—— claude.exe 不在時 UI 要停用按鈕並說明原因，
    #    而不是讓人按下去才失敗。
    return ok(tasks=items, available=okay, unavailable_reason=why)


def _expand_options(task: dict) -> dict:
    """把 `options_from: {source: ...}` 展開成實際的 `options`。

    ⛔ 不展開的話，宣告了 source 的欄位在表單上是**空的下拉** ——
       而「產品」是必填，於是任務永遠按不下去，且畫面上看不出原因
       （2026-08-23 範本端到端驗收，五支內建任務全中）。

    展開放在後端：產品清單本來就只有伺服器知道，
    而且這樣任何前端（含日後的 MCP／CLI）都不必各自實作一次。
    """
    out = dict(task)
    fields = []
    for f in task.get("fields") or []:
        src = (f.get("options_from") or {}).get("source")
        if src == "products" and not f.get("options"):
            f = dict(f)
            f["options"] = [
                {"value": p.get("id"), "label": p.get("label") or p.get("id")}
                for p in get_registry().products if not p.get("virtual")
            ]
            # 只有一個產品時直接選好 —— 少一次沒有選擇的選擇
            if len(f["options"]) == 1 and f.get("default") is None:
                f["default"] = f["options"][0]["value"]
        fields.append(f)
    out["fields"] = fields
    return out


@bp.get("/api/tasks/<task_id>")
def get_task(task_id):
    t = T.get(task_id)
    if not t:
        return fail("未知的任務：%s" % task_id, 404)
    return ok(task=_expand_options(t))


def pick_model(body: dict, task: dict) -> str | None:
    """人在任務框選的 > 任務自己宣告的預設 > None（交給 `api_create_session` 補 config）。

    ⚠️ 後兩段要在**後端**判，不能只靠前端 —— 日後 MCP／CLI 也會呼叫這支。
    ⚠️ 空字串要當成「沒給」：下拉在極端情況下可能送出 `""`，
       直接傳下去會變成 `--model ""`，那是個一定會失敗的命令列。
    """
    return (body.get("model") or "").strip() or task.get("model") or None


@bp.post("/api/tasks/<task_id>/launch")
def launch(task_id):
    t = T.get(task_id)
    if not t:
        return fail("未知的任務：%s" % task_id, 404)
    okay, why = claude_available()
    if not okay:
        return fail(why, 503)

    body = request.get_json(force=True, silent=True) or {}
    values = dict(body.get("values") or {})

    # 缺必填就擋在這裡 —— 讓人在表單上改，不要送一則殘缺的提示給 session
    missing = [f["label"] for f in (t.get("fields") or [])
               if f.get("required") and not values.get(f["key"])]
    if missing:
        return fail("必填欄位未填：%s" % "、".join(missing))

    # 收尾體檢與開工接手都吃平台的跨 session 發現（同一份，用途不同：
    # 收尾看「漏做了什麼」、開工看「現在卡在哪、什麼動不得」）
    if task_id in ("handoff_check", "start_day"):
        values["findings"] = T.findings_for_handoff()

    r = T.render(t, values, product_skill=_product_skill(values.get("product", "")))
    session = api_create_session({
        "title": "%s %s" % (t.get("icon", ""), t.get("label")),
        "model": pick_model(body, t),
        "context": {**r["context"], "launched_by": "task"},
        "product": values.get("product"),
        "task_id": task_id,
        "allowed_tools": r["allowed_tools"],
        "timeout_sec": r.get("timeout_sec"),
        "writes": r["writes"],
    })
    # ⭐ 截圖落點要指到**這一個 session 自己的目錄** —— 但 `render()` 跑在建 session 之前，
    #    那時還沒有 sid，所以提示裡先放 `__SID__`，這裡拿到 sid 再換掉。
    #    ⚠️ 目錄由平台先建好：MCP 的 `filename` 遇到不存在的中間目錄不保證會自己建，
    #       而截圖失敗的症狀是「工具回了路徑、檔案卻不在」—— 正是 2026-08-25 那場事故的形狀。
    prompt = r["prompt"].replace("__SID__", session["id"])
    for sub in ("shots", "work"):
        os.makedirs(os.path.join(SESSIONS_DIR, session["id"], sub), exist_ok=True)
    return ok(session=session, prompt=prompt, skills=r["skills"])
