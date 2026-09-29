# -*- coding: utf-8 -*-
"""「报表 → 占成报表」的賠率差金額 Page Object（B98～B100）。

用途：設定日期／彩種／結算狀態篩選、逐層下鑽、讀取「赔率差金额」欄與會員注單明細。

使用方式：
    report = OddsGapReportPage(company_page)
    report.goto()
    report.query(date_from="2026-09-16", date_to="2026-09-16", settled=True)
    rows = report.rows()
    report.drill_into("aaa111")

前置條件：已登入公司層後台。

⚠️ **收益歸屬看的是 ancestorLevel，不是列帳號**（UI 元素對照 §4）——
   表頭「赔率差金额」對應的是**當下下鑽到的上級**。查一級收益要進 aaa111 層看其下級列，
   查九級要進 aaa999 層看會員列。⛔ 不可只憑某一列的帳號就判定該筆收益屬於誰。
"""
from __future__ import annotations

import re
from decimal import Decimal

from playwright.sync_api import Page

from xzh_qa.odds_gap_oracle import dec


class OddsGapReportPage:
    """占成報表頁；表格讀取一律依**欄頭文字**對應，不寫死欄位順序。"""

    GAP_COLUMN = "赔率差金额"

    def __init__(self, page: Page):
        self.page = page

    # ---------------- 導覽與查詢 ----------------

    def goto(self) -> None:
        """導覽到「报表」（預設落地即占成報表 `/report/share`）。

        ⚠️ 必須 `exact=True`：進到報表頁後會展開「占成报表／玩法报表／货量折扣报表」三個子選單，
        非精確比對會一次命中 4 個 menuitem 而觸發 strict mode violation。
        """
        self.page.get_by_role("menuitem", name="报表", exact=True).click()
        self.page.get_by_placeholder("开始日期").wait_for(state="visible")

    def query(self, date_from: str, date_to: str, settled: bool = True) -> None:
        """設定日期起訖與結算狀態後按「查询」。

        ⚠️ 彩種是「游戏 14/14」那顆下拉裡的一組 checkbox，**預設全選**；
        本方法不動它。呼叫端須先用 `select_games()` 對齊 UI、API 與稽核檔彩種；
        同一範圍的全部已結算注單才能與該範圍報表比較。
        """
        for placeholder, value in (("开始日期", date_from), ("结束日期", date_to)):
            box = self.page.get_by_placeholder(placeholder)
            box.fill(value)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(300)
        # 結算狀態是 radio（「已结算」／「未结算」），不是下拉選單。
        # 2026-09-29 實測：它是 el-segmented，radio input 為隱藏元素，直接 check() 會逾時；
        # 須點包含該 input 的可見選項，再核對已選中（「已结算」為預設值，原寫法只在它身上碰巧可用）。
        radio = self.page.get_by_role("radio", name="已结算" if settled else "未结算")
        if not radio.is_checked():
            self.page.locator(".el-segmented__item").filter(has=radio).click()
        assert radio.is_checked(), "結算狀態切換失敗"
        self.page.get_by_role("button", name="查询", exact=True).click()
        self.page.wait_for_timeout(1500)

    def select_games(self, names: list[str]) -> None:
        """在「游戏」下拉裡只勾選指定彩種（先「清除」再逐一勾選）。"""
        self.page.get_by_role("button", name=re.compile(r"^游戏")).click()
        self.page.wait_for_timeout(300)
        self.page.get_by_role("button", name="清除", exact=True).click()
        for name in names:
            box = self.page.get_by_role("checkbox", name=name, exact=True)
            if not box.is_checked():
                self.page.locator("label.el-checkbox").filter(has=box).click()
            assert box.is_checked(), f"彩種 {name} 未選取"
        self.page.keyboard.press("Escape")

    # ---------------- 讀取 ----------------

    #: 表格 thead 有**兩層**（第一層是「会员／一级代理／公司」分組，第二層才是實際欄位），
    #: 且第一欄的欄名會隨下鑽層級變動（公司層叫「一级代理」、下鑽後叫「二级代理」…）。
    #: 因此欄位一律用下面的 rowspan/colspan 展開演算法算出**葉欄**，⛔ 不可直接用 `thead th` 的順序。
    _READ_TABLE_JS = """() => {
        const table = [...document.querySelectorAll('table')]
            .find(t => t.innerText.includes('赔率差金额'));
        if (!table) return null;
        const headRows = [...table.querySelectorAll('thead tr')];
        const grid = [];
        headRows.forEach((tr, r) => {
            let c = 0;
            [...tr.querySelectorAll('th')].forEach(th => {
                while (grid[r] && grid[r][c]) c++;
                for (let i = 0; i < th.rowSpan; i++) {
                    for (let j = 0; j < th.colSpan; j++) {
                        grid[r + i] = grid[r + i] || [];
                        grid[r + i][c + j] = th.innerText.trim();
                    }
                }
                c += th.colSpan;
            });
        });
        const width = Math.max(...grid.map(row => row.length));
        const leaf = [];
        for (let c = 0; c < width; c++) {
            const stack = [];
            for (let r = 0; r < grid.length; r++) {
                const v = grid[r] ? grid[r][c] : undefined;
                if (v && stack[stack.length - 1] !== v) stack.push(v);
            }
            leaf.push(stack.join('/'));
        }
        const rows = [...table.querySelectorAll('tbody tr')].map(tr => {
            const cells = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
            const obj = {__account: cells[0] || ''};
            leaf.forEach((name, i) => { obj[name] = cells[i] !== undefined ? cells[i] : ''; });
            return obj;
        });
        return {leaf, rows};
    }"""

    def read_table(self) -> dict:
        """回傳 `{leaf: [葉欄名], rows: [{欄名: 文字, __account: 第一欄}]}`。"""
        data = self.page.evaluate(self._READ_TABLE_JS)
        assert data is not None, "畫面上找不到含「赔率差金额」欄的表格"
        return data

    def rows(self) -> list[dict]:
        return self.read_table()["rows"]

    def _gap_key(self, leaf: list[str]) -> str:
        keys = [name for name in leaf if name.endswith(self.GAP_COLUMN)]
        assert len(keys) == 1, f"找不到唯一的「{self.GAP_COLUMN}」欄；實際葉欄：{leaf}"
        return keys[0]

    def gap_amounts(self) -> dict:
        """一次讀回 `{帳號: 赔率差金额}`。

        ⚠️ 金額的**受益層**是當下下鑽到的上級（表頭分組寫的那一層），不是列帳號本身；
        呼叫端必須自己記錄「現在下鑽在哪一層」（UI 元素對照 §4）。
        """
        data = self.read_table()
        key = self._gap_key(data["leaf"])
        return {r["__account"]: dec(r[key].replace(",", "") or 0)
                for r in data["rows"] if r["__account"]}

    def gap_amount(self, account: str) -> Decimal:
        amounts = self.gap_amounts()
        assert account in amounts, f"報表內找不到帳號 {account!r}；目前列：{list(amounts)}"
        return amounts[account]

    def has_gap_column(self) -> bool:
        try:
            self._gap_key(self.read_table()["leaf"])
            return True
        except AssertionError:
            return False

    # ---------------- 下鑽 ----------------

    def drill_into(self, account: str) -> None:
        """點帳號進入下一層（aaa111 → aaa222 → … → aaa010）。"""
        self.page.get_by_role("button", name=account, exact=True).click()
        self.page.wait_for_timeout(1000)

    def expand_layers(self) -> None:
        """點「展开分层」（可點文字，不是 button）。"""
        target = self.page.get_by_text("展开分层", exact=True)
        if target.count():
            target.first.click()
            self.page.wait_for_timeout(500)

    def open_member_bets(self, date_text: str) -> None:
        """在會員層點日期，開啟該日注單明細。"""
        self.page.get_by_text(date_text, exact=True).first.click()
        self.page.wait_for_timeout(1200)

    def bet_rows(self) -> list[dict]:
        """讀注單明細表（投注額、结果、赔率等），欄名對應同 `rows()`。"""
        return self.rows()

    def total_pages(self) -> int:
        """讀「共 N 条」換算分頁狀況——完整查詢範圍必須把**所有分頁**都讀完才可加總。"""
        text = self.page.get_by_text(re.compile(r"共\s*\d+\s*条"))
        if text.count() == 0:
            return 0
        match = re.search(r"(\d+)", text.first.inner_text())
        return int(match.group(1)) if match else 0

    def next_page(self) -> bool:
        """翻下一頁；已是最後一頁回 False。"""
        button = self.page.get_by_role("button", name=re.compile(r"下一页|next"))
        if button.count() == 0 or button.first.is_disabled():
            return False
        button.first.click()
        self.page.wait_for_timeout(900)
        return True
