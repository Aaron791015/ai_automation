# -*- coding: utf-8 -*-
"""公司層幾個唯讀查詢頁的 Page Object：代理層級、開獎號碼、空狀態頁面。

用途：C0（代理層級人數自檢）、E1（開獎歷史）、E2（注單數據／報表空狀態）。
前置條件：已登入公司層（`http://b1.c1.snotra.qat`）。
"""
from __future__ import annotations

import re

from playwright.sync_api import Page


class AgentHierarchyPage:
    """預設落地頁 `/user/account`，導覽列有「一级代理 9」…「会员 14」這類分頁。"""

    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        self.page.get_by_role("menuitem", name="用户管理").click()

    def switch_tab(self, tab_prefix: str) -> None:
        """切到指定分頁（如「会员」「一级代理」），不含後面的人數數字。"""
        item = self.page.get_by_role(
            "menuitem", name=re.compile(r"^%s\s*\d+$" % re.escape(tab_prefix))
        )
        item.click()
        # 表格內容是切分頁後非同步重新查詢的，給一點緩衝再讓呼叫端讀資料
        self.page.wait_for_timeout(600)

    def tab_label_count(self, tab_prefix: str) -> int:
        """讀導覽列該分頁標籤上的人數（如「会员 14」→ 14）。"""
        item = self.page.get_by_role(
            "menuitem", name=re.compile(r"^%s\s*\d+$" % re.escape(tab_prefix))
        )
        m = re.search(r"(\d+)\s*$", item.inner_text())
        assert m, "分頁標籤裡沒有找到人數數字"
        return int(m.group(1))

    def table_total_count(self) -> int:
        """讀表格下方分頁列「共 N 条」的 N。"""
        text = self.page.get_by_text(re.compile(r"共\s*\d+\s*条")).inner_text()
        m = re.search(r"(\d+)", text)
        assert m, "找不到『共 N 条』的計數文字"
        return int(m.group(1))


class IssuePage:
    """開獎號碼頁（`/issue`）。"""

    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        self.page.get_by_role("menuitem", name="开奖号码").click()
        self.page.wait_for_timeout(600)

    def row_texts(self) -> list[str]:
        """回傳資料列文字（不含表頭），最新一期在最上面。"""
        rows = self.page.get_by_role("row").all_inner_texts()
        header_kw = "期号"
        return [r for r in rows if not r.startswith(header_kw)]


class EmptyStatePage:
    """注單數據（`/bet/summary`）／報表（`/report/share`）——目前無真實下注資料的空狀態頁面。"""

    def __init__(self, page: Page):
        self.page = page

    def goto_bet_summary(self) -> None:
        self.page.get_by_role("menuitem", name="注单数据").click()

    def goto_report(self) -> None:
        self.page.get_by_role("menuitem", name="报表").click()

    def shows_no_data(self) -> bool:
        """用 `wait_for` 而非直接 `is_visible()`——切選單後內容非同步載入，
        立刻檢查會撲空；真的沒有這段文字時逾時回 False，仍是有效的否定結果。
        """
        try:
            self.page.get_by_text("暂无数据").wait_for(state="visible", timeout=12000)
            return True
        except Exception:
            return False
