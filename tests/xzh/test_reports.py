# -*- coding: utf-8 -*-
"""報表選單案例（案例清單 E2b；2026-08-28 依子頁面補齊）。

📝 2026-08-28：原本跟「开奖号码」「注单数据」擠在同一份檔案（檔名跟內容對不上，
三條案例其實對應三個不同選單），依使用者指示拆成三個檔案：「开奖号码」移到
`test_draw_numbers.py`、「注单数据」移到 `test_bet_summary.py`，本檔只留「报表」這一條選單，
檔名跟內容終於一致。

「报表」底下是**真正的子頁面**：「占成报表」（預設落地，`/report/share`，依代理層級分組）／
「玩法报表」（`/report/play-type`，依「遊戲×玩法」分組，欄位比占成報表少「人数」、
多「贡献度」），比照 `test_system_setting.py` 的模式各自一條案例配靜態 `@allure.suite(...)`。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.dashboard_page import EmptyStatePage


@allure.suite("占成报表")
@pytest.mark.smoke
def test_share_report_page_loads(company_page):
    """E2b：「报表→占成报表」能正常載入並顯示表格。

    步驟：
    1. 導覽到「报表」頁（預設落地即占成報表）
    2. 等待畫面載入

    預期結果：
    - 頁面主要內容區應該正常顯示（不管有沒有實際資料）

    ⚠️ 2026-08-26 重跑 T9 時發現「報表→占成報表」已經有真實聚合資料
    （例如帳號 mimir1 已有 107 注、總投 225.00），跟首次探索當下「無資料」的現況不再一致——
    QAT 環境並非只有我們在用，有其他 session／使用者的活動會反映在這裡。這條案例因此
    只驗證頁面能正常載入並顯示表格，不斷言有無資料——那個假設已經不成立，
    見 `新綜合_驗證項目清單.md` H2/H3 附註。
    """
    page = company_page
    esp = EmptyStatePage(page)
    with allure.step("導覽到「报表」頁（預設落地即占成報表）並等待畫面載入"):
        esp.goto_report()
        page.wait_for_timeout(1500)
    with allure.step("讀取主要內容區是否顯示"):
        visible = page.get_by_role("main").is_visible()
    allure.attach(
        f"實際：main 區塊 {'顯示' if visible else '未顯示'}（期望：顯示）",
        name="占成報表頁面載入",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert visible


@allure.suite("玩法报表")
@pytest.mark.smoke
def test_play_type_report_page_loads(company_page):
    """E2b：「报表→玩法报表」能正常載入並顯示表格。

    步驟：
    1. 導覽到「报表→玩法报表」子頁面
    2. 等待畫面載入

    預期結果：
    - 頁面主要內容區應該正常顯示

    oracle 來源：D 級（探索當下已有真實資料，如「英国赛车／大小」1 注）——只驗證頁面
    能正常載入，不斷言有無資料（會隨每日下注情況變動）。
    """
    page = company_page
    esp = EmptyStatePage(page)
    with allure.step("導覽到「报表→玩法报表」子頁面並等待畫面載入"):
        esp.goto_play_type_report()
        page.wait_for_timeout(1500)
    with allure.step("讀取主要內容區是否顯示"):
        visible = page.get_by_role("main").is_visible()
    allure.attach(
        f"實際：main 區塊 {'顯示' if visible else '未顯示'}（期望：顯示）",
        name="玩法報表頁面載入",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert visible
