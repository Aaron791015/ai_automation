# -*- coding: utf-8 -*-
"""報表選單案例（案例清單 E2b；2026-08-28 依子頁面補齊）。

📝 2026-08-28：原本跟「开奖号码」「注单数据」擠在同一份檔案（檔名跟內容對不上，
三條案例其實對應三個不同選單），依使用者指示拆成三個檔案：「开奖号码」移到
`test_draw_numbers.py`、「注单数据」移到 `test_bet_summary.py`，本檔只留「报表」這一條選單，
檔名跟內容終於一致。

「报表」底下是**真正的子頁面**：「占成报表」（預設落地，`/report/share`，依代理層級分組）／
「玩法报表」（`/report/play-type`，依「遊戲×玩法」分組，欄位比占成報表少「人数」、
多「贡献度」），比照 `test_system_setting.py` 的模式各自一條案例配靜態 `@allure.suite(...)`。
"""
from __future__ import annotations

import io
import json
import os
from datetime import date

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES, OddsGapClient
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec, settle_bet, sum_by_level
from xzh_qa.pages.dashboard_page import EmptyStatePage
from xzh_qa.pages.odds_gap_report_page import OddsGapReportPage
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS


@allure.suite("占成报表")
@pytest.mark.smoke
def test_share_report_page_loads(company_page):
    """E2b：「报表→占成报表」能正常載入並顯示表格。

    步驟：
    1. 導覽到「报表」頁（預設落地即占成報表）
    2. 等待畫面載入

    預期結果：
    - 頁面主要內容區應該正常顯示（不管有沒有實際資料）

    ⚠️ 2026-08-26 重跑 T9 時發現「報表→占成報表」已經有真實聚合資料
    （例如帳號 mimir1 已有 107 注、總投 225.00），跟首次探索當下「無資料」的現況不再一致——
    QAT 環境並非只有我們在用，有其他 session／使用者的活動會反映在這裡。這條案例因此
    只驗證頁面能正常載入並顯示表格，不斷言有無資料——那個假設已經不成立，
    見 `新綜合_驗證項目清單.md` H2/H3 附註。
    """
    page = company_page
    esp = EmptyStatePage(page)
    with allure.step("導覽到「报表」頁（預設落地即占成報表）並等待畫面載入"):
        esp.goto_report()
        page.wait_for_timeout(1500)
    with allure.step("讀取主要內容區是否顯示"):
        visible = page.get_by_role("main").is_visible()
    allure.attach(
        f"實際：main 區塊 {'顯示' if visible else '未顯示'}（期望：顯示）",
        name="占成報表頁面載入",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert visible


@allure.suite("玩法报表")
@pytest.mark.smoke
def test_play_type_report_page_loads(company_page):
    """E2b：「报表→玩法报表」能正常載入並顯示表格。

    步驟：
    1. 導覽到「报表→玩法报表」子頁面
    2. 等待畫面載入

    預期結果：
    - 頁面主要內容區應該正常顯示

    oracle 來源：D 級（探索當下已有真實資料，如「英国赛车／大小」1 注）——只驗證頁面
    能正常載入，不斷言有無資料（會隨每日下注情況變動）。
    """
    page = company_page
    esp = EmptyStatePage(page)
    with allure.step("導覽到「报表→玩法报表」子頁面並等待畫面載入"):
        esp.goto_play_type_report()
        page.wait_for_timeout(1500)
    with allure.step("讀取主要內容區是否顯示"):
        visible = page.get_by_role("main").is_visible()
    allure.attach(
        f"實際：main 區塊 {'顯示' if visible else '未顯示'}（期望：顯示）",
        name="玩法報表頁面載入",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert visible


@allure.suite("赔率差金额")
@allure.title('[邏輯驗證] B98：赔率差报表：會員中獎結算後，九層「赔率差金额」是否等於逐注計算合計')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@allure.step("沿報表下鑽，核對完整注單、凍結資料與九層收益")
def test_odds_gap_winning_report_amount_by_level(company_page):
    """平台案例：[邏輯驗證] B98：赔率差报表：會員中獎結算後，九層「赔率差金额」是否等於逐注計算合計
    前置條件：QAT 指定帳號鏈；XZH_GAP_REPORT_DAY 指定日期，預設當日；需完整已結算注單及可追溯凍結稽核。
    測試範圍：三彩種各自完整查詢範圍，範圍內全部注單、九層收益；每彩種至少一筆應得非零收益的中獎樣本。
    步驟：
    1. UI 選定日期、彩種與已結算狀態；逐層下鑽，依受益層核對 UI/API。
    2. 讀完會員注單所有分頁，核對報表會員數、注數及投注額，確認範圍一致。
    3. 核對凍結來源的注單ID、帳號鏈、彩種、期號、日期、結果及占成；逐注獨立驗算並與產品逐層實值比較。
    4. 依彩種彙總全部注單，逐一比較九層報表，不以部分合計比較整份報表。
    預期結果：remit(N)＝投注額−總控鏈前後兩段凍結佔成（非自營總控公司為零）−本級至九級凍結占成；贏局 gapMoney(N)＝remit(N)×凍結有效差，輸局與和局退本為零；實際逐注收益及完整合計均相符。
    佐證方式：Allure 完整查詢、來源檔、逐注識別與產品實值核對。
    已知問題：無注單、缺凍結來源、範圍不符或缺應得非零樣本均 BLOCKED；UI/API 同為零不能证明金額正確。phase-4 不在無部署證據下自行套用。
    """

    from xzh_qa.odds_gap_report_checks import run_report_check
    run_report_check(company_page)



@allure.suite("赔率差金额")
@allure.title('[邏輯驗證] B99：赔率差报表：輸局、退本或有效差為零時，報表是否不產生差分收益')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@allure.step("核對四種零收益條件與產品實際收益")
def test_odds_gap_zero_amount_conditions(company_page):
    """平台案例：[邏輯驗證] B99：赔率差报表：輸局、退本或有效差為零時，報表是否不產生差分收益
    前置條件：QAT 指定帳號鏈；有完整已結算範圍、凍結輸入及獨立產品結算實值。
    測試範圍：三彩種各自覆蓋輸局、和局退本、有效差為零、上繳額為零四種條件及對應收益層。
    步驟：
    1. UI 查詢並下鑽，讀取全部同範圍注單；核對ID、帳號鏈、彩種、日期、結算狀態及分頁完整性。
    2. 以凍結輸入獨立計算九層收益，每筆與 actualGapMoney 產品實值比較。
    3. 各彩種核對四種樣本是否齊全，再以完整範圍合計比較九層報表。
    預期結果：指定條件之對應層收益為零，且產品實際收益與独立期望一致；不能只驗 oracle 算出零。
    佐證方式：Allure 查詢範圍、注單ID、來源檔及實值比對；完整範圍核對共用 B98。
    已知問題：缺任一條件樣本列 BLOCKED；不以空資料或無注單當通過。
    """

    from xzh_qa.odds_gap_report_checks import run_report_check
    run_report_check(company_page, zero=True)



@allure.suite("赔率差金额")
@allure.title('[邏輯驗證] B100：赔率差报表：投注後修改差分並結算，舊注收益是否仍依凍結值計算')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@allure.step("下注A、修改設定、下注B、還原後等待自然結算並驗凍結值")
def test_odds_gap_report_uses_frozen_bet_values(browser, gap_context, odds_gap_run):
    """平台案例：[邏輯驗證] B100：赔率差报表：投注後修改差分並結算，舊注收益是否仍依凍結值計算
    前置條件：QAT 指定帳號鏈、有效 XZH_GAP_FROZEN_AUDIT 與 XZH_GAP_BET_PLAN，來源可隨自然結算更新。
    測試範圍：三彩種各至少一組可區分舊值與新值的 A/B 樣本，核對九層收益。
    步驟：
    1. 記錄會員設定原值，以既有前台 POM UI 下注 A，保留唯一注單ID；回應不明不重送。
    2. UI 修改差分並保存讀回，記錄修改完成時間；UI 下注 B，隨即以衝突守衛還原設定。
    3. 等待自然結算與唯讀稽核匯出，不操控共享期數；核對完整注單範圍及 A/修改/B 時序。
    4. 分別用下注時公司解析賠率、最低值、有效差及占成驗算，核對 A 保留舊值、B 保留新值與九層產品收益。
    預期結果：A/B 各自使用下注凍結值，具可辨別的收益差異；設定最終還原。僅歷史已結算報表不變不算完成。
    佐證方式：原值快照、保存與還原 journal、A/B 注單ID、來源匯出、時序及收益比對。
    已知問題：缺來源先 BLOCKED，不額外建立無法驗算的注單；等待逾時保留既有注單、不重送；僅設定環境變數不能判 PASS。
    """

    from xzh_qa.odds_gap_scenarios import run_ab
    run_ab(browser, gap_context, odds_gap_run)



def _share_rows_by_account(client, day, game, settled=True):
    """同範圍唯讀 API：`{下級帳號: 列}`；公司層不帶 parentId。"""
    rows = client.share_report(day, day, game_ids=[game],
                               settlement_state="settled" if settled else "unsettled")
    return {r["descendantAccount"]: r for r in rows}


@allure.suite("赔率差金额")
@allure.title('[邏輯驗證] B102：赔率差报表：公司層查詢已结算占成报表時，公司的「赔率差金额」是否皆為 0')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@allure.step("逐彩種查詢公司層已結算報表，核對公司的賠率差金額皆為 0，並確認同日一級代理層確有賠率差收益")
def test_odds_gap_company_level_amount_is_zero(company_page):
    """平台案例：[邏輯驗證] B102：赔率差报表：公司層查詢已结算占成报表時，公司的「赔率差金额」是否皆為 0
    前置條件：QAT 公司帳號；XZH_GAP_REPORT_DAY 指定日期（預設當日），該日一級代理 aaa111 下有已結算注單且一級代理層有非零賠率差收益；只讀，不下注、不改設定。
    測試範圍：英国天天彩、香港六合彩、宾果六合彩各自單獨查詢；公司層全部一級代理列，以及 aaa111 下一層的一級代理收益列。
    步驟：
    1. 公司後台進入「报表→占成报表」，選指定日期與「已结算」，依序只勾選單一彩種後按「查询」。
    2. 讀公司層每一列「公司」分組的「赔率差金额」，並與同範圍唯讀 API 的金額逐列比對。
    3. 點 aaa111 下鑽一層，以同範圍唯讀 API 確認一級代理層確有非零賠率差收益，畫面原始文字另存佐證。
    預期結果：公司層所有列的「赔率差金额」為 0，畫面與 API 一致（2026-09-29 新版文件：以公司為錨的賺取賠率差恆為 0，公司自身的差分收益已反映在較低的派彩）；同日 aaa111 層至少一列非零。
    佐證方式：逐彩種公司層畫面值／API 值、aaa111 層收益列與查詢條件的 JSON 附件。
    已知問題：某彩種當日 aaa111 層收益全為 0 或無注單時，該彩種列 BLOCKED，不以全 0 判通過；公司層任一列非 0 即判失敗。報表畫面金額的顯示位數沒有規格（2026-09-29 實測 aaa111 層 API 0.0815、畫面顯示 0），不在本案例判定。
    """
    page = company_page
    day = os.environ.get("XZH_GAP_REPORT_DAY", date.today().isoformat())
    observed = OddsGapClient.attach(page)
    report = OddsGapReportPage(page)
    failures, blocked, evidence, raw_rows = [], [], [], []
    for game in scope_games():
        with allure.step("只勾選單一彩種查詢已結算占成报表，讀公司層「赔率差金额」與 API 值"):
            report.goto()
            report.select_games([GAMES[game]])
            report.query(day, day, settled=True)
            client = OddsGapClient.from_page(page, observed)
            api = _share_rows_by_account(client, day, game)
            ui = report.gap_amounts() if api else {}
        company_rows = []
        for account, row in api.items():
            api_amount = row.get("oddsGapAmount")
            ui_amount = ui.get(account)
            company_rows.append({"account": account, "ui": str(ui_amount), "api": str(api_amount)})
            if api_amount is None or ui_amount is None:
                failures.append(f"{GAMES[game]}／{account}：公司層缺「赔率差金额」（畫面 {ui_amount}／API {api_amount}）")
            elif dec(api_amount) != 0 or ui_amount != 0:
                failures.append(f"{GAMES[game]}／{account}：公司層「赔率差金额」畫面 {ui_amount}／API {api_amount}，預期 0")
        proof = []
        if "aaa111" in api and api["aaa111"].get("canDrillDown"):
            with allure.step("點 aaa111 下鑽一層，確認同日一級代理層確有非零賠率差收益"):
                report.drill_into("aaa111")
                rows = client.share_report(day, day, game_ids=[game], parent_id=api["aaa111"]["descendantId"])
                # 一級代理層只用來證明「同日確有賠率差收益」：以唯讀 API 金額判定，畫面原始文字另存佐證；
                # 報表畫面的金額顯示位數未有規格，不在本案例判定。
                raw = report.read_table() if rows else {"leaf": [], "rows": []}
                proof = [{"account": r["descendantAccount"], "api": str(r.get("oddsGapAmount"))} for r in rows]
                raw_rows.append({"game": GAMES[game], "leaf": raw["leaf"], "rows": raw["rows"]})
        if not any(dec(r["api"]) != 0 for r in proof if r["api"] not in ("None", "")):
            blocked.append(f"{GAMES[game]}：{day} aaa111 層無非零賠率差收益，公司層為 0 不足以證明規則")
        evidence.append({"game": GAMES[game], "date": day, "company_level": company_rows, "aaa111_level": proof})
    allure.attach(json.dumps(evidence, ensure_ascii=False, indent=1), "公司層與 aaa111 層賠率差金額：實際 vs 預期 0",
                  allure.attachment_type.JSON)
    allure.attach(json.dumps(raw_rows, ensure_ascii=False, indent=1), "aaa111 層報表畫面原始文字",
                  allure.attachment_type.JSON)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    if blocked:
        pytest.skip("BLOCKED（部分）：" + "；".join(blocked))


@allure.suite("赔率差金额")
@allure.title('[畫面驗證] B103：赔率差报表：切換為「未结算」查詢占成报表時，是否不顯示「赔率差金额」欄')
@allure.severity(allure.severity_level.NORMAL)
@pytest.mark.smoke
@allure.step("逐彩種以「未结算」查詢占成报表，核對表頭不含「赔率差金额」")
def test_odds_gap_unsettled_report_hides_amount_column(company_page):
    """平台案例：[畫面驗證] B103：赔率差报表：切換為「未结算」查詢占成报表時，是否不顯示「赔率差金额」欄
    前置條件：QAT 公司帳號；XZH_GAP_REPORT_DAY 指定日期（預設當日）；只讀，不下注、不改設定。
    測試範圍：英国天天彩、香港六合彩、宾果六合彩各自單獨查詢；公司層占成报表表頭。
    步驟：
    1. 公司後台進入「报表→占成报表」，選指定日期與「未结算」，依序只勾選單一彩種後按「查询」。
    2. 讀報表表頭的所有欄名，確認含「投注金额」的報表表格已顯示。
    3. 同條件改選「已结算」查詢一次，確認已结算時表頭有「赔率差金额」作為對照。
    預期結果：「未结算」查詢的表頭不含「赔率差金额」；「已结算」查詢的表頭含「赔率差金额」（2026-09-29 新版文件：未結算模式不提供此欄，需結算結果才算得出）。
    佐證方式：逐彩種未结算與已结算的表頭欄名及未结算 API 回傳欄位的 JSON 附件。
    已知問題：找不到含「投注金额」的報表表格時列 BLOCKED，不以找不到欄位判通過。
    """
    page = company_page
    day = os.environ.get("XZH_GAP_REPORT_DAY", date.today().isoformat())
    observed = OddsGapClient.attach(page)
    report = OddsGapReportPage(page)
    headers_js = """() => [...document.querySelectorAll('table')]
        .map(t => [...t.querySelectorAll('thead th')].map(th => th.innerText.trim()))
        .filter(h => h.includes('投注金额'))"""
    failures, blocked, evidence = [], [], []
    for game in scope_games():
        with allure.step("以「未结算」查詢單一彩種占成报表並讀取表頭欄名"):
            report.goto()
            report.select_games([GAMES[game]])
            report.query(day, day, settled=False)
            unsettled = page.evaluate(headers_js)
            client = OddsGapClient.from_page(page, observed)
            api_keys = sorted({k for r in client.share_report(day, day, game_ids=[game], settlement_state="unsettled")
                               for k in r})
        with allure.step("同條件改以「已结算」查詢，讀取表頭欄名作為對照"):
            report.query(day, day, settled=True)
            settled = page.evaluate(headers_js)
        evidence.append({"game": GAMES[game], "date": day, "unsettled_headers": unsettled,
                         "settled_headers": settled, "unsettled_api_fields": api_keys})
        if not unsettled or not settled:
            blocked.append(f"{GAMES[game]}：找不到含「投注金额」的報表表格")
            continue
        if any("赔率差金额" in h for table in unsettled for h in table):
            failures.append(f"{GAMES[game]}：「未结算」查詢仍顯示「赔率差金额」欄")
        if not any("赔率差金额" in h for table in settled for h in table):
            failures.append(f"{GAMES[game]}：「已结算」查詢沒有「赔率差金额」欄，對照條件不成立")
    allure.attach(json.dumps(evidence, ensure_ascii=False, indent=1), "未结算／已结算表頭：實際 vs 預期",
                  allure.attachment_type.JSON)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    if blocked:
        pytest.skip("BLOCKED（部分）：" + "；".join(blocked))
