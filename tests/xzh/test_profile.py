# -*- coding: utf-8 -*-
"""個人資料選單案例。

2026-08-28 首次探索。「个人资料」底下有三個**真正的子頁面**（role=menuitem，
切換會改變 URL）：「修改密码」（預設落地）／「双重验证」／「IP 白名单」，
跟「用户管理」「系统设置」同一種結構，各自一條案例配靜態 `@allure.suite(...)`。

⛔ 三條案例都只做結構性檢查，不實際送出任何表單——`aaron01` 是這個工作區目前
唯一一組公司層帳密，被多個 session／pytest 共用（見驗證交接 T13）：
- 「修改密码」送出會讓所有還在用這組帳密登入的 session 立刻失效；
- 「双重验证」點「绑定」會把這組共用帳號綁上 TOTP 驗證器，之後所有 session
  登入都會被要求輸入驗證碼，形同鎖死共用帳號；
- 「IP 白名单」點「保存」（尤其欄位空白時）可能變更帳號可登入的 IP 範圍，
  影響其他 session 用這組帳密連線的能力。
細節見各 Page Object 方法的檔頭說明（`xzh_qa.pages.profile_page`）。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.profile_page import ProfilePage


@allure.suite("修改密码")
@pytest.mark.smoke
def test_password_form_structure(company_page):
    """個人資料→修改密碼子頁面的表單欄位與按鈕都在（純結構檢查，不填不送出）。

    步驟：
    1. 導覽到「个人资料」頁（預設落地頁就是「修改密码」）
    2. 確認「旧密码」「新密码」「确认新密码」三個欄位與「保存」「重置」按鈕都存在

    預期結果：
    - 三個密碼欄位與兩個按鈕都應該存在

    ⛔ 不會實際填寫或送出——會影響到共用帳密的其他 session，見本檔檔頭說明。
    """
    page = company_page
    pp = ProfilePage(page)
    with allure.step("導覽到「个人资料」頁（預設落地頁就是「修改密码」）"):
        pp.goto()
    with allure.step("確認「旧密码」「新密码」「确认新密码」三個欄位與「保存」「重置」按鈕都存在"):
        ok = pp.has_password_form()
    allure.attach(
        f"實際：三個密碼欄位＋保存/重置按鈕 {'全部存在' if ok else '有缺漏'}（期望：全部存在）",
        name="修改密码表單結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert ok


@allure.suite("双重验证")
@pytest.mark.smoke
def test_security_setup_structure(company_page):
    """個人資料→雙重驗證子頁面的 QR Code、OTP 欄位與「绑定」按鈕都在
    （純結構檢查，不點「绑定」）。

    步驟：
    1. 導覽到「个人资料→双重验证」子頁面
    2. 確認標題、QR Code、六格 OTP 輸入欄位與「绑定」按鈕都存在

    預期結果：
    - 標題、QR Code、OTP 欄位與「绑定」按鈕都應該存在

    ⛔ 不會點擊「绑定」——會把共用帳號綁上 TOTP 驗證器，見本檔檔頭說明。
    """
    page = company_page
    pp = ProfilePage(page)
    with allure.step("導覽到「个人资料→双重验证」子頁面"):
        pp.goto_security()
    with allure.step("確認標題、QR Code、六格 OTP 輸入欄位與「绑定」按鈕都存在"):
        ok = pp.has_security_setup_ui()
    allure.attach(
        f"實際：標題／QR Code／OTP 欄位／「绑定」按鈕 {'全部存在' if ok else '有缺漏'}（期望：全部存在）",
        name="双重验证表單結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert ok


@allure.suite("IP 白名单")
@pytest.mark.smoke
def test_ip_allowlist_structure(company_page):
    """個人資料→IP 白名單子頁面的三組 IP／備註欄位與「保存」按鈕都在
    （純結構檢查，不點「保存」）。

    步驟：
    1. 導覽到「个人资料→IP 白名单」子頁面
    2. 確認標題與三組「IP N」／「备注」欄位、以及「保存」按鈕都存在

    預期結果：
    - 標題、三組欄位與「保存」按鈕都應該存在

    ⛔ 不會點擊「保存」——空白送出可能改變帳號可登入的 IP 範圍，見本檔檔頭說明。
    """
    page = company_page
    pp = ProfilePage(page)
    with allure.step("導覽到「个人资料→IP 白名单」子頁面"):
        pp.goto_ip_allowlist()
    with allure.step("確認標題與三組「IP N」／「备注」欄位、以及「保存」按鈕都存在"):
        ok = pp.has_ip_allowlist_form()
    allure.attach(
        f"實際：標題／三組 IP 欄位／「保存」按鈕 {'全部存在' if ok else '有缺漏'}（期望：全部存在）",
        name="IP 白名单表單結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert ok
