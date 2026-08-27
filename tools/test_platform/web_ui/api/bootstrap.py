"""GET /api/bootstrap —— 前端啟動的唯一初始化來源（沿用「/api/config 是 UI 初始化唯一來源」慣例）。

回：products／tools（public spec）／config 片段／registry 錯誤／時間。不含任何密碼。
"""
from __future__ import annotations

import os
import time

from flask import Blueprint

from core.config import load_config
from core.paths import REPO_ROOT
from core.registry import get_registry
from web_ui.api import ok

bp = Blueprint("bootstrap", __name__)


@bp.get("/api/bootstrap")
def bootstrap():
    cfg = load_config()
    reg = get_registry()
    return ok(
        host=cfg.get("host"), port=cfg.get("port"),
        poll_seconds=cfg.get("poll_seconds", 2),
        recent_run_keep_minutes=cfg.get("recent_run_keep_minutes", 15),
        ui=cfg.get("ui", {}),
        claude={"default_model": (cfg.get("claude") or {}).get("default_model", "sonnet"),
                "fallback_model": (cfg.get("claude") or {}).get("fallback_model")},
        products=reg.products,
        tools=[t.public() for t in reg.tools.values() if t.enabled],
        registry_errors=reg.errors,
        server_time=time.strftime("%Y-%m-%d %H:%M:%S"),
        # header 中間的工作區識別（2026-08-24 取代裝飾性的 "Situational Awareness"）——
        # 範本情境下同事常同時開著原型與自己那一份，**兩個平台長得一模一樣**。
        workspace={"name": os.path.basename(REPO_ROOT.rstrip(os.sep)), "path": REPO_ROOT},
        # ⛔ 不要把 "demo" 寫進版本字串 —— 範本一律出貨 live，
        #    模式已經由上面的 mode／demo 兩個欄位回報了（2026-08-23 範本驗收）。
        version="0.1.0",
    )
