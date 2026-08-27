# -*- coding: utf-8 -*-
"""新綜合（xzh）測試設定載入。

用途：pytest 測試與 page object 共用同一份環境設定（後台網址、測試帳密），
      不把網址/帳密寫死在測試檔或 page object 裡。
使用方式：
    from xzh_qa.config_loader import qat
    cfg = qat()
    cfg["backend_platform_url"]
前置條件：`config/environments.json` 需有 `xzh` 段落
         （`scripts/new_product.py` 已建立骨架，見該檔 `xzh.qat`）。

設定來源與合併規則（見 CLAUDE.md §4）：
    config/environments.json 的 `xzh` 段落（非敏感，可版控）
    ＋ config/config.local.json 若存在且有 `xzh` 段落則深度合併覆蓋（敏感值優先本機檔）。
    目前新綜合的測試帳密屬 QAT 測試帳密，依專案慣例直接放在 environments.json，
    本檔仍保留 local 合併邏輯，供日後若改放敏感設定時不必改動呼叫端。
"""
from __future__ import annotations

import io
import json
import os
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_JSON = os.path.join(ROOT, "config", "environments.json")
LOCAL_JSON = os.path.join(ROOT, "config", "config.local.json")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_config() -> dict:
    """回傳新綜合的環境設定（`environments.json` 的 `xzh` 段落，
    `config.local.json` 若有同名段落則深度合併覆蓋）。"""
    env = _read_json(ENV_JSON).get("xzh", {})
    local = _read_json(LOCAL_JSON).get("xzh", {})
    return _deep_merge(env, local)


def qat() -> dict:
    """快捷取 `xzh.qat` 段落（網址與測試帳密）。"""
    return get_config().get("qat", {})


def admin_credentials() -> tuple[str, str]:
    """回傳 (帳號, 密碼)——平台層／公司層目前共用同一組帳密。"""
    admin = qat().get("admin", {})
    return admin.get("username", ""), admin.get("password", "")
