# -*- coding: utf-8 -*-
"""開獎號碼選單案例（案例清單 E1）。

📝 2026-08-28：原本跟「注单数据」「报表」擠在同一份 `test_reports.py`（檔名跟內容對不上，
三條案例其實對應三個不同選單），拆成三個檔案，各自對應一個選單。本檔只留「开奖号码」這一條。
檔名由 `test_issue.py` 改為 `test_draw_numbers.py`（依使用者指示；「开奖号码」對應英文
"draw numbers"，比 `issue`「期號」更精準對到這個選單本身）。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.dashboard_page import IssuePage


@pytest.mark.smoke
def test_draw_numbers_history_has_records(company_page):
    """E1：開獎號碼頁能讀到歷史紀錄（先驗證讀取到位；期號遞增規律已在
    `docs/新綜合/新綜合_遊戲機制.md` §2 的首次探索記錄過，這裡做 regression）。
    """
    page = company_page
    ip = IssuePage(page)
    with allure.step("導覽到「开奖号码」頁"):
        ip.goto()
    with allure.step("讀取表格資料列（不含表頭）"):
        rows = ip.row_texts()
    allure.attach(
        f"實際列數：{len(rows)}（期望：> 1）\n首 3 列：{rows[:3]}",
        name="開獎歷史紀錄列數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(rows) > 1, "應有多筆歷史開獎紀錄可供比對"
