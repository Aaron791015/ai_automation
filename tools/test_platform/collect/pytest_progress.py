# -*- coding: utf-8 -*-
"""pytest plugin：把執行進度 append 成 `progress.jsonl`（供測試助手的 run 頁即時顯示）。

用途：平台跑 pytest 時要即時知道「跑到第幾條、過了幾條、哪幾條紅」。
使用方式（由 `adapters/pytest_.py` 以 subprocess 帶入）：
    <python> -m pytest -v -p no:cacheprovider \\
        -p tools.test_platform.collect.pytest_progress \\
        --progress-out=<run 目錄>/progress.jsonl \\
        --alluredir=<run 目錄>/allure-results

前置條件（三條，違反任何一條都會靜默壞掉）：
    · ⛔ **只准 stdlib，且絕不呼叫 `core.run_store.update_status()`** ——
      `core/jsonio.py` 的鎖是 `threading.Lock`（**程序內**），
      這裡是**另一個程序**，兩邊同時 read-modify-write `run_status.json` 會互相蓋掉。
      本 plugin 只做 append（O_APPEND 的單行寫入是原子的），
      由父程序當唯一寫入者去更新 run_status。
    · ⛔ **本檔不進 pyproject 的 addopts** —— 一般執行不該產生 progress.jsonl。
    · ★ **命令列要再給一次 `--alluredir`** 指向該 run 的目錄，
      覆蓋 pyproject 無條件帶的 `reports/allure-results`（argparse 後者覆蓋前者）。
      不這麼做的話**所有 run 的 allure 結果會互相污染**，還會弄髒工作區的正式 reports/。
      ⚠️ 不要用 `-p no:allure_pytest`（那會讓 allure marker 註冊失敗而噴 warning）。
"""
from __future__ import annotations

import json
import os
import time


def pytest_addoption(parser):
    parser.addoption("--progress-out", action="store", default=None,
                     help="進度 jsonl 的輸出路徑（測試助手用）")


class _Progress:
    """每個測試結果 append 一行 JSON。

    ⚠️ 只用 `open(..., 'a')` ＋ 單行寫入 —— **不做 read-modify-write**，
      父程序才能安全地邊讀邊算（見檔頭第一條前置條件）。
    """

    def __init__(self, out):
        self.out = out
        self.total = 0
        self.done = 0
        self.counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        self.failed_cases = []
        self.titles = {}

    # 收集完成 → 知道總數
    def pytest_collection_finish(self, session):
        self.total = len(session.items)
        for it in session.items:
            doc = (getattr(it, "function", None).__doc__ or "").strip() if getattr(it, "function", None) else ""
            self.titles[it.nodeid] = (doc.splitlines()[0].strip() if doc else it.name)[:80]
        self._emit({"event": "collected", "total": self.total})

    # 每條測試的結果
    def pytest_runtest_logreport(self, report):
        # 只算「決定成敗」的那一階段：setup 出錯算 error，call 決定 pass/fail，
        # teardown 的 skip 不重複計。
        if report.when == "setup" and report.failed:
            self._count(report.nodeid, "error", report)
        elif report.when == "setup" and report.skipped:
            self._count(report.nodeid, "skipped", report)
        elif report.when == "call":
            self._count(report.nodeid, "failed" if report.failed else "passed", report)

    def _count(self, nodeid, outcome, report):
        self.done += 1
        self.counts[outcome] = self.counts.get(outcome, 0) + 1
        if outcome in ("failed", "error"):
            msg = ""
            try:
                msg = str(report.longrepr.reprcrash.message)[:400]
            except Exception:
                msg = str(getattr(report, "longrepr", ""))[:400]
            self.failed_cases.append({"nodeid": nodeid,
                                      "title": self.titles.get(nodeid, ""),
                                      "message": msg})
        self._emit({
            "event": "test", "nodeid": nodeid, "outcome": outcome,
            "title": self.titles.get(nodeid, ""),
            "done": self.done, "total": self.total,
            "counts": dict(self.counts),
            "duration": round(getattr(report, "duration", 0.0), 3),
        })

    def pytest_sessionfinish(self, session, exitstatus):
        self._emit({
            "event": "finished", "exitstatus": int(exitstatus),
            "done": self.done, "total": self.total,
            "counts": dict(self.counts),
            "failed_cases": self.failed_cases[:200],
        })

    def _emit(self, obj):
        obj["ts"] = time.time()
        try:
            # ⚠️ 每次都重開 ＋ 立即 flush：run 中途被殺掉時，已寫的行仍然完整。
            with open(self.out, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                f.flush()
        except OSError:
            pass          # 進度回報壞掉不該讓測試本身失敗


def pytest_configure(config):
    out = config.getoption("--progress-out")
    if not out:
        return
    d = os.path.dirname(out)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    config.pluginmanager.register(_Progress(out), "test-platform-progress")
