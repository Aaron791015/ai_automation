"""run 管理：多 run 並行的 registry dict ＋ 三層併發策略 ＋ 佔位在啟動前。

用途：web API 啟停 run 的唯一入口。既有三個壓測工具是「模組層單一 _active_process」；
      平台合成多 run 後必須改成 dict，並新增跨工具互斥（exclusive_group）—— 兩個 CRUX 壓測同時打
      同一 QAT 站台會互相污染統計、兩個 pytest run 會搶 wbot_current_target.json。
使用方式：
    from runner import manager
    manager.start(spec, command, params, remark, selection) → status dict（含 run_id）
    manager.stop(run_id, force, reason) / manager.active() / manager.get(run_id)
    manager.on_finished(run_id)  ← adapter 在 run 進入 terminal 時呼叫，釋放佔位
前置條件：
    · 佔位（_runs[run_id] = ...）在 adapter.start() **之前**，否則兩個並行請求會雙雙通過檢查
      （既有 start_run 有這個競態窗口，只是單使用者不易踩到）。
    · 衝突 raise ConflictError（web 層轉 409，帶 blocking_run_id／blocking_tool）。
    · 剛結束的 run 保留 recent_run_keep_minutes（預設 15 分）供 Dashboard 顯示。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from adapters import get_adapter
from adapters.base import StartRequest
from core import run_store as rs
from core.config import load_config
from core.registry import get_registry


class ConflictError(Exception):
    def __init__(self, message: str, blocking_run_id: str | None = None, blocking_tool: str | None = None):
        super().__init__(message)
        self.blocking_run_id = blocking_run_id
        self.blocking_tool = blocking_tool


@dataclass
class RunRecord:
    run_id: str
    tool_id: str
    product: str
    exclusive_group: str | None
    started_ts: float = field(default_factory=time.time)
    ended_ts: float | None = None
    adapter: object = None


_runs: dict[str, RunRecord] = {}
_lock = threading.RLock()


def products_from_selection(flat, selection, *, dedupe: bool = True) -> list[str]:
    """依選取案例的 nodeid 反推所屬產品。

    兩個消費者共用同一份邏輯，免得日後分歧：
      · `web_ui/api/runs.py` 注入虛擬欄位 `_products`（給 visible_when 判斷該顯示哪一組環境欄位）
      · 本檔 `start()` 推 run meta 的 product（那裡要多數決，故 dedupe=False 保留重複）
    """
    by = {c["nodeid"]: c.get("product") for c in (flat or [])}
    out: list[str] = []
    for n in selection or []:
        p = by.get(n)
        if p and (not dedupe or p not in out):
            out.append(p)
    return out


def _acquire_slot(spec, run_id: str) -> None:
    run_cfg = spec.run
    with _lock:
        live = [r for r in _runs.values() if r.ended_ts is None]
        if run_cfg.get("concurrency", "single") == "single":
            for r in live:
                if r.tool_id == spec.id:
                    raise ConflictError(f"{spec.name} 已有進行中的 run：{r.run_id}", r.run_id, r.tool_id)
        else:
            mp = int(run_cfg.get("max_parallel", 4))
            if sum(1 for r in live if r.tool_id == spec.id) >= mp:
                raise ConflictError(f"{spec.name} 同時最多 {mp} 個 run", None, spec.id)
        grp = run_cfg.get("exclusive_group")
        if grp:
            for r in live:
                if r.exclusive_group == grp and r.tool_id != spec.id:
                    other = get_registry().tools.get(r.tool_id)
                    raise ConflictError(f"{other.name if other else r.tool_id} 的 run {r.run_id} 正佔用互斥群組「{grp}」", r.run_id, r.tool_id)
        _runs[run_id] = RunRecord(run_id=run_id, tool_id=spec.id, product=spec.product, exclusive_group=grp)


def start(spec, command: dict, params: dict, *, remark: str = "", selection: list[str] | None = None,
          profile_id: str | None = None, ctx: dict | None = None) -> dict:
    adapter = get_adapter(spec, ctx)
    clean = adapter.validate(command, params)
    run_id = rs.new_run_id(spec.id)
    _acquire_slot(spec, run_id)          # ★ 佔位在 start 之前
    try:
        product = clean.get("product") or spec.product
        if spec.kind == "pytest" and selection:
            # 依選取案例推產品（多產品混選時取多數）
            idx = adapter.list_cases() or {}
            prods = [p for p in (products_from_selection(idx.get("flat"), selection, dedupe=False))]
            if prods:
                product = max(set(prods), key=prods.count)
        meta = {
            "tool_id": spec.id, "tool_name": spec.name, "product": product, "kind": spec.kind,
            "command_id": command["id"], "command_label": command.get("label"),
            "params": _redact(command, clean), "remark": remark, "profile_id": profile_id,
            "selection_count": len(selection or []), "demo": adapter.kind == "fake",
            "exclusive_group": spec.run.get("exclusive_group"),
        }
        rs.init_run(run_id, meta)
        if selection:
            with open(rs.run_dir(run_id) + "/selection.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(selection))
        req = StartRequest(tool_id=spec.id, command_id=command["id"], params=clean, run_id=run_id,
                           platform_run_dir=rs.run_dir(run_id), profile_id=profile_id, remark=remark,
                           selection=selection or [])
        with _lock:
            _runs[run_id].adapter = adapter
        adapter.start(req)
        rs.update_status(run_id, phase="starting")
        return rs.read_status(run_id) or {"run_id": run_id}
    except Exception:
        with _lock:
            _runs.pop(run_id, None)
        raise


def _redact(command: dict, params: dict) -> dict:
    secrets = {f["key"] for f in (command.get("params") or {}).get("fields", []) if f.get("type") == "secret" or f.get("never_persist")}
    return {k: ("***" if k in secrets else v) for k, v in params.items()}


def stop(run_id: str, *, force: bool = False, reason: str = "user") -> dict:
    with _lock:
        rec = _runs.get(run_id)
    if not rec or rec.adapter is None:
        st = rs.read_status(run_id)
        if st and st.get("phase") in rs.TERMINAL:
            return {"ok": False, "error": "該 run 已結束"}
        return {"ok": False, "error": "找不到進行中的 run（可能是平台重啟前啟動的）"}
    return rec.adapter.stop(run_id, force=force, reason=reason)


def on_finished(run_id: str) -> None:
    with _lock:
        rec = _runs.get(run_id)
        if rec:
            rec.ended_ts = time.time()


def _sweep() -> None:
    keep = int(load_config().get("recent_run_keep_minutes", 15)) * 60
    now = time.time()
    with _lock:
        for rid in [r.run_id for r in _runs.values() if r.ended_ts and now - r.ended_ts > keep]:
            _runs.pop(rid, None)


def active(include_recent: bool = True) -> list[dict]:
    """進行中的 run（＋剛結束保留 N 分鐘的），供 Dashboard 單一輪詢端點。"""
    _sweep()
    with _lock:
        recs = list(_runs.values())
    out = []
    for r in recs:
        if r.ended_ts and not include_recent:
            continue
        st = rs.read_status(r.run_id)
        if st:
            st["_recent"] = r.ended_ts is not None
            out.append(st)
    out.sort(key=lambda s: s.get("started_at") or "", reverse=True)
    return out


def get(run_id: str) -> dict | None:
    return rs.read_status(run_id)


def is_live(run_id: str) -> bool:
    with _lock:
        r = _runs.get(run_id)
    return bool(r and r.ended_ts is None)
