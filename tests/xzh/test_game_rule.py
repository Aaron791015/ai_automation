# -*- coding: utf-8 -*-
"""遊戲規則選單案例（案例清單 C1～C3）。

📝 2026-08-28：原本跟「用户管理」擠在同一份檔案（檔名跟內容對不上，兩條案例其實對應
兩個不同選單），依使用者指示拆成兩個檔案：「用户管理」移到 `test_user_management.py`，
本檔只留「游戏规则」這一條，檔名跟內容終於一致。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.game_rule_page import INTRO_MARKERS, GameRulePage


@pytest.mark.smoke
@pytest.mark.parametrize("game_name", ["香港六合彩", "英国天天彩", "宾果六合彩"])
def test_game_rule_intro_and_bet_types(company_page, game_name):
    """C1～C3：三彩種的「遊戲規則」頁遊戲介紹與 21 種玩法皆正確顯示。

    步驟：
    1. 導覽到「游戏规则」頁
    2. 切換到 `game_name` 分頁
    3. 讀取遊戲介紹段落文字
    4. 逐一檢查 21 種玩法按鈕是否齊全

    預期結果：
    - 介紹段落應包含 `docs/新綜合/新綜合_遊戲機制.md` 記錄的關鍵字
    - 玩法按鈕不應有缺漏

    oracle 來源：A 級——期望值即 `docs/新綜合/新綜合_遊戲機制.md` §2/§3 記錄的原文，
    這裡驗證的是「頁面顯示是否仍與機制文件記錄一致」（regression），不是重新定義規格。
    """
    page = company_page
    grp = GameRulePage(page)
    with allure.step(f"導覽到「游戏规则」頁並切換到「{game_name}」"):
        grp.goto()
        grp.switch_game(game_name)
    with allure.step("讀取遊戲介紹段落文字"):
        intro = grp.intro_text()
    marker = INTRO_MARKERS[game_name]
    allure.attach(
        f"期望包含關鍵字：{marker!r}\n實際介紹段落：{intro!r}",
        name=f"{game_name} 遊戲介紹段落",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert marker in intro, "遊戲介紹段落應包含「%s」" % marker
    with allure.step("逐一檢查 21 種玩法按鈕是否齊全"):
        missing = grp.missing_bet_types()
    allure.attach(
        f"缺少的玩法按鈕：{missing}（期望：空清單）",
        name=f"{game_name} 玩法按鈕齊全度",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert missing == [], "缺少玩法按鈕：%s" % missing
