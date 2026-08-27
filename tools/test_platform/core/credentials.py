# -*- coding: utf-8 -*-
"""憑證設定的讀寫（階段 F-1，2026-08-23）。

用途：平台原本**對設定完全唯讀**（`web_ui/api/settings.py` 沒有任何 POST）。
      JIRA 憑證只能手動編輯 `config/config.local.json` —— 而其中的
      `session_cookie` **會過期**，是最常要重貼的一個。

使用方式：
    from core import credentials as C
    C.status()                      # 只回「有沒有設定 ＋ 最後更新」，**不含任何密碼**
    C.save({"jira": {"username": "...", "password": "..."}})
    C.test_jira()                   # 唯讀連線測試
    C.test_jira_attachment(key)     # 驗 session_cookie 還沒過期

⛔ 三條安全紀律（缺一不可）：

  1. **絕不把已存的密碼回傳給瀏覽器** —— 只回「已設定／未設定 ＋ 最後更新時間」。
     沿用 `web_ui/api/bootstrap.py` docstring 的既有慣例（「不含任何密碼」）。
  2. **讀-改-寫，只動平台擁有的鍵** —— `config.local.json` 還放著別的工具的憑證
     （測試站帳密等），不可整份覆蓋。合併語意比照
     `tools/crux_qa/config_loader.py` 的 `_deep_merge`。
  3. **寫入 `config/config.local.json`** —— 該檔已在 `.gitignore`，
     且 `export_template` 的白名單把它列為 NEVER。
"""
from __future__ import annotations

import io
import json
import os
import time

from core.paths import REPO_ROOT, rel_to_repo

LOCAL_PATH = os.path.join(REPO_ROOT, "config", "config.local.json")
ENV_PATH = os.path.join(REPO_ROOT, "config", "environments.json")

# 平台**擁有**的鍵（只有這些會被本模組改寫；其餘一律原封不動）
OWNED = {
    "jira": ["username", "password", "session_cookie"],
}
SECRET_KEYS = {"password", "session_cookie"}


def _read_local() -> dict:
    if not os.path.isfile(LOCAL_PATH):
        return {}
    try:
        return json.load(io.open(LOCAL_PATH, encoding="utf-8")) or {}
    except ValueError:
        return {}


def status() -> dict:
    """⛔ 回傳**不含任何密碼** —— 只說「有沒有設定」。"""
    local = _read_local()
    out = {"path": rel_to_repo(LOCAL_PATH), "groups": {}}
    for group, keys in OWNED.items():
        node = local.get(group) or {}
        out["groups"][group] = {
            k: {"set": bool(str(node.get(k) or "").strip()),
                # 只給前幾碼讓人認得出是哪一組，不足以還原
                "hint": _hint(node.get(k)) if k not in SECRET_KEYS else None}
            for k in keys
        }
        out["groups"][group]["_updated"] = (local.get("_platform_meta") or {}).get(group)
    # base_url 在 environments.json（非敏感），一併回讓人看得到打去哪
    try:
        env = json.load(io.open(ENV_PATH, encoding="utf-8"))
        out["jira_base_url"] = (env.get("jira") or {}).get("base_url")
    except (OSError, ValueError):
        out["jira_base_url"] = None
    return out


def _hint(v):
    v = str(v or "")
    return (v[:3] + "…") if len(v) > 4 else ("…" if v else None)


def save(values: dict) -> dict:
    """只寫平台擁有的鍵，其餘原封不動。

    ⚠️ **空字串 ＝ 不改**（不是清空）—— 表單不會回填已存的密碼，
      使用者只改其中一欄時，其他欄位送來的就是空字串。
      要清空請用 `clear()`。
    """
    local = _read_local()
    meta = local.setdefault("_platform_meta", {})
    changed = []
    for group, keys in OWNED.items():
        incoming = (values or {}).get(group) or {}
        node = local.setdefault(group, {})
        for k in keys:
            v = incoming.get(k)
            if v is None or str(v).strip() == "":
                continue                       # 空 ＝ 不改
            node[k] = str(v).strip()
            changed.append("%s.%s" % (group, k))
        if changed:
            meta[group] = time.strftime("%Y-%m-%d %H:%M")
    if changed:
        _write(local)
    return {"changed": changed}


def clear(group: str, key: str) -> dict:
    local = _read_local()
    node = local.get(group) or {}
    if key in node:
        node.pop(key)
        (local.setdefault("_platform_meta", {}))[group] = time.strftime("%Y-%m-%d %H:%M")
        _write(local)
        return {"cleared": "%s.%s" % (group, key)}
    return {"cleared": None}


def _write(data: dict) -> None:
    d = os.path.dirname(LOCAL_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = LOCAL_PATH + ".tmp"
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, LOCAL_PATH)


# ────────────────────────────────── 唯讀連線測試

def test_jira() -> dict:
    """Basic Auth 還活著嗎。⛔ 唯讀 —— 不寫 JIRA（`jira-verify` §0 的邊界）。"""
    try:
        from tools.jira_qa.jira_api import JiraClient          # noqa: F401
    except Exception:                                          # noqa: BLE001
        pass
    try:
        import sys
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        from tools.jira_qa.jira_api import JiraClient
        c = JiraClient.from_config()
        # 用 JQL 取 1 筆就夠 —— 只是要確認認證通得過
        n = c.search("order by created DESC", max_results=1)
        return {"ok": True, "detail": "認證通過（取到 %d 筆）" % len(n or [])}
    except Exception as e:                                     # noqa: BLE001
        return {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:300])}


def test_jira_attachment(issue_key: str = "") -> dict:
    """`session_cookie` 還沒過期嗎。

    ★ 為什麼要單獨測：Jira Server 8.6.1 早於 PAT，附件下載走 web 層
      **不吃 Basic Auth** —— 要貼已通過 2FA 的 `JSESSIONID`，而它**會過期**。
      這是這一頁最常被用到的功能（重貼 cookie）。
    """
    if not str((_read_local().get("jira") or {}).get("session_cookie") or "").strip():
        return {"ok": False, "detail": "未設定 session_cookie（不下載附件的話可以留空）"}
    if not issue_key:
        return {"ok": False, "detail": "請給一個有附件的單號來測"}
    try:
        import sys
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        from tools.jira_qa.jira_api import JiraClient
        c = JiraClient.from_config()
        issue = c.get_issue(issue_key)
        atts = getattr(issue, "attachments", None) or []
        if not atts:
            return {"ok": False, "detail": "%s 沒有附件，換一張有附件的單" % issue_key}
        return {"ok": True, "detail": "%s 有 %d 個附件，cookie 可用" % (issue_key, len(atts))}
    except Exception as e:                                     # noqa: BLE001
        return {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:300])}
