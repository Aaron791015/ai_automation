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

帳號鏈切換（2026-10-02）：預設用 aaa 鏈（`xzh.qat` 的 admin／player／agent_accounts）。
    設環境變數 `XZH_CHAIN=b`（須在 python／pytest 行程啟動前設好）改用第二條鏈
    （`xzh.qat.chain_b`：公司 aaron02、一至九級 bbb111～bbb999、會員 bbb010），
    `admin_credentials()`／`player_credentials()`／`agent_password()`／`chain_accounts()`／
    `chain_lock_name()` 會一起切換；未設或設 `a` 時行為與切換前完全相同。
    兩條鏈各有各的鎖檔（`aaa111-through-aaa010`、`bbb111-through-bbb010`），可併行測試；
    ⛔ 同一條鏈內仍不可併行（同帳號他處登入會踢掉前者）。
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


#: 選第二條鏈的環境變數；值為 `b`（不分大小寫）即用 `xzh.qat.chain_b`，未設或 `a` 為預設的 aaa 鏈。
CHAIN_ENV = "XZH_CHAIN"

#: aaa 鏈的帳號順序（索引 0～8 為一～九級代理、索引 9 為會員）；預設鏈寫死，確保預設行為不隨設定檔改變。
_CHAIN_A_ACCOUNTS = ["aaa" + str(i) * 3 for i in range(1, 10)] + ["aaa010"]


def active_chain() -> str:
    """目前使用的帳號鏈：`a`（預設）或 `b`；其他值直接報錯，避免打錯字默默跑到預設鏈。"""
    raw = os.environ.get(CHAIN_ENV, "").strip().lower()
    if raw in ("", "a"):
        return "a"
    if raw == "b":
        return "b"
    raise ValueError(f"{CHAIN_ENV} 只接受 a 或 b，收到 {raw!r}")


def _chain_section() -> dict:
    """目前帳號鏈的設定段落：a＝`xzh.qat`（admin／player／agent_accounts），b＝`xzh.qat.chain_b`。"""
    if active_chain() == "b":
        section = qat().get("chain_b")
        if not section:
            raise KeyError("config 缺少 xzh.qat.chain_b（第二組帳號），無法使用 XZH_CHAIN=b")
        return section
    return qat()


def chain_accounts() -> list[str]:
    """目前鏈的帳號順序：索引 0～8＝一～九級代理、索引 9＝會員（賠率差測試以此為準）。"""
    if active_chain() == "a":
        return list(_CHAIN_A_ACCOUNTS)
    section = _chain_section()
    agents = [k for k in section.get("agent_accounts", {}) if not k.startswith("_")]
    return agents + [section.get("player", {}).get("username", "")]


def chain_lock_name() -> str:
    """賠率差測試的帳號鏈鎖檔名（不含 `.lock`）：aaa 鏈＝`aaa111-through-aaa010`，b 鏈＝`bbb111-through-bbb010`。"""
    accounts = chain_accounts()
    return f"{accounts[0]}-through-{accounts[-1]}"


def admin_credentials() -> tuple[str, str]:
    """回傳 (帳號, 密碼)——平台層／公司層目前共用同一組帳密。

    ⚠️ `XZH_CHAIN=b` 時回傳公司操作員 aaron02；aaron02 只能登入公司後台，登入平台層會被拒
    （2026-10-02 實測「账号或密码错误」），平台層讀值仍須由 aaron01 取得。
    """
    admin = _chain_section().get("admin", {})
    return admin.get("username", ""), admin.get("password", "")


def player_credentials() -> tuple[str, str]:
    """回傳 QAT 會員前台測試帳密。"""
    player = _chain_section().get("player", {})
    return player.get("username", ""), player.get("password", "")


def agent_password(username: str) -> str:
    """取得指定 QAT 代理測試帳號密碼；未配置時回傳空字串。

    二至九級代理不應猜測或沿用公司管理員密碼。可在 ``xzh.qat`` 下以
    ``agent_accounts`` 對照表提供各帳號憑證，B82 便能逐層接續驗證。
    ``aaa111`` 為既有已確認共用管理員密碼的測試帳號，保留相容 fallback。
    """
    config = _chain_section()
    account = config.get("agent_accounts", {}).get(username, {})
    password = account.get("password", "") if isinstance(account, dict) else ""
    if password:
        return password
    if username == "aaa111" and active_chain() == "a":
        return admin_credentials()[1]
    return ""
