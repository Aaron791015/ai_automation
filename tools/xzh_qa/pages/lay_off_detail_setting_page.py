# -*- coding: utf-8 -*-
"""公司層「系統設置→飛單選項明細設置」Page Object（`/setting/lay-off-setting-detail`）。

用途：B11～B14、B17 案例（矩陣 K7）。
前置條件：已登入公司層。

⚠️ 這頁跟同層級的「飛單設置」（`SystemSettingPage`，矩陣 K4）結構完全不同，
   不是「同一張大表格多幾欄」——是「玩法分類（25 個按鈕）→ 每分類自己一張
   1~49 選項表」，且多了一顆「啟用飛單選項明細」總開關，另立一個類別。

⚠️⚠️ 2026-08-28 實測發現「比大小」分類的 UI **跟其餘 24 個分類完全不同**——
   不是「選項 1~N 逐列自動飛單」的標準表格，是先選 6 個子項按鈕之一（一比一～一比六，
   純文字＋`cursor=pointer`，不是語意 `button`／`table`，role 查詢會找不到任何東西），
   選定後顯示的是「組合占成金額」表格（正1特～正6特＋特码 共 7 個組合欄位），
   還多了「关连／不关连」切換與「共用自留上限」規則說明（「此設定下共用自留上限將存為 0，
   該玩法所有組合無條件全飛」）。**這與矩陣 K4「飛單設置」頁的 `一比五`／`一比六` 例外列
   分屬不同層級的概念**——K4 的「一比五/一比六」是玩法整體的一列，K7「比大小」底下的
   「一比五/一比六」則是玩法內的子項，不能直接假設兩者是同一件事的兩種呈現，
   需要規格文件或 RD 確認才能定義兩者關聯的 oracle（見案例 B14、交接檔 T17）。

⚠️⚠️ 2026-08-28 MCP 實測發現「啟用飛單選項明細」總開關是**關鍵的父子層級連動點**，
   直接回答了矩陣 K7／K4 是否連動的疑問（見交接檔 T17、案例清單 B14）：
   - **關閉**：不跳確認框，立即生效（送出 API，reload 後仍是關閉——即時持久化，
     不需要按頁面下方「保存」）。關閉後底下所有選項列的「自動飛單」switch 變成
     disabled（但保留原本 checked 值，不會被清空）、「每選項自留上限」從可編輯
     button 變回純文字、分類工具列「全部設置／一鍵自動／一鍵手動」全部變 disabled。
   - **開啟**：會跳一個 `el-message-box` 確認框，文字明確寫著：
     「是否启用飞单选项明细功能？**原系统设定－飞单设定中，飞单设定的金额将会失效，
     并且自动出货将变更为手动模式**，请确认！」
     ——這就是 A 級 oracle：系統自己承認 K7 總開關開啟時 **K4（飛單設置）的金額設定
     會失效、自動出貨改手動**，兩層不是各自獨立，是互斥切換的父子關係。
     `set_master_switch(True)` 必須點確認框的「確定」才會真的生效，光點開關本身
     只是跳出確認框，不會立刻改變狀態（已實測：點開關但不點確定，reload 後仍是關閉）。
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


class LayOffDetailSettingPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        self.page.get_by_role("menuitem", name="系统设置").click()
        self.page.get_by_role("menuitem", name="飞单选项明细设置", exact=True).click()
        self.page.wait_for_timeout(1200)

    def category_labels(self) -> list[str]:
        """讀取左側／上方玩法分類按鈕的文字清單（結構掃描用，矩陣 K7／案例 B17）。"""
        return self.page.get_by_role("navigation").get_by_role("button").all_inner_texts()

    def select_category(self, name: str) -> None:
        """切到指定玩法分類。

        ⚠️ 不能統一用「分類標題（`heading` level 3）出現」當等待條件——2026-08-28 實測
        發現「比大小」分類**沒有** `heading`（它是完全不同的組合型 UI，見本檔檔頭說明），
        用 `heading` 等待會直接超時。改用**固定等待＋`networkidle`**，犧牲一點精確度
        換取對所有分類（含結構特殊的「比大小」）都適用。
        """
        self.page.get_by_role("button", name=name, exact=True).click()
        self.page.wait_for_load_state("networkidle", timeout=10000)
        self.page.wait_for_timeout(500)

    # ---- 總開關（B11）----
    def is_master_switch_enabled(self) -> bool:
        switch = self.page.get_by_text("启用飞单选项明细", exact=True).locator("..").get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def set_master_switch(self, enable: bool) -> None:
        """把「啟用飛單選項明細」總開關切到 `enable`。

        ⚠️ 開啟時會跳確認框（見檔頭說明），本方法已處理：偵測到 dialog 出現就點「確定」。
        關閉時不會跳確認框，直接生效。兩個方向都**立即送出 API、無需另外按保存**——
        呼叫端用完記得呼叫 `set_master_switch(<原值>)` 還原（見 CLAUDE.md §5）。
        """
        if self.is_master_switch_enabled() == enable:
            return
        self.page.get_by_text("启用飞单选项明细", exact=True).locator("..").locator(".el-switch").click()
        if enable:
            dialog = self.page.get_by_role("dialog", name="启用飞单选项明细")
            dialog.get_by_role("button", name="确定").click()
        self.page.wait_for_timeout(800)

    # ---- 分類工具列（B12）----
    def click_batch_auto(self) -> None:
        self.page.get_by_role("button", name="一键自动").click()
        self.page.wait_for_timeout(500)

    def click_batch_manual(self) -> None:
        self.page.get_by_role("button", name="一键手动").click()
        self.page.wait_for_timeout(500)

    # ---- 分類表格（B12/B13/B14/B17）----
    def _table(self):
        """目前顯示中的分類選項表格（每次只會有一個分類是啟用狀態）。

        ⚠️ 2026-08-28 實測發現「正特码」分類頁面上同時有 **2 個** `table:visible`——
        第 1 個只有表頭沒有資料列（疑似樣板殘留，非本頁重點），第 2 個才是真正的
        49 列資料表。用 `.first` 會抓到空表格；改用 `.last` 才能一律拿到有資料的那個
        （多數分類只有 1 個 table，`.first`／`.last` 結果相同，不受影響）。
        """
        return self.page.locator("table:visible").last

    def option_row_count(self) -> int:
        """目前分類的選項列數（不含表頭）。"""
        return self._table().get_by_role("row").count() - 1

    def option_row(self, option_number: int):
        """依 DOM 順序取第 `option_number` 個選項列（1-based，表頭不算）。"""
        return self._table().get_by_role("row").nth(option_number)

    def option_auto_lay_off_enabled(self, option_number: int) -> bool:
        switch = self.option_row(option_number).get_by_role("cell").nth(3).get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def option_auto_lay_off_toggleable(self, option_number: int) -> bool:
        switch = self.option_row(option_number).get_by_role("cell").nth(3).get_by_role("switch")
        return switch.get_attribute("aria-disabled") != "true"

    def set_option_auto_lay_off(self, option_number: int, enable: bool) -> None:
        """把單一選項列的「自動飛單」開關切到 `enable`（只在目前值不同才點擊）。

        用於批次工具（`click_batch_auto`／`click_batch_manual`）測完後逐一還原個別選項，
        比重新整理頁面猜測原值更明確——呼叫前搭配 `option_auto_lay_off_enabled()`
        記錄原值。
        """
        cell = self.option_row(option_number).get_by_role("cell").nth(3)
        current = cell.get_by_role("switch").get_attribute("aria-checked") == "true"
        if current != enable:
            cell.locator(".el-switch").click()

    def option_cap_editable(self, option_number: int) -> bool:
        cell = self.option_row(option_number).get_by_role("cell").nth(2)
        return cell.get_by_role("button").count() > 0

    def option_cap_value(self, option_number: int) -> str:
        return self.option_row(option_number).get_by_role("cell").nth(2).inner_text()

    def set_option_cap(self, option_number: int, value: str) -> None:
        cell = self.option_row(option_number).get_by_role("cell").nth(2)
        cell.get_by_role("button").click()
        field = cell.get_by_role("spinbutton")
        field.fill(value)
        field.press("Enter")
        self.page.wait_for_timeout(300)

    # ---- 快速設置面板（B13）----
    def quick_set_select_numbers(self, numbers: list[int]) -> None:
        """在右側「快速設置」號碼格勾選指定號碼（依畫面上的數字文字定位）。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        for n in numbers:
            panel.get_by_text(str(n), exact=True).first.click()

    def quick_set_reset(self) -> None:
        self.page.get_by_role("button", name="重置").click()

    def quick_set_apply(self, value: str) -> None:
        """在「快速設置」面板下方輸入數值並按「套用」，套用到已勾選的號碼。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        panel.get_by_role("spinbutton").last.fill(value)
        panel.get_by_role("button", name="套用").click()
        self.page.wait_for_timeout(300)

    # ---- 保存區 ----
    def save(self) -> None:
        self.page.get_by_role("button", name="保存").click()

    # ---- 組合型分類（10 個，含比大小；B19）----
    #
    # ⚠️ 2026-08-28 只在「比大小」上實測驗證過，其餘 9 個組合型分類
    # （连码／过关／六肖／连肖／连尾／不中／多选中一／特平中／合肖）結構可能不完全相同
    # （见檔頭關於 `table=10` vs `table=0` 兩種子變體的說明），呼叫前先確認畫面結構一致。
    #
    # ⚠️ 「一比一」～「一比六」、「关连」／「不关连」都是 Element Plus 的
    # `el-radio-button`——底層 `<input type="radio">` 是視覺隱藏的，Playwright 對它
    # `get_attribute("aria-checked")` 恆回 `None`（不可靠），**讀狀態要用
    # `.evaluate("el => el.checked")`**；**點擊要用文字定位**（`get_by_text(...).click()`），
    # 直接點 `get_by_role("radio")` 會因為視覺隱藏而逾時失敗——跟 `el-switch` 的陷阱同一類，
    # 見 `system_setting_page.py` 檔頭對 `el-switch` 的說明。
    def select_sub_item(self, name: str) -> None:
        """切到子項（如「比大小」分類下的「一比一」～「一比六」）。"""
        self.page.get_by_text(name, exact=True).click()
        self.page.wait_for_timeout(500)

    def is_relation_linked(self) -> bool:
        """讀取目前子項「关连／不关连」是否為「关连」狀態。"""
        radio = self.page.get_by_role("radio", name="关连", exact=True)
        return radio.evaluate("el => el.checked")

    def set_relation_linked(self, linked: bool) -> None:
        """切換「关连／不关连」（只在目前值不同才點擊）。

        ⚠️ 這個切換**只影響前端當下狀態**，不送 API（跟 K4「開啟飛單選項明細設定」
        同一種模式）——切完不用擔心殘留，但仍要切回原樣（見 CLAUDE.md §5）。
        """
        if self.is_relation_linked() == linked:
            return
        self.page.get_by_text("关连" if linked else "不关连", exact=True).click()
        self.page.wait_for_timeout(500)

    def shared_cap_value(self) -> str:
        """讀取「共用自留上限」欄位目前值。"""
        return self.page.get_by_role("spinbutton", name="共用自留上限").input_value()

    def set_shared_cap(self, value: str) -> None:
        field = self.page.get_by_role("spinbutton", name="共用自留上限")
        field.fill(value)
        field.press("Tab")
        self.page.wait_for_timeout(300)

    def combo_auto_lay_off_enabled(self) -> bool:
        """讀取目前子項的「自動飛單」開關（組合型分類是子項層級單一開關，
        不是每個組合欄位各自一顆——跟標準選項清單型的 `option_auto_lay_off_enabled`
        是不同層級的方法，不要混用）。"""
        switch = self.page.get_by_role("switch", name="自动飞单")
        return switch.get_attribute("aria-checked") == "true"

    def combo_item_marked(self, index: int) -> bool:
        """讀取第 `index` 個組合列（正1特～正6特＋特码，0-based）的「選擇」checkbox 是否勾選。"""
        return self.page.get_by_role("checkbox").nth(index).evaluate("el => el.checked")

    def set_combo_item_marked(self, index: int, marked: bool) -> None:
        """勾選/取消第 `index` 個組合列的「選擇」checkbox。

        ⚠️⚠️ 2026-08-28 實測發現：**保存前必須至少勾選一個組合列**，否則點「保存」
        只會跳「請選擇號碼或選項」提示，**完全不會送出 API**——這是先前 roundtrip
        一直讀不到持久化結果的真因，不是保存流程本身失敗。
        用 `PUT /api/LayOffSettingDetail` 攔截確認的資料模型：`items` 陣列每項對應
        一個組合（`selection` "1"~"7"），`isMarked` 對應這裡的勾選狀態，
        `retentionCap` 對應「共用自留上限」的值（**但只套用到未勾選的項目**——
        已勾選／「選擇」的項目會保留其個別值不受「共用自留上限」影響，這跟畫面文字
        「此設定下共用自留上限將存為 0，該玩法所有組合無條件全飛」的語意一致：
        沒被特別勾選＝套用共用規則，勾選＝該項目獨立處理），`relationMode`
        對應「关连／不关连」（`"related"`／`"unrelated"`）。
        checkbox 同樣是 Element Plus 視覺隱藏 `<input>`，**要點父層元素**才點得到。
        """
        if self.combo_item_marked(index) == marked:
            return
        box = self.page.get_by_role("checkbox").nth(index)
        box.locator("xpath=..").click()
        self.page.wait_for_timeout(300)
