"""賠率差分抽驗：每層每彩種一個代表欄，保存判定及超位小數待確認分開記錄。"""
import json
import os

import allure
import pytest

from xzh_qa.odds_gap_flows import run_save_flow, check_boundary_inputs

REPRESENTATIVES = {
    'markSix': 'bonusNumberA:oddsGap',
    'ukLucky7': 'pickTwoHitBonus:subOddsGap',
    'bingo6': 'sevenNumberOdd0:oddsGap',
}


@pytest.mark.write_action
@pytest.mark.parametrize('index', range(10))
@allure.suite('賠率差分代表欄抽驗')
@allure.step('直屬上級核對三彩種代表主欄、副欄與七碼的保存、超位小數觀察及還原')
def test_odds_gap_smoke_parent(index, gap_context, odds_gap_manifest, odds_gap_run, monkeypatch):
    """前置條件：QAT指定帳號鏈，保存與授權操作均須受控還原。
    操作步驟：直屬上級逐彩種取一般主欄、副欄、七碼代表，驗保存並觀察超位小數處理。
    預期結果：保存重載與相對剩餘正確，超位小數規則待確認列BLOCKED，原值完整還原。
    佐證方式：逐步JSON與journal；本案例為抽測，不宣稱全玩法通過。
    """
    ctx = gap_context(index, via='parent')
    results = []
    for game, representative in REPRESENTATIVES.items():
        # 本輪一級香港已由warmup保存及截斷案例覆蓋，避免重複計數。
        if index == 0 and game == 'markSix' and os.environ.get('XZH_GAP_SMOKE_WARMUP_DONE') == '1':
            continue
        monkeypatch.setenv('XZH_GAP_FIELDS', representative)
        monkeypatch.setenv('XZH_GAP_GAMES', game)
        monkeypatch.setenv('XZH_GAP_BOUNDARY_INPUTS', json.dumps(['-0.12346']))
        for kind in ('save', 'truncate'):
            record = {'level': index+1, 'via': 'parent', 'game': game, 'field': representative, 'check': kind}
            try:
                if kind == 'save':
                    result = run_save_flow(ctx, game, odds_gap_manifest)
                    assert result['saved_all_ok'] and result['step_ok'] and result['delta_all_ok'] and result['restored']
                else:
                    result = check_boundary_inputs(ctx, game, odds_gap_manifest)
                    assert result['legal'] and all(item['ok'] for item in result['legal'])
                record['status'] = 'PASS'
            except pytest.skip.Exception as exc:
                record.update(status='BLOCKED', reason=str(exc))
            except Exception as exc:
                record.update(status='FAIL', reason=str(exc))
            results.append(record)
            odds_gap_run.dump('smoke-results.json', results)
            print(f"SMOKE level={index+1} {game} {kind}: {record['status']}", flush=True)
            if getattr(odds_gap_run, 'restore_pending', False):
                pytest.exit('還原異常，停止後續寫入；見restore-pending與停止標記', returncode=2)
    allure.attach(json.dumps(results, ensure_ascii=False), '抽驗分項結果；超位小數待確認列BLOCKED，實值詳各彩種附件', allure.attachment_type.JSON)
    assert not any(r['status'] == 'FAIL' for r in results), '抽測不符，見smoke-results.json'
    if any(r['status'] == 'BLOCKED' for r in results):
        pytest.skip('抽測部分受阻，詳逐項结果')


@pytest.mark.write_action
@allure.suite('賠率差分代表欄抽驗')
@allure.step('公司操作二級香港特碼A，獨立核對保存回應與還原，不改走直屬上級')
def test_odds_gap_smoke_company_lower(gap_context, odds_gap_manifest, odds_gap_run, monkeypatch):
    """前置條件：公司操作二級，與直屬上級路徑分開判定。
    操作步驟：香港特碼A代表欄輸入、保存及重載，異常亦重讀並受控還原。
    預期結果：保存成功、重載保留、原值還原；403如實FAIL，不換上級冒充通過。
    佐證方式：save-failed或result及journal，本案例不擴大重複相同403。
    """
    monkeypatch.setenv('XZH_GAP_FIELDS', 'bonusNumberA:oddsGap')
    monkeypatch.setenv('XZH_GAP_GAMES', 'markSix')
    try:
        result = run_save_flow(gap_context(1, via='company'), 'markSix', odds_gap_manifest)
        allure.attach(json.dumps(result, ensure_ascii=False, default=str), '公司路徑實值與預期；成功回應應為200或204', allure.attachment_type.JSON)
    finally:
        allure.attach(str(odds_gap_run.dir), '公司路徑原始回應、快照及還原journal位置', allure.attachment_type.TEXT)
