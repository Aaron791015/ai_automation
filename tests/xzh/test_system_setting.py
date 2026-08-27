# -*- coding: utf-8 -*-
"""公司層系統設置寫入案例（案例清單批次 B：B1～B6）。

✅ 2026-08-26 T9 實測確認：大表格（賠率設置／降賠設置／退水設置／投注限額）的
「點格→出現輸入框→填值→Enter」互動方式（`SystemSettingPage.set_table_cell`）是正確的。
唯一要注意的是找列要用 `filter(has_text=...)`，不能用 `get_by_role("row", name=regex)`
（後者對 row 的 accessible name 比對不準，會找不到明明存在的列）。

B5（飛單設置）仍待確認：「自動飛單」欄位的 accessible name 未知，見該案例的 skip 說明。
"""
from __future__ import annotations

import pytest

from xzh_qa.pages.system_setting_page import SystemSettingPage


def _cell_values(row_text: str) -> list[str]:
    """把 `table_row_text()` 讀到的整列文字拆成各欄位值。

    ⚠️ 實測發現這批表格的 `inner_text()` 是用 `\\n\\t\\n` 這類含 tab 的換行分隔儲存格，
    直接 `split("\\n")` 會夾雜純 tab 的空白項——過濾掉空白/純空白的項目才是真正的欄位值，
    索引才對得上 `set_table_cell` 的 `column_index`（0 是「玩法」欄本身，1 起才是數值欄）。
    """
    return [c for c in row_text.split("\n") if c.strip()]


@pytest.mark.write_action
def test_pass_bonus_cap_roundtrip(company_page):
    """B3：遊戲設置的過關彩金上限改值並保存 → 重新整理後仍是新值。

    ⚠️ 2026-08-26 真實前端 bug（網路攔截＋截圖＋使用者實機操作三方確認）：
    剛進「游戲設置」頁時，開盤/關盤時間與過關彩金上限欄位畫面空白（儘管
    `GET /api/GameSettings` 其實已經正確回傳資料），空白狀態按保存會送出空值、
    後端回 400。**確認過的解法**：切到別的彩種卡片再切回來，欄位就會正確顯示，
    保存也就正常——`ensure_fields_loaded()` 就是做這件事，見 `system_setting_page.py`
    檔頭的完整說明。這個 bug 本身待使用者裁示是否開單（見驗證交接 T10）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("游戏设置")
    sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
    original = sp.pass_bonus_cap()
    probe = "260000"
    sp.set_pass_bonus_cap(probe)
    sp.save()
    page.reload()
    sp.goto("游戏设置")
    sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
    assert sp.pass_bonus_cap() == probe

    sp.set_pass_bonus_cap(original)
    sp.save()


@pytest.mark.smoke
def test_bet_limit_table_visible(company_page):
    """B2 的前置：確認投注限額表格能讀到「两面」列（不編輯，先只驗證讀取到位）。"""
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("投注限额")
    assert "两面" in sp.table_row_text("两面")


@pytest.mark.write_action
def test_bet_limit_two_sides_cap_roundtrip(company_page):
    """B1：投注限額「两面」單注上限改值並保存 → 重新整理後仍是新值。

    ✅ 2026-08-26 實測確認：`set_table_cell` 的「點格→出現輸入框→填值→Enter」推測寫法是對的，
    先前失敗是 `table_row_text` 用 role name regex 找不到列（已改用 `filter(has_text=...)` 修正），
    不是編輯互動本身的問題。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("投注限额")
    original = sp.table_row_text("两面")
    sp.set_table_cell("两面", column_index=1, value="99999")
    sp.save()
    page.reload()
    sp.goto("投注限额")
    assert "99999" in sp.table_row_text("两面")

    # 還原（CLAUDE.md §5：測試資料用完即還原）
    orig_upper = _cell_values(original)[1 + 1]  # column_index=1 → 欄位索引 2（單注上限）
    sp.set_table_cell("两面", column_index=1, value=orig_upper)
    sp.save()


@pytest.mark.write_action
def test_rebate_rate_roundtrip(company_page):
    """B4：退水設置「特码A」盤口 A 的退水率改值並保存 → 重新整理後仍是新值。

    架構與投注限額相同（大表格點格編輯），B1 確認互動方式正確後比照實作。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("退水设置")
    original = sp.table_row_text("特码A")
    sp.set_table_cell("特码A", column_index=0, value="0.1000")
    sp.save()
    page.reload()
    sp.goto("退水设置")
    assert "0.1000" in sp.table_row_text("特码A")

    orig_a = _cell_values(original)[0 + 1]  # column_index=0 → 欄位索引 1（A 盤）
    sp.set_table_cell("特码A", column_index=0, value=orig_a)
    sp.save()


@pytest.mark.write_action
def test_odds_shortening_threshold_roundtrip(company_page):
    """B6：降賠設置「两面」的累計占成門檻改值並保存 → 重新整理後仍是新值。

    架構與投注限額相同（大表格點格編輯），B1 確認互動方式正確後比照實作。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("降赔设置")
    original = sp.table_row_text("两面")
    sp.set_table_cell("两面", column_index=0, value="99999")
    sp.save()
    page.reload()
    sp.goto("降赔设置")
    assert "99999" in sp.table_row_text("两面")

    orig_first = _cell_values(original)[0 + 1]  # column_index=0 → 欄位索引 1（累計占成）
    sp.set_table_cell("两面", column_index=0, value=orig_first)
    sp.save()


@pytest.mark.write_action
def test_lay_off_toggle(company_page):
    """B5：飛單設置「自動飛單」開關 roundtrip（讀原值→改值→保存→reload 驗證→改回原值）。

    ⚠️ 2026-08-26 更正先前的誤判：「自動飛單」在 QAT 現況下對全部 68 個玩法列皆為
    disabled，**不是環境整個鎖死，是與同列「開啟飛單選項明細設定」的互斥關係**——
    明細設定開著時鎖住自動飛單，關掉明細設定後自動飛單立刻可互動（已用 MCP 現場驗證可逆）。
    ✅ 使用者 2026-08-26 裁定：這是刻意設計，非缺陷（矩陣 K4／交接檔 T11 已關閉）。

    ⚠️⚠️ 「開啟飛單選項明細設定」的切換**單獨點擊時**不送 API（純前端狀態），但一旦按下
    「保存」，會跟該列其他欄位一起被送進 `PUT /api/LayOffSetting` 的
    `isSelectionDetailEnabled` 欄位——**只要為了解鎖而關過它、之後又按過保存，就已經
    把它寫進後端了**，不是切一切不點保存就沒事。已用網路攔截實測確認：關閉後保存，
    reload 後 GET 回應的 `isSelectionDetailEnabled` 真的變成 `false`。
    因此本案例每次為了解鎖而關閉明細設定、並確實按下保存之後，**都要在收尾用同樣的
    「關閉解鎖→操作→保存」流程把它救回來**，不能只是把 UI 切回去而不按保存。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("飞单设置")
    row = "特码"

    detail_mode_original = sp.is_lay_off_detail_mode_enabled(row)
    if not sp.is_auto_lay_off_toggleable(row):
        sp.set_lay_off_detail_mode(row, False)
    assert sp.is_auto_lay_off_toggleable(row), (
        "關掉「開啟飛單選項明細設定」後，「自動飛單」仍是 disabled——"
        "代表互斥假設不成立，或環境現況又變了，需要重新確認。"
    )

    original = sp.is_auto_lay_off_enabled(row)
    sp.toggle_auto_lay_off(row, not original)
    sp.save()
    page.reload()
    sp.goto("飞单设置")
    assert sp.is_auto_lay_off_enabled(row) == (not original)

    # 還原（CLAUDE.md §5：測試資料用完即還原）
    # ⚠️ 上面那次保存已經把「開啟飛單選項明細設定」一併存成 False（見上方 docstring）——
    # reload 後它仍是 False（不是自己跳回原值），所以這裡不必再另外關一次就能點「自動飛單」。
    sp.toggle_auto_lay_off(row, original)
    sp.save()
    page.reload()
    sp.goto("飞单设置")
    assert sp.is_auto_lay_off_enabled(row) == original

    # 最後才把「開啟飛單選項明細設定」真正救回原值，且必須按保存才會真的寫回後端。
    sp.set_lay_off_detail_mode(row, detail_mode_original)
    sp.save()
    page.reload()
    sp.goto("飞单设置")
    assert sp.is_lay_off_detail_mode_enabled(row) == detail_mode_original
