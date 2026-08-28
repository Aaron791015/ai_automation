# -*- coding: utf-8 -*-
"""注单数据選單案例（案例清單 E2a；2026-08-28 依子頁面補齊）。

📝 2026-08-28：原本跟「开奖号码」「报表」擠在同一份 `test_reports.py`（檔名跟內容對不上），
依使用者指示拆成三個檔案，各自對應一個選單。本檔只留「注单数据」這一條選單。

「注单数据」底下是**真正的子頁面**：「注单概览」（預設落地，`/bet/summary`）／
「注单明细」（`/bet/detail`，欄位不同——多了「号码」篩選、注单编号/赔率/中奖等欄位），
比照 `test_system_setting.py` 的模式各自一條案例配靜態 `@allure.suite(...)`。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.dashboard_page import EmptyStatePage


@allure.suite("注单概览")
@pytest.mark.smoke
def test_bet_overview_shows_no_data(company_page):
    """E2a：「注单数据→注单概览」目前仍顯示「暫無數據」。

    步驟：
    1. 導覽到「注单数据」頁（預設落地頁就是「注单概览」）

    預期結果：
    - 頁面應顯示「暫無數據」（探索當下現況）

    oracle 來源：D 級（探索當下實測），regression 用途。
    """
    page = company_page
    esp = EmptyStatePage(page)
    with allure.step("導覽到「注单数据」頁（預設落地頁就是「注单概览」）"):
        esp.goto_bet_summary()
    with allure.step("讀取「暂无数据」文字是否顯示"):
        no_data = esp.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="注单概览空狀態",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("注单明细")
@pytest.mark.smoke
def test_bet_detail_shows_no_data(company_page):
    """E2a：「注单数据→注单明细」目前仍顯示「暫無數據」。

    步驟：
    1. 導覽到「注单数据→注单明细」子頁面

    預期結果：
    - 頁面應顯示「暫無數據」（探索當下現況）

    oracle 來源：D 級（探索當下實測），regression 用途。
    """
    page = company_page
    esp = EmptyStatePage(page)
    with allure.step("導覽到「注单数据→注单明细」子頁面"):
        esp.goto_bet_detail()
    with allure.step("讀取「暂无数据」文字是否顯示"):
        no_data = esp.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="注单明细空狀態",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data
