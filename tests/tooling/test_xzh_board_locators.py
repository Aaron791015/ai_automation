# -*- coding: utf-8 -*-
"""新綜合公司即时盘面的兩個定位工具（2026-10-05 前端改版後修正）離線回歸：不連線、不登入、不下注。

用途：以 `page.set_content()` 的靜態 HTML（結構照 2026-10-05 唯讀 DOM 實測）驗證
      1. `odds_gap_chain_winner._click_member`：依 DOM 順序＋svg 圖形點「−／＋」，相容舊類別，
         圖形不符／列不唯一／鈕數不對時報錯且不點任何一顆（交接 T97）；
      2. `LiveTradingPage.find_odds_for_option`：「序号→球號→賠率」版面讀到賠率而不是球號，
         連肖等「選項→賠率」版面與改版前的純文字版面不受影響（交接 T100）。
      3. `OddsGapSettingPage.step_button_count`（用户管理→编辑→赔率差分設定頁）：2026-10-07 起差分輸入框
         沒有「−」「＋」（`is-without-controls`，Aaron 同日裁定為規格），新版每欄數到 0、舊版數到 2（交接 T114）。
使用方式：`.venv\\Scripts\\python.exe -m pytest tests/tooling/test_xzh_board_locators.py -q`
前置條件：Playwright chromium（沿用 pytest-playwright 的 `page` fixture）；不需要任何站台帳號。
"""
import pytest

pw = pytest.importorskip("playwright.sync_api")

from xzh_qa.odds_gap_chain_winner import _click_member, pick_offset_button  # noqa: E402
from xzh_qa.pages.live_trading_page import LiveTradingPage  # noqa: E402
from xzh_qa.pages.odds_gap_setting_page import OddsGapSettingPage  # noqa: E402


@pytest.fixture(scope="module")
def browser():
    """自備瀏覽器（不用 pytest-playwright 的 session 級 `playwright`）：它會常駐一個 asyncio loop，
    之後同一輪跑的 `test_xzh_player_bet_locator.py` 再開 `sync_playwright()` 會報「Sync API inside asyncio loop」。"""
    with pw.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as exc:  # 沒裝瀏覽器不算被測程式的問題
            pytest.skip(f"無法啟動 Chromium：{exc}")
        yield instance
        instance.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context()
    context.set_default_timeout(5000)
    yield context.new_page()
    context.close()

MINUS_ICON = '<i class="el-icon"><svg viewBox="0 0 24 24"><path d="M5 12h14"></path></svg></i>'
PLUS_ICON = '<i class="el-icon"><svg viewBox="0 0 24 24"><path d="M5 12h14m-7-7v14"></path></svg></i>'
NEW_CLS = "el-button el-button--small odds-btn"
MINUS_PATH, PLUS_PATH = "M5 12h14", "M5 12h14m-7-7v14"


# ---------------------------------------------------------------- pick_offset_button（純邏輯）

@pytest.mark.parametrize("direction,index", [("minus", 0), ("plus", 1)])
def test_pick_new_dom_by_order_and_icon(direction, index):
    assert pick_offset_button([NEW_CLS, NEW_CLS], [MINUS_PATH, PLUS_PATH], direction) == index


@pytest.mark.parametrize("direction,index", [("minus", 0), ("plus", 1)])
def test_pick_legacy_dom_by_class(direction, index):
    classes = ["el-button el-button--danger odds-btn", "el-button el-button--primary odds-btn"]
    # 舊版沒有 svg 圖形也要能點
    assert pick_offset_button(classes, [None, None], direction) == index


@pytest.mark.parametrize("classes,paths,match", [
    ([NEW_CLS, NEW_CLS], [PLUS_PATH, MINUS_PATH], "圖形"),                       # 順序顛倒
    ([NEW_CLS, NEW_CLS], [MINUS_PATH, MINUS_PATH], "圖形"),                      # 兩顆都是減號
    ([NEW_CLS, NEW_CLS], [None, None], "圖形"),                                  # 沒有 svg 且沒有舊類別
    ([NEW_CLS, NEW_CLS], [MINUS_PATH, "M0 0h1"], "圖形"),                        # 未知圖形
    (["el-button--primary odds-btn", "el-button--danger odds-btn"], [None, None], "舊版"),    # 舊類別順序顛倒
    (["el-button--danger odds-btn", NEW_CLS], [None, PLUS_PATH], "舊版"),                      # 新舊混用
    ([NEW_CLS], [MINUS_PATH], "預期 2"),                                          # 鈕數不對
    ([NEW_CLS] * 3, [MINUS_PATH, PLUS_PATH, MINUS_PATH], "預期 2"),
])
def test_pick_refuses_ambiguous_or_mismatched_buttons(classes, paths, match):
    for direction in ("minus", "plus"):
        with pytest.raises(AssertionError, match=match):
            pick_offset_button(classes, paths, direction)


def test_pick_rejects_unknown_direction():
    with pytest.raises(AssertionError, match="minus"):
        pick_offset_button([NEW_CLS, NEW_CLS], [MINUS_PATH, PLUS_PATH], "up")


# ---------------------------------------------------------------- _click_member（真 Chromium＋靜態 HTML）

def _odds_cell(value, *, minus_cls=NEW_CLS, plus_cls=NEW_CLS, minus_icon=MINUS_ICON, plus_icon=PLUS_ICON,
               cells=1, wrapper=True):
    one = (f'<button type="button" class="{minus_cls}" onclick="window.__clicks.push(\'minus:{value}\')">{minus_icon}</button>'
           f'<span class="odds-value">{value}</span>'
           f'<button type="button" class="{plus_cls}" onclick="window.__clicks.push(\'plus:{value}\')">{plus_icon}</button>')
    if not wrapper:
        return one
    return '<div class="odds-pair">' + "".join(f'<div class="odds-cell">{one}</div>' for _ in range(cells)) + "</div>"


def _group(label, members, **cell_kwargs):
    rows = "".join(
        f'<tr><td><div class="cell"><span class="sel-name">{name}</span></div></td>'
        f'<td><div class="cell">{_odds_cell(value, **cell_kwargs)}</div></td><td><div class="cell">0</div></td></tr>'
        for name, value in members)
    return f'<div class="group"><div class="group-label">{label}</div><table><tbody>{rows}</tbody></table></div>'


def _board(page, *groups, message_box=False):
    box = ('<div class="el-message-box" style="display:block"><button>取消</button>'
           '<button onclick="window.__clicks.push(\'confirm\')">确定</button></div>') if message_box else ""
    page.set_content("<script>window.__clicks=[]</script>" + "".join(groups) + box)


def _clicks(page):
    return page.evaluate("window.__clicks")


CHAIN_ZODIAC = _group("二肖连中", [("鼠", "4.81"), ("蛇", "4.8109"), ("马", "4.0676")])
CHAIN_ZODIAC_MISS = _group("二肖连不中", [("蛇", "3.77")])


@pytest.mark.parametrize("direction", ["minus", "plus"])
def test_click_member_new_dom_clicks_the_right_button(page, direction):
    _board(page, CHAIN_ZODIAC_MISS, CHAIN_ZODIAC)
    _click_member(page, direction)   # 預設：二肖连中蛇；不得誤點同名成員的「二肖连不中」群組
    assert _clicks(page) == [f"{direction}:4.8109"]


def test_click_member_other_play_and_member_args(page):
    tail = _group("二尾连不中", [("0尾尾", "5.51"), ("1尾尾", "5.52")])
    _board(page, CHAIN_ZODIAC, tail)
    _click_member(page, "plus", play_label="二尾连不中", member="1尾")
    assert _clicks(page) == ["plus:5.52"]


def test_click_member_confirm_box_presses_confirm_button(page):
    _board(page, CHAIN_ZODIAC, message_box=True)
    _click_member(page, "minus")
    assert _clicks(page) == ["minus:4.8109", "confirm"]


def test_click_member_legacy_classes_still_work(page):
    legacy = _group("二肖连中", [("蛇", "4.8109")], minus_cls="el-button el-button--danger odds-btn",
                    plus_cls="el-button el-button--primary odds-btn", minus_icon="", plus_icon="")
    _board(page, legacy)
    _click_member(page, "plus")
    _click_member(page, "minus")
    assert _clicks(page) == ["plus:4.8109", "minus:4.8109"]


@pytest.mark.parametrize("label,groups,kwargs,match", [
    ("圖形順序顛倒", [_group("二肖连中", [("蛇", "4.8")], minus_icon=PLUS_ICON, plus_icon=MINUS_ICON)], {}, "圖形"),
    ("沒有圖形", [_group("二肖连中", [("蛇", "4.8")], minus_icon="", plus_icon="")], {}, "圖形"),
    ("一列兩個賠率格", [_group("二肖连中", [("蛇", "4.8")], cells=2)], {}, "2 個賠率格"),
    ("同名成員重複", [_group("二肖连中", [("蛇", "4.8"), ("蛇", "4.9")])], {}, "唯一"),
    ("找不到成員", [_group("二肖连中", [("鼠", "4.8")])], {}, "唯一"),
    ("找不到玩法群組", [_group("三肖连中", [("蛇", "4.8")])], {}, "群組"),
])
def test_click_member_errors_without_clicking(page, label, groups, kwargs, match):
    _board(page, *groups)
    for direction in ("minus", "plus"):
        with pytest.raises(AssertionError, match=match):
            _click_member(page, direction)
    assert _clicks(page) == [], f"{label}：報錯時不得點到任何一顆"


def test_click_member_no_wrapper_two_buttons_legacy_row(page):
    """沒有 `.odds-cell` 包裝的舊版畫面：直接在列內找兩顆鈕。"""
    rows = (f'<tr><td><span class="sel-name">蛇</span></td><td>'
            f'{_odds_cell("4.8109", minus_cls="el-button--danger odds-btn", plus_cls="el-button--primary odds-btn", minus_icon="", plus_icon="", wrapper=False)}'
            "</td></tr>")
    page.set_content('<script>window.__clicks=[]</script><div class="group"><div class="group-label">二肖连中</div>'
                     f"<table><tbody>{rows}</tbody></table></div>")
    _click_member(page, "minus")
    assert _clicks(page) == ["minus:4.8109"]


# ---------------------------------------------------------------- LiveTradingPage.find_odds_for_option

def _bonus_board(options, per_row=4):
    """特码版面：每列 per_row 組「序号｜球號｜賠率（含 −／＋ 鈕）｜占成」；球號不補零，賠率各不相同。"""
    rows = []
    for r in range(0, len(options), per_row):
        cells = ""
        for n, value in options[r:r + per_row]:
            cells += (f'<td class="index-column"><div class="cell">{n}</div></td>'
                      f'<td class="narrow-column"><div class="cell"><span class="lotto-ball"><span class="digits">{n}</span></span></div></td>'
                      f'<td><div class="cell">{_odds_cell(value)}</div></td><td><div class="cell">0</div></td>')
        rows.append(f'<tr class="el-table__row">{cells}</tr>')
    return f"<table><tbody>{''.join(rows)}</tbody></table>"


def test_reader_special_number_layout_reads_odds_not_ball(page):
    options = [(n, f"{40 + n / 10:.4f}") for n in range(1, 50)]
    page.set_content(_bonus_board(options))
    reader = LiveTradingPage(page)
    for n, value in options:
        assert reader.find_odds_for_option(str(n)) == value, f"選項 {n}"
    assert reader.find_odds_for_option("50") is None
    assert reader.odds_for_option("1") == "40.1000"


HEADER_GROUP = "<th>序号</th><th>选项</th><th>赔率</th><th>占成</th>"


def _with_header(body, groups=4):
    """照 Element Plus 結構：表頭與表身是同一個 .el-table 底下的兩個 table。"""
    return (f'<div class="el-table"><div class="el-table__header-wrapper"><table><thead><tr>{HEADER_GROUP * groups}</tr></thead></table></div>'
            f'<div class="el-table__body-wrapper">{body}</div></div>')


def test_reader_with_header_plain_text_odds_without_buttons(page):
    """表頭定位：沒有偏移鈕、沒有 .odds-value 的純文字賠率（例如代理盤面）也讀賠率而不是球號；補位的空組略過。"""
    cells = "".join(
        f'<td class="index-column">{n}</td><td><span class="lotto-ball">{n}</span></td><td>{40 + n / 10:.4f}</td><td>0</td>'
        for n in (1, 14, 27)) + '<td class="index-column"></td><td></td><td></td><td></td>'
    page.set_content(_with_header(f'<table><tbody><tr class="el-table__row">{cells}</tr></tbody></table>'))
    reader = LiveTradingPage(page)
    assert reader.find_odds_for_option("1") == "40.1000"
    assert reader.find_odds_for_option("14") == "41.4000"
    assert reader.find_odds_for_option("27") == "42.7000"
    assert reader.find_odds_for_option("") is None and reader.find_odds_for_option("2") is None


def test_reader_with_header_odds_value_cells_and_named_options(page):
    """表頭定位 ＋ .odds-value：序号｜选项（sel-name）｜赔率（含 −／＋）；公司賠率欄名「公司赔率」也認。"""
    body = ('<table><tbody><tr class="el-table__row"><td class="index-column">1</td>'
            f'<td><span class="sel-name">红大</span></td><td>{_odds_cell("6.768")}</td><td>0</td></tr></tbody></table>')
    page.set_content(_with_header(body, groups=1).replace("<th>赔率</th>", "<th>公司赔率</th>"))
    reader = LiveTradingPage(page)
    assert reader.find_odds_for_option("红大") == "6.768"
    assert reader.find_odds_for_option("1") is None


def test_reader_old_buggy_pattern_would_have_read_the_ball(page):
    """對照：舊寫法（名為選項的格子的下一格）在新版面讀到球號「1」——T100 的現象。"""
    page.set_content(_bonus_board([(1, "46.893"), (2, "46.893")]))
    old = page.get_by_role("cell", name="1", exact=True).first.locator("xpath=following-sibling::*[1]").inner_text().strip()
    assert old == "1"
    assert LiveTradingPage(page).find_odds_for_option("1") == "46.893"


def test_reader_chain_layout_without_index_column_and_named_options(page):
    page.set_content(CHAIN_ZODIAC)
    reader = LiveTradingPage(page)
    assert reader.find_odds_for_option("蛇") == "4.8109"
    assert reader.find_odds_for_option("马") == "4.0676"
    assert reader.find_odds_for_option("龙") is None


def test_reader_other_layout_index_then_sel_name(page):
    """「其他」版面：序号｜选项（sel-name，如「红大」）｜赔率——選項是名稱不是序号。"""
    page.set_content('<table><tbody><tr class="el-table__row"><td class="index-column"><div class="cell">1</div></td>'
                     '<td><div class="cell"><span class="sel-name">红大</span></div></td>'
                     f'<td><div class="cell">{_odds_cell("6.768")}</div></td></tr></tbody></table>')
    reader = LiveTradingPage(page)
    assert reader.find_odds_for_option("红大") == "6.768"
    assert reader.find_odds_for_option("1") is None   # 序号不是選項


def test_reader_duplicate_option_is_an_error(page):
    page.set_content(_bonus_board([(1, "46.893"), (1, "41.993")]))
    with pytest.raises(AssertionError, match="2 格"):
        LiveTradingPage(page).find_odds_for_option("1")


def test_reader_legacy_plain_text_layout_still_supported(page):
    """改版前（沒有 .odds-value）的純文字版面：選項格後緊接賠率格。"""
    page.set_content('<table><tbody><tr><td role="cell">1</td><td role="cell">46.89</td><td role="cell">0</td></tr></tbody></table>')
    reader = LiveTradingPage(page)
    assert reader.find_odds_for_option("1") == "46.89"
    assert reader.find_odds_for_option("2") is None


def test_reader_odds_for_option_times_out_clearly(page):
    page.set_content(_bonus_board([(1, "46.893")]))
    with pytest.raises(AssertionError, match="找不到選項"):
        LiveTradingPage(page).odds_for_option("9", timeout_ms=600)


def _gap_cell(controls: bool) -> str:
    """一個差分輸入欄；結構照 2026-10-07 17:58 唯讀 DOM（aaa111 宾果）。controls=True 為 10/01 以前的舊版。"""
    buttons = ('<span class="el-input-number__decrease" role="button">−</span>'
               '<span class="el-input-number__increase" role="button">＋</span>') if controls else ''
    cls = "el-input-number is-center" if controls else "el-input-number is-without-controls is-center"
    return (f'<div class="{cls}">{buttons}<div class="el-input"><div class="el-input__wrapper">'
            '<input class="el-input__inner" type="text" inputmode="decimal" role="spinbutton" step="0.0001" value="0">'
            '</div></div></div>')


def _gap_table(controls: bool) -> str:
    """特码A（單欄）＋二中特／中二（主副雙欄）兩列。"""
    single = f'<tr><td>特码A</td><td><div class="diff-cell">{_gap_cell(controls)}</div></td><td>9.3786</td></tr>'
    dual = (f'<tr><td>二中特 / 中二</td><td><div class="diff-cell">{_gap_cell(controls)}<span class="sep">/</span>'
            f'{_gap_cell(controls)}</div></td><td>16.2750 / 6.5100</td></tr>')
    return f'<table><tbody>{single}{dual}</tbody></table>'


@pytest.mark.parametrize("controls,expected", [(False, 0), (True, 2)])
def test_gap_setting_step_button_count_matches_dom(page, controls, expected):
    """10/07 新版每欄 0 個加減按鈕（規格）；10/01 以前的舊版每欄 2 個，B90 依此判出現按鈕即不符。"""
    page.set_content(_gap_table(controls))
    gap = OddsGapSettingPage(page)
    assert [gap.step_button_count(0, 0), gap.step_button_count(1, 0), gap.step_button_count(1, 1)] == [expected] * 3
