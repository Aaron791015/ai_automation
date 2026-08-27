# -*- coding: utf-8 -*-
"""`scripts/archive_bugs.py` 的回歸測試。

用途：歸檔會搬檔案並改寫引用，而 `bugs/` **不版控、出錯無法用 git 還原** ——
      這是全工作區風險最高的腳本，必須有回歸保障。
      本檔鎖住 2026-08-11 沙箱驗證時踩到的三個陷阱（見各案例 docstring）。
前置條件：無（全在 tmp_path）。
"""
import io
import os

import pytest

import archive_bugs as A
from conftest import bug_doc, write


def read(path):
    return io.open(path, encoding="utf-8").read()


def plan_and_apply(bugs_dir, statuses=A.ARCHIVABLE):
    _targets, docs, imgs = A.build_plan("CRUX", bugs_dir, statuses)
    A.rewrite(bugs_dir, docs, imgs, True)
    A.move_all(bugs_dir, docs, imgs, True)
    return docs, imgs


def test_open單不會被歸檔(bugs_tree):
    """未修復的缺陷無論多久都要留在手邊——判準是狀態，不是日期"""
    bugs, _base = bugs_tree
    _t, docs, _i = A.build_plan("CRUX", bugs, A.ARCHIVABLE)
    assert not [d for d in docs if "CRUX-001" in d], docs


def test_已結案單與其圖一起搬走(bugs_tree):
    bugs, _base = bugs_tree
    docs, imgs = plan_and_apply(bugs)
    assert os.path.isfile(os.path.join(bugs, A.ARCHIVE_DIR, "CRUX-002_測試乙.md"))
    assert os.path.isfile(os.path.join(bugs, A.ARCHIVE_DIR, "shots",
                                       "CRUX-002_01_一般圖.png"))
    assert not os.path.exists(os.path.join(bugs, "CRUX-002_測試乙.md"))
    assert len(docs) == 2 and len(imgs) == 2      # CRUX-002(fixed)＋CRUX-003(superseded)


def test_歸檔單內部的圖引用維持相對正確(bugs_tree):
    """單與圖一起進 old/，`shots/x.png` 相對 old/ 仍然正確，不該被改成 `../shots/`"""
    bugs, _base = bugs_tree
    plan_and_apply(bugs)
    text = read(os.path.join(bugs, A.ARCHIVE_DIR, "CRUX-002_測試乙.md"))
    assert "(shots/CRUX-002_01_一般圖.png)" in text, text


def test_報告對已歸檔圖的引用被改寫(bugs_tree):
    """`_reports/` 在 bugs/ 下一層，圖進 old/ 後應變成 `../old/shots/…`"""
    bugs, _base = bugs_tree
    plan_and_apply(bugs)
    text = read(os.path.join(bugs, "_reports", "報告_2026-08-01.md"))
    assert "../%s/shots/CRUX-002_fixed_01_修復驗證.png" % A.ARCHIVE_DIR in text, text


def test_報告對未歸檔單的引用不受影響(bugs_tree):
    bugs, _base = bugs_tree
    plan_and_apply(bugs)
    text = read(os.path.join(bugs, "_reports", "報告_2026-08-01.md"))
    assert "(../CRUX-001_測試甲.md)" in text, text


def test_主目錄單引用已歸檔單會被改寫(bugs_tree):
    bugs, _base = bugs_tree
    p = os.path.join(bugs, "CRUX-001_測試甲.md")
    write(p, read(p) + "\n關聯：[乙](CRUX-002_測試乙.md)\n")
    plan_and_apply(bugs)
    assert "(%s/CRUX-002_測試乙.md)" % A.ARCHIVE_DIR in read(p), read(p)


def test_markdown跳脫的連結文字不會被改壞(bugs_tree):
    """原檔 `[../\\_reports/x.md](…)` 的跳脫底線曾讓改寫插出 `../\\../_reports/`"""
    bugs, _base = bugs_tree
    p = os.path.join(bugs, "CRUX-002_測試乙.md")
    write(p, read(p) + "\n> 來源：[../\\_reports/報告_2026-08-01.md](_reports/報告_2026-08-01.md)\n")
    plan_and_apply(bugs)
    text = read(os.path.join(bugs, A.ARCHIVE_DIR, "CRUX-002_測試乙.md"))
    assert "../\\../" not in text, text
    assert "[../\\_reports/報告_2026-08-01.md]" in text, text     # 連結文字原封不動
    assert "(../_reports/報告_2026-08-01.md)" in text, text        # 連結目標多一層 ../


def test_restore可以把單取回主目錄(bugs_tree):
    bugs, _base = bugs_tree
    plan_and_apply(bugs)
    docs, imgs = A.restore(bugs, "CRUX-002", True)
    A.rewrite(bugs, docs, imgs, True)
    A.move_all(bugs, docs, imgs, True)
    assert os.path.isfile(os.path.join(bugs, "CRUX-002_測試乙.md"))
    assert os.path.isfile(os.path.join(bugs, "shots", "CRUX-002_01_一般圖.png"))


def test_歸檔後lint仍全綠(bugs_tree):
    """整合檢查：搬完＋改寫完，資產一致性不能有任何破口"""
    import lint_bug_assets as L
    bugs, base = bugs_tree
    plan_and_apply(bugs)
    errors, warnings, _d, _s = L.lint("CRUX", base)
    assert not errors, errors
    assert not [w for w in warnings if w[:2] in ("W1", "W2", "W3")], warnings


@pytest.mark.parametrize("status", ["open", "suggestion"])
def test_未結案狀態不在可歸檔清單(status):
    assert status not in A.ARCHIVABLE
