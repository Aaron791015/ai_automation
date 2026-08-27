# -*- coding: utf-8 -*-
"""`scripts/reset_workspace.py` —— 把範本原型的產品實例清乾淨。

用途：這是**破壞性且不可逆**的腳本（`docs/<產品>/bugs/` 整層不版控，刪了沒 git 可救），
      所以三件事一定要釘住：
      ① 只刪**該產品宣告過的**路徑，不碰通用層
      ② `extra_paths`（壓測工具、探索腳本）不能漏 —— 漏了會留下孤兒目錄
      ③ 預設 dry-run，且 working tree 不乾淨時要擋下來

前置條件：無，全部在 tmp_path 造假工作區。
使用方式：`pytest tests/tooling/test_reset_workspace.py -q`
"""
import io
import json
import os

import pytest

import reset_workspace as R


def touch(path, text=u"x"):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


PRODUCTS = {
    "products": [
        {"id": "甲", "docs_dir": "Alpha", "tests_dir": "alpha",
         "qa_tools_dir": "alpha_qa", "skill": "alpha", "bug_prefix": "ALPHA",
         "extra_paths": ["tools/Alpha_Performance", "scripts/explore_alpha.py"]},
        {"id": "乙", "docs_dir": "Beta", "tests_dir": "beta",
         "qa_tools_dir": "beta_qa", "skill": "beta", "bug_prefix": "BETA"},
    ],
    "common_handovers": ["docs/共通_工作區維護交接.md"],
}


@pytest.fixture
def root(tmp_path):
    r = str(tmp_path)
    touch(os.path.join(r, "config", "products.json"),
          json.dumps(PRODUCTS, ensure_ascii=False, indent=2))
    for rel in ["docs/Alpha/bugs/單.md", "docs/Beta/機制.md",
                "tests/alpha/test_a.py", "tests/beta/test_b.py",
                "tools/alpha_qa/pages/p.py", "tools/beta_qa/x.py",
                "tools/Alpha_Performance/runner.py", "scripts/explore_alpha.py",
                ".claude/skills/alpha/SKILL.md", ".claude/skills/beta/SKILL.md",
                # ── 通用層，一律不得被碰 ──
                ".claude/skills/handoff/SKILL.md", "scripts/lint_docs.py",
                "tools/qa_common/shot.py", "tests/tooling/test_x.py",
                "docs/INDEX.md", "docs/共通_工作區維護交接.md"]:
        touch(os.path.join(r, rel.replace("/", os.sep)))
    return r


def exists(root, rel):
    return os.path.exists(os.path.join(root, rel.replace("/", os.sep)))


def test_計畫涵蓋標準四處與_extra_paths(root):
    targets, removed = R.plan(root)
    assert len(removed) == 2
    for rel in ["docs/Alpha", "tests/alpha", "tools/alpha_qa", ".claude/skills/alpha",
                "tools/Alpha_Performance", "scripts/explore_alpha.py",
                "docs/Beta", "tests/beta", "tools/beta_qa", ".claude/skills/beta"]:
        assert rel in targets, rel


def test_計畫不含通用層(root):
    targets, _ = R.plan(root)
    for rel in [".claude/skills/handoff", "scripts/lint_docs.py",
                "tools/qa_common", "tests/tooling", "docs/INDEX.md"]:
        assert rel not in targets, rel


def test_只清一個產品時另一個不受影響(root):
    targets, removed = R.plan(root, only="甲")
    assert [p["id"] for p in removed] == ["甲"]
    left = R.apply_plan(root, targets, removed)

    assert not exists(root, "docs/Alpha")
    assert not exists(root, "tools/Alpha_Performance")
    assert not exists(root, "scripts/explore_alpha.py")
    assert exists(root, "docs/Beta") and exists(root, ".claude/skills/beta")
    assert left == 1

    data = json.load(io.open(os.path.join(root, "config", "products.json"),
                             encoding="utf-8"))
    assert [p["id"] for p in data["products"]] == ["乙"]


def test_只清一個產品時不重設_INDEX(root):
    """還有別的產品在，INDEX 裡有它們的條目，不能整份洗掉。"""
    targets, removed = R.plan(root, only="甲")
    R.apply_plan(root, targets, removed)
    assert io.open(os.path.join(root, "docs", "INDEX.md"),
                   encoding="utf-8").read() == u"x"


def test_全清空才重設_INDEX_且通用層仍在(root):
    targets, removed = R.plan(root)
    left = R.apply_plan(root, targets, removed)
    assert left == 0

    index = io.open(os.path.join(root, "docs", "INDEX.md"), encoding="utf-8").read()
    assert u"docs 文件索引" in index and u"共通（工作區維護" in index

    assert exists(root, ".claude/skills/handoff/SKILL.md")
    assert exists(root, "tools/qa_common/shot.py")
    assert exists(root, "tests/tooling/test_x.py")
    assert exists(root, "docs/共通_工作區維護交接.md")


def test_不存在的路徑不會進計畫(root):
    """乙沒有 extra_paths，也沒有壓測工具 —— 不該憑空生出目標。"""
    targets, _ = R.plan(root, only="乙")
    assert all(exists(root, t) for t in targets)


def test_髒的_worktree_會被偵測到(root, monkeypatch):
    monkeypatch.setattr(R.subprocess, "check_output",
                        lambda *a, **k: b" M docs/Alpha/x.md\n?? new.py\n")
    assert len(R.worktree_dirty(root)) == 2


def test_非_git_目錄不擋(root, monkeypatch):
    def boom(*a, **k):
        raise OSError("not a repo")
    monkeypatch.setattr(R.subprocess, "check_output", boom)
    assert R.worktree_dirty(root) == []
