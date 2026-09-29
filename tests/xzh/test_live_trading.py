# -*- coding: utf-8 -*-
"""即時操盤選單案例（2026-08-28 依子頁面補齊）。

「即時操盤」底下是**真正的子頁面**：「盘面总览」（預設落地，`/live-trading/overview`，
3 組欄位橫向並排）／「盘面明细」（`/live-trading/detail`，單組欄位逐列列出），
比照 `test_system_setting.py` 的模式各自一條案例配靜態 `@allure.suite(...)`。
"""
from __future__ import annotations

import json

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.pages.live_trading_page import LiveTradingPage


@allure.suite("盘面总览")
@pytest.mark.smoke
def test_live_trading_overview_shows_option_odds(company_page):
    """「即时操盘→盘面总览」能正常載入並讀到選項的賠率。

    步驟：
    1. 導覽到「即时操盘」頁（預設落地即「盘面总览」）
    2. 讀取選項「1」目前的賠率

    預期結果：
    - 賠率應為非空字串，且可解析為正數

    oracle 來源：D 級（探索當下實測現況）——不斷言確切賠率數值，因為賠率會隨操盤
    調整而變動，這裡只驗證頁面讀取到位（能不能讀到值），不是驗算賠率本身。
    """
    page = company_page
    ltp = LiveTradingPage(page)
    with allure.step("導覽到「即时操盘」頁（預設落地即「盘面总览」）"):
        ltp.goto()
    with allure.step("讀取選項「1」目前的賠率"):
        odds = ltp.odds_for_option("1")
    allure.attach(
        f"實際讀到的賠率：{odds!r}（期望：非空字串，且可解析為正數）",
        name="盘面总览選項「1」賠率",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert odds, "應該讀得到選項「1」的賠率"
    assert float(odds) > 0, "賠率應為正數"


@allure.suite("盘面明细")
@pytest.mark.smoke
def test_live_trading_detail_shows_option_odds(company_page):
    """「即时操盘→盘面明细」能正常載入並讀到選項的賠率。

    步驟：
    1. 導覽到「即时操盘→盘面明细」子頁面
    2. 讀取選項「01」目前的賠率

    預期結果：
    - 賠率應為非空字串，且可解析為正數

    ⚠️ 「盘面明细」的選項數字是**兩位數補零**（「01」而非「盘面总览」的「1」），
    見 `live_trading_page.py::goto_detail` 檔頭說明——這裡不能沿用「盘面总览」的 "1"。

    oracle 來源：D 級（探索當下實測現況），同「盘面总览」不斷言確切數值。
    """
    page = company_page
    ltp = LiveTradingPage(page)
    with allure.step("導覽到「即时操盘→盘面明细」子頁面"):
        ltp.goto_detail()
    with allure.step("讀取選項「01」目前的賠率"):
        odds = ltp.odds_for_option("01")
    allure.attach(
        f"實際讀到的賠率：{odds!r}（期望：非空字串，且可解析為正數）",
        name="盘面明细選項「01」賠率",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert odds, "應該讀得到選項「01」的賠率"
    assert float(odds) > 0, "賠率應為正數"


def _board_option_odds(page, game_name: str, option: str = "1"):
    """進入「即时盘面」切到指定彩種，讀預設「特码」A 盘選項的「赔率」；無資料時回 None。"""
    page.get_by_role("menuitem", name="即时盘面", exact=True).click()
    page.wait_for_timeout(1500)
    page.get_by_text(game_name, exact=True).first.click()
    page.wait_for_timeout(2500)
    for _ in range(3):
        box = page.locator(".el-message-box:visible")
        if not box.count():
            break
        box.get_by_role("button").first.click()
        page.wait_for_timeout(300)
    cell = page.get_by_role("cell", name=option, exact=True)
    if not cell.count():
        return None
    return cell.first.locator("xpath=following-sibling::*[1]").inner_text().strip()


@allure.suite("盘面总览")
@allure.title('[邏輯驗證] B105：即时盘面：一级代理有赔率差分時，一级代理盤面的「赔率」是否等於公司盤面「赔率」加上該差分')
@pytest.mark.smoke
def test_agent1_board_odds_include_agent1_gap(odds_gap_login, gap_context, odds_gap_run):
    """平台案例：[邏輯驗證] B105：即时盘面：一级代理有赔率差分時，一级代理盤面的「赔率」是否等於公司盤面「赔率」加上該差分
    前置條件：QAT 公司帳號與一級代理 aaa111；aaa111 在該彩種「特码A」有非 0 的赔率差分；只讀，不下注、不改設定。
    測試範圍：英国天天彩、香港六合彩、宾果六合彩各自讀取；「即时盘面」預設「特码」A 盘選項 1。
    步驟：
    1. 公司後台用户管理→一级代理 aaa111→编辑→赔率差分，讀該彩種「特码A」的差分。
    2. 公司帳號進入「即时盘面」切到同一彩種，讀「特码」選項 1 的「赔率」。
    3. 一級代理 aaa111 登入後進入「即时盘面」切到同一彩種，讀同一選項的「赔率」。
    預期結果：一級代理盤面的「赔率」＝公司盤面「赔率」＋ aaa111 的「特码A」差分（2026-09-29 新版文件：代理盤面的公司赔率欄是公司解析值加上一級代理差分，與注單記錄的公司賠率差一個差分）。
    佐證方式：逐彩種差分、公司與一級代理盤面賠率、預期值的 JSON 附件。
    已知問題：新版文件稱此欄為「公司赔率」，實際畫面欄名為「赔率」；彩種未開盤無盤面資料或差分為 0 無法鑑別時該彩種列 BLOCKED。
    """
    ctx = gap_context(0, via="company")
    company, agent = odds_gap_login("__company__"), odds_gap_login("aaa111")
    failures, blocked, evidence = [], [], []
    for game in scope_games():
        name = GAMES[game]
        with allure.step("讀一級代理 aaa111 該彩種「特码A」的赔率差分"):
            rows = ctx.open(game)
            gap = dec(next(r for r in rows if r["playTypeId"] == "bonusNumberA").get("oddsGap") or 0)
        with allure.step("公司與一級代理分別進入「即时盘面」切到同一彩種，讀「特码」選項 1 的「赔率」"):
            company_odds = _board_option_odds(company, name)
            agent_odds = _board_option_odds(agent, name)
        record = {"game": name, "gap": str(gap), "company_board": company_odds, "agent1_board": agent_odds}
        evidence.append(record)
        if company_odds is None or agent_odds is None:
            blocked.append(f"{name}：盤面無「特码」選項資料（可能未開盤）")
            continue
        if gap == 0:
            blocked.append(f"{name}：aaa111「特码A」差分為 0，無法鑑別")
            continue
        expected = dec(company_odds) + gap
        record["expected_agent1_board"] = str(expected)
        if dec(agent_odds) != expected:
            failures.append(f"{name}／特码 選項1：一級代理盤面「赔率」{agent_odds}，預期 {expected}（公司 {company_odds} ＋ 差分 {gap}）")
    allure.attach(json.dumps(evidence, ensure_ascii=False, indent=1), "逐彩種差分、公司與一級代理盤面賠率：實際 vs 預期",
                  allure.attachment_type.JSON)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    if blocked:
        pytest.skip("BLOCKED（部分）：" + "；".join(blocked))
