# -*- coding: utf-8 -*-
"""公司層「系統設置→飛單選項設置」Page Object（`/setting/lay-off-setting-detail`）。

⚠️ 2026-10-02 改名：選單與頁面原名「飛單選項明細設置」，現名「飛單選項設置」（網址不變）。
   Aaron 2026-10-02 確認是 RD 刻意改名，不是缺陷（交接檔 T89）。
⚠️ 同日另有三處變動，Aaron 2026-10-02 14:28 裁示「對 刻意改的。『保存后立即触发本次选项自动飞单』功能
   不要了」（交接檔 T90；人為的變更聲明，不是缺陷、不開單）：
   ①頁面總開關標籤原「启用飞单选项明细」→ 現「开关选项设置」；確認框標題原「启用飞单选项明细」→ 現
     「开启选项设置」，內文改為「是否开启选项设置功能？原系统设置－飞单设置中，飞单设置的金额将会失效，
     并且自动出货将变更为手动模式，请确认！」；鎖定提示原「编辑已锁定，启用飞单选项明细后才能编辑」→ 現
     「编辑已锁定，开启选项设置后才能编辑」（2026-10-02 QAT 實測，aaa222；前端 i18n 與之一致）；
   ②保存區勾選框「保存后立即触发本次选项自动飞单」**功能已移除**——`trigger_now_*` 已改為明確報錯，
     不要再呼叫；現行觸發方式見《遊戲機制》§5.4；
   ③飛單設置頁（K4）表頭「开启飞单选项明细设定」→ 現「开关选项设置」（K4 方法依欄位順序定位，不受影響）。

用途：B37～B50 案例（矩陣 K7；2026-08-31 飛單案例從零重新設計後編號已改，
對照舊編號見 `docs/新綜合/新綜合_案例清單.md` §0.1）。
前置條件：已登入公司層。

⚠️ 這頁跟同層級的「飛單設置」（`SystemSettingPage`，矩陣 K4）結構完全不同，
   不是「同一張大表格多幾欄」——是「玩法分類（25 個按鈕）→ 每分類自己一張
   1~49 選項表」，且多了一顆「开关选项设置」總開關（2026-10-02 前名為「啟用飛單選項明細」），另立一個類別。

⚠️⚠️ 2026-08-28 實測發現「比大小」分類的 UI **跟其餘 24 個分類完全不同**——
   不是「選項 1~N 逐列自動飛單」的標準表格，是先選 6 個子項按鈕之一（一比一～一比六，
   純文字＋`cursor=pointer`，不是語意 `button`／`table`，role 查詢會找不到任何東西），
   選定後顯示的是「組合占成金額」表格（正1特～正6特＋特码 共 7 個組合欄位），
   還多了「关连／不关连」切換與「共用自留上限」規則說明（「此設定下共用自留上限將存為 0，
   該玩法所有組合無條件全飛」）。**這與矩陣 K4「飛單設置」頁的 `一比五`／`一比六` 例外列
   分屬不同層級的概念**——K4 的「一比五/一比六」是玩法整體的一列，K7「比大小」底下的
   「一比五/一比六」則是玩法內的子項，不能直接假設兩者是同一件事的兩種呈現，
   需要規格文件或 RD 確認才能定義兩者關聯的 oracle（見案例 B14、交接檔 T17）。

⚠️⚠️ 2026-08-28 MCP 實測發現「开关选项设置」（2026-10-02 前名為「啟用飛單選項明細」）總開關是**關鍵的父子層級連動點**，
   直接回答了矩陣 K7／K4 是否連動的疑問（見交接檔 T17、案例清單 B14）：
   - **關閉**：不跳確認框，立即生效（送出 API，reload 後仍是關閉——即時持久化，
     不需要按頁面下方「保存」）。關閉後底下所有選項列的「自動飛單」switch 變成
     disabled（但保留原本 checked 值，不會被清空）、「每選項自留上限」從可編輯
     button 變回純文字、分類工具列「全部設置／一鍵自動／一鍵手動」全部變 disabled。
   - **開啟**：會跳一個 `el-message-box` 確認框（標題「开启选项设置」），文字明確寫著
     （2026-10-02 起的現況；舊文字為「是否启用飞单选项明细功能？原系统设定－飞单设定中，飞单设定的金额将会失效，
     并且自动出货将变更为手动模式，请确认！」，標題「启用飞单选项明细」）：
     「是否开启选项设置功能？**原系统设置－飞单设置中，飞单设置的金额将会失效，
     并且自动出货将变更为手动模式**，请确认！」
     ——這就是 A 級 oracle：系統自己承認 K7 總開關開啟時 **K4（飛單設置）的金額設定
     會失效、自動出貨改手動**，兩層不是各自獨立，是互斥切換的父子關係。
     `set_master_switch(True)` 必須點確認框的「確定」才會真的生效，光點開關本身
     只是跳出確認框，不會立刻改變狀態（已實測：點開關但不點確定，reload 後仍是關閉）。

⚠️⚠️ 2026-09-01 三彩種全玩法覆蓋（B43）實測發現**標準型玩法表格其實有兩種欄位配置**，
   先前所有文件都假設只有一種：`选项／实际占成金额／每选项自留上限／自动飞单`（4 欄）。
   `生肖中／生肖不中／半波／特肖／尾数中／尾数不中` 這 6 個玩法多一欄「對應號碼」
   （選項對照的實際號碼），變成 5 欄，「每選項自留上限」與「自動飛單」整體往後推一位。
   `option_cap_editable`／`option_cap_value`／`set_option_cap`／
   `option_auto_lay_off_enabled`／`option_auto_lay_off_toggleable`／
   `set_option_auto_lay_off` 已改為依表頭動態判斷（見 `_has_number_column()`／
   `_cap_cell_index()`），呼叫端不需要關心這個差異。**這是 B43 全量 15×3 實跑「總開關開啟後
   自留上限欄位一直未變成可編輯」失敗的真正根因**——不是渲染時序問題，是欄位索引原本就抓
   錯欄（抓到恆為唯讀文字的「實際占成金額」），先前以為的等待/重試workaround治標不治本。
"""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect


class LayOffDetailSettingPage:
    # 2026-10-02 RD 刻意改名（Aaron 當日 14:28 確認）；舊名「启用飞单选项明细」。
    MASTER_SWITCH_LABEL = "开关选项设置"
    # 開啟總開關時的確認框標題（el-message-box 的 dialog 名稱）；舊名「启用飞单选项明细」。
    MASTER_CONFIRM_TITLE = "开启选项设置"
    # 總開關關閉時的鎖定提示；舊文字「编辑已锁定，启用飞单选项明细后才能编辑」。
    LOCKED_NOTICE = "编辑已锁定，开启选项设置后才能编辑"
    # 組合型分類的「選擇」checkbox。⚠️ 2026-10-02 QAT 實測：組合型頁面工具列（`.edit-toggle-bar`，
    # 「开关选项设置」開關旁）新增一顆「全选」checkbox，且在 DOM 順序上排在所有組合列之前，
    # `get_by_role("checkbox")` 會把它算成第 0 個——組合列索引整體差 1、列數多算 1。
    # Aaron 2026-10-02 17:25 確認這是 RD 刻意改動（交接檔 T94，不開單）；本 POM 刻意**排除**工具列內的
    # checkbox（也排除 role=switch 的開關），因為組合列索引要與「列」一一對應。排除後各分類數量與舊文件相同
    # （连码 49、六肖 24、过关 28、连肖 12、连尾 10、合肖 12、比大小 7）。
    # 行為觀察（2026-10-02 唯讀，aaa222，宾果六合彩→连码→二中特，並以 route 阻擋所有寫入請求）：
    # 「全选」位於「开关选项设置」開關右側、預設未勾；勾選後該頁 49 列「選擇」checkbox 全部變為勾選，
    # 再點一次全部取消；全程沒有任何寫入請求，重新整理（未保存）後恢復為後端值（皆未勾）。
    # 目前沒有案例驗「全选」本身（POM 不提供點它的方法）。
    _COMBO_BOX_SELECTOR = "input[type=checkbox]:not([role=switch]):not(.edit-toggle-bar *)"

    def __init__(self, page: Page):
        self.page = page
        # 最近一次 `combo_share_detail()` 讀到的視窗表頭與分頁文字（供佐證附件用）。
        self.last_share_detail_meta: dict[str, object] = {}

    def goto(self) -> None:
        system_item = self.page.get_by_role("menuitem", name="系统设置", exact=True)
        if system_item.count() == 0 or not system_item.last.is_visible():
            # 2026-09-02 實測：1280px 寬度時，頂部靠右的「系统设置」會被 Element Plus
            # 收進最後一個「…」溢出子選單。直接等待 menuitem 會逾時，需先展開溢出選單。
            overflow = self.page.locator(".el-menu--horizontal > .el-sub-menu").last
            expect(overflow).to_be_visible()
            overflow.click()
            expect(system_item.last).to_be_visible()
        system_item.last.click()
        # 2026-10-02 起選單名稱為「飞单选项设置」（舊名「飞单选项明细设置」，網址不變）；
        # Aaron 2026-10-02 確認是 RD 刻意改名，非缺陷。
        self.page.get_by_role("menuitem", name="飞单选项设置", exact=True).click()
        self.page.wait_for_timeout(1200)

    def switch_game(self, game_name: str) -> None:
        """切換上方彩種卡片，機制同 `SystemSettingPage.switch_game`（B42 三彩種分類比對用）。"""
        self.page.get_by_text(game_name, exact=True).first.click()
        self.page.wait_for_timeout(1200)

    def category_labels(self) -> list[str]:
        """讀取左側／上方玩法分類按鈕的文字清單（結構掃描用，矩陣 K7／案例 B17）。"""
        return self.page.get_by_role("navigation").get_by_role("button").all_inner_texts()

    def select_category(self, name: str, *, wait_for_networkidle: bool = True) -> None:
        """切到指定玩法分類。

        ⚠️ 不能統一用「分類標題（`heading` level 3）出現」當等待條件——2026-08-28 實測
        發現「比大小」分類**沒有** `heading`（它是完全不同的組合型 UI，見本檔檔頭說明），
        用 `heading` 等待會直接超時。改用**固定等待＋`networkidle`**，犧牲一點精確度
        換取對所有分類（含結構特殊的「比大小」）都適用。
        """
        self.page.get_by_role("button", name=name, exact=True).click()
        if wait_for_networkidle:
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.page.wait_for_timeout(500)
        else:
            # 呼叫端會以實際欄位可操作狀態作後續等待時，不必每次都等待整頁 network-idle。
            self.page.wait_for_timeout(150)

    # ---- 總開關（B11）----
    def is_master_switch_enabled(self) -> bool:
        switch = self.page.get_by_text(self.MASTER_SWITCH_LABEL, exact=True).locator("..").get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def set_master_switch(self, enable: bool) -> None:
        """把「开关选项设置」總開關（2026-10-02 前名為「啟用飛單選項明細」）切到 `enable`。

        ⚠️ 開啟時會跳確認框（見檔頭說明），本方法已處理：偵測到 dialog 出現就點「確定」。
        關閉時不會跳確認框，直接生效。兩個方向都**立即送出 API、無需另外按保存**——
        呼叫端用完記得呼叫 `set_master_switch(<原值>)` 還原（見 CLAUDE.md §5）。

        ⚠️⚠️ 2026-08-31 探索發現一個**尚未查明根因、但已三次重現**的異常：呼叫本方法
        （開啟或關閉皆有可能）之後，回到 K4「飛單設置」頁複查，發現**K4 表格第一列
        「特码」**會被意外解鎖（`isSelectionDetailEnabled` 變 False），即使該次操作
        完全沒有碰過 K4 頁面、也沒有碰過「特码」這個玩法。三次都能用同一套鎖回程序
        （`set_lay_off_detail_mode("特码", True)` + `save()`）修復，資料本身沒有壞掉，
        但**每次呼叫本方法後都應該去複查 K4「特码」列的鎖定狀態**，不能假設只有自己
        碰過的列會受影響。懷疑是前端在總開關切換時重新整理 K4 本地端快取時的
        index／參照錯誤（「特码」恰好是陣列第 0 項），但未深入 debug 前端原始碼確認。
        見案例清單 B38、交接檔（K4「特码」意外解鎖）。
        """
        if self.is_master_switch_enabled() == enable:
            return
        self.page.get_by_text(self.MASTER_SWITCH_LABEL, exact=True).locator("..").locator(".el-switch").click()
        if enable:
            dialog = self.page.get_by_role("dialog", name=self.MASTER_CONFIRM_TITLE)
            dialog.get_by_role("button", name="确定").click()
        self.page.wait_for_timeout(800)

    def click_master_switch_and_cancel(self) -> None:
        """點擊總開關嘗試開啟，但在確認框按「取消」（B37 取消分支，交接檔 T26）。

        ⚠️ 前提：呼叫前總開關必須是**關閉**狀態——開關「關閉」動作本身不跳確認框，
        沒有取消可測；只有「關→開」這個方向才會跳確認框。呼叫端呼叫前應先用
        `is_master_switch_enabled()` 確認為 False，或先 `set_master_switch(False)`。
        點「取消」後預期總開關維持關閉，不應真的送出任何持久化（2026-08-31 已 MCP
        唯讀＋寫入實測確認：取消後 `is_master_switch_enabled()` 仍讀到 False）。
        """
        self.page.get_by_text(self.MASTER_SWITCH_LABEL, exact=True).locator("..").locator(".el-switch").click()
        dialog = self.page.get_by_role("dialog", name=self.MASTER_CONFIRM_TITLE)
        dialog.get_by_role("button", name="取消").click()
        self.page.wait_for_timeout(500)

    # ---- 分類工具列（B44，舊編號 B12）----
    def click_batch_auto(self) -> None:
        self.page.get_by_role("button", name="一键自动").click()
        self.page.wait_for_timeout(500)

    def click_batch_manual(self) -> None:
        self.page.get_by_role("button", name="一键手动").click()
        self.page.wait_for_timeout(500)

    def batch_tool_buttons_disabled(self) -> dict[str, bool]:
        """讀取目前分類工具列「全部設置／一鍵自動／一鍵手動」三顆按鈕是否為 disabled（B50-2）。

        ⚠️ 2026-08-31 探索發現一個混淆變因：「全部設置」旁邊有一個數值輸入框，
        **輸入框未填值時，「全部設置」本身恆為 disabled**，與總開關（K7 master switch）
        無關——即使總開關開啟、選項可正常編輯，「全部設置」也會因為輸入框空白而
        disabled。呼叫端若要驗證「總開關關閉造成的影響」，只能用「一鍵自動」／「一鍵手動」
        兩者當可靠樣本（總開關開啟時兩者皆可互動、關閉時兩者皆 disabled）；「全部設置」
        只適合用來記錄「關閉時同樣是 disabled」這個現況，不能反向拿它證明「開啟時不受影響」。
        """
        return {
            name: self.page.get_by_role("button", name=name, exact=True).is_disabled()
            for name in ("全部设置", "一键自动", "一键手动")
        }

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

    # ---- 全 25 分類畫面元素掃描（B68，2026-09-01）----
    def quick_set_panel_visible(self) -> bool:
        """讀取目前分類是否顯示「快速設置」面板。

        ⚠️⚠️ 2026-09-01 探索發現：**不是全部 25 分類共有的元素**——只有「特码／正码／
        正特码」這 3 個「號碼型（選項即 1~49 號碼）」分類才有這個面板（面板內容本身就是
        1~49 號碼格＋波色/單雙快速勾選），其餘 22 個分類（含同為標準選項清單型的「两面」
        「生肖中」等）完全沒有這個區塊（DOM 裡不存在，非只是不可見）。B40 先前只驗證過
        「特码」1 個分類，未在此之前發現這個範圍限制，見案例清單 B68。
        """
        return self.page.get_by_text("快速设置", exact=True).count() > 0

    def relation_radio_block_count(self) -> int:
        """讀取目前分類的「关连」radio 出現次數——多數組合型分類是 1 個，
        但「六肖」是唯一例外，會同時顯示「六肖中」「六肖不中」兩個子區塊，各自一組
        关连/共用自留上限，因此讀到 2（2026-09-01 探索發現，見案例清單 B68）。"""
        return self.page.get_by_role("radio", name="关连", exact=True).count()

    def shared_cap_field_count(self) -> int:
        """讀取目前分類的「共用自留上限」欄位出現次數，同上——「六肖」讀到 2，其餘讀到 1。"""
        return self.page.get_by_role("spinbutton", name="共用自留上限").count()

    # ---- 結構家族判定（B41，交接檔 T24）----
    def is_current_category_combo(self) -> bool:
        """讀取目前選定分類是否為「組合型」——組合型才有「共用自留上限」欄位，
        標準選項清單型沒有這個欄位（只有「每選項自留上限」）。

        ⚠️ 2026-08-31 用本方法逐一掃描 25 個分類才發現案例清單先前記錄的「14 個標準型」
        有誤（漏算「色波」），實際是 15 個標準型＋10 個組合型＝25，見 B41、交接檔 T24。
        """
        return self.page.get_by_text("共用自留上限", exact=True).count() > 0

    def wait_until_category_unlocked(self, timeout_ms: int = 45000) -> None:
        """等待「目前分類」的欄位鎖定狀態跟上總開關的實際值（B47/B49/B64 根因修復，2026-09-01）。

        ⚠️⚠️ 2026-09-01 發現：`select_category()` 切分類本身是一次非同步重新載入，
        總開關的畫面 `aria-checked` 有時會**先**顯示成「已開啟」，但該分類自己的欄位
        鎖定狀態還沒跟上——舊版 `_ensure_category_switch_enabled()` 只在「原本是關、
        剛點下去開」這條分支才等 1500ms，「切過去發現已經是開的」完全不等，導致誤判成
        「連碼等組合型分類即使總開關已開啟、欄位仍鎖死長達 30 秒以上」（曾誤記為總開關
        規則不一致，見 B47/B49/B64、交接檔 §7）。MCP 現場覆核「连码」證實：只要給欄位
        足夠時間追上，鎖定機制其實跟「比大小」一致，都是單純的總開關控制。

        改用**輪詢真正的解鎖信號**取代固定等待，兩種結構家族分開判斷：
        - 組合型：「共用自留上限」欄位（第一個區塊）的 `aria-disabled` 變成 `"false"`。
        - 標準型：第 1 列「每選項自留上限」欄位從唯讀文字變成可編輯 `button`
          （沿用 `option_cap_editable()` 同一套判準，見 B43 根因說明）。
        呼叫端不需要自己判斷分類是哪種結構家族，本方法內部已處理。
        """
        if self.is_current_category_combo():
            field = self.page.get_by_role("spinbutton", name="共用自留上限").first
            expect(field).to_have_attribute("aria-disabled", "false", timeout=timeout_ms)
        else:
            cell = self.option_row(1).get_by_role("cell").nth(self._cap_cell_index())
            expect(cell.get_by_role("button")).to_have_count(1, timeout=timeout_ms)

    # ---- 已移除功能：保存區「保存后立即触发本次选项自动飞单」勾選框 ----
    #
    # ⛔ Aaron 2026-10-02 14:28 裁示（交接檔 T90）：「『保存后立即触发本次选项自动飞单』功能 不要了」。
    # 2026-10-02 QAT 實測（aaa222）頁面上已無此勾選框；前端 `PUT /api/LayOffSettingDetail` 的 payload
    # 現在只有 `gameId`／`playTypeId`／`items`，不再帶 `triggerImmediateAutoLayOff`。
    # 以下方法保留名稱只為了讓漏改的呼叫端**明確報錯**，不要再呼叫。
    _TRIGGER_NOW_LABEL = "保存后立即触发本次选项自动飞单"
    _TRIGGER_NOW_REMOVED = (
        "『保存后立即触发本次选项自动飞单』勾選框功能已移除（Aaron 2026-10-02 14:28 確認，交接檔 T90）；"
        "現行觸發方式見《新綜合_遊戲機制》§5.4"
    )

    def trigger_now_visible(self) -> bool:
        """保存區是否還看得到已移除的勾選框；現況預期為 False（可當「功能已移除」的反向確認）。"""
        return self.page.locator(
            ".el-checkbox", has_text=self._TRIGGER_NOW_LABEL
        ).last.is_visible()

    def trigger_now_checkbox(self):
        raise NotImplementedError(self._TRIGGER_NOW_REMOVED)

    def trigger_now_enabled(self) -> bool:
        raise NotImplementedError(self._TRIGGER_NOW_REMOVED)

    def set_trigger_now(self, enable: bool) -> None:
        raise NotImplementedError(self._TRIGGER_NOW_REMOVED)

    # ---- 現行觸發方式（2026-10-02 QAT 實測，aaa222；證據 scratchpad/t90-20261002/probe_c.json）----
    # ①保存本身就會執行自動飛單：前端 `PUT /api/LayOffSettingDetail` 只送 gameId／playTypeId／items，
    #   後端回 `{"executedCount": N}`；代理層（非公司層）畫面提示「更新成功，本次已飞出 N 笔自动飞单」
    #   或「更新成功，本次无自动飞单飞出」。
    # ②選項的「自動飛單」開著時，新注單進來也會自動處理（實測：下注後約 4 秒占成由 10 降到自留上限 1，
    #   期間沒有任何保存）。
    # ⚠️ `set_option_cap()` 按 Enter 會立刻送出 PUT（只帶已變更的列），所以設定順序會影響何時觸發：
    #   先開自動飛單再填上限，上限那次 Enter 就會觸發。
    _AUTO_LAY_OFF_NOTICE_RE = re.compile(r"更新成功，本次(?:已飞出\s*(\d+)\s*笔自动飞单|无自动飞单飞出)")

    def save_and_read_notice(self, wait_ms: int = 3000) -> str:
        """按「保存」並讀取畫面提示全文；公司層沒有這兩句提示，讀不到回空字串。"""
        self.save()
        waited = 0
        while waited < wait_ms:
            self.page.wait_for_timeout(250)
            waited += 250
            texts = self.page.evaluate(
                "() => [...document.querySelectorAll('.el-notification, .el-message, [role=alert]')]"
                ".map(e => (e.innerText || '').trim()).filter(Boolean)"
            )
            hits = [t for t in texts if "更新成功" in t]
            if hits:
                return " ".join(dict.fromkeys(hits))
        return ""

    @classmethod
    def executed_count_from_notice(cls, notice: str) -> int | None:
        """從 `save_and_read_notice()` 的文字取出「本次已飛出 N 筆」的 N；無自動飛單飛出回 0；讀不懂回 None。"""
        match = cls._AUTO_LAY_OFF_NOTICE_RE.search(notice or "")
        if not match:
            return None
        return int(match.group(1)) if match.group(1) else 0

    def _combo_boxes(self):
        """組合列的「選擇」checkbox（不含工具列的「全选」與所有開關），索引 0 起算。"""
        return self.page.locator(self._COMBO_BOX_SELECTOR)

    def combo_item_count(self) -> int:
        """讀取目前選定（組合型）分類的組合列數，用「選擇」checkbox 的數量計算。

        ⚠️ 不同組合型分類的 checkbox 數量差異很大（8～50 不等，依玩法組合數而定；
        `table=10` 四個成員固定 50，`table=0` 六個成員依玩法 8～29，見 B68），
        本方法只讀數量，不判斷是 `table=0` 或 `table=10` 哪一種子變體——子變體的行為
        差異見 B47（`table=0`）／B48（`table=10`）。

        ⚠️⚠️ 2026-09-02 修正 off-by-one：頁面下方保存區的「保存后立即触发本次选项
        自动飞单」（2026-10-02 起該勾選框已移除，下面的扣除量現為 0，邏輯保留無害）
        也是一顆 `checkbox`，且它跟分類內容共用同一個 `get_by_role("checkbox")`
        查詢空間——原本直接回傳 `count()` 會把它也算進組合列數（六肖量到 25，實際只有
        24；连码量到 50，實際只有 49），2026-09-02 六肖探索時發現。這裡明確扣掉這顆，
        改用「排除保存區勾選框」的方式計數，不能只靠「永遠是最後一個」的假設硬減 1。
        """
        # 2026-10-02：保存區勾選框已移除、工具列新增「全选」checkbox；改用 `_combo_boxes()`
        # 直接數組合列，不再靠「總數減去特定幾顆」。
        return self._combo_boxes().count()

    def option_row(self, option_number: int):
        """依 DOM 順序取第 `option_number` 個選項列（1-based，表頭不算）。"""
        return self._table().get_by_role("row").nth(option_number)

    def _has_number_column(self) -> bool:
        """判讀目前分類的表格是否多一欄「對應號碼」。

        ⚠️⚠️ 2026-09-01 三彩種全玩法覆蓋實測發現（B43 全量實跑失敗的真正根因）：
        `生肖中／生肖不中／半波／特肖／尾数中／尾数不中` 這 6 個玩法的表格比其餘標準型
        多一欄「對應號碼」（選項對照的實際號碼），欄位順序整體往後推一位——
        `选项／[对应号码]／实际占成金额／每选项自留上限／自动飞单`。原本 `option_cap_editable`
        等方法寫死 `nth(2)`／`nth(3)`，只對**沒有**這欄的表格（4 欄）成立；套用到這 6 個
        玩法會抓到「實際占成金額」欄（恆為唯讀文字），因而誤判成「總開關開啟後自留上限欄位
        一直未變成可編輯」——**不是渲染時序問題，是欄位索引本身就抓錯欄**。MCP 現場逐一核對
        `生肖中`／`半波`（5 欄，有「對應號碼」）與`特码`／`色波`（4 欄，無此欄）後確認。
        """
        headers = self._table().locator("thead").get_by_role("columnheader").all_inner_texts()
        return "对应号码" in headers

    def _cap_cell_index(self) -> int:
        """「每選項自留上限」欄位在 `get_by_role("cell")` 裡的索引，依表格是否有「對應號碼」欄動態判斷。"""
        return 3 if self._has_number_column() else 2

    def option_auto_lay_off_enabled(self, option_number: int) -> bool:
        switch = self.option_row(option_number).get_by_role("cell").nth(self._cap_cell_index() + 1).get_by_role("switch")
        return switch.get_attribute("aria-checked") == "true"

    def option_auto_lay_off_toggleable(self, option_number: int) -> bool:
        switch = self.option_row(option_number).get_by_role("cell").nth(self._cap_cell_index() + 1).get_by_role("switch")
        return switch.get_attribute("aria-disabled") != "true"

    def set_option_auto_lay_off(self, option_number: int, enable: bool) -> None:
        """把單一選項列的「自動飛單」開關切到 `enable`（只在目前值不同才點擊）。

        用於批次工具（`click_batch_auto`／`click_batch_manual`）測完後逐一還原個別選項，
        比重新整理頁面猜測原值更明確——呼叫前搭配 `option_auto_lay_off_enabled()`
        記錄原值。
        """
        cell = self.option_row(option_number).get_by_role("cell").nth(self._cap_cell_index() + 1)
        current = cell.get_by_role("switch").get_attribute("aria-checked") == "true"
        if current != enable:
            cell.locator(".el-switch").click()

    def option_cap_editable(self, option_number: int) -> bool:
        """讀取「每選項自留上限」欄位目前是否為可編輯 button。

        ⚠️⚠️ 2026-08-31 探索發現（B43，先前沒有任何文件記載，卻是能不能編輯這欄的關鍵前提）：
        這欄只有在頁面總開關「开关选项设置」（舊名「啟用飛單選項明細」）**開啟**時才會是可編輯 button；總開關關閉時
        呈唯讀 `is-static`（`option_cap_editable()` 回 False）。呼叫 `set_option_cap()` 前
        若總開關是關的，要先 `set_master_switch(True)`，測完記得關回原狀（見 B43 案例）。

        ⚠️⚠️ 2026-09-01 補：欄位索引依 `_cap_cell_index()` 動態判斷（見該方法檔頭）——
        `生肖中`等 6 個玩法有「對應號碼」欄，索引跟其餘玩法不同。
        """
        cell = self.option_row(option_number).get_by_role("cell").nth(self._cap_cell_index())
        return cell.get_by_role("button").count() > 0

    def option_cap_value(self, option_number: int) -> str:
        return self.option_row(option_number).get_by_role("cell").nth(self._cap_cell_index()).inner_text()

    def option_share_amount(self, option_number: int) -> int:
        """讀取標準型選項列的「實際占成金額」。"""
        cells = self.option_row(option_number).get_by_role("cell")
        share_cell_index = self._cap_cell_index() - 1
        raw = cells.nth(share_cell_index).inner_text().strip().replace(",", "")
        return int(float(raw or "0"))

    def open_option_cap_editor(self, option_number: int):
        """開啟指定列的「每選項自留上限」編輯器並回傳 number input。"""
        cell = self.option_row(option_number).get_by_role("cell").nth(self._cap_cell_index())
        cell.get_by_role("button").click()
        return cell.get_by_role("spinbutton")

    def set_option_cap(self, option_number: int, value: str) -> None:
        """把第 `option_number` 個選項（1-based，不含表頭，見 `option_row()`）的自留上限改成
        `value`。⚠️ 前提見 `option_cap_editable()`——總開關必須先開啟這欄才可編輯。
        """
        field = self.open_option_cap_editor(option_number)
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

    def quick_set_fill_apply_value(self, value: str) -> None:
        """只填「快速設置」套用數值輸入框，不點擊「套用」（供檢查按鈕 disabled 狀態用）。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        panel.get_by_role("spinbutton").last.fill(value)

    def quick_set_apply_disabled(self) -> bool:
        """讀取「快速設置」面板「套用」按鈕目前是否為不可點擊。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        return panel.get_by_role("button", name="套用").is_disabled()

    def quick_set_click_apply(self) -> None:
        """點擊「快速設置」面板的「套用」，供案例將輸入與送出拆成兩個可讀步驟。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        panel.get_by_role("button", name="套用").click()
        self.page.wait_for_timeout(300)

    def quick_set_apply(self, value: str) -> None:
        """在「快速設置」面板下方輸入數值並按「套用」，套用到已勾選的號碼。"""
        self.quick_set_fill_apply_value(value)
        self.quick_set_click_apply()

    def quick_set_invert(self) -> None:
        """點擊「快速設置」面板的「反選」按鈕。"""
        self.page.get_by_role("button", name="反选").click()

    def quick_set_select_by_property(self, name: str) -> None:
        """在「快速設置」面板勾選屬性 checkbox（如「红波」「大」「合单」「尾大」等）。
        2026-09-02 唯讀/write_action 探索已確認：屬性名稱對應的號碼與畫面上號碼球
        自身的顏色分類（`red`/`green`/`blue` class）或大小/單雙定義完全一致，見 B69。

        ⚠️ `force=True` + 短 timeout：總開關關閉時這顆 checkbox 會被鎖定（disabled），
        Playwright 預設點擊會等待元素變成「可操作」而卡住到 30 秒逾時（B75 曾因此整條
        案例卡死）。鎖定情境下即使強制送出點擊事件，Element UI 的 disabled checkbox
        也不會真的觸發勾選（Vue 層擋下 change 事件），所以用 `force=True` 不會讓
        「應該鎖住」的案例失真，只是避免 Playwright 白等 30 秒。
        """
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        panel.get_by_text(name, exact=True).click(force=True, timeout=5000)

    def ball_color_map(self) -> dict[int, str]:
        """讀取「快速設置」號碼球本身的顏色分類（class 標記為 red/green/blue），
        作為驗證「紅波/藍波/綠波」勾選正確性的自身一致性基準（不依賴外部文件的號碼清單，
        因為目前查無明確記載色波對應號碼的權威文件，見 B69）。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        pairs = panel.evaluate(
            """(panel) => {
                const nums = Array.from(panel.querySelectorAll('*'))
                    .filter(el => el.children.length === 0 && /^\\d{1,2}$/.test(el.textContent.trim()));
                return nums.map(el => {
                    const cls = el.parentElement.className;
                    const color = cls.includes('red') ? 'red' : cls.includes('green') ? 'green' : cls.includes('blue') ? 'blue' : null;
                    return [parseInt(el.textContent.trim(), 10), color];
                });
            }"""
        )
        return {n: c for n, c in pairs}

    def quick_set_selected_numbers(self) -> list[int]:
        """讀取「快速設置」號碼格目前被標記為已選（`is-selected`）的號碼，供斷言比對。"""
        panel = self.page.get_by_text("快速设置", exact=True).locator("..")
        return panel.evaluate(
            """(panel) => {
                const nums = Array.from(panel.querySelectorAll('*'))
                    .filter(el => el.children.length === 0 && /^\\d{1,2}$/.test(el.textContent.trim()));
                return nums
                    .filter(el => el.parentElement.className.includes('is-selected'))
                    .map(el => parseInt(el.textContent.trim(), 10))
                    .sort((a, b) => a - b);
            }"""
        )

    def set_all_options(self, value: str) -> None:
        """在分類標題列的「全部設置」輸入框填值並點擊，套用到目前分類全部選項（未保存）。"""
        container = self.page.get_by_role("button", name="全部设置").locator("..")
        container.get_by_role("spinbutton").fill(value)
        container.get_by_role("button", name="全部设置").click()
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
    def select_sub_item(self, name: str, *, settle_ms: int = 500) -> None:
        """切到子項（如「比大小」分類下的「一比一」～「一比六」）。

        ⚠️⚠️ 2026-09-02 比大小全 6 子項覆蓋實測發現：選定子項後，下方
        `el-card__header`（組合表格標題）也會重複顯示同一個文字（例如選「一比一」後，
        表格標題也寫「一比一」），`get_by_text(name, exact=True)` 因此會撞 Playwright
        strict mode（resolved to 2 elements：子項選單本身 ＋ 表格標題）。改用 class
        限定在頂部的子項選單元素（`el-segmented__item-label`），不比對整頁文字。
        """
        self.page.locator(".el-segmented__item-label", has_text=name).click()
        self.page.wait_for_timeout(settle_ms)

    def is_relation_linked(self, block_index: int = 0) -> bool:
        """讀取目前子項「关连／不关连」是否為「关连」狀態。

        ⚠️⚠️ 2026-09-01 三彩種全玩法覆蓋實測發現：「六肖」是組合型分類裡**唯一**同時顯示
        兩個子區塊（「六肖中」「六肖不中」）的分類，各自一組「关连」radio／「共用自留上限」
        欄位，accessible name 相同——不加索引直接 `get_by_role(..., name="关连")` 會撞
        Playwright strict mode（resolved to 2 elements）。`block_index` 預設 0，其餘 9 個
        分類只有 1 個區塊，`nth(0)` 等同原行為；「六肖」呼叫端需分別用 0／1 各驗一次。
        """
        radio = self.page.get_by_role("radio", name="关连", exact=True).nth(block_index)
        return radio.evaluate("el => el.checked")

    def set_relation_linked(self, linked: bool, block_index: int = 0) -> None:
        """切換「关连／不关连」（只在目前值不同才點擊）。

        ⚠️ 這個切換**只影響前端當下狀態**，不送 API（跟 K4「開啟飛單選項明細設定」
        同一種模式）——切完不用擔心殘留，但仍要切回原樣（見 CLAUDE.md §5）。
        `block_index` 用途見 `is_relation_linked()` 檔頭（「六肖」雙區塊）。
        """
        if self.is_relation_linked(block_index) == linked:
            return
        self.page.get_by_text("关连" if linked else "不关连", exact=True).nth(block_index).click()
        self.page.wait_for_timeout(500)

    def shared_cap_value(self, block_index: int = 0) -> str:
        """讀取「共用自留上限」欄位目前值。`block_index` 用途見 `is_relation_linked()` 檔頭。"""
        return self.page.get_by_role("spinbutton", name="共用自留上限").nth(block_index).input_value()

    def set_shared_cap(self, value: str, block_index: int = 0) -> None:
        field = self.page.get_by_role("spinbutton", name="共用自留上限").nth(block_index)
        field.fill(value)
        field.press("Tab")
        self.page.wait_for_timeout(300)

    def combo_auto_lay_off_enabled(self, block_index: int = 0) -> bool:
        """讀取目前子項的「自動飛單」開關（組合型分類是子項層級單一開關，
        不是每個組合欄位各自一顆——跟標準選項清單型的 `option_auto_lay_off_enabled`
        是不同層級的方法，不要混用）。`block_index` 用途見 `is_relation_linked()` 檔頭
        （「六肖」有兩個區塊、各自一顆「自動飛單」，2026-09-02 補上索引避免撞
        Playwright strict mode）。"""
        switch = self.page.get_by_role("switch", name="自动飞单").nth(block_index)
        return switch.get_attribute("aria-checked") == "true"

    def set_combo_auto_lay_off(self, enable: bool, block_index: int = 0) -> None:
        """切換組合型分類的單一「自動飛單」開關。"""
        if self.combo_auto_lay_off_enabled(block_index) == enable:
            return
        self.page.get_by_role("switch", name="自动飞单").nth(block_index).locator("xpath=ancestor::*[contains(@class, 'el-switch')][1]").click()
        self.page.wait_for_timeout(300)

    def combo_share_amount(self, index: int) -> int:
        """讀取組合型第 ``index`` 列的「組合占成金額」。

        K7 有三種實際排版：``number-row``（不中／多選中一／特平中）、
        ``option-row``（六肖／連肖／連尾／合肖）及 ``group-row`` 內的單一
        ``cell``（過關／部分比較玩法）。三者都以同一顆 ``share-amount-cell``
        呈現金額，先從選擇 checkbox 找最近的承載列即可避免依頁面全域索引誤抓。
        """
        row = self._combo_amount_row(index)
        raw = row.locator("button.share-amount-cell").first.inner_text().strip().replace(",", "")
        return int(float(raw or "0"))

    def _combo_amount_row(self, index: int):
        checkbox = self._combo_boxes().nth(index)
        # ⚠️ 2026-10-02：選擇 checkbox 外層 span 的 class 現為 `cell-checkbox`（舊寫法 `contains(@class,'cell')`
        # 會先命中它，找不到金額按鈕）。改成以 class 完整字詞比對：`number-row`／`option-row`／`cell`。
        row = checkbox.locator(
            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' number-row ') or "
            "contains(concat(' ', normalize-space(@class), ' '), ' option-row ') or "
            "contains(concat(' ', normalize-space(@class), ' '), ' cell ')][1]"
        )
        expect(row).to_have_count(1)
        expect(row.locator("button.share-amount-cell").first).to_have_count(1)
        return row

    # 占成明细視窗現行欄位（2026-10-02，Aaron 當日 17:25 確認是 RD 刻意改動，交接檔 T94）。
    # 舊樣貌為「投注选项／占成金额／补货」；現為「序号／投注选项／占成金额／可飞额」，另有分頁「共 N 条」。
    SHARE_DETAIL_HEADERS = ("序号", "投注选项", "占成金额", "可飞额")

    def combo_share_detail(self, index: int) -> list[dict[str, object]]:
        """開啟組合占成金額明細，讀取每筆序號／投注選項／占成金額／可飛額（目前所在這一頁）後關閉。

        這個視窗是 B85 的核心行為證據；欄位名稱與資料皆從實際 dialog/table 語意定位，
        不以整頁第 N 個 table 或猜測 CSS 結構取值。

        ⚠️ 2026-10-02 起視窗欄位為「序号／投注选项／占成金额／可飞额」（舊為「投注选项／占成金额／补货」；
        Aaron 當日 17:25 確認是 RD 刻意改動，交接檔 T94）。四個欄位都必須存在，缺任一個即丟 AssertionError。
        回傳的每筆含 `seq`（序號）、`bet_option`（以「,」分隔的組合）、`share_amount`（占成金額）、
        `layoffable`（可飛額）。「可飞额」的計算規則沒有規格，呼叫端只附在佐證裡、不斷言。
        另把視窗表頭與分頁文字留在 `self.last_share_detail_meta`（供佐證附件用）。
        """
        row = self._combo_amount_row(index)
        row.locator("button.share-amount-cell").first.click()
        dialog = self.page.get_by_role("dialog").last
        expect(dialog).to_be_visible()
        details: list[dict[str, object]] = []
        try:
            headers = [text.strip() for text in dialog.get_by_role("columnheader").all_inner_texts()]
            dialog_text = dialog.inner_text()
            pager = re.search(r"共\s*\d+\s*条", dialog_text)
            self.last_share_detail_meta = {
                "headers": headers,
                "pager_text": pager.group(0) if pager else None,
            }
            missing = [header for header in self.SHARE_DETAIL_HEADERS if header not in headers]
            if missing:
                raise AssertionError(
                    f"占成明细缺少欄位{missing}；實際欄位={headers}；視窗文字={dialog_text!r}"
                )
            column_indices = {header: headers.index(header) for header in headers}

            def _amount(cells, header):
                return int(float(cells[column_indices[header]].replace(",", "") or "0"))

            for detail_row in dialog.get_by_role("row").all()[1:]:
                cells = [text.strip() for text in detail_row.get_by_role("cell").all_inner_texts()]
                if not cells:
                    continue
                details.append({
                    "seq": _amount(cells, "序号"),
                    "bet_option": cells[column_indices["投注选项"]].replace("、", ","),
                    "share_amount": _amount(cells, "占成金额"),
                    "layoffable": _amount(cells, "可飞额"),
                })
        finally:
            # 即使欄位檢查失敗也要關掉視窗，否則殘留的遮罩會擋住呼叫端 finally 裡的還原導覽。
            close = dialog.get_by_role("button", name="关闭", exact=True)
            if close.count():
                close.click()
            else:
                dialog.locator(".el-dialog__headerbtn").click()
            expect(dialog).to_be_hidden()
        return details

    def combo_item_marked(self, index: int) -> bool:
        """讀取第 `index` 個組合列（正1特～正6特＋特码，0-based）的「選擇」checkbox 是否勾選。"""
        return self._combo_boxes().nth(index).evaluate("el => el.checked")

    def combo_marked_indices(self) -> list[int]:
        """一次讀取目前組合型玩法所有已勾選列，避免逐列跨瀏覽器查詢。"""
        count = self.combo_item_count()
        return self._combo_boxes().evaluate_all(
            "(boxes, count) => boxes.slice(0, count).flatMap((box, index) => box.checked ? [index] : [])",
            count,
        )

    def combo_ui_state(self, block_index: int = 0) -> dict[str, object]:
        """從目前畫面讀取組合型設定狀態，供保存後重新整理的 UI 顯示核對使用。

        這裡刻意只讀畫面，不呼叫 API：T43／B84 要驗的是後端資料已保存後，前端重新整理
        是否仍正確呈現「关连／不关连」、「共用自留上限」與所有「選擇」勾選狀態。
        """
        return {
            "relation_linked": self.is_relation_linked(block_index),
            "shared_cap": self.shared_cap_value(block_index),
            "marked_indices": self.combo_marked_indices(),
        }

    def set_combo_marked_indices(self, marked_indices: list[int]) -> None:
        """批次把組合列調整成指定勾選集合（只點擊狀態不同的視覺 checkbox）。

        B46 需要在 3 彩種 × 55 個目標反覆清空及還原；逐列使用 Playwright `click()`
        會產生數千次跨程序往返。這裡仍觸發每顆 Element Plus checkbox 的真實 click
        handler，只把同頁的點擊集中在一次瀏覽器端執行，完成後再讀回確認狀態。
        """
        count = self.combo_item_count()
        expected = sorted(set(marked_indices))
        invalid = [index for index in expected if index < 0 or index >= count]
        if invalid:
            raise IndexError(f"組合列索引超出範圍（共{count}列）：{invalid}")
        self._combo_boxes().evaluate_all(
            """(boxes, args) => {
                const [count, expected] = args;
                const selected = new Set(expected);
                boxes.slice(0, count).forEach((box, index) => {
                    if (box.checked !== selected.has(index)) box.parentElement.click();
                });
            }""",
            [count, expected],
        )
        self.page.wait_for_timeout(300)
        actual = self.combo_marked_indices()
        if actual != expected:
            raise AssertionError(f"組合勾選批次調整失敗：預期{expected}，實際{actual}")

    def set_combo_item_marked(self, index: int, marked: bool) -> None:
        """勾選/取消第 `index` 個組合列的「選擇」checkbox。

        ⚠️⚠️ 2026-08-28 實測發現：**保存前必須至少勾選一個組合列**，否則點「保存」
        只會跳「請選擇號碼或選項」提示，**完全不會送出 API**——這是先前 roundtrip
        一直讀不到持久化結果的真因，不是保存流程本身失敗。
        用 `PUT /api/LayOffSettingDetail` 攔截確認的資料模型：`items` 陣列每項對應
        一個組合（`selection` "1"~"7"），`isMarked` 對應這裡的勾選狀態，
        `retentionCap` 對應「共用自留上限」的值，`relationMode` 對應「关连／不关连」
        （`"related"`／`"unrelated"`）。
        checkbox 同樣是 Element Plus 視覺隱藏 `<input>`，**要點父層元素**才點得到。

        ⚠️⚠️ 2026-08-31 更正（B49，方向與本檔頭原本寫的相反，以此為準）：
        「共用自留上限」的值會套用到**目前所有已勾選**的組合，**未勾選的組合一律強制
        `retentionCap=0`**——不是「只套用到未勾選」。畫面文字「此設定下共用自留上限將存為
        0，該玩法所有組合無條件全飛」因此只對**未勾選**的組合成立；已勾選的組合可以有
        非 0 值，不受「全飛」限制（這正是「選擇」checkbox 存在的意義：讓操作者能個別
        處理特定組合的例外值）。

        ⚠️ 呼叫端陷阱：**呼叫序列若讓「目前已勾選數」中途變成 0（例如迴圈把全部組合都
        取消勾選、下一步才勾選新的目標項），保存會卡住送不出 PUT**（`expect_request`
        逾時，非提示訊息擋下——訊息只在「保存當下」零勾選才會跳，中途瞬間歸零不會跳訊息，
        但後續保存仍可能失敗）。安全作法：**全程至少保留一個組合勾選**，改動其餘項目時
        用「先勾新目標、再取消其餘」而非「先全部取消、再勾新目標」的順序。
        """
        if self.combo_item_marked(index) == marked:
            return
        box = self._combo_boxes().nth(index)
        box.locator("xpath=..").click()
        self.page.wait_for_timeout(300)
