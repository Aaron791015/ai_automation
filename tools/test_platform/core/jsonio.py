"""JSON 原子讀寫（移植自 tools/qixing_Performance/core/run_status.py）。

用途：所有跨程序／跨執行緒共享的 JSON 檔一律走這裡。
    · 寫：先寫 .<pid>.tmp 再 os.replace ——避免另一方讀到「寫到一半」的檔
      （CRUX_Performance 2026-08-03 因就地覆寫遺失過整批統計）
    · Windows 上對方正開著檔案時 os.replace 會 PermissionError，重試 8 次 × 0.05s
    · 讀：遇到破損 JSON 短暫重試再放棄
使用方式：write_json_atomic(path, data) / read_json(path, default=None) / append_jsonl(path, obj)
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


_path_locks: dict[str, threading.Lock] = {}
_path_locks_guard = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    with _path_locks_guard:
        return _path_locks.setdefault(os.path.abspath(path), threading.Lock())


def write_json_atomic(path: str, data: Any, *, indent: int = 2) -> None:
    with _lock_for(path):
        _write_json_atomic_unlocked(path, data, indent=indent)


def _write_json_atomic_unlocked(path: str, data: Any, *, indent: int = 2) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # 同程序內多執行緒（Flask threaded ＋ 各 run 的播放/pump 執行緒）也會同寫一檔，tmp 名要含 thread id
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    last_exc: Exception | None = None
    for _ in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:  # noqa: PERF203
            last_exc = e
            time.sleep(0.05)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if last_exc:
        raise last_exc


def read_json(path: str, default: Any = None, *, retries: int = 3) -> Any:
    if not os.path.isfile(path):
        return default
    for attempt in range(retries):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            if attempt < retries - 1:
                time.sleep(0.05)
    return default


def append_jsonl(path: str, obj: Any) -> None:
    """單行 append（單行寫入天然近似原子；重建才走 write_json_atomic）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: str, *, limit: int | None = None) -> list:
    """從檔尾讀最多 limit 行（None＝全部），忽略壞行。"""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if limit is not None:
        lines = lines[-limit:]
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out
