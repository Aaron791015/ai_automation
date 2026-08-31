# -*- coding: utf-8 -*-
"""公司層系統設置案例（案例清單批次 B：B1～B7；K4／K7 飛單案例 2026-08-31 已從零重新
設計並全面重編號為 B26～B54，17 個既有 pytest 函式的 docstring 首行已同步更新，
新舊編號對照見 `docs/新綜合/新綜合_案例清單.md` §0.1）。

「系统设置」底下有 8 個子選單，本檔現在全部覆蓋：游戏设置／投注限额／退水设置／
降赔设置／飞单设置（K4，B26～B36 系列，含寫入 roundtrip）／赔率设置／
飞单选项明细设置（K7，B37～B50 系列）／公告管理。

✅ 2026-08-26 T9 實測確認：大表格（賠率設置／降賠設置／退水設置／投注限額）的
「點格→出現輸入框→填值→Enter」互動方式（`SystemSettingPage.set_table_cell`）是正確的。
唯一要注意的是找列要用 `filter(has_text=...)`，不能用 `get_by_role("row", name=regex)`
（後者對 row 的 accessible name 比對不準，會找不到明明存在的列）。

⚠️ 2026-08-28 發現「飛單設置」頁的「最小飛單額」欄位持久化模式與其他大表格不同——
按 Enter 就即時送出 API，不需要按頁面下方的「保存」按鈕，見 B30（舊編號 B9）與
`SystemSettingPage.set_min_lay_off_amount` 的檔頭說明，不要誤用 `save()`。

⚠️ 2026-08-28「飛單選項明細設置」總開關（K7）與「飛單設置」（K4）父子連動已證實
（B37，舊編號 B11）：開啟 K7 總開關會跳確認框，明講「原系統設定－飛單設定中，飛單設定的金額將會
失效，並且自動出貨將變更為手動模式」——見 `LayOffDetailSettingPage` 檔頭說明。
"""
from __future__ import annotations

import allure
import pytest

from xzh_qa.pages.lay_off_detail_setting_page import LayOffDetailSettingPage
from xzh_qa.pages.system_setting_page import SystemSettingPage


def _cell_values(row_text: str) -> list[str]:
    """把 `table_row_text()` 讀到的整列文字拆成各欄位值。

    ⚠️ 實測發現這批表格的 `inner_text()` 是用 `\\n\\t\\n` 這類含 tab 的換行分隔儲存格，
    直接 `split("\\n")` 會夾雜純 tab 的空白項——過濾掉空白/純空白的項目才是真正的欄位值，
    索引才對得上 `set_table_cell` 的 `column_index`（0 是「玩法」欄本身，1 起才是數值欄）。
    """
    return [c for c in row_text.split("\n") if c.strip()]


@allure.suite("游戏设置")
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
    with allure.step("導覽到「游戏设置」頁，確保欄位已載入，記錄過關彩金上限原值"):
        sp.goto("游戏设置")
        sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
        original = sp.pass_bonus_cap()
    probe = "260000"
    with allure.step("改成探測值「260000」並保存，reload 後重讀"):
        sp.set_pass_bonus_cap(probe)
        sp.save()
        page.reload()
        sp.goto("游戏设置")
        sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
        after = sp.pass_bonus_cap()
    allure.attach(
        f"設定值：{probe!r}\n重整後實際讀到：{after!r}（期望：兩者相等）",
        name="過關彩金上限 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after == probe

    with allure.step("還原成進入案例前讀到的原值（CLAUDE.md §5：測試資料用完即還原）"):
        sp.set_pass_bonus_cap(original)
        sp.save()


@allure.suite("游戏设置")
@pytest.mark.write_action
def test_game_setting_open_close_time_roundtrip(company_page):
    """B24：遊戲設置「開盤時間」「關盤時間」欄位改值並保存 → 重新整理後仍是新值。

    ⚠️ 2026-08-29 實測：這兩顆是 Element Plus 時間選擇器（`combobox`），點擊會彈出
    時／分滾輪選單，**但不需要真的用滾輪選**——直接 `.fill("HH:MM:SS")` 再按 Enter
    就會被接受、彈窗自動關閉，跟其他一般表單欄位（如過關彩金上限）同一套操作方式；
    按頁面「保存」才持久化（不是 Enter 即時送出，這點跟「最小飛單額」不同）。

    步驟：
    1. 導覽到「游戏设置」頁，確保欄位已載入，記錄開盤/關盤時間原值
    2. 改成探測值（開盤 16:45:00／關盤 22:15:00）並保存，reload 後重讀
    3. 還原成原值並保存

    預期結果：改值並保存後，reload 仍是新值（B 級自檢不變量）
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「游戏设置」頁，確保欄位已載入，記錄開盤/關盤時間原值"):
        sp.goto("游戏设置")
        sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
        original_open = sp.opening_time()
        original_close = sp.closing_time()
    with allure.step("改成探測值（開盤 16:45:00／關盤 22:15:00）並保存，reload 後重讀"):
        sp.set_opening_time("16:45:00")
        sp.set_closing_time("22:15:00")
        sp.save()
        page.reload()
        sp.goto("游戏设置")
        sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
        after_open = sp.opening_time()
        after_close = sp.closing_time()
    allure.attach(
        f"開盤設定值：16:45:00，重整後實際：{after_open!r}\n"
        f"關盤設定值：22:15:00，重整後實際：{after_close!r}",
        name="開盤/關盤時間 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_open == "16:45:00"
    assert after_close == "22:15:00"

    with allure.step("還原成原值（CLAUDE.md §5）"):
        sp.set_opening_time(original_open)
        sp.set_closing_time(original_close)
        sp.save()
        page.reload()
        sp.goto("游戏设置")
        sp.ensure_fields_loaded("香港六合彩", "英国天天彩")
        assert sp.opening_time() == original_open
        assert sp.closing_time() == original_close


@allure.suite("投注限额")
@pytest.mark.smoke
def test_bet_limit_table_visible(company_page):
    """B2 的前置：確認投注限額表格能讀到「两面」列（不編輯，先只驗證讀取到位）。"""
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「投注限额」頁"):
        sp.goto("投注限额")
    with allure.step("讀取「两面」列文字"):
        row_text = sp.table_row_text("两面")
    allure.attach(
        f"該列實際文字：{row_text!r}（期望包含：两面）",
        name="投注限額「两面」列讀取",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "两面" in row_text


@allure.suite("投注限额")
@pytest.mark.write_action
def test_bet_limit_two_sides_cap_roundtrip(company_page):
    """B1：投注限額「两面」單注上限改值並保存 → 重新整理後仍是新值。

    ✅ 2026-08-26 實測確認：`set_table_cell` 的「點格→出現輸入框→填值→Enter」推測寫法是對的，
    先前失敗是 `table_row_text` 用 role name regex 找不到列（已改用 `filter(has_text=...)` 修正），
    不是編輯互動本身的問題。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「投注限额」頁，記錄「两面」列原值"):
        sp.goto("投注限额")
        original = sp.table_row_text("两面")
    with allure.step("把「两面」單注上限改成 99999 並保存，reload 後重讀"):
        sp.set_table_cell("两面", column_index=1, value="99999")
        sp.save()
        page.reload()
        sp.goto("投注限额")
        after = sp.table_row_text("两面")
    allure.attach(
        f"設定值：99999\n重整後實際該列文字：{after!r}（期望包含：99999）",
        name="投注限額「两面」單注上限 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "99999" in after

    # 還原（CLAUDE.md §5：測試資料用完即還原）
    with allure.step("還原成原值"):
        orig_upper = _cell_values(original)[1 + 1]  # column_index=1 → 欄位索引 2（單注上限）
        sp.set_table_cell("两面", column_index=1, value=orig_upper)
        sp.save()


@allure.suite("退水设置")
@pytest.mark.write_action
def test_rebate_rate_roundtrip(company_page):
    """B4：退水設置「特码A」盤口 A 的退水率改值並保存 → 重新整理後仍是新值。

    架構與投注限額相同（大表格點格編輯），B1 確認互動方式正確後比照實作。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「退水设置」頁，記錄「特码A」列原值"):
        sp.goto("退水设置")
        original = sp.table_row_text("特码A")
    with allure.step("把 A 盤退水率改成 0.1000 並保存，reload 後重讀"):
        sp.set_table_cell("特码A", column_index=0, value="0.1000")
        sp.save()
        page.reload()
        sp.goto("退水设置")
        after = sp.table_row_text("特码A")
    allure.attach(
        f"設定值：0.1000\n重整後實際該列文字：{after!r}（期望包含：0.1000）",
        name="退水設置「特码A」A 盤 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "0.1000" in after

    with allure.step("還原成原值"):
        orig_a = _cell_values(original)[0 + 1]  # column_index=0 → 欄位索引 1（A 盤）
        sp.set_table_cell("特码A", column_index=0, value=orig_a)
        sp.save()


@allure.suite("降赔设置")
@pytest.mark.write_action
def test_odds_shortening_threshold_roundtrip(company_page):
    """B6：降賠設置「两面」的累計占成門檻改值並保存 → 重新整理後仍是新值。

    架構與投注限額相同（大表格點格編輯），B1 確認互動方式正確後比照實作。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「降赔设置」頁，記錄「两面」列原值"):
        sp.goto("降赔设置")
        original = sp.table_row_text("两面")
    with allure.step("把累計占成門檻改成 99999 並保存，reload 後重讀"):
        sp.set_table_cell("两面", column_index=0, value="99999")
        sp.save()
        page.reload()
        sp.goto("降赔设置")
        after = sp.table_row_text("两面")
    allure.attach(
        f"設定值：99999\n重整後實際該列文字：{after!r}（期望包含：99999）",
        name="降賠設置「两面」累計占成門檻 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "99999" in after

    with allure.step("還原成原值"):
        orig_first = _cell_values(original)[0 + 1]  # column_index=0 → 欄位索引 1（累計占成）
        sp.set_table_cell("两面", column_index=0, value=orig_first)
        sp.save()


@allure.title("[功能驗證] B33：飛單設置「自動飛單」開關：切換並保存後應持久化生效")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_toggle(company_page):
    """B33｜功能驗證：飛單設置「自動飛單」開關 roundtrip（讀原值→改值→保存→reload 驗證→改回原值）。
    （2026-08-31 案例重編號：本案例併入互斥狀態機案例，舊編號 B5，見案例清單 §0.1）

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
    row = "特码"
    with allure.step("導覽到「飞单设置」頁，若「特码」列被鎖住則先關閉明細設定解鎖"):
        sp.goto("飞单设置")
        detail_mode_original = sp.is_lay_off_detail_mode_enabled(row)
        if not sp.is_auto_lay_off_toggleable(row):
            sp.set_lay_off_detail_mode(row, False)
        toggleable = sp.is_auto_lay_off_toggleable(row)
    allure.attach(
        f"實際：自動飛單 {'可互動' if toggleable else '仍是 disabled'}（期望：可互動）",
        name="自動飛單解鎖狀態",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert toggleable, (
        "關掉「開啟飛單選項明細設定」後，「自動飛單」仍是 disabled——"
        "代表互斥假設不成立，或環境現況又變了，需要重新確認。"
    )

    with allure.step("讀取「特码」自動飛單原值，切成相反值並保存，reload 後重讀"):
        original = sp.is_auto_lay_off_enabled(row)
        sp.toggle_auto_lay_off(row, not original)
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        after_toggle = sp.is_auto_lay_off_enabled(row)
    allure.attach(
        f"原值：{original}\n切換後設定：{not original}\n重整後實際：{after_toggle}（期望：與設定值相等）",
        name="自動飛單 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_toggle == (not original)

    # 還原（CLAUDE.md §5：測試資料用完即還原）
    # ⚠️ 上面那次保存已經把「開啟飛單選項明細設定」一併存成 False（見上方 docstring）——
    # reload 後它仍是 False（不是自己跳回原值），所以這裡不必再另外關一次就能點「自動飛單」。
    with allure.step("把「特码」自動飛單還原成進入案例前讀到的原值並保存，reload 後重讀"):
        sp.toggle_auto_lay_off(row, original)
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        assert sp.is_auto_lay_off_enabled(row) == original

    # 最後才把「開啟飛單選項明細設定」真正救回原值，且必須按保存才會真的寫回後端。
    with allure.step("把「特码」列的「開啟飛單選項明細設定」還原成進入案例前讀到的原值並保存，reload 後重讀"):
        sp.set_lay_off_detail_mode(row, detail_mode_original)
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        assert sp.is_lay_off_detail_mode_enabled(row) == detail_mode_original


@allure.title("[畫面驗證] B26：飛單設置表格結構：欄位／8 個分組／列數應與規格一致")
@allure.suite("飞单设置")
@pytest.mark.smoke
def test_lay_off_setting_table_structure(company_page):
    """B26｜畫面驗證：飛單設置表格結構性掃描——欄位齊全、8 個可收合分組都在、70 列都讀得到。
    （2026-08-31 案例重編號：舊編號 B16，見案例清單 §0.1）

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面
    2. 讀取表頭欄位、8 個分組收合按鈕、資料列總數

    預期結果：
    - 表頭 6 欄：玩法／自留口徑／每選項自留上限／自動飛單／最小飛單額／開啟飛單選項明細設定
    - 8 個分組（連碼／連肖／連尾／不中／多選中一／特平中／合肖／比大小）皆存在
    - 資料列數＝**70**（⚠️ 2026-08-28 本案例執行時用「cell 數＝6」的結構特徵精確計數才發現：
      先前文件與 B5 案例檔頭記錄的「68 個玩法列」是誤算，已一併更正相關文件，見交接檔 T17）

    oracle 來源：B 級（regression baseline，2026-08-28 結構性複掃時清點）。
    本案例只驗結構完整，不驗每列數值與狀態——那些見 B8～B10。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→飞单设置」子頁面"):
        sp.goto("飞单设置")
    headers = ("玩法", "自留口径", "每选项自留上限", "自动飞单", "最小飞单额", "开启飞单选项明细设定")
    with allure.step("讀取表頭 6 欄位（玩法／自留口径／每选项自留上限／自动飞单／最小飞单额／开启飞单选项明细设定）、8 個分組收合按鈕（连码／连肖／连尾／不中／多选中一／特平中／合肖／比大小）、資料列總數"):
        header_visible = {h: page.get_by_role("columnheader", name=h, exact=True).is_visible() for h in headers}
        groups = sp.group_toggle_labels()
        row_count = sp.row_count()
    allure.attach(
        f"表頭實際：{header_visible}（期望：全部 True）\n"
        f"分組實際：{groups}\n"
        f"列數實際：{row_count}（期望：70）",
        name="飛單設置表格結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    for header, visible in header_visible.items():
        assert visible, f"表頭「{header}」未找到"
    for name in ("连码", "连肖", "连尾", "不中", "多选中一", "特平中", "合肖", "比大小"):
        assert any(name in g for g in groups), f"分組「{name}」未找到，實際：{groups}"
    assert row_count == 70, f"預期 70 列玩法，實際 {row_count} 列"


@allure.title("[邏輯驗證] B36-1：飛單設置逐列解鎖獨立性：只應影響操作列，其餘列不受連動影響")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_row_unlock_is_isolated(company_page):
    """B36-1｜邏輯驗證：抽樣「两面」列驗證解鎖是逐列獨立、不誤動其他列。
    （2026-08-31 案例重編號：舊編號 B8，見案例清單 §0.1）

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面
    2. 記錄「特码」列（未操作對象）目前的鎖定狀態
    3. 關閉「两面」列的「開啟飛單選項明細設定」→ 讀取「两面」列的自動飛單／自留上限是否解鎖
    4. 重新讀取「特码」列狀態，確認未被連動改變
    5. 還原「两面」列

    預期結果：
    - 「两面」列解鎖後：自動飛單可互動、自留上限變可編輯
    - 「特码」列全程不受影響（正反向兩問：該動的動了／不該動的沒被動到）

    oracle 來源：B 級（依 2026-08-28 發現的 `一比五`／`一比六` 例外反推的假說，
    本案例即為驗證手段——見矩陣 K4、交接檔 T17）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→飞单设置」子頁面，記錄「特码」列（未操作對象）目前的鎖定狀態"):
        sp.goto("飞单设置")
        control_before = sp.is_auto_lay_off_toggleable("特码")
    assert control_before is False, "前置假設：「特码」列應處於鎖定狀態，若已解鎖代表環境現況已變"

    with allure.step("關閉「两面」列的「開啟飛單選項明細設定」→ 讀取自動飛單／自留上限是否解鎖"):
        sp.set_lay_off_detail_mode("两面", False)
        toggleable = sp.is_auto_lay_off_toggleable("两面")
        cap_editable = sp.is_cap_editable("两面")
    with allure.step("重新讀取「特码」列狀態，確認未被連動改變"):
        control_after = sp.is_auto_lay_off_toggleable("特码")
    allure.attach(
        f"「两面」解鎖後：自動飛單可互動={toggleable}、自留上限可編輯={cap_editable}（期望：皆 True）\n"
        f"「特码」操作前={control_before}、操作後={control_after}（期望：不變）",
        name="逐列解鎖獨立性",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert toggleable is True
    assert cap_editable is True
    assert control_after == control_before, "「特码」列不該被「两面」列的操作連動影響"

    # 還原（CLAUDE.md §5：測試資料用完即還原；本切換純前端，不需要 save()）
    with allure.step("還原「两面」列"):
        sp.set_lay_off_detail_mode("两面", True)
        assert sp.is_auto_lay_off_toggleable("两面") is False


@allure.title("[功能驗證] B30：飛單設置「最小飛單額」欄位邊界值：負數應拒絕、超大值應接受並即時持久化")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_min_amount_boundary(company_page):
    """B30｜功能驗證：測試「特码」列的「最小飛單額」輸入框，填負數是否可以成功保存、
    （2026-08-31 案例重編號：舊編號 B9，見案例清單 §0.1）
    填超大值是否可以成功保存。

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面，記錄「特码」列「最小飛單額」原值
    2. 填入負數 -5 → Enter → 點畫面「保存」按鈕 → reload，確認有沒有成功保存
    3. 填入超大值 999999999 → Enter → 點畫面「保存」按鈕 → reload，確認有沒有成功保存
    4. 還原為原值

    預期結果：
    - 負數：不可保存成功——reload 後仍是原值
    - 超大值：可成功保存——reload 後是新值

    ⚠️⚠️ 2026-08-31 補充驗證（明確測「點畫面保存按鈕」這個動作，並用網路攔截確認）：
    這欄是 Enter 即時持久化——**Enter 當下就已經送出 PUT**（合法值時 payload 帶著新值、
    204 成功；輸入負數這種非法值時，前端已把畫面打回原值，Enter 送出的 PUT payload
    是空陣列 `{"settings": []}`，等於沒有變更可送）。**額外點擊頁面「保存」按鈕不會
    改變結果**——因為 Enter 已經把「有沒有變更」這件事處理掉了，保存按鈕再點一次送出的
    PUT 一律是空陣列。這正是 POM 檔頭原本寫「不需要也不可以再按頁面保存」的真正原因：
    不是按了會出錯，是按了本來就不會有任何效果——本案例把這個動作也做一次，用實測
    證明「按不按保存，結果都一樣」，不是只憑推論。

    oracle 來源：B 級（2026-08-28 MCP 三方確認＋2026-08-31 補測「點保存按鈕」、
    並用網路攔截比對兩種情境下 PUT payload 的差異）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→飞单设置」子頁面，記錄「特码」列「最小飛單額」原值"):
        sp.goto("飞单设置")
        original = sp.min_lay_off_amount("特码")

    with allure.step("填入負數 -5 → Enter → 點畫面「保存」按鈕 → reload"):
        after_negative = sp.set_min_lay_off_amount("特码", "-5")
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        persisted_negative = sp.min_lay_off_amount("特码")
    allure.attach(
        f"填入：-5\nEnter 後畫面顯示：{after_negative!r}\n點保存＋reload 後實際：{persisted_negative!r}"
        f"（期望：{original!r}，即輸入負數不可保存成功）",
        name="最小飛單額負數邊界 => 輸入負數不可保存成功",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert persisted_negative == original, "輸入負數不應該保存成功，reload 後應維持原值"

    with allure.step("填入超大值 999999999 → Enter → 點畫面「保存」按鈕 → reload"):
        after_large = sp.set_min_lay_off_amount("特码", "999999999")
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        persisted_large = sp.min_lay_off_amount("特码")
    allure.attach(
        f"填入：999999999\nEnter 後畫面顯示：{after_large!r}\n點保存＋reload 後實際：{persisted_large!r}"
        "（期望：999999999，即輸入超大值可成功保存）",
        name="最小飛單額超大值持久化 => 輸入超大值可成功保存",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert persisted_large == "999999999", "輸入超大值應該保存成功"

    # 還原（CLAUDE.md §5）
    with allure.step("把「特码」的「最小飛單額」還原成進入案例前讀到的原值，點保存後 reload 確認"):
        sp.set_min_lay_off_amount("特码", original)
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        assert sp.min_lay_off_amount("特码") == original


@allure.title("[邏輯驗證] B28子集：飛單設置異常列復原：一比五／一比六重新鎖定後狀態應與其餘列一致")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_anomaly_rows_can_relock(company_page):
    """（2026-08-31 案例重編號：舊編號 B10，現為 B28「環境健康度基線」涵蓋範圍內的子集
    ——B28 掃描全部 70 列的一致鎖定狀態，本案例聚焦的 `一比五`／`一比六` 兩列已包含在內；
    保留本案例是因為它額外驗證「鎖不回去就視為非可逆殘留」這個更明確的失敗訊息，見案例清單 §0.1）
    邏輯驗證：追查 `一比五`／`一比六` 目前的「解鎖」狀態能否復原。

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面
    2. 讀取 `一比五`／`一比六` 兩列目前的鎖定狀態
    3. 若目前是解鎖狀態，將其「開啟飛單選項明細設定」重新開啟
    4. 讀取兩列是否恢復成與其餘 66 列一致的鎖定狀態

    預期結果：
    - 開啟明細設定後，兩列的自動飛單應變回 disabled、自留上限應變回不可編輯
    - 若鎖不回去，代表這不是可逆操作造成的殘留，需回頭在交接檔 T17 記錄並提高優先度

    oracle 來源：B 級（同 B8 假說：明細設定與鎖定狀態應是一致的因果關係）。
    ⚠️ 本案例**不假設**兩列目前的起始狀態一定是解鎖——先讀值，再決定要不要操作，
    這樣重跑也不會因為前一輪已經鎖回去而失敗。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→飞单设置」子頁面，依序處理 2 個異常列：一比五、一比六"):
        sp.goto("飞单设置")

    for row in ("一比五", "一比六"):
        with allure.step(f"讀取「{row}」目前鎖定狀態，若解鎖則重新開啟明細設定"):
            was_unlocked = sp.is_auto_lay_off_toggleable(row)
            if was_unlocked:
                sp.set_lay_off_detail_mode(row, True)
            toggleable = sp.is_auto_lay_off_toggleable(row)
            cap_editable = sp.is_cap_editable(row)
        allure.attach(
            f"「{row}」操作前解鎖={was_unlocked}；操作後：自動飛單可互動={toggleable}、"
            f"自留上限可編輯={cap_editable}（期望：兩者皆 False）",
            name=f"{row} 是否可重新鎖回",
            attachment_type=allure.attachment_type.TEXT,
        )
        assert toggleable is False, f"「{row}」列鎖不回去——非可逆殘留，需更新交接檔 T17"
        assert cap_editable is False, f"「{row}」列自留上限鎖不回去——非可逆殘留，需更新交接檔 T17"


@allure.title("[邏輯驗證] B36-2：飛單設置可收合分組成員一致性：鎖定／解鎖機制應與頂層列相同")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_group_members_lock_unlock_consistency(company_page):
    """B36-2｜邏輯驗證：8 個可收合分組（連碼／連肖／連尾／不中／多選中一／特平中／合肖／比大小）裡的成員，
    （2026-08-31 案例重編號：舊編號 B23，見案例清單 §0.1）
    鎖定/解鎖機制是否跟頂層列（B8 已驗的「两面」）一致。

    ⚠️ K4 表格的 70 列裡，有一大塊（連碼展開後的二全中/二中特…等）先前只在 K7
    （飛單選項明細設置）驗過對應玩法的組合型 UI，**在 K4 這張表自己的鎖定/解鎖機制
    是否一致從未逐一確認**——「比大小」的 `一比五`／`一比六` 已在 B10 驗過，
    本案例補其餘 7 個分組各挑一個代表成員（分層抽樣，§6）。

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面
    2. 對每個代表成員：讀取鎖定狀態原值 → 關閉明細設定解鎖 → 確認自動飛單/自留上限變可編輯
       → 重新開啟明細設定鎖回 → 確認兩者變回不可編輯

    預期結果：
    - 7 個代表成員（連碼／連肖／連尾／不中／多選中一／特平中／合肖 各一）的解鎖-鎖回行為
      跟頂層列完全一致，沒有任何分組成員是例外
    """
    page = company_page
    sp = SystemSettingPage(page)
    samples = {
        "连码": "二全中",
        "连肖": "二肖连中",
        "连尾": "二尾连中",
        "不中": "五不中",
        "多选中一": "五中一",
        "特平中": "一粒任中",
        "合肖": "二合肖中",
    }
    with allure.step("導覽到「系统设置→飞单设置」子頁面，依序處理 7 個分組代表成員：连码→二全中、连肖→二肖连中、连尾→二尾连中、不中→五不中、多选中一→五中一、特平中→一粒任中、合肖→二合肖中"):
        sp.goto("飞单设置")

    for group, member in samples.items():
        with allure.step(f"分組「{group}」代表成員「{member}」：解鎖 → 確認可編輯 → 鎖回 → 確認不可編輯"):
            detail_original = sp.is_lay_off_detail_mode_enabled(member)
            sp.set_lay_off_detail_mode(member, False)
            unlocked_toggleable = sp.is_auto_lay_off_toggleable(member)
            unlocked_cap_editable = sp.is_cap_editable(member)
            sp.set_lay_off_detail_mode(member, detail_original)
            relocked_toggleable = sp.is_auto_lay_off_toggleable(member)
            relocked_cap_editable = sp.is_cap_editable(member)
        allure.attach(
            f"分組「{group}」成員「{member}」：解鎖後 toggleable={unlocked_toggleable}、"
            f"cap_editable={unlocked_cap_editable}；鎖回後 toggleable={relocked_toggleable}、"
            f"cap_editable={relocked_cap_editable}（期望：解鎖皆 True、鎖回皆 False）",
            name=f"{group}/{member} 解鎖-鎖回一致性",
            attachment_type=allure.attachment_type.TEXT,
        )
        assert unlocked_toggleable is True, f"「{member}」解鎖後自動飛單仍不可互動"
        assert unlocked_cap_editable is True, f"「{member}」解鎖後自留上限仍不可編輯"
        assert relocked_toggleable is False, f"「{member}」鎖不回去——分組成員與頂層列行為不一致"
        assert relocked_cap_editable is False, f"「{member}」自留上限鎖不回去——分組成員與頂層列行為不一致"


@allure.title("[邏輯驗證] B31＋B35：飛單設置「每選項自留上限」欄位耦合陷阱：Enter 送出會一併持久化明細設定鎖定狀態")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_cap_value_boundary(company_page):
    """B31＋B35｜邏輯驗證：「每選項自留上限」欄位邊界值——負數應被拒絕（打回 0）、超大值應被接受並即時持久化。
    （2026-08-31 案例重編號：舊編號 B25，拆為「自留上限邊界值」B31 與「整列持久化陷阱」B35
    兩個新案例，本函式的內容同時涵蓋兩者，見案例清單 §0.1）

    ⚠️⚠️ 2026-08-29 實測發現的重要陷阱（見 `SystemSettingPage.set_cap_value` 檔頭）：
    這欄要先解鎖（關閉「開啟飛單選項明細設定」）才能編輯，而**編輯後 Enter 送出的 API
    是整列資料**，會把當下「明細設定＝解鎖」的狀態也一併持久化——光把開關切回「鎖定」
    不會生效（那是純前端切換，不送 API），**必須搭配再對同一列做一次「最小飛單額」的
    Enter（哪怕值不變）才能把鎖回的狀態真正寫回後端**。本案例的收尾步驟就是照這個
    程序做，不能只呼叫 `set_lay_off_detail_mode`。

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面，抽樣「过关」列（頂層、非「两面」避免跟 B8/B9
       共用同一列造成互相干擾），解鎖後記錄自留上限原值
    2. 填入負數 `-10` → Enter，讀取畫面顯示值
    3. 填入超大值 `777777` → Enter → reload 頁面 → 讀取持久化後的值
    4. 還原自留上限為原值，並用「正確的收尾鎖回程序」確保明細設定真的鎖回

    預期結果：
    - 負數：前端拒絕，Enter 後打回 **0**（不是打回原值——`el-input-number` 的 min=0 邊界，
      跟「最小飛單額」欄位「打回原值」的行為不同）
    - 超大值：前端接受，reload 後仍是新值（這欄按 Enter 即時持久化，不需按頁面保存）
    """
    page = company_page
    sp = SystemSettingPage(page)
    row = "过关"
    with allure.step("導覽到「系统设置→飞单设置」子頁面，解鎖「过关」列，記錄自留上限原值"):
        sp.goto("飞单设置")
        detail_original = sp.is_lay_off_detail_mode_enabled(row)
        sp.set_lay_off_detail_mode(row, False)
        original_cap = sp.cap_value(row)

    with allure.step("填入負數 -10 → Enter，讀取畫面顯示值"):
        after_negative = sp.set_cap_value(row, "-10")
    allure.attach(
        f"填入：-10\nEnter 後畫面顯示：{after_negative!r}（期望：打回 0，不是打回原值 {original_cap!r}）",
        name=f"{row} 自留上限負數邊界",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_negative == "0", "負數應被前端拒絕並打回 0（el-input-number min 邊界）"

    with allure.step("填入超大值 777777 → Enter → reload → 讀取持久化後的值"):
        after_large = sp.set_cap_value(row, "777777")
        page.reload()
        sp.goto("飞单设置")
        persisted = sp.cap_value(row)
    allure.attach(
        f"填入：777777\nEnter 後畫面顯示：{after_large!r}\nreload 後持久化值：{persisted!r}（期望：777777）",
        name=f"{row} 自留上限超大值持久化",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_large == "777777"
    assert persisted == "777777", "超大值應已即時持久化到後端"

    with allure.step("還原自留上限為原值，並用「最小飛單額」Enter 把明細設定鎖回狀態一併持久化"):
        sp.set_cap_value(row, original_cap)
        sp.set_lay_off_detail_mode(row, detail_original)
        sp.set_min_lay_off_amount(row, sp.min_lay_off_amount(row))
        page.reload()
        sp.goto("飞单设置")
        assert sp.cap_value(row) == original_cap
        assert sp.is_lay_off_detail_mode_enabled(row) == detail_original, (
            f"「{row}」明細設定沒有真正鎖回——確認是否漏了「最小飛單額」那次 Enter"
        )


def _put_lay_off_setting(page, game_id: str, play_type_id: str, **fields) -> int:
    """繞過 UI，直接對 `PUT /api/LayOffSetting` 送出指定欄位（B32 前端擋 vs 後端擋驗證用）。

    用 `localStorage.accessToken` 的 Bearer token 認證，與前端實際送出的方式一致
    （2026-08-31 MCP 探索確認 key 名稱是 `accessToken`，不是其他產品慣用的 `jwtToken`）。
    回傳 HTTP 狀態碼。
    """
    return page.evaluate(
        """async ([gameId, playTypeId, fields]) => {
            const token = localStorage.getItem('accessToken');
            const res = await fetch('/api/LayOffSetting', {
                method: 'PUT',
                headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
                body: JSON.stringify({gameId, settings: [{playTypeId, ...fields}]}),
            });
            return res.status;
        }""",
        [game_id, play_type_id, fields],
    )


def _get_lay_off_setting_row(page, game_id: str, play_type_id: str) -> dict:
    """繞過 UI，直接 `GET /api/LayOffSetting` 讀取指定玩法列的完整欄位（B32 用）。"""
    return page.evaluate(
        """async ([gameId, playTypeId]) => {
            const token = localStorage.getItem('accessToken');
            const res = await fetch(`/api/LayOffSetting?gameId=${gameId}`, {
                headers: {Authorization: `Bearer ${token}`},
            });
            const data = await res.json();
            return data.find(r => r.playTypeId === playTypeId);
        }""",
        [game_id, play_type_id],
    )


def _get_lay_off_setting_detail(page, game_id: str, play_type_id: str) -> list[dict]:
    """繞過 UI，直接 `GET /api/LayOffSettingDetail` 讀取指定分類的完整選項清單（B65 用）。"""
    return page.evaluate(
        """async ([gameId, playTypeId]) => {
            const token = localStorage.getItem('accessToken');
            const res = await fetch(`/api/LayOffSettingDetail?gameId=${gameId}&playTypeId=${playTypeId}`, {
                headers: {Authorization: `Bearer ${token}`},
            });
            return await res.json();
        }""",
        [game_id, play_type_id],
    )


def _put_lay_off_setting_detail(page, game_id: str, play_type_id: str, items: list[dict], **extra) -> int:
    """繞過 UI，直接對 `PUT /api/LayOffSettingDetail` 送出指定 items（B65 前端擋 vs 後端擋驗證用）。

    回傳 HTTP 狀態碼。`extra` 通常帶 `triggerImmediateAutoLayOff`（見 B15/B52 前台真生效系列）。
    """
    return page.evaluate(
        """async ([gameId, playTypeId, items, extra]) => {
            const token = localStorage.getItem('accessToken');
            const body = Object.assign({gameId, playTypeId, items}, extra || {});
            const res = await fetch('/api/LayOffSettingDetail', {
                method: 'PUT',
                headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
            return res.status;
        }""",
        [game_id, play_type_id, items, extra],
    )


@allure.title("[功能驗證] B63：飛單選項明細設置標準型「每選項自留上限」欄位邊界值：負數應拒絕、超大值應接受並持久化")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_standard_type_cap_boundary(company_page):
    """B63：標準選項清單型「每選項自留上限」欄位邊界值——負數／超大值行為是否跟 K4 同名
    欄位（B31）一致（2026-08-31 審查 K7 案例覆蓋率時發現的缺口，見 testcase-design §5③）。

    ⚠️ 這是本次審查 K7 案例時發現的缺口：K7 這個欄位先前（B43）只做過 roundtrip（正常值
    1234/555/888），從未測過邊界值——K4 的同名欄位（B31）早已測過負數打回 0、超大值持久化，
    K7 完全沒對照過。2026-08-31 MCP 實測已確認行為與 K4 一致，本案例把它固化成回歸測試。

    步驟：
    1. 導覽到飛單選項明細設置頁，開啟總開關（前提：欄位才可編輯，見 B43），切到「特码」分類，
       記錄選項 1 的自留上限原值
    2. 填入負數 -10 → Enter，讀取畫面顯示值 → 點保存 → reload，確認持久化結果
    3. 填入超大值 888888 → Enter → 點保存 → reload，確認持久化結果
    4. 還原選項 1 自留上限為原值，還原總開關為原狀

    預期結果：
    - 負數：前端拒絕，打回 **0**（`el-input-number` min 邊界，同 K4「每選項自留上限」B31，
      不是打回原值）
    - 超大值：前端接受，reload 後仍是新值
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    row = 1
    with allure.step("導覽到飛單選項明細設置頁，開啟總開關，切到「特码」分類，記錄選項 1 自留上限原值"):
        sp.goto()
        master_original = sp.is_master_switch_enabled()
        if not master_original:
            sp.set_master_switch(True)
        sp.select_category("特码")
        original_cap = sp.option_cap_value(row)

    with allure.step("填入負數 -10 → Enter → 保存 → reload"):
        sp.set_option_cap(row, "-10")
        after_negative = sp.option_cap_value(row)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("特码")
        persisted_negative = sp.option_cap_value(row)
    allure.attach(
        f"填入：-10\nEnter 後畫面顯示：{after_negative!r}（期望打回 0）\n"
        f"保存＋reload 後實際：{persisted_negative!r}（期望 0，與 K4「每選項自留上限」B31 一致）",
        name="標準型自留上限負數邊界",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_negative == "0", "負數應被前端拒絕並打回 0"
    assert persisted_negative == "0", "負數保存後應仍是 0"

    with allure.step("填入超大值 888888 → Enter → 保存 → reload"):
        sp.set_option_cap(row, "888888")
        after_large = sp.option_cap_value(row)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("特码")
        persisted_large = sp.option_cap_value(row)
    allure.attach(
        f"填入：888888\nEnter 後畫面顯示：{after_large!r}\n保存＋reload 後實際：{persisted_large!r}（期望 888888）",
        name="標準型自留上限超大值持久化",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_large == "888888"
    assert persisted_large == "888888", "超大值應成功持久化"

    with allure.step("還原選項 1 自留上限為原值，還原總開關為原狀"):
        sp.set_option_cap(row, original_cap)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("特码")
        assert sp.option_cap_value(row) == original_cap
        sp.set_master_switch(master_original)
        assert sp.is_master_switch_enabled() == master_original


@allure.title("[功能驗證] B64：飛單選項明細設置組合型「共用自留上限」欄位邊界值：負數應拒絕、超大值應接受並持久化")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_type_shared_cap_boundary(company_page):
    """B64：組合型「共用自留上限」欄位邊界值——負數／超大值行為是否跟標準型（B63）與
    K4 同名欄位（B31）一致（2026-08-31 審查 K7 案例覆蓋率時發現的缺口）。

    ⚠️ 缺口同 B63：組合型「共用自留上限」（B47/B48）先前只做過 roundtrip（正常值
    777/555/333），從未測過邊界值。2026-08-31 MCP 實測確認行為與標準型一致。

    步驟：
    1. 導覽到飛單選項明細設置頁，切到「比大小」分類（預設子項「一比一」），確保至少一項
       「選擇」勾選（避免零勾選陷阱，見 B49），記錄共用自留上限原值
    2. 填入負數 -15 → 讀取畫面顯示值 → 保存 → reload，確認持久化結果
    3. 填入超大值 666666 → 保存 → reload，確認持久化結果
    4. 還原共用自留上限與勾選狀態為原值

    預期結果：
    - 負數：前端拒絕，打回 **0**（同標準型 B63、K4 B31）
    - 超大值：前端接受，reload 後仍是新值
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「比大小」分類，確保至少一項已勾選，記錄共用自留上限原值"):
        sp.goto()
        sp.select_category("比大小")
        original_marked = sp.combo_item_marked(0)
        if not original_marked:
            sp.set_combo_item_marked(0, True)
        original_cap = sp.shared_cap_value()

    with allure.step("填入負數 -15 → 保存 → reload"):
        sp.set_shared_cap("-15")
        after_negative = sp.shared_cap_value()
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("比大小")
        persisted_negative = sp.shared_cap_value()
    allure.attach(
        f"填入：-15\n填入後畫面顯示：{after_negative!r}（期望打回 0）\n"
        f"保存＋reload 後實際：{persisted_negative!r}（期望 0）",
        name="組合型共用自留上限負數邊界",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_negative == "0", "負數應被前端拒絕並打回 0"
    assert persisted_negative == "0", "負數保存後應仍是 0"

    with allure.step("填入超大值 666666 → 保存 → reload"):
        sp.set_shared_cap("666666")
        after_large = sp.shared_cap_value()
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("比大小")
        persisted_large = sp.shared_cap_value()
    allure.attach(
        f"填入：666666\n填入後畫面顯示：{after_large!r}\n保存＋reload 後實際：{persisted_large!r}（期望 666666）",
        name="組合型共用自留上限超大值持久化",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_large == "666666"
    assert persisted_large == "666666", "超大值應成功持久化"

    with allure.step("還原共用自留上限與勾選狀態為原值"):
        sp.set_shared_cap(original_cap)
        sp.set_combo_item_marked(0, original_marked)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("比大小")
        assert sp.shared_cap_value() == original_cap
        assert sp.combo_item_marked(0) == original_marked


@allure.title("[邏輯驗證] B65：飛單選項明細設置：繞過 UI 直打 API 驗證後端是否也擋負數自留上限")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_backend_rejects_negative_cap(company_page):
    """B65：前端擋 vs 後端擋——K4 有 B32 繞過 UI 驗證 `/api/LayOffSetting` 的後端契約，
    K7 對應的 `/api/LayOffSettingDetail` 從未做過等價測試（2026-08-31 審查 K7 案例覆蓋率
    時發現的缺口，見 testcase-design §5④）。

    ⚠️ B63 只證明前端會擋負數。若後端照單全收，任何能直打 API 的途徑都能寫入非法值。

    步驟：
    1. 導覽到飛單選項明細設置頁建立登入 session，繞過 UI 讀取「特码」選項 1 原值
    2. 繞過 UI 直接 PUT 負數自留上限（-999）
    3. 繞過 UI 直接 PUT 超大值（999999999），確認後端與前端行為一致（接受）
    4. 還原「特码」選項 1 自留上限為原值

    預期結果：
    - 負數：後端應拒絕（狀態碼 ≥400），資料維持原值未被寫壞
    - 超大值：後端應接受（204／200），資料成功寫入

    oracle 來源：延伸 B32 的結論；直接讀 API 回應，A 級。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    game_id, play_type_id = "markSix", "bonusNumber"
    with allure.step("導覽到飛單選項明細設置頁建立登入 session，繞過 UI 讀取「特码」選項 1 原值"):
        sp.goto()
        rows = _get_lay_off_setting_detail(page, game_id, play_type_id)
        original = next(r for r in rows if r["selection"] == "01")

    with allure.step("繞過 UI 直接 PUT 負數自留上限（-999）"):
        neg_item = dict(original)
        neg_item["retentionCap"] = -999
        status_negative = _put_lay_off_setting_detail(
            page, game_id, play_type_id, [neg_item], triggerImmediateAutoLayOff=False
        )
        rows_after_negative = _get_lay_off_setting_detail(page, game_id, play_type_id)
        after_negative = next(r for r in rows_after_negative if r["selection"] == "01")
    allure.attach(
        f"負數 PUT 回應狀態碼：{status_negative}（期望：≥400，代表後端拒絕）\n"
        f"送出前原值：{original['retentionCap']}\n送出後實際值：{after_negative['retentionCap']}"
        "（期望：維持原值，未被寫壞）",
        name="後端負數邊界驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert status_negative >= 400, f"預期後端拒絕負數自留上限，實際狀態碼 {status_negative}"
    assert after_negative["retentionCap"] == original["retentionCap"], "負數請求雖被拒絕，但資料疑似已被寫壞"

    with allure.step("繞過 UI 直接 PUT 超大值（999999999），確認後端與前端行為一致（接受）"):
        large_item = dict(original)
        large_item["retentionCap"] = 999999999
        status_large = _put_lay_off_setting_detail(
            page, game_id, play_type_id, [large_item], triggerImmediateAutoLayOff=False
        )
        rows_after_large = _get_lay_off_setting_detail(page, game_id, play_type_id)
        after_large = next(r for r in rows_after_large if r["selection"] == "01")
    allure.attach(
        f"超大值 PUT 回應狀態碼：{status_large}（期望：200，接受）\n"
        f"送出後實際值：{after_large['retentionCap']}（期望：999999999）",
        name="後端超大值邊界驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert status_large == 200
    assert after_large["retentionCap"] == 999999999

    with allure.step("還原「特码」選項 1 自留上限為原值"):
        restore_status = _put_lay_off_setting_detail(
            page, game_id, play_type_id, [original], triggerImmediateAutoLayOff=False
        )
        assert restore_status == 200
        rows_final = _get_lay_off_setting_detail(page, game_id, play_type_id)
        final = next(r for r in rows_final if r["selection"] == "01")
        assert final["retentionCap"] == original["retentionCap"]


@allure.title("[邏輯驗證] B66：飛單選項明細設置：批次工具反向驗證——不應誤動其他分類")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_batch_tools_do_not_affect_other_categories(company_page):
    """B66：批次工具「一鍵自動」只驗證了「特码」分類內樣本被改動（B44），從未驗證過
    「其他分類（如正码）沒被誤動」（2026-08-31 審查 K7 案例覆蓋率時發現的缺口，
    見 testcase-design §5②「正向 vs 反向」）。

    步驟：
    1. 導覽到飛單選項明細設置頁，切到「正码」分類（控制組），記錄抽樣選項 1/25/49 原值
    2. 切到「特码」分類，點「一鍵自動」
    3. 切回「正码」分類，重新讀取同三個選項，確認未被連動改變
    4. 還原「特码」分類為操作前狀態

    預期結果：
    - 「正码」分類的抽樣選項在「特码」分類執行批次操作前後應**完全不變**
      （批次工具的作用範圍應僅限當下選定的分類）

    oracle 來源：B 級（自檢不變量，批次操作理應只影響當下分類，屬 §5② 反向驗證）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    sample = (1, 25, 49)
    with allure.step("導覽到飛單選項明細設置頁，切到「正码」分類（控制組），記錄抽樣選項原值"):
        sp.goto()
        sp.select_category("正码")
        control_before = {n: sp.option_auto_lay_off_enabled(n) for n in sample}

    with allure.step("切到「特码」分類，點「一鍵自動」"):
        sp.select_category("特码")
        sp.click_batch_auto()

    with allure.step("切回「正码」分類，重新讀取同三個選項，確認未被連動改變"):
        sp.select_category("正码")
        control_after = {n: sp.option_auto_lay_off_enabled(n) for n in sample}
    allure.attach(
        f"「正码」分類操作前：{control_before}\n「特码」執行「一鍵自動」後「正码」實際：{control_after}"
        "（期望：與操作前完全相同，不受影響）",
        name="批次工具跨分類隔離性",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert control_after == control_before, "「特码」分類的批次操作不應影響「正码」分類"

    with allure.step("還原「特码」分類為操作前狀態（點「一鍵手動」）"):
        sp.select_category("特码")
        sp.click_batch_manual()


@allure.title("[畫面驗證] B67：飛單選項明細設置：總開關對組合型欄位可編輯性的影響（決策表延伸）")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_master_switch_effect_on_combo_fields(company_page):
    """B67：B43 發現「總開關關閉時**標準型**每選項自留上限變唯讀」，但**組合型**（共用自留
    上限／关连不关连／選擇）是否受同一個總開關約束，從未驗證過（2026-08-31 審查 K7 案例
    覆蓋率時發現的缺口，見 testcase-design §5⑧ 決策表）。

    ⚠️⚠️ 2026-08-31 MCP 實測發現：**不受約束，兩種類型的耦合程度不同**——總開關關閉時，
    組合型「比大小」分類的「共用自留上限」欄位、「关连」radio、「選擇」checkbox
    **全部維持可互動**（`disabled` 屬性不存在），跟標準型「每選項自留上限」變唯讀（B43）
    的行為不一致。不判定為缺陷（沒有規格文件說兩者該一致），純記錄現況供之後有規格依據
    時重新判斷，比照 B38／B14 的 D 級快照處理方式。

    步驟：
    1. 導覽到飛單選項明細設置頁，關閉總開關（不跳確認框，立即生效）
    2. 切到「比大小」分類，讀取「共用自留上限」欄位、「关连」radio、「選擇」checkbox
       是否為 disabled
    3. 還原總開關為原狀

    預期結果：現況記錄（D 級快照），不預設「應該」一致或「應該」不一致——留給之後有
    規格依據時再判斷是否為刻意設計差異
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，關閉總開關"):
        sp.goto()
        master_original = sp.is_master_switch_enabled()
        if master_original:
            sp.set_master_switch(False)
        assert sp.is_master_switch_enabled() is False

    with allure.step("切到「比大小」分類，讀取共用自留上限／关连radio／選擇checkbox 是否為 disabled"):
        sp.select_category("比大小")
        shared_cap_disabled = page.get_by_role("spinbutton", name="共用自留上限").get_attribute("disabled") is not None
        relation_disabled = page.get_by_role("radio", name="关连", exact=True).get_attribute("disabled") is not None
        checkbox_disabled = page.get_by_role("checkbox").nth(0).get_attribute("disabled") is not None
    allure.attach(
        f"總開關關閉時，組合型「比大小」分類：\n"
        f"共用自留上限 disabled={shared_cap_disabled}\n关连 radio disabled={relation_disabled}\n"
        f"選擇 checkbox disabled={checkbox_disabled}\n"
        "（現況記錄：三者皆為 False，即維持可互動，與標準型「每選項自留上限」在同一情境下"
        "變唯讀的行為不一致——B43 vs 本案例的耦合程度不同，非缺陷判斷，純記錄現況）",
        name="總開關對組合型欄位可編輯性影響（D 級快照）",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert shared_cap_disabled is False, (
        "現況應為可互動——如重現本案例卻發現變 disabled，代表行為已改變，需要重新檢討"
        "本案例的記錄與交接檔的說明"
    )
    assert relation_disabled is False
    assert checkbox_disabled is False

    with allure.step("還原總開關為原狀"):
        sp.set_master_switch(master_original)
        assert sp.is_master_switch_enabled() == master_original


@allure.title("[畫面驗證] B27：飛單設置三彩種結構比對：列數／分組／鎖定列數是否一致")
@allure.suite("飞单设置")
@pytest.mark.smoke
def test_lay_off_setting_cross_game_structure(company_page):
    """B27：飛單設置在英國天天彩／賓果六合彩的結構快照，與香港六合彩對照（2026-08-31 從零設計新增）。

    ⚠️ 全新軸線——先前所有飛單案例只跑在預設彩種（香港六合彩）上，機制文件 §5.2 明寫
    系統設置 8 個子選單「皆依目前選中的彩種分別設定」，另兩彩種的飛單資料從沒被看過。

    ⚠️⚠️ 2026-08-31 探索結果（重大發現，比照矩陣 K2 的處理方式，記錄現況不預設對錯）：
    三彩種**玩法列數皆為 70**（組成一致），但**鎖定列數差異極大**——
    香港六合彩 70/70、英國天天彩 6/70、賓果六合彩 13/70；且**只有香港六合彩有 8 個
    可收合分組按鈕**，另兩彩種完全沒有分組 UI。這跟 K2（賠率 B~I 盤全 0）是同一種訊號，
    已回報使用者裁定是否為環境資料缺口（見矩陣 K4、交接檔）。本案例只斷言玩法列數一致
    （這是規格層級的不變量），鎖定列數與分組數只記錄不斷言，避免案例隨環境現況跳動。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「飞单设置」頁（預設香港六合彩），記錄結構基準"):
        sp.goto("飞单设置")
        hk_rows = sp.row_count()
        hk_groups = sp.group_toggle_labels()
        hk_locked = sp.locked_row_count()
    with allure.step("切到英國天天彩，記錄同一組結構數據"):
        sp.switch_game("英国天天彩")
        uk_rows = sp.row_count()
        uk_groups = sp.group_toggle_labels()
        uk_locked = sp.locked_row_count()
    with allure.step("切到賓果六合彩，記錄同一組結構數據"):
        sp.switch_game("宾果六合彩")
        bg_rows = sp.row_count()
        bg_groups = sp.group_toggle_labels()
        bg_locked = sp.locked_row_count()
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")
    allure.attach(
        f"香港六合彩：{hk_rows} 列／{len(hk_groups)} 分組／{hk_locked}/{hk_rows} 列鎖定\n"
        f"英國天天彩：{uk_rows} 列／{len(uk_groups)} 分組／{uk_locked}/{uk_rows} 列鎖定\n"
        f"賓果六合彩：{bg_rows} 列／{len(bg_groups)} 分組／{bg_locked}/{bg_rows} 列鎖定\n"
        "（期望：列數皆為 70——玩法組成三彩種應相同；鎖定列數與分組數為 D 級現況快照，"
        "不預設對錯，比照矩陣 K2 處理，待使用者裁定是否為環境資料缺口）",
        name="K4 三彩種結構比對",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert hk_rows == 70 and uk_rows == 70 and bg_rows == 70, (
        "三彩種的玩法列數應一致（皆為 70）——如不同代表玩法組成本身有差異，需另外調查"
    )


@allure.title("[畫面驗證] B28：飛單設置環境健康度基線：70 列應全數一致鎖定，無解鎖殘留")
@allure.suite("飞单设置")
@pytest.mark.smoke
def test_lay_off_setting_no_residual_unlocked_rows(company_page):
    """B28：掃描全部 70 列，確認沒有「明細設定已開啟但自留上限/自動飛單仍解鎖」的不一致列。

    ⚠️ 這是所有 K4 write_action 案例的前置：2026-08-28 曾有 `一比五`／`一比六` 兩列
    處於解鎖殘留狀態（成因見 B35 的整列持久化陷阱），不先掃描就跑行為案例會誤判。
    2026-08-31 實測：目前環境乾淨，70/70 列一致鎖定。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「飞单设置」頁，掃描全部列的鎖定狀態"):
        sp.goto("飞单设置")
        total = sp.row_count()
        locked = sp.locked_row_count()
    allure.attach(
        f"總列數：{total}\n一致鎖定列數：{locked}（期望：{total}，即全數鎖定，無殘留解鎖列）",
        name="環境健康度基線",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert locked == total, (
        f"發現 {total - locked} 列處於解鎖狀態，需先用正確鎖回程序清乾淨，"
        "才能進行後續 write_action 案例（見 B35 收尾程序）"
    )


@allure.title("[邏輯驗證] B29：飛單設置：「保存」按鈕能否持久化「開啟飛單選項明細設定」的切換")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_detail_mode_persists_via_save_button(company_page):
    """B29：解鎖某列後不碰任何其他欄位，直接按「保存」，reload 後是否維持解鎖。

    ⚠️⚠️ 2026-08-31 解決機制文件與 POM 的矛盾（見交接檔 T20）：機制文件 §5.2 說「按保存時
    會與該列其他欄位一併寫入」；`set_cap_value()` 檔頭卻說鎖回只能靠「對最小飛單額再
    Enter 一次」，全程沒提保存按鈕。**實測證實機制文件是對的**——保存按鈕確實能持久化
    「開啟飛單選項明細設定」的當下狀態，不需要額外對其他欄位做 Enter。整列持久化其實
    有兩條路徑都通：①按保存；②對任一 Enter-即時持久化欄位做 Enter（後者見 B35）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    row = "特码"
    with allure.step("導覽到「飞单设置」頁，解鎖「特码」列"):
        sp.goto("飞单设置")
        original = sp.is_lay_off_detail_mode_enabled(row)
        sp.set_lay_off_detail_mode(row, not original)

    with allure.step("不碰任何其他欄位，直接按「保存」，reload 後重讀"):
        sp.save()
        page.wait_for_timeout(500)
        page.reload()
        sp.goto("飞单设置")
        after = sp.is_lay_off_detail_mode_enabled(row)
    allure.attach(
        f"原值：{original}\n切換設定：{not original}\n只按保存、reload 後實際：{after}"
        f"（期望：{not original}，證實保存按鈕本身就能持久化本欄位）",
        name="保存按鈕對明細設定持久化驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after == (not original), "保存按鈕未能持久化「開啟飛單選項明細設定」——與機制文件記載不符"

    with allure.step("還原「特码」為原值並保存"):
        sp.set_lay_off_detail_mode(row, original)
        sp.save()
        page.wait_for_timeout(500)
        page.reload()
        sp.goto("飞单设置")
        assert sp.is_lay_off_detail_mode_enabled(row) == original


@allure.title("[邏輯驗證] B34：飛單設置：反向驗證「純前端切換不送 API」——不按保存直接 reload 應復原")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_detail_mode_toggle_alone_reverts_on_reload(company_page):
    """B34：切換「開啟飛單選項明細設定」後不做任何持久化動作，reload 應恢復原狀。

    ⚠️ 這個假設是 B29／B35 與整套收尾程序的地基，先前只在 POM 檔頭寫「切換當下沒有
    任何 API 請求送出」，卻從未反向驗證過「不送 API＝reload 會恢復」這個推論本身。
    2026-08-31 實測確認成立。不需要還原（reload 已自動復原，沒有任何殘留）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    row = "正码"
    with allure.step("導覽到「飞单设置」頁，切換「正码」列明細設定但不保存"):
        sp.goto("飞单设置")
        original = sp.is_lay_off_detail_mode_enabled(row)
        sp.set_lay_off_detail_mode(row, not original)

    with allure.step("不按保存，直接 reload，重讀狀態"):
        page.reload()
        sp.goto("飞单设置")
        after = sp.is_lay_off_detail_mode_enabled(row)
    allure.attach(
        f"原值：{original}\n切換後（未保存）：{not original}\n"
        f"reload 後實際：{after}（期望：{original}，證實純前端切換不送 API）",
        name="純前端切換 reload 復原驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after == original, (
        "reload 後未恢復原狀——切換本身可能其實有持久化途徑，需重新檢討 B29/B35 的收尾程序"
    )


@allure.title("[邏輯驗證] B32：飛單設置：繞過 UI 直接打 API 驗證後端是否也擋負數自留上限")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_setting_backend_rejects_negative_cap(company_page):
    """B32：前端擋 vs 後端擋——UI 邊界值測試（B31）只證明前端會擋負數，從未驗證過繞過 UI
    直接打 API 時後端契約是否也擋。若後端照單全收，任何能直打 API 的途徑都能寫入非法值。

    ⚠️⚠️ 2026-08-31 實測結論：**後端確實有擋**——送負數觸發 500（`FluentValidation`
    拋出未處理例外，不是乾淨的 400，屬前端錯誤處理待改善但不影響「有沒有擋住」的判準）；
    超大值後端接受（204），與前端行為一致，無資料完整性缺口。
    """
    page = company_page
    sp = SystemSettingPage(page)
    game_id, play_type_id, row = "markSix", "bonusNumber", "特码"
    with allure.step("導覽到「飞单设置」頁建立登入 session，讀取「特码」原值"):
        sp.goto("飞单设置")
        original = _get_lay_off_setting_row(page, game_id, play_type_id)

    common_fields = {
        "isAutoEnabled": original["isAutoEnabled"],
        "minLayOffAmount": original["minLayOffAmount"],
        "isSelectionDetailEnabled": original["isSelectionDetailEnabled"],
    }

    with allure.step("繞過 UI 直接 PUT 負數自留上限（-999）"):
        status_negative = _put_lay_off_setting(page, game_id, play_type_id, retentionCap=-999, **common_fields)
        after_negative = _get_lay_off_setting_row(page, game_id, play_type_id)
    allure.attach(
        f"負數 PUT 回應狀態碼：{status_negative}（期望：≥400，代表後端拒絕）\n"
        f"送出前原值：{original['retentionCap']}\n送出後實際值：{after_negative['retentionCap']}"
        "（期望：維持原值，未被寫壞）",
        name="後端負數邊界驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert status_negative >= 400, f"預期後端拒絕負數自留上限，實際狀態碼 {status_negative}"
    assert after_negative["retentionCap"] == original["retentionCap"], "負數請求雖被拒絕，但資料疑似已被寫壞"

    with allure.step("繞過 UI 直接 PUT 超大值（999999999），確認後端與前端行為一致（接受）"):
        status_large = _put_lay_off_setting(page, game_id, play_type_id, retentionCap=999999999, **common_fields)
        after_large = _get_lay_off_setting_row(page, game_id, play_type_id)
    allure.attach(
        f"超大值 PUT 回應狀態碼：{status_large}（期望：204，接受）\n"
        f"送出後實際值：{after_large['retentionCap']}（期望：999999999）",
        name="後端超大值邊界驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert status_large == 204
    assert after_large["retentionCap"] == 999999999

    with allure.step("還原「特码」自留上限為原值"):
        restore_status = _put_lay_off_setting(
            page, game_id, play_type_id, retentionCap=original["retentionCap"], **common_fields
        )
        assert restore_status == 204
        restored = _get_lay_off_setting_row(page, game_id, play_type_id)
        assert restored["retentionCap"] == original["retentionCap"]


# ============================================================================
# B55~B59：飛單設置（K4）三彩種延伸（2026-08-31 從零設計新增，見案例清單 §0.2）
#
# ⚠️ 抽樣依據：B27 已發現三彩種鎖定列數落差極大（香港六合彩 70/70、英國天天彩 6/70、
# 賓果六合彩 13/70），推翻了「三彩種共用同一份資料結構」這個先前用來收斂 B28~B36 功能層
# 測試範圍的假設——那批案例全部只在預設彩種（香港六合彩）驗過。依 `testcase-design` §6
# 「抽樣依據可證偽」規則，回頭把功能層展開到另兩彩種，即本節 B55~B59。
#
# 樣本列挑選依據 2026-08-31 探索記錄（交接檔 T29）：「特码」在香港/英國/賓果三彩種皆為
# 已鎖定列，「尾数中」／「过关」／「正码」在英國/賓果皆為已解鎖列，跨彩種共用同一組樣本名稱。
# ============================================================================


@allure.title("[畫面驗證] B55：飛單設置：非預設彩種環境健康度基線（狀態自洽，不要求全部鎖定）")
@allure.suite("飞单设置")
@pytest.mark.smoke
def test_lay_off_setting_non_default_games_consistency(company_page):
    """B55：英國天天彩／賓果六合彩各掃描全部 70 列，確認「明細設定開⇄自留上限唯讀＋自動飛單
    disabled」「明細設定關⇄兩者皆可互動」的一致性是否跟香港六合彩（B28）一樣成立。

    ⚠️ 這兩個彩種**不能沿用 B28 的「locked_row_count()==total」判準**——B27 已發現鎖定列數
    落差極大（香港六合彩 70/70、英國天天彩 6/70、賓果六合彩 13/70），多數列本來就是解鎖
    狀態。本案例改用更寬鬆但仍嚴謹的判準：不管該列目前鎖定或解鎖，兩個受「開啟飛單選項明細
    設定」連動的欄位（自動飛單、每選項自留上限）有沒有互相同步（`consistent_row_count()`）。

    步驟：
    1. 導覽到「飞单设置」頁，切到英國天天彩，掃描全部列的狀態自洽性
    2. 切到賓果六合彩，掃描全部列的狀態自洽性
    3. 切回香港六合彩（還原彩種選取狀態）

    預期結果：
    - 兩個彩種的「狀態自洽列數」皆應等於總列數（70）——即使多數列是解鎖狀態，
      解鎖也該是「兩個連動欄位都變成可互動」的乾淨解鎖，不是半解鎖的不一致狀態

    oracle 來源：B 級（自檢不變量，與 B28 同一套邏輯，只是放寬「鎖定為多數」的假設）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「飞单设置」頁，切到英國天天彩，掃描全部列的狀態自洽性"):
        sp.goto("飞单设置")
        sp.switch_game("英国天天彩")
        uk_consistent, uk_total = sp.consistent_row_count()
    with allure.step("切到賓果六合彩，掃描全部列的狀態自洽性"):
        sp.switch_game("宾果六合彩")
        bg_consistent, bg_total = sp.consistent_row_count()
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")
    allure.attach(
        f"英國天天彩：{uk_consistent}/{uk_total} 列狀態自洽（期望 {uk_total}）\n"
        f"賓果六合彩：{bg_consistent}/{bg_total} 列狀態自洽（期望 {bg_total}）",
        name="非預設彩種環境健康度基線",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert uk_consistent == uk_total, f"英國天天彩有 {uk_total - uk_consistent} 列狀態不自洽"
    assert bg_consistent == bg_total, f"賓果六合彩有 {bg_total - bg_consistent} 列狀態不自洽"


@allure.title("[邏輯驗證] B56：飛單設置：非預設彩種互斥狀態機 roundtrip（已鎖定列＋已解鎖列各一）")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_setting_non_default_games_mutex_roundtrip(company_page):
    """B56：英國天天彩／賓果六合彩各挑一個「已解鎖」列＋一個「已鎖定」列，驗證明細設定開↔關
    切換時自動飛單／自留上限是否遵循跟香港六合彩（B33）同一套互斥規則。

    ⚠️ 樣本挑選依據 B55 探索記錄：「特码」在兩個彩種都是**已鎖定**列，「尾数中」在兩個彩種
    都是**已解鎖**列（見交接檔 T29），因此兩彩種共用同一組樣本名稱。

    步驟（每個彩種、每個樣本列各跑一次）：
    1. 導覽到「飞单设置」頁，切到目標彩種，記錄樣本列的明細設定原始狀態
    2. 切換明細設定為相反狀態 → 讀取自動飛單是否可互動、自留上限是否可編輯
    3. 切回原始狀態 → 確認自動飛單／自留上限恢復原本的可互動性

    預期結果：
    - 明細設定切到「開」：自動飛單應變不可互動、自留上限應變不可編輯
    - 明細設定切到「關」：自動飛單應變可互動、自留上限應變可編輯
    - 這套互斥規則在英國天天彩／賓果六合彩應與香港六合彩（B33）一致

    oracle 來源：沿用 B33 已建立的 A 級事實（互斥為刻意設計）作對照基準，本案例驗證是否
    在其他彩種也成立。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("飞单设置")
    samples = ("特码", "尾数中")
    report_lines = []
    for game in ("英国天天彩", "宾果六合彩"):
        with allure.step(f"切到{game}"):
            sp.switch_game(game)
        for row in samples:
            with allure.step(f"{game}／「{row}」：切換明細設定為相反狀態，驗證互斥後再切回原狀"):
                original = sp.is_lay_off_detail_mode_enabled(row)
                sp.set_lay_off_detail_mode(row, not original)
                toggled_toggleable = sp.is_auto_lay_off_toggleable(row)
                toggled_cap_editable = sp.is_cap_editable(row)
                sp.set_lay_off_detail_mode(row, original)
                restored_toggleable = sp.is_auto_lay_off_toggleable(row)
                restored_cap_editable = sp.is_cap_editable(row)
            report_lines.append(
                f"{game}／{row}：原始明細設定={original}；切換後 auto可互動={toggled_toggleable}、"
                f"cap可編輯={toggled_cap_editable}；切回後 auto可互動={restored_toggleable}、"
                f"cap可編輯={restored_cap_editable}"
            )
            assert toggled_toggleable == original, f"{game}／{row} 切換明細設定後互斥規則不成立（自動飛單）"
            assert toggled_cap_editable == original, f"{game}／{row} 切換明細設定後互斥規則不成立（自留上限）"
            assert restored_toggleable == (not original), f"{game}／{row} 切回原狀後未恢復（自動飛單）"
            assert restored_cap_editable == (not original), f"{game}／{row} 切回原狀後未恢復（自留上限）"
    allure.attach(
        "\n".join(report_lines), name="非預設彩種互斥狀態機 roundtrip", attachment_type=allure.attachment_type.TEXT
    )
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")


@allure.title("[功能驗證] B57：飛單設置：非預設彩種欄位邊界值（最小飛單額／每選項自留上限）")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_setting_non_default_games_boundary_values(company_page):
    """B57：英國天天彩／賓果六合彩各挑一列，驗證「最小飛單額」負數／超大值（比照 B30）與
    「每選項自留上限」負數／超大值（比照 B31）行為是否跟香港六合彩一致。

    步驟（每個彩種各跑一次）：
    1. 導覽到「飞单设置」頁，切到目標彩種，記錄「特码」列「最小飛單額」原值
    2. 填入負數 -5 → Enter（期望打回原值）；填入超大值 999999999 → Enter → reload
       確認是否成功持久化，還原為原值
    3. 解鎖「过关」列，記錄「每選項自留上限」原值
    4. 填入負數 -10 → Enter（期望打回 0）；填入超大值 777777 → Enter → reload 確認是否
       成功持久化，還原自留上限並用 `save()` 走正確程序把明細設定鎖回原狀

    預期結果：
    - 「最小飛單額」：負數打回原值不持久化；超大值即時持久化（同 B30）
    - 「每選項自留上限」：負數打回 0；超大值即時持久化（同 B31）
    - 兩個彩種的行為應與香港六合彩一致

    oracle 來源：沿用 B30／B31 已建立的 B 級事實作對照基準，本案例驗證是否在其他彩種也成立。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("飞单设置")
    report_lines = []
    for game in ("英国天天彩", "宾果六合彩"):
        with allure.step(f"切到{game}，測試「特码」最小飛單額邊界值"):
            sp.switch_game(game)
            original_min = sp.min_lay_off_amount("特码")
            after_negative = sp.set_min_lay_off_amount("特码", "-5")
            after_large = sp.set_min_lay_off_amount("特码", "999999999")
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            persisted_large = sp.min_lay_off_amount("特码")
            sp.set_min_lay_off_amount("特码", original_min)
        report_lines.append(
            f"{game}／特码 最小飛單額：原值={original_min!r}，負數Enter後={after_negative!r}"
            f"（期望維持原值），超大值Enter後={after_large!r}，reload後持久化={persisted_large!r}（期望 999999999）"
        )
        assert after_negative == original_min, f"{game} 最小飛單額負數應被拒絕，維持原值"
        assert persisted_large == "999999999", f"{game} 最小飛單額超大值應成功持久化"

        with allure.step(f"{game}：解鎖「过关」列，測試每選項自留上限邊界值"):
            detail_original = sp.is_lay_off_detail_mode_enabled("过关")
            sp.set_lay_off_detail_mode("过关", False)
            original_cap = sp.cap_value("过关")
            after_cap_negative = sp.set_cap_value("过关", "-10")
            after_cap_large = sp.set_cap_value("过关", "777777")
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            persisted_cap = sp.cap_value("过关")
        report_lines.append(
            f"{game}／过关 每選項自留上限：原值={original_cap!r}，負數Enter後={after_cap_negative!r}"
            f"（期望 0），超大值Enter後={after_cap_large!r}，reload後持久化={persisted_cap!r}（期望 777777）"
        )
        assert after_cap_negative == "0", f"{game} 每選項自留上限負數應打回 0"
        assert persisted_cap == "777777", f"{game} 每選項自留上限超大值應成功持久化"

        with allure.step(f"{game}：還原「过关」自留上限與明細設定"):
            sp.set_cap_value("过关", original_cap)
            sp.set_lay_off_detail_mode("过关", detail_original)
            sp.save()
            page.wait_for_timeout(500)
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            assert sp.cap_value("过关") == original_cap
            assert sp.is_lay_off_detail_mode_enabled("过关") == detail_original

    allure.attach("\n".join(report_lines), name="非預設彩種欄位邊界值", attachment_type=allure.attachment_type.TEXT)
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")


@allure.title("[邏輯驗證] B58：飛單設置：非預設彩種「保存」按鈕效果與 PUT API 的 gameId 參數")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_setting_non_default_games_save_and_game_id(company_page):
    """B58：英國天天彩／賓果六合彩驗證「保存」按鈕對「開啟飛單選項明細設定」是否同樣有效
    （比照 B29），並用網路攔截確認 `PUT /api/LayOffSetting` 的 `gameId` 參數正確對應目標彩種。

    ⚠️ 附帶排除一個混淆變因：B27 觀察到的三彩種鎖定列數落差（70/6/13）有沒有可能其實是
    「彩種切換沒有真的切換 API 查詢參數、抓到的是同一份資料」造成的假象？本案例用網路攔截
    直接確認 `gameId` 參數確實隨切換的彩種而變，排除此可能性。

    步驟（每個彩種各跑一次）：
    1. 導覽到「飞单设置」頁，切到目標彩種，解鎖「特码」列
    2. 不碰任何其他欄位，直接按「保存」，攔截 PUT payload 的 gameId → reload 重讀

    預期結果：
    - PUT payload 的 `gameId` 應對應目標彩種（2026-08-31 探索已知英國天天彩＝`ukLucky7`、
      賓果六合彩＝`bingo6`，與香港六合彩的 `markSix` 不同）
    - 「保存」按鈕應能持久化「開啟飛單選項明細設定」的切換，跟 B29 一致

    oracle 來源：延伸 B29 的結論；gameId 對應為網路攔截直接讀取，A 級。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("飞单设置")
    report_lines = []
    game_ids: dict[str, str] = {}
    for game in ("英国天天彩", "宾果六合彩"):
        with allure.step(f"切到{game}，解鎖「特码」列"):
            sp.switch_game(game)
            original = sp.is_lay_off_detail_mode_enabled("特码")
            sp.set_lay_off_detail_mode("特码", not original)
        with allure.step(f"{game}：不碰任何其他欄位，直接按「保存」，攔截 PUT payload 的 gameId"):
            with page.expect_request(
                lambda r: r.method == "PUT" and "LayOffSetting" in r.url and "LayOffSettingDetail" not in r.url,
                timeout=10000,
            ) as req_info:
                sp.save()
            payload = req_info.value.post_data_json
            game_id = payload.get("gameId")
            game_ids[game] = game_id
            page.wait_for_timeout(500)
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            after = sp.is_lay_off_detail_mode_enabled("特码")
        report_lines.append(f"{game}：gameId={game_id!r}，保存後 reload 讀到明細設定={after}（期望 {not original}）")
        assert after == (not original), f"{game} 保存按鈕未能持久化明細設定切換"
        with allure.step(f"{game}：還原「特码」為原值並保存"):
            sp.set_lay_off_detail_mode("特码", original)
            sp.save()
            page.wait_for_timeout(500)
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            assert sp.is_lay_off_detail_mode_enabled("特码") == original

    allure.attach(
        "\n".join(report_lines) + f"\n\ngameId 對照：{game_ids}（期望兩者不同，且皆不等於香港六合彩的 markSix）",
        name="非預設彩種保存按鈕與 gameId 參數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert game_ids["英国天天彩"] != game_ids["宾果六合彩"], "兩個非預設彩種的 gameId 不應相同"
    assert "markSix" not in game_ids.values(), "非預設彩種的 gameId 不應是香港六合彩的 markSix"
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")


@allure.title("[邏輯驗證] B59：飛單設置：非預設彩種純前端切換與整列持久化陷阱")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_setting_non_default_games_toggle_and_persistence_trap(company_page):
    """B59：英國天天彩／賓果六合彩驗證純前端切換是否同樣不送 API（比照 B34）、整列持久化陷阱
    是否同樣存在（比照 B35）。

    步驟（每個彩種各跑一次）：
    1. 導覽到「飞单设置」頁，切到目標彩種，切換「正码」列明細設定但不做任何持久化動作 →
       reload（期望恢復原狀，驗證純前端切換不送 API，比照 B34）
    2. 解鎖「过关」列 → 對「每選項自留上限」填入探測值並 Enter → reload（期望仍為解鎖，
       驗證 Enter 送出的是整列資料，比照 B35）→ 走正確鎖回程序（還原自留上限、切回明細
       設定為原值、`save()`）

    預期結果：
    - 純前端切換：reload 後應恢復原狀（不送 API）
    - 整列持久化陷阱：解鎖後對自留上限做一次 Enter，reload 後明細設定仍是解鎖狀態
      （陷阱成立）；用 `save()` 走正確程序後應能鎖回

    oracle 來源：延伸 B34／B35 的結論，驗證是否在其他彩種也成立。
    """
    page = company_page
    sp = SystemSettingPage(page)
    sp.goto("飞单设置")
    report_lines = []
    for game in ("英国天天彩", "宾果六合彩"):
        with allure.step(f"切到{game}，切換「正码」列明細設定但不保存 → reload"):
            sp.switch_game(game)
            original_toggle = sp.is_lay_off_detail_mode_enabled("正码")
            sp.set_lay_off_detail_mode("正码", not original_toggle)
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            after_reload = sp.is_lay_off_detail_mode_enabled("正码")
        report_lines.append(
            f"{game}／正码 純前端切換：原值={original_toggle}，reload 後={after_reload}"
            f"（期望恢復為 {original_toggle}）"
        )
        assert after_reload == original_toggle, f"{game} 純前端切換 reload 後未恢復原狀"

        with allure.step(f"{game}：解鎖「过关」列 → 編輯「每選項自留上限」觸發 Enter 整列持久化 → reload"):
            detail_original = sp.is_lay_off_detail_mode_enabled("过关")
            sp.set_lay_off_detail_mode("过关", False)
            cap_original = sp.cap_value("过关")
            sp.set_cap_value("过关", "500")
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            trap_detail_state = sp.is_lay_off_detail_mode_enabled("过关")
            trap_cap_state = sp.cap_value("过关")
        report_lines.append(
            f"{game}／过关 整列持久化陷阱：Enter 後 reload 讀到明細設定={trap_detail_state}"
            f"（期望 False，即陷阱成立）、自留上限={trap_cap_state!r}（期望 500）"
        )
        assert trap_detail_state is False, f"{game} 未重現整列持久化陷阱——與 B35 的結論不符，需重新確認"
        assert trap_cap_state == "500", f"{game} 自留上限探測值未成功持久化"

        with allure.step(f"{game}：走正確鎖回程序（還原自留上限、切回明細設定為原值，save()）"):
            sp.set_cap_value("过关", cap_original)
            sp.set_lay_off_detail_mode("过关", detail_original)
            sp.save()
            page.wait_for_timeout(500)
            page.reload()
            sp.goto("飞单设置")
            sp.switch_game(game)
            assert sp.cap_value("过关") == cap_original, f"{game} 「过关」自留上限未還原"
            assert sp.is_lay_off_detail_mode_enabled("过关") == detail_original, f"{game} 「过关」未能正確鎖回"

    allure.attach(
        "\n".join(report_lines),
        name="非預設彩種純前端切換與整列持久化陷阱",
        attachment_type=allure.attachment_type.TEXT,
    )
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")


# ============================================================================
# B60~B62：飛單設置「最小飛單額」×「開啟飛單選項明細設定」交叉驗證
# （2026-08-31 從零設計新增，見案例清單 §0.2）
#
# B28／B33 只確認了「自動飛單」與「每選項自留上限」兩欄受明細設定開關影響，「最小飛單額」
# 是否受影響先前只是隱含在 B30 裡沒被排除，沒有案例明確斷言過。本節補上這張決策表。
# ============================================================================


@allure.title("[邏輯驗證] B60：飛單設置「最小飛單額」×「開啟飛單選項明細設定」決策表-1：明細設定開時的耦合檢查")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_min_amount_detail_mode_decision_table_open(company_page):
    """B60：明細設定＝開時，對「最小飛單額」Enter 新值，驗證①新值確實持久化②明細設定狀態
    不會被連帶改變。

    ⚠️ 這個交叉驗證先前完全沒做過——B30 只驗過「最小飛單額」欄位本身的邊界值行為，從未
    明確斷言過它跟「開啟飛單選項明細設定」這個開關之間**沒有**耦合關係（B31/B35 已證實
    「每選項自留上限」有耦合陷阱，「最小飛單額」是否也有同樣的陷阱，先前只是**沒被排除**，
    不是已經驗證過不存在——實際上 B62 證實它也有，見下）。

    步驟：
    1. 導覽到「飞单设置」頁，確認「特码」列明細設定＝開（若非開則先設為開並保存），
       記錄最小飛單額原值
    2. 對「最小飛單額」Enter 新值「2222」→ reload → 讀取①最小飛單額是否持久化②明細設定
       狀態是否不變
    3. 還原「特码」最小飛單額為原值

    預期結果：
    - 最小飛單額成功持久化為新值（沿用 B30 已證實的即時持久化機制）
    - 明細設定狀態應維持「開」，不因為編輯最小飛單額而被意外改動
      （因為操作前明細設定本來就是「開」，Enter 送出的整列 payload 也會帶著「開」，
      跟 B62 揭露的陷阱不衝突——陷阱只在「明細設定的 UI 狀態與後端持久化狀態不一致」
      時才會造成非預期的結果，這裡兩者原本就一致）
    """
    page = company_page
    sp = SystemSettingPage(page)
    row = "特码"
    with allure.step("導覽到「飞单设置」頁，確認「特码」列明細設定＝開，記錄最小飛單額原值"):
        sp.goto("飞单设置")
        if not sp.is_lay_off_detail_mode_enabled(row):
            sp.set_lay_off_detail_mode(row, True)
            sp.save()
            page.wait_for_timeout(500)
            page.reload()
            sp.goto("飞单设置")
        assert sp.is_lay_off_detail_mode_enabled(row) is True
        original_min = sp.min_lay_off_amount(row)

    with allure.step("對「最小飛單額」Enter 新值「2222」→ reload → 讀取持久化結果與明細設定狀態"):
        sp.set_min_lay_off_amount(row, "2222")
        page.reload()
        sp.goto("飞单设置")
        persisted_min = sp.min_lay_off_amount(row)
        detail_after = sp.is_lay_off_detail_mode_enabled(row)
    allure.attach(
        f"最小飛單額：設定=2222，reload 後實際={persisted_min!r}（期望 2222）\n"
        f"明細設定：操作前=True，Enter 後 reload 讀到={detail_after}（期望仍為 True，不受連帶影響）",
        name="決策表-1：明細設定開時的耦合檢查",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert persisted_min == "2222", "最小飛單額應成功持久化"
    assert detail_after is True, "明細設定不應因編輯最小飛單額而被意外改動"

    with allure.step("還原「特码」最小飛單額為原值"):
        sp.set_min_lay_off_amount(row, original_min)
        page.reload()
        sp.goto("飞单设置")
        assert sp.min_lay_off_amount(row) == original_min


@allure.title("[邏輯驗證] B61：飛單設置「最小飛單額」×「開啟飛單選項明細設定」決策表-2：明細設定關時的耦合檢查")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_min_amount_detail_mode_decision_table_closed(company_page):
    """B61：明細設定＝關時重複 B60 的驗證，並將 {開,關}×{最小飛單額可否輸入/持久化} 兩態
    整理成決策表對照（`testcase-design` §5⑧），確認「最小飛單額」真的不受此開關耦合。

    步驟：
    1. 導覽到「飞单设置」頁，解鎖「过关」列明細設定，記錄最小飛單額原值
    2. 對「最小飛單額」Enter 新值「3333」→ reload → 讀取①最小飛單額是否持久化②明細設定
       狀態是否不變
    3. 還原「过关」最小飛單額為原值與明細設定原狀

    預期結果（合併 B60 構成完整決策表）：

    | 明細設定狀態 | 最小飛單額可否編輯 | Enter 後是否持久化 | 是否連帶改動明細設定 |
    | --- | --- | --- | --- |
    | 開（B60） | 可 | 是 | 否（因為 UI 狀態與後端一致） |
    | 關（本案例） | 可 | 是 | 否（因為 UI 狀態與後端一致） |

    →「最小飛單額」欄位本身在兩種明細設定狀態下都可編輯、都會持久化，不因這個開關被鎖住
    （對照「每選項自留上限」欄位：只有明細設定＝關時才可編輯，見 B31——兩個金額欄位對這個
    開關的**可編輯性**耦合程度不同，但兩者的 Enter 都是整列 payload，見 B35／B62）
    """
    page = company_page
    sp = SystemSettingPage(page)
    row = "过关"
    with allure.step("導覽到「飞单设置」頁，解鎖「过关」列明細設定，記錄最小飛單額原值"):
        sp.goto("飞单设置")
        detail_original = sp.is_lay_off_detail_mode_enabled(row)
        sp.set_lay_off_detail_mode(row, False)
        original_min = sp.min_lay_off_amount(row)

    with allure.step("對「最小飛單額」Enter 新值「3333」→ reload → 讀取持久化結果與明細設定狀態"):
        sp.set_min_lay_off_amount(row, "3333")
        page.reload()
        sp.goto("飞单设置")
        persisted_min = sp.min_lay_off_amount(row)
        detail_after = sp.is_lay_off_detail_mode_enabled(row)
    allure.attach(
        f"最小飛單額：設定=3333，reload 後實際={persisted_min!r}（期望 3333）\n"
        f"明細設定：操作前=False，Enter 後 reload 讀到={detail_after}（期望仍為 False，不受連帶影響"
        f"——因為操作前 UI 狀態與後端本來就一致，見 B62 對「不一致時才會怎樣」的說明）",
        name="決策表-2：明細設定關時的耦合檢查",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert persisted_min == "3333", "最小飛單額應成功持久化"
    assert detail_after is False, "明細設定不應因編輯最小飛單額而被意外改動"

    with allure.step("還原「过关」最小飛單額與明細設定為原狀"):
        sp.set_min_lay_off_amount(row, original_min)
        sp.set_lay_off_detail_mode(row, detail_original)
        sp.save()
        page.wait_for_timeout(500)
        page.reload()
        sp.goto("飞单设置")
        assert sp.min_lay_off_amount(row) == original_min
        assert sp.is_lay_off_detail_mode_enabled(row) == detail_original


@allure.title("[邏輯驗證] B62：飛單設置「最小飛單額」整列持久化陷阱對稱性檢查")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_min_amount_row_persistence_symmetry(company_page):
    """B62：比照 B35，用網路攔截確認編輯「最小飛單額」的 Enter 送出的 payload 是否也是整列
    資料（可能意外持久化明細設定狀態），與 B35「每選項自留上限」的結果對照。

    ⚠️⚠️ 2026-08-31 用 MCP 網路攔截實測確認：**對稱成立**。解鎖「特码」列（純前端切換，
    尚未持久化）後對「最小飛單額」按 Enter，實測 payload 為
    `{"gameId":"markSix","settings":[{"playTypeId":"bonusNumber","retentionCap":1000,
    "isAutoEnabled":false,"minLayOffAmount":4444,"isSelectionDetailEnabled":false,
    "expectedIsSelectionDetailEnabled":true}]}`——`isSelectionDetailEnabled` 確實跟著
    UI 上尚未持久化的解鎖狀態一併送出，reload 後也確實仍是解鎖，與「每選項自留上限」
    （B35）的行為完全一致。附帶發現：`expectedIsSelectionDetailEnabled` 這個先前「用途
    待查」的欄位，此時的值是 `true`——與當下送出的 `isSelectionDetailEnabled:false` 相反，
    懷疑是後端用來記錄「送出前端這次操作預期的舊狀態」以偵測併發修改，但只是這次實測附帶
    觀察到的線索，用途仍待查（非本次範圍）。

    步驟：
    1. 導覽到「飞单设置」頁，解鎖「特码」列明細設定（純前端切換，尚未持久化）
    2. 對「最小飛單額」Enter 新值，攔截 PUT payload，讀取其中 `isSelectionDetailEnabled` 欄位
    3. reload 確認明細設定實際持久化狀態，走正確鎖回程序還原「特码」明細設定與最小飛單額

    預期結果：
    - PUT payload 應包含 `isSelectionDetailEnabled` 欄位，且值等於解鎖後的 `False`
      （整列持久化，不是只送變動欄位）
    - reload 後明細設定應仍是解鎖狀態（陷阱成立，跟 B35 對稱）
    """
    page = company_page
    sp = SystemSettingPage(page)
    row = "特码"
    with allure.step("導覽到「飞单设置」頁，解鎖「特码」列明細設定（純前端切換，尚未持久化）"):
        sp.goto("飞单设置")
        detail_original = sp.is_lay_off_detail_mode_enabled(row)
        sp.set_lay_off_detail_mode(row, False)
        original_min = sp.min_lay_off_amount(row)

    with allure.step("對「最小飛單額」Enter 新值「4444」，攔截 PUT payload"):
        cell = page.get_by_role("row").filter(has_text=row).first.get_by_role("cell").nth(4)
        with page.expect_request(
            lambda r: r.method == "PUT" and "LayOffSetting" in r.url and "LayOffSettingDetail" not in r.url,
            timeout=10000,
        ) as req_info:
            cell.get_by_role("button").click()
            field = cell.get_by_role("spinbutton")
            field.fill("4444")
            field.press("Enter")
        payload = req_info.value.post_data_json
        setting = payload["settings"][0] if payload.get("settings") else {}

    with allure.step("reload 確認明細設定實際持久化狀態"):
        page.reload()
        sp.goto("飞单设置")
        detail_persisted = sp.is_lay_off_detail_mode_enabled(row)
        min_persisted = sp.min_lay_off_amount(row)
    allure.attach(
        f"PUT payload settings[0]：{setting}\n"
        f"reload 後：明細設定={detail_persisted}（期望 False，即陷阱成立）、"
        f"最小飛單額={min_persisted!r}（期望 4444）",
        name="最小飛單額整列持久化陷阱對稱性檢查",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert min_persisted == "4444", "最小飛單額應成功持久化"
    assert "isSelectionDetailEnabled" in setting, (
        "PUT payload 未包含 isSelectionDetailEnabled 欄位——與「每選項自留上限」（B35）的"
        "整列 payload 結構不同，兩個欄位在這點上不對稱"
    )
    assert setting.get("isSelectionDetailEnabled") is False, (
        "payload 的 isSelectionDetailEnabled 不是 False——與解鎖後的 UI 狀態不一致"
    )
    assert detail_persisted is False, (
        "reload 後明細設定仍是解鎖——證實「最小飛單額」的 Enter 跟「每選項自留上限」一樣會把"
        "尚未持久化的明細設定狀態一併送出（整列持久化陷阱對稱成立）"
    )

    with allure.step("走正確鎖回程序，還原「特码」明細設定與最小飛單額"):
        sp.set_min_lay_off_amount(row, original_min)
        sp.set_lay_off_detail_mode(row, detail_original)
        sp.save()
        page.wait_for_timeout(500)
        page.reload()
        sp.goto("飞单设置")
        assert sp.min_lay_off_amount(row) == original_min
        assert sp.is_lay_off_detail_mode_enabled(row) == detail_original


@allure.suite("赔率设置")
@pytest.mark.smoke
def test_odds_setting_table_visible(company_page):
    """K2 的前置：確認賠率設置表格能讀到「特码A」列（不編輯，先只驗證讀取到位）。

    步驟：
    1. 導覽到「系统设置→赔率设置」子頁面
    2. 讀取「特码A」列的文字

    預期結果：
    - 該列文字應包含「特码A」

    ⚠️ 2026-08-28 探索附帶確認矩陣 K2 現況仍成立：該列只有 A 盤（41.993）有值，
    B~I 盤皆為 0，與退水設置「A~I 全部盤口皆有相同值」的現況不一致（是否為缺陷待使用者裁示）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→赔率设置」子頁面"):
        sp.goto("赔率设置")
    with allure.step("讀取「特码A」列的文字"):
        row_text = sp.table_row_text("特码A")
    allure.attach(
        f"該列實際文字：{row_text!r}（期望包含：特码A）",
        name="賠率設置「特码A」列讀取",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "特码A" in row_text


@allure.title("[畫面驗證] B40：飛單選項明細設置頁結構性掃描——25 個分類按鈕、總開關、表格欄位、快速設置面板、保存區皆齊全")
@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_categories_visible(company_page):
    """B40：飛單選項明細設置頁結構性掃描——25 個分類按鈕、總開關、表格欄位、
    （2026-08-31 案例重編號：舊編號 B17，見案例清單 §0.1；標題截斷問題已用 @allure.title 修正）
    快速設置面板、保存區皆齊全（不編輯，先只驗證讀取到位）。

    ⚠️ 2026-08-28 擴充：原案例只驗「特码」按鈕＋「自動飛單」欄位存在，覆蓋不足，
    依 `ui-exploration-structural-sweep-default` 補齊完整結構掃描，**沿用同一測試函式**
    （案例清單 B17 註明取代原案例，不需另開新測試）。

    步驟：
    1. 導覽到「系统设置→飞单选项明细设置」子頁面
    2. 讀取 25 個玩法分類按鈕、總開關、當前分類（「特码」）表格欄位與列數
    3. 確認右側「快速設置」面板與底部保存區的關鍵元素都在

    預期結果：
    - 25 個分類按鈕全部存在（特码/正码/正特码/两面/连码/过关/生肖中/生肖不中/尾数中/
      尾数不中/半波/六肖/色波/特肖/连肖/连尾/不中/多选中一/特平中/合肖/七码/五行/
      一肖量/尾数量/比大小）
    - 總開關「啟用飛單選項明細」存在
    - 「特码」分類表格 4 欄齊全（選項／實際占成金額／每選項自留上限／自動飛單），
      列數＝49（對應 1~49 號碼）
    - 快速設置面板的重置／反選／套用按鈕存在；保存區「保存」按鈕與
      「保存後立即觸發本次選項自動飛單」checkbox 存在

    oracle 來源：B 級（regression baseline，2026-08-28 結構性複掃時清點）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到「系统设置→飞单选项明细设置」子頁面"):
        sp.goto()

    expected_categories = [
        "特码", "正码", "正特码", "两面", "连码", "过关", "生肖中", "生肖不中",
        "尾数中", "尾数不中", "半波", "六肖", "色波", "特肖", "连肖", "连尾",
        "不中", "多选中一", "特平中", "合肖", "七码", "五行", "一肖量", "尾数量", "比大小",
    ]
    with allure.step("讀取 25 個玩法分類按鈕、總開關、當前分類（「特码」）表格欄位與列數"):
        labels = sp.category_labels()
        master_switch_visible = page.get_by_text("启用飞单选项明细", exact=True).is_visible()
        headers = ("选项", "实际占成金额", "每选项自留上限", "自动飞单")
        header_visible = {h: page.get_by_role("columnheader", name=h, exact=True).is_visible() for h in headers}
        option_row_count = sp.option_row_count()
    with allure.step("確認右側「快速設置」面板與底部保存區的關鍵元素都在"):
        quick_set_visible = page.get_by_text("快速设置", exact=True).is_visible()
        reset_visible = page.get_by_role("button", name="重置").is_visible()
        invert_visible = page.get_by_role("button", name="反选").is_visible()
        apply_visible = page.get_by_role("button", name="套用").is_visible()
        save_visible = page.get_by_role("button", name="保存").is_visible()
        auto_trigger_visible = page.get_by_text("保存后立即触发本次选项自动飞单").is_visible()
    allure.attach(
        f"分類按鈕數：{len(labels)}（期望 25）：{labels}\n"
        f"總開關顯示：{master_switch_visible}\n"
        f"表頭顯示：{header_visible}\n"
        f"「特码」列數：{option_row_count}（期望 49）\n"
        f"快速設置面板：快速设置={quick_set_visible} 重置={reset_visible} 反选={invert_visible} 套用={apply_visible}\n"
        f"保存區：保存={save_visible} 保存後觸發checkbox={auto_trigger_visible}",
        name="飛單選項明細設置結構性掃描",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(labels) == 25, f"預期 25 個玩法分類按鈕，實際 {len(labels)}：{labels}"
    for name in expected_categories:
        assert name in labels, f"分類「{name}」未找到，實際：{labels}"

    assert master_switch_visible

    for header, visible in header_visible.items():
        assert visible, f"表頭「{header}」未找到"
    assert option_row_count == 49, f"「特码」分類預期 49 個選項，實際 {option_row_count}"

    assert quick_set_visible
    assert reset_visible
    assert invert_visible
    assert apply_visible
    assert save_visible
    assert auto_trigger_visible


@allure.title("[畫面驗證] B41：飛單選項明細設置：25 個分類歸類為兩種結構家族（標準選項清單型／組合型）")
@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_two_structure_families(company_page):
    """B41：把 25 個玩法分類逐一點開，斷言其真的分屬「標準選項清單型」與「組合型」兩種結構家族，
    並固化各分類的列數／子結構特徵，取代先前只有唯讀腳本記錄、沒有 assert 守著的狀態
    （2026-08-31 案例重編號：舊編號 B18，見案例清單 §0.1；補齊斷言，見交接檔 T24）。

    ⚠️⚠️ 2026-08-31 補課實測時發現案例清單先前記錄的「14 個標準型」有誤——逐一點開 25 個
    分類實際統計，標準選項清單型是 **15 個**（漏算「色波」），組合型仍是 10 個
    （15＋10＝25，與總分類數對得上）。已同步更正 `新綜合_案例清單.md` B41 與機制文件，
    不留著錯的數字——這正是本案例存在的理由：唯讀探索記錄沒有 assert 守著，
    數字錯了也不會被發現。

    步驟：
    1. 導覽到飛單選項明細設置頁，記錄 25 個分類按鈕清單
    2. 逐一點開每個分類，讀取是否為組合型（有無「共用自留上限」欄位）——
       標準型記錄列數，組合型記錄「選擇」checkbox 數量

    預期結果：
    - 標準選項清單型應為 15 個：特码/正码/正特码(各49)、两面(62)、
      生肖中/生肖不中/半波/特肖(各12)、尾数中/尾数不中(各10)、色波(21)、七码(32)、
      五行(5)、一肖量/尾数量(各6)
    - 組合型應為 10 個：连码/过关/六肖/连肖/连尾/不中/多选中一/特平中/合肖/比大小
    - 15 + 10 = 25（分類總數不變，只是重新分組確認）

    oracle 來源：B 級（regression baseline，2026-08-31 逐一點開實測建立）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    expected_standard_rows = {
        "特码": 49, "正码": 49, "正特码": 49, "两面": 62,
        "生肖中": 12, "生肖不中": 12, "半波": 12, "特肖": 12,
        "尾数中": 10, "尾数不中": 10, "色波": 21, "七码": 32,
        "五行": 5, "一肖量": 6, "尾数量": 6,
    }
    expected_combo = {
        "连码", "过关", "六肖", "连肖", "连尾", "不中", "多选中一", "特平中", "合肖", "比大小",
    }

    with allure.step("導覽到飛單選項明細設置頁，記錄 25 個分類按鈕清單"):
        sp.goto()
        categories = sp.category_labels()
    assert len(categories) == 25, f"預期 25 個分類，實際 {len(categories)}：{categories}"

    standard_rows: dict[str, int] = {}
    combo_counts: dict[str, int] = {}
    for name in categories:
        with allure.step(f"分類「{name}」：讀取是否為組合型並記錄結構特徵"):
            sp.select_category(name)
            if sp.is_current_category_combo():
                combo_counts[name] = sp.combo_item_count()
            else:
                standard_rows[name] = sp.option_row_count()

    allure.attach(
        f"標準選項清單型（{len(standard_rows)} 個）：{standard_rows}\n"
        f"組合型（{len(combo_counts)} 個，數字為「選擇」checkbox 數）：{combo_counts}\n"
        f"合計：{len(standard_rows)} + {len(combo_counts)} = "
        f"{len(standard_rows) + len(combo_counts)}（期望 25＝15＋10）",
        name="25 分類結構家族歸類",
        attachment_type=allure.attachment_type.TEXT,
    )

    assert set(standard_rows) == set(expected_standard_rows), (
        f"標準選項清單型的分類組成與預期不同：實際 {sorted(standard_rows)}，"
        f"預期 {sorted(expected_standard_rows)}"
    )
    assert set(combo_counts) == expected_combo, (
        f"組合型的分類組成與預期不同：實際 {sorted(combo_counts)}，預期 {sorted(expected_combo)}"
    )
    for name, expected in expected_standard_rows.items():
        assert standard_rows[name] == expected, f"「{name}」列數預期 {expected}，實際 {standard_rows[name]}"
    assert len(standard_rows) == 15, f"標準選項清單型應為 15 個，實際 {len(standard_rows)}"
    assert len(combo_counts) == 10, f"組合型應為 10 個，實際 {len(combo_counts)}"


@allure.title("[邏輯驗證] B37：飛單選項明細設置：總開關關↔開的狀態轉移（含取消分支）")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_master_switch_transition(company_page):
    """B37：K7 總開關「啟用飛單選項明細」的狀態轉移，並確認它是 K4 的父子連動點。
    （2026-08-31 案例重編號：舊編號 B11，拆為「開啟／關閉狀態轉移」B37、「關閉還原」B39、
    「批次影響範圍」B50 三個新案例，本函式對應 B37；B39 沒有獨立函式，見 B38 的收尾步驟；
    見案例清單 §0.1）

    步驟：
    1. 導覽到「系统设置→飞单选项明细设置」子頁面，記錄總開關原始狀態
    2. 關閉總開關 → 讀取「特码」分類選項 1 的自動飛單開關是否被鎖住，附帶讀取批次工具列
       三顆按鈕是否 disabled、「每選項自留上限」欄位是否變回純文字（B50-2、B50-3，交接檔 T25）
    3. 重新開啟總開關（會跳確認框，需點「確定」）→ 讀取選項 1 的自動飛單開關是否恢復可互動
    4. 關閉總開關 → 再次點擊嘗試開啟，但這次在確認框按「取消」，驗證維持關閉
       （B37 取消分支，交接檔 T26；先前文件誤寫「含取消分支」但實際未測，此為補齊）
    5. 重新開啟總開關（走正常「確定」路徑）並還原成進入案例前的原值

    預期結果：
    - 關閉：不跳確認框，底下所有選項的自動飛單 switch 變 disabled（但保留原本 checked 值）；
      批次工具列「一鍵自動」「一鍵手動」變 disabled（B50-2，「全部設置」另受輸入框是否
      填值影響，見 `batch_tool_buttons_disabled()` 檔頭）；「每選項自留上限」從可編輯
      button 變回純文字（B50-3）
    - 開啟：跳出確認框，文字明確寫「原系統設定－飛單設定中，飛單設定的金額將會失效，
      並且自動出貨將變更為手動模式」——**這是 A 級 oracle：系統自己承認 K7 開啟時
      K4（飛單設置）的金額設定會失效**，兩層是互斥切換的父子關係，不是各自獨立
      （回答矩陣 K7／案例 B14 的疑問）
    - 取消：確認框按「取消」後，總開關應維持關閉，選項仍不可互動（B37 取消分支）

    oracle 來源：A 級（系統確認框的原文自白，非測試者臆測）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到「系统设置→飞单选项明细设置」子頁面，記錄總開關原始狀態"):
        sp.goto()
        original = sp.is_master_switch_enabled()

    with allure.step("關閉總開關 → 讀取「特码」分類選項 1 的自動飛單開關是否被鎖住，附帶讀取批次工具列三顆按鈕與「每選項自留上限」欄位是否受影響"):
        sp.set_master_switch(False)
        switch_off = sp.is_master_switch_enabled()
        option1_toggleable_off = sp.option_auto_lay_off_toggleable(1)
        batch_buttons_off = sp.batch_tool_buttons_disabled()
        cap_editable_off = sp.option_cap_editable(1)
    allure.attach(
        f"實際：總開關={switch_off}（期望 False）、選項1可互動={option1_toggleable_off}（期望 False）\n"
        f"批次工具列 disabled 狀態：{batch_buttons_off}（期望：一鍵自動／一鍵手動皆 True）\n"
        f"選項1「每選項自留上限」可編輯（button）：{cap_editable_off}（期望 False，即變回純文字）",
        name="K7 總開關關閉後的連動（含 B50-2、B50-3 批次影響範圍）",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert switch_off is False
    assert option1_toggleable_off is False, "總開關關閉後，選項列的自動飛單應變成不可互動"
    assert batch_buttons_off["一键自动"] is True, "總開關關閉後，「一鍵自動」按鈕應變 disabled（B50-2）"
    assert batch_buttons_off["一键手动"] is True, "總開關關閉後，「一鍵手動」按鈕應變 disabled（B50-2）"
    assert cap_editable_off is False, "總開關關閉後，「每選項自留上限」應從可編輯 button 變回純文字（B50-3）"

    with allure.step("重新開啟總開關（會跳確認框，需點「確定」）→ 讀取選項 1 的自動飛單開關是否恢復可互動"):
        sp.set_master_switch(True)
        switch_on = sp.is_master_switch_enabled()
        option1_toggleable_on = sp.option_auto_lay_off_toggleable(1)
    allure.attach(
        f"實際：總開關={switch_on}（期望 True）、選項1可互動={option1_toggleable_on}（期望 True）",
        name="K7 總開關重新開啟後的連動",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert switch_on is True
    assert option1_toggleable_on is True, "總開關重新開啟後，選項列的自動飛單應恢復可互動"

    with allure.step("關閉總開關 → 再次點擊嘗試開啟，但這次在確認框按「取消」，驗證維持關閉"):
        sp.set_master_switch(False)
        sp.click_master_switch_and_cancel()
        switch_after_cancel = sp.is_master_switch_enabled()
        option1_toggleable_after_cancel = sp.option_auto_lay_off_toggleable(1)
    allure.attach(
        f"點「取消」後實際：總開關={switch_after_cancel}（期望 False，即取消不生效）、"
        f"選項1可互動={option1_toggleable_after_cancel}（期望 False，維持鎖定）",
        name="K7 總開關取消分支驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert switch_after_cancel is False, "按「取消」後總開關不應被打開"
    assert option1_toggleable_after_cancel is False, "按「取消」後選項列不應恢復可互動"

    # 還原（CLAUDE.md §5）
    with allure.step("把 K7 總開關還原成進入案例前讀到的原值"):
        if sp.is_master_switch_enabled() != original:
            sp.set_master_switch(original)
        assert sp.is_master_switch_enabled() == original


@allure.title("[邏輯驗證] B44：飛單選項明細設置：批次工具「一鍵自動／一鍵手動」")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_batch_tools_apply_to_all_options(company_page):
    """B44：「特码」分類「一鍵自動／一鍵手動」批次操作，49 個選項應全部變成一致狀態。
    （2026-08-31 案例重編號：舊編號 B12，見案例清單 §0.1）

    步驟：
    1. 導覽到飛單選項明細設置頁，切到「特码」分類
    2. 點「一鍵自動」→ 抽樣讀取選項 1、25、49 的自動飛單開關
    3. 點「一鍵手動」→ 再次抽樣讀取同三個選項
    4. 還原成操作前的狀態

    預期結果：
    - 「一鍵自動」後，抽樣的選項應**全部** checked
    - 「一鍵手動」後，抽樣的選項應**全部**未 checked
    - 自檢不變量：批次操作後全部選項狀態一致（A 級，「一鍵」按鈕名稱本身即隱含規格）

    ⚠️ 抽樣 1／25／49（首、中、尾）而非全 49 個逐一讀取，屬 testcase-design §6
    分層抽樣＋邊界優先；若之後懷疑中間有漏網選項，再擴大抽樣範圍。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「特码」分類，記錄抽樣選項原值"):
        sp.goto()
        sp.select_category("特码")
        sample = [1, 25, 49]
        originals = {n: sp.option_auto_lay_off_enabled(n) for n in sample}

    with allure.step("點「一鍵自動」→ 抽樣讀取選項 1、25、49 的自動飛單開關"):
        sp.click_batch_auto()
        after_auto = {n: sp.option_auto_lay_off_enabled(n) for n in sample}
    allure.attach(
        f"「一鍵自動」後抽樣結果：{after_auto}（期望：全部 True）",
        name="批次一鍵自動",
        attachment_type=allure.attachment_type.TEXT,
    )
    for n, v in after_auto.items():
        assert v is True, f"選項 {n} 「一鍵自動」後應為 checked"

    with allure.step("點「一鍵手動」→ 再次抽樣讀取同三個選項"):
        sp.click_batch_manual()
        after_manual = {n: sp.option_auto_lay_off_enabled(n) for n in sample}
    allure.attach(
        f"「一鍵手動」後抽樣結果：{after_manual}（期望：全部 False）",
        name="批次一鍵手動",
        attachment_type=allure.attachment_type.TEXT,
    )
    for n, v in after_manual.items():
        assert v is False, f"選項 {n} 「一鍵手動」後應為未 checked"

    # 還原（CLAUDE.md §5）：批次工具會覆蓋全部 49 個選項，抽樣到的 3 個逐一還原即可、
    # 未抽樣到的選項本來就不在本案例的驗證範圍內，維持「一鍵手動」後的狀態
    with allure.step("還原抽樣到的 3 個選項"):
        for n, was_enabled in originals.items():
            sp.set_option_auto_lay_off(n, was_enabled)
            assert sp.option_auto_lay_off_enabled(n) == was_enabled


@allure.title("[邏輯驗證] B45：飛單選項明細設置：快速設置面板套用範圍")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_quick_set_scope(company_page):
    """B45：「快速設置」面板套用範圍——只有被勾選的號碼欄位值改變，其餘不受影響。
    （2026-08-31 案例重編號：舊編號 B13，見案例清單 §0.1）

    步驟：
    1. 導覽到飛單選項明細設置頁，切到「特码」分類
    2. 記錄選項 2、3（未勾選對象）目前的自留上限
    3. 勾選號碼 1，輸入新值並「套用」
    4. 讀取選項 1（被勾選）與選項 2、3（未勾選）的自留上限

    預期結果：
    - 選項 1（被勾選）：值變成套用的新值（正向）
    - 選項 2、3（未勾選）：值不受影響（反向，§5②通用兩問）

    oracle 來源：B 級（套用範圍＝勾選範圍，屬自檢不變量）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「特码」分類，記錄選項 1、2、3 原值"):
        sp.goto()
        sp.select_category("特码")
        original_1 = sp.option_cap_value(1)
        control_2 = sp.option_cap_value(2)
        control_3 = sp.option_cap_value(3)

    with allure.step("重置勾選 → 勾選號碼 1 → 輸入 1500 並「套用」"):
        sp.quick_set_reset()
        sp.quick_set_select_numbers([1])
        sp.quick_set_apply("1500")
        after_1 = sp.option_cap_value(1)
        after_2 = sp.option_cap_value(2)
        after_3 = sp.option_cap_value(3)
    allure.attach(
        f"選項1（被勾選）：套用前={original_1!r} 套用後={after_1!r}（期望：1500）\n"
        f"選項2（未勾選）：套用前={control_2!r} 套用後={after_2!r}（期望：不變）\n"
        f"選項3（未勾選）：套用前={control_3!r} 套用後={after_3!r}（期望：不變）",
        name="快速設置套用範圍",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_1 == "1500"
    assert after_2 == control_2, "未勾選的選項 2 不該被套用動作影響"
    assert after_3 == control_3, "未勾選的選項 3 不該被套用動作影響"

    # 還原（CLAUDE.md §5）
    with allure.step("把「特码」選項 1 還原成進入案例前讀到的原值"):
        sp.set_option_cap(1, original_1)
        assert sp.option_cap_value(1) == original_1


@allure.title("[畫面驗證] B14（歷史保留，已被拆分並取代）：K4（飛單設置）／K7（飛單選項明細設置）父子層級交叉比對")
@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_vs_setting_cross_reference(company_page):
    """B14（歷史保留，已被拆分並取代）：K4（飛單設置）／K7（飛單選項明細設置）父子層級交叉比對
    ——用「比大小」分類當樣本（唯一已知有異常的玩法）。
    （2026-08-31 案例重編號：舊編號 B14，已被拆分並取代——「25 分類結構家族歸類」
    見 B41（`test_lay_off_detail_two_structure_families`，2026-08-31 已補齊，交接檔 T24 已結案）、
    「比大小共用自留上限聲明是否兌現」見 B49（`test_lay_off_detail_compare_shared_cap_declaration`，
    已實作）。本函式作為早期探索快照保留，其「K4／K7 交叉記錄」段落未被後兩者取代，故不刪除，
    見案例清單 §0.1）

    ⚠️ 2026-08-28 執行時發現：「比大小」分類的 UI **跟其餘 24 個分類完全不同**——
    不是標準的「選項 1~N 逐列自動飛單」表格，是先選 6 個子項（一比一～一比六，
    純文字＋可點擊，不是語意 `button`／`table`）之一，才顯示「組合占成金額」表格
    （正1特～正6特＋特码，共用自留上限規則另有特殊說明）。原本設計的「選項數＝6」
    斷言不成立，已改用文字定位驗證這個跟其他分類不同的結構本身
    ——**這個「不一樣」的發現，才是本案例對 T17 真正有意義的產出**：
    K4「一比五/一比六」（玩法整體一列）跟 K7「比大小」底下的「一比五/一比六」
    （玩法內子項）不能直接假設是同一件事的兩種呈現。

    步驟：
    1. 讀取 K7「飛單選項明細設置」的「比大小」分類，確認 6 個子項（一比一～一比六）都在
    2. 確認選定子項後出現「組合占成金額」表格與「共用自留上限」規則說明
    3. 讀取 K4「飛單設置」頁「比大小」列的狀態（是否為 T17 記錄的例外解鎖列），交叉記錄

    預期結果：
    - K7「比大小」分類的 6 個子項（一比一～一比六）都存在
    - 「組合占成金額」與「共用自留上限」說明文字都存在（確認這是組合型玩法的特殊 UI）
    - 記錄 K4 兩層現況供之後比對（regression 快照，非正確性判斷）

    oracle 來源：D 級（探索當下實測記錄，非正確性判斷）——K4／K7 逐選項是否該一一對應
    尚無規格文件佐證，本案例先做**現況快照**，之後若找到規格依據再升級判準。
    """
    page = company_page
    sp7 = LayOffDetailSettingPage(page)
    with allure.step("讀取 K7「飛單選項明細設置」的「比大小」分類，確認 6 個子項都在：一比一／一比二／一比三／一比四／一比五／一比六"):
        sp7.goto()
        sp7.select_category("比大小")
        sub_visible = {sub: page.get_by_text(sub, exact=True).first.is_visible()
                       for sub in ("一比一", "一比二", "一比三", "一比四", "一比五", "一比六")}
    with allure.step("確認選定子項後出現「組合占成金額」表格與「共用自留上限」規則說明"):
        combo_cap_visible = page.get_by_text("组合占成金额", exact=True).is_visible()
        shared_cap_visible = page.get_by_text("共用自留上限", exact=True).is_visible()
    allure.attach(
        f"6 個子項顯示狀態：{sub_visible}（期望：全部 True）\n"
        f"「组合占成金额」顯示：{combo_cap_visible}\n「共用自留上限」顯示：{shared_cap_visible}",
        name="K7「比大小」分類結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    for sub, visible in sub_visible.items():
        assert visible, f"「比大小」子項「{sub}」未找到"
    assert combo_cap_visible
    assert shared_cap_visible

    with allure.step("讀取 K4「飛單設置」頁「比大小」列的狀態，交叉記錄"):
        sp4 = SystemSettingPage(page)
        sp4.goto("飞单设置")
        k4_unlocked = {row: sp4.is_auto_lay_off_toggleable(row) for row in ("一比五", "一比六")}
    # 現況快照：記錄下來，之後有規格依據再補斷言
    allure.attach(
        str(k4_unlocked), name="K4 飛單設置「比大小」一比五/一比六 現況", attachment_type=allure.attachment_type.TEXT
    )


@allure.title("[功能驗證] B47-1：組合型分類（以「比大小→一比一」為樣本）的「关连/不关连」與「共用自留上限」roundtrip")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_relation_and_shared_cap_roundtrip(company_page):
    """B47-1：組合型分類（以「比大小→一比一」為樣本）的「关连/不关连」與「共用自留上限」roundtrip。
    （2026-08-31 案例重編號：舊編號 B19，與 B20（今 B47-2）合併為 B47「組合型 table=0 代表樣本
    roundtrip」的兩個獨立 pytest 函式，見案例清單 §0.1）

    ⚠️ K7 有 10 個組合型分類（連碼／過關／六肖／連肖／連尾／不中／多選中一／特平中／合肖／
    比大小，見矩陣 K7、案例 B18），本案例只驗「比大小」一個樣本，其餘 9 個結構可能不完全
    相同（`table=10` vs `table=0` 兩種子變體），還沒逐一確認。

    ⚠️⚠️ 2026-08-28 實測發現：**保存前必須先勾選至少一個組合列的「選擇」checkbox**，
    否則會跳「請選擇號碼或選項」提示、完全不送出 API（第一版案例漏了這步，導致
    roundtrip 讀不到任何持久化結果，誤以為保存沒生效）。已用網路攔截確認
    `PUT /api/LayOffSettingDetail` 的資料模型：見 `set_combo_item_marked()` 的檔頭說明。

    步驟：
    1. 導覽到飛單選項明細設置頁，切到「比大小」分類（預設子項「一比一」）
    2. 記錄「关连/不关连」「共用自留上限」「正1特」選擇狀態的原值
    3. 切到「不关连」、改「共用自留上限」為新值、勾選「正1特」的選擇 → 按保存
    4. reload、重新導覽回同一子項 → 讀取是否持久化
    5. 還原為原值並保存

    預期結果：
    - 「关连/不关连」「共用自留上限」「選擇」勾選狀態改值並保存後，reload 仍是新值
      （持久化，B 級自檢不變量）
    - 切換「关连/不关连」本身不影響「共用自留上限」欄位是否顯示——2026-08-28 實測發現
      兩者同時存在、不是互斥顯示（先前檔頭猜測「关连才顯示共用上限」不成立，已更正）
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「比大小」分類（預設子項「一比一」），記錄原值"):
        sp.goto()
        sp.select_category("比大小")
        original_linked = sp.is_relation_linked()
        original_cap = sp.shared_cap_value()
        original_marked = sp.combo_item_marked(0)

    with allure.step("切到相反的关连狀態、改共用自留上限為 777、勾選「正1特」的選擇 → 保存 → reload 重讀"):
        sp.set_relation_linked(not original_linked)
        sp.set_shared_cap("777")
        sp.set_combo_item_marked(0, True)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("比大小")
        after_linked = sp.is_relation_linked()
        after_cap = sp.shared_cap_value()
        after_marked = sp.combo_item_marked(0)
    allure.attach(
        f"关连：設定={not original_linked} 重整後實際={after_linked}\n"
        f"共用自留上限：設定=777 重整後實際={after_cap!r}\n"
        f"選擇勾選：設定=True 重整後實際={after_marked}",
        name="比大小 关连/共用自留上限 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_linked == (not original_linked)
    assert after_cap == "777"
    assert after_marked is True

    # 還原（CLAUDE.md §5）
    with allure.step("還原為原值並保存"):
        sp.set_relation_linked(original_linked)
        sp.set_shared_cap(original_cap)
        sp.set_combo_item_marked(0, original_marked)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("比大小")
        assert sp.is_relation_linked() == original_linked
        assert sp.shared_cap_value() == original_cap
        assert sp.combo_item_marked(0) == original_marked


@allure.title("[功能驗證] B47-2：組合型分類第二樣本「過關」——確認跟「比大小」（B47-1）是同一套 API 模型")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_second_sample_api_consistency(company_page):
    """B47-2：組合型分類第二樣本「過關」——確認跟「比大小」（B47-1）是同一套 API 模型。
    （2026-08-31 案例重編號：舊編號 B20，見案例清單 §0.1）

    ⚠️ 「過關」跟「比大小」的差異：**沒有子項選擇器**（不需要先選「一比幾」），
    進分類直接就是「关连/不关连」＋「共用自留上限」＋組合列（本身即代表整個玩法，
    不是玩法下的子項）。用來確認 K7 的「組合型」是否真的共用同一套後端資料模型，
    而不是每個分類各自一套。

    步驟：同 B19，只是分類換成「過關」，且不需要 `select_sub_item()`

    預期結果：
    - 保存前同樣要先勾選「選擇」，否則不送 API（跟比大小一致）
    - ✅ 2026-08-28 已用網路攔截確認：`PUT /api/LayOffSettingDetail`，`gameId=markSix`，
      **`playTypeId=parlay`**（比大小是 `compareBigSmall1v1`）——**同一個 API 資源，
      只有 `gameId`／`playTypeId`／`items[].selection` 命名依玩法不同，資料結構完全一致**
      （A 級 oracle，直接讀 API payload）。同一輪順便確認 25 個分類（含標準型／組合型
      table=0／table=10 三種 UI）的 **GET 都打同一個 `/api/LayOffSettingDetail` 端點**，
      只是查詢參數不同，證實 K7 後端是單一資源、前端才依 `playTypeId` 客製化渲染方式
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「過關」分類（無子項選擇器），記錄原值"):
        sp.goto()
        sp.select_category("过关")
        original_linked = sp.is_relation_linked()
        original_cap = sp.shared_cap_value()
        original_marked = sp.combo_item_marked(0)

    with allure.step("切到相反的关连狀態、改共用自留上限為 555、勾選「選擇」→ 保存 → reload 重讀"):
        sp.set_relation_linked(not original_linked)
        sp.set_shared_cap("555")
        sp.set_combo_item_marked(0, True)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("过关")
        after_linked = sp.is_relation_linked()
        after_cap = sp.shared_cap_value()
        after_marked = sp.combo_item_marked(0)
    allure.attach(
        f"关连：設定={not original_linked} 重整後實際={after_linked}\n"
        f"共用自留上限：設定=555 重整後實際={after_cap!r}\n"
        f"選擇勾選：設定=True 重整後實際={after_marked}\n"
        "（用來確認「過關」跟 B19「比大小」是同一套 API 模型）",
        name="過關 关连/共用自留上限 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_linked == (not original_linked)
    assert after_cap == "555"
    assert after_marked is True

    # 還原（CLAUDE.md §5）
    with allure.step("還原為原值並保存"):
        sp.set_relation_linked(original_linked)
        sp.set_shared_cap(original_cap)
        sp.set_combo_item_marked(0, original_marked)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("过关")
        assert sp.is_relation_linked() == original_linked
        assert sp.shared_cap_value() == original_cap
        assert sp.combo_item_marked(0) == original_marked


@allure.title("[功能驗證] B48-1：組合型 `table=10`（连码／不中／多选中一／特平中 4 個分類共用的號碼矩陣結構）代表樣本「連碼→二全中」——確認跟 B47-1/B47-2（`table=0`：过关／六肖／连肖／连尾／合肖／比大小 6 個分類）是否同一套 API 模型")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_number_grid_api_consistency(company_page):
    """B48-1：組合型 `table=10`（连码／不中／多选中一／特平中 4 個分類共用的號碼矩陣結構）
    代表樣本「連碼→二全中」——確認跟 B47-1/B47-2（`table=0`：过关／六肖／连肖／连尾／合肖／比大小
    6 個分類）
    （2026-08-31 案例重編號：舊編號 B21，見案例清單 §0.1；標題截斷問題已用 @allure.title 修正）
    是否同一套 API 模型。

    ⚠️ 「連碼」的畫面跟比大小/過關完全不同——是 1~49 號碼的組合矩陣（分 5 個小表格顯示），
    **每個號碼的「組合占成金額」button 恆為 disabled**（不管有沒有勾選都不能個別點擊編輯，
    2026-08-28 用 `el.disabled` 逐列掃描 49 列確認），只能靠「共用自留上限」統一設定——
    這代表「連碼」這個玩法**設計上不支援逐號碼個別設定**，UI 才會把個別編輯整個鎖死。
    但「关连/不关连」「共用自留上限」「選擇」三個欄位的存在與 API 行為跟 `table=0` 變體
    完全一樣，不受「個別編輯鎖死」影響。

    步驟：同 B19/B20 模式（不驗個別金額欄位，因為那欄本來就鎖死不給編輯）

    預期結果：
    - ✅ 已用網路攔截確認：`PUT /api/LayOffSettingDetail`，`gameId=markSix`，
      `playTypeId=pickTwoAllHit`，`items[].selection` 為兩位數字串（`"01"`~`"49"`，
      跟 `table=0` 變體的命名格式不同，但整體資料結構一致）——**四種 UI 呈現
      （標準列表／`table=0` 組合／`table=10` 組合／比大小的子項式）背後都是同一套模型**
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「連碼」分類（table=10 號碼矩陣變體），記錄原值"):
        sp.goto()
        sp.select_category("连码")
        original_linked = sp.is_relation_linked()
        original_cap = sp.shared_cap_value()

    with allure.step("切到相反的关连狀態、改共用自留上限為 333 → 保存 → reload 重讀"):
        sp.set_relation_linked(not original_linked)
        sp.set_shared_cap("333")
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("连码")
        after_linked = sp.is_relation_linked()
        after_cap = sp.shared_cap_value()
    allure.attach(
        f"关连：設定={not original_linked} 重整後實際={after_linked}\n"
        f"共用自留上限：設定=333 重整後實際={after_cap!r}\n"
        "（用來確認 table=10 號碼矩陣變體跟 table=0 變體是同一套 API 模型）",
        name="連碼 关连/共用自留上限 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_linked == (not original_linked)
    assert after_cap == "333"

    # 還原（CLAUDE.md §5）
    with allure.step("還原為原值並保存"):
        sp.set_relation_linked(original_linked)
        sp.set_shared_cap(original_cap)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("连码")
        assert sp.is_relation_linked() == original_linked
        assert sp.shared_cap_value() == original_cap


@allure.title("[功能驗證] B48-2：`table=10`（连码／不中／多选中一／特平中）變體第二樣本「不中」——確認「保存前必須勾選」這條規則對這個子變體同樣成立")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_number_grid_requires_selection(company_page):
    """B48-2：`table=10`（连码／不中／多选中一／特平中）變體第二樣本「不中」——確認「保存前必須勾選」
    這條規則對這個子變體同樣成立。
    （2026-08-31 案例重編號：舊編號 B22，見案例清單 §0.1）

    ⚠️ 跟 B21（連碼）的差異：連碼探索當下已經有既存勾選的號碼（可以不勾直接改
    关连/共用自留上限就成功保存），「不中」探索當下**完全沒有任何勾選**——
    直接改值保存會被「請選擇號碼或選項」擋下，補勾一個才成功，跟 B19 的規則一致。

    步驟：
    1. 導覽到飛單選項明細設置頁，切到「不中」分類
    2. 直接改「关连/不关连」「共用自留上限」→ 保存 → 預期被擋（不驗證這步的斷言，
       只在 write 版本補勾第一個「選擇」後才驗證持久化，避免依賴「當下没有勾選」
       這個易變的環境現況）
    3. 勾選「五不中」的「選擇」→ 改值 → 保存 → reload 驗證持久化
    4. 還原

    預期結果：
    - ✅ 已用網路攔截確認：`PUT /api/LayOffSettingDetail`，`gameId=markSix`，
      `playTypeId=miss5`，資料結構與 B19/B20/B21 一致
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁，切到「不中」分類（探索當下完全沒有勾選），記錄原值"):
        sp.goto()
        sp.select_category("不中")
        original_linked = sp.is_relation_linked()
        original_cap = sp.shared_cap_value()
        original_marked = sp.combo_item_marked(0)

    with allure.step("補勾「選擇」→ 改关连狀態與共用自留上限為 222 → 保存 → reload 重讀"):
        sp.set_relation_linked(not original_linked)
        sp.set_shared_cap("222")
        sp.set_combo_item_marked(0, True)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("不中")
        after_linked = sp.is_relation_linked()
        after_cap = sp.shared_cap_value()
        after_marked = sp.combo_item_marked(0)
    allure.attach(
        f"关连：設定={not original_linked} 重整後實際={after_linked}\n"
        f"共用自留上限：設定=222 重整後實際={after_cap!r}\n"
        f"選擇勾選：設定=True 重整後實際={after_marked}\n"
        "（確認「保存前必須先勾選」這條規則對 table=10 變體同樣成立）",
        name="不中 关连/共用自留上限 roundtrip",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_linked == (not original_linked)
    assert after_cap == "222"
    assert after_marked is True

    # 還原（CLAUDE.md §5）
    with allure.step("還原為原值並保存"):
        sp.set_relation_linked(original_linked)
        sp.set_shared_cap(original_cap)
        sp.set_combo_item_marked(0, original_marked)
        sp.save()
        page.wait_for_timeout(1000)
        page.reload()
        sp.goto()
        sp.select_category("不中")
        assert sp.is_relation_linked() == original_linked
        assert sp.shared_cap_value() == original_cap
        assert sp.combo_item_marked(0) == original_marked


@allure.title("[畫面驗證] B42：飛單選項明細設置三彩種分類比對：25 個分類清單是否一致")
@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_categories_consistent_across_games(company_page):
    """B42：確認 25 個分類清單在三彩種下是否一致（2026-08-31 從零設計新增，同 B27 全新軸線）。

    ⚠️ 這件事本身有意義：若三彩種分類組成不同，K7 案例（B43～B49）目前只在香港六合彩
    抽樣驗證的抽樣邏輯就需要重新評估——分類清單是抽樣的基礎，抽樣前要先確認基礎一致。

    ✅ 2026-08-31 實測：三彩種分類清單完全一致（皆 25 個，逐項比對也相同）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到飛單選項明細設置頁（預設香港六合彩），記錄分類清單"):
        sp.goto()
        hk_categories = sp.category_labels()
    with allure.step("切到英國天天彩，記錄分類清單"):
        sp.switch_game("英国天天彩")
        uk_categories = sp.category_labels()
    with allure.step("切到賓果六合彩，記錄分類清單"):
        sp.switch_game("宾果六合彩")
        bg_categories = sp.category_labels()
    with allure.step("切回香港六合彩（還原彩種選取狀態）"):
        sp.switch_game("香港六合彩")
    allure.attach(
        f"香港六合彩（{len(hk_categories)}）：{hk_categories}\n"
        f"英國天天彩（{len(uk_categories)}）：{uk_categories}\n"
        f"賓果六合彩（{len(bg_categories)}）：{bg_categories}\n"
        "（期望：三者皆 25 個且內容一致——K7 分類清單是玩法分類本身，理論上不隨彩種變化）",
        name="K7 三彩種分類比對",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(hk_categories) == 25
    assert uk_categories == hk_categories, "英國天天彩的分類清單與香港六合彩不同"
    assert bg_categories == hk_categories, "賓果六合彩的分類清單與香港六合彩不同"


@allure.title("[功能驗證] B43：飛單選項明細設置標準型代表樣本 roundtrip：特码／两面／五行／正特码")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_standard_type_cap_roundtrip(company_page):
    """B43：標準選項清單型（15 個分類，見 B41）用列數最大/最小/中位三個邊界點抽樣：
    特码（49 列，中位）／两面（62 列，最大）／五行（5 列，最小），2026-08-31 審查 K7
    案例覆蓋率時（見 testcase-design §6 手段3「有鑑別力的樣本」）額外補上「正特码」——
    這是唯一已知有 DOM 結構異常的分類（B18 記錄「頁面同時存在 2 個 table，1 個空表頭
    殘留」，見 POM `_table()` 檔頭），先前只被結構性掃描過（B26/B41），沒被納入過
    write_action 功能驗證——結構異常的分類最可能藏著功能 bug，正是該優先納入的樣本。
    2026-08-31 MCP 實測「正特码」roundtrip 正常，未發現異常，但值得固化成回歸測試。

    ⚠️⚠️ 2026-08-31 探索發現的前置依賴（先前沒有任何文件記載，卻是這三條案例能不能
    執行的關鍵前提）：K7 選項的「每選項自留上限」欄位**只有在頁面總開關「啟用飞单选项
    明细」開啟時才可編輯**（關閉時呈唯讀 `is-static`）。本案例因此需要先開啟總開關
    （會連動影響 K4，見 B38），測完再關回原狀。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    # ⚠️ 2026-08-31 實測修正：`option_row()` 是 1-based（不含表頭），傳 0 會取到表頭列
    # （`columnheader` 而非 `cell`，讀不到自留上限欄位、逾時失敗）——這裡一律用 1（第一個選項）。
    samples = [
        ("特码", 1, "1234", 49),
        ("两面", 1, "555", 62),
        ("五行", 1, "888", 5),
        ("正特码", 1, "2001", 49),
    ]

    with allure.step("導覽到飛單選項明細設置頁，開啟總開關（前提：選項欄位才可編輯），依序處理 4 個樣本：特码(49列)第1個選項改1234、两面(62列)第1個選項改555、五行(5列)第1個選項改888、正特码(49列，有DOM結構異常)第1個選項改2001"):
        sp.goto()
        master_original = sp.is_master_switch_enabled()
        if not master_original:
            sp.set_master_switch(True)
        assert sp.is_master_switch_enabled() is True

    report_lines = []
    for category, option_index, probe, expected_rows in samples:
        with allure.step(f"「{category}」分類：改第 {option_index} 個選項的自留上限為 {probe} → 保存 → reload 重讀"):
            sp.select_category(category)
            row_count = sp.option_row_count()
            original_cap = sp.option_cap_value(option_index)
            sp.set_option_cap(option_index, probe)
            sp.save()
            page.wait_for_timeout(1000)
            page.reload()
            sp.goto()
            sp.select_category(category)
            after_cap = sp.option_cap_value(option_index)
            report_lines.append(
                f"{category}：列數={row_count}（期望 {expected_rows}）原值={original_cap!r} "
                f"設定值={probe!r} reload 後實際={after_cap!r}"
            )
            assert row_count == expected_rows, f"{category} 列數預期 {expected_rows}，實際 {row_count}"
            assert after_cap == probe, f"{category} 自留上限 roundtrip 失敗：設定 {probe!r}，reload 後 {after_cap!r}"

        with allure.step(f"還原「{category}」第 {option_index} 個選項的自留上限為原值"):
            sp.set_option_cap(option_index, original_cap)
            sp.save()
            page.wait_for_timeout(1000)

    allure.attach("\n".join(report_lines), name="標準型四樣本 roundtrip", attachment_type=allure.attachment_type.TEXT)

    with allure.step("還原總開關為原狀"):
        sp.goto()
        sp.set_master_switch(master_original)
        assert sp.is_master_switch_enabled() == master_original


@allure.title("[邏輯驗證] B49：飛單選項明細設置比大小：「共用自留上限將存為 0」聲明是否對已勾選組合也成立")
@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_compare_shared_cap_declaration(company_page):
    """B49：畫面規則說明寫「此设定下共用自留上限将存为 0，该玩法所有组合无条件全飞」——
    實測 payload 驗證這句「所有組合」是否真的包含已勾選的組合（2026-08-31 從零設計新增）。

    ⚠️⚠️ 2026-08-31 結論：**聲明不精確**——只對**未勾選**的組合成立（`retentionCap`
    強制為 0）；已勾選的組合可以自訂非 0 值，不受「全飛」限制（這正是「選擇」checkbox
    存在的意義：讓操作者能個別處理特定組合的例外值）。不判定為缺陷：行為本身合理，
    只是文案用了「所有組合」這樣的全稱語句，沒有排除已勾選的例外情況。

    ⚠️ 另一項實測修正：「共用自留上限」欄位是**真的共用**——保存時會把當下輸入值套用到
    **全部目前已勾選**的組合，不是只套用到「這次操作」的那一項。第一版案例沒有先清空
    既有勾選（環境裡「特码」項當時仍是先前案例留下的已勾選基準狀態），導致保存時
    「正1特」與「特码」兩項都被設成同一個共用值，誤以為是缺陷，後來才確認是漏了
    「先清空所有勾選」這個前置步驟。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到 K7，切到「比大小→一比一」，清空「正1特」以外的既有勾選避免殘留干擾"):
        sp.goto()
        sp.select_category("比大小")
        # ⚠️ 2026-08-31 實測發現：一旦所有組合列同時變成「無勾選」，共用上限欄位／保存
        # 邏輯需要的重新整備時間比單次操作長很多，緊接著馬上勾選＋改值＋保存會讓保存
        # 送不出 PUT（`expect_request` 逾時）。改成**全程至少保留「正1特」勾選**、
        # 只清掉其餘列，避免中途經過「零勾選」這個過渡狀態。
        if not sp.combo_item_marked(0):
            sp.set_combo_item_marked(0, True)
        for i in range(1, 7):
            if sp.combo_item_marked(i):
                sp.set_combo_item_marked(i, False)

    with allure.step("共用自留上限設為 500 → 保存，攔截 PUT payload"):
        sp.set_shared_cap("500")
        with page.expect_request(
            lambda r: r.method == "PUT" and "LayOffSettingDetail" in r.url, timeout=10000
        ) as req_info:
            sp.save()
        payload = req_info.value.post_data_json
        page.wait_for_timeout(500)

    marked_items = [item for item in payload["items"] if item["isMarked"]]
    unmarked_items = [item for item in payload["items"] if not item["isMarked"]]
    allure.attach(
        f"已勾選項（{len(marked_items)} 項）：{marked_items}（期望：retentionCap=500，不受「全飛」限制）\n"
        f"未勾選項（{len(unmarked_items)} 項）：{unmarked_items}（期望：retentionCap 全為 0，符合畫面聲明）\n"
        "→ 結論：畫面文字「所有組合無條件全飛」對已勾選組合不成立，聲明不夠精確但非缺陷",
        name="比大小共用自留上限聲明驗證",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(marked_items) == 1
    assert marked_items[0]["retentionCap"] == 500, "已勾選項的自訂值未被保留，與探索確認的行為不同"
    assert all(item["retentionCap"] == 0 for item in unmarked_items), "未勾選項未強制歸零，聲明連這部分也不成立"

    with allure.step("還原：取消勾選「正1特」，改勾選「特码」並將共用自留上限設為 0（環境基準狀態）"):
        sp.set_combo_item_marked(0, False)
        sp.set_combo_item_marked(6, True)
        sp.set_shared_cap("0")
        sp.save()
        page.wait_for_timeout(1000)


@allure.title("[畫面驗證] B38：K7 總開關開啟後，切回 K4 觀察「開啟飛單選項明細設定」開關是否受影響")
@allure.suite("飞单设置")
@pytest.mark.write_action
def test_k7_master_switch_effect_on_k4_detail_toggle(company_page):
    """B38：K7 總開關開啟時的確認框宣告「原系統設定－飛單設定中，飛單設定的金額將會
    失效，並且自動出貨將變更為手動模式」——過去從未在 K4 頁面實際驗證過這句宣告是否兌現
    （2026-08-31 從零設計新增）。

    ⚠️⚠️ 2026-08-31 結論修正（重要）：**手動 MCP 探索時曾觀察到 K4 的明細設定開關點擊
    無效**，但用受控的 pytest 自動化重新驗證（含正確等待與乾淨的前置狀態）**無法重現**——
    K4 的開關實測仍可正常切換。**先前的「凍結」結論予以撤回**，判定是手動探索當下快速
    連續操作、缺乏足夠等待造成的操作假象（同一類問題也曾誤導 B49 的初次探索）。
    真正的結論是：**K7 總開關開啟後，K4 側在 UI 層面沒有觀察到變化**——這句宣告很可能
    只在後端邏輯生效，前端完全無感知。此為 D 級快照記錄；要進一步確認「後端是否真的
    忽略 K4 金額設定」需要真實下注情境（屬 B51/B52 真生效系列，⛔ 待前置）。
    """
    page = company_page
    detail_sp = LayOffDetailSettingPage(page)
    setting_sp = SystemSettingPage(page)
    row = "正码"

    with allure.step("開啟 K7 總開關（會跳確認框，點確定）"):
        detail_sp.goto()
        master_original = detail_sp.is_master_switch_enabled()
        if not master_original:
            detail_sp.set_master_switch(True)
        assert detail_sp.is_master_switch_enabled() is True

    with allure.step("切到 K4「飞单设置」頁，嘗試切換「正码」列的明細設定開關"):
        setting_sp.goto("飞单设置")
        before = setting_sp.is_lay_off_detail_mode_enabled(row)
        setting_sp.set_lay_off_detail_mode(row, not before)
        page.wait_for_timeout(500)
        after_click = setting_sp.is_lay_off_detail_mode_enabled(row)
    allure.attach(
        f"點擊前：{before}\n嘗試切換為：{not before}\n點擊後實際：{after_click}\n"
        "（現況記錄，不預設「應該」凍結或「應該」可切換——K7 開啟只在後端聲明會讓 K4 金額失效，"
        "沒有聲明前端 UI 層面要有什麼變化。2026-08-31 實測：開關可正常切換，無凍結現象）",
        name="K7 總開關對 K4 明細設定開關的影響",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_click == (not before), (
        "K4 明細設定開關在 K7 總開關開啟時無法切換——如重現此結果，代表「凍結」現象其實存在，"
        "需要重新檢討本案例的結論與交接檔記錄"
    )

    with allure.step("還原「正码」明細設定為原值（純前端切換，不需保存，見 B34 已證實的行為）"):
        setting_sp.set_lay_off_detail_mode(row, before)
        assert setting_sp.is_lay_off_detail_mode_enabled(row) == before

    with allure.step("關閉 K7 總開關為原狀"):
        detail_sp.goto()
        detail_sp.set_master_switch(master_original)
        assert detail_sp.is_master_switch_enabled() == master_original


@allure.title("[畫面驗證] B54：觀察交接檔 T12 週期性自動導回是否影響 K7（飛單選項明細設置）多步驟保存流程")
@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_page_stable_during_extended_dwell(company_page):
    """B54：交接檔 T12 記錄站台會約十幾到數十秒背景自動整頁導回「游戏规则」頁、未保存的
    表單會被清空——先前沒有人把這個現象跟 K7「選分類→勾選→設值→保存」這種天生需要停留
    較久的多步驟流程連起來看過（2026-08-31 從零設計新增）。

    ⚠️ 2026-08-31 探索結果：在 K7 頁面停留 25 秒無操作，未觀察到自動導回。**這是否定性
    結果，不代表 T12 不存在**——時間盒不夠長，或觸發條件不只是「停留」。本案例先記錄
    「25 秒內未重現」的事實，作為 regression 基準；若之後要下更強的結論，需要更長的
    觀察時間盒或更多樣本。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到 K7 頁，記錄目前 URL"):
        sp.goto()
        url_before = page.url

    with allure.step("停留 25 秒不做任何操作"):
        page.wait_for_timeout(25_000)

    url_after = page.url
    allure.attach(
        f"停留前 URL：{url_before}\n停留 25 秒後 URL：{url_after}（期望：不變；若跳到 /rule 即重現 T12）",
        name="T12 觀察（25 秒時間盒）",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert url_after == url_before, "頁面在無操作情況下被導向別處，重現了交接檔 T12 的現象"


@allure.suite("公告管理")
@pytest.mark.smoke
def test_announcement_table_visible(company_page):
    """確認公告管理頁的表格欄位都在（不編輯，先只驗證讀取到位）。

    步驟：
    1. 導覽到「系统设置→公告管理」子頁面
    2. 確認表格欄位「标题」存在

    預期結果：
    - 「标题」欄位應該存在，且目前顯示「暫無數據」（探索當下現況，尚無任何公告）

    oracle 來源：D 級（探索當下實測），regression 用途。「新增」按鈕是 write action，
    本案例不點擊。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→公告管理」子頁面"):
        sp.goto("公告管理")
    with allure.step("確認表格欄位「标题」與「暂无数据」是否顯示"):
        header_visible = page.get_by_role("columnheader", name="标题").is_visible()
        empty_visible = page.get_by_text("暂无数据").is_visible()
    allure.attach(
        f"「标题」欄位顯示：{header_visible}（期望 True）\n「暂无数据」顯示：{empty_visible}（期望 True，探索當下現況）",
        name="公告管理頁結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert header_visible
    assert empty_visible
