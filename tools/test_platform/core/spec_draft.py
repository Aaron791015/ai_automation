"""案例 draft：需求 → 案例清單 → （人工調整）→ 產碼 的中間態。

用途：動線 D 的資料骨幹。一份 draft ＝ 一次需求輸入 ＋ 它生出來的一批案例。
使用方式：
    from core import spec_draft
    d = spec_draft.create(requirement="…", product="crux", source_ref="docs/CRUX/…md")
    spec_draft.put_cases(d["id"], cases)      # 生成器或人工編輯的結果
    spec_draft.get(d["id"]) / spec_draft.recent()
前置條件：存 logs/drafts/<draft_id>.json（run 產物，不版控）。

一條案例的結構（`case`）：
    {id, title, product, surface, preconditions[], steps[], expected, markers[],
     template_from（參考了哪條既有案例的結構）, pom_hints[], confidence, note}
"""
from __future__ import annotations

import os
import re
import time

from core.jsonio import read_json, write_json_atomic
from core.paths import DRAFTS_DIR


def _new_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"


def _path(draft_id: str) -> str:
    if not re.fullmatch(r"[0-9_]{10,25}", draft_id or ""):
        raise ValueError("draft_id 格式不合法")
    return os.path.join(DRAFTS_DIR, f"{draft_id}.json")


def create(*, requirement: str, product: str, source_ref: str = "", title: str = "") -> dict:
    d = {"id": _new_id(), "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "title": title or (requirement or "").strip().splitlines()[0][:60] or "未命名需求",
         "requirement": requirement or "", "product": product, "source_ref": source_ref,
         "cases": [], "generated_by": None, "committed": []}
    write_json_atomic(_path(d["id"]), d)
    return d


def get(draft_id: str) -> dict | None:
    return read_json(_path(draft_id))


def save(d: dict) -> dict:
    d["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json_atomic(_path(d["id"]), d)
    return d


def put_cases(draft_id: str, cases: list[dict], *, generated_by: str | None = None) -> dict:
    d = get(draft_id)
    if not d:
        raise ValueError("找不到 draft")
    # 補流水 id，讓前端可以穩定地增刪改
    for i, c in enumerate(cases, 1):
        c.setdefault("id", f"C{i:02d}")
    d["cases"] = cases
    if generated_by:
        d["generated_by"] = generated_by
    return save(d)


def recent(limit: int = 20) -> list[dict]:
    if not os.path.isdir(DRAFTS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(DRAFTS_DIR), reverse=True)[:limit]:
        if fn.endswith(".json"):
            d = read_json(os.path.join(DRAFTS_DIR, fn))
            if d:
                out.append({k: d.get(k) for k in
                            ("id", "title", "product", "created_at", "updated_at", "generated_by")}
                           | {"case_count": len(d.get("cases") or []),
                              "committed": len(d.get("committed") or [])})
    return out


def delete(draft_id: str) -> bool:
    p = _path(draft_id)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False
