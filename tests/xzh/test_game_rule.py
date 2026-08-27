# -*- coding: utf-8 -*-
"""代理層級與遊戲規則案例（案例清單 C0～C3）。"""
from __future__ import annotations

import pytest

from xzh_qa.pages.dashboard_page import AgentHierarchyPage
from xzh_qa.pages.game_rule_page import INTRO_MARKERS, GameRulePage


@pytest.mark.smoke
def test_agent_hierarchy_count_matches(company_page):
    """C0：導覽列「会员」分頁的人數與表格『共 N 条』一致（自檢不變量，讀取比對）。"""
    page = company_page
    ah = AgentHierarchyPage(page)
    ah.goto()
    ah.switch_tab("会员")
    assert ah.tab_label_count("会员") == ah.table_total_count()


@pytest.mark.smoke
@pytest.mark.parametrize("game_name", ["香港六合彩", "英国天天彩", "宾果六合彩"])
def test_game_rule_intro_and_bet_types(company_page, game_name):
    """C1～C3：三彩種的「遊戲規則」頁遊戲介紹與 21 種玩法皆正確顯示。

    oracle 來源：A 級——期望值即 `docs/新綜合/新綜合_遊戲機制.md` §2/§3 記錄的原文，
    這裡驗證的是「頁面顯示是否仍與機制文件記錄一致」（regression），不是重新定義規格。
    """
    page = company_page
    grp = GameRulePage(page)
    grp.goto()
    grp.switch_game(game_name)
    intro = grp.intro_text()
    marker = INTRO_MARKERS[game_name]
    assert marker in intro, "遊戲介紹段落應包含「%s」" % marker
    missing = grp.missing_bet_types()
    assert missing == [], "缺少玩法按鈕：%s" % missing
