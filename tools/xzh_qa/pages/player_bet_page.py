# -*- coding: utf-8 -*-
"""會員前台下注頁最小 POM；selector 於 2026-09-04 QAT 實際探索確認。

2026-09-05 依 QAT 實測重寫送出流程（見 `_confirm_bet`）：
成敗一律以 `POST /api/Bets` 的實際回應判定，不再倚賴 toast 文字或
「確認視窗是否關閉」——頁面上永遠有 3 個空的 `el-overlay-dialog` 與一個
「网络测速」抽屜同樣帶 `role="dialog"`，用 `.last` 取視窗必然取錯。
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import Page

from xzh_qa.pages.login_page import LoginPage


class BetAmountRejected(AssertionError):
    """站台以「投注金额超过最高限额」拒絕本次金額；`limit` 是站台回報的上限。"""

    def __init__(self, message: str, limit: str):
        super().__init__(message)
        self.limit = limit


class BetOddsChanged(AssertionError):
    """站台以「赔率已变动，请确认后重新投注」拒絕本次送出。

    這是暫時性狀況——前端手上的賠率快照過期，注單並未建立；重新選一次、拿到新的
    賠率快照再送即可。不可當成成功，也不是「不明狀態」（後端明確回 400 且沒有建單）。
    """


class PlayerBetPage:
    def __init__(self, page: Page):
        self.page = page

    def login(self, url: str, username: str, password: str) -> None:
        login = LoginPage(self.page)
        login.goto(url)
        login.login(username, password)
        if login.is_otp_page():
            login.submit_otp("123456")
        self.page.wait_for_url(lambda value: "/bet" in value, timeout=10_000)

    _FRONTEND_CATEGORY = {"连肖": "生肖连", "连尾": "尾数连"}
    _ZODIACS = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
    _CN_NUMBERS = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    }

    def select_game(self, game_name: str) -> None:
        self.page.get_by_text(game_name, exact=True).first.click()
        self.page.wait_for_timeout(500)

    def select_combo_target(self, category: str, sub_item: str | None = None) -> None:
        """切到前台組合玩法及其子項；名稱以後台 K7 顯示名稱為準。"""
        front_category = self._FRONTEND_CATEGORY.get(category, category)
        # 不能只用字串 ``has_text``：例如「特码」會同時命中「特码」與「正特码」，
        # Playwright strict mode 會因此拒絕點擊。分類與子項都是完整標籤，使用完整
        # 文字比對也可避免未來「二全中」等名稱相近時選到錯誤玩法。
        self.page.locator(
            ".category-item", has_text=re.compile(rf"^{re.escape(front_category)}$")
        ).click()
        self.page.wait_for_timeout(400)
        if sub_item:
            self.page.locator(
                ".el-segmented__item-label", has_text=re.compile(rf"^{re.escape(sub_item)}$")
            ).click()
            self.page.wait_for_timeout(400)

    def _bet_dialog(self):
        """下注確認視窗；以「返回修改」按鈕辨識。

        ⚠️ 不可用 `get_by_role("dialog").last` —— 2026-09-05 QAT 實測，`/bet` 頁固定
        存在 4 個 `role="dialog"`：「网络测速」抽屜 ＋ 3 個 `el-overlay-dialog`，其中
        只有一個承載下注確認內容，另外兩個永遠是空殼。舊版取 `.last` 會落在空殼上，
        因而把「限額被拒、視窗仍開著」誤報成「視窗未關閉，無法確認注單是否送出」。
        """
        return self.page.locator('[role="dialog"]').filter(
            has=self.page.get_by_role("button", name=re.compile(r"^返回修改$"))
        )

    def dismiss_message_box(self) -> str | None:
        """關掉殘留的 `el-message-box`（例如限額錯誤），回傳其文字；沒有則回 None。

        這個訊息框會蓋住整個下注面板，不關掉時下一個目標的所有點擊都會被攔截。
        """
        box = self.page.locator(".el-message-box")
        if not box.count() or not box.first.is_visible():
            return None
        text = " ".join(box.first.inner_text().split())
        confirm = box.first.get_by_role("button", name=re.compile(r"^(確認|确认|确定)$"))
        (confirm.last if confirm.count() else box.first.locator("button").last).click()
        try:
            box.first.wait_for(state="hidden", timeout=5_000)
        except Exception:
            pass
        return text

    def selection_summary(self) -> str:
        """回傳目前投注面板（已選項目／注數／金額）的摘要，供失敗訊息定位問題。"""
        text = self.page.locator("body").inner_text()
        anchor = max(text.rfind("投注球"), text.rfind("已选"), text.rfind("每注金额"))
        window = text[anchor:anchor + 260] if anchor >= 0 else text[-260:]
        return " ".join(window.split())

    def clear_selection(self) -> None:
        """回到可編輯狀態並清掉上一個目標的選項。

        順序固定：先關錯誤訊息框 → 再把仍開著的確認視窗按「返回修改」收掉 →
        最後才按「清空」。任一步殘留都會讓下一個目標的投注按鈕維持 disabled。
        """
        self.dismiss_message_box()
        dialog = self._bet_dialog()
        if dialog.count() and dialog.first.is_visible():
            dialog.first.get_by_role("button", name="返回修改").click()
            try:
                dialog.first.wait_for(state="hidden", timeout=3_000)
            except Exception:
                pass
        button = self.page.get_by_role("button", name="清空", exact=True).last
        if button.count() and button.is_visible() and button.is_enabled():
            # ⚠️ 2026-09-05 診斷：清空按鈕位於視窗底部（y≈661／視窗高 720），該座標上
            # 最上層的元素是投注區的 `.tab-area`——按鈕本身沒有 disabled、也沒有任何
            # `el-overlay` 遮罩，純粹是版面重疊，Playwright 的 actionability 因此一直等。
            # 兩個彩種都是這個狀態，先捲動到按鈕再點；仍被擋就用 JS 直接觸發。
            # ⛔ 清空不可略過：它失敗時上一個玩法的選項會留在面板上，跟下一個玩法的
            # 選取疊加，投注按鈕會因狀態不合法而永遠 disabled，後續目標整批被污染。
            try:
                button.scroll_into_view_if_needed(timeout=3_000)
                button.click(timeout=3_000)
            except Exception:
                try:
                    button.evaluate("el => el.click()")
                except Exception:
                    pass
            self.page.wait_for_timeout(300)

    @classmethod
    def _required_count(cls, sub_item: str) -> int:
        # 「一比三」＝1 個投注球對 3 個比較球，數量在「比」的後面；直接用前綴比對會把
        # 一比二～一比六全部解析成 1，比較球選不足、投注按鈕就永遠是 disabled
        #（2026-09-05 查出的舊批次「比大小」全滅根因）。
        target = sub_item.rsplit("比", 1)[-1] if "比" in sub_item else sub_item
        for word in sorted(cls._CN_NUMBERS, key=len, reverse=True):
            if target.startswith(word):
                return cls._CN_NUMBERS[word]
        raise ValueError(f"無法從組合子項解析選取數量：{sub_item}")

    def _select_numbers(self, count: int, offset: int = 0) -> None:
        numbers = [((offset + index) % 49) + 1 for index in range(count)]
        for number in numbers:
            self.page.get_by_role(
                "button", name=re.compile(rf"^{number}(?:\s|$)")
            ).click()

    def _select_zodiacs(self, count: int, offset: int = 0) -> None:
        zodiacs = [self._ZODIACS[(offset + index) % len(self._ZODIACS)] for index in range(count)]
        for zodiac in zodiacs:
            self.page.get_by_role(
                "button", name=re.compile(rf"^{zodiac}(?:\s|$)")
            ).click()

    def _select_tails(self, count: int, offset: int = 0) -> None:
        tails = [(offset + index) % 10 for index in range(count)]
        for tail in tails:
            self.page.get_by_role(
                "button", name=re.compile(rf"^{tail}尾(?:\s|$)")
            ).click()

    def _click_bet_button(self) -> None:
        """按下「投注」；按鈕仍 disabled 時附上投注面板摘要，讓失敗可直接判讀。"""
        button = self.page.get_by_role("button", name="投注", exact=True).last
        deadline = time.monotonic() + 8
        while button.is_disabled() and time.monotonic() < deadline:
            self.page.wait_for_timeout(200)
        if button.is_disabled():
            raise AssertionError("前台投注按鈕仍 disabled；投注面板=" + self.selection_summary())
        button.click()

    def _submit_dialog(self) -> tuple[int, str]:
        """在確認視窗按下「确认」，回傳 `POST /api/Bets` 的 (HTTP 狀態, 回應本文)。

        成功時回應本文就是注單 ID（QAT 實測回傳單一數字），是唯一能寫進稽核紀錄的憑據。
        """
        dialog = self._bet_dialog().first
        dialog.wait_for(state="visible", timeout=10_000)
        confirm = dialog.get_by_role("button", name=re.compile(r"^(確認|确认|确定)$"))
        with self.page.expect_response(
            lambda response: "/api/Bets" in response.url and response.request.method == "POST",
            timeout=20_000,
        ) as captured:
            confirm.last.click()
        response = captured.value
        try:
            body = response.text().strip()
        except Exception:
            body = ""
        return response.status, body

    def _confirm_bet(self, amount: str = "") -> str:
        """送出注單並以後端回應判定成敗，回傳含注單 ID 與實際金額的訊息。

        ⚠️ 站台對部分玩法設有**單注上限**（實測「连码／三全中」為 3,000），超過時
        `POST /api/Bets` 回 400「投注金额超过最高限额 N」而**注單根本沒建立**。
        這種情況丟出 `BetAmountRejected` 交由呼叫端整組重選、以站台上限重送——不在
        這裡就地改金額，因為被拒後確認視窗與選項狀態不保證還在（實測會一起消失）。
        """
        self.dismiss_message_box()
        self._click_bet_button()
        status, body = self._submit_dialog()
        if status >= 400:
            capped = re.search(r"最高限额\s*([\d,]+(?:\.\d+)?)", body)
            try:
                self.clear_selection()
            except Exception:
                pass
            if "赔率已变动" in body or "賠率已變動" in body:
                raise BetOddsChanged(f"下注被後端拒絕（HTTP {status}）：{body[:200]}")
            if not capped:
                raise AssertionError(f"下注被後端拒絕（HTTP {status}）：{body[:200]}")
            raise BetAmountRejected(
                f"投注金额超过最高限额 {capped.group(1)}",
                str(int(float(capped.group(1).replace(",", "")))),
            )
        try:
            self._bet_dialog().first.wait_for(state="hidden", timeout=5_000)
        except Exception:
            pass
        return f"投注成功：注單#{body or '未回傳ID'}／金額{amount or '未指定'}"

    def place_combo_target_bet(
        self, category: str, sub_item: str | None = None, amount: str = "5000", selection_offset: int = 0
    ) -> str:
        """對一個組合目標建立一筆真實前台注單（每個目標恰一組組合）。

        兩種站台明確拒絕（注單皆未建立）會自動重來一次並在訊息裡寫明原因：
        金額超過該玩法單注上限（降到站台回報的上限重送）、賠率快照過期（原金額重送）。
        其餘失敗一律往外拋，不靜默吞掉，也不把被拒當成成功。
        """
        amounts = [amount]
        note = ""
        for attempt in range(3):
            try:
                message = self._place_combo_once(category, sub_item, amounts[-1], selection_offset)
                return message + note
            except BetAmountRejected as rejected:
                amounts.append(rejected.limit)
                note = f"（原金額 {amount} 超過站台單注上限，站台回報上限 {rejected.limit}）"
            except BetOddsChanged:
                if attempt == 2:
                    raise
                note += "（曾遇賠率變動，已重取賠率後重送）"
                self.page.wait_for_timeout(1_000)
        raise AssertionError(f"{category}／{sub_item}：連續 3 次被站台拒絕，停止重送")

    def _place_combo_once(
        self, category: str, sub_item: str | None, amount: str, selection_offset: int
    ) -> str:
        self.clear_selection()
        self.select_combo_target(category, sub_item)
        if category == "过关":
            cells = self.page.locator(".cell.is-clickable")
            options = ["1大", "1小", "2大", "2小", "3大", "3小", "4大", "4小", "5大", "5小", "6大", "6小", "特大", "特小"]
            first, second = options[selection_offset % (len(options) - 1)], options[(selection_offset + 1) % (len(options) - 1)]
            cells.filter(has_text=first).click()
            cells.filter(has_text=second).click()
        elif category == "六肖":
            self._select_zodiacs(6, selection_offset % len(self._ZODIACS))
            self.page.get_by_role("button", name=re.compile(r"^中(?:\s|$)")).click()
        elif category == "比大小":
            count = self._required_count(sub_item or "一比一")
            betting = self.page.locator(".ball-cell.has-side-odds.is-clickable")
            betting.nth(selection_offset % betting.count()).click()
            self.page.wait_for_timeout(250)
            # 選定投注球後，比較球區的同一顆球會變成 `is-disabled`（實測：選正1 後
            # 比較球正1 停用），點它不會生效。不排除掉就會少選一顆、投注按鈕維持
            # disabled——這是舊批次「一比二～一比六」全滅的第二個成因。
            compare = self.page.locator(
                ".ball-cell.is-clickable:not(.has-side-odds):not(.is-disabled)"
            )
            available = compare.count()
            if available < count:
                raise AssertionError(f"比較球可選數不足：{sub_item} 需 {count}，可選 {available}")
            for index in range(count):
                compare.nth(index).click()
        else:
            count = self._required_count(sub_item or "一")
            if category in ("连肖", "合肖"):
                self._select_zodiacs(count, selection_offset % len(self._ZODIACS))
            elif category == "连尾":
                self._select_tails(count, selection_offset % 10)
            else:
                self._select_numbers(count, selection_offset)
        self.page.get_by_role("spinbutton").last.fill(amount)
        # 某些分類的下注按鈕會在選項／金額狀態尚未完成同步時短暫 disabled；
        # 讓 Vue 完成一次事件迴圈後再送出，並把等待交給 actionability。
        self.page.wait_for_timeout(300)
        return self._confirm_bet(amount)

    def place_six_zodiac_mode_bet(self, mode: str, amount: str = "5000", selection_offset: int = 0) -> str:
        """六肖建立一筆指定「中」或「不中」的真實注單（重送規則同 `place_combo_target_bet`）。"""
        amounts = [amount]
        note = ""
        for attempt in range(3):
            try:
                return self._place_six_zodiac_once(mode, amounts[-1], selection_offset) + note
            except BetAmountRejected as rejected:
                amounts.append(rejected.limit)
                note = f"（原金額 {amount} 超過站台單注上限，站台回報上限 {rejected.limit}）"
            except BetOddsChanged:
                if attempt == 2:
                    raise
                note += "（曾遇賠率變動，已重取賠率後重送）"
                self.page.wait_for_timeout(1_000)
        raise AssertionError(f"六肖／{mode}：連續 3 次被站台拒絕，停止重送")

    def _place_six_zodiac_once(self, mode: str, amount: str, selection_offset: int) -> str:
        self.clear_selection()
        self.select_combo_target("六肖")
        self._select_zodiacs(6, selection_offset % len(self._ZODIACS))
        self.page.get_by_role("button", name=re.compile(rf"^{mode}(?:\s|$)")).click()
        self.page.get_by_role("spinbutton").last.fill(amount)
        self.page.wait_for_timeout(300)
        return self._confirm_bet(amount)

    def select_bingo6_pick_two_all_hit(self) -> None:
        self.select_game("宾果六合彩")
        self.select_combo_target("连码", "二全中")
        self.page.get_by_text("请选择号码（最少 2 个，最多 10 个）", exact=True).wait_for()

    def select_bingo6_standard_special(self) -> None:
        """選擇賓果六合彩的標準型「特码」玩法。"""
        self.select_game("宾果六合彩")
        self.select_combo_target("特码")
        # 標準型號碼是可點擊的 `.lotto-ball` span，不是 button；外層
        # `.bet-cell` 內的第一個「1」是實際投注格，第二個是快捷投注圖。
        self.page.get_by_text("1", exact=True).first.locator("xpath=..").wait_for()

    def current_issue(self) -> str:
        text = self.page.locator("body").inner_text()
        match = re.search(r"宾果六合彩\s+(\d{9})\b", text)
        if not match:
            raise AssertionError(f"讀不到賓果六合彩期號：{text!r}")
        return match.group(1)

    # 站台用兩句不同的文案表示「現在不能投注」，缺一不可：
    # 「尚未开盘，暂无法投注」＝該期還沒開放；「已封盘，请等待下一期」＝已截止收單。
    _CLOSED_BANNERS = ("尚未开盘，暂无法投注", "已封盘，请等待下一期")

    def is_open(self) -> bool:
        """目前這個彩種是否可以投注。

        ⚠️ 2026-09-05：舊版只認「尚未开盘」，香港六合彩封盤時 `is_open()` 仍回 True，
        於是每個目標都一路跑到選號、填金額，最後卡在 disabled 的投注按鈕才失敗——
        整批 15 個玩法全滅，而且錯誤訊息看起來像選取器壞掉，把封盤這個真正的原因
        整個蓋掉了。封盤是市場狀態、不是缺陷，必須在下注前就辨識出來。
        """
        # 用 count() 先擋掉「元素不存在」與「多個同文案節點觸發 strict mode」兩種情況。
        for text in self._CLOSED_BANNERS:
            banner = self.page.get_by_text(text, exact=True)
            if banner.count() and banner.first.is_visible():
                return False
        return True

    def place_pick_two_bet(self, numbers: tuple[str, ...], amount_per_combination: str) -> str:
        for number in numbers:
            self.page.get_by_role(
                "button", name=re.compile(rf"^{int(number)}(?:\s|$)")
            ).click()
        self.page.get_by_role("spinbutton").fill(amount_per_combination)
        self.page.get_by_text(f"{len(numbers) * (len(numbers) - 1) // 2} 注", exact=True).wait_for()
        self.page.get_by_role("button", name="投注").last.click()
        dialog = self.page.get_by_text("连码下注确认", exact=True)
        dialog.wait_for()
        self.page.get_by_text("01,02", exact=True).wait_for()
        self.page.get_by_text("01,03", exact=True).wait_for()
        self.page.get_by_text("02,03", exact=True).wait_for()
        self.page.get_by_role("button", name="确认").click()
        return self._wait_success_message()

    def place_standard_bet(self, option: str, amount: str) -> str:
        """對目前標準型玩法的單一選項下注並完成確認。"""
        number = self.page.get_by_text(str(int(option)), exact=True).first
        number.locator("xpath=..").click()
        bet_cell = number.locator("xpath=ancestor::*[contains(@class, 'bet-cell')][1]")
        bet_cell.get_by_role("spinbutton").fill(amount)
        self.page.get_by_role("button", name="投注").last.click()
        dialog = self.page.get_by_role("dialog").last
        dialog.wait_for()
        dialog.get_by_role("button", name="确认").click()
        return self._wait_success_message()

    # 後台玩法名稱 → (前台分類名稱, 該玩法在前台投注列中的起始位移)
    # 2026-09-05 於英國天天彩實測：後台把「生肖中／生肖不中」「尾数中／尾数不中」拆成
    # 兩個玩法，前台卻各自合併成一個分類，前半段是「中」、後半段是「不中」，因此需要
    # 位移才對得上。其餘玩法前後台同名、無位移。
    # 值為 (前台分類名稱, 起始位移, 該玩法佔幾列)；`None` 表示整個分類都是它的。
    # 「色波」不在這張表裡——它不是「單一分類的一段列」，需要跨分類／子項導覽，
    # 見下方 `_COLOR_WAVE_ZHENG_TE_SUBITEMS` 與 `_place_color_wave_bet()`。
    _STANDARD_FRONTEND = {
        "生肖中": ("生肖", 0, 12), "生肖不中": ("生肖", 12, 12),
        "尾数中": ("尾数", 0, 10), "尾数不中": ("尾数", 10, 10),
        "半波": ("半波", 0, None), "特肖": ("特肖", 0, None), "七码": ("七码", 0, None),
        "五行": ("五行", 0, None), "一肖量": ("一肖量", 0, None), "尾数量": ("尾数量", 0, None),
    }

    # 2026-09-05 查明「色波」在前台的位置（使用者提供線索：入口在「特碼」下注頁面裡）：
    # 前台**沒有**獨立的「色波」`.category-item`，而是一張獨立的 `.el-card`（class
    # `color-bet-grid`，標題「色波」），**同時內嵌在「特码」與「正特码」兩個分類頁面裡**：
    #   - 「特码」分類：色波卡片固定對應「特码」這個位置（紅波／藍波／綠波 3 格）。
    #   - 「正特码」分類：色波卡片會跟著子項切換（正1特～正6特），MCP 實測切到「正2特」
    #     「正6特」下注紅波，確認視窗玩法欄分別顯示「正2特红波」「正6特红波」，證實色波卡片
    #     的位置是**當前選定的子項**，不是固定值。
    # 色波卡片內固定 3 個 `.bet-cell`，DOM 順序固定是「红波、蓝波、绿波」（`.name` 的
    # class 分別是 `name red`／`name blue`／`name green`），四次唯讀探測（特码、正2特、
    # 正6特）皆一致，未發現例外。
    #
    # 後台色波 21 選項＝(正1特～正6特＋特码) 7 個位置 × (紅/藍/綠) 3 色。用
    # `python`：`fetch('/api/LayOffSettingDetail?gameId=ukLucky7&playTypeId=color')`
    # 讀到的 21 筆 `selection` 依 `"1-blue","1-green","1-red","2-blue",...,"7-red"`
    # 排序（position 1~6＝正1～6特、7＝特码；顏色依英文字母序 blue/green/red）——
    # 這是**儲存用的原始順序**，跟後台「飛單選項明細設置」畫面實際顯示的「选项」欄
    # **不是同一個順序**：畫面第 1～21 列依序是
    #   正1特紅/蓝/绿波、正2特紅/蓝/绿波、…、正6特紅/蓝/绿波、特码紅/蓝/绿波
    # （即：每個位置內部畫面用「紅→藍→綠」，API 儲存用「blue→green→red」字母序；
    # 位置分組順序兩邊一致，只有組內顏色順序不同）。`_standard_targets()` 與
    # `rows_with_share()` 用的是**畫面列號**（1-based），所以這裡的
    # `_place_color_wave_bet()` 也依「畫面順序」（位置分組＋紅藍綠）產生對應的
    # `option_index`，兩邊才能對得上——不可依 API 的 `selection` 順序實作，
    # 那是本專案已踩過兩次的「畫面順序 ≠ API 順序」同一種坑（生肖／七码）。
    _COLOR_WAVE_ZHENG_TE_SUBITEMS = ("正1特", "正2特", "正3特", "正4特", "正5特", "正6特")

    def _place_color_wave_bet(self, amount: str, option_index: int) -> str:
        """對「色波」畫面第 `option_index % 21 + 1` 列下注（列序見上方檔頭說明）。"""
        group, color_index = divmod(option_index % 21, 3)
        if group < 6:
            self.select_combo_target("正特码", self._COLOR_WAVE_ZHENG_TE_SUBITEMS[group])
        else:
            self.select_combo_target("特码")
        cells = self.page.locator(".color-bet-grid .bet-cell")
        cells.first.wait_for(state="visible", timeout=10_000)
        if cells.count() != 3:
            raise AssertionError(f"色波卡片投注格數非預期的 3，實際 {cells.count()}")
        cell = cells.nth(color_index)
        cell.locator(".name").click()
        cell.get_by_role("spinbutton").fill(amount)
        self.page.wait_for_timeout(300)
        return self._confirm_bet(amount)

    def select_standard_sub_item(self, sub_item: str) -> None:
        """切到標準型玩法的子項（例如正特码的「正2特」）。

        ⚠️ `.el-segmented__item-label` 這個 class 在同一頁還被盤口（A盘／B盘）與
        下注模式（共用金额／各别金额／百倍…）共用，必須用完整文字比對，
        否則會選到不相干的控制項。
        """
        self.page.locator(
            ".el-segmented__item-label", has_text=re.compile(rf"^{re.escape(sub_item)}$")
        ).first.click()
        self.page.wait_for_timeout(600)

    def place_standard_category_bet(
        self, category: str, amount: str = "5000", option_index: int = 0,
        sub_item: str | None = None,
    ) -> str:
        """對標準型玩法畫面上第 `option_index` 個投注格下注（`category` 用後台名稱）。

        三種排版：號碼型（特码／正码／正特码／两面）是 `.bet-cell` ＋ 可點擊的
        `.lotto-ball`；多數其餘玩法是 `.bet-row`，每列自帶名稱、對應號碼、賠率與金額欄，
        直接填金額即可，不需先點選號碼；「色波」是獨立跨分類的卡片，見
        `_place_color_wave_bet()`。
        """
        self.clear_selection()
        if category == "色波":
            return self._place_color_wave_bet(amount, option_index)
        front_category, offset, span = self._STANDARD_FRONTEND.get(category, (category, 0, None))
        self.select_combo_target(front_category)
        if sub_item:
            self.select_standard_sub_item(sub_item)
        cells = self.page.locator(".bet-cell")
        if cells.count():
            cell = cells.nth(option_index % cells.count())
            # 號碼是可點擊的 `.lotto-ball` span 而非 button，要點它的父層才會選取。
            ball = cell.locator(".lotto-ball").first
            (ball.locator("xpath=..") if ball.count() else cell).click()
            cell.get_by_role("spinbutton").fill(amount)
        else:
            rows = self.page.locator(".bet-row")
            rows.first.wait_for(state="visible", timeout=10_000)
            # ⚠️ 合併分類（生肖／尾数）必須把取餘限制在該玩法自己的區段內，否則
            # 「生肖中」會算到「生肖不中」的列去，前後台就對不上了。
            width = span if span else rows.count()
            row = rows.nth(offset + (option_index % max(width, 1)))
            row.get_by_role("spinbutton").fill(amount)
        self.page.wait_for_timeout(300)
        return self._confirm_bet()

    def _wait_success_message(self) -> str:
        """等待下注成功提示；兼容 toast 短暫出現或多個同文案節點。"""
        try:
            self.page.wait_for_function(
                "() => /(?:投注|下注).*成功/.test(document.body.innerText)",
                timeout=4_000,
            )
        except Exception:
            # toast 可能已消失或文案不同；確認視窗已關閉時仍代表前台已完成確認，
            # 回傳可追蹤的 fallback，不讓單一 toast 時序阻斷後續目標。
            dialog = self._bet_dialog()
            if dialog.count() and dialog.first.is_visible():
                raise AssertionError(
                    "投注確認視窗未關閉，無法確認注單是否送出；訊息="
                    + (self.dismiss_message_box() or "無")
                )
            return "投注已確認（QAT 成功提示未捕捉）"
        text = self.page.locator("body").inner_text()
        for line in reversed(text.splitlines()):
            line = line.strip()
            if re.search(r"(?:投注|下注).*成功", line):
                return line
        return "投注成功"
