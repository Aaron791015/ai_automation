# -*- coding: utf-8 -*-
"""把 run 的 allure 結果送進 `scripts/analyze_run.py` 分三類。

用途：allure 只告訴你「幾條紅」，發版判斷要的是「**新壞的**有幾條」——
      真失敗／前置未備／環境問題三類的處置完全不同，而其中一大部分
      早就有對應的 Bug 單。

⛔ **本檔不自己判斷任何一條規則** —— 規則全在 `scripts/analyze_run.py`
   （終端機的 `python scripts\\analyze_run.py` 用的是同一份）。
   平台再寫一份的話兩邊遲早漂移，而症狀是「終端機說環境問題、平台說真失敗」，
   沒有人知道該信哪個。

前置條件：run 目錄下要有 `allure-results/`（`PytestAdapter` 會用
          `--alluredir <run 目錄>` 覆蓋 pyproject 的 addopts）。
"""
from __future__ import annotations

import os
import sys

from core.paths import REPO_ROOT

_SCRIPTS = os.path.join(REPO_ROOT, "scripts")

_KIND_LABEL = {
    "real": "真失敗",
    "prereq": "前置未備",
    "env": "環境問題",
}


def _analyze_run():
    """延遲 import —— 平台不該在載入時就相依 `scripts/`。"""
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    import analyze_run
    return analyze_run


def classify_run(run_dir: str, product: str | None = None) -> dict | None:
    """回 {counts, items, matched} —— 沒有 allure 結果就回 None。

    · counts  {real, prereq, env}
    · items   [{name, kind, kind_label, msg, bug_id?, bug_status?, matched_by?}]
    · matched 已對應到既有 Bug 單的筆數
    """
    results = os.path.join(run_dir, "allure-results")
    if not os.path.isdir(results):
        return None
    try:
        ar = _analyze_run()
    except Exception:
        return None                       # 缺相依時不要讓整個 run 收尾失敗

    recs = [r for r in ar.load_results(results) if r["status"] not in ("passed", "unknown")]
    if not recs:
        return {"counts": {"real": 0, "prereq": 0, "env": 0}, "items": [], "matched": 0}

    bugs = []
    if product:
        try:
            bugs = ar.known_bugs(product)
        except Exception:
            bugs = []

    counts = {"real": 0, "prereq": 0, "env": 0}
    items, matched = [], 0
    for r in recs:
        kind = ar.classify(r)
        counts[kind] = counts.get(kind, 0) + 1
        item = {"name": r.get("name") or r.get("full"), "kind": kind,
                "kind_label": _KIND_LABEL.get(kind, kind),
                "msg": (r.get("msg") or "")[:200]}
        hit = ar.match_known(r, bugs) if bugs else None
        if hit:
            matched += 1
            item.update(bug_id=hit[0], bug_status=hit[1], matched_by=hit[2])
        items.append(item)
    return {"counts": counts, "items": items, "matched": matched}


def summary_line(analysis: dict | None) -> str:
    """一句話摘要，給 run 卡片用。"""
    if not analysis:
        return ""
    c = analysis["counts"]
    total = sum(c.values())
    if not total:
        return "沒有失敗"
    parts = ["%s %d" % (_KIND_LABEL[k], c[k]) for k in ("real", "prereq", "env") if c.get(k)]
    tail = "，其中 %d 條已有對應 Bug 單" % analysis["matched"] if analysis["matched"] else ""
    return "、".join(parts) + tail
