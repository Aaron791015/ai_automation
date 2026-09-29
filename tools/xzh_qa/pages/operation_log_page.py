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

    # ---- 以下 2026-09-29 T66／B108 加入；帳號「日志」頁（`/user/account/<id>/logs`）是同一種表格，可共用 ----

    def select_type(self, label: str) -> None:
        """「类型」下拉選指定類型，等到該次查詢回應再讓呼叫端讀表格。

        ⚠️ 選完後約 2.5 秒內表格仍可能是篩選前的舊資料（2026-09-29 MCP 實測），
        所以等 API 回應而不是等固定時間。
        """
        item = self.page.locator(".el-form-item").filter(has_text="类型").first
        item.locator(".el-select").first.click()
        with self.page.expect_response(lambda r: "/api/AuditLogs" in r.url and "topic=" in r.url,
                                       timeout=20000):
            self.page.locator(".el-select-dropdown:visible .el-select-dropdown__item",
                              has_text=label).first.click()
        self.page.wait_for_timeout(800)

    def table_rows(self) -> list[dict]:
        """目前表格的列：`level` 0＝一般列或批次代表列，1＝批次展開後的子列；`cells` 為各欄文字。"""
        return self.page.locator(".el-table__body > tbody > tr").evaluate_all(
            "trs => trs.map(tr => ({level: tr.className.includes('el-table__row--level-1') ? 1 : 0,"
            " cells: Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())}))")

    def expand_batch(self, target_text: str, time_text: str) -> None:
        """展開「共 N 笔」的批次列（依目标與时间定位），等同批明細查詢回應。"""
        row = (self.page.locator(".el-table__body > tbody > tr")
               .filter(has_text=target_text).filter(has_text=time_text).first)
        with self.page.expect_response(lambda r: "/api/AuditLogs" in r.url and "batchId=" in r.url,
                                       timeout=20000):
            row.locator(".el-table__expand-icon").click()
        self.page.wait_for_timeout(800)

    def batch_cells(self, target_text: str, time_text: str) -> list[list[str]] | None:
        """代表列＋其後連續子列的各欄文字；找不到代表列回 None。"""
        rows = self.table_rows()
        for i, row in enumerate(rows):
            cells = row["cells"]
            if row["level"] == 0 and len(cells) >= 10 and cells[3] == target_text and cells[9] == time_text:
                group = [cells]
                for follow in rows[i + 1:]:
                    if follow["level"] != 1:
                        break
                    group.append(follow["cells"])
                return group
        return None
