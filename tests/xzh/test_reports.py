# -*- coding: utf-8 -*-
"""開獎號碼與空狀態頁面案例（案例清單 E1、E2）。"""
from __future__ import annotations

import pytest

from xzh_qa.pages.dashboard_page import EmptyStatePage, IssuePage


@pytest.mark.smoke
def test_issue_history_has_records(company_page):
    """E1：開獎號碼頁能讀到歷史紀錄（先驗證讀取到位；期號遞增規律已在
    `docs/新綜合/新綜合_遊戲機制.md` §2 的首次探索記錄過，這裡做 regression）。
    """
    page = company_page
    ip = IssuePage(page)
    ip.goto()
    rows = ip.row_texts()
    assert len(rows) > 1, "應有多筆歷史開獎紀錄可供比對"


@pytest.mark.smoke
def test_bet_summary_shows_no_data(company_page):
    """E2a：注單數據（逐筆注單）目前仍顯示「暫無數據」。

    oracle 來源：D 級（2026-08-26 探索當下實測），regression 用途。
    """
    page = company_page
    esp = EmptyStatePage(page)
    esp.goto_bet_summary()
    assert esp.shows_no_data()


@pytest.mark.smoke
def test_report_page_loads_with_data(company_page):
    """E2b：⚠️ 2026-08-26 重跑 T9 時發現「報表→占成報表」已經有真實聚合資料
    （例如帳號 mimir1 已有 107 注、總投 225.00），跟首次探索當下「無資料」的現況不再一致——
    QAT 環境並非只有我們在用，有其他 session／使用者的活動會反映在這裡。

    這條案例因此改為只驗證頁面能正常載入並顯示表格（不管有沒有資料），
    不再斷言「暫無數據」——那個假設已經不成立，見 `新綜合_驗證項目清單.md` H2/H3 附註。
    """
    page = company_page
    esp = EmptyStatePage(page)
    esp.goto_report()
    page.wait_for_timeout(1500)
    assert page.get_by_role("main").is_visible()
