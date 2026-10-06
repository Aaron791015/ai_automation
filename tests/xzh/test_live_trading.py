# -*- coding: utf-8 -*-
"""即時盤面選單案例（2026-08-28 依子頁面補齊；2026-10-05 配合選單改版更新導覽）。

2026-08-28 時「即时操盘」底下是第二層選單：「盘面总览」（預設落地，`/live-trading/overview`）／
「盘面明细」（`/live-trading/detail`，單組欄位逐列列出），比照 `test_system_setting.py` 的模式
各自一條案例配靜態 `@allure.suite(...)`。
⚠️ 2026-10-05 選單改版（aaron02 唯讀實測）：「即时操盘」頂層選單與第二層選單已不存在，兩個子頁各自升為頂層選單、
網址不變——「盘面总览」→ 現「即时盘面」（`/live-trading/overview`）、「盘面明细」→ 現「敞口排行」
（`/live-trading/detail`）。案例函式名稱與 `@allure.suite` 沿用原名稱（平台案例樹以它們為鍵），
標題與步驟改用現行選單名稱。
"""
from __future__ import annotations

import json
import re

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.pages.live_trading_page import LiveTradingPage


@allure.suite("盘面总览")
@pytest.mark.smoke
def test_live_trading_overview_shows_option_odds(company_page):
    """「即时盘面」（原「即时操盘→盘面总览」）能正常載入並讀到選項的賠率。

    步驟：
    1. 導覽到頂層選單「即时盘面」（`/live-trading/overview`）
    2. 讀取選項「1」目前的賠率

    預期結果：
    - 賠率應為非空字串，且可解析為正數

    oracle 來源：D 級（探索當下實測現況）——不斷言確切賠率數值，因為賠率會隨操盤
    調整而變動，這裡只驗證頁面讀取到位（能不能讀到值），不是驗算賠率本身。
    """
    page = company_page
    ltp = LiveTradingPage(page)
    with allure.step("導覽到頂層選單「即时盘面」（`/live-trading/overview`）"):
        ltp.goto()
    with allure.step("讀取選項「1」目前的賠率"):
        odds = ltp.odds_for_option("1")
    allure.attach(
        f"實際讀到的賠率：{odds!r}（期望：非空字串，且可解析為正數）",
        name="即时盘面選項「1」賠率",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert odds, "應該讀得到選項「1」的賠率"
    assert float(odds) > 0, "賠率應為正數"


@allure.suite("盘面明细")
@pytest.mark.smoke
def test_live_trading_detail_shows_option_odds(company_page):
    """「敞口排行」（原「即时操盘→盘面明细」，同網址 `/live-trading/detail`）能正常載入並讀到選項的賠率。

    步驟：
    1. 導覽到頂層選單「敞口排行」（`/live-trading/detail`）
    2. 讀取選項「1」目前的賠率

    預期結果：
    - 賠率應為非空字串，且可解析為正數

    ⚠️ 2026-08-28 時「盘面明细」的選項數字是兩位數補零的「01」；2026-10-05 唯讀實測「敞口排行」的
    选项格是不補零的「1」（`lotto-ball` 的 `.digits`，`find_odds_for_option("01")` 回 None、「1」回賠率），
    所以這裡改讀「1」——判準（賠率為正數）不變，見 `live_trading_page.py::goto_detail`／`odds_for_option` 說明。

    oracle 來源：D 級（探索當下實測現況），同「即时盘面」不斷言確切數值。
    """
    page = company_page
    ltp = LiveTradingPage(page)
    with allure.step("導覽到頂層選單「敞口排行」（`/live-trading/detail`）"):
        ltp.goto_detail()
    with allure.step("讀取選項「1」目前的賠率"):
        odds = ltp.odds_for_option("1")
    allure.attach(
        f"實際讀到的賠率：{odds!r}（期望：非空字串，且可解析為正數）",
        name="敞口排行選項「1」賠率",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert odds, "應該讀得到選項「1」的賠率"
    assert float(odds) > 0, "賠率應為正數"


def _dismiss_message_boxes(page) -> None:
    """關掉進頁面時可能彈出的提示視窗（最多 3 個）。"""
    for _ in range(3):
        box = page.locator(".el-message-box:visible")
        if not box.count():
            break
        box.get_by_role("button").first.click()
        page.wait_for_timeout(300)


def _board_option_odds_by_panel(page, game_name: str, option: str = "1") -> dict:
    """進入「即时盘面」切到指定彩種，依序切到「A 盘」「B 盘」，讀「特码」該選項的「赔率」。

    回傳 `{"A": 賠率字串或 None, "B": 賠率字串或 None}`；該盤沒有「特码」選項資料時為 None。
    2026-10-02 13:18 唯讀實測：「A 盘」對應 `bonusNumberA`（特码A）、「B 盘」對應 `bonusNumberB`（特码B）。
    """
    page.get_by_role("menuitem", name="即时盘面", exact=True).click()
    page.wait_for_timeout(1500)
    page.get_by_text(game_name, exact=True).first.click()
    page.wait_for_timeout(2500)
    _dismiss_message_boxes(page)
    odds = {}
    for panel in ("A", "B"):
        tab = page.get_by_text(re.compile(rf"^\s*{panel}\s*盘\s*$"))
        if not tab.count():
            odds[panel] = None
            continue
        tab.first.click()
        page.wait_for_timeout(2500)
        _dismiss_message_boxes(page)
        # 2026-10-05 版面改版（交接 T100）：「特码」每組改為「序号／球號／赔率（含 −／＋ 按鈕）」，
        # 舊寫法取「名為選項的格子」的下一格，會先命中「序号」而讀到球號「1」；
        # 改由 LiveTradingPage 以「賠率格（.odds-value）的前一格＝選項」讀值，連肖等無「序号」的版面照樣適用。
        odds[panel] = LiveTradingPage(page).find_odds_for_option(option)
    return odds


# （盤別, 設定頁玩法 ID, 設定頁列名）——「A 盘」讀「特码A」差分、「B 盘」讀「特码B」差分
_BOARD_PANELS = (("A", "bonusNumberA", "特码A"), ("B", "bonusNumberB", "特码B"))


@allure.suite("盘面总览")
@allure.title('[邏輯驗證] B105：即时盘面：一级代理有赔率差分時，一级代理「A 盘」「B 盘」的「赔率」是否分別等於公司盤面「赔率」加上特码A、特码B 的差分')
@pytest.mark.smoke
def test_agent1_board_odds_include_agent1_gap(odds_gap_login, gap_context, odds_gap_run):
    """平台案例：[邏輯驗證] B105：即时盘面：一级代理有赔率差分時，一级代理「A 盘」「B 盘」的「赔率」是否分別等於公司盤面「赔率」加上特码A、特码B 的差分
    前置條件：QAT 公司帳號與一級代理 aaa111；該彩種「特码A」或「特码B」至少一列有非 0 的赔率差分才有鑑別力；只讀，不下注、不改設定、不寫差分。
    測試範圍：英国天天彩、香港六合彩、宾果六合彩各自讀取；「即时盘面」「特码」的「A 盘」（對應特码A）與「B 盘」（對應特码B）選項 1。
    步驟：
    1. 公司後台用户管理→一级代理 aaa111→编辑→赔率差分，讀該彩種「特码A」與「特码B」的差分。
    2. 公司帳號進入「即时盘面」切到同一彩種，分別切到「A 盘」「B 盘」，讀「特码」選項 1 的「赔率」。
    3. 一級代理 aaa111 登入後進入「即时盘面」切到同一彩種，同樣分別讀「A 盘」「B 盘」選項 1 的「赔率」。
    預期結果：一級代理盤面的「赔率」＝公司同一盤的「赔率」＋ aaa111 的差分，「A 盘」加「特码A」差分、「B 盘」加「特码B」差分（2026-09-29 新版文件：代理盤面的公司赔率欄是公司解析值加上一級代理差分，與注單記錄的公司賠率差一個差分）。
    佐證方式：逐彩種逐盤列出公司盤面賠率、讀到的差分、期望值算式、一級代理盤面實際值與判定的文字附件，及同內容的 JSON 附件。
    已知問題：新版文件稱此欄為「公司赔率」，實際畫面欄名為「赔率」；彩種未開盤無盤面資料，或「特码A」「特码B」差分都是 0 無法鑑別時，該彩種列 BLOCKED；單一盤差分為 0 時仍比對代理盤面＝公司盤面，但標明無鑑別力、不算有效通過。
    實作備註：2026-10-02 Aaron 確認 RD 對調 QAT「特码A／B」「正特码A／B」（非缺陷）後擴充——原本只讀「A 盘」與「特码A」，對調後賓果的 −1.1 落在「特码B」，賓果被判無法鑑別；現兩盤都讀。
    同日 13:18 唯讀實測確認：「A 盘」對應 `bonusNumberA`、「B 盘」對應 `bonusNumberB`；代理盤面「赔率」是畫面層加上該列差分，`/api/LiveTrading` 的 `odds` 仍是公司值（見 Snotra-019 補註、交接檔 T88）。
    """
    ctx = gap_context(0, via="company")
    company, agent = odds_gap_login("__company__"), odds_gap_login("aaa111")
    failures, blocked, evidence, lines = [], [], [], []
    for game in scope_games():
        name = GAMES[game]
        with allure.step("讀一級代理 aaa111 該彩種「特码A」「特码B」的赔率差分"):
            rows = ctx.open(game)
            gaps = {}
            for panel, play_type_id, _label in _BOARD_PANELS:
                row = next((r for r in rows if r["playTypeId"] == play_type_id), None)
                gaps[panel] = None if row is None else dec(row.get("oddsGap") or 0)
        with allure.step("公司與一級代理分別進入「即时盘面」切到同一彩種，讀「A 盘」「B 盘」「特码」選項 1 的「赔率」"):
            company_odds = _board_option_odds_by_panel(company, name)
            agent_odds = _board_option_odds_by_panel(agent, name)
        game_reasons, discriminating, game_failed = [], False, False
        for panel, _play_type_id, label in _BOARD_PANELS:
            gap, c_odds, a_odds = gaps[panel], company_odds[panel], agent_odds[panel]
            record = {"game": name, "panel": f"{panel} 盘", "gap_row": label,
                      "gap": None if gap is None else str(gap),
                      "company_board": c_odds, "agent1_board": a_odds}
            if gap is None or c_odds is None or a_odds is None:
                reason = "設定頁沒有該列" if gap is None else "盤面無「特码」選項資料（可能未開盤）"
                record["verdict"] = f"BLOCKED（{reason}）"
                game_reasons.append(f"{name}／{panel} 盘（{label}）：{reason}")
                lines.append(f"{name}｜{panel} 盘（{label}）｜公司 {c_odds}｜差分 {gap}｜—｜代理 {a_odds}｜{record['verdict']}")
            else:
                expected = dec(c_odds) + gap
                record["expected_agent1_board"] = str(expected)
                formula = f"{c_odds} + ({gap}) = {expected}"
                if dec(a_odds) != expected:
                    record["verdict"] = "FAIL"
                    game_failed = True
                    failures.append(f"{name}／{panel} 盘（{label}）：一級代理盤面「赔率」{a_odds}，預期 {expected}（公司 {c_odds} ＋ 差分 {gap}）")
                elif gap != 0:
                    record["verdict"] = "PASS（差分非 0，有鑑別力）"
                    discriminating = True
                else:
                    record["verdict"] = "PASS（差分 0，無鑑別力，不算有效通過）"
                lines.append(f"{name}｜{panel} 盘（{label}）｜公司 {c_odds}｜差分 {gap}｜{formula}｜代理 {a_odds}｜{record['verdict']}")
            evidence.append(record)
        blocked.extend(game_reasons)
        if not discriminating and not game_failed and not game_reasons:
            blocked.append(f"{name}：aaa111「特码A」「特码B」差分皆為 0，無法鑑別（兩盤只比對到代理盤面＝公司盤面，不算有效通過）")
    allure.attach("彩種｜盤（差分列）｜公司盤面「赔率」｜aaa111 差分｜期望值算式（公司＋差分）｜一級代理盤面實際值｜判定\n" + "\n".join(lines),
                  "逐彩種逐盤算式明細：公司盤面、差分、期望值、一級代理盤面實際值", allure.attachment_type.TEXT)
    allure.attach(json.dumps(evidence, ensure_ascii=False, indent=1), "逐彩種逐盤差分、公司與一級代理盤面賠率：實際 vs 預期",
                  allure.attachment_type.JSON)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    if blocked:
        pytest.skip("BLOCKED（部分）：" + "；".join(blocked))
