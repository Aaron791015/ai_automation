# -*- coding: utf-8 -*-
"""跟單管理案例（案例清單 F1、H4）。"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.copy_bet_page import CopyBetPage


@pytest.mark.smoke
def test_existing_copy_bet_group_displayed(company_page):
    """H4 現況記錄：既有跟單群組「M2E2E」的欄位顯示正確（唯讀，不建立新群組）。"""
    page = company_page
    cbp = CopyBetPage(page)
    with allure.step("導覽到跟單管理頁"):
        cbp.goto()
    with allure.step("讀取群組「M2E2E」該列的文字"):
        text = cbp.group_row_text("M2E2E")
    allure.attach(
        f"該列實際文字：{text!r}\n期望包含：跟單比例 50%、狀態「停用」",
        name="跟單群組 M2E2E 欄位現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "50" in text, "跟單比例應顯示 50%"
    assert "停用" in text


@pytest.mark.skip(
    reason="F1：2026-08-26 已用 MCP 點開『新增』表單並唯讀探索完整欄位結構"
    "（未送出保存，見 CopyBetPage 檔頭說明），發現前置條件比預期複雜，非單純補 selector 能解決："
    "① 『跟單對象』要求輸入內部數字 user ID（不是帳號名稱），UI 上任何列表都不顯示這個 ID，"
    "目前沒有從 UI 查得到任意帳號 ID 的入口；② 『投注會員』要求輸入會員的安全碼（資金密碼），"
    "這是敏感憑證，不能挪用既有帳號（如 M2E2E 已用的會員，CLAUDE.md §5 紀律 2），"
    "必須先有一個自己建立、知道安全碼的測試會員——而『建會員』與『查得帳號內部 ID』這兩條路"
    "本身都還沒探索過，不屬本次任務範圍。硬做會建立不完整或無法通過『分配比例合計需為 100%』"
    "驗證的殘缺資料，因此保留 skip。已在 CopyBetPage 補上 open_create_form／fill_basic_fields／"
    "add_target_object_row／add_betting_member_row／cancel_create／save_create 六個方法，"
    "欄位結構與已知限制見該檔檔頭說明，供之後补齊前置條件（會員安全碼、帳號 ID 查詢方式）後直接使用。"
)
def test_create_copy_bet_group(company_page):
    with allure.step("略過：前置條件未備妥（會員安全碼、帳號內部 ID 查詢方式皆未探索，見上方 skip 原因）"):
        pass
