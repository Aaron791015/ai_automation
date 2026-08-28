# -*- coding: utf-8 -*-
"""公司層「即時操盤」Page Object（`/live-trading/overview`）。

2026-08-28 MCP 實測確認：底下有第二層選單「盘面总览」（預設落地）／「盘面明细」，
跟「报表」「注单数据」同一種結構。本檔目前只做「盘面总览」的唯讀讀取，
「盘面明细」尚未覆蓋。

「盘面总览」畫面結構：
- 玩法分類頁籤（特码／正码／正1特～正6特／连码／生尾／连肖／连尾／不中／中一／
  特平中／合肖／比大小／其他），各自帶目前的投注量徽章。
- 盘口切換（A 盘／B 盘／AB-A／AB-B）與 实货／虚货 切換。
- 賠率表格是 **3 欄一組**（選項／賠率／占成／盈亏／飞单）橫向重複排 3 組，
  不是單一組欄位——讀值要先用完整字串比對「選項」儲存格，再取同一組內的下一格（賠率）。
"""
from __future__ import annotations

from playwright.sync_api import Page


class LiveTradingPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        """導覽到「即时操盘→盘面总览」（預設落地頁）。"""
        self.page.get_by_role("menuitem", name="即时操盘").click()
        self.page.wait_for_timeout(600)

    def goto_detail(self) -> None:
        """導覽到「即时操盘→盘面明细」子頁面（`/live-trading/detail`）。

        2026-08-28 實測：跟「盘面总览」的差異除了表格排版（「盘面明细」是**單一組**
        選項/賠率/注額/占成/盈亏/飞单逐列列出，不是「盘面总览」那種 3 組橫向並排），
        ⚠️ **選項的數字格式也不同**：「盘面总览」是不補零的「1」「2」…，
        「盘面明细」是**兩位數補零**的「01」「02」…——用 `odds_for_option()` 查值時
        兩邊要傳不同字串，混用會因為 `exact=True` 完全比對不到儲存格而逾時。
        """
        self.goto()
        self.page.get_by_role("menuitem", name="盘面明细").click()
        self.page.wait_for_timeout(600)

    def odds_for_option(self, option: str) -> str:
        """讀「盘面总览」表格裡某個選項（如「1」「大」「特码」對應的號碼）目前的賠率。

        ⚠️ 表格每列是 3 組（選項/賠率/占成/盈亏/飞单）橫向排列，用完整字串（`exact`）
        比對「選項」儲存格避免「1」誤中「21」「41」，再取同一組緊接著的下一格（賠率欄）。
        """
        cell = self.page.get_by_role("cell", name=option, exact=True).first
        odds_cell = cell.locator("xpath=following-sibling::*[1]")
        return odds_cell.inner_text().strip()
