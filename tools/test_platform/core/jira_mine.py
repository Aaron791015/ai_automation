# -*- coding: utf-8 -*-
"""「指派在我身上」的 JIRA 單 —— 給「驗 JIRA 修復」任務框當選單用。

用途：`web_ui/api/tasks_api.py` 的 `/api/tasks/<id>/options/<key>`。
使用方式：
    from core.jira_mine import mine_for_product
    got = mine_for_product("crux")          # {"options": [...], "reason": "..."}

⛔ **除了 Done 以外，不可以依狀態過濾**（`jira-verify` skill §4）：

    > JIRA 單的 status 不是「能否驗證」的判準，不得據此拒驗或建議延後。

  第一版本來想「只列 Resolved」，那正好是 skill 禁止的事 —— 狀態流轉未必即時
  反映實際修復進度，濾掉就等於幫使用者決定了「這張不用驗」。
  ⭐ 狀態仍然要**顯示**（skill 說它的用途是「解讀結果」），只是不當篩選條件。

★ **唯一的例外：`Done` 不進選單**（2026-08-27 使用者裁示）。理由與 skill 不衝突 ——
  Done 是**這條流程的終點**（驗完、關單），不是「還沒輪到驗」的中間狀態；
  而清單一多（本站實測 100 張）就找不到要驗的那幾張。
  ⛔ 但這**不等於「Done 不能驗」** —— 上面的 `tickets` 欄位仍然打得進任何單號，
     要回頭複驗一張 Done 的單，照打即可（CLAUDE.md §7.0：訂「一律不准」之前，
     先問這條會不會連正當用途一起擋掉）。**擋掉的只是選單的雜訊，不是驗證的權利。**
  ⚠️ 過濾放在**取回之後**、不放進 JQL：JQL 寫 `status != Done` 時，
     萬一該站台沒有叫這個名字的狀態，整句查詢會失敗 → 選單直接壞掉。
     用 Python 濾則最壞情況只是「沒濾到」，不會把功能弄壞。

⛔ 唯讀（`jira-verify` §0）—— 只查詢，不開單、不留言、不改狀態。

前置條件與踩坑：
  · JIRA 憑證放 `config/config.local.json`（不版控）。沒設定時**不可以報錯** ——
    同事可能根本沒有 JIRA，任務框要照常打得開（只是這個選單是空的＋一句說明）。
  · 產品的 `jira_key` 可能是 `None`（七星就是）→ 同樣給空清單＋說明，不要當成故障。
  · 查詢**要快取**，因為每次切換產品都會重問一次；沿用
    `platform_config.json` 的 `jira_cache_minutes`（預設 30 分）。
"""
from __future__ import annotations

import os
import sys
import time

from core.config import load_config
from core.jsonio import read_json, write_json_atomic
from core.paths import CACHE_DIR, REPO_ROOT

#: 一次最多列幾張。⚠️ 純粹是「畫面上列得完」的上限，不是篩選。
MAX_ISSUES = 100
#: 向 JIRA 取幾張。⚠️ 要比 MAX_ISSUES 多 —— Done 是**取回之後**才濾掉的，
#  取 100 濾完可能只剩十幾張，那不是「畫面列得完」而是「被截掉了」。
FETCH_MAX = 300
#: 不進選單的狀態（小寫比對）。★ 只有這一個，理由見檔頭。
HIDDEN_STATUS = {"done"}


def _hidden(issue) -> bool:
    return str(issue.get("status") or "").strip().lower() in HIDDEN_STATUS


def _cache_path() -> str:
    return os.path.join(CACHE_DIR, "jira_mine.json")


def _jira_key(product_id: str):
    """平台 slug／權威 id → JIRA project key。找不到回 None。"""
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if product_id in (p.get("id"), p.get("product_id"), p.get("slug"), p.get("label")):
                return p.get("jira_key")
    except Exception:                           # noqa: BLE001
        pass
    return None


def _search(key: str):
    """跑一次 JQL。⛔ 唯讀。"""
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
    from jira_qa.jira_api import JiraClient    # noqa: E402
    client = JiraClient.from_config()
    # ⛔ 刻意**沒有** status 條件 —— Done 的過濾在 Python 那側做（見檔頭的理由）。
    #    排序用 updated，最近動過的在前面。
    jql = "project = %s AND assignee = currentUser() ORDER BY updated DESC" % key
    out = []
    for i in client.search(jql, max_results=FETCH_MAX):
        out.append({"key": i.key,
                    "status": getattr(i, "status", "") or "",
                    "summary": (getattr(i, "summary", "") or "")[:80]})
    return out


def mine_for_product(product_id: str, refresh: bool = False) -> dict:
    """回 `{"options": [{value,label}], "reason": str}`。

    ⛔ 任何失敗都回**空清單 ＋ 說得出原因的一句話**，不要拋 ——
       任務框要照常打得開（同事可能根本沒有 JIRA）。
    """
    key = _jira_key(product_id)
    if not key:
        return {"options": [], "reason": "這個產品沒有對應的 JIRA 專案（products.json 的 jira_key 是空的）"}

    cache = read_json(_cache_path(), {}) or {}
    ttl = int(load_config().get("jira_cache_minutes", 30)) * 60
    hit = (cache.get(key) or {}) if not refresh else {}
    if hit.get("ts") and time.time() - hit["ts"] < ttl and hit.get("issues") is not None:
        issues, note = hit["issues"], "（%d 分鐘內的快取）" % (ttl // 60)
    else:
        try:
            issues, note = _search(key), ""
        except Exception as e:                  # noqa: BLE001
            # ⚠️ 憑證沒設、過期、站台不通都走這裡 —— 講得出原因就好，不要當機。
            return {"options": [],
                    "reason": "讀不到 JIRA（%s）—— 到設定頁檢查憑證，或直接手動輸入單號"
                              % str(e)[:120]}
        cache[key] = {"ts": time.time(), "issues": issues}
        try:
            write_json_atomic(_cache_path(), cache)
        except Exception:                       # noqa: BLE001
            pass

    if not issues:
        return {"options": [], "reason": "JIRA 上沒有指派給你的 %s 單" % key}

    # ★ Done 不進選單（見檔頭）。⚠️ 快取存的是**未過濾**的原始清單 ——
    #   規則哪天改了不必重打 JIRA，也才報得出「濾掉幾張」。
    live = [i for i in issues if not _hidden(i)]
    dropped = len(issues) - len(live)
    shown, cut = live[:MAX_ISSUES], max(0, len(live) - MAX_ISSUES)
    if not shown:
        return {"options": [],
                "reason": "指派給你的 %s 單都是 Done（共 %d 張）—— 要複驗就直接在上面輸入單號"
                          % (key, dropped)}
    return {
        # ⭐ 狀態放進 label **給人看**（skill §4：狀態的用途是解讀結果），
        #    除了 Done 之外**沒有**拿它做任何過濾。
        "options": [{"value": i["key"],
                     "label": "%s · %s · %s" % (i["key"], i.get("status") or "?", i.get("summary") or ""),
                     "status": i.get("status") or "",
                     "summary": i.get("summary") or ""}
                    for i in shown],
        "reason": "指派給你的 %s 單 %d 張%s%s%s —— ⚠️ 狀態只是資訊，"
                  "**不是能不能驗的判準**（jira-verify §4）；要驗 Done 的單直接輸入單號"
                  % (key, len(shown), note,
                     ("，已略過 %d 張 Done" % dropped) if dropped else "",
                     ("，另有 %d 張未列出" % cut) if cut else ""),
    }
