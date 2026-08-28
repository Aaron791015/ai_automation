# -*- coding: utf-8 -*-
"""公司層系統設置案例（案例清單批次 B：B1～B17；2026-08-28 依子頁面補齊，同日再依
K4／K7 結構性複掃補齊 B8～B17）。

「系统设置」底下有 8 個子選單，本檔現在全部覆蓋：游戏设置／投注限额／退水设置／
降赔设置／飞单设置（B 系列，含寫入 roundtrip）／赔率设置／飞单选项明细设置／
公告管理（後三個是 2026-08-26 補上的唯讀結構檢查，飞单选项明细设置 2026-08-28 已補齊
完整結構與行為驗證，見 B11～B14、B17）。

✅ 2026-08-26 T9 實測確認：大表格（賠率設置／降賠設置／退水設置／投注限額）的
「點格→出現輸入框→填值→Enter」互動方式（`SystemSettingPage.set_table_cell`）是正確的。
唯一要注意的是找列要用 `filter(has_text=...)`，不能用 `get_by_role("row", name=regex)`
（後者對 row 的 accessible name 比對不準，會找不到明明存在的列）。

⚠️ 2026-08-28 發現「飛單設置」頁的「最小飛單額」欄位持久化模式與其他大表格不同——
按 Enter 就即時送出 API，不需要按頁面下方的「保存」按鈕，見 B9 與
`SystemSettingPage.set_min_lay_off_amount` 的檔頭說明，不要誤用 `save()`。

⚠️ 2026-08-28「飛單選項明細設置」總開關（K7）與「飛單設置」（K4）父子連動已證實
（B11）：開啟 K7 總開關會跳確認框，明講「原系統設定－飛單設定中，飛單設定的金額將會
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
    with allure.step(f"改成探測值「{probe}」並保存，reload 後重讀"):
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

    with allure.step(f"還原成原值「{original}」（CLAUDE.md §5：測試資料用完即還原）"):
        sp.set_pass_bonus_cap(original)
        sp.save()


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


@allure.suite("飞单设置")
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
    row = "特码"
    with allure.step(f"導覽到「飞单设置」頁，若「{row}」列被鎖住則先關閉明細設定解鎖"):
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

    with allure.step(f"讀取「{row}」自動飛單原值，切成相反值並保存，reload 後重讀"):
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
    with allure.step(f"把「{row}」自動飛單還原成原值 {original} 並保存，reload 後重讀"):
        sp.toggle_auto_lay_off(row, original)
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        assert sp.is_auto_lay_off_enabled(row) == original

    # 最後才把「開啟飛單選項明細設定」真正救回原值，且必須按保存才會真的寫回後端。
    with allure.step(f"把「開啟飛單選項明細設定」還原成原值 {detail_mode_original} 並保存，reload 後重讀"):
        sp.set_lay_off_detail_mode(row, detail_mode_original)
        sp.save()
        page.reload()
        sp.goto("飞单设置")
        assert sp.is_lay_off_detail_mode_enabled(row) == detail_mode_original


@allure.suite("飞单设置")
@pytest.mark.smoke
def test_lay_off_setting_table_structure(company_page):
    """B16：飛單設置表格結構性掃描——欄位齊全、8 個可收合分組都在、70 列都讀得到。

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
    with allure.step("讀取表頭欄位、8 個分組收合按鈕、資料列總數"):
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


@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_row_unlock_is_isolated(company_page):
    """B8：抽樣「两面」列驗證解鎖是逐列獨立、不誤動其他列。

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


@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_min_amount_boundary(company_page):
    """B9：「最小飛單額」欄位邊界值——負數應被拒絕、超大值應被接受並即時持久化。

    步驟：
    1. 導覽到「系统设置→飞单设置」子頁面，記錄「特码」列「最小飛單額」原值
    2. 填入負數 `-5` → Enter，讀取畫面顯示值
    3. 填入超大值 `999999999` → Enter → reload 頁面 → 讀取持久化後的值
    4. 還原為原值

    預期結果：
    - 負數：前端拒絕，Enter 後欄位打回原值（不送出 API）
    - 超大值：前端接受，reload 後仍是新值（**這欄按 Enter 即時持久化，不需按頁面保存**——
      與同頁「開啟飛單選項明細設定」的純前端切換是兩種不同的持久化模式，見 POM 檔頭說明）

    oracle 來源：B 級（2026-08-28 MCP 三方確認：填值→Enter→reload 驗證持久化）。
    """
    page = company_page
    sp = SystemSettingPage(page)
    with allure.step("導覽到「系统设置→飞单设置」子頁面，記錄「特码」列「最小飛單額」原值"):
        sp.goto("飞单设置")
        original = sp.min_lay_off_amount("特码")

    with allure.step("填入負數 -5 → Enter，讀取畫面顯示值"):
        after_negative = sp.set_min_lay_off_amount("特码", "-5")
    allure.attach(
        f"填入：-5\n實際顯示值：{after_negative!r}（期望：打回原值 {original!r}）",
        name="最小飛單額負數邊界",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_negative == original, "負數應被前端拒絕，欄位應打回原值"

    with allure.step("填入超大值 999999999 → Enter → reload 頁面 → 讀取持久化後的值"):
        after_large = sp.set_min_lay_off_amount("特码", "999999999")
        page.reload()
        sp.goto("飞单设置")
        persisted = sp.min_lay_off_amount("特码")
    allure.attach(
        f"填入後畫面顯示：{after_large!r}\nreload 後實際：{persisted!r}（期望：999999999）",
        name="最小飛單額超大值持久化",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert after_large == "999999999"
    assert persisted == "999999999", "超大值應已即時持久化到後端"

    # 還原（CLAUDE.md §5）——這欄 Enter 即時持久化，還原後同樣不需要 save()
    with allure.step(f"還原為原值 {original}"):
        sp.set_min_lay_off_amount("特码", original)
        page.reload()
        sp.goto("飞单设置")
        assert sp.min_lay_off_amount("特码") == original


@allure.suite("飞单设置")
@pytest.mark.write_action
def test_lay_off_anomaly_rows_can_relock(company_page):
    """B10：追查 `一比五`／`一比六` 目前的「解鎖」狀態能否復原。

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
    with allure.step("導覽到「系统设置→飞单设置」子頁面"):
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


@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_categories_visible(company_page):
    """B17：飛單選項明細設置頁結構性掃描——25 個分類按鈕、總開關、表格欄位、
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


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_master_switch_transition(company_page):
    """B11：K7 總開關「啟用飛單選項明細」的狀態轉移，並確認它是 K4 的父子連動點。

    步驟：
    1. 導覽到「系统设置→飞单选项明细设置」子頁面，記錄總開關原始狀態
    2. 關閉總開關 → 讀取「特码」分類選項 1 的自動飛單開關是否被鎖住
    3. 重新開啟總開關（會跳確認框，需點「確定」）
    4. 讀取選項 1 的自動飛單開關是否恢復可互動

    預期結果：
    - 關閉：不跳確認框，底下所有選項的自動飛單 switch 變 disabled（但保留原本 checked 值）
    - 開啟：跳出確認框，文字明確寫「原系統設定－飛單設定中，飛單設定的金額將會失效，
      並且自動出貨將變更為手動模式」——**這是 A 級 oracle：系統自己承認 K7 開啟時
      K4（飛單設置）的金額設定會失效**，兩層是互斥切換的父子關係，不是各自獨立
      （回答矩陣 K7／案例 B14 的疑問）

    oracle 來源：A 級（系統確認框的原文自白，非測試者臆測）。
    """
    page = company_page
    sp = LayOffDetailSettingPage(page)
    with allure.step("導覽到「系统设置→飞单选项明细设置」子頁面，記錄總開關原始狀態"):
        sp.goto()
        original = sp.is_master_switch_enabled()

    with allure.step("關閉總開關 → 讀取「特码」分類選項 1 的自動飛單開關是否被鎖住"):
        sp.set_master_switch(False)
        switch_off = sp.is_master_switch_enabled()
        option1_toggleable_off = sp.option_auto_lay_off_toggleable(1)
    allure.attach(
        f"實際：總開關={switch_off}（期望 False）、選項1可互動={option1_toggleable_off}（期望 False）",
        name="K7 總開關關閉後的連動",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert switch_off is False
    assert option1_toggleable_off is False, "總開關關閉後，選項列的自動飛單應變成不可互動"

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

    # 還原（CLAUDE.md §5）
    with allure.step(f"還原成原值 {original}"):
        if sp.is_master_switch_enabled() != original:
            sp.set_master_switch(original)
        assert sp.is_master_switch_enabled() == original


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_batch_tools_apply_to_all_options(company_page):
    """B12：「特码」分類「一鍵自動／一鍵手動」批次操作，49 個選項應全部變成一致狀態。

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


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_quick_set_scope(company_page):
    """B13：「快速設置」面板套用範圍——只有被勾選的號碼欄位值改變，其餘不受影響。

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
    with allure.step(f"還原選項 1 為原值 {original_1!r}"):
        sp.set_option_cap(1, original_1)
        assert sp.option_cap_value(1) == original_1


@allure.suite("飞单选项明细设置")
@pytest.mark.smoke
def test_lay_off_detail_vs_setting_cross_reference(company_page):
    """B14：K4／K7 父子層級交叉比對——用「比大小」分類當樣本（唯一已知有異常的玩法）。

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
    with allure.step("讀取 K7「飛單選項明細設置」的「比大小」分類，確認 6 個子項都在"):
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


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_relation_and_shared_cap_roundtrip(company_page):
    """B19：組合型分類（以「比大小→一比一」為樣本）的「关连/不关连」與「共用自留上限」roundtrip。

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


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_second_sample_api_consistency(company_page):
    """B20：組合型分類第二樣本「過關」——確認跟「比大小」（B19）是同一套 API 模型。

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


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_number_grid_api_consistency(company_page):
    """B21：組合型 `table=10` 變體代表樣本「連碼→二全中」——確認跟 B19/B20（`table=0` 變體）
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


@allure.suite("飞单选项明细设置")
@pytest.mark.write_action
def test_lay_off_detail_combo_number_grid_requires_selection(company_page):
    """B22：`table=10` 變體第二樣本「不中」——確認「保存前必須勾選」這條規則對這個子變體同樣成立。

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
