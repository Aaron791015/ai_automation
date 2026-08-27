# -*- coding: utf-8 -*-
"""`tools/test_platform/core/worktree.py` —— 「這一輪工作區動了哪些檔」。

用途：平台 session 2026-08-25 起有 shell 與寫檔，它**直接改的檔草稿模型看不見**。
      這支是唯一的問責機制，兩件事要釘住：
        ① 比對得出「新出現／狀態變了」的路徑（不能把跑之前就在的異動算成這一輪的）
        ② 取不到 git 時**失效方向是「沒有這一段」**，不是讓整輪失敗

前置條件：無（subprocess 全部換掉，不碰真的 git）。
"""
import importlib.util
import os
import subprocess

import pytest

_MOD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools", "test_platform", "core", "worktree.py")


@pytest.fixture
def W(monkeypatch):
    """依檔案路徑載入 —— ⛔ 不可在模組層改 `sys.path`（會綁死 `core`，見 test_collect_all_roots）。"""
    import sys
    plat = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tools", "test_platform")
    monkeypatch.syspath_prepend(plat)          # fixture 內插入：收集期不受影響
    spec = importlib.util.spec_from_file_location("wt_under_test", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fake_status(text):
    return lambda *a, **k: text.encode("utf-8")


def test_解析porcelain(W, monkeypatch):
    monkeypatch.setattr(subprocess, "check_output",
                        fake_status(" M docs/a.md\n?? 新檔.py\nA  b.txt\n"))
    assert W.snapshot() == {"docs/a.md": " M", "新檔.py": "??", "b.txt": "A "}


def test_只回這一輪新出現或變了的(W, monkeypatch):
    """⛔ 跑之前就髒的檔不算這一輪的 —— 否則每一輪都會把別人的異動算到它頭上。"""
    before = {"舊的.md": " M", "兩邊都有.py": " M"}
    monkeypatch.setattr(subprocess, "check_output",
                        fake_status(" M 舊的.md\n M 兩邊都有.py\n?? 這輪新增.py\nM  這輪變了.md\n"))
    assert W.changed_since(before) == ["這輪新增.py", "這輪變了.md"]


def test_狀態碼變了也算(W, monkeypatch):
    """`?? → A ` 之類的轉變同樣是「這一輪動過」。"""
    monkeypatch.setattr(subprocess, "check_output", fake_status("A  x.py\n"))
    assert W.changed_since({"x.py": "??"}) == ["x.py"]


def test_取不到git時整段消失而不是壞掉(W, monkeypatch):
    def boom(*a, **k):
        raise OSError("沒有 git")
    monkeypatch.setattr(subprocess, "check_output", boom)
    assert W.snapshot() is None
    assert W.changed_since({"a": " M"}) == []


def test_跑之前就取不到快照時不臆測(W, monkeypatch):
    """before 是 None（例如不是 repo）→ 回空，不要把「現在髒的」全部當成這一輪改的。"""
    monkeypatch.setattr(subprocess, "check_output", fake_status(" M 一堆.md\n"))
    assert W.changed_since(None) == []


def test_不碰索引(W, monkeypatch):
    """⛔ 只准 `status` —— 索引是整個工作目錄共用的（`commit` skill §0 第 2 條）。"""
    seen = {}

    def spy(argv, *a, **k):
        seen["argv"] = argv
        return b""
    monkeypatch.setattr(subprocess, "check_output", spy)
    W.snapshot()
    assert "status" in seen["argv"]
    for bad in ("add", "commit", "stash", "reset"):
        assert bad not in seen["argv"]
