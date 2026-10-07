# -*- coding: utf-8 -*-
"""什麼可以自動落檔、什麼一定要人按 —— 判準是「**錯了要付什麼代價**」。

## 為什麼有這一支

2026-08-23 使用者質疑：

> 「平台上有非常多需要人去審核／判斷的部分…這些不是都已經在 skills
>   定義好的規範，為何還要在平台上人工確認？」

**質疑是對的。** 2026-08-21 那條「草稿／落單兩段式」的裁示，原文只針對 Bug，
理由是 `CLAUDE.md` §6「**ID 配發後永不回收**」——**代價不可逆**。
把它推廣到交接檔、機制文件、驗證報告是過度擴大：那三種錯了刪掉就好。

| 產出 | 代價 | 要不要人按 |
| --- | --- | --- |
| Bug 落單 | ⛔ 燒掉永不回收的 ID（撤銷過的單至今 8 張） | ✅ 要 |
| `doc` 整檔覆寫 | 蓋掉別人寫的內容 | ✅ 要 |
| 交接檔附加一列 | 多一列，刪掉就好 | ❌ 自動 |
| `doc` 附加一節 | 接在檔尾，可回退 | ❌ 自動 |
| 驗證報告 | 不版控、撞名自動讓開 | ❌ 自動 |

使用方式：`pytest tests/tooling/test_platform_autowrite.py -q`
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


def _a_product():
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


# ── 可以自動的三種 ──────────────────────────────────────
def test_交接檔附加一列可以自動():
    ok, why = _dd().is_auto_safe({"kind": "handover", "product": _a_product(),
                                  "section": "todo", "cells": ["a", "b", "c"]})
    assert ok, why


def test_驗證報告可以自動():
    ok, why = _dd().is_auto_safe({"kind": "report", "product": _a_product(),
                                  "topic": "某主題", "body": "# 報告"})
    assert ok and "_reports" in why


def test_新檔或附加到檔尾可以自動():
    ok, why = _dd().is_auto_safe({"kind": "doc", "product": _a_product(),
                                  "path": "_不存在的檔_zz.md", "body": "# 新文件"})
    assert ok, why


# ── ⛔ 一定要人按的：整檔覆寫 ───────────────────────────
def test_整檔覆寫一定要人按():
    """★ 這是「自動化」與「蓋掉別人的東西」之間的界線。"""
    m = _dd()
    p = _a_product()
    probe = os.path.join(m._docs_dir(p), "_zz_auto_probe.md")
    io.open(probe, "w", encoding="utf-8").write("# 原本的機制文件\n\n很重要\n")
    try:
        ok, why = m.is_auto_safe({"kind": "doc", "product": p,
                                  "path": "_zz_auto_probe.md",
                                  "body": "# 一份完整的新文件\n\n新內容"})
        assert not ok, u"整檔覆寫被判成可以自動 —— 那會蓋掉別人寫的內容"
        assert "覆寫" in why
    finally:
        if os.path.exists(probe):
            os.remove(probe)


def test_附加一節仍然可以自動():
    """同一個既有檔，但 body 是片段（沒有 H1）→ 附加，不是覆寫。"""
    m = _dd()
    p = _a_product()
    probe = os.path.join(m._docs_dir(p), "_zz_auto_probe2.md")
    io.open(probe, "w", encoding="utf-8").write("# 原本的\n\n內容\n")
    try:
        ok, _ = m.is_auto_safe({"kind": "doc", "product": p,
                                "path": "_zz_auto_probe2.md",
                                "body": "## 補一節\n\n這次探索的發現"})
        assert ok
    finally:
        if os.path.exists(probe):
            os.remove(probe)


# ── ⛔ Bug 落單不在這條路上（它燒的是永不回收的 ID）────────────
def test_bug不走自動落檔():
    """`is_auto_safe` 只認文件類 —— Bug 走的是 `bugs_file.file_bug`，一律要人按。"""
    ok, _ = _dd().is_auto_safe({"kind": "bug", "title": "某現象"})
    assert not ok


# ── 批次落檔：能自動的寫掉、要人按的原樣留著 ────────────────
def test_批次落檔會跳過要人按的那一筆(tmp_path, monkeypatch):
    """⛔ 交接檔附加一定要寫在暫存的假交接檔上。

    2026-10-07 這裡原本直接附加到 registry 第一個產品的**真交接檔**，收尾再刪含「甲、乙、丙以直線隔開」的列；
    但實際寫進去的是「| Tnnn | 甲 | 乙；丙 |」（後兩格併成一格），對不上就殘留下來，還佔掉一個 T 編號，
    並以 LF 重寫整檔——新綜合交接檔因此多出 6 列假待辦（見新綜合交接 T116、共通交接 T4）。
    """
    m = _dd()
    p = _a_product()
    monkeypatch.setattr(m.paths, "SESSIONS_DIR", str(tmp_path))
    real_handover = m._handover_path(p)
    real_before = (io.open(real_handover, "rb").read()
                   if real_handover and os.path.isfile(real_handover) else None)
    fake_handover = tmp_path / "假交接.md"
    fake_handover.write_text("\n".join([
        "# 交接", "", "## 2. ★ 待辦總覽", "", "### 2.1 可立即動手", "",
        "| # | 事項 | 說明 | 優先 |", "| --- | --- | --- | --- |", "| T1 | 既有的 | 不可以被動到 | 中 |", "",
        "## 3. 別的節", ""]), encoding="utf-8")
    monkeypatch.setattr(m, "_handover_path", lambda pid: str(fake_handover))
    src = {"kind": "session", "id": "auto1"}
    probe = os.path.join(m._docs_dir(p), "_zz_auto_probe3.md")
    io.open(probe, "w", encoding="utf-8").write("# 原本的\n\n內容\n")
    m.save(src, {"drafts": [
        {"kind": "doc", "product": p, "path": "_zz_auto_probe3.md",
         "signature": "s1", "title": "會覆寫的", "body": "# 完整新文件\n\n蓋掉"},
        {"kind": "handover", "product": p, "section": "todo",
         "signature": "s2", "title": "附加一列", "cells": ["甲", "乙", "丙"]},
    ]})
    try:
        res = m.auto_commit_all(src)
        wrote = [r for r in res if r.get("ok")]
        skipped = [r for r in res if r.get("skipped")]
        assert len(skipped) == 1 and "覆寫" in skipped[0]["why"]
        assert len(wrote) == 1 and wrote[0]["kind"] == "handover"
        # 既有檔沒被動過
        assert io.open(probe, encoding="utf-8").read() == "# 原本的\n\n內容\n"
        # 自動寫的要留痕
        kept = [d for d in m.read(src)["drafts"] if d["signature"] == "s2"][0]
        assert kept.get("auto_written") is True
        # 附加的那一列落在假交接檔的 §2.1，既有列不動
        fake = fake_handover.read_text(encoding="utf-8")
        assert "甲" in fake and "| T1 | 既有的 | 不可以被動到 | 中 |" in fake
    finally:
        if os.path.exists(probe):
            os.remove(probe)
    # 真交接檔一個位元組都不能變
    if real_before is not None:
        assert io.open(real_handover, "rb").read() == real_before, "測試寫進了真的產品交接檔"
