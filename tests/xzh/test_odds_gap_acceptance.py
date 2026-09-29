"""本輪可分批續跑的賠率差驗收入口；每層、彩種、路徑各自留下結果。"""
import os
import json

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES
from xzh_qa.odds_gap_flows import run_save_flow, check_boundary_inputs, scope_games, load_ancestor_rows


def levels():
    raw = os.environ.get("XZH_GAP_LEVELS", "1,2,9,10")
    values = [int(x)-1 for x in raw.split(",")]
    assert values and len(set(values)) == len(values) and all(0 <= i < 10 for i in values), "層級須1～10且不可重複（10為會員）"
    return values


def route_scopes():
    vias = os.environ.get('XZH_GAP_VIAS', 'company,parent').split(',')
    assert vias and len(vias)==len(set(vias)) and set(vias)<= {'company','parent'}, '操作路徑非法或重複'
    return [(i,v) for i in levels() for v in vias if not (i==0 and v=='parent' and 'company' in vias)]


@allure.suite("賠率差分分批驗收")
@allure.title("B90＋B92：逐欄保存重載、剩餘公式與還原")
@pytest.mark.write_action
@pytest.mark.parametrize("game", scope_games())
@pytest.mark.parametrize("index,via", route_scopes())
@allure.step("讀取同彩種祖先設定，驗保存、剩餘與受控還原")
def test_save_and_remaining_by_scope(index, via, game, gap_context, odds_gap_manifest, odds_gap_run):
    """前置條件：QAT 指定帳號鏈、授權已成立；本輪設定值需還原。
    操作步驟：UI 確認目標後唯讀取得同彩種祖先設定，再輸入目標欄、加減、保存重載及還原。
    預期結果：輸入與保存一致、剩餘符合完整公式、未改欄不變、最終還原。
    佐證方式：逐欄算式與 run journal；受阻欄不計入通過。
    已知問題：公司與parent各自獨立收集，403失敗不抵銷或略過其他路徑。
    """
    ctx = gap_context(index, via=via)
    ctx.ancestor_rows = load_ancestor_rows(ctx, game)
    result = run_save_flow(ctx, game, odds_gap_manifest, verify_remaining_formula=True)
    allure.attach(json.dumps(result, ensure_ascii=False, default=str), "本組逐欄結果", allure.attachment_type.JSON)
    assert result["saved_all_ok"] and result["step_ok"], "輸入／步進／保存不符"
    assert result["delta_all_ok"] and not result["untouched_changed"], "剩餘變化或控制組不符"
    assert result["restored"], "未完整還原"
    if result["blocked"]:
        pytest.skip(f"BLOCKED（部分）：未測欄 {result['blocked']}")
    if not result["cap_rate_independent"]:
        pytest.skip("BLOCKED（部分）：保存及相對變化已驗；未取得平台實際上限比例，絕對公式不判通過")
    if not result["ancestors_available"]:
        pytest.skip("BLOCKED（部分）：保存與相對變化已驗，同彩種完整祖先來源受阻")
    assert result["remaining_all_ok"], "剩餘完整公式不符"


@allure.suite("賠率差分分批驗收")
@allure.title("B91：依所選欄位模式驗輸入條件與還原")
@pytest.mark.write_action
@pytest.mark.parametrize("game", scope_games())
@pytest.mark.parametrize("index,via", route_scopes())
@allure.step("依full/sample實際範圍輸入邊界值，每次保存後立即核對與還原")
def test_boundary_by_scope(index, via, game, gap_context, odds_gap_manifest, odds_gap_run):
    """前置條件：以本組via指定身分登入，依full/sample選擇主／副欄。
    操作步驟：逐條輸入、保存讀回，每次完成後還原；另輸入超過剩餘差分的值（取至四位小數）保存讀回。
    預期結果：合法值保存正確、正數不得生效；超扣可保存且讀回等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣）；未定義處理不自行推定。
    佐證方式：每條輸入的畫面值、回應與還原日誌。
    已知問題：超位小數處置仍待確認；文字／空值處理仍待確認；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    """
    try:
        result = check_boundary_inputs(gap_context(index, via=via), game, odds_gap_manifest)
    finally:
        allure.attach(f"本組層級={index+1}，彩種={game}；各輸入與還原詳見 {odds_gap_run.dir}",
                      "B91實際範圍與佐證", allure.attachment_type.TEXT)
    assert all(r["ok"] for r in result["legal"]), "合法輸入讀回不符"
    assert not result["positive_persisted"], "正數已成為有效差分"
    if result["undefined"]:
        pytest.skip("BLOCKED（部分）：明確值已檢查；超位小數；文字／空值等處理仍待規格裁定，見附件")


@allure.suite("賠率差分分批驗收")
@allure.title("B88：逐對上下級授權切換、保留與投注效果")
@pytest.mark.write_action
@pytest.mark.parametrize("index", range(9))
@allure.step("每對獨立執行授權切換並還原，缺投注證據分開列受阻")
def test_authorization_by_pair(index, browser, gap_context, odds_gap_run):
    """前置條件：QAT 指定帳號鏈，記錄每對授權與三彩種設定原值。
    步驟：關閉授權、讀回、核對設定保留，再恢復並讀回；有凍結來源時新投注驗生效。
    預期結果：設定與授權還原；投注關閉／恢復效果需獨立凍結證據，缺資料不能完整通過。
    佐證方式：每對 b88-pairs.json、授權快照、journal 及投注來源。
    已知問題：父子對分開判定，一對受阻不跳過其他可獨立執行的關係。
    """
    from xzh_qa.odds_gap_scenarios import run_authorization
    try:
        run_authorization(browser, gap_context, odds_gap_run, indexes=[index])
    finally:
        allure.attach(f"父子對索引={index}；佐證 {odds_gap_run.dir}", "授權實際範圍", allure.attachment_type.TEXT)
