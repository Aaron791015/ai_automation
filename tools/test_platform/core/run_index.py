"""跨工具 run 索引：logs/runs_index.jsonl（append-only）＋ 自癒重建。

用途：Dashboard「最近 N 次執行」、報告中心、知識雷達外環（24 小時執行熱度）、趨勢圖。
      跑久了會有數百個 run 目錄，每次都 listdir + 讀兩個 JSON 會愈來愈慢；jsonl 從尾端讀 N 行即可。
使用方式：
    from core import run_index as ri
    ri.append_finished(status)               # run 進入 terminal 時 append 一行
    ri.recent(limit=20, product=None, tool=None, status=None)
    ri.rebuild()                              # 目錄數與索引行數不符時自動呼叫（權威來源始終是 run 目錄）
前置條件：Demo 模式下若索引為空，退回 demo/history/runs_index.jsonl（40 筆假歷史）。
"""
from __future__ import annotations

import os
import time

from core.jsonio import append_jsonl, read_json, read_jsonl, write_json_atomic
from core.paths import LOGS_DIR
from core import run_store

INDEX_PATH = os.path.join(LOGS_DIR, "runs_index.jsonl")


def _row_from_status(st: dict, meta: dict | None = None) -> dict:
    meta = meta or {}
    s = st.get("summary") or {}
    headline = ""
    if s.get("kind") == "pytest":
        headline = f"通過 {s.get('passed', 0)}／失敗 {s.get('failed', 0)}／略過 {s.get('skipped', 0)}"
    elif s.get("kind") == "perf":
        headline = f"累計 {s.get('total_bets', 0):,} 注 · 失敗率 {round((s.get('fail_ratio') or 0) * 100, 2)}%"
    elif s.get("kind") == "check":
        headline = s.get("headline", "")
    return {
        "run_id": st["run_id"], "tool_id": st.get("tool_id"), "tool_name": st.get("tool_name"),
        "product": st.get("product"), "kind": st.get("kind"), "command_id": st.get("command_id"),
        "started_at": st.get("started_at"), "ended_at": st.get("ended_at"),
        "duration_sec": _dur(st.get("started_at"), st.get("ended_at")),
        "phase": st.get("phase"), "headline": headline, "remark": st.get("remark", ""),
        "primary_report": next((a.get("href") for a in st.get("artifacts", []) if a.get("primary")), None),
        "summary": {k: v for k, v in s.items() if k in ("kind", "passed", "failed", "skipped", "total_bets", "fail_ratio", "periods_seen")},
    }


def _dur(a: str | None, b: str | None) -> float | None:
    try:
        ta = time.mktime(time.strptime(a, "%Y-%m-%d %H:%M:%S"))
        tb = time.mktime(time.strptime(b, "%Y-%m-%d %H:%M:%S"))
        return round(tb - ta, 1)
    except (TypeError, ValueError):
        return None


def append_finished(st: dict) -> None:
    append_jsonl(INDEX_PATH, _row_from_status(st, run_store.read_meta(st["run_id"])))


def rebuild() -> int:
    rows = []
    for rid in sorted(run_store.list_run_dirs()):
        st = run_store.read_status(rid)
        if st and st.get("phase") in run_store.TERMINAL:
            rows.append(_row_from_status(st, run_store.read_meta(rid)))
    tmp = INDEX_PATH + ".tmp"
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        import json
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, INDEX_PATH)
    return len(rows)


def _ensure_consistent() -> None:
    dirs = [d for d in run_store.list_run_dirs()
            if (run_store.read_status(d) or {}).get("phase") in run_store.TERMINAL]
    rows = read_jsonl(INDEX_PATH)
    if len(rows) != len(dirs):
        rebuild()


def all_rows() -> list[dict]:
    _ensure_consistent()
    rows = read_jsonl(INDEX_PATH)
    return rows


def recent(limit: int = 20, product: str | None = None, tool: str | None = None,
           status: str | None = None, since: str | None = None) -> list[dict]:
    rows = all_rows()
    if product:
        rows = [r for r in rows if r.get("product") == product]
    if tool:
        rows = [r for r in rows if r.get("tool_id") == tool]
    if status:
        rows = [r for r in rows if r.get("phase") == status]
    if since:
        rows = [r for r in rows if (r.get("started_at") or "") >= since]
    rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return rows[:limit]


def hourly_heat(hours: int = 24) -> list[dict]:
    """知識雷達外環：過去 N 小時每小時 {hour, runs, failed, ok}。"""
    now = time.time()
    buckets = [{"hour": time.strftime("%H", time.localtime(now - i * 3600)), "ts": now - i * 3600,
                "runs": 0, "failed": 0, "ok": 0} for i in range(hours - 1, -1, -1)]
    for r in all_rows():
        try:
            t = time.mktime(time.strptime(r["started_at"], "%Y-%m-%d %H:%M:%S"))
        except (KeyError, TypeError, ValueError):
            continue
        age = now - t
        if age < 0 or age > hours * 3600:
            continue
        idx = hours - 1 - int(age // 3600)
        if 0 <= idx < hours:
            b = buckets[idx]
            b["runs"] += 1
            if r.get("phase") == "failed" or (r.get("summary") or {}).get("failed"):
                b["failed"] += 1
            else:
                b["ok"] += 1
    return buckets
