# -*- coding: utf-8 -*-
"""操作日志選單案例。

2026-08-28 首次探索。「操作日志」是單一頁面，沒有第二層選單，不需要 suite 分組。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.operation_log_page import OperationLogPage


@pytest.mark.smoke
def test_operation_log_has_records(company_page):
    """操作日誌頁能讀到操作紀錄（先驗證讀取到位）。

    步驟：
    1. 導覽到「操作日志」頁
    2. 讀取表格下方「共 N 条」的計數

    預期結果：
    - 應有至少 1 筆操作紀錄可供比對（探索當下已有其他 session 的真實操作紀錄）

    oracle 來源：D 級（探索當下實測現況），regression 用途。
    """
    page = company_page
    olp = OperationLogPage(page)
    with allure.step("導覽到「操作日志」頁"):
        olp.goto()
    with allure.step("讀取表格下方「共 N 条」的計數"):
        total = olp.total_count()
    allure.attach(
        f"實際筆數：{total}（期望：> 0）",
        name="操作日誌總筆數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert total > 0, "應有至少 1 筆操作紀錄"
