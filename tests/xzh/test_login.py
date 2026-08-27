# -*- coding: utf-8 -*-
"""新綜合登入案例（案例清單批次 A：A1～A4）。

前置條件：見 `tests/xzh/conftest.py`。這幾條案例本身在測登入流程，
         不能用 conftest 的 `platform_page`／`company_page` fixture（那些已經幫你登入了）。
"""
from __future__ import annotations

import pytest

from xzh_qa.config_loader import admin_credentials
from xzh_qa.pages.login_page import LoginPage


@pytest.mark.smoke
def test_platform_login_success(page, xzh_qat):
    """A1：正確帳密＋2FA 任意輸入 6 位數字 → 登入成功並導向租戶管理頁。

    oracle 來源：B 級（使用者 2026-08-26 告知現況，非正式規格），
    之後若 QAT 的 2FA 規則改動，本案例的斷言需要重新確認（見 SKILL.md §1 不變量 #3）。
    """
    username, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_platform_url"])
    lp.login(username, password)
    assert lp.is_otp_page(), "帳密正確送出後應先導到二次驗證頁"
    lp.submit_otp("123456")
    assert "/tenant/company" in page.url


@pytest.mark.skip(
    reason="A2：2FA 非數字字元/位數不足時的預期行為尚未實測確認，"
    "屬探索性案例（見案例清單 A2），先不硬編一個猜測的 oracle"
)
def test_platform_otp_invalid_input(page, xzh_qat):
    pass


@pytest.mark.smoke
def test_platform_login_wrong_password(page, xzh_qat):
    """A3：密碼錯誤 → 應仍停在登入頁。

    只驗證「沒登入成功」，不斷言確切錯誤訊息文字——訊息內容尚未實測確認（見案例清單 A3）。
    """
    username, _password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_platform_url"])
    lp.login(username, "wrong-password-xzh-probe")
    page.wait_for_timeout(1000)
    assert lp.is_on_sign_in_page()


@pytest.mark.smoke
def test_company_login_no_otp(page, xzh_qat):
    """A4：公司層同帳密登入——現況記錄，非正確性判斷。

    目前觀察到公司層不會跳 2FA，原因未明（見矩陣 A2、SKILL.md §1 不變量待補項）。
    此案例只是把「現況」釘住做 regression，之後原因查明前不可改成斷言「這是對的」。
    """
    username, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_company_url"])
    lp.login(username, password)
    assert not lp.is_otp_page()
    assert "/user/account" in page.url
