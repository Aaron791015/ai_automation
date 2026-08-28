# -*- coding: utf-8 -*-
"""公司層「操作日誌」Page Object（`/log`）。

2026-08-28 MCP 實測確認：單一頁面，沒有第二層選單。篩選條件為「类型」下拉與
「时间」日期區間，表格欄位為 類型／操作動作／目標／變更項／變更前值／變更後值／
操作者／IP 地址／時間；部分列可展開看多筆合併紀錄（「展开当前行 共 N 笔」）。
探索當下已有其他 session（帳號 `tomchen1`）留下的真實操作紀錄可供讀取驗證。
"""
from __future__ import annotations

import re

from playwright.sync_api import Page


class OperationLogPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        """導覽到「操作日志」頁（`/log`）。"""
        self.page.get_by_role("menuitem", name="操作日志").click()
        self.page.wait_for_timeout(600)

    def total_count(self) -> int:
        """讀表格下方分頁列「共 N 条」的 N。"""
        text = self.page.get_by_text(re.compile(r"共\s*\d+\s*条")).inner_text()
        m = re.search(r"(\d+)", text)
        assert m, "找不到『共 N 条』的計數文字"
        return int(m.group(1))
