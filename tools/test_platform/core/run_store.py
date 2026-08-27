"""平台 run 目錄的讀寫：run_meta.json（不可變）／run_status.json（可變，原子寫）／console.log（append）。

用途：所有 adapter 與 web API 存取 run 狀態的唯一路徑；前端輪詢 /api/runs/active
      看到的就是這裡寫出的東西。Demo 與 live 共用同一份程式 —— 這是「假在 adapter，不在前端」的基礎。
使用方式：
    from core import run_store as rs
    rs.new_run_id("crux_perf")           # YYYYMMDD_HHMMSS_<tool_id>（多工具同秒不撞）
    rs.init_run(run_id, meta)            # 建目錄、寫 meta 與初始 status
    rs.update_status(run_id, phase=..., **fields)   # 淺合併 + 原子寫
    rs.read_status(run_id) / rs.read_meta(run_id)
    rs.append_console(run_id, "一行")   / rs.tail_console(run_id, offset)
前置條件：run_status.json 的欄位見計畫 §8 —— 平台 phase（7 值）與工具 phase 分開；summary.kind 為前端渲染分派鍵。
"""
from __future__ import annotations

import os
import time
from datetime import datetime

from core.jsonio import _lock_for, read_json, write_json_atomic
from core.paths import RUNS_DIR

PLATFORM_PHASES = ("queued", "starting", "running", "stopping", "completed", "failed", "stopped")
TERMINAL = {"completed", "failed", "stopped"}
_MERGE_KEYS = ("summary", "metrics", "progress")
_TERMINAL_LABEL = {"completed": "完成", "stopped": "已停止", "failed": "失敗"}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_dir(run_id: str) -> str:
    return os.path.join(RUNS_DIR, run_id)


def meta_path(run_id: str) -> str:
    return os.path.join(run_dir(run_id), "run_meta.json")


def status_path(run_id: str) -> str:
    return os.path.join(run_dir(run_id), "run_status.json")


def console_path(run_id: str) -> str:
    return os.path.join(run_dir(run_id), "console.log")


def new_run_id(tool_id: str) -> str:
    base = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{tool_id}"
    rid = base
    n = 2
    while os.path.exists(run_dir(rid)):
        rid = f"{base}_{n}"
        n += 1
    return rid


def init_run(run_id: str, meta: dict) -> dict:
    d = run_dir(run_id)
    os.makedirs(d, exist_ok=True)
    meta = {"run_id": run_id, "created_at": now_str(), **meta}
    write_json_atomic(meta_path(run_id), meta)
    status = {
        "run_id": run_id, "tool_id": meta.get("tool_id"), "product": meta.get("product"),
        "kind": meta.get("kind"), "tool_name": meta.get("tool_name"), "command_id": meta.get("command_id"),
        "phase": "queued", "tool_phase": None, "tool_phase_label": None, "tool_phase_tone": None,
        "started_at": now_str(), "updated_at": now_str(), "ended_at": None,
        "exit_code": None, "stopped_by_user": False, "stop_reason": None, "forced": False,
        "progress": None, "summary": None, "metrics": {}, "artifacts": [], "error": None, "survivors": [],
        "remark": meta.get("remark", ""),
    }
    write_json_atomic(status_path(run_id), status)
    open(console_path(run_id), "a", encoding="utf-8").close()
    return status


def read_meta(run_id: str) -> dict | None:
    return read_json(meta_path(run_id))


def read_status(run_id: str) -> dict | None:
    return read_json(status_path(run_id))


def update_status(run_id: str, phase: str | None = None, **fields) -> dict:
    # read-modify-write 必須整段互斥（多執行緒同時 update 會互相蓋掉欄位）
    with _lock_for(status_path(run_id)):
        return _update_status_locked(run_id, phase, **fields)


def _update_status_locked(run_id: str, phase: str | None = None, **fields) -> dict:
    from core.jsonio import _write_json_atomic_unlocked
    st = read_status(run_id) or {"run_id": run_id, "phase": "queued"}
    if phase is not None:
        st["phase"] = phase
        if phase in TERMINAL and not st.get("ended_at"):
            st["ended_at"] = now_str()
            # ★ 一處修全部：progress 走淺合併（_MERGE_KEYS），而三條終止路徑
            #   （pytest 完成／停止／補完成）都沒帶 progress，於是舊的 label 原封不動留著 ——
            #   畫面就出現「已完成，但仍寫著『產生 Allure 報告』／『下注中』」。
            #   只在「首次進終態且本次沒帶 progress」這個窄條件補寫，不影響任何正常回報。
            if not isinstance(fields.get("progress"), dict):
                fields["progress"] = {"percent": 100, "label": _TERMINAL_LABEL[phase]}
    for k, v in fields.items():
        if k in _MERGE_KEYS and isinstance(v, dict) and isinstance(st.get(k), dict):
            st[k] = {**st[k], **v}
        else:
            st[k] = v
    st["updated_at"] = now_str()
    _write_json_atomic_unlocked(status_path(run_id), st)
    return st


def append_console(run_id: str, *lines: str, ts: bool = True) -> None:
    with open(console_path(run_id), "a", encoding="utf-8") as f:
        for ln in lines:
            f.write((f"[{time.strftime('%H:%M:%S')}] " if ts else "") + ln.rstrip("\n") + "\n")


def tail_console(run_id: str, offset: int = 0, limit_bytes: int = 262144) -> dict:
    """byte offset 增量讀取（沿用壓測工具的 tail_run_log 契約）：{lines, offset, size}"""
    p = console_path(run_id)
    if not os.path.isfile(p):
        return {"lines": [], "offset": 0, "size": 0}
    size = os.path.getsize(p)
    if offset > size:
        offset = 0
    with open(p, "rb") as f:
        f.seek(offset)
        chunk = f.read(limit_bytes)
    text = chunk.decode("utf-8", errors="replace")
    new_off = offset + len(chunk)
    lines = text.splitlines()
    return {"lines": lines, "offset": new_off, "size": size, "truncated": new_off < size}


def list_run_dirs() -> list[str]:
    if not os.path.isdir(RUNS_DIR):
        return []
    return sorted((d for d in os.listdir(RUNS_DIR) if os.path.isdir(os.path.join(RUNS_DIR, d))), reverse=True)
