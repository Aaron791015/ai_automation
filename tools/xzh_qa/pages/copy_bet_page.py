# -*- coding: utf-8 -*-
"""公司層「跟單管理」Page Object（`/copy-bet`，複製投注機制）。

用途：H4 現況記錄（既有群組顯示）＋ F1 新增表單欄位結構（唯讀探索已完成，見下）。

⚠️ 2026-08-26 用 browser_snapshot／browser_evaluate 探索「新增」表單（只點開表單看欄位、
沒有送出保存，見 `tests/xzh/test_copy_bet.py` 的 `test_create_copy_bet_group`）：

1. **「新增」不是彈窗，是整頁導航** —— 點下去會離開 `/copy-bet` 導到 `/copy-bet/create`
   （獨立頁面，含自己的「返回」「保存」button），不是 `.el-dialog`。
2. 表單欄位：
   - `* 组别名称`：必填 textbox
   - `* 跟单比例(%)`：必填 spinbutton，預設 "100"
   - `彩种`：checkbox group（"全选" ＋ 14 個彩種各自 checkbox，含本專案範圍外的其餘彩種，
     見 `.claude/skills/xzh` §1 不變量 #4 —— 測試時只勾三個範圍內的彩種）
   - `跟单对象` group：按「新增對象」逐行新增一列，每列＝
     [對象類型 combobox（預設顯示"会员"，另一個選項未展開確認，可能是"代理"）]
     ＋ [`对象用户 ID` spinbutton —— ⚠️ 要求輸入**內部數字 user ID**，不是帳號名稱，
     UI 上的用戶管理列表沒有顯示這個 ID 欄位，目前沒有從 UI 查得到任意帳號 ID 的入口]
     ＋ [「移除」button]
   - `投注会员` group：按「新增投注會員」逐行新增一列，每列＝
     [`安全码` textbox（會員的資金密碼／安全碼，敏感憑證）]
     ＋ [`账号` textbox（會員帳號，文字，非 ID）]
     ＋ [`分配比例(%)` spinbutton]
     ＋ [「移除」button]；上方即時顯示「分配比例合计: X%」。
   - 底部：「返回」（取消，不保存）／「保存」button。
3. **F1 案例目前卡住的原因**：「跟單對象」需要內部數字 ID、「投注會員」需要會員安全碼——
   兩者都是目前沒有既有測試帳號資訊、也沒有從 UI 直接查得到的敏感/內部值。
   若要湊出可用資料，得先另外走通「建會員＋取得其安全碼」與「查得某帳號內部 ID」兩條路，
   這兩條本身都還沒探索過，不屬本次任務範圍。見 `test_create_copy_bet_group` 的 skip 理由。
4. **「刪除」的確認對話框結構未確認** —— 列表列的「操作」欄有「启用」「编辑」「删除」按鈕
   （既有群組 `M2E2E` 上看到的），但點擊「删除」的動作被本次 session 的權限分類器擋下
   （偵測為刪除類危險操作），未能觀察到確認對話框的實際文字／按鈕。**不要憑猜測寫
   `delete_group()`**——之後真的要做刪除流程時，請先用 MCP 對自己建立的測試資料點開確認一次。
5. 額外觀察（與本頁探索無直接關係，但寫入操作時要注意）：這個站台在多個頁面上都出現過
   **背景自動整頁導回 `/rule`（游戏规则）** 的行為，間隔約十幾秒到數十秒不等，
   會把未保存的表單內容清空。原因未明（可能是某種心跳/路由重置），操作要快、
   重要資料填完要盡快保存，不要停留太久才動作。

前置條件：已登入公司層。
"""
from __future__ import annotations

from playwright.sync_api import Page


class CopyBetPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        self.page.get_by_role("menuitem", name="跟单管理").click()
        self.page.wait_for_timeout(800)

    def group_row_text(self, group_name: str) -> str:
        """讀取指定跟單群組列的文字（`filter(has_text=...)`，理由見 system_setting_page.py 的說明）。"""
        row = self.page.get_by_role("row").filter(has_text=group_name).first
        row.wait_for(state="visible", timeout=15000)
        return row.inner_text()

    # ---- F1：新增表單（2026-08-26 已探索欄位結構，見檔頭說明）----
    def open_create_form(self) -> None:
        """點擊「新增」，導到 `/copy-bet/create` 整頁表單（不是彈窗）。"""
        self.page.get_by_role("button", name="新增").click()
        self.page.get_by_role("textbox", name="* 组别名称").wait_for(state="visible", timeout=15000)

    def fill_basic_fields(self, group_name: str, ratio: str, lottery_names: list[str]) -> None:
        """填「组别名称」「跟单比例(%)」，並勾選指定彩種（用彩種中文名稱，如「香港六合彩」）。

        ⚠️ 只勾 `lottery_names` 傳入的彩種——本專案範圍只測三彩種，表單上其餘彩種
        （見 `.claude/skills/xzh` §1 不變量 #4）不要一併勾選。
        """
        self.page.get_by_role("textbox", name="* 组别名称").fill(group_name)
        self.page.get_by_role("spinbutton", name="* 跟单比例(%)").fill(ratio)
        for name in lottery_names:
            self.page.get_by_role("checkbox", name=name).check()

    def add_target_object_row(self, user_id: str) -> None:
        """點「新增對象」加一列「跟單對象」，只填 `对象用户 ID`（對象類型維持預設「会员」）。

        ⚠️ `user_id` 必須是內部數字 ID，不是帳號名稱——目前沒有從 UI 查得到任意帳號 ID
        的入口，見檔頭說明第 3 點。呼叫前請先確認已經有辦法拿到這個 ID。
        """
        self.page.get_by_role("button", name="新增对象").click()
        rows = self.page.get_by_role("spinbutton", name="对象用户 ID")
        rows.last.fill(user_id)

    def add_betting_member_row(self, account: str, security_code: str, ratio: str) -> None:
        """點「新增投注會員」加一列「投注會員」，填帳號／安全碼／分配比例(%)。

        ⚠️ `security_code` 是會員的資金密碼／安全碼，屬敏感憑證——只能用自己建立、
        知道安全碼的測試會員，不可挪用他人既有帳號（CLAUDE.md §5 紀律 2）。
        """
        self.page.get_by_role("button", name="新增投注会员").click()
        self.page.get_by_role("textbox", name="安全码").last.fill(security_code)
        self.page.get_by_role("textbox", name="账号").last.fill(account)
        self.page.get_by_role("spinbutton", name="分配比例(%)").last.fill(ratio)

    def cancel_create(self) -> None:
        """點「返回」離開新增表單，不保存（唯讀探索、或建好一半要放棄時用）。"""
        self.page.get_by_role("button", name="返回").click()

    def save_create(self) -> None:
        self.page.get_by_role("button", name="保存").click()
