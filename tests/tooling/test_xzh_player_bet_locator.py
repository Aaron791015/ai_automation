# -*- coding: utf-8 -*-
"""`PlayerBetPage` 標準型下注的號碼定位（交接 T77）——離線 DOM 重現，不連測試站。

用途：2026-10-01 驗 Snotra-019 時，上期開獎號碼含「1」，`get_by_text("1", exact=True).first`
      命中頁面頂部的開獎號碼球（不在 `.bet-cell` 內），下注時找不到金額欄而逾時。
      這裡用同結構的靜態 DOM（頂部開獎球＋投注格＋確認視窗）證明修正後點到、填到的是投注格。
使用方式：`pytest tests/tooling/test_xzh_player_bet_locator.py -q`
前置條件：本機已安裝 Playwright Chromium（`scripts\\setup_test_env.ps1`）；裝不到瀏覽器時整檔 SKIP。
DOM 結構依據：2026-10-02 `scratchpad/mapping-check-20261002/p2/member_ui.json` 的前台探測
（頂部開獎球與投注格同為 `.lotto-ball`、號碼文字不補零）。
"""
import pytest

pw = pytest.importorskip("playwright.sync_api")

from xzh_qa.pages.player_bet_page import PlayerBetPage  # noqa: E402

# 頂部開獎球「1／5／12」＋ 投注格 1／5／11／12（含一個隱藏頁籤的重複格 1）。
# 點號碼球的父層會把該格標成 selected 並記到 window.__clicked；確認後出現「投注成功」。
HTML = """
<div class="header-draw">
  <span class="lotto-ball red md">1</span><span class="lotto-ball red md">5</span>
  <span class="lotto-ball red md">12</span>
</div>
<div class="tab-hidden" style="display:none">
  <div class="bet-cell" data-cell="hidden-1"><div class="wrap"><span class="lotto-ball">1</span></div>
    <input type="number" data-input="hidden-1"></div>
</div>
<div class="grid">
  <div class="bet-cell" data-cell="1"><div class="wrap" onclick="window.__clicked=(window.__clicked||[]).concat(['1'])">
    <span class="lotto-ball red md">1</span></div><span class="odds">41.993</span>
    <input type="number" data-input="1"></div>
  <div class="bet-cell" data-cell="5"><div class="wrap" onclick="window.__clicked=(window.__clicked||[]).concat(['5'])">
    <span class="lotto-ball red md">5</span></div><span class="odds">41.993</span>
    <input type="number" data-input="5"></div>
  <div class="bet-cell" data-cell="11"><div class="wrap" onclick="window.__clicked=(window.__clicked||[]).concat(['11'])">
    <span class="lotto-ball red md">11</span></div><span class="odds">41.993</span>
    <input type="number" data-input="11"></div>
  <div class="bet-cell" data-cell="12"><div class="wrap" onclick="window.__clicked=(window.__clicked||[]).concat(['12'])">
    <span class="lotto-ball red md">12</span></div><span class="odds">41.993</span>
    <input type="number" data-input="12"></div>
</div>
<button onclick="document.getElementById('dlg').style.display='block'">投注</button>
<div id="dlg" role="dialog" style="display:none">
  <button onclick="document.getElementById('dlg').style.display='none';
                   document.getElementById('toast').textContent='投注成功'">确认</button>
</div>
<div id="toast"></div>
"""


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as exc:  # 沒裝瀏覽器不算被測程式的問題
            pytest.skip(f"無法啟動 Chromium：{exc}")
        yield instance
        instance.close()


@pytest.fixture
def bet_page(browser):
    page = browser.new_page()
    page.set_content(HTML)
    yield PlayerBetPage(page)
    page.close()


def _cell_of(locator):
    """回傳元素所屬 `.bet-cell` 的 data-cell；不在任何投注格內回 None。"""
    return locator.evaluate("el => (el.closest('.bet-cell') || {dataset: {}}).dataset.cell || null")


def test_舊寫法命中頂部開獎球_不在投注格內(bet_page):
    """重現 T77：舊寫法 `.first` 落在頂部開獎球，沒有 `.bet-cell` 祖先。"""
    old = bet_page.page.get_by_text("1", exact=True).first
    assert _cell_of(old) is None


@pytest.mark.parametrize("option,expected_cell", [("1", "1"), ("01", "1"), (5, "5"), ("11", "11"), ("12", "12")])
def test_號碼定位到投注格_開獎球含同號碼也不受影響(bet_page, option, expected_cell):
    cell = bet_page._standard_bet_cell(option)
    assert _cell_of(cell) == expected_cell
    # exact 比對：「1」不得命中「11」；隱藏頁籤的重複格（hidden-1）不得被選到。
    assert cell.locator(".lotto-ball").inner_text().strip() == str(int(option))


def test_select_standard_special_等的是投注格而不是開獎球(bet_page):
    """投注格延後渲染：開獎球「1」早已存在，等待仍須等到投注格出現才放行。"""
    page = bet_page.page
    page.evaluate("document.querySelector('.grid').style.display='none'")
    with pytest.raises(Exception):
        bet_page._standard_bet_cell(1).wait_for(timeout=300)
    page.evaluate("document.querySelector('.grid').style.display='block'")
    bet_page._standard_bet_cell(1).wait_for(timeout=1_000)


@pytest.mark.parametrize("option", ["1", "5", "12"])
def test_place_standard_bet_開獎球含該號碼時仍點到並填入投注格(bet_page, option):
    """上期開獎球含 1／5／12：點擊與金額都必須落在對應投注格，且完成確認。"""
    message = bet_page.place_standard_bet(option, "2")
    page = bet_page.page
    assert page.evaluate("window.__clicked") == [str(int(option))]
    filled = page.evaluate(
        "() => Object.fromEntries([...document.querySelectorAll('input[data-input]')].map(e => [e.dataset.input, e.value]))"
    )
    assert filled[str(int(option))] == "2"
    assert all(value == "" for key, value in filled.items() if key != str(int(option))), filled
    assert "成功" in message
