"""平台設定載入：config/platform_config.json ＋ platform_config.local.json 深度合併。

用途：埠、輪詢秒數、預設模型、claude 執行檔覆寫等。
使用方式：from core.config import load_config; cfg = load_config()
前置條件：platform_config.json 版控；*.local.json 不版控（可覆寫任何欄位）。

📝 2026-08-23 移除 `mode`（demo|live）與 `is_demo()` —— 平台已全面接真，
   留著假路徑的代價是每個落點都要記得「這裡有兩條路」，
   而這一輪已經因此踩到兩個缺陷（開單與寫案例都寫進了沙箱）。
"""
from __future__ import annotations

import os
from functools import lru_cache

from core.jsonio import read_json
from core.paths import CONFIG_DIR

_DEFAULTS = {
    "host": "127.0.0.1",
    "port": 5300,
    "poll_seconds": 2,
    "recent_run_keep_minutes": 15,
    "jira_cache_minutes": 30,
    "claude": {"executable": None, "default_model": "sonnet", "fallback_model": "sonnet"},
    "ui": {"motion": True},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_UNREADABLE = "__unreadable__"


def _layer(name: str) -> dict:
    """讀一層設定。⚠️ **檔案在、卻讀不出來要出聲。**

    `read_json` 讀失敗時回預設值 —— 那是為了「另一個 session 正在寫」而設計的，
    對那個情境正確。但人**打錯字**時也走同一條路：重試三次仍失敗，然後靜靜地
    當成「這個檔不存在」，平台用預設值照常啟動。

    `platform_config.local.json` 正是同事會手改的檔（port、generator、claude 路徑）——
    改壞了卻毫無徵兆，他只會看到「我的設定沒作用」而查不到原因。
    （2026-08-23：少一個跳脫字元，平台默默用回預設 port，撞上另一個工作區的平台。）
    """
    path = os.path.join(CONFIG_DIR, name)
    got = read_json(path, _UNREADABLE)
    if got is _UNREADABLE:
        if os.path.isfile(path):
            print("⚠️ %s 讀不出來（JSON 語法錯誤？）—— **本層設定整個被忽略**，"
                  "平台會用預設值啟動。用 `python -m json.tool %s` 看是哪一行。"
                  % (name, path))
        return {}
    return got or {}


@lru_cache(maxsize=1)
def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    cfg = _deep_merge(cfg, _layer("platform_config.json"))
    cfg = _deep_merge(cfg, _layer("platform_config.local.json"))
    return cfg
