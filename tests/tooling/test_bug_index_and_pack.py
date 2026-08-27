# -*- coding: utf-8 -*-
"""`scripts/gen_bug_index.py` 與 `scripts/pack_bug_report.py` 的回歸測試。

用途：
  - 配號（`--next-id`）**必須掃到 old/** —— ID 永不回收，漏掉就直接撞號，
    而撞號的損害不可逆（先佔者的檔案不能動，只能後寫入者全面改名）。
  - `superseded` 不該進「待開立」——它由後續單接手，列進來會讓清單永遠清不完。
  - 打包必須找得到已歸檔的單 —— 已結案的單正是最常被交付的對象。
前置條件：無（全在 tmp_path）。
"""
import io
import os

import gen_bug_index as G
import pack_bug_report as P
from conftest import bug_doc, write
import pytest

import bug_paths as _bp
# ⚠️ 這個檔的測試都需要**一個已登記的產品**當樣本（腳本的 `--product` 有 choices 驗證）。
#    全新範本「一個產品都還沒接」是正常狀態 —— 那時候沒有東西可測，明講跳過。
#    ⛔ 不要靠 `bug_paths` 的 fallback 變出產品來：那個 fallback 只給「設定檔壞掉」用，
#       拿它來餵測試會讓「空工作區」這個狀態永遠測不到（2026-08-23）。
_REGISTERED = _bp.PRODUCTS
pytestmark = pytest.mark.skipif(
    not _REGISTERED,
    reason="這個工作區還沒接任何產品 —— 這幾條測的是「對某個產品」的腳本行為")
_SAMPLE = _REGISTERED[0] if _REGISTERED else ""



def test_配號會掃到歸檔層(bugs_tree):
    """`ls bugs/` 看不到 old/；若配號沿用該做法，已歸檔的號會被重複配出"""
    bugs, _base = bugs_tree
    write(os.path.join(bugs, G.ARCHIVE_DIR, "CRUX-009_已歸檔.md"),
          bug_doc("CRUX-009", "已歸檔", status="fixed"))
    nid, recent = G.next_id("CRUX", bugs)
    assert nid == "CRUX-010", (nid, recent)
    assert 9 in recent


def test_配號也認得frontmatter壞掉的檔(bugs_tree):
    """frontmatter 壞掉的檔仍然佔號，只靠 frontmatter 掃會漏"""
    bugs, _base = bugs_tree
    write(os.path.join(bugs, "CRUX-020_沒有frontmatter.md"), "# 直接寫內文\n")
    nid, _recent = G.next_id("CRUX", bugs)
    assert nid == "CRUX-021", nid


def test_空目錄從001開始(tmp_path):
    d = str(tmp_path / "bugs")
    os.makedirs(d)
    nid, _ = G.next_id("CRUX", d)
    assert nid == "CRUX-001"


def test_各產品前綴正確(tmp_path):
    """每個**已登記**產品的配號前綴都要對得上 `config/products.json`。

    ⚠️ **不可以指名特定產品**（2026-08-23）—— 本測試隨範本發送，
       原本硬編投注機器人／七星，同事清掉原型產品後直接 `SystemExit`。
    """
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(G.__file__)))
    from bug_paths import PRODUCTS, ID_PREFIX
    # 空工作區已由檔頭的 pytestmark 跳過，這裡不再重複斷言
    for i, product in enumerate(PRODUCTS):
        d = str(tmp_path / ("bugs%d" % i))
        os.makedirs(d)
        assert G.next_id(product, d)[0].startswith(ID_PREFIX[product] + "-")


def test_superseded不列入待開立(bugs_tree):
    """CRUX-003 是 superseded 且 reported 為空，不該出現在待開立"""
    bugs, _base = bugs_tree
    bugs_list = G.load_bugs(bugs, quiet=True)
    out = G.render("CRUX", bugs_list)
    section = out.split("## ❌ 待開立")[-1] if "## ❌ 待開立" in out else ""
    assert "CRUX-003" not in section, section
    assert "CRUX-001" in section, section          # open 且未開立者仍要列


def test_superseded不列入待補回歸案例(bugs_tree):
    bugs, _base = bugs_tree
    out = G.render("CRUX", G.load_bugs(bugs, quiet=True))
    section = out.split("## ⚠️ 待補回歸案例")[-1] if "## ⚠️ 待補回歸案例" in out else ""
    assert "CRUX-003" not in section, section


def test_索引與分組檢視涵蓋歸檔層(bugs_tree, tmp_path):
    bugs, _base = bugs_tree
    write(os.path.join(bugs, G.ARCHIVE_DIR, "CRUX-007_已歸檔.md"),
          bug_doc("CRUX-007", "已歸檔", status="fixed"))
    bugs_list = G.load_bugs(bugs, quiet=True)
    assert any(b["id"] == "CRUX-007" and b["_archived"] for b in bugs_list)
    out = G.render("CRUX", bugs_list)
    assert "CRUX-007" in out and "📦" in out
    views = G.render_views("CRUX", bugs_list, os.path.join(bugs, G.VIEW_DIR))
    assert len(views) == len(G.VIEWS)
    fixed_view = io.open(os.path.join(bugs, G.VIEW_DIR, "03_已修復.md"),
                         encoding="utf-8").read()
    assert "CRUX-007" in fixed_view


def test_打包找得到已歸檔的單(bugs_tree, monkeypatch, tmp_path):
    """歸檔導入後，只掃主目錄會讓已結案單報「找不到」"""
    import archive_bugs as A
    bugs, _base = bugs_tree
    _t, docs, imgs = A.build_plan("CRUX", bugs, A.ARCHIVABLE)
    A.rewrite(bugs, docs, imgs, True)
    A.move_all(bugs, docs, imgs, True)

    monkeypatch.setattr(P, "ROOT", str(tmp_path))
    monkeypatch.setattr("sys.argv",
                        ["pack", "--product", "CRUX", "--name", "測試批", "--ids", "CRUX-002"])
    P.main()

    dst = os.path.join(bugs, "_deliver", "測試批")
    assert os.path.isfile(os.path.join(dst, "CRUX-002_測試乙.md"))
    assert os.path.isfile(os.path.join(dst, "shots", "CRUX-002_01_一般圖.png"))
    # 對外副本不得帶 frontmatter
    assert not io.open(os.path.join(dst, "CRUX-002_測試乙.md"),
                       encoding="utf-8").read().startswith("---")


# ── 長駐程序的產品清單要能重讀（2026-08-24）────────────────

def test_reload_products會更新模組常數(monkeypatch):
    """★ `bug_paths` 的四個常數是 **import 當下**凍結的。

    CLI 腳本每次都是新程序所以永遠最新；而測試助手是長駐的 Flask ——
    從介面接一個新產品之後不重讀，它的 Bug 索引**永遠看不到那個產品**，
    產品頁顯示成「未建立 bugs/」，而畫面上看不出這是快取
    （2026-08-24 拍手冊截圖時抓到）。
    """
    原本 = list(_bp.PRODUCTS)
    monkeypatch.setattr(_bp, "_load_products",
                        lambda: ({"newp": "新產品"}, ["新產品"], {"新產品": "NEWP"}, {}))
    assert _bp.reload_products() == ["新產品"]
    assert _bp.PRODUCTS == ["新產品"]
    assert _bp.ID_PREFIX["新產品"] == "NEWP", "前綴決定這張單燒掉誰的號，不能對不到"
    monkeypatch.undo()
    _bp.reload_products()                     # ⚠️ 還原後要真的讀回來，別汙染後面的測試
    assert _bp.PRODUCTS == 原本


def test_平台在掃描與配前綴之前都會重讀():
    """⛔ 只在 `bug_paths` 補一支函式沒有用 —— 呼叫端沒叫它就等於沒修。

    兩個呼叫端各自對應一種傷害：
      · `bug_index` 不重讀 → 新產品的 Bug 面板永遠是空的
      · `bugs_file` 不重讀 → 前綴對不到而退回 `product.upper()[:8]`，**燒錯號**
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for rel in ("tools/test_platform/core/bug_index.py",
                "tools/test_platform/web_ui/api/bugs_file.py"):
        src = io.open(os.path.join(root, *rel.split("/")), encoding="utf-8").read()
        assert "reload_products()" in src, rel + " 沒有重讀產品清單"
