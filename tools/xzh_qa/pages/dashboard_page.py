# -*- coding: utf-8 -*-
"""公司層幾個唯讀查詢頁的 Page Object：代理層級、開獎號碼、空狀態頁面。

用途：C0（代理層級人數自檢）、E1（開獎歷史）、E2（注單數據／報表空狀態）。
前置條件：已登入公司層（`http://b1.c1.snotra.qat`）。
"""
from __future__ import annotations

import re

from playwright.sync_api import Page


class AgentHierarchyPage:
    """預設落地頁 `/user/account`，導覽列有「一级代理 9」…「会员 14」這類分頁。

    ⚠️ 2026-08-28 探索一级代理～会员整條 `aaa111` 下線鏈（`aaa111→aaa222→…→aaa999→aaa010`）
    後發現：二级代理～八级代理跟一级代理**結構完全一樣**（同一套元件），但兩個邊界層不同——
    **九级代理**的操作欄少了「直属会员」按鈕（只剩 编辑/操作员/日志）；**会员**是最底層，
    欄位更少（沒有「下级」「本層占成%」欄，因為沒有下線）、操作欄只剩 编辑/日志。
    以下方法多數用欄頭文字讀取、不寫死欄位順序，同一套方法可以跨層共用；
    唯一需要知道「目前在哪一層」的是 `row_level_breakdown_sum`（見該方法說明）。
    """

    #: 代理層級的完整鏈，用來推算「這一層的下面還有哪些層」（見 `row_level_breakdown_sum`）。
    LEVELS = ["一级代理", "二级代理", "三级代理", "四级代理", "五级代理",
              "六级代理", "七级代理", "八级代理", "九级代理", "会员"]

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

    def search_account(self, keyword: str) -> None:
        """在「账号/昵称」欄位輸入關鍵字並送出查詢（Enter 觸發，無獨立查詢鈕）。"""
        box = self.page.get_by_role("textbox", name="账号/昵称")
        box.fill(keyword)
        box.press("Enter")
        self.page.wait_for_timeout(600)

    def filter_money_type(self, money_type: str) -> None:
        """依「资金模式」篩選（`money_type` 如「现金」「信用」）。

        ⚠️ 不能直接點 `role=combobox` 那個 `<input>`——它與同層的 placeholder `<span>`
        皆包在 `.el-select__wrapper` 底下，那個 placeholder 會蓋住攔截點擊
        （`intercepts pointer events`）。要點的是再往上一層、真正有 `cursor:pointer`
        點擊事件的 `.el-select__wrapper`（`<input>` 的父層的父層），
        跟 MCP 探索時點的是同一個節點。
        """
        combobox = self.page.get_by_role("combobox", name="资金模式")
        combobox.locator("xpath=../../..").click()
        self.page.get_by_role("option", name=money_type, exact=True).click()
        self.page.wait_for_timeout(600)

    def expand_level_columns(self) -> None:
        """點擊「展开 »」，把「下级」欄拆成「公司～会员」逐層人數欄（2026-08-28 探索所見）。"""
        self.page.get_by_text("展开 »", exact=True).click()
        self.page.wait_for_timeout(300)

    def table_rows(self) -> list[dict]:
        """讀取目前表格所有列，依**欄頭文字**對應成 `{欄名: 文字}`（不依賴欄位順序/索引），
        另附 `__has_withdraw`（該列操作欄是否有「存取款」按鈕）。呼叫端（案例）需要逐列檢查
        （如 C3 驗證資金模式與存取款按鈕的對應）時直接用這支，不必只透過下面的單列輔助方法。
        """
        return self.page.evaluate(
            """() => {
                const table = document.querySelector('table');
                const headers = Array.from(table.querySelectorAll('thead th')).map(h => h.innerText.trim());
                const rows = Array.from(table.querySelectorAll('tbody tr'));
                return rows.map(r => {
                    const cells = Array.from(r.querySelectorAll('td'));
                    const obj = {};
                    headers.forEach((h, i) => { obj[h] = cells[i] ? cells[i].innerText.trim() : ''; });
                    obj.__has_withdraw = r.innerText.includes('存取款');
                    return obj;
                });
            }"""
        )

    def row_account_names(self) -> list[str]:
        """回傳目前表格所有列的「账号」欄文字。"""
        return [r["账号"] for r in self.table_rows()]

    def row_has_withdraw_button(self, account: str) -> bool:
        """該帳號列的操作欄是否有「存取款」按鈕（只有「资金模式=现金」的帳號才有）。"""
        row = self._row_by_account(account)
        return bool(row["__has_withdraw"])

    def row_level_breakdown_sum(self, account: str, tier: str) -> int:
        """展開後讀該列「`tier` 的下一層～会员」逐層人數欄的加總
        （不含 `tier` 自己那一欄，因為那是占成% 不是人數）。

        `tier` 是目前所在分頁的名稱（如「一级代理」「五级代理」），用 `LEVELS` 推算
        「這一層下面還有哪些層」——例如 `tier="五级代理"` 只加總 六~九级代理＋会员，
        不會誤加一~四级代理（那些是**上面**的層，展開後顯示的是占成%鏈，不是人數）。
        """
        idx = self.LEVELS.index(tier)
        deeper_cols = self.LEVELS[idx + 1:]
        row = self._row_by_account(account)
        return sum(int(row[c]) for c in deeper_cols)

    def row_action_names(self, account: str) -> list[str]:
        """回傳該帳號列「操作」欄目前有哪些按鈕文字（結構性掃描：不同層級/資金模式的
        按鈕集合不同——例如九级代理少「直属会员」、会员只剩「编辑」「日志」）。
        """
        return self._row_locator(account).locator("td:last-child button").all_inner_texts()

    def _row_locator(self, account: str):
        """定位該帳號所在列。

        ⚠️ **不能只用 `get_by_role("button", name=account)` 找**——代理層級的帳號欄是
        可點擊連結（`<button>`），但**会员層級的帳號只是純文字**，不是 button（2026-08-28
        實測撲空過：對會員用 role=button 找列，找到 0 列，後續點按鈕全部 timeout）。
        改成直接比對第一欄（账号欄）的文字，兩種情況都比對得到。
        """
        return self.page.locator("table tbody tr").filter(
            has=self.page.locator("td:first-child").get_by_text(account, exact=True)
        )

    def row_collapsed_subordinate_count(self, account: str) -> int:
        """收合狀態下讀該列「下级」欄的總數（所有層級下線人數合計）。"""
        row = self._row_by_account(account)
        return int(row["下级"])

    def _row_by_account(self, account: str) -> dict:
        for row in self.table_rows():
            if row["账号"] == account:
                return row
        raise AssertionError(f"表格內找不到帳號 {account!r}")

    def column_headers(self) -> list[str]:
        """讀取（收合狀態下）表格欄位標題文字，依畫面順序回傳（結構性掃描用）。"""
        return self.page.locator("table thead th").all_inner_texts()

    def status_options(self) -> list[str]:
        """開啟「状态」下拉，讀取選項文字後按 Escape 收起（結構性掃描：下拉選單本身正不正常）。

        ⚠️ 跟 `filter_money_type` 同一個陷阱：不能點 `role=combobox` 的 `<input>`，
        要點外層 `.el-select__wrapper`。
        ⚠️ **不能直接選 `.el-select-dropdown__item`**——Element Plus 的下拉選單是傳送到
        全域 overlay 容器的，「状态」「资金模式」兩份選項清單會同時存在 DOM 裡（只是沒開的
        那份不可見），選 class 會把兩邊選項混在一起。要用 `<input>` 的 `aria-controls`
        屬性鎖定「這顆下拉當下控制的是哪個 listbox」，只讀那個 listbox 底下的選項。
        """
        combobox = self.page.get_by_role("combobox", name="状态")
        combobox.locator("xpath=../../..").click()
        self.page.wait_for_timeout(200)
        listbox_id = combobox.get_attribute("aria-controls")
        options = self.page.locator(f"#{listbox_id} .el-select-dropdown__item").all_inner_texts()
        self.page.keyboard.press("Escape")
        return [o.strip() for o in options]

    def money_type_options(self) -> list[str]:
        """開啟「资金模式」下拉，讀取選項文字後按 Escape 收起（結構性掃描：下拉選單本身正不正常）。

        跟 `status_options()` 同一套寫法（同一個陷阱、同一個 `aria-controls` 鎖定手法）。
        ⚠️ 這條**不需要任何帳號**——純粹檢查下拉選單開不開得起來、選項是不是「信用／现金」，
        不牽涉「篩選後結果對不對」（那才需要一個现金模式帳號，見 `filter_money_type` 與
        C6 案例的 skip reason）。2026-08-28 補：C6 原本把這兩件事綁在一起測，缺现金帳號時
        連這條本來測得到的結構檢查也一起被 skip 掉了，這支方法把它拆出來。
        """
        combobox = self.page.get_by_role("combobox", name="资金模式")
        combobox.locator("xpath=../../..").click()
        self.page.wait_for_timeout(200)
        listbox_id = combobox.get_attribute("aria-controls")
        options = self.page.locator(f"#{listbox_id} .el-select-dropdown__item").all_inner_texts()
        self.page.keyboard.press("Escape")
        return [o.strip() for o in options]

    def shows_no_data(self) -> bool:
        """同 `EmptyStatePage.shows_no_data()`：非同步載入，用 `wait_for` 避免立刻檢查撲空。"""
        try:
            self.page.get_by_text("暂无数据").wait_for(state="visible", timeout=12000)
            return True
        except Exception:
            return False

    def open_direct_members(self, account: str) -> None:
        """點該帳號列的「直属会员」——導向「会员」分頁並依這個帳號的內部 ID 過濾
        （⚠️ 是「直屬」會員，不是這條線下所有層級的會員——見 `row_level_breakdown_sum`
        的「会员」欄，那個是整條下線鏈的總數，語意不同）。
        """
        self._row_locator(account).get_by_role("button", name="直属会员").click()
        self.page.wait_for_timeout(600)

    def open_operators_dialog(self, account: str):
        """點該帳號列的「操作员」——彈窗（非導頁），回傳 dialog locator 供呼叫端檢查內容。

        ⚠️ 對話框殼子（標題、表頭）立刻渲染，但表格內容是**開啟後才非同步查詢**——
        `dialog.wait_for(state="visible")` 只確保殼子在，太早讀 `inner_text()` 會撲空
        （讀到表頭就結束，「共 N 条」「暂无数据」都還沒渲染），要再等一下內容跟上。
        """
        self._row_locator(account).get_by_role("button", name="操作员").click()
        dialog = self.page.get_by_role("dialog", name=f"{account} 的操作员")
        dialog.wait_for(state="visible", timeout=8000)
        # ⚠️ 「共 N 条」跟表格本體的空狀態區塊（`el-table` 預設 emptyText）不是同一個
        # render tick 掛上去的——只等前者、或只補固定毫秒數的緩衝，都在 2026-08-28 全量跑
        # 89 條時各撲空過一次（機率型 race，不是每次都發生）。改成直接等「暂无数据」這個
        # 文字本身出現，才是真正決定性的等待條件——呼叫端固定會斷言這段文字，這裡先等好，
        # 之後 `inner_text()` 就不會提早讀到殼子。
        dialog.get_by_text("暂无数据").wait_for(state="visible", timeout=8000)
        return dialog

    def open_logs_page(self, account: str) -> None:
        """點該帳號列的「日志」——導向獨立的日誌頁（`/user/account/<id>/logs`），
        非彈窗，跟「操作员」不同（見 `open_operators_dialog` 的說明）。
        """
        self._row_locator(account).get_by_role("button", name="日志").click()
        self.page.wait_for_timeout(600)

    def switch_logs_tab(self, tab_name: str) -> None:
        """在日誌頁切換「操作日志」／「登录日志」子頁籤。

        ⚠️ 這是 Element Plus 的 segmented 控件，`role=radio` 解析到的 `<input>` 本身不可見
        （視覺上顯示的是包住它的 `<label>`），要點 `<label>` 才點得到——跟 `filter_money_type`
        「不能點 combobox 的 input 本身」是同一種陷阱的另一種變形。
        """
        self.page.locator("label").filter(has_text=tab_name).click()
        self.page.wait_for_timeout(400)

    def logs_table_headers(self) -> list[str]:
        return self.page.locator("table thead th").all_inner_texts()

    def logs_row_count(self) -> int:
        """讀日誌頁表格下方分頁列「共 N 条」的 N（跟 `table_total_count` 同款式，
        獨立一份是因為日誌頁是不同的路由/元件，不共用 `AgentHierarchyPage` 主表格的 DOM）。
        """
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
    """注單數據（`/bet/summary`）／報表（`/report/share`）——目前無真實下注資料的空狀態頁面。

    ⚠️ 2026-08-28 MCP 實測確認：點「注单数据」「报表」這兩個**父選單**後，畫面上還會出現
    第二層選單——「注单数据」底下是「注单概览」（預設落地，`/bet/summary`）／「注单明细」；
    「报表」底下是「占成报表」（預設落地，`/report/share`）／「玩法报表」。
    `goto_bet_summary()`／`goto_report()` 目前都只點父選單一次，實際落地在各自的
    **預設子頁面**，不是父選單本身——呼叫端（`tests/xzh/test_reports.py`）的 allure suite
    標籤已依此更正為子頁面名稱（「注单概览」「占成报表」），不是這裡的父選單名稱。
    """

    def __init__(self, page: Page):
        self.page = page

    def goto_bet_summary(self) -> None:
        """導覽到「注单数据→注单概览」（預設落地頁）。"""
        self.page.get_by_role("menuitem", name="注单数据").click()

    def goto_bet_detail(self) -> None:
        """導覽到「注单数据→注单明细」子頁面（`/bet/detail`）。

        2026-08-28 實測：欄位跟「注单概览」不同（注单编号／会员／投注时间／号码／
        投注金额／赔率／总监赔率／中奖／下级实付／下级退水／IP），多一個「号码」篩選欄位。
        """
        self.goto_bet_summary()
        self.page.get_by_role("menuitem", name="注单明细").click()
        self.page.wait_for_timeout(600)

    def goto_report(self) -> None:
        """導覽到「报表→占成报表」（預設落地頁）。"""
        self.page.get_by_role("menuitem", name="报表").click()

    def goto_play_type_report(self) -> None:
        """導覽到「报表→玩法报表」子頁面（`/report/play-type`）。

        2026-08-28 實測：依「遊戲×玩法」分組，欄位跟「占成报表」不同（少「人数」欄、
        多「贡献度」欄）；探索當下已有真實資料（如「英国赛车／大小」1 注）。
        """
        self.goto_report()
        self.page.get_by_role("menuitem", name="玩法报表").click()
        self.page.wait_for_timeout(600)

    def shows_no_data(self) -> bool:
        """用 `wait_for` 而非直接 `is_visible()`——切選單後內容非同步載入，
        立刻檢查會撲空；真的沒有這段文字時逾時回 False，仍是有效的否定結果。
        """
        try:
            self.page.get_by_text("暂无数据").wait_for(state="visible", timeout=12000)
            return True
        except Exception:
            return False
