"""Bug 現況索引：本地 Bug 單（frontmatter）× JIRA 現況 → 四種交叉狀態。

用途：Dashboard「待辦與 Bug 現況」面板、知識雷達「缺陷」圈、Ctrl+K 搜 Bug 單號。
使用方式：
    from core.bug_index import build_bug_index
    idx = build_bug_index(jira="cached"|"refresh"|"off")
    python -m core.bug_index --dump [--no-jira]
前置條件：
    · 直接重用 scripts/bug_paths.py（PRODUCTS／bugs_dir／bug_layers／parse_frontmatter），不另寫解析。
    · docs/*/bugs/ 不版控 —— 缺目錄時該產品回 present=False（「未建立」而非 0）。
    · JIRA：reported 欄內嵌單號（例「2026-07-30（CRUX-874）」）；批次 JQL 查現況，
      快取 30 分鐘於 cache/jira_status.json。Demo 模式或 JIRA 不可達時退回
      demo/knowledge/jira_snapshot.json，且回應標明 jira_source。
四種交叉狀態（每種對應一個動作）：
    revisit   本地 open × JIRA Resolved/Closed  → 該重驗了
    unfiled   本地 open × reported 未開立        → 沒人在追
    to_close  本地 fixed × JIRA 仍 Open          → 該關單
    no_regr   regression 待補                     → 沒有守門案例
"""
from __future__ import annotations

import glob
import os
import re
import sys
import time

from core.config import load_config
from core.jsonio import read_json, write_json_atomic
from core.paths import CACHE_DIR, REPO_ROOT, rel_to_repo

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
try:
    import bug_paths  # noqa: E402  scripts/bug_paths.py
except ImportError:  # pragma: no cover
    bug_paths = None

_JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_OPEN_STATUSES = {"open", "已接續", "superseded_by", "reopen"}
_FIXED_STATUSES = {"fixed", "verified"}
_JIRA_DONE = {"resolved", "closed", "done", "已解決", "已關閉", "verified"}
_STATUS_LABEL = {
    "open": "🔴 未修復", "fixed": "✅ 已修復", "rejected": "⛔ 已撤銷",
    "superseded": "🔁 已接續", "suggestion": "💡 建議", "verified": "✅ 已修復",
}


def _slug_of(prod: str) -> str:
    """config 的產品 id（`樂透`）→ 平台用的 slug（`lotto`）。

    ⛔ 不可硬編 —— 落回中文 id 的話，Bug 索引的鍵與平台其他地方（一律 slug）
       對不起來，**那個產品的 Bug 數量永遠掛不上去，而且不報錯**
       （2026-08-23 範本端到端驗收）。
    """
    from core.registry import get_registry
    for p in get_registry().products:
        if p.get("product_id") == prod:
            return p.get("id") or prod
    return prod




def _jira_keys(reported: str) -> list[str]:
    if not reported or "未開立" in reported:
        return []
    return _JIRA_KEY.findall(reported)


def _scan_local() -> dict:
    """{product_id: {present, bugs:[...], counts}}"""
    out: dict[str, dict] = {}
    if bug_paths is None:
        return out
    # ⚠️ 每次重讀產品清單 —— `bug_paths` 的常數是 **import 當下**凍結的，
    #    而平台是長駐的 Flask：接完新產品之後不重讀就永遠看不到它
    #    （產品頁會顯示成「未建立 bugs/」，且看不出是快取問題）。
    bug_paths.reload_products()
    for prod in bug_paths.PRODUCTS:
        pid = _slug_of(prod)
        bdir = bug_paths.bugs_dir(prod)
        if not os.path.isdir(bdir):
            out[pid] = {"present": False, "bugs": [], "counts": {}}
            continue
        bugs = []
        for layer_i, layer in enumerate(bug_paths.bug_layers(bdir)):
            for path in sorted(glob.glob(os.path.join(layer, "*.md"))):
                name = os.path.basename(path)
                if name.startswith("BUG清單") or name.startswith("_"):
                    continue
                meta, _ = bug_paths.parse_frontmatter(path)
                if not meta or "id" not in meta:
                    continue
                status = (meta.get("status") or "").strip()
                bugs.append({
                    "id": meta["id"], "title": meta.get("title", ""), "product": pid,
                    "severity": meta.get("severity", ""), "status": status,
                    "status_label": _STATUS_LABEL.get(status, status),
                    "module": meta.get("module", ""), "surface": meta.get("surface", ""),
                    "found": meta.get("found", ""), "reported": meta.get("reported", ""),
                    "verified": meta.get("verified", ""), "regression": meta.get("regression", ""),
                    "jira_keys": _jira_keys(meta.get("reported", "")),
                    "related": meta.get("related", ""),
                    "archived": layer_i == 1,
                    "path": rel_to_repo(path),
                    "mtime": os.path.getmtime(path),
                })
        counts = {}
        for b in bugs:
            counts[b["status"]] = counts.get(b["status"], 0) + 1
        out[pid] = {"present": True, "bugs": bugs, "counts": counts,
                    "active": sum(1 for b in bugs if b["status"] in _OPEN_STATUSES),
                    "archived": sum(1 for b in bugs if b["archived"])}
    return out


# ---------------------------------------------------------------- JIRA
def _jira_cache_path() -> str:
    return os.path.join(CACHE_DIR, "jira_status.json")


def _fetch_jira(keys: list[str]) -> dict:
    """{key: {status, assignee, updated}}；用 tools/jira_qa 的 JiraClient（唯讀）。"""
    if not keys:
        return {}
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
    from jira_qa.jira_api import JiraClient  # noqa: E402
    client = JiraClient.from_config()
    out: dict[str, dict] = {}
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        jql = "key in (" + ",".join(chunk) + ")"
        try:
            for issue in client.search(jql, max_results=len(chunk)):
                out[issue.key] = {"status": issue.status, "assignee": getattr(issue, "assignee", None),
                                  "updated": getattr(issue, "updated", None), "summary": issue.summary}
        except Exception as e:  # noqa: BLE001
            for k in chunk:
                out.setdefault(k, {"error": str(e)[:200]})
    return out


def _load_jira(keys: list[str], mode: str) -> tuple[dict, str, str | None]:
    """回 (status_map, source, fetched_at)。source ∈ live|cache|snapshot|off"""
    if mode == "off":
        return {}, "off", None
    # ★ 沒有任何產品宣告 jira_key ＝ 這個工作區不比對 JIRA。
    #   別去連、也別說「不可達」—— 那會讓沒有 JIRA 的同事以為是壞了
    #   （計畫 F-2：顯示「未設定」，不可報錯。2026-08-23 情境 B 走查）。
    if not keys:
        return {}, "未設定", None
    cache = read_json(_jira_cache_path(), {}) or {}
    ttl = int(load_config().get("jira_cache_minutes", 30)) * 60
    fresh = cache.get("fetched_ts") and (time.time() - cache["fetched_ts"] < ttl)
    have_all = all(k in cache.get("issues", {}) for k in keys)
    if mode == "cached" and fresh and have_all:
        return cache["issues"], "cache", cache.get("fetched_at")
    try:
        issues = _fetch_jira(keys)
        data = {"fetched_ts": time.time(), "fetched_at": time.strftime("%Y-%m-%d %H:%M"), "issues": issues}
        write_json_atomic(_jira_cache_path(), data)
        return issues, "live", data["fetched_at"]
    except Exception as e:  # noqa: BLE001
        if cache.get("issues"):
            return cache["issues"], "cache", cache.get("fetched_at")
        # ⚠️ 分辨「**還沒設定**」與「**真的連不上**」—— 處置完全不同：
        #    前者去設定頁填帳密，後者查網路／VPN。混成一句話的話，
        #    沒有 JIRA 的同事會以為平台壞了（2026-08-23 情境 B 走查）。
        msg = str(e)
        unset = any(k in msg for k in ("base_url", "未設定", "帳密", "username", "password", "credential"))
        # ⛔ live 模式不讀 demo 的假快照 —— 那是原型的資料。
        return {}, ("未設定" if unset else f"不可達（{msg[:60]}）"), None


# ---------------------------------------------------------------- 交叉狀態
def _cross(bug: dict, jira: dict) -> list[str]:
    tags = []
    jstat = [(jira.get(k) or {}).get("status", "") for k in bug["jira_keys"]]
    jdone = any(str(s).lower() in _JIRA_DONE for s in jstat if s)
    jopen = any(s and str(s).lower() not in _JIRA_DONE for s in jstat)
    if bug["status"] in _OPEN_STATUSES:
        if jdone:
            tags.append("revisit")
        if not bug["jira_keys"] and bug["status"] == "open":
            tags.append("unfiled")
    if bug["status"] in _FIXED_STATUSES and jopen:
        tags.append("to_close")
    if "待補" in (bug.get("regression") or "") and bug["status"] in (_OPEN_STATUSES | _FIXED_STATUSES):
        tags.append("no_regr")
    return tags


def build_bug_index(jira: str = "cached") -> dict:
    local = _scan_local()
    all_keys = sorted({k for p in local.values() for b in p["bugs"] for k in b["jira_keys"]})
    jira_map, source, fetched_at = _load_jira(all_keys, jira)
    products = {}
    for pid, p in local.items():
        cross = {"revisit": [], "unfiled": [], "to_close": [], "no_regr": []}
        for b in p["bugs"]:
            b["jira"] = [{"key": k, **(jira_map.get(k) or {})} for k in b["jira_keys"]]
            b["cross"] = _cross(b, jira_map)
            for t in b["cross"]:
                cross[t].append(b["id"])
        products[pid] = {**p, "cross": cross,
                         "cross_counts": {k: len(v) for k, v in cross.items()}}
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jira_source": source, "jira_fetched_at": fetched_at,
        "jira_keys_total": len(all_keys),
        "products": products,
    }


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    idx = build_bug_index(jira="off" if "--no-jira" in argv else "cached")
    print(f"jira_source={idx['jira_source']} keys={idx['jira_keys_total']}")
    for pid, p in idx["products"].items():
        if not p["present"]:
            print(f"  {pid}: 未建立 bugs/")
            continue
        print(f"  {pid}: {len(p['bugs'])} 張（活躍 {p['active']}／歸檔 {p['archived']}） counts={p['counts']} cross={p['cross_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
