"""/reports/<run_id>/<path> —— 報告靜態服務：白名單 ＋ abspath 前綴雙重防護（沿用壓測控制台）。

allure 報告有數百個 hash 檔名 → allow_subtree 內改檢副檔名白名單。
"""
from __future__ import annotations

import os

from flask import Blueprint, Response, send_file

from core import run_store
from core.paths import REPO_ROOT, RUNS_DIR
from core.registry import get_registry
from web_ui.api import fail

bp = Blueprint("reports", __name__)

_SAFE_EXTS = {".html", ".htm", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico",
              ".woff", ".woff2", ".ttf", ".csv", ".txt", ".log", ".map", ".webp"}


@bp.get("/reports/<run_id>/<path:filename>")
def serve_report(run_id, filename):
    if ".." in run_id or ".." in filename or filename.startswith("/"):
        return fail("非法路徑", 400)
    meta = run_store.read_meta(run_id) or {}
    reg = get_registry()
    spec = reg.tools.get(meta.get("tool_id"))
    # 平台 run 目錄，或（吸收的工具）tool_run_dir
    base = os.path.abspath(meta.get("tool_run_dir") or run_store.run_dir(run_id))
    if not base.startswith(os.path.abspath(RUNS_DIR)) and not base.startswith(os.path.abspath(REPO_ROOT)):
        return fail("非法路徑", 400)
    path = os.path.abspath(os.path.join(base, filename))
    if not path.startswith(base + os.sep):
        return fail("非法路徑", 400)
    art = spec.artifacts if spec else {}
    head = filename.split("/", 1)[0]
    if head in (art.get("allow_subtree") or []):
        if os.path.splitext(path)[1].lower() not in _SAFE_EXTS:
            return fail("不允許的檔案型別", 404)
    else:
        wl = set(art.get("whitelist") or []) | {"console.log", "run_meta.json", "run_status.json", "selection.txt"}
        # Demo 樣本可能不在該工具白名單內（例如 crux 用了 locust_report.html）—— 白名單為主、副檔名為輔
        if filename not in wl and os.path.splitext(path)[1].lower() not in {".html", ".json", ".log", ".csv", ".txt"}:
            return fail("不在白名單內的檔案", 404)
    if not os.path.isfile(path):
        return fail("檔案不存在", 404)
    if path.endswith(".log") or path.endswith(".txt"):
        with open(path, "rb") as f:
            return Response(f.read(), mimetype="text/plain; charset=utf-8")
    if path.endswith(".csv"):
        return send_file(path, mimetype="text/csv; charset=utf-8", as_attachment=True)
    if path.endswith(".json"):
        return send_file(path, mimetype="application/json; charset=utf-8")
    return send_file(path)
