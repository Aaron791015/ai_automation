# -*- coding: utf-8 -*-
"""公司層「即时盘面」「敞口排行」Page Object（`/live-trading/overview`、`/live-trading/detail`）。

⚠️ 2026-10-05 選單改版（aaron02 唯讀實測，公司後台頂層選單為：用户管理／即时盘面／敞口排行／注单数据／
报表／跟单管理／开奖号码／操作日志／系统设置／个人资料／游戏规则）：舊的「即时操盘」頂層選單與它底下的
第二層選單已不存在，兩個子頁各自升為頂層選單，**網址不變**：
- 舊「即时操盘→盘面总览」（預設落地）→ 現頂層「**即时盘面**」＝`/live-trading/overview`（`goto()`）
- 舊「即时操盘→盘面明细」→ 現頂層「**敞口排行**」＝`/live-trading/detail`（`goto_detail()`）
（2026-08-28 曾實測到第二層選單「盘面总览」「盘面明细」；2026-09-29 起公司側選單已改名，見《UI元素對照》§5。）

「即时盘面」（原「盘面总览」）畫面結構：
- 玩法分類頁籤（特码／正码／正1特～正6特／连码／生尾／连肖／连尾／不中／中一／
  特平中／合肖／比大小／其他），各自帶目前的投注量徽章。
- 盘口切換（A 盘／B 盘／AB-A／AB-B）與 实货／虚货 切換。
- 賠率表格是 **一組欄位橫向重複排多組**，不是單一組欄位——讀值要先用完整字串比對「選項」儲存格，
  再取同一組內的賠率格。
- ⚠️ 2026-10-05 版面改版：「特码」等分類每組變成「序号／选项（球號）／赔率（含 −／＋ 按鈕）／占成…」，
  每列 4 組；「选项」前多了「序号」格，賠率格內是 `.odds-value`（兩側是 −／＋ 按鈕）。
  連肖／連尾等則是「选项（`span.sel-name`）／赔率／占成」。讀值一律走 `find_odds_for_option`
  （賠率格的前一格才是選項），不要再用「找名為選項的格子、取下一格」——會讀到球號。
"""
from __future__ import annotations

from typing import Optional

from playwright.sync_api import Page

#: 讀目前畫面所有「賠率格」及其「選項」（2026-10-05 版面改版後的通用讀法）。
#: 以表頭定位：表頭文字為「赔率」（或「公司赔率」）的那一欄是賠率欄，**它左邊那一欄才是「選項」**：
#:   - 特码／正码／其他等：序号｜选项（球號或 `span.sel-name`）｜赔率｜占成… → 左邊是選項（不是序号）
#:   - 连肖／连尾／合肖等：选项（`span.sel-name`）｜赔率｜占成 → 左邊就是選項
#: 賠率值取格內 `.odds-value`（有 −／＋ 按鈕的版面），沒有就取格內文字（純文字賠率，如沒有偏移鈕的代理盤面）。
#: 一列有多組欄位（橫向重複）時每一組都收；選項為空的補位組略過；只收可見格。
#: 讀不到表頭時退回：含 `.odds-value` 的格子，前一格是選項。
_BOARD_ENTRIES_JS = """() => {
  const text = el => (el ? el.innerText : '').trim();
  const visible = el => { const box = el.getBoundingClientRect(); return box.width > 0 && box.height > 0; };
  const roots = new Set();
  document.querySelectorAll('tbody tr').forEach(tr => {
    const root = tr.closest('.el-table') || tr.closest('table');
    if (root) roots.add(root);
  });
  const entries = [];
  roots.forEach(root => {
    const oddsCols = [...root.querySelectorAll('thead th')]
      .map((th, i) => (/^(公司)?赔率$/.test(text(th)) ? i : -1)).filter(i => i > 0);
    root.querySelectorAll('tbody tr').forEach(tr => {
      const cells = [...tr.children].filter(c => c.tagName === 'TD');
      if (oddsCols.length) {
        oddsCols.forEach(i => {
          const odds = cells[i], label = text(cells[i - 1]);
          if (!odds || !label || !visible(odds)) return;
          entries.push({label: label, odds: text(odds.querySelector('.odds-value') || odds)});
        });
      } else {
        cells.forEach((odds, i) => {
          const value = odds.querySelector('.odds-value');
          if (!value || i === 0 || !visible(odds)) return;
          entries.push({label: text(cells[i - 1]), odds: text(value)});
        });
      }
    });
  });
  return entries;
}"""


class LiveTradingPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> None:
        """導覽到頂層選單「即时盘面」（`/live-trading/overview`；原「即时操盘→盘面总览」，預設落地頁）。

        選單名稱用 `exact=True` 完全比對；點完等網址進到 `/live-trading/overview`，
        導覽失敗時在這裡就報錯，不要留給後面「讀不到賠率」去猜。
        """
        self.page.get_by_role("menuitem", name="即时盘面", exact=True).click()
        self.page.wait_for_url(lambda url: "/live-trading/overview" in url)
        self.page.wait_for_timeout(600)

    def goto_detail(self) -> None:
        """導覽到頂層選單「敞口排行」（`/live-trading/detail`；原「即时操盘→盘面明细」子頁面）。

        2026-10-05 實測：舊子頁升為頂層選單，網址仍是 `/live-trading/detail`，**不必先進「即时盘面」**。
        跟「即时盘面」的差異是表格排版：這頁是**單一組**欄位逐列列出
        （序号／选项／赔率／总盈亏／飞单／特码／特码单双…），分類頁籤第一個叫「特码汇总」，
        賠率格是純文字（沒有 −／＋ 按鈕）；「即时盘面」則是 4 組橫向並排、賠率格帶 −／＋ 按鈕。
        選項的數字寫法見下方 `odds_for_option` 說明（2026-10-05 實測為不補零的「1」）。
        """
        self.page.get_by_role("menuitem", name="敞口排行", exact=True).click()
        self.page.wait_for_url(lambda url: "/live-trading/detail" in url)
        self.page.wait_for_timeout(600)

    def find_odds_for_option(self, option: str) -> Optional[str]:
        """讀目前畫面某個選項（如「1」「红大」「蛇」）的賠率；畫面上沒有該選項回 None（不等待）。

        ⚠️ 2026-10-05 版面改版：「特码」等分類由「選項→賠率」改成「序号→球號→賠率（含 −／＋ 按鈕）」，
        舊寫法「找名為選項的格子、取下一格」會先命中「序号」格而讀到旁邊的球號（永遠讀成「1」）。
        現改為：以表頭定位「赔率」欄，取它**左邊那一欄**當選項（見 `_BOARD_ENTRIES_JS`；沒有表頭時退回
        「含 `.odds-value` 的格子、前一格是選項」），完整字串比對選項（避免「1」誤中「21」「41」），
        回傳該賠率格的值（有 −／＋ 按鈕的版面取 `.odds-value`，純文字賠率取格內文字）；
        同一選項在畫面上出現多次視為歧義，直接報錯，不取第一個。
        以上都讀不到任何賠率格（改版前、沒有表頭也沒有 `.odds-value` 的純文字版面）才退回舊讀法。
        """
        entries = self.page.evaluate(_BOARD_ENTRIES_JS)
        if entries:
            hits = [entry["odds"] for entry in entries if entry["label"] == option]
            assert len(hits) <= 1, f"盤面有 {len(hits)} 格選項「{option}」，無法判定要讀哪一格：{hits}"
            return hits[0] if hits else None
        cell = self.page.get_by_role("cell", name=option, exact=True)
        if not cell.count():
            return None
        return cell.first.locator("xpath=following-sibling::*[1]").inner_text().strip()

    def odds_for_option(self, option: str, timeout_ms: int = 15000) -> str:
        """讀目前畫面（「即时盘面」或「敞口排行」）表格裡某個選項（如「1」「大」「特码」對應的號碼）目前的賠率。

        ⚠️ 選項的數字寫法：2026-10-05 實測兩頁都是**不補零**的「1」「2」…（`选项` 格內是 `lotto-ball` 的 `.digits`）；
        2026-08-28 舊「盘面明细」曾是兩位數補零的「01」，現已不是——傳「01」會比對不到、等到逾時。

        讀值邏輯見 `find_odds_for_option`（含 2026-10-05 版面改版說明）。選項尚未出現時每 0.5 秒重讀，
        逾時仍找不到就丟 `AssertionError`（不回傳空值，避免把「讀不到」當成「賠率為空」）。
        """
        waited = 0
        while True:
            odds = self.find_odds_for_option(option)
            if odds is not None:
                return odds
            assert waited < timeout_ms, f"盤面 {timeout_ms} ms 內找不到選項「{option}」的賠率格"
            self.page.wait_for_timeout(500)
            waited += 500
