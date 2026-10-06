# -*- coding: utf-8 -*-
"""新綜合後台登入頁 Page Object（平台層／公司層共用同一套元件結構）。

用途：封裝登入流程，含平台層的二次驗證(2FA)步驟。
使用方式：
    lp = LoginPage(page)
    lp.goto(cfg["backend_platform_url"])
    lp.login(username, password)
    if lp.is_otp_page():
        lp.submit_otp("123456")
前置條件：目標站台可連線；帳密見 `config/environments.json` 的 `xzh.qat`
         （用 `xzh_qa.config_loader.admin_credentials()` 取得）。

⚠️ 不變量依據：`.claude/skills/xzh/SKILL.md` §1 #3 —— QAT 環境目前 2FA 任意輸入
6 位數字即可通過；#5 —— 之後若改動使用者會另行告知，屆時 `submit_otp` 的假設要重新確認。
2026-08-26 探索確認：**只有平台層登入會跳 2FA，公司層目前不會**（原因未明，見矩陣 A2）。
"""
from __future__ import annotations

from playwright.sync_api import Page


class LoginPage:
    """帳密輸入框與登入按鈕的 accessible name 在平台層／公司層完全相同，可共用一份實作。"""

    def __init__(self, page: Page):
        self.page = page

    def goto(self, url: str) -> None:
        self.page.goto(url)

    def login(self, username: str, password: str) -> None:
        """填帳密並送出。平台層送出後會導到 2FA 頁；公司層目前會直接登入成功。

        ⚠️ 送出後的導頁是非同步的（SPA 路由）——**點下去那一刻 URL 還沒變**。
        `click()` 本身只保證點擊動作完成，不會等後續路由跳轉，
        所以這裡明確等「URL 離開登入頁」，逾時（密碼錯誤等不會跳轉的情境）就放行讓呼叫端自己判斷。
        """
        self.page.get_by_role("textbox", name="账号").fill(username)
        self.page.get_by_role("textbox", name="密码").fill(password)
        self.page.get_by_role("button", name="登录").click()
        try:
            self.page.wait_for_url(lambda url: "/auth/sign-in" not in url, timeout=8000)
        except Exception:
            pass  # 密碼錯誤等本來就不會離開登入頁的情境，逾時是預期中的

    def is_otp_page(self) -> bool:
        """判斷是否已導到二次驗證頁（只有平台層會出現，見不變量 #3）。"""
        return "two-factor-verify" in self.page.url

    def submit_otp(self, code: str = "123456") -> None:
        """逐格輸入 OTP 六碼並送出。QAT 目前任意 6 位數字即可通過。

        ⚠️ 2026-08-26 實測發現：**填完第 6 碼後畫面會自動送出並導頁**，
        不一定需要再按「提交」——而且常常是填完的當下就已經在導頁了。
        兩種情況都要撐得住：先等一下看會不會自動導頁，還在原頁才補點提交，
        否則會對著已經導航離開的頁面點一個不存在的按鈕而逾時。
        """
        assert len(code) == 6 and code.isdigit(), "OTP 必須是 6 位數字"
        for i, ch in enumerate(code, start=1):
            self.page.get_by_role(
                "textbox", name="请输入第 %d 位 OTP 字符" % i
            ).fill(ch)
        try:
            self.page.wait_for_url(lambda u: "two-factor-verify" not in u, timeout=2000)
            return  # 已自動送出並導頁，不必再點提交
        except Exception:
            pass
        submit = self.page.get_by_role("button", name="提交")
        if submit.is_visible():
            submit.click()

    def is_two_factor_setup_page(self) -> bool:
        """首次登入的帳號會落在「设置双重验证」頁（`/auth/two-factor-setup`，有「跳过」「绑定」兩鈕）。

        2026-10-02：第二組帳號（bbb111～bbb999、bbb010）首次登入遇到；aaron02（公司操作員）與
        aaa 鏈不會。該頁不是 2FA 驗證頁（`is_otp_page()` 為否），不處理就停在這裡。
        """
        return "two-factor-setup" in self.page.url

    def skip_two_factor_setup(self) -> None:
        """點「跳过」並在確認框（「跳过双重验证会增加账号被盗的风险，确定要跳过吗？」）再按「跳过」。

        ⛔ 只跳過，**不點「绑定」**（綁定會把帳號鎖上驗證器，之後每次登入都要輸入驗證碼）。
        跳過後伺服器端 `twoFactorAuthStatus` 變 `skipped`，同帳號之後登入不再出現此頁。
        """
        self.page.get_by_role("button", name="跳过", exact=True).first.click()
        box = self.page.locator(".el-message-box, .el-overlay-message-box, [role=dialog]").filter(
            has_text="确定要跳过吗")
        box.get_by_role("button", name="跳过", exact=True).click()
        self.page.wait_for_url(lambda url: "two-factor-setup" not in url, timeout=8000)

    def is_on_sign_in_page(self) -> bool:
        """登入失敗時應仍停在登入頁（見案例清單 A3，僅驗證「沒登入成功」，
        不斷言確切錯誤訊息文字——目前尚未實測確認訊息內容）。"""
        return "/auth/sign-in" in self.page.url
