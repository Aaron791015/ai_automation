"""唯讀驗算三彩種十層剩餘差分，排除UI顯示小數位判定。"""
import json
import time
from decimal import Decimal
from pathlib import Path

import allure
import pytest

from xzh_qa.odds_gap_cap_source import read_platform_cap
from xzh_qa.odds_gap_client import GAMES
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS


def calculate(data):
    checks = []
    rate = data.get('independent_rate')
    for game in GAMES:
        maps = [{r['playTypeId']: r for r in level['games'][game]} for level in data['levels']]
        stable = data['odds_before'][game] == data['odds_after'][game] and all(
            level['games'][game] == after['games'][game]
            for level, after in zip(data['levels'], data['levels_after']))
        for index, rows in enumerate(maps):
            for play_id, row in rows.items():
                for sub in range(2 if row.get('subOddsLabel') is not None else 1):
                    gap = 'subOddsGap' if sub else 'oddsGap'
                    remaining = 'remainingSubOddsGap' if sub else 'remainingOddsGap'
                    item = {'level': index+1, 'account': CHAIN_ACCOUNTS[index], 'game': game,
                            'play': row['playTypeName'], 'play_id': play_id, 'field': gap,
                            'absolute': 'BLOCKED', 'relative': 'NOT_APPLICABLE' if index == 0 else 'BLOCKED',
                            'stable': stable}
                    checks.append(item)
                    if not stable:
                        item['reason'] = '讀取前後來源異動，不能混用不同時間的值'
                        continue
                    try:
                        # None不是已知零值；缺來源不得假通過。
                        chain = [Decimal(str(m[play_id][gap])) for m in maps[:index+1]]
                        actual = Decimal(str(row[remaining]))
                        assert actual.is_finite() and all(v.is_finite() for v in chain)
                        item.update(actual=str(actual), own_gap=str(chain[-1]),
                                    ancestor_sum=str(sum(chain[:-1], Decimal(0))))
                        if index:
                            parent_remaining = Decimal(str(maps[index-1][play_id][remaining]))
                            expected_relative = parent_remaining + chain[-1]
                            item.update(relative='PASS' if expected_relative == actual else 'FAIL',
                                        parent_remaining=str(parent_remaining), relative_expected=str(expected_relative))
                        setting = data['odds_before'][game][play_id]
                        base = Decimal(str(setting['subOdds' if sub else 'odds']))
                        low_raw = setting.get('subMinOdds') if sub else setting.get('minOdds')
                        if sub and low_raw is None:
                            low_raw = setting.get('minOdds')
                        low = Decimal(str(low_raw))
                        assert base.is_finite() and low.is_finite()
                        cumulative = sum(chain, Decimal(0))
                        assumed = (base-low)*Decimal('0.8')+cumulative
                        item.update(base=str(base), minimum=str(low), diagnostic_rate='0.8',
                                    diagnostic_expected=str(assumed), diagnostic_matches=assumed == actual)
                        if rate is not None:
                            expected = (base-low)*Decimal(str(rate))+cumulative
                            item.update(absolute='PASS' if expected == actual else 'FAIL', expected=str(expected))
                        else:
                            item['reason'] = '缺平台上限比例独立來源；0.8僅條件驗算'
                    except (KeyError, ValueError, ArithmeticError, AssertionError) as exc:
                        item['reason'] = f'缺少完整有限數值來源：{type(exc).__name__}'
    return checks


@pytest.mark.smoke
@allure.step('唯讀取得同彩種十層差分、基準與最低賠率，驗算剩餘並獨立核對平台比例來源')
def test_odds_gap_remaining_readonly(gap_context, odds_gap_run):
    """前置條件：QAT允許的aaa111～aaa010鏈及公司唯讀基準資料。
    操作步驟：UI逐層確認帳號ID，GET三彩種差分與基準，讀前後來源並以Decimal獨立驗算。
    預期結果：各層剩餘符合自身與祖先差分累加；平台比例缺失時絕對公式列BLOCKED。
    佐證方式：完整來源、逐欄算式；不輸入、不保存、不下注、不判UI顯示位數。
    """
    started = time.monotonic()
    data = {'levels': [], 'levels_after': [], 'independent_rate': None}
    first = gap_context(0, via='company')
    client = first.client
    rate, independent = client.cap_rate()
    data['company_cap_evidence'] = client.cap_rate_evidence
    data['company_status'] = client.company_status()
    if independent:
        assert Decimal(0) <= rate <= Decimal(1)
        data['independent_rate'] = str(rate)
    data['odds_before'] = {game: client.odds_setting(game) for game in GAMES}
    for index in range(10):
        ctx = first if index == 0 else gap_context(index, via='company')
        ids = ctx.observed['target_user_ids']
        assert ids and len(set(ids)) == 1, 'UI目標ID缺少或不唯一'
        user_id = ids[-1]
        chain = client.share_ancestors(user_id)
        agents = [r for r in chain if r.get('level') != 'company']
        assert [r['account'] for r in agents] == CHAIN_ACCOUNTS[:index+1]
        assert agents[-1]['id'] == user_id
        record = {'account': ctx.account, 'id': user_id, 'chain': chain,
                  'games': {game: client.gap_setting(user_id, game) for game in GAMES}}
        assert all(record['games'].values())
        data['levels'].append(record)
        odds_gap_run.dump('remaining-source-partial.json', data)
        print(f'READ level={index+1} 三彩種完成', flush=True)
    data['odds_after'] = {game: client.odds_setting(game) for game in GAMES}
    for level in data['levels']:
        data['levels_after'].append({'account': level['account'],
                                    'games': {game: client.gap_setting(level['id'], game) for game in GAMES}})
    odds_gap_run.dump('remaining-source-partial.json', data)
    # 公司資料全部讀完，才切換到平台登入，避免同帳號互踢污染資料。
    try:
        evidence = read_platform_cap(first.page, Path(odds_gap_run.dir) / 'platform-cap-after.png')
        data['platform_cap_evidence'] = evidence
        before = data['company_cap_evidence']
        if not independent or Decimal(before['rate']) != Decimal(evidence['rate']):
            data['independent_rate'] = None
            data['platform_cap_error'] = '平台上限讀取前後不一致或缺少前值，完整公式BLOCKED'
    except Exception as exc:
        data['independent_rate'] = None
        data['platform_cap_error'] = str(exc)[:800]
    data['seconds'] = round(time.monotonic()-started, 2)
    odds_gap_run.dump('remaining-source.json', data)
    checks = calculate(data)
    odds_gap_run.dump('remaining-calculations.json', checks)
    allure.attach(json.dumps(checks, ensure_ascii=False), '剩餘差分逐欄算式、實值與來源受阻原因', allure.attachment_type.JSON)
    print(f'CALCULATED fields={len(checks)} evidence={odds_gap_run.dir}', flush=True)
    assert not any(r['relative'] == 'FAIL' or r['absolute'] == 'FAIL' for r in checks), '剩餘差分算式不符，見逐欄證據'
    if any(r['absolute'] == 'BLOCKED' for r in checks):
        pytest.skip('BLOCKED（部分）：詳逐欄相對公式結果；絕對公式缺獨立上限比例或完整輸入來源')
