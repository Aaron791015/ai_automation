# -*- coding: utf-8 -*-
"""公司層「個人資料」Page Object（`/profile`）。

2026-08-28 MCP 實測確認：「个人资料」底下有**真正的子頁面**（role=menuitem，
切換會改變 URL）：「修改密码」（預設落地，`/profile`）／「双重验证」
（`/profile/security`）／「IP 白名单」（`/profile/ip-allowlist`）。
前置條件：已登入公司層（`http://b1.c1.snotra.qat`）。

⚠️⚠️ 三個子頁面全部刻意只做**結構性檢查**（欄位／按鈕都在），不送出任何表單——
`aaron01` 是這個工作區目前唯一一組公司層帳密，被多個 session／pytest 共用：
- 「修改密码」送出會讓所有還在用這組帳密登入的 session 立刻失效；
- 「双重验证」點「绑定」會把這組共用帳號綁上 TOTP 驗證器，之後所有 session
  登入都會被要求輸入驗證碼，形同鎖死共用帳號；
- 「IP 白名单」點「保存」（尤其欄位空白時）可能變更帳號可登入的 IP 範圍，
  影響其他 session 用這組帳密連線的能力。
之後若有專用測試帳號，才適合把這些 roundtrip 補進真正的 write_action 案例。
"""
from __future__ import annotations

from playwright.sync_api import Page


class ProfilePage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        """導覽到「个人资料→修改密码」子頁面（預設落地頁，`/profile`）。"""
        self.page.get_by_role("menuitem", name="个人资料").click()
        self.page.wait_for_timeout(600)

    def goto_security(self) -> None:
        """導覽到「个人资料→双重验证」子頁面（`/profile/security`）。"""
        self.goto()
        self.page.get_by_role("menuitem", name="双重验证").click()
        self.page.wait_for_timeout(600)

    def goto_ip_allowlist(self) -> None:
        """導覽到「个人资料→IP 白名单」子頁面（`/profile/ip-allowlist`）。"""
        self.goto()
        self.page.get_by_role("menuitem", name="IP 白名单").click()
        self.page.wait_for_timeout(600)

    def has_password_form(self) -> bool:
        """三個密碼欄位與保存/重置按鈕是否都在（純結構檢查，不填不送出）。

        ⚠️ 欄位的 accessible name 帶著必填星號前綴（「* 新密码」），子字串比對
        `name="新密码", exact=False` 會同時中「* 新密码」與「* 确认新密码」，
        必須用完整字串（含星號前綴）配 `exact=True` 精準比對。
        """
        try:
            self.page.get_by_role("textbox", name="* 旧密码", exact=True).wait_for(
                state="visible", timeout=8000
            )
            self.page.get_by_role("textbox", name="* 新密码", exact=True).wait_for(
                state="visible", timeout=8000
            )
            self.page.get_by_role("textbox", name="* 确认新密码", exact=True).wait_for(
                state="visible", timeout=8000
            )
            self.page.get_by_role("button", name="保存").wait_for(state="visible", timeout=8000)
            self.page.get_by_role("button", name="重置").wait_for(state="visible", timeout=8000)
            return True
        except Exception:
            return False

    def has_security_setup_ui(self) -> bool:
        """雙重驗證子頁面：標題、QR Code、六格 OTP 欄位與「绑定」按鈕都在
        （純結構檢查，不點「绑定」）。
        """
        try:
            self.page.get_by_role("heading", name="设置双重验证").wait_for(
                state="visible", timeout=8000
            )
            self.page.get_by_role("img", name="QR Code").wait_for(state="visible", timeout=8000)
            self.page.get_by_role(
                "textbox", name="请输入第 1 位 OTP 字符"
            ).wait_for(state="visible", timeout=8000)
            self.page.get_by_role(
                "textbox", name="请输入第 6 位 OTP 字符"
            ).wait_for(state="visible", timeout=8000)
            self.page.get_by_role("button", name="绑定").wait_for(state="visible", timeout=8000)
            return True
        except Exception:
            return False

    def has_ip_allowlist_form(self) -> bool:
        """IP 白名單子頁面：標題、三組「IP N」／「备注」欄位與「保存」按鈕都在
        （純結構檢查，不點「保存」）。
        """
        try:
            self.page.get_by_role("heading", name="IP 白名单").wait_for(
                state="visible", timeout=8000
            )
            for i in (1, 2, 3):
                self.page.get_by_role(
                    "textbox", name="IP %d" % i, exact=True
                ).wait_for(state="visible", timeout=8000)
            self.page.get_by_role("button", name="保存").wait_for(state="visible", timeout=8000)
            return True
        except Exception:
            return False
