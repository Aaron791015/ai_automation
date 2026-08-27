# -*- coding: utf-8 -*-
"""`scripts/lint_docs.py` 的 D8「skill 交叉引用的章節指標」—— 特別是**子項**那一層。

用途：D8 原本只驗到章節層（`§N.M`），子項改動不會被發現。
      2026-08-22 實際踩到：`writeback` §6 指向 `handoff` §2③，
      但 lint 那段其實在 §2④（③ 是狀態交接）—— 當時 D8 全綠。
      這組測試釘住兩件事：**該叫的時候叫**（子項不存在），
      **不該叫的時候閉嘴**（章節根本沒有標題型子項時一律跳過，寧可漏報不要誤報）。

前置條件：無，全部用 tmp_path 造假 skill 樹。
使用方式：`pytest tests/tooling/test_lint_docs_refs.py -q`
"""
import io
import os

import pytest

import lint_docs


def _write(path, text):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


HANDOFF = u"""# 開工與收尾

## 1. 開工 checklist

### A. 開場必做

### B. 依任務觸發

## 2. 收尾 checklist

### ① 判斷能不能發

### ② 知識回寫

### ③ 狀態交接

### ④ 跑 lint
"""

# 子項寫成粗體條列而非標題 —— 偵測不到，應跳過不驗
COMMIT = u"""# commit

## 8. 流程

**A. 許可前：唯讀預檢**

**B. 許可後：暫存 → 提交**
"""


@pytest.fixture
def skills(tmp_path, monkeypatch):
    """造一棵假的 .claude/skills/ 並把 lint_docs 指過去。"""
    root = str(tmp_path)
    sk = os.path.join(root, ".claude", "skills")
    _write(os.path.join(sk, "handoff", "SKILL.md"), HANDOFF)
    _write(os.path.join(sk, "commit", "SKILL.md"), COMMIT)
    _write(os.path.join(root, "CLAUDE.md"), u"# 規則\n\n## 5. 測試\n\n## 8. 版控\n")
    monkeypatch.setattr(lint_docs, "ROOT", root)
    monkeypatch.setattr(lint_docs, "SKILLS", sk)

    def put(name, body):
        _write(os.path.join(sk, name, "SKILL.md"), body)
    return put


def test_子項存在時不報(skills):
    skills("writeback", u"# w\n\n## 1. 分流\n\n收尾見 `handoff` §2④ 那張表。\n")
    assert lint_docs.check_skill_refs() == []


def test_子項不存在時要報(skills):
    skills("writeback", u"# w\n\n## 1. 分流\n\n收尾見 `handoff` §2⑧ 那張表。\n")
    errs = lint_docs.check_skill_refs()
    assert len(errs) == 1
    assert u"§2⑧" in errs[0]
    assert u"①②③④" in errs[0]          # 錯誤訊息要列出實際有哪些子項


def test_字母子項也驗(skills):
    skills("writeback", u"# w\n\n## 1. 分流\n\n開工見 `handoff` §1 D 的說明。\n")
    errs = lint_docs.check_skill_refs()
    assert len(errs) == 1 and u"§1D" in errs[0]

    skills("writeback", u"# w\n\n## 1. 分流\n\n開工見 `handoff` §1 A 的說明。\n")
    assert lint_docs.check_skill_refs() == []


def test_章節無標題型子項時跳過不誤報(skills):
    """`commit` §8 的 A/B 是粗體條列不是標題 —— 偵測不到就別叫。"""
    skills("writeback", u"# w\n\n## 1. 分流\n\n見 `commit` §8 A 與 `commit` §8 Z。\n")
    assert lint_docs.check_skill_refs() == []


def test_章節本身不存在仍照報(skills):
    skills("writeback", u"# w\n\n## 1. 分流\n\n見 `handoff` §9④。\n")
    errs = lint_docs.check_skill_refs()
    assert len(errs) == 1 and u"沒有這一節" in errs[0]


def test_references_也會被掃到(skills, tmp_path):
    """references/ 底下的檔案同樣會寫章節指標，不能漏掃。"""
    skills("writeback", u"# w\n\n## 1. 分流\n")
    _write(os.path.join(str(tmp_path), ".claude", "skills", "writeback",
                        "references", "範例.md"),
           u"# 範例\n\n見 `handoff` §2⑧。\n")
    errs = lint_docs.check_skill_refs()
    assert len(errs) == 1 and u"範例.md" in errs[0]
