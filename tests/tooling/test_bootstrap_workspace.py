# -*- coding: utf-8 -*-
"""`scripts/bootstrap_workspace.py` —— 把範本內建的通用 memory 裝進本機。

用途：memory 在 repo 外面、以 repo 路徑當 key，同事 clone 下來是空的。
      這支腳本補上那一層。三件事要釘住：
      ① **冪等** —— 重跑不覆蓋已存在的 memory（使用者可能已經改過）
      ② **索引不重複** —— MEMORY.md 已有該檔就不再加一行
      ③ 檔案在、索引缺時要能補回來（安裝與索引是兩件事）

前置條件：無，全部在 tmp_path 造假。
使用方式：`pytest tests/tooling/test_bootstrap_workspace.py -q`
"""
import io
import os

import pytest

import bootstrap_workspace as B


SEED_A = u"""---
name: seed-a
description: 甲
metadata:
  type: feedback
---

甲的內容
"""
SEED_B = u"""---
name: seed-b
description: 乙
metadata:
  type: feedback
---

乙的內容
"""
INDEX = u"""# memory-seed 索引

- [甲](seed-a.md) — 甲的鉤子
- [乙](seed-b.md) — 乙的鉤子
"""


def touch(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


@pytest.fixture
def seeds(tmp_path, monkeypatch):
    seed_dir = str(tmp_path / "seed")
    touch(os.path.join(seed_dir, "seed-a.md"), SEED_A)
    touch(os.path.join(seed_dir, "seed-b.md"), SEED_B)
    touch(os.path.join(seed_dir, "_index.md"), INDEX)
    monkeypatch.setattr(B, "SEED_DIR", seed_dir)
    monkeypatch.setattr(B, "INDEX_SEED", os.path.join(seed_dir, "_index.md"))
    return str(tmp_path / "mem")


def read_index(mem):
    p = os.path.join(mem, "MEMORY.md")
    return io.open(p, encoding="utf-8").read() if os.path.isfile(p) else ""


def test_底線開頭的檔案不當種子(seeds):
    assert B.seed_files() == ["seed-a.md", "seed-b.md"]


def test_首次安裝兩則並補索引(seeds):
    installed, skipped, added = B.install(seeds)
    assert installed == ["seed-a.md", "seed-b.md"] and skipped == []
    assert os.path.isfile(os.path.join(seeds, "seed-a.md"))
    idx = read_index(seeds)
    assert u"# Memory Index" in idx
    assert u"[甲](seed-a.md)" in idx and u"[乙](seed-b.md)" in idx


def test_重跑冪等_不覆蓋也不重複加索引(seeds):
    B.install(seeds)
    io.open(os.path.join(seeds, "seed-a.md"), "w",
            encoding="utf-8", newline="\n").write(u"使用者改過的內容")

    installed, skipped, added = B.install(seeds)
    assert installed == [] and skipped == ["seed-a.md", "seed-b.md"]
    assert added == []
    assert io.open(os.path.join(seeds, "seed-a.md"),
                   encoding="utf-8").read() == u"使用者改過的內容"
    assert read_index(seeds).count(u"(seed-a.md)") == 1


def test_檔案在但索引缺時補回來(seeds):
    """安裝與索引是兩件事 —— memory 存在卻沒進索引，等於不會被想起。"""
    B.install(seeds)
    io.open(os.path.join(seeds, "MEMORY.md"), "w",
            encoding="utf-8", newline="\n").write(B.MEMORY_HEADER)

    installed, skipped, added = B.install(seeds)
    assert installed == [] and len(added) == 2
    assert u"[甲](seed-a.md)" in read_index(seeds)


def test_使用者改過索引標題也不會重複加(seeds):
    """判「已收錄」看檔名不看整行，否則改過鉤子就會每次多一條。"""
    B.install(seeds)
    txt = read_index(seeds).replace(u"[甲](seed-a.md) — 甲的鉤子",
                                    u"[我自己的標題](seed-a.md) — 我改的鉤子")
    io.open(os.path.join(seeds, "MEMORY.md"), "w",
            encoding="utf-8", newline="\n").write(txt)

    _, _, added = B.install(seeds)
    assert added == []
    assert read_index(seeds).count(u"(seed-a.md)") == 1


def test_force_會覆蓋(seeds):
    B.install(seeds)
    io.open(os.path.join(seeds, "seed-a.md"), "w",
            encoding="utf-8", newline="\n").write(u"改過")
    installed, skipped, _ = B.install(seeds, force=True)
    assert installed == ["seed-a.md", "seed-b.md"] and skipped == []
    assert u"甲的內容" in io.open(os.path.join(seeds, "seed-a.md"),
                                 encoding="utf-8").read()


def test_dry_run_不寫任何檔(seeds):
    installed, _, added = B.install(seeds, dry_run=True)
    assert installed == ["seed-a.md", "seed-b.md"] and len(added) == 2
    assert not os.path.exists(seeds)


def test_實際種子目錄與索引一致():
    """★ 真的掃 .claude/memory-seed/：每一則種子都要在 _index.md 有一行。

    漏了就是「裝進去了卻不會出現在索引」—— memory 存在但不會被想起，
    正是 memory 這一層要解決的問題。
    """
    names = set(B.seed_files())
    indexed = set(B.index_lines())
    assert names, "找不到任何種子"
    assert names == indexed, u"種子與索引對不上：只在種子=%s／只在索引=%s" % (
        sorted(names - indexed), sorted(indexed - names))
