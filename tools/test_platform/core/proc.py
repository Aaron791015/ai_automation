# -*- coding: utf-8 -*-
"""殺整棵程序樹 —— **只有這一份實作**。

用途：對話的「中止這一輪」與壓測的 stop 都要殺到孫程序。
使用方式：`from core.proc import kill_tree`；`kill_tree(pid, force=True)`。
前置條件：有 psutil 更準；沒有時退回 `os.kill`。

⛔ 不要再抄一份：`adapters/cli.py` 原本自己有一支同名的，
   2026-08-28 收斂到這裡（對話的「中止這一輪」也需要同一件事）。

為什麼要整棵樹：子程序會再開孫程序（壓測引擎的 locust worker、
claude 起的 MCP server 與瀏覽器），**只殺父程序的話孫程序會留下來繼續動**
—— 壓測那邊會繼續下注（真金流），對話這邊會留下沒人管的瀏覽器。
"""
import os


def kill_tree(pid, force=False):
    """殺 `pid` 與它底下所有子孫。`force` ＝ 直接 kill，不先 terminate。"""
    try:
        import psutil
        p = psutil.Process(pid)
        for ch in p.children(recursive=True):
            try:
                ch.kill() if force else ch.terminate()
            except psutil.Error:
                pass
        p.kill() if force else p.terminate()
    except Exception:                       # noqa: BLE001 —— 已經死掉是常態
        try:
            os.kill(pid, 9)
        except OSError:
            pass
