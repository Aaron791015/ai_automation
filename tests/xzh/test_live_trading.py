# -*- coding: utf-8 -*-
"""即時操盤選單案例（2026-08-28 依子頁面補齊）。

「即時操盤」底下是**真正的子頁面**：「盘面总览」（預設落地，`/live-trading/overview`，
3 組欄位橫向並排）／「盘面明细」（`/live-trading/detail`，單組欄位逐列列出），
比照 `test_system_setting.py` 的模式各自一條案例配靜態 `@allure.suite(...)`。
"""
from __future__ import annotations

import allure
import pytest

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
