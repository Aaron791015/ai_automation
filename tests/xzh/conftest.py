# -*- coding: utf-8 -*-
"""新綜合（xzh）測試共用 fixtures：已登入的 page（平台層／公司層）。

前置條件：`config/environments.json` 的 `xzh.qat` 需已填好網址與帳密
         （`scripts/new_product.py` 建立時已放好骨架，2026-08-26 已補上實際值）。
"""
from __future__ import annotations

import pytest

from xzh_qa.config_loader import admin_credentials, qat
from xzh_qa.pages.login_page import LoginPage


@pytest.fixture
def xzh_qat():
    return qat()


@pytest.fixture
def platform_page(page, xzh_qat):
    """已登入平台層（含 2FA，QAT 目前任意 6 位數字即可通過）的 page。"""
    username, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_platform_url"])
    lp.login(username, password)
    if lp.is_otp_page():
        lp.submit_otp("123456")
    return page


@pytest.fixture
def company_page(page, xzh_qat):
    """已登入公司層的 page（目前不會跳 2FA，原因未明，見矩陣 A2）。"""
    username, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_company_url"])
    lp.login(username, password)
    return page


@pytest.fixture
def level1_agent_page(page, xzh_qat):
    """已登入一級代理層的 page。

    代理測試帳號是可審查的 QAT 測試資料；密碼與現有 QAT admin 共用，
    只由既有設定讀取，不另寫入測試碼、文件或 Allure 附件。
    """
    _, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_company_url"])
    lp.login("aaa111", password)
    if lp.is_otp_page():
        lp.submit_otp("123456")
    return page
