# -*- coding: utf-8 -*-
"""`tools/qa_common/shot.py` 截圖標注的回歸測試。

用途：Bug 截圖若沒有標注，讀者得自己找問題在哪；本模組讓「加紅框」變成零成本，
      規範才不會漂移。測試用**本地 HTML**驗證，不連任何測試站。
前置條件：Playwright 瀏覽器已安裝（`scripts\\setup_test_env.ps1`）。
"""
import os

import pytest

from qa_common.shot import ANNOTATE_JS, annotate, capture_annotated, clear

FIXTURE = """
<html><body style="margin:0;padding:40px;font:14px system-ui">
  <table border="1" cellpadding="8">
    <tr><th>玩法</th><th>貨量</th><th id="maxloss-head">最大損失</th></tr>
    <tr><td>组六多码</td><td id="hold">¥20</td><td id="maxloss">+550.24</td></tr>
  </table>
  <div id="far-right" style="position:absolute;right:0;top:200px">靠右元素</div>
</body></html>
"""


@pytest.fixture
def fixture_page(page, tmp_path):
    f = tmp_path / "fixture.html"
    f.write_text(FIXTURE, encoding="utf-8")
    page.goto(f.as_uri())
    return page


def _count(page):
    return page.evaluate("() => document.querySelectorAll('[data-qa-annotation]').length")


def test_標注會產生紅框與徽章(fixture_page):
    r = annotate(fixture_page, [{"selector": "#maxloss", "label": "應為 −129.76"}])
    assert r["marked"] == 1 and not r["missing"]
    assert _count(fixture_page) == 3          # 框 ＋ 徽章 ＋ 頁尾圖例


def test_無說明時不產生標籤(fixture_page):
    annotate(fixture_page, [{"selector": "#maxloss"}])
    assert _count(fixture_page) == 2          # 只有框 ＋ 徽章


def test_說明條會加在頂端(fixture_page):
    annotate(fixture_page, [{"selector": "#hold"}], note="CRUX-050 大類卡最大損失錯值")
    assert _count(fixture_page) == 3          # 框 ＋ 徽章 ＋ 說明條


def test_selector對不到會回報missing(fixture_page):
    r = annotate(fixture_page, [{"selector": "#not-exist", "label": "x"},
                                {"selector": "#hold", "label": "y"}])
    assert r["marked"] == 1
    assert r["missing"] == ["#not-exist"]


def test_clear會移除全部標注(fixture_page):
    annotate(fixture_page, [{"selector": "#maxloss", "label": "a"}], note="b")
    assert _count(fixture_page) > 0
    clear(fixture_page)
    assert _count(fixture_page) == 0


def test_重複標注不會疊加(fixture_page):
    """標注前先清乾淨——否則反覆截圖會愈疊愈多層紅框"""
    for _ in range(3):
        annotate(fixture_page, [{"selector": "#maxloss", "label": "a"}])
    assert _count(fixture_page) == 3          # 與單次標注相同，未累積


def test_截圖後自動清除(fixture_page, tmp_path):
    out = str(tmp_path / "shot.png")
    capture_annotated(fixture_page, out,
                      marks=[{"selector": "#maxloss", "label": "應為 −129.76"}],
                      note="CRUX-050")
    assert os.path.isfile(out) and os.path.getsize(out) > 0
    assert _count(fixture_page) == 0, "截圖後未清除，後續畫面都會帶紅框"


def test_selector對不到時strict模式應失敗(fixture_page, tmp_path):
    """寧可讓案例失敗，也不要產出一張沒標到問題點的截圖"""
    out = str(tmp_path / "shot.png")
    with pytest.raises(AssertionError):
        capture_annotated(fixture_page, out, marks=[{"selector": "#not-exist", "label": "x"}])
    assert _count(fixture_page) == 0, "失敗路徑也必須清除標注"


def test_說明文字不得浮在內容上(fixture_page):
    """⚠️ 早期版本把說明貼在框旁邊，直接蓋住它要說明的那個數值（比沒標注更糟）。
    現在說明一律收進頁尾圖例：畫面上的絕對定位元素只能是框與徽章，不得帶說明文字。"""
    annotate(fixture_page, [{"selector": "#maxloss", "label": "這段說明很長很長很長"}])
    floating = fixture_page.evaluate(
        "() => [...document.querySelectorAll('[data-qa-annotation]')]"
        ".filter(e => e.style.position === 'absolute' && e.textContent.includes('這段說明'))"
        ".length")
    assert floating == 0, "說明不可用絕對定位浮在內容上"


def test_圖例位於文檔流末端不遮蔽內容(fixture_page):
    """圖例插在 body 最後，屬正常文檔流 —— 結構上不可能與畫面內容重疊"""
    annotate(fixture_page, [{"selector": "#maxloss", "label": "說明甲"}])
    is_last = fixture_page.evaluate(
        "() => {const l=document.body.lastElementChild;"
        " return l.hasAttribute('data-qa-annotation') && l.style.position === '';}")
    assert is_last, "圖例應為 body 最後一個元素且非絕對定位"


def test_說明條插在文檔最前(fixture_page):
    annotate(fixture_page, [{"selector": "#maxloss"}], note="標題說明")
    first_ok = fixture_page.evaluate(
        "() => {const f=document.body.firstElementChild;"
        " return f.hasAttribute('data-qa-annotation') && f.textContent === '標題說明';}")
    assert first_ok


def test_說明條造成的版面推移必須被校正(fixture_page):
    """⛔ 2026-08-20 的實害：說明條插在頁首會把內容往下推，而舊版在同一個 tick 就量座標，
    六張 bug 截圖的紅框全部整體下移一個說明條的高度、框到空白處 ——
    **圖看起來有標注、實際上標錯地方，比沒標更誤導**（說明條愈多行偏移愈大）。

    本案例用四行說明條（推移量明顯）驗證框最終與目標對齊。
    """
    long_note = "\n".join(["第一行", "第二行", "第三行", "第四行"])
    r = annotate(fixture_page, [{"selector": "#maxloss", "label": "應為 −129.76"}],
                 note=long_note)
    assert r["marked"] == 1
    aligned = fixture_page.evaluate(
        """() => {
            const t = document.querySelector('#maxloss').getBoundingClientRect();
            const box = [...document.querySelectorAll('[data-qa-annotation]')]
                .find(e => e.style.position === 'absolute' && e.style.borderStyle === 'solid');
            const want = t.top + window.scrollY - 3;
            return {delta: Math.abs(parseFloat(box.style.top) - want)};
        }""")
    assert aligned["delta"] <= 1, (
        "紅框與目標的垂直位移 %.1fpx —— 說明條推移後未重新量測座標" % aligned["delta"])


def test_展開中的下拉會被偵測並讓strict失敗(fixture_page, tmp_path):
    """開著的下拉／彈窗幾乎必定蓋住表格中段（正好是要框的欄位）。

    2026-08-20 的 CRUX-086／087 兩張圖就是玩法下拉沒關，把 `会员盈亏`／`笔数` 整段蓋掉。
    這件事機器判得了，就不要留給人自律。
    """
    fixture_page.evaluate(
        "() => {const d=document.createElement('div');"
        " d.className='el-select-dropdown'; d.style.cssText='height:200px;width:180px';"
        " d.textContent='下拉選項'; document.body.appendChild(d);}")
    r = annotate(fixture_page, [{"selector": "#maxloss", "label": "x"}])
    assert r["overlays"], "展開中的下拉未被偵測到"

    out = str(tmp_path / "shot.png")
    with pytest.raises(AssertionError, match="下拉"):
        capture_annotated(fixture_page, out, marks=[{"selector": "#maxloss", "label": "x"}])
    assert _count(fixture_page) == 0, "失敗路徑也必須清除標注"


def test_JS常數同時供MCP使用(  ):
    """MCP 與 pytest 共用同一份 JS，避免兩邊行為漂移"""
    assert "data-qa-annotation" in ANNOTATE_JS
    assert "marks" in ANNOTATE_JS and "note" in ANNOTATE_JS


def test_PNG標記可寫可讀(tmp_path, fixture_page):
    """標記讓 lint 分得出「已標注」與「原始畫面」——規範才機檢得了"""
    from qa_common.shot import read_png_mark, stamp_png
    raw = str(tmp_path / "raw.png")
    fixture_page.screenshot(path=raw)
    assert read_png_mark(raw) is None, "未經標注的圖不應有標記"
    assert stamp_png(raw, "marks=2")
    assert read_png_mark(raw) == "marks=2"


def test_標記後PNG仍可解碼(tmp_path, fixture_page):
    """tEXt 區塊插在 IHDR 之後；插壞了圖會開不起來"""
    from qa_common.shot import stamp_png
    p = str(tmp_path / "x.png")
    fixture_page.screenshot(path=p)
    size_before = os.path.getsize(p)
    stamp_png(p, "marks=1")
    assert os.path.getsize(p) > size_before
    # 讓瀏覽器自己驗證：能載入且尺寸正常，即代表 PNG 結構完好
    fixture_page.goto("file:///" + p.replace("\\", "/"))
    ok = fixture_page.evaluate("() => {const i=document.querySelector('img');"
                               " return i && i.naturalWidth > 0;}")
    assert ok, "標記後的 PNG 無法解碼"


def test_非PNG檔靜默略過(tmp_path):
    from qa_common.shot import read_png_mark, stamp_png
    p = str(tmp_path / "not.png")
    open(p, "wb").write(b"JPEGish")
    assert stamp_png(p, "x") is False
    assert read_png_mark(p) is None


def test_capture_annotated會蓋標記(tmp_path, fixture_page):
    from qa_common.shot import read_png_mark
    out = str(tmp_path / "a.png")
    capture_annotated(fixture_page, out, marks=[{"selector": "#maxloss", "label": "實際X應為Y"}])
    assert read_png_mark(out) == "marks=1"
