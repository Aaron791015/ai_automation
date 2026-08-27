"""/api/cases —— UI 測試案例索引（樹／扁平／重建）。"""
from __future__ import annotations

from flask import Blueprint, request

from collect.case_index import build_or_load, rebuild
from core.registry import get_registry
from web_ui.api import fail, ok

bp = Blueprint("cases", __name__)


def _spec():
    reg = get_registry()
    return next((t for t in reg.tools.values() if t.kind == "pytest"), None)


@bp.get("/api/cases")
def cases():
    spec = _spec()
    if not spec:
        return fail("沒有 pytest 類工具", 404)
    idx = build_or_load(spec, refresh=request.args.get("refresh") == "1")
    slim = request.args.get("slim") == "1"
    payload = {k: v for k, v in idx.items() if k not in ("signature",)}
    if slim:
        payload.pop("flat", None)
    return ok(**payload)


@bp.get("/api/cases/flat")
def flat():
    spec = _spec()
    idx = build_or_load(spec)
    q = (request.args.get("q") or "").strip().lower()
    product = request.args.get("product") or None
    rows = idx.get("flat", [])
    if product:
        rows = [c for c in rows if c.get("product") == product]
    if q:
        rows = [c for c in rows if q in (c.get("title", "") + c.get("nodeid", "") + c.get("func", "")).lower()]
    return ok(count=len(rows), cases=rows[:500])


@bp.get("/api/cases/source")
def case_source():
    """讀一個案例檔的原始碼（唯讀）。

    ⛔ 只放行 `tests/` 底下的 `.py` —— 這個口存在的理由只有一個：
       讓人看得到「平台自動寫出來的那個檔到底長什麼樣」。
       放寬到整個 repo 等於開一個任意檔案讀取（`config.local.json` 就在裡面）。
    """
    import os

    from core.paths import REPO_ROOT
    rel = (request.args.get("path") or "").replace("\\", "/").strip()
    if not rel or os.path.isabs(rel) or os.path.splitext(rel)[1].lower() != ".py":
        return fail("非法路徑（只放行 tests/ 底下的 .py）", 400)
    root = os.path.realpath(os.path.join(REPO_ROOT, "tests"))
    path = os.path.realpath(os.path.join(REPO_ROOT, rel))
    if not (path == root or path.startswith(root + os.sep)):
        return fail("非法路徑（只放行 tests/ 底下的 .py）", 400)
    if not os.path.isfile(path):
        return fail("找不到檔案：%s" % rel, 404)
    if os.path.getsize(path) > 512 * 1024:
        return fail("檔案過大", 400)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return ok(path=rel, text=text, lines=text.count("\n") + 1)


@bp.post("/api/cases/rebuild")
def do_rebuild():
    spec = _spec()
    idx = rebuild(spec)
    return ok(count=idx.get("count"), stale=idx.get("stale"), collect_error=idx.get("collect_error"))
