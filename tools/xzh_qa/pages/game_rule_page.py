# -*- coding: utf-8 -*-
"""公司層「遊戲規則」頁 Page Object（`/rule`）。

用途：讀取服務條款、各彩種的遊戲介紹文字、21 種玩法按鈕清單。
使用方式：
    grp = GameRulePage(page)
    grp.goto()
    grp.switch_game("香港六合彩")
    grp.intro_text()          # 含「游戏介绍」標題與段落文字
    grp.missing_bet_types()   # 空清單＝21 種玩法全部都在
前置條件：已登入公司層（`http://b1.c1.snotra.qat`）。

機制依據：`docs/新綜合/新綜合_遊戲機制.md` §2（各彩種遊戲介紹原文）、§3（21 種玩法清單）。
⚠️ 三個彩種（香港六合彩／英國天天彩／賓果六合彩）共用同一套 21 種玩法按鈕——
本檔的 `BET_TYPES` 常數即為權威清單，改動玩法前先跟機制文件核對。
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

#: 各彩種「游戏介绍」段落裡用來確認內容正確的可辨識子字串。
#: ⚠️ **不是每個彩種的介紹都會重複打出自己的全名**——2026-08-26 實測發現，
#: 香港六合彩的原文是「六合彩源自香港…」，並不包含「香港六合彩」這個完整字串，
#: 跟英國天天彩／賓果六合彩開頭就打出全名的寫法不一樣（見 `新綜合_遊戲機制.md` §2 原文）。
INTRO_MARKERS = {
    "香港六合彩": "源自香港",
    "英国天天彩": "英国天天彩",
    "宾果六合彩": "宾果六合彩",
}

#: 三彩種共用的 21 種玩法（見 `新綜合_遊戲機制.md` §3，勿與該文件內容脫鉤）。
BET_TYPES = [
    "特码", "正码", "正特码", "两面", "连码", "过关", "生肖", "尾数", "半波",
    "六肖", "特肖", "生肖连", "尾数连", "不中", "多选中一", "特平中", "合肖",
    "七码", "五行", "一肖量", "尾数量", "比大小",
]


class GameRulePage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        self.page.get_by_role("menuitem", name="游戏规则").click()

    def switch_game(self, game_name: str) -> None:
        """點擊上方彩種卡片切換目前顯示的彩種（如「香港六合彩」「英国天天彩」「宾果六合彩」）。

        ⚠️ 「游戏介绍」的容器一直都在，切彩種只是**內容非同步換掉**——
        用 `expect().to_contain_text()` 等內容真的換成新彩種，而不是點完立刻讀（會讀到舊彩種殘留）。
        """
        self.page.get_by_text(game_name, exact=True).first.click()
        container = self.page.get_by_role("heading", name="游戏介绍").locator("xpath=..")
        marker = INTRO_MARKERS.get(game_name, game_name)
        expect(container).to_contain_text(marker, timeout=8000)

    def intro_text(self) -> str:
        """回傳「游戏介绍」標題所在容器的文字（含標題本身＋段落內容）。

        用 `get_by_role("heading", ...)` 而非假設實際標籤是 `<h3>`——
        Playwright 依 accessibility tree 判斷角色，不受實際 DOM 標籤影響。
        """
        heading = self.page.get_by_role("heading", name="游戏介绍")
        return heading.locator("xpath=..").inner_text()

    def missing_bet_types(self) -> list[str]:
        """回傳畫面上看不到的玩法名稱清單（空清單＝21 種玩法按鈕全部都在）。

        用 `wait_for` 而非直接 `is_visible()`——後者是immediate 快照，
        切彩種後這批按鈕可能還沒重新渲染完成。
        """
        missing = []
        for label in BET_TYPES:
            try:
                self.page.get_by_role("button", name=label, exact=True).wait_for(
                    state="visible", timeout=5000
                )
            except Exception:
                missing.append(label)
        return missing
