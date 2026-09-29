"""平台 company1 編輯頁的獨立上限來源；每次執行重讀，不載入舊快照。"""
from xzh_qa.config_loader import admin_credentials, qat
from xzh_qa.pages.login_page import LoginPage
from xzh_qa.pages.platform_system_page import PlatformSystemPage


def read_platform_cap(page, screenshot=None):
    """須安排在公司登入前或所有公司讀取完成後，避免同帳號互踢。"""
    login = LoginPage(page)
    login.goto(qat()['backend_platform_url'])
    login.login(*admin_credentials())
    if login.is_otp_page():
        login.submit_otp('123456')
    return PlatformSystemPage(page).company_odds_gap_cap('company1', screenshot)
