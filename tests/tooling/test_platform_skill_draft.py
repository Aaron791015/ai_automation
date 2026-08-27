# -*- coding: utf-8 -*-
"""產品 skill 的回寫（`kind: skill`，2026-08-24 使用者裁示）。

## 為什麼要有這一支

`writeback` skill「回寫完成的四個必做」第 2 條寫著：

> **產品 skill 補一列意圖對照**，以「使用者會怎麼問」為鍵

但**平台起的 session 做不到** —— 它沒有 `Write`／`Edit`
（而且 `Write` 在 `claude_session.DENIED_TOOLS` 裡，加白名單也放不行），
草稿又只能落到 `docs/<產品>/`。同一條規範，走終端機會做、走平台默默漏掉。

## 兩節的處置刻意不同（使用者 2026-08-24 裁示）

| 節 | 處置 | 為什麼 |
| --- | --- | --- |
| §2 **意圖對照**（指路） | ✅ 自動 | 只說「去哪看」——人點過去就發現對不對，**會自我修正** |
| §1 **不變量**（規則） | ⏸️ 要人按 | Claude **每次對話開場都讀它**。寫錯會讓之後所有 session 照錯的做，而且沒人會發現——大家都相信那是規則 |

⚠️ §1 那張表裡已經有「這是規格，不是 bug，勿重開」這種列（CRUX 第 16、17 條）——
那是**使用者的裁定**。`CLAUDE.md`「實測與文件不符時」講的就是這個失效模式。

使用方式：`pytest tests/tooling/test_platform_skill_draft.py -q`
"""
import io
import os
import sys

import pytest

import conftest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _D():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import doc_draft
    return doc_draft


def _P():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import draft_parse
    return draft_parse


# ── ⭐ 這一節的核心裁示 ────────────────────────────────
def test_意圖對照自動寫入():
    ok, why = _D().is_auto_safe({"kind": "skill", "section": "intent",
                                 "product": "x", "cells": ["a", "b"]})
    assert ok, why


def test_不變量一律要人按():
    """★ 判準不是「重不重要」，是**錯了要付什麼代價**。

    不變量寫錯 → 之後**每一個** session 開場都讀到它 → 大家停止懷疑那件事。
    """
    ok, why = _D().is_auto_safe({"kind": "skill", "section": "invariant",
                                 "product": "x", "cells": ["a", "b"]})
    assert not ok
    assert "不變量" in why and "確認" in why


def test_沒寫section時當成意圖對照():
    """⚠️ 猜成不變量會把它送進「等你按」而卡住；猜成意圖對照最多是多一列可刪的。"""
    P = _P()
    got = P.parse("````\nkind skill\nproduct CRUX\ncells 問法 | 位置\n````", "crux")
    assert len(got["docs"]) == 1
    assert got["docs"][0]["section"] == "intent"


def test_沒有cells的skill草稿不成立():
    """skill 是「表格裡的一列」—— 沒有 cells 就沒有東西可寫。"""
    got = _P().parse("````\nkind skill\nproduct CRUX\ntitle 只有標題\n````", "crux")
    assert not got["docs"]


def test_解析帶得出分類():
    got = _P().parse("````\nkind skill\nproduct CRUX\nsection intent\n"
                     "group 後台功能\ncells 問法 | 位置\n````", "crux")
    assert got["docs"][0]["group"] == "後台功能"


# ── 落點：拆到 references 的要找得到 ──────────────────
def test_意圖對照拆出去時要寫到references():
    """★ CRUX 的意圖對照表已經從 SKILL.md §2 拆到 `references/意圖對照表.md`
    （原本佔全檔 77%）。SKILL.md §2 只剩一張「分類｜列數」的摘要表 ——
    **附加到摘要表就完全錯了**。
    """
    D = _D()
    slug, _ = conftest.need_product()
    ref = os.path.join(ROOT, ".claude", "skills", slug, "references", "意圖對照表.md")
    target = D.skill_target({"product": slug, "section": "intent"})
    if os.path.isfile(ref):
        assert target == ref, "有 references 卻沒寫到那裡"
    else:
        assert target.endswith("SKILL.md")


def test_不變量一律寫在SKILL主檔():
    slug, _ = conftest.need_product()
    t = _D().skill_target({"product": slug, "section": "invariant"})
    assert t.endswith("SKILL.md")


# ── 寫入：對齊表頭、接流水號、插對位置 ────────────────
def _skill_fixture(tmp_path):
    """做一份最小的產品 skill（兩節都有表）。"""
    d = tmp_path / "skills" / "demo"
    os.makedirs(str(d))
    io.open(str(d / "SKILL.md"), "w", encoding="utf-8", newline="\n").write(
        "# demo\n\n## 1. 必記的不變量\n\n| # | 不變量 | 用途／後果 |\n| --- | --- | --- |\n"
        "| 1 | 既有的第一條 | 後果 |\n| 2 | 既有的第二條 | 後果 |\n\n"
        "## 2. 我要做這件事 → 去讀這裡\n\n| 意圖 | 位置 |\n| --- | --- |\n"
        "| 既有問法 | `既有.md` |\n\n## 3. 其他\n\n尾巴\n")
    return str(d / "SKILL.md")


def test_附加一列到意圖對照表(tmp_path):
    D = _D()
    p = _skill_fixture(tmp_path)
    assert D.append_skill_row(p, "2", "| 新問法 | `新.md` |")
    txt = io.open(p, encoding="utf-8").read()
    lines = txt.split("\n")
    i = lines.index("| 新問法 | `新.md` |")
    # ⛔ 一定要落在 §2 那張表裡，不能掉到 §3
    assert lines[i - 1] == "| 既有問法 | `既有.md` |"
    assert "## 3. 其他" in txt and txt.index("| 新問法") < txt.index("## 3. 其他")


def test_不變量會自動接流水號(tmp_path):
    """⛔ 由平台在**寫入當下**接號 —— session 看不到別人剛加的那一列。"""
    D = _D()
    p = _skill_fixture(tmp_path)
    assert D._next_skill_no(p, "1") == 3


def test_欄數對不上會被對齊而不是寫歪(tmp_path):
    """表頭三欄、只交兩欄 → 補空欄，不要讓 markdown 把整張表渲染歪。"""
    D = _D()
    p = _skill_fixture(tmp_path)
    header = D.skill_header(p, "1")
    assert header == ["#", "不變量", "用途／後果"]
    cells, note = D.align_cells(["只有一欄"], header)
    assert len(cells) == 3 and note


def test_找不到分類時退回整份檔的最後一張表(tmp_path):
    """⛔ **不可以「找不到就放棄」** —— 那會讓人按了寫入卻什麼都沒發生，
    而且沒有錯誤訊息。"""
    D = _D()
    p = _skill_fixture(tmp_path)
    assert D.append_skill_row(p, "2", "| 落到哪 | x |", group="根本不存在的分類")
    assert "| 落到哪 | x |" in io.open(p, encoding="utf-8").read()


# ── 提示裡要教 session 交這種草稿 ────────────────────
def test_探索與需求驗證的提示都教了怎麼交():
    """⚠️ 不教的話這個能力等於不存在 —— session 不會憑空知道平台收得下。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import tasks
    for tid in ("explore", "verify_requirement"):
        t = tasks.get(tid)
        tpl = t["prompt_template"]
        assert "kind     skill" in tpl, "%s 沒教怎麼交 skill 草稿" % tid
        assert "section  intent" in tpl and "section  invariant" in tpl, tid
        # ⛔ 一定要講明知識本體不放這裡，否則會把整段機制抄進 skill
        assert "知識本體" in tpl, "%s 沒講「知識本體走 ①」" % tid


def test_產品頁看得到skill檔():
    """★ **寫得進去卻看不到，等於沒寫**（27 份驗證報告沒有入口那次的教訓）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.knowledge_index import build_knowledge_index
    conftest.need_product()
    k = build_knowledge_index()
    for pid, v in (k.get("products") or {}).items():
        files = v.get("skill_files")
        assert isinstance(files, list), "%s 沒帶 skill_files" % pid
        if files:
            assert any(f["name"] == "SKILL.md" for f in files), pid
            assert all(f.get("path") and f.get("lines") for f in files), pid
