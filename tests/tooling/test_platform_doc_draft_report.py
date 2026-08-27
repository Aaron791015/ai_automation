# -*- coding: utf-8 -*-
"""需求驗證報告的落檔路徑：**檔名一律問 `new_bug_doc.py`**。

為什麼需要這一支
    `bugs/_reports/` 的檔名是「類型＋日期」的固定組合，同一天兩個 session
    各驗一批就必然撞名 —— 而 `docs/**/bugs/` 不版控，**覆蓋掉沒有 git 可以救**
    （`CLAUDE.md` §6 第 4 條，事故發生在 2026-08-14）。

    平台的「需求驗證」任務會產出報告草稿，落檔如果自己拼檔名，
    等於把那場事故搬進平台，而且是**無人看管**地重演。

使用方式：`pytest tests/tooling/test_platform_doc_draft_report.py -q`
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import doc_draft
    return doc_draft


def _a_product():
    """挑一個真的接上的產品 —— ⚠️ 不可硬編 CRUX（範本裡通常沒有它）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import get_registry
    for p in get_registry().products:
        if not p.get("virtual") and (p.get("knowledge") or {}).get("docs_dir"):
            return p["id"]
    return None


# ⛔ **模組層不可以 import 平台的 core** —— 那會在**收集期**把 `sys.modules['core']`
#    綁成平台的 core，於是接著收集 `tests/wbot/perf/` 時，那 12 支的
#    `from core.time_utils import …` 全部 ModuleNotFoundError。
#    後果是**平台的案例索引重建一直失敗、沿用舊快取**（2026-08-24 走查才發現，
#    因為單獨跑 `pytest tests/tooling` 是綠的）。見 test_collect_all_roots.py。
#
# ⛔ **也不要 `import conftest`** —— `tests/wbot/perf/` 也有一支 `conftest.py`，
#    兩者同名，誰先被匯入誰就佔住 `sys.modules['conftest']`。
#    → 這裡就地讀 `config/products.json`（產品定義的單一來源），不依賴任何人。
def _has_product():
    import json as _json
    try:
        _d = _json.load(open(os.path.join(ROOT, "config", "products.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(not p.get("virtual") for p in (_d.get("products") or []))


pytestmark = pytest.mark.skipif(not _has_product(),
                                reason="本工作區還沒接任何產品")


def _draft(**kw):
    d = {"kind": "report", "product": _a_product(), "topic": "平台自我驗收",
         "title": "測試用", "body": "# 測試用報告\n\n內容。", "report_kind": "requirement"}
    d.update(kw)
    return d


def test_預覽的路徑來自取號腳本而不是自己拼():
    pv = _mod().preview(_draft())
    assert pv["ok"], pv.get("errors")
    assert "bugs/_reports/" in pv["path"].replace("\\", "/")
    assert "需求驗證報告_平台自我驗收_" in pv["path"]
    assert "new_bug_doc.py" in pv["mode"], u"沒講明檔名的來源，人會以為是平台自己編的"


def test_空報告不給寫():
    """⛔ 空的 body 寫出去只會在 bugs/ 留下一個誰都不知道是什麼的檔。"""
    pv = _mod().preview(_draft(body="   "))
    assert not pv["ok"] and any("body" in e for e in pv["errors"])


def test_真的寫得出來而且撞名會自動讓開():
    """★ 實跑：連寫兩次，第二次必須**另取檔名**，不可覆蓋第一次。"""
    m = _mod()
    written = []
    try:
        r1 = m.commit(_draft())
        assert r1["ok"], r1.get("errors")
        written.append(os.path.join(ROOT, *r1["path"].replace("\\", "/").split("/")))
        r2 = m.commit(_draft(body="# 第二批\n\n不同內容。"))
        assert r2["ok"], r2.get("errors")
        written.append(os.path.join(ROOT, *r2["path"].replace("\\", "/").split("/")))

        assert r1["path"] != r2["path"], u"第二次撞名了 —— 這正是 2026-08-14 那場覆蓋事故"
        assert "第2批" in r2["path"] or "第 2 批" in r2["path"], r2["path"]
        assert "第二批" in io.open(written[1], encoding="utf-8").read()
        assert "測試用報告" in io.open(written[0], encoding="utf-8").read(), \
            u"第一份被蓋掉了"
    finally:
        for p in written:
            if os.path.isfile(p):
                os.remove(p)


def test_cells是一行文字時要切成欄位():
    """⚠️ 交回來的是 `A | B | C` 一行字，直接 join 會**逐字元**拆開。"""
    m = _mod()
    got = m.save({"kind": "session", "id": "_selftest_cells"},
                 {"drafts": [{"kind": "handover", "product": _a_product(),
                              "section": "data", "title": "t",
                              "cells": "建了三筆設定 | 總監2 netsub2 | 已還原 | —"}]})
    cells = got["drafts"][0]["cells"]
    import shutil
    shutil.rmtree(os.path.join(PLATFORM, "logs", "sessions", "_selftest_cells"),
                  ignore_errors=True)
    assert cells == ["建了三筆設定", "總監2 netsub2", "已還原", "—"], cells


# ── 知識回寫的第四段：**登記 docs/INDEX.md** ────────────────────
#
# `writeback` 的「回寫完成的四個必做」第一條就是它，而 `CLAUDE.md` 舉過的教訓是
# 「期數還原 SOP 早就寫在 docs/CRUX/ 裡，索引描述沒提到 → 別人搜尋不到 → 等於沒寫」。
# 平台先前只回一句「記得登記」—— 靠自律的規範必然漂移。

def _doc(**kw):
    d = {"kind": "doc", "product": _a_product(), "path": "_平台自我驗收_勿留.md",
         "title": "測試用", "body": "# 測試用\n\n內容。"}
    d.update(kw)
    return d


def test_挑得出該產品在INDEX裡的子節():
    secs = _mod().index_sections(_a_product())
    assert secs, u"找不到子節的話就無從登記"


def test_沒有描述就不亂登記():
    plan = _mod().index_plan(_doc())
    assert not plan["ok"] and "index_desc" in plan["reason"]


def test_子節對不上時要列出可選的節而不是亂塞():
    """⛔ 塞進「最後一張表」＝ 塞進不相干的子節，接手的人再也找不到它。"""
    plan = _mod().index_plan(_doc(index_desc="描述", index_section="不存在的節"))
    assert not plan["ok"]
    assert plan.get("section_options"), u"沒告訴人可以選哪些節"


def test_寫檔會一併登記INDEX而且真的寫進那一節():
    """★ 實跑：真的寫、真的登記，然後把兩邊都還原。"""
    m = _mod()
    idx = m.INDEX_PATH
    before = io.open(idx, encoding="utf-8").read()
    sec = m.index_sections(_a_product())[0]
    item = _doc(index_desc="平台自我驗收用，測完就刪", index_section=sec)
    written = None
    try:
        res = m.commit(item)
        assert res["ok"], res.get("errors")
        written = os.path.join(ROOT, *res["path"].replace("\\", "/").split("/"))
        assert "已一併登記" in res["note"], res["note"]

        after = io.open(idx, encoding="utf-8").read()
        assert "_平台自我驗收_勿留.md" in after, u"INDEX 沒被寫進去"
        # 落在指定的那一節，而不是檔尾
        body = after.split("### " + sec, 1)[1].split("\n### ", 1)[0]
        assert "_平台自我驗收_勿留.md" in body, u"登記到別的子節去了"
    finally:
        io.open(idx, "w", encoding="utf-8", newline="\n").write(before)
        if written and os.path.isfile(written):
            os.remove(written)
    assert io.open(idx, encoding="utf-8").read() == before
