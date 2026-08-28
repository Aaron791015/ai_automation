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
   開啟飛單選項明細設定＝`el-switch` 可切換。不要假設整張表都同一種互動方式。
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


class SystemSettingPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self, submenu: str) -> None:
        """導覽到系統設置的指定子選單，如「游戏设置」「投注限额」等。"""
        self.page.get_by_role("menuitem", name="系统设置").click()
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
    # （同一列右邊「開啟飛單選項明細設定」也是一個 switch，兩者都不帶 name，只能靠欄位順序區分，
    # 不能用 get_by_role("switch", name=...)）。
    # 抽查全部 70 個玩法列（含「仓位型」與「占成型」兩種自留口徑）發現：
    # ⚠️ 2026-08-28 用「cell 數＝6」精確計數才發現：先前這裡與相關文件記錄的
    # 「68 個玩法列」是誤算，實際是 70 個（見 B16 `row_count()` 的檔頭說明），已一併更正。
    # 「自動飛單」這顆 switch **每一列在當下都是 disabled**（`input.disabled===true`）。
    #
    # ⚠️⚠️ 2026-08-26 追加驗證，更正先前的誤判：**這不是「環境整個鎖死」，是兩個開關的
    # 互斥關係**——「開啟飛單選項明細設定」開著的時候，「自動飛單」才會被鎖住；
    # 把「開啟飛單選項明細設定」關掉，「自動飛單」立刻變成可互動，且此互動只發生在前端
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
        switch = row.get_by_role("cell").nth(3).get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def is_auto_lay_off_toggleable(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「自動飛單」開關目前是否可互動（非 disabled）。

        ⚠️ 2026-08-26 實測：QAT 現況下，只要同列「開啟飛單選項明細設定」是開的，這裡就會
        回 False——這是**互斥關係**，不是環境鎖死。要讓它變 True，先用
        `set_lay_off_detail_mode(row, False)` 關掉那顆開關。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        switch = row.get_by_role("cell").nth(3).get_by_role("switch")
        return switch.get_attribute("aria-disabled") != "true"

    def is_lay_off_detail_mode_enabled(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「開啟飛單選項明細設定」開關目前是否為開啟狀態。

        ⚠️ 這顆開關與「自動飛單」互斥（見本方法群組上方註解）：開著時「自動飛單」被鎖住。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        switch = row.get_by_role("cell").nth(5).get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def set_lay_off_detail_mode(self, row_name_prefix: str, enable: bool) -> None:
        """把指定玩法列的「開啟飛單選項明細設定」開關切到 `enable` 狀態。

        ⚠️ 2026-08-26 實測：這個切換**只影響前端當下狀態**，不會送出任何 API 請求
        （不是「保存」動作）——切完不必特別還原網路層面的東西，但仍要把畫面狀態切回
        原樣（見 CLAUDE.md §5），避免影響同一頁面接下來的操作或別的案例的前置假設。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(5)
        current = cell.get_by_role("switch").get_attribute("aria-checked") == "true"
        if current != enable:
            cell.locator(".el-switch").click()

    def toggle_auto_lay_off(self, row_name_prefix: str, enable: bool) -> None:
        """把指定玩法列的「自動飛單」開關切到 `enable` 狀態（只在目前值不同才點擊）。

        ⚠️ 呼叫前請先用 `is_auto_lay_off_toggleable` 確認可互動；若回 False，先用
        `set_lay_off_detail_mode(row, False)` 關掉互斥的「開啟飛單選項明細設定」
        （見本方法群組上方 2026-08-26 追加驗證的註解）。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(3)
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
    # 證實不是前端暫存。這跟同一頁「開啟飛單選項明細設定」（純前端切換，不點保存不會送出，
    # 見上面 `set_lay_off_detail_mode` 的註解）是兩種完全不同的持久化模式，
    # 呼叫端**不要**在改完 `set_min_lay_off_amount` 後又去按 `save()`（那是給一般表單欄位用的）。
    #
    # ⚠️ 邊界值實測（同一輪）：負數（如 `-5`）會被前端拒絕、Enter 後欄位打回原值，
    # 不會送出任何 API；超大值（如 `999999999`）會被接受並直接持久化。
    def group_toggle_labels(self) -> list[str]:
        """讀取飛單設置表格目前可收合分組的按鈕文字（如「連碼」「連肖」…）。"""
        return self.page.get_by_role("button", name="收起当前行").locator("..").all_inner_texts()

    def row_count(self) -> int:
        """表格目前渲染的玩法資料列數。

        ⚠️ 不能用「總列數 - 表頭 - 分組列數」推算——2026-08-28 實測這樣算不出正確數字
        （分組展開/收合、巢狀列渲染方式跟預期不同）。改用**資料列本身的結構特徵**：
        玩法資料列固定是 6 個 `cell`（玩法／自留口徑／每選項自留上限／自動飛單／
        最小飛單額／開啟飛單選項明細設定），分組收合列只有 1 個 cell（「收起當前行 <分組名>」），
        表頭列的 `columnheader` 不算 `cell`——用 cell 數＝6 篩選，不受分組展開狀態影響。
        """
        rows = self.page.get_by_role("row")
        count = 0
        for i in range(rows.count()):
            if rows.nth(i).get_by_role("cell").count() == 6:
                count += 1
        return count

    def min_lay_off_amount(self, row_name_prefix: str) -> str:
        """讀取指定玩法列「最小飛單額」目前顯示值（未點擊前的 button 文字）。"""
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        return row.get_by_role("cell").nth(4).inner_text()

    def is_min_lay_off_amount_editable(self, row_name_prefix: str) -> bool:
        """讀取指定玩法列「最小飛單額」欄位目前是否為可編輯的 button（未點擊前的顯示態）。

        ⚠️ 這欄跟「每選項自留上限」不同——所有 70 列的「最小飛單額」目前都恆是
        可點擊的 button（2026-08-28 已抽查特码列確認），不像「每選項自留上限」
        只有 `一比五`／`一比六` 兩列是 button、其餘 68 列是純文字。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(4)
        return cell.get_by_role("button").count() > 0

    def set_min_lay_off_amount(self, row_name_prefix: str, value: str) -> str:
        """把指定玩法列「最小飛單額」改成 `value`（點格→輸入→Enter），回傳 Enter 後畫面顯示的值。

        ⚠️ 見本方法群組上方註解——這欄按 Enter 就即時持久化，**不需要**也**不要**呼叫 `save()`。
        回傳值可用來判斷輸入是否被前端拒絕（拒絕時會打回原值，不等於 `value`）。
        """
        row = self.page.get_by_role("row").filter(has_text=row_name_prefix).first
        cell = row.get_by_role("cell").nth(4)
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
        cell = row.get_by_role("cell").nth(2)
        return cell.get_by_role("button").count() > 0
