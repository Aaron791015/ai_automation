# -*- coding: utf-8 -*-
"""「用户管理 → 编辑 → 赔率差分」設定頁的 Page Object。

用途：B88～B92、B101 的設定端操作——開啟目標帳號、切彩種、定位玩法主副欄、
      輸入／Tab、確認沒有加減按鈕、保存、重載、讀回、授權開關。

使用方式：
    gap = OddsGapSettingPage(company_page)
    gap.open_target("二级代理", "aaa222")
    gap.select_game("markSix")
    gap.set_value(row_index=0, column=0, value=Decimal("-1.1"))
    status = gap.save()

前置條件：已登入公司層或**直屬上級**代理層後台（`config/environments.json` 的 `xzh.qat`）。

⚠️ 實測得到的三個陷阱（2026-09-09～09-16，寫在這裡避免每個案例重踩）：
1. **列與 API 順序要先對齊再操作**——UI 列是非同步渲染的，切彩種後可能還留著上一個彩種的列。
   一律先 `wait_rows_match(api_rows)` 確認列名序列與 API 一致，再用列索引定位輸入框。
2. **副欄存在與否依 `subOddsLabel`**，不能用 `subOddsGap != null` 判定
   （`pickTwoHitBonus` 曾 `subOddsGap=null` 但副標籤為「中二」、UI 仍有副欄）。
3. **保存後可能 403 並跳回登入頁**（Snotra-006：公司保存下級）。`save()` 一律回傳實際狀態碼，
   ⛔ 不在此類內部把 403 吞掉或自動改走別的路徑——那會讓已知缺陷被判成通過。
"""
from __future__ import annotations

import re
from decimal import Decimal

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from xzh_qa.config_loader import chain_accounts
from xzh_qa.odds_gap_client import GAMES
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.pages.dashboard_page import AgentHierarchyPage

#: 設定目標帳號鏈：索引 0～8 為一～九級代理，索引 9 為會員。
#: 預設 aaa111～aaa999、aaa010；環境變數 `XZH_CHAIN=b` 時為 bbb111～bbb999、bbb010（見 config_loader）。
#: ⚠️ 模組載入時就決定，須在 python／pytest 行程啟動前設好環境變數。
CHAIN_ACCOUNTS = chain_accounts()


# 2026-10-07 前端把賠率差分輸入框從 input[type=number] 改成 input[type=text]（role=spinbutton、
# inputmode=decimal），兩種寫法都要能定位，否則切彩種會在等第一個輸入框時逾時。
GAP_INPUT_SELECTOR = "input[type=number], input[role=spinbutton]"

class OddsGapTabMissing(AssertionError):
    """目標帳號的編輯頁沒有「赔率差分」分頁（Snotra-005）。

    授權前提成立時應判**入口失敗**，下游檢查列受阻；⛔ 不可改列「不適用」。
    """


class OddsGapSettingPage:
    """賠率差分設定頁。列索引 `row` 對應 API 回傳的 `displayOrder` 順序（已對齊後）。"""

    #: 等「赔率差分」分頁出現的上限；逾時才判定為缺分頁（Snotra-005）。
    TAB_TIMEOUT_MS = 10000

    def __init__(self, page: Page):
        self.page = page

    # ---------------- 導覽 ----------------

    def open_target(self, level_tab: str, account: str, require_gap: bool = True) -> None:
        """從用户管理切到 `level_tab` 分頁、搜尋 `account`、點「编辑」、切到「赔率差分」分頁。"""
        hierarchy = AgentHierarchyPage(self.page)
        hierarchy.goto()
        hierarchy.switch_tab(level_tab)
        hierarchy.search_account(account)
        row = self.page.get_by_role("row").filter(
            has=self.page.get_by_text(account, exact=True))
        row.get_by_role("button", name="编辑", exact=True).click()
        self.page.get_by_role("tab", name="基本资料", exact=True).wait_for(state="visible")
        if not require_gap:
            return
        # 編輯頁的分頁列是非同步渲染的：要等，不能點完 `编辑` 就立刻 `count()`，
        # 否則每次都會誤判成 Snotra-005「缺分頁」。
        tab = self.page.get_by_role("tab", name="赔率差分", exact=True)
        try:
            tab.wait_for(state="visible", timeout=self.TAB_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            raise OddsGapTabMissing(
                f"{account} 的編輯頁在 {self.TAB_TIMEOUT_MS} ms 內沒有出現「赔率差分」分頁"
                f"（見 Snotra-005；授權前提成立時應判入口失敗，不可改列不適用）")
        tab.click()

    def open_target_by_index(self, index: int) -> str:
        """依鏈索引（0＝一级代理 aaa111 … 9＝会员 aaa010）開啟目標，回傳帳號。"""
        account = CHAIN_ACCOUNTS[index]
        self.open_target(AgentHierarchyPage.LEVELS[index], account)
        return account

    def select_game(self, game_id: str) -> None:
        """切換彩種（`markSix`／`ukLucky7`／`bingo6`），並等第一個輸入框出現。"""
        self.page.locator(".game-nav:visible").get_by_role(
            "button", name=GAMES[game_id], exact=True).click()
        self.page.locator("tr:visible").locator(GAP_INPUT_SELECTOR).first.wait_for(state="visible")

    def reload_tab(self, game_id: str) -> None:
        """重新整理整頁後回到賠率差分分頁與指定彩種——用於「保存後重載是否保留」的核對。

        ⚠️ 2026-09-16 實測補上：分頁列跟 `open_target` 一樣是非同步渲染的
        （reload 後不會立刻出現），先前這裡直接 `.click()`、沒有等可見就送出，
        在保存成功、重載時遇到渲染較慢會直接 20s 逾時整個中斷，
        導致保存後的還原步驟沒機會執行、把測試資料留在已改過的狀態。
        這裡已經先透過 `open_target` 進過一次編輯頁確認過有分頁，
        所以逾時視為單純渲染延遲重試，不當作 Snotra-005 的缺分頁判定。
        """
        self.page.reload(wait_until="domcontentloaded")
        tab = self.page.get_by_role("tab", name="赔率差分", exact=True)
        try:
            tab.wait_for(state="visible", timeout=self.TAB_TIMEOUT_MS * 2)
        except PlaywrightTimeoutError:
            if "/auth/" in self.page.url:
                # 2026-09-16 實測發現：reload 後被踢回登入頁，畫面訊息為
                # 「登录状态已失效，可能是账号已在其他地方登录，请重新登录」——
                # 這是**同一帳號被別處登入**踢下線，不是分頁渲染慢，也不是 Snotra-005 缺頁。
                # 本工作區多個 session 共用同一份 QAT 測試帳密（見 CLAUDE.md），
                # 極可能是另一個 session 同時用同一組公司/代理帳密操作而互踢。
                # 這裡改丟出明確訊息，讓呼叫端／人工判讀不會誤判成缺分頁或渲染逾時。
                raise AssertionError(
                    f"重載後被踢回登入頁（{self.page.url}）：疑似同一帳號被其他 session 登入頂替，"
                    f"非分頁渲染逾時、非 Snotra-005 缺頁；本輪保存後的還原步驟未能執行，"
                    f"目標欄位可能停留在已修改值，需人工確認並還原。")
            raise
        tab.click()
        self.select_game(game_id)

    # ---------------- 讀取 ----------------

    def _rows(self):
        return self.page.locator("tr:visible").filter(
            has=self.page.locator(GAP_INPUT_SELECTOR))

    def read_rows(self) -> list[dict]:
        """一次讀回畫面上所有設定列：`{name, inputs: [...], remaining: [...]}`。

        用單一 `evaluate_all` 讀完，避免逐格 locator 造成上百次往返（100 列／115 欄）。
        """
        return self._rows().evaluate_all(
            """rs => rs.map(r => ({
                name: r.cells[0].innerText.trim(),
                inputs: Array.from(r.querySelectorAll('input')).map(x => x.value),
                remaining: r.cells[r.cells.length - 1].innerText.split('/').map(x => x.trim())
            }))"""
        )

    def row_names(self) -> list[str]:
        return [r["name"] for r in self.read_rows()]

    def column_headers(self) -> list[str]:
        """讀表頭文字（期望「玩法／赔率差分／剩余差分」）。"""
        return [t.strip() for t in
                self.page.locator("table:visible thead th").all_inner_texts()]

    def wait_rows_match(self, api_rows: list[dict], timeout_ms: int = 6000) -> list[dict]:
        """等到畫面列名序列與 API 的 `playTypeName` 序列一致，回傳當下讀到的列。

        切彩種是非同步的，不等齊就用列索引定位會**寫到別的彩種的欄位**。
        """
        expected = [r["playTypeName"] for r in api_rows]
        # 新版UI將副標籤合併顯示為「二中特 / 中二」；API主名稱仍為「二中特」。
        # 只接受API對應的主名與副標籤，不任意刪除斜線後文字而掩蓋錯列。
        def normalized(value):
            return re.sub(r"\s+", "", value)
        allowed = [{normalized(r["playTypeName"])} | (
            {normalized(r["playTypeName"] + "/" + r["subOddsLabel"])}
            if r.get("subOddsLabel") is not None else set()) for r in api_rows]
        deadline = timeout_ms
        while deadline > 0:
            rows = self.read_rows()
            if len(rows) == len(allowed) and all(
                    normalized(r["name"]) in names for r, names in zip(rows, allowed)):
                return rows
            self.page.wait_for_timeout(200)
            deadline -= 200
        actual = self.row_names()
        raise AssertionError(
            f"UI 列與 API 列對不上：UI {len(actual)} 列、API {len(expected)} 列；"
            f"首個差異＝{next((a for a, b in zip(actual, expected) if a != b), '(長度不同)')}")

    def wait_values_match(self, api_rows: list[dict], timeout_ms: int = 10000) -> dict:
        """重載後等畫面輸入框的值與 API 一致，回傳 `{rows, matched, waited_ms, first_mismatches}`。

        ⚠️ 2026-09-23 實測：重載後列名先出現、數值稍後才綁上，只等列名就讀值，
        偶爾整批讀到 0.0000（76 組中 2 組，API 值皆正確）。這裡只多等數值，
        逾時仍不一致就原樣回傳最後一次讀值，讓呼叫端照常判失敗，不掩蓋真的顯示錯誤。
        API 為 NULL 的欄位不比（畫面不一定顯示成 0）。
        """
        def mismatches(rows):
            bad = 0
            for ui, api in zip(rows, api_rows):
                for col, key in ((0, "oddsGap"), (1, "subOddsGap")):
                    if api.get(key) is None or col >= len(ui["inputs"]):
                        continue
                    try:
                        same = Decimal(ui["inputs"][col]) == Decimal(str(api[key]))
                    except (ArithmeticError, ValueError):
                        same = False
                    bad += not same
            return bad + abs(len(rows) - len(api_rows))

        rows = self.read_rows()
        first = mismatches(rows)
        waited = 0
        bad = first
        while bad and waited < timeout_ms:
            self.page.wait_for_timeout(200)
            waited += 200
            rows = self.read_rows()
            bad = mismatches(rows)
        return {"rows": rows, "matched": bad == 0, "waited_ms": waited, "first_mismatches": first}

    def input_box(self, row: int, column: int = 0):
        """定位第 `row` 列第 `column` 欄的輸入框（0＝主差分欄、1＝副差分欄）。"""
        return self._rows().nth(row).locator("input").nth(column)

    def value_of(self, row: int, column: int = 0) -> Decimal:
        return dec(self.input_box(row, column).input_value())

    def remaining_of(self, row: int, column: int = 0) -> Decimal:
        return dec(self.read_rows()[row]["remaining"][column])

    # ---------------- 輸入 ----------------

    def set_value(self, row: int, column: int, value) -> Decimal:
        """輸入值後按 Tab，回傳失焦後的實際值（呼叫端自行斷言，本方法不替它判定）。

        ⚠️ 刻意**不** assert——B91 邊界案例要測的就是「非法值失焦後變成什麼」，
        在這裡先 assert 會讓那些案例無法取得實際行為。
        """
        box = self.input_box(row, column)
        box.fill(str(value), force=True)
        self.page.keyboard.press("Tab")
        return dec(box.input_value())

    def fill_raw(self, row: int, column: int, text: str) -> str:
        """輸入**原始字串**（空值、`abc`、超位小數等）後按 Tab，回傳失焦後的字串值。"""
        box = self.input_box(row, column)
        box.fill("", force=True)
        if text:
            box.press_sequentially(text)
        self.page.keyboard.press("Tab")
        return box.input_value()

    def step_button_count(self, row: int, column: int = 0) -> int:
        """該欄「−」「＋」加減按鈕的數量。

        2026-10-07 Aaron 裁定設定頁差分輸入框沒有加減按鈕（`el-input-number is-without-controls`），應為 0；
        9/14～10/01 舊畫面每欄各有一組、步進 0.0001，舊的 `step_down`／`step_up` 已隨之移除。
        """
        cell = self._rows().nth(row).locator(".el-input-number").nth(column)
        return cell.locator(".el-input-number__decrease, .el-input-number__increase").count()

    def paste_raw(self, row: int, column: int, text: str) -> str | None:
        """可用瀏覽器剪貼簿時實際 Ctrl+V；不能操作時回 None，不冒充貼上。"""
        if not self.page.evaluate("Boolean(navigator.clipboard)"):
            return None
        self.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        original = self.page.evaluate("navigator.clipboard.readText()")
        try:
            self.page.evaluate("s => navigator.clipboard.writeText(s)", text)
            box = self.input_box(row, column)
            box.fill("", force=True)
            box.press("Control+V")
            self.page.keyboard.press("Tab")
            return box.input_value()
        finally:
            self.page.evaluate("s => navigator.clipboard.writeText(s)", original)

    # ---------------- 保存 ----------------

    def save(self, allow_no_request: bool = False) -> dict:
        """點「保存」並攔 PUT `/api/OddsGapSetting`，回傳 `{status, body, payload, url}`。

        ⛔ 不在此判定成功／失敗——403 跳登入（Snotra-006）由案例判 FAIL 並留證。
        """
        requests = []
        def observe(request):
            if "/api/OddsGapSetting" in request.url and request.method == "PUT":
                requests.append(request)
        self.page.on("request", observe)
        try:
            with self.page.expect_response(
                    lambda r: "/api/OddsGapSetting" in r.url and r.request.method == "PUT",
                    timeout=5000 if allow_no_request else 20000) as caught:
                self.page.get_by_role("button", name="保存", exact=True).click(timeout=5000 if allow_no_request else 20000)
            response = caught.value
            return {"status": response.status, "body": response.text()[:2000],
                    "payload": response.request.post_data_json, "url": response.url}
        except PlaywrightTimeoutError:
            if not allow_no_request or requests:
                raise
            return {"status": None, "body": "UI 未送出 PUT", "payload": None, "url": self.page.url}
        finally:
            self.page.remove_listener("request", observe)

    def bounced_to_login(self) -> bool:
        """保存後是否被踢回登入頁（Snotra-006 的伴隨現象）。"""
        self.page.wait_for_timeout(1200)
        return "/auth/" in self.page.url

    def messages(self) -> list[str]:
        """讀畫面上的提示訊息（Element Plus 的 message／message-box）。"""
        return [t.strip() for t in
                self.page.locator(".el-message, .el-overlay-message-box").all_text_contents()]

    # ---------------- 授權（B88） ----------------

    def open_basic_info(self) -> None:
        self.page.get_by_role("tab", name="基本资料", exact=True).click()

    def earn_odds_gap_checkbox(self):
        """「基本资料」分頁的「赚取赔率差」勾選項——上級授權開關。

        ⚠️ 2026-09-16 實測：這是標準 Element Plus 樣式，真正的 `<input>`
        （`el-checkbox__original`）視覺上是隱藏的（供原生 checked 狀態用），
        可點擊的是外層 `<label class="el-checkbox">`。`is_checked()` 讀狀態
        不需要可見性，正常；但 `.click()` 這顆隱藏 input 會因「element is not
        visible」逾時——這是本測試腳本的定位問題，不是產品缺陷。
        """
        return self.page.get_by_role("checkbox", name=re.compile(r"赚取赔率差"))

    def earn_odds_gap_label(self):
        """「赚取赔率差」checkbox 外層可點擊的 `<label>`（用於 `.click()`）。"""
        return self.page.locator("label.el-checkbox", has_text="赚取赔率差")

    def is_earn_odds_gap_checked(self) -> bool:
        self.open_basic_info()
        return self.earn_odds_gap_checkbox().is_checked()

    def set_earn_odds_gap(self, enabled: bool) -> dict:
        """切換授權開關並保存，回傳保存回應（同 `save()` 的格式）。"""
        self.open_basic_info()
        box = self.earn_odds_gap_checkbox()
        if box.is_checked() != enabled:
            self.earn_odds_gap_label().click()
        with self.page.expect_response(
                lambda r: "/api/" in r.url and r.request.method in ("PUT", "POST")) as caught:
            self.page.get_by_role("button", name="保存", exact=True).click()
        response = caught.value
        return {"status": response.status, "body": response.text()[:2000], "url": response.url}

    def has_gap_tab(self) -> bool:
        """編輯頁是否有「赔率差分」分頁（授權撤銷後的存取權判定，B88）。"""
        return self.page.get_by_role("tab", name="赔率差分", exact=True).count() > 0
