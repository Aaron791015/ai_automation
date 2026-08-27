# -*- coding: utf-8 -*-
"""「已確認」標記（2026-08-24 使用者要求）。

> 「報告中心的驗證報告，報告列表需增加『已確認』的勾選框來輔助使用者辨識
>   哪些已經確認完畢，哪些還沒看」

## 為什麼是獨立一份檔，而不是寫進報告本身

報告在 `docs/<產品>/bugs/_reports/`，那一層**整層不版控**（含測試站帳密），
而且它是**產出**：內容代表「當時驗到什麼」，不該因為誰看過了就被改動。
「我看過了」是**閱讀狀態**，屬於這台平台、屬於這個人 —— 兩者生命週期不同，
所以分開存。

## 為什麼記 mtime 而不是只記「看過」

報告會被**重寫**（同一天第二批、補截圖、改結論）。只記「看過」的話，
內容變了畫面還是綠的 —— 那比沒有標記更糟，因為它會讓人**跳過**新內容。
所以記下確認當下的 `mtime`，檔案再被動過就自動退回「未確認」並標「已更新」。

使用方式：
    from core import acks
    acks.status(["docs/A/bugs/_reports/x.md"])   # {path: {acked, at, stale}}
    acks.set_ack(path, True, mtime)
"""
from __future__ import annotations

import os
import time

from core.jsonio import read_json, write_json_atomic
from core.paths import LOGS_DIR

STORE = os.path.join(LOGS_DIR, "acks.json")


def _load() -> dict:
    return (read_json(STORE, {}) or {}).get("acks") or {}


def _save(acks: dict) -> None:
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    write_json_atomic(STORE, {"acks": acks, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})


def status(paths: list) -> dict:
    """回 {path: {"acked": bool, "at": str, "stale": bool}}。

    `stale` ＝ **確認過、但檔案之後又被改了** —— 這種要退回未確認並講明原因，
    否則人會以為自己看過的就是現在這一份。
    """
    acks = _load()
    out = {}
    for p in paths:
        rec = acks.get(p)
        if not rec:
            out[p] = {"acked": False, "at": "", "stale": False}
            continue
        stale = False
        try:
            cur = int(os.path.getmtime(os.path.join(_repo_root(), *p.split("/"))))
            stale = bool(rec.get("mtime")) and cur > int(rec["mtime"])
        except OSError:
            pass
        out[p] = {"acked": not stale, "at": rec.get("at", ""), "stale": stale}
    return out


def set_ack(path: str, acked: bool, mtime: int | None = None) -> dict:
    """標記／取消標記。回這一筆的新狀態。"""
    acks = _load()
    if acked:
        if mtime is None:
            try:
                mtime = int(os.path.getmtime(os.path.join(_repo_root(), *path.split("/"))))
            except OSError:
                mtime = 0
        acks[path] = {"at": time.strftime("%Y-%m-%d %H:%M"), "mtime": int(mtime or 0)}
    else:
        acks.pop(path, None)
    _save(acks)
    return status([path])[path]


def _repo_root() -> str:
    from core.paths import REPO_ROOT
    return REPO_ROOT
