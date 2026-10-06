# -*- coding: utf-8 -*-
"""公司層「系統設置」Page Object（`/setting/*`，8 個子選單）。

用途：B 系列案例（系統設置寫入）。
前置條件：已登入公司層。

⚠️ 兩種截然不同的欄位互動方式，2026-08-26 探索時只確認了第一種：
    1. **一般表單欄位**（遊戲設置的「過關彩金上限」等）——本身就是 `spinbutton`/`textbox`，
       直接 `.fill()` 即可。**已用瀏覽器實測確認**。
    2. **玩法 × 盤口的大表格**（賠率設置／降賠設置／退水設置／投注限額）——
       每個儲存格目前顯示為 `button`（accessible name＝目前的值），推測要點擊才會出現
       可編輯的輸入框，**但因寫入權限分類器擋下未能實際點擊確認**（見驗證交接 T8 附註）。
       `set_table_cell()` 是照這個推測寫的，**跑之前请先用 headed 模式跑一次確認**：
       `python -m pytest tests/xzh/test_system_setting.py -k table_cell --headed -s`

⚠️ 飛單設置頁（`/setting/lay-off-setting`）的表格欄位互動方式**不是單一模式**，
   同一列裡有四種不同狀態並存（2026-08-26 用 browser_snapshot／browser_evaluate 唯讀確認）：
   自留口徑＝純文字（不可編輯）、每選項自留上限＝`input-number-readonly is-disabled`（鎖住）、
   自動飛單＝`el-switch is-disabled`（鎖住，見 `toggle_auto_lay_off` 註解）、
   最小飛單額＝`input-number-readonly` 可點擊（同 `set_table_cell` 的點格模式）、
   開關選項設置＝`el-switch` 可切換。不要假設整張表都同一種互動方式。

⚠️ 2026-10-02 表頭「開啟飛單選項明細設定」改名為「開關選項設置」（RD 刻意改名，Aaron 當日 14:28 確認，交接檔 T90）；
   下方註解與 docstring 已改用新名。

⚠️ 2026-10-02 公司層「飛單設置」不再顯示「自動飛單」欄（Aaron 2026-10-02 17:25 確認是 RD 刻意改動，交接檔 T94；
   不開單）。QAT 實測（aaron01／aaa111／aaa222，三彩種）：
   - 公司層：表頭 5 欄（玩法／自留口徑／每選項自留上限／最小飛單額／開關選項設置），玩法資料列 5 個 cell；
   - 代理層：表頭 6 欄（多一欄「自動飛單」，位於「每選項自留上限」與「最小飛單額」之間），玩法資料列 6 個 cell。
   舊版方法依「固定第幾個 cell」定位（自動飛單 nth(3)、最小飛單額 nth(4)、開關選項設置 nth(5)），公司層會整批錯位；
   現改為**依表頭名稱定位**（`column_headers()`／`_col()`）。公司層沒有「自動飛單」欄時，
   `is_auto_lay_off_*`／`toggle_auto_lay_off` 丟 `AutoLayOffColumnAbsent`，呼叫端先用 `has_auto_lay_off_column()` 判斷。
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


class AutoLayOffColumnAbsent(LookupError):
    """目前這一層的「飛單設置」頁沒有「自動飛單」欄（2026-10-02 起公司層即是如此，Aaron 當日確認是 RD 刻意改動）。"""


class SystemSettingPage:
    # 飛單設置頁的表頭名稱（簡體字為畫面實際文字）。
    COL_CAP = "每选项自留上限"
    COL_AUTO = "自动飞单"
    COL_MIN = "最小飞单额"
    COL_DETAIL = "开关选项设置"

    def __init__(self, page: Page):
        self.page = page

    # ---- 飛單設置：依表頭名稱定位欄位（2026-10-02，交接檔 T94）----
    def column_headers(self) -> list[str]:
        """飛單設置頁目前可見的表頭文字（畫面順序）。公司層 5 欄、代理層 6 欄。

        重新整理或換彩種後表頭是非同步渲染的：先等第一個表頭出現（最多 15 秒）再讀，
        逾時（頁面沒有這張表）回空清單，由呼叫端的 `_col()` 丟出明確錯誤。
        """
        headers = self.page.get_by_role("columnheader")
        try:
            headers.first.wait_for(state="attached", timeout=15000)
        except Exception:
            return []
        self.page.wait_for_timeout(100)
        return [t.strip() for t in headers.all_inner_texts() if t.strip()]

    def has_auto_lay_off_column(self) -> bool:
        """這一層的飛單設置頁是否有「自動飛單」欄（公司層 2026-10-02 起沒有；代理層有）。"""
        return self.COL_AUTO in self.column_headers()

    def _col(self, name: str, headers: list[str] | None = None) -> int:
        """表頭 `name` 對應的資料格索引（資料列 cell 與表頭一對一，由左而右）。"""
        headers = headers if headers is not None else self.column_headers()
        if name in headers:
            return headers.index(name)
        if name == self.COL_AUTO:
            raise AutoLayOffColumnAbsent(
                f"目前層級的「飛單設置」頁沒有「{self.COL_AUTO}」欄（表頭={headers}）。"
                "公司層 2026-10-02 起不顯示該欄（Aaron 當日確認是 RD 刻意改動，交接檔 T94）；"
                "呼叫前請先用 has_auto_lay_off_column() 判斷。"
            )
        raise LookupError(f"飛單設置頁找不到表頭「{name}」（表頭={headers}）")

    def goto(self, submenu: str) -> None:
        """導覽到系統設置的指定子選單，如「游戏设置」「投注限额」等。"""
        system_item = self.page.get_by_role("menuitem", name="系统设置", exact=True)
        if system_item.count() == 0 or not system_item.last.is_visible():
            # 1280px 寬度時頂部「系统设置」會被收進最後一個「…」溢出子選單，
            # 與 LayOffDetailSettingPage.goto() 的導覽規則一致。
            overflow = self.page.locator(".el-menu--horizontal > .el-sub-menu").last
            expect(overflow).to_be_visible()
            overflow.click()
            expect(system_item.last).to_be_visible()
        system_item.last.click()
        self.page.get_by_role("menuitem", name=submenu, exact=True).click()
        # 子選單內容是非同步載入的，給緩衝時間再讓呼叫端讀欄位
        self.page.wait_for_timeout(1200)

    def save(self) -> None:
        self.page.get_by_role("button", name="保存").click()

    # ---- 遊戲設置：已驗證的一般欄位（B3）----
    #
    # ⚠️⚠️ 真實前端 bug（2026-08-26 用網路攔截＋截圖＋使用者實機操作三方確認，非測試碼問題）：
    # 剛登入、第一次進「游戲設置」頁時，開盤時間／關盤時間／過關彩金上限這三個欄位**畫面空白**，
    # 但 `GET /api/GameSettings?gameId=<id>` 其實已經正確回傳資料（例：`openTime":"17:00:00"`）——
    # 是前端沒有把已經拿到的資料繫結進這幾個欄位，不是後端或 API 的問題。
    # 空白狀態下直接按「保存」，會把空字串送進 `PUT /api/GameSettings`，後端回 400
    # （`$.openTime` 無法轉成 TimeOnly）。
    # **確認過的觸發／解法**：切到上方任一其他彩種卡片、再切回目標彩種，欄位就會正確顯示數值，
    # 之後保存就正常——`ensure_fields_loaded()` 就是做這件事，任何要操作這幾個欄位的案例
    # 都要先呼叫它，不要只是多等幾秒（單純加長 `wait_for_timeout` 沒用，已實測過）。
    def ensure_fields_loaded(self, this_game: str, other_game: str) -> None:
        """繞過「游戲設置」欄位初次進入時空白的前端 bug：切到別的彩種卡片再切回來。

        `this_game`／`other_game` 用彩種卡片上的中文名稱（如「香港六合彩」「英国天天彩」）。
        """
        self.page.get_by_text(other_game, exact=True).first.click()
        self.page.wait_for_timeout(1500)
        self.page.get_by_text(this_game, exact=True).first.click()
        self.page.wait_for_timeout(1500)

    def set_pass_bonus_cap(self, value: str) -> None:
        self.page.get_by_role("spinbutton", name="过关彩金上限").fill(value)

    # ---- 遊戲設置：開盤／關盤時間（B24）----
    # 2026-08-29 實測：這兩顆是 Element Plus 時間選擇器（`combobox`），點擊會彈出
    # 時／分兩欄的滾輪選單，**但不需要真的用滾輪選**——直接對 combobox `.fill("HH:MM:SS")`
    # 再按 Enter 就會被接受、彈窗自動關閉，跟一般 spinbutton 欄位一樣簡單。
    # 屬於「一般表單欄位」那一類（按頁面「保存」才持久化，不像最小飛單額是 Enter 即時送出）。
    def opening_time(self) -> str:
        return self.page.get_by_role("combobox", name="开盘时间").input_value()

    def set_opening_time(self, value: str) -> None:
        field = self.page.get_by_role("combobox", name="开盘时间")
        field.fill(value)
        field.press("Enter")
        self.page.wait_for_timeout(300)

    def closing_time(self) -> str:
        return self.page.get_by_role("combobox", name="关盘时间").input_value()

    def set_closing_time(self, value: str) -> None:
        field = self.page.get_by_role("combobox", name="关盘时间")
        field.fill(value)
        field.press("Enter")
        self.page.wait_for_timeout(300)

    def pass_bonus_cap(self) -> str:
        """讀「過關彩金上限」目前值。

        ⚠️ 若是**剛進頁面第一次讀**，這裡幾乎必定是空字串——不是等待時間不夠，
        是上面說的前端 bug，要先呼叫 `ensure_fields_loaded()` 才讀得到真值。
        這裡保留的 `expect(...).not_to_have_value("")` 只防守一般的非同步繪製延遲，
        擋不住那個 bug（已實測：等 12 秒一樣是空字串）。
        """
        field = self.page.get_by_role("spinbutton", name="过关彩金上限")
        try:
            expect(field).not_to_have_value("", timeout=12000)
        except AssertionError:
            pass
        return field.input_value()

    # ---- 大表格（賠率/降賠/退水/投注限額）：互動方式未經 MCP 驗證，見檔頭說明 ----
    def set_table_cell(self, row_name_prefix: str, column_index: int, value: str) -> None:
        """點指定玩法列（用列文字開頭比對，避免撞到子字串，如「两面」不誤中「正特码」）、
        第 `column_index` 個儲存格（0-based，不含「玩法」欄本身），輸入新值。

        ⚠️ 推測寫法，未經實測確認，見本檔檔頭說明。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(column_index + 1)  # +1 跳過「玩法」欄
        cell.get_by_role("button").click()
        editable = cell.get_by_role("textbox")
        if editable.count() == 0:
            editable = cell.get_by_role("spinbutton")
        editable.fill(value)
        self.page.keyboard.press("Enter")

    # ---- 飛單設置：「自動飛單」開關（B5）----
    # 2026-08-26 用 browser_snapshot ＋ browser_evaluate 唯讀確認：
    # 欄位是標準 Element Plus `el-switch`（role=switch），無 accessible name
    # （同一列右邊「開關選項設置」也是一個 switch，兩者都不帶 name，只能靠欄位順序區分，
    # 不能用 get_by_role("switch", name=...)）。
    # 抽查全部 70 個玩法列（含「仓位型」與「占成型」兩種自留口徑）發現：
    # ⚠️ 2026-08-28 用「cell 數＝6」精確計數才發現：先前這裡與相關文件記錄的
    # 「68 個玩法列」是誤算，實際是 70 個（見 B16 `row_count()` 的檔頭說明），已一併更正。
    # 「自動飛單」這顆 switch **每一列在當下都是 disabled**（`input.disabled===true`）。
    #
    # ⚠️⚠️ 2026-08-26 追加驗證，更正先前的誤判：**這不是「環境整個鎖死」，是兩個開關的
    # 互斥關係**——「開關選項設置」開著的時候，「自動飛單」才會被鎖住；
    # 把「開關選項設置」關掉，「自動飛單」立刻變成可互動，且此互動只發生在前端
    # （切換當下沒有任何 API 請求送出，不必擔心殘留測試資料）。已用 `browser_evaluate`
    # 現場切一列驗證可逆：明細設定 開→自動飛單 disabled；明細設定 關→自動飛單 可切換；
    # 明細設定 切回開→自動飛單 重新鎖回 disabled，跟切之前完全一致。
    # 先前誤判的原因是**只做了唯讀抽查，沒有測試「反過來關掉另一個開關會怎樣」**——
    # 68 列剛好全部都是「明細設定開著」的狀態，才會誤以為是全站鎖死。
    # ✅ **使用者 2026-08-26 裁定：這是刻意設計，非缺陷**（矩陣 K4 已判定非缺陷，交接檔 T11
    # 已關閉，不開單）。兩者是二選一的互斥模式，不是「值為關閉」那種待修的環境限制。
    #
    # ⚠️ 點擊寫法的陷阱：Element Plus 的 `el-switch` 真正接收點擊的是外層 `.el-switch`
    # 容器（視覺上的滑塊），role="switch" 對應到的 `<input>` 本身是視覺隱藏的（用來給
    # accessibility tree 讀狀態），Playwright 的 actionability 檢查判它「not visible」，
    # 直接對 `get_by_role("switch")` 呼叫 `.click()` 會逾時失敗。**讀狀態**可以用
    # role="switch"（`aria-checked`／`aria-disabled` 都在這顆元素上）；**要點擊切換**
    # 必須改點同一格內的 `.el-switch` 容器——下面兩個 `set_*`／`toggle_*` 方法已這樣寫，
    # 2026-08-26 已用 MCP 現場驗證可正常點擊與還原。
    def is_auto_lay_off_enabled(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「自動飛單」開關目前是否為開啟狀態（不判斷是否可互動）。"""
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        switch = row.get_by_role("cell").nth(self._col(self.COL_AUTO)).get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def is_auto_lay_off_toggleable(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「自動飛單」開關目前是否可互動（非 disabled）。

        ⚠️ 2026-08-26 實測：QAT 現況下，只要同列「開關選項設置」是開的，這裡就會
        回 False——這是**互斥關係**，不是環境鎖死。要讓它變 True，先用
        `set_lay_off_detail_mode(row, False)` 關掉那顆開關。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        switch = row.get_by_role("cell").nth(self._col(self.COL_AUTO)).get_by_role("switch")
        return switch.get_attribute("aria-disabled") != "true"

    def is_lay_off_detail_mode_enabled(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「開關選項設置」開關目前是否為開啟狀態。

        ⚠️ 這顆開關與「自動飛單」互斥（見本方法群組上方註解）：開著時「自動飛單」被鎖住。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        switch = row.get_by_role("cell").nth(self._col(self.COL_DETAIL)).get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    # 把「開關選項設置」切到開啟時跳出的確認框標題（2026-10-02 前名為「启用飞单选项明细」）。
    ENABLE_CONFIRM_TITLE = "开启选项设置"

    def confirm_enable_dialog(self, timeout_ms: int = 3000) -> bool:
        """若「开启选项设置」確認框出現就按「确定」，回傳是否真的按了。

        框內文字：「是否开启选项设置功能？原系统设置－飞单设置中，飞单设置的金额将会失效，并且自动出货将变更为手动模式，
        请确认！」，按鈕「取消」「确定」。按「确定」前開關畫面狀態不會變成開啟（2026-10-02 公司層與代理層實測）。
        """
        dialog = self.page.get_by_role("dialog", name=self.ENABLE_CONFIRM_TITLE)
        try:
            dialog.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            return False
        dialog.get_by_role("button", name="确定").click()
        dialog.wait_for(state="hidden")
        return True

    def set_lay_off_detail_mode(self, row_name_prefix: str, enable: bool, confirm: bool = True) -> None:
        """把指定玩法列的「開關選項設置」開關切到 `enable` 狀態。

        ⚠️ 2026-10-02 實測（T94 實跑 B36-2／B56 時發現，公司層與代理層皆然）：切到**開啟**時會跳「开启选项设置」確認框，
        按「确定」前開關與連動欄位（每選項自留上限等）都還沒變成開啟後的樣子。舊案例（B29／B34／B36 等）切回開啟後
        沒有處理它（確認框何時開始出現無從考證：2026-08-31 的 B36-1 當時 PASS，HEAD 版 B85 已在代理層處理同名舊標題確認框）。
        `confirm=True`（預設）會在切到開啟後偵測確認框並按「确定」
        （切到關閉不會跳框）；呼叫端若要自己處理確認框（例如要驗「取消」或 B85～B87 的既有寫法）傳 `confirm=False`。
        「确定」之後仍是純前端狀態，要持久化一樣得 `save()`（見下）。

        ⚠️ 2026-08-26 實測：**單獨點擊**這個切換只影響前端當下狀態，不會送出任何 API 請求
        （不是「保存」動作）——切完不必特別還原網路層面的東西，但仍要把畫面狀態切回
        原樣（見 CLAUDE.md §5），避免影響同一頁面接下來的操作或別的案例的前置假設。

        ✅ 2026-08-31 補充確認（B29／B34，交接檔 T20 已結案）：機制文件 §5.2 是對的——
        切完之後只要呼叫 `save()`，這個當下狀態**就會被持久化**，不需要額外對「最小飛單額」
        之類的欄位再做一次 Enter。整列持久化因此有兩條路徑都通：①按保存；②對任一
        Enter-即時持久化欄位（見 `set_cap_value`／`set_min_lay_off_amount`）做 Enter。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(self._col(self.COL_DETAIL))
        current = cell.get_by_role("switch").get_attribute("aria-checked") == "true"
        if current != enable:
            cell.locator(".el-switch").click()
            if enable and confirm:
                self.confirm_enable_dialog()

    def toggle_auto_lay_off(self, row_name_prefix: str, enable: bool) -> None:
        """把指定玩法列的「自動飛單」開關切到 `enable` 狀態（只在目前值不同才點擊）。

        ⚠️ 呼叫前請先用 `is_auto_lay_off_toggleable` 確認可互動；若回 False，先用
        `set_lay_off_detail_mode(row, False)` 關掉互斥的「開關選項設置」
        （見本方法群組上方 2026-08-26 追加驗證的註解）。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(self._col(self.COL_AUTO))
        current = cell.get_by_role("switch").get_attribute("aria-checked") == "true"
        if current != enable:
            cell.locator(".el-switch").click()

    def table_row_text(self, row_name_prefix: str) -> str:
        """讀取指定玩法列的文字。

        ⚠️ 用 `filter(has_text=...)` 而非 `get_by_role("row", name=regex)`——
        2026-08-26 實測發現後者對 row 的 accessible name 比對不準（表格已確實渲染、
        `all_inner_texts()` 也讀得到該列，但 role name regex 卻抓不到），
        `filter(has_text=...)` 是 Playwright 官方建議、基於實際文字內容篩選的作法，更穩定。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        row.wait_for(state="visible", timeout=15000)
        return row.inner_text()

    # ---- 飛單設置：結構性掃描與 2026-08-28 複掃新增方法（B8/B9/B10/B16）----
    #
    # ⚠️⚠️ 2026-08-28 MCP 唯讀+寫入實測發現一個與 K1/K3/K5/K6 大表格不同的行為：
    # 「最小飛單額」欄位**每次按 Enter 就立刻送出 API 並持久化**，不需要再按頁面下方的
    # 「保存」按鈕——已用「填入 999999999 → Enter → reload 頁面」三方確認新值仍在，
    # 證實不是前端暫存。這跟同一頁「開關選項設置」（純前端切換，不點保存不會送出，
    # 見上面 `set_lay_off_detail_mode` 的註解）是兩種完全不同的持久化模式，
    # 呼叫端**不要**在改完 `set_min_lay_off_amount` 後又去按 `save()`（那是給一般表單欄位用的）。
    #
    # ⚠️ 邊界值實測（同一輪）：負數（如 `-5`）會被前端拒絕、Enter 後欄位打回原值，
    # 不會送出任何 API；超大值（如 `999999999`）會被接受並直接持久化。
    def switch_game(self, game_name: str) -> None:
        """切換上方彩種卡片（如「香港六合彩」「英国天天彩」「宾果六合彩」），並等待表格重新載入。

        ⚠️ 沿用 `ensure_fields_loaded()` 已驗證過的卡片點擊方式；飛單設置頁沒有像
        「游戏规则」頁那樣的固定文字可等待內容真的換掉，改用固定等待（見
        `browser-ops` §7 增量驗證的權衡：等內容不如等結構穩定的頁面更難抓等待條件）。
        """
        self.page.get_by_text(game_name, exact=True).first.click()
        self.page.wait_for_timeout(1200)

    def locked_row_count(self) -> int:
        """回傳目前彩種下，明細設定＝開啟 且 自動飛單＝disabled 的一致鎖定列數。

        用途：B28 環境健康度基線、B27 三彩種鎖定列數比對。判準與 `row_count()` 用同一種
        「cell 數＝表頭欄數」結構特徵篩資料列，逐列讀 switch 的狀態，不受分組展開/收合影響。

        ⚠️ 2026-10-02 起公司層沒有「自動飛單」欄（交接檔 T94）：此時「鎖定」改以
        「開關選項設置＝開啟 且 每選項自留上限不可編輯（非 button）」判斷——這是受它連動的另一個欄位，
        `consistent_row_count()` 本來就把它當同一組判準；代理層仍照原判準（自動飛單 disabled）。
        """
        headers = self.column_headers()
        n_cols = len(headers)
        i_detail = self._col(self.COL_DETAIL, headers)
        i_auto = headers.index(self.COL_AUTO) if self.COL_AUTO in headers else None
        i_cap = self._col(self.COL_CAP, headers)
        rows = self.page.get_by_role("row")
        count = 0
        for i in range(rows.count()):
            row = rows.nth(i)
            cells = row.get_by_role("cell")
            if cells.count() != n_cols:
                continue
            detail_checked = cells.nth(i_detail).get_by_role("switch").get_attribute("aria-checked")
            if i_auto is not None:
                other_locked = cells.nth(i_auto).get_by_role("switch").get_attribute("aria-disabled") == "true"
            else:
                other_locked = cells.nth(i_cap).get_by_role("button").count() == 0
            if detail_checked == "true" and other_locked:
                count += 1
        return count

    def consistent_row_count(self) -> tuple[int, int]:
        """回傳 (狀態自洽的列數, 總列數)：檢查每列「開關選項設置」與「自動飛單」／
        「每選項自留上限」兩個受它連動的欄位是否互相一致——**不預設該列目前是鎖定或解鎖**，
        只要求兩者同步（明細設定開⇄自動飛單 disabled 且自留上限不可編輯；明細設定關⇄兩者
        皆可互動）。

        用途：B55（非預設彩種環境健康度基線）。B28 用的 `locked_row_count() == total` 判準
        只適用於「全部列本來就該是鎖定」的彩種（香港六合彩 70/70 皆鎖定）；英國天天彩／
        賓果六合彩的環境現況大部分列本來就是解鎖狀態（見矩陣 K4、案例 B27），不能沿用同一個
        判準，必須改成「不管鎖定或解鎖，兩個受連動欄位有沒有同步」這個更寬鬆但仍然嚴謹的版本。

        ⚠️ 2026-10-02 起公司層沒有「自動飛單」欄（交接檔 T94）：此時只檢查「開關選項設置」與
        「每選項自留上限」兩者是否同步（自動飛單那一項不存在，不計入）；代理層仍檢查三者。
        """
        headers = self.column_headers()
        n_cols = len(headers)
        i_detail = self._col(self.COL_DETAIL, headers)
        i_auto = headers.index(self.COL_AUTO) if self.COL_AUTO in headers else None
        i_cap = self._col(self.COL_CAP, headers)
        rows = self.page.get_by_role("row")
        total = 0
        consistent = 0
        for i in range(rows.count()):
            row = rows.nth(i)
            cells = row.get_by_role("cell")
            if cells.count() != n_cols:
                continue
            total += 1
            detail_on = cells.nth(i_detail).get_by_role("switch").get_attribute("aria-checked") == "true"
            cap_editable = cells.nth(i_cap).get_by_role("button").count() > 0
            if i_auto is None:
                auto_ok = True
            else:
                auto_disabled = cells.nth(i_auto).get_by_role("switch").get_attribute("aria-disabled") == "true"
                auto_ok = auto_disabled if detail_on else (not auto_disabled)
            cap_ok = (not cap_editable) if detail_on else cap_editable
            if auto_ok and cap_ok:
                consistent += 1
        return consistent, total

    def group_toggle_labels(self) -> list[str]:
        """讀取飛單設置表格目前可收合分組的按鈕文字（如「連碼」「連肖」…）。"""
        return self.page.get_by_role("button", name="收起当前行").locator("..").all_inner_texts()

    def row_count(self) -> int:
        """表格目前渲染的玩法資料列數。

        ⚠️ 不能用「總列數 - 表頭 - 分組列數」推算——2026-08-28 實測這樣算不出正確數字
        （分組展開/收合、巢狀列渲染方式跟預期不同）。改用**資料列本身的結構特徵**：
        玩法資料列的 `cell` 數＝表頭欄數（代理層 6 個：玩法／自留口徑／每選項自留上限／自動飛單／
        最小飛單額／開關選項設置；公司層 5 個：少了「自動飛單」，2026-10-02 起，交接檔 T94），
        分組收合列只有 1 個 cell（「收起當前行 <分組名>」），表頭列的 `columnheader` 不算 `cell`——
        用 cell 數＝表頭欄數篩選，不受分組展開狀態影響。
        """
        n_cols = len(self.column_headers())
        if n_cols < 2:  # 表頭還沒渲染：不可拿 0 當欄數（表頭列自己的 cell 數就是 0）
            return 0
        rows = self.page.get_by_role("row")
        count = 0
        for i in range(rows.count()):
            if rows.nth(i).get_by_role("cell").count() == n_cols:
                count += 1
        return count

    def min_lay_off_amount(self, row_name_prefix: str) -> str:
        """讀取指定玩法列「最小飛單額」目前顯示值（未點擊前的 button 文字）。"""
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        return row.get_by_role("cell").nth(self._col(self.COL_MIN)).inner_text()

    def is_min_lay_off_amount_editable(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「最小飛單額」欄位目前是否為可編輯的 button（未點擊前的顯示態）。

        ⚠️ 這欄跟「每選項自留上限」不同——所有 70 列的「最小飛單額」目前都恆是
        可點擊的 button（2026-08-28 已抽查特码列確認），不像「每選項自留上限」
        只有 `一比五`／`一比六` 兩列是 button、其餘 68 列是純文字。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(self._col(self.COL_MIN))
        return cell.get_by_role("button").count() > 0

    def set_min_lay_off_amount(self, row_name_prefix: str, value: str) -> str:
        """把指定玩法列「最小飛單額」改成 `value`（點格→輸入→Enter），回傳 Enter 後畫面顯示的值。

        ⚠️ 見本方法群組上方註解——這欄按 Enter 就即時持久化，**不需要**呼叫 `save()`。
        回傳值可用來判斷輸入是否被前端拒絕（拒絕時會打回原值，不等於 `value`）。

        ✅ 2026-08-31 補充驗證（B9，網路攔截確認）：Enter 當下就已經送出 `PUT`——輸入合法
        新值時 payload 帶著新值、204 成功；輸入被前端拒絕的非法值（如負數）時，畫面已把
        欄位打回原值，Enter 送出的 `PUT` payload 是空陣列 `{"settings": []}`（不是完全不送，
        是送了但沒有變更內容）。**呼叫端額外再點頁面「保存」按鈕不會改變結果**——因為 Enter
        已經把「有沒有變更」這件事處理掉了，之後再點保存送出的 `PUT` 一律是空陣列，不影響
        這欄或其他列的資料。這就是「不需要」呼叫 `save()` 的真正原因：不是按了會出錯，
        是按了本來就不會有任何效果。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(self._col(self.COL_MIN))
        cell.get_by_role("button").click()
        field = cell.get_by_role("spinbutton")
        field.fill(value)
        field.press("Enter")
        self.page.wait_for_timeout(500)
        return cell.inner_text()

    def is_cap_editable(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「每選項自留上限」欄位目前是否為可編輯 button。

        ⚠️ 2026-08-28 發現：這是判斷該列是否處於「解鎖」狀態的旁證欄位之一——
        68 列鎖定狀態下是純文字（不可編輯），只有 `一比五`／`一比六`（目前唯二解鎖的例外列）
        是 button。跟 `is_auto_lay_off_toggleable()` 一起讀，兩者狀態應該一致
        （同時可編輯／同時鎖定），若不一致代表這個假說不成立，需要重新調查（見交接檔 T17）。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(self._col(self.COL_CAP))
        return cell.get_by_role("button").count() > 0

    def cap_value(self, row_name_prefix: str) -> str:
        """讀取指定玩法列「每選項自留上限」目前顯示值（不管鎖定或解鎖狀態都讀得到）。"""
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        return row.get_by_role("cell").nth(self._col(self.COL_CAP)).inner_text()

    def set_cap_value(self, row_name_prefix: str, value: str) -> str:
        """把指定玩法列「每選項自留上限」改成 `value`（點格→輸入→Enter），回傳 Enter 後畫面顯示的值。

        ⚠️⚠️ 2026-08-29 實測發現的重要陷阱：**這欄跟「最小飛單額」一樣是 Enter 即時持久化**，
        但送出的 API 是**整列**的資料，會把當下「開關選項設置」的狀態也一併寫進去。
        意思是：解鎖某列（`set_lay_off_detail_mode(row, False)`）後呼叫本方法編輯自留上限，
        Enter 送出的那次 API 呼叫**會把「明細設定＝關閉（解鎖）」也順便持久化**——即使之後
        再呼叫 `set_lay_off_detail_mode(row, True)` 想鎖回去，那個切換**本身不送 API**
        （見該方法註解），該列的後端狀態依然是解鎖的殘留。

        **收尾鎖回程序**（呼叫端測完邊界值後必須照做，不能只切開關）——**2026-08-31 更正
        （交接檔 T20 已結案）**：本檔頭原本寫「只能」靠對「最小飛單額」再 Enter 一次才救得回來，
        這個說法**不完整**。實測（B29／B34）證實 `save()` 本身就能持久化「開啟飛單選項明細
        設定」的當下狀態，是更直接的作法：
        ```python
        sp.set_lay_off_detail_mode(row, True)  # 切回鎖定（純前端）
        sp.save()                              # 按保存即可持久化，不必再找別的欄位補一次 Enter
        ```
        原本記載的「對『最小飛單額』無變化重填」寫法**仍然有效**（是另一條也走得通的路徑，
        因為那欄同樣是 Enter 即時持久化、送出的也是整列資料），兩者擇一即可，優先建議用
        `save()`，語意更直接。
        負數邊界值實測：會被前端拒絕，Enter 後打回 **0**（不是打回原值，跟「最小飛單額」的
        「打回原值」不同，屬於 el-input-number 的 min=0 邊界，呼叫端斷言時要注意這個差異）。
        超大值：會被接受並直接持久化。後端契約已確認（B32）：負數同樣被後端拒絕（500，
        `FluentValidation` 例外，非乾淨 400）、超大值後端也接受——前端擋法與後端一致，無資料
        完整性缺口。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(self._col(self.COL_CAP))
        cell.get_by_role("button").click()
        field = cell.get_by_role("spinbutton")
        field.fill(value)
        field.press("Enter")
        self.page.wait_for_timeout(500)
        return cell.inner_text()
