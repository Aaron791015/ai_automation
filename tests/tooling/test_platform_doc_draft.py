# -*- coding: utf-8 -*-
"""文件草稿 → 寫檔（探索的機制文件、收尾補做的交接檔內容）。

為什麼這一支值得寫
    計畫 E-1b 列了**五種**寫入型產出，先前只做了兩種（Bug、案例）。
    另外兩種——探索寫出來的機制文件、收尾補做的交接檔內容——
    **根本沒有寫檔路徑**：session 產得出來，介面上寫不下去，
    使用者只能自己複製貼上到編輯器。那正是「草稿／寫檔兩段式」要消滅的手工。

要釘住的三條紀律
    ① 草稿不寫檔 —— 寫檔一律由平台在人確認後執行
    ② **編號在寫入的那一刻才取**（多 session 併行沒有機制擋重複）
    ③ 覆寫既有的機制文件要明確確認 —— 一次誤按就蓋掉別人辛苦寫的東西

使用方式：`pytest tests/tooling/test_platform_doc_draft.py -q`
"""
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _dd():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import doc_draft
    return doc_draft


def _product():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import get_registry
    real = [p for p in get_registry().products if not p.get("virtual")]
    if not real:
        pytest.skip("這個工作區還沒接任何產品")
    return real[0]


# ─────────────────────────────── 形狀

def test_草稿一律正規化成固定形狀(tmp_path, monkeypatch):
    D = _dd()
    monkeypatch.setattr(D.paths, "SESSIONS_DIR", str(tmp_path))
    out = D.save({"kind": "session", "id": "s1"},
                 {"drafts": [{"title": "只有標題"}]})
    d = out["drafts"][0]
    for k in ("kind", "signature", "product", "title", "path", "section", "body", "cells", "why"):
        assert k in d, u"缺欄位 %s —— 形狀不固定就顯示不出來" % k
    assert d["kind"] == "doc", u"kind 沒給時要有安全的預設"


def test_已寫檔的不再列出(tmp_path, monkeypatch):
    D = _dd()
    monkeypatch.setattr(D.paths, "SESSIONS_DIR", str(tmp_path))
    monkeypatch.setattr(D.paths, "RUNS_DIR", str(tmp_path / "_runs"))
    D.save({"kind": "session", "id": "s1"},
           {"drafts": [{"signature": "a", "title": "A"}, {"signature": "b", "title": "B"}]})
    D.mark_written({"kind": "session", "id": "s1"}, "a", "docs/X/a.md")
    left = [x["signature"] for x in D.read_all()]
    assert left == ["b"], left


# ─────────────────────────────── 目標路徑

def test_機制文件寫進產品的docs目錄():
    D = _dd()
    p = _product()
    t = D.target_of({"kind": "doc", "product": p["id"], "path": "測試_機制.md"})
    assert t and t.endswith("測試_機制.md")
    assert os.path.join("docs", "") in t.replace("/", os.sep) + os.sep


def test_檔名沒有副檔名時自動補():
    D = _dd()
    p = _product()
    assert D.target_of({"kind": "doc", "product": p["id"], "path": "無副檔名"}).endswith(".md")


def test_檔名裡的不合法字元會被去掉():
    D = _dd()
    p = _product()
    t = D.target_of({"kind": "doc", "product": p["id"], "path": "a/b:c*.md"})
    assert not any(c in os.path.basename(t) for c in r'\/:*?"<>|')


def test_交接檔寫進活文件():
    D = _dd()
    p = _product()
    t = D.target_of({"kind": "handover", "product": p["id"]})
    assert t and t.endswith(".md") and "交接" in os.path.basename(t)


# ─────────────────────────────── 寫檔紀律

def test_整檔覆寫要明確確認(tmp_path, monkeypatch):
    """★ 一次誤按就蓋掉別人辛苦寫的機制文件。

    ⚠️ 判準是「這份 body 是不是一份**完整文件**」（H1 檔頭）——
       是完整文件才算覆寫；片段走附加（見下一條）。
    """
    D = _dd()
    p = _product()
    base = D._docs_dir(p["id"])
    probe = os.path.join(base, "_zz_probe_doc.md")
    io.open(probe, "w", encoding="utf-8").write("原本的內容\n")
    try:
        item = {"kind": "doc", "product": p["id"], "path": "_zz_probe_doc.md",
                "signature": "z", "body": "# 一份完整的新文件\n\n新內容"}
        res = D.commit(item)
        assert not res["ok"] and res.get("needs_overwrite"), res
        assert io.open(probe, encoding="utf-8").read() == "原本的內容\n", u"預設就把檔案蓋掉了"
        res2 = D.commit(item, overwrite=True)
        assert res2["ok"]
        assert "新內容" in io.open(probe, encoding="utf-8").read()
    finally:
        if os.path.exists(probe):
            os.remove(probe)


def test_只是要補一節時走附加而不是覆寫(tmp_path, monkeypatch):
    """★ 2026-08-23 實跑抓到的：探索最常見的產出是「**補一節到既有機制文件**」。

    當時平台只有「整檔覆寫」一種寫法 —— 按下去就是**用一段片段蓋掉整份
    609 行的機制文件**。交回來的草稿甚至自己寫著「非整份替換，僅新增一小節」，
    平台卻沒有這個模式。
    """
    D = _dd()
    p = _product()
    probe = os.path.join(D._docs_dir(p["id"]), "_zz_probe_append.md")
    io.open(probe, "w", encoding="utf-8").write("# 原本的機制文件\n\n很重要的既有內容\n")
    try:
        item = {"kind": "doc", "product": p["id"], "path": "_zz_probe_append.md",
                "signature": "z", "body": "## 新增一節\n\n這次探索補的內容"}
        pv = D.preview(item)
        assert pv["write_mode"] == "append", pv["mode"]
        assert not pv["exists"], u"附加不該被當成覆寫，還要人再確認一次"
        res = D.commit(item)
        assert res["ok"], res.get("errors")
        got = io.open(probe, encoding="utf-8").read()
        assert "很重要的既有內容" in got, u"既有內容被蓋掉了"
        assert "這次探索補的內容" in got
    finally:
        if os.path.exists(probe):
            os.remove(probe)


def test_交回來的路徑帶了說明也要正規化成檔名():
    """★ 實跑交回 `docs/CRUX/X.md（既有檔案，非整份替換）`——

    舊做法只把不合法字元刪掉，結果寫出 `docsCRUXX.md（既有檔案…）.md` 這種
    垃圾檔名，**而且它寫得出來**，於是 docs/ 底下多一個沒人看得懂的檔。
    """
    D = _dd()
    assert D.doc_name("docs/CRUX/CRUX_賠率變動設置.md（既有檔案，非整份替換）") \
        == "CRUX_賠率變動設置.md"
    assert D.doc_name("樂透_開獎機制") == "樂透_開獎機制.md"
def test_交接檔的編號在寫入那一刻才取():
    """⛔ 草稿裡不可以帶編號 —— 多 session 併行沒有機制擋重複。"""
    D = _dd()
    p = _product()
    pv = D.preview({"kind": "handover", "product": p["id"], "section": "todo",
                    "signature": "z", "cells": ["某件事", "說明", "中"]})
    assert pv["ok"], pv
    assert pv["text"].startswith("| "), pv["text"]
    # 第一欄是平台取來的編號，不是草稿給的
    first = pv["text"].split("|")[1].strip()
    assert first != "某件事", u"編號那一欄被草稿的內容佔掉了：%s" % pv["text"]


def test_附加不會動到既有的列(tmp_path):
    D = _dd()
    doc = tmp_path / "h.md"
    doc.write_text("\n".join([
        "# 交接", "", "## 2. ★ 待辦總覽", "",
        "| # | 事項 | 說明 | 優先 |", "| --- | --- | --- | --- |",
        "| T1 | 既有的 | 不可以被動到 | 中 |", "",
        "## 3. 別的節", "", "（略）", "",
    ]), encoding="utf-8")
    assert D._append_to_section(str(doc), "2", "| T2 | 新的 | 附加 | 低 |")
    got = doc.read_text(encoding="utf-8")
    assert "| T1 | 既有的 | 不可以被動到 | 中 |" in got
    assert got.index("| T2 |") > got.index("| T1 |")
    assert got.index("| T2 |") < got.index("## 3."), u"附加到別節去了"


def test_找不到那一節要明講():
    D = _dd()
    p = _product()
    res = D.commit({"kind": "handover", "product": p["id"], "section": "todo",
                    "signature": "z", "cells": []}) if False else None
    # 直接測 _append_to_section 的否定路徑
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    io.open(path, "w", encoding="utf-8").write("# 沒有任何節\n")
    try:
        assert D._append_to_section(path, "2", "| x |") is False
    finally:
        os.remove(path)


# ─────────────────────────────── 任務要告訴 session 交什麼

def test_兩支任務的prompt有寫明產出格式():
    """session 不知道要交哪些欄位的話，平台組不出東西可寫。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.tasks as T
    assert "kind     doc" in (T.get("explore") or {}).get("prompt_template", ""), \
        u"explore 沒告訴 session 機制文件要交什麼"
    assert "kind     handover" in (T.get("handoff_check") or {}).get("prompt_template", ""), \
        u"handoff_check 沒告訴 session 交接檔內容要交什麼"


# ─────────────────────────────── 子節要挑對

def _handover_fixture(tmp_path):
    doc = tmp_path / "h.md"
    doc.write_text("\n".join([
        "# 交接", "", "## 2. ★ 待辦總覽", "",
        "### 2.1 可立即動手", "",
        "| # | 事項 | 說明 | 優先 |", "| --- | --- | --- | --- |",
        "| T1 | 現在能做的 | — | 中 |", "",
        "### 2.4 被 blocker 擋住", "",
        "| # | 事項 | 擋在 | 解除後怎麼做 |", "| --- | --- | --- | --- |",
        "| T2 | 被擋住的 | B1 | — |", "",
        "## 5. 測試資料現況", "",
        "| 動過什麼 | 還原了嗎 | 備註 |", "| --- | --- | --- |",
        "| 帳號 A | ⛔ 刻意保留 | 屬 X-001 |", "",
    ]), encoding="utf-8")
    return doc


def test_可立即動手要附到21不是24(tmp_path):
    """★ 核心迴歸：只指到 §2 會附加到整節最後一張表（＝ §2.4）——
    把「現在就能做」的事寫進「被擋住」那一格，接手的人會直接跳過它。"""
    D = _dd()
    doc = _handover_fixture(tmp_path)
    assert D._append_to_section(str(doc), "2", "| T9 | 新的可做 | — | 中 |", "2.1")
    lines = doc.read_text(encoding="utf-8").split("\n")
    i9 = next(i for i, l in enumerate(lines) if l.startswith("| T9 "))
    i24 = next(i for i, l in enumerate(lines) if l.startswith("### 2.4"))
    assert i9 < i24, u"附加到 §2.4 去了（第 %d 行，而 §2.4 在第 %d 行）" % (i9, i24)


def test_被擋住的要附到24(tmp_path):
    D = _dd()
    doc = _handover_fixture(tmp_path)
    assert D._append_to_section(str(doc), "2", "| T9 | 新的被擋 | B1 | — |", "2.4")
    lines = doc.read_text(encoding="utf-8").split("\n")
    i9 = next(i for i, l in enumerate(lines) if l.startswith("| T9 "))
    i24 = next(i for i, l in enumerate(lines) if l.startswith("### 2.4"))
    i5 = next(i for i, l in enumerate(lines) if l.startswith("## 5."))
    assert i24 < i9 < i5


def test_四個子節都對得到():
    D = _dd()
    for key, expect in (("todo", "2.1"), ("todo_ext", "2.2"),
                        ("todo_who", "2.3"), ("todo_blk", "2.4")):
        assert D._SECTIONS[key][1] == expect, key
    assert D._SECTIONS["data"][0] == "5"


# ── 跨行的 JSON 陣列 cells（2026-08-24 拍手冊實跑時抓到）──────

def test_跨行的json陣列是一列不是三列():
    """★ `_rows()` 按行切是為了讓 session 交回一整張表時能拆列。

    但 session 也會把**一列**寫成跨行的 JSON 陣列 ——
    實跑（收尾體檢）就這樣把一筆待辦拆成 T2／T3／T4 三筆殘句寫進交接檔，
    每一筆都只有片段，**而且沒有任何錯誤訊息**。
    """
    from core.draft_parse import _rows
    raw = ('["補 CRUX-001 回歸案例",' + chr(10)
           + '          "regression 欄目前待補（lint D10）",' + chr(10)
           + '          "高"]')
    rows = _rows(raw)
    assert len(rows) == 1, "被拆成 %d 列了：%r" % (len(rows), rows)
    assert rows[0] == ["補 CRUX-001 回歸案例", "regression 欄目前待補（lint D10）", "高"]


def test_陣列的陣列才是多列():
    from core.draft_parse import _rows
    assert _rows('[["a","b"],["c","d"]]') == [["a", "b"], ["c", "d"]]


def test_多行表格仍然按行切():
    """⛔ 不可以為了修上面那條而把老路弄壞 —— 交回一整張表時仍要拆成多列。"""
    from core.draft_parse import _rows
    assert _rows("A | B | C" + chr(10) + "D | E | F") == [["A", "B", "C"], ["D", "E", "F"]]


def test_不是合法json就走老路():
    """⚠️ 看起來像陣列但解不開時**不要吞掉** —— 退回按行切，至少內容還在。"""
    from core.draft_parse import _rows
    assert _rows('["a", 壞掉的') == [['["a", 壞掉的']]
