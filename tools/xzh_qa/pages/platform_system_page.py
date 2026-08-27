# -*- coding: utf-8 -*-
"""平台層「系統管理」「租戶管理」Page Object。

用途：A5（全局設置圖片網域）、B7（company1 彩種啟用範圍快照）。
前置條件：已登入平台層（`http://platform.snotra.qat`，含 2FA）。
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

#: 平台層目前實際啟用的 14 個彩種（見 `.claude/skills/xzh/SKILL.md` §1 不變量 #4）。
ALL_14_GAMES = [
    "香港六合彩", "英国天天彩", "宾果六合彩", "英国赛车", "英国极速赛车", "英国飞艇",
    "宾果赛车(前)", "宾果赛车(后)", "英国时时彩", "英国极速时时彩",
    "宾果时时彩(A)", "宾果时时彩(B)", "宾果时时彩(C)", "宾果时时彩(D)",
]
#: 「新綜合」本專案範圍鎖定的三個彩種（2026-08-26 使用者裁定）。
XZH_SCOPE_GAMES = ["香港六合彩", "英国天天彩", "宾果六合彩"]


class PlatformSystemPage:
    def __init__(self, page: Page):
        self.page = page

    # ---- 系統管理 → 全局設置（A5）----
    def goto_global_setting(self) -> None:
        self.page.get_by_role("menuitem", name="系统管理").click()
        self.page.get_by_role("menuitem", name="全局设置").click()
        self.page.wait_for_timeout(1200)

    def image_domain(self) -> str:
        """讀「圖片網域」目前值。

        ⚠️ 2026-08-26 實測發現：`page.reload()` 後這個欄位會先短暫顯示空字串，
        要等非同步資料回填才會出現真值（若讀太快會誤判成「保存沒生效」）——
        不是 K1 那種「切彩種才觸發繫結」的死結，這裡純粹是繪製時序，稍等即可，
        故用 `expect(...).not_to_have_value("")` 等待，而非直接 `input_value()`。
        """
        field = self.page.get_by_role("textbox", name="图片网域")
        try:
            expect(field).not_to_have_value("", timeout=8000)
        except AssertionError:
            pass
        return field.input_value()

    def set_image_domain(self, value: str) -> None:
        self.page.get_by_role("textbox", name="图片网域").fill(value)

    def save(self) -> None:
        self.page.get_by_role("button", name="保存").click()

    # ---- 租戶管理 → 指定公司的『游戏』設定頁（B7，唯讀）----
    def goto_games(self, company_row_name: str) -> None:
        self.page.get_by_role("menuitem", name="租户管理").click()
        row = self.page.get_by_role("row").filter(has_text=company_row_name).first
        row.get_by_role("button", name="游戏").click()
        self.page.wait_for_timeout(1200)

    def is_game_enabled(self, game_name: str) -> bool:
        """讀取指定彩種目前是否為「启用」狀態（唯讀，不點擊任何 radio）。

        ⚠️ 彩種名稱在這頁會出現兩次（上方跑馬燈卡片 + 下方設定列表），
        用 `get_by_role("main")` 限定範圍在設定列表區塊，避免撞到跑馬燈那個。
        `wait_for` 是為了避開換頁後 radiogroup 還沒渲染完成的瞬間。
        """
        main = self.page.get_by_role("main")
        container = main.get_by_text(game_name, exact=True).locator("xpath=..")
        radio = container.get_by_role("radio", name="启用")
        radio.wait_for(state="visible", timeout=15000)
        return radio.is_checked()
