"""GET /api/search?q= —— Ctrl+K 全域模糊搜尋：案例（中文標題／nodeid）、工具、Bug 單號、run_id、待辦編號、session。"""
from __future__ import annotations

import re

from flask import Blueprint, request

from collect.case_index import build_or_load
from core import run_index
from core.bug_index import build_bug_index
from core.registry import get_registry
from core.todo_index import build_todo_index
from web_ui.api import ok
from web_ui.api.knowledge import _memoize

bp = Blueprint("search", __name__)


def _docs_of_products(reg) -> list[dict]:
    """列出各產品 `docs/<目錄>/` 底下的 markdown（不遞迴進 bugs/）。

    只比對**檔名** —— 全文檢索是另一回事（成本高、雜訊多），
    而使用者記得的通常正是檔名裡那幾個字。
    """
    import glob
    import os as _os
    from core.paths import repo_path
    out = []
    for p in reg.products:
        if p.get("virtual"):
            continue
        docs_dir = (p.get("knowledge") or {}).get("docs_dir")
        if not docs_dir:
            continue
        base = repo_path(*docs_dir.split("/"))
        for f in sorted(glob.glob(_os.path.join(base, "*.md"))):
            out.append({"name": _os.path.basename(f)[:-3],
                        "path": "%s/%s" % (docs_dir, _os.path.basename(f)),
                        "product": p.get("id")})
    return out


@bp.get("/api/search")
def search():
    q = (request.args.get("q") or "").strip()
    ql = q.lower()
    if not q:
        return ok(results=[])
    reg = get_registry()
    res: list[dict] = []
    # 命令模式
    if q.startswith(">"):
        cmds = [("停止全部", "stop_all"), ("重建案例索引", "rebuild_index"), ("更新 JIRA", "refresh_jira"), ("健康檢查", "health"), ("開啟工具清單", "tools")]
        for label, cid in cmds:
            if q[1:].strip() in label or not q[1:].strip():
                res.append({"type": "command", "label": f"> {label}", "id": cid})
        return ok(results=res)
    # 工具
    for t in reg.tools.values():
        if ql in t.name.lower() or ql in t.id or any(ql in tag.lower() for tag in t.raw.get("tags", [])):
            res.append({"type": "tool", "label": t.name, "sub": t.raw.get("subtitle", ""), "id": t.id, "product": t.product})
    # 產品
    for p in reg.products:
        if ql in p["label"].lower() or ql in p["id"]:
            res.append({"type": "product", "label": p["label"], "id": p["id"]})
    # 案例（中文標題／nodeid／函式名）
    if len(q) >= 2:
        spec = next((t for t in reg.tools.values() if t.kind == "pytest"), None)
        if spec:
            idx = build_or_load(spec)
            hits = [c for c in idx.get("flat", []) if "error" not in c and (ql in c["title"].lower() or ql in c["nodeid"].lower() or ql in c["func"].lower())]
            for c in hits[:30]:
                res.append({"type": "case", "label": c["title"], "sub": c["nodeid"], "id": c["nodeid"], "product": c.get("product"), "markers": c.get("markers", [])})
            if len(hits) > 30:
                res.append({"type": "more", "label": f"…還有 {len(hits) - 30} 條案例命中，到案例瀏覽器用搜尋列看全部", "id": q})
    # run_id
    if re.match(r"^\d{8}", q):
        for r in run_index.recent(limit=200):
            if q in r["run_id"]:
                res.append({"type": "run", "label": r["run_id"], "sub": f"{r.get('tool_name')} · {r.get('headline')}", "id": r["run_id"]})
    # 待辦編號
    if re.match(r"^[tdb]\d+$", ql):
        t = _memoize("todos", 30, build_todo_index)
        for pid, p in t["products"].items():
            for d in p["docs"]:
                for it in d.get("items", []):
                    if it["id"].lower() == ql:
                        res.append({"type": "todo", "label": f"{pid.upper()} {it['id']} {it['summary']}", "sub": it["sub_label"], "id": it["id"], "product": pid, "done": it["done"]})
                # ⚠️ blocker 不在 `items` 裡（`todo_index` 另存一份）——
                #    先前只掃 items，於是**所有 B 開頭的 blocker 都搜不到**，
                #    而 blocker 正是交接檔 §1、開工第一個要讀的東西
                #    （2026-08-23 情境 B 走查）。
                for bl in d.get("blockers", []):
                    if (bl.get("n") or bl.get("id") or "").lower() != ql:
                        continue
                    res.append({"type": "todo",
                                "label": f"⛔ {pid.upper()} {bl.get('n') or bl.get('id')} {(bl.get('what') or '')[:60]}",
                                "sub": f"blocker · 卡在 {bl.get('who') or '—'}",
                                "id": bl.get("n") or bl.get("id"), "product": pid, "done": False})
    # 知識文件（檔名）
    #  ⭐「我記得有一份講 X 的文件，在哪？」是這個工作區最常見的需求 ——
    #    先前搜尋完全不涵蓋 docs/，只能靠人記得 INDEX.md
    #    （2026-08-23 情境 B 走查：搜「開獎機制」零結果）。
    if len(q) >= 2:
        for d in _docs_of_products(reg):
            if ql in d["name"].lower():
                res.append({"type": "doc", "label": d["name"], "sub": d["path"],
                            "id": d["path"], "product": d["product"], "path": d["path"]})
                if len(res) > 45:
                    break
    # Bug 單號／標題
    #  ⛔ 不再用寫死的前綴正則（原本是 `^(crux|wbot|qx|bot)-?\d*`）——
    #     新產品的前綴不在裡面，而它後面的 `len(q) >= 2` 本來就涵蓋了全部情況。
    if len(q) >= 2:
        b = _memoize("bugs", 60, lambda: build_bug_index())
        for pid, p in b["products"].items():
            for bug in p.get("bugs", []):
                if ql in bug["id"].lower() or ql in bug["title"].lower() or any(ql in k.lower() for k in bug["jira_keys"]):
                    res.append({"type": "bug", "label": f"{bug['id']} {bug['title']}", "sub": f"{bug['status_label']} · {bug['module']}", "id": bug["id"], "product": pid, "path": bug["path"]})
                    if len(res) > 45:
                        break
    return ok(results=res[:60], total=len(res))
