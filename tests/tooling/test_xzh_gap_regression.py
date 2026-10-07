"""正式賠率差回歸的離線保護：不可錯價、錯期、超額、重送或把缺資料當PASS。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import runpy

import pytest

from xzh_qa.odds_gap_regression import (BatchLedger, validate_plan, price_request,
                                      read_bets, select_unique, frozen_checks, client_quote_matches,
                                      already_won)
from xzh_qa.odds_gap_regression_settlement import expected_settlement, check_settlement, revenue_matches


def plan(kind='minimum'):
    count = {'minimum': 2, 'branches': 1, 'ab': 2, 'authorization': 3}[kind]
    return {'batch_id': 'unit-batch', 'kind': kind, 'game': 'bingo6', 'panel': 'a',
            'options': ['tail-main'], 'amount': '1', 'max_bets': count, 'max_total': str(count)}


def source():
    issue = {'issueNumber': 123, 'status': 'open', 'isBettable': True,
             'closeTime': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
    row = {'playTypeId': 'tailNumberHit', 'baseOdds': '1.974', 'minOdds': '1.5792',
           'subMinOdds': '1.3', 'selectionOverrides': []}
    snapshot = {'gameId': 'bingo6', 'issueNumber': 123, 'playTypes': [row]}
    payload = {'gameId': 'bingo6', 'panelId': 'a', 'issueNumber': 123,
               'items': [{'playTypeId': 'tailNumberHit', 'selection': '1', 'betAmount': 1, 'clientOdds': '1.734'}]}
    return issue, snapshot, payload, row


@pytest.mark.parametrize('gap,phase,expected', [('-0.024', 'above', '1.734'), ('-0.06', 'floor', '1.5792')])
def test_minimum_uses_independent_floor_and_company_source(gap, phase, expected):
    issue, snapshot, payload, row = source()
    payload['items'][0]['clientOdds'] = expected
    _, result, minimum = price_request(plan(), {'option': 'tail-main', 'phase': phase}, payload, snapshot, issue, [gap]*10, row)
    assert str(result) == expected and minimum == '1.5792'


@pytest.mark.parametrize('change', ['game', 'panel', 'issue', 'selection', 'amount', 'price', 'closed', 'minimum', 'ambiguous'])
def test_send_guard_rejects_wrong_scope_or_unprovable_price(change):
    issue, snapshot, payload, row = source()
    pricing = deepcopy(row)
    if change == 'game': payload['gameId'] = 'markSix'
    if change == 'panel': payload['panelId'] = 'b'
    if change == 'issue': snapshot['issueNumber'] = 999
    if change == 'selection': payload['items'][0]['selection'] = '0'
    if change == 'amount': payload['items'][0]['betAmount'] = 2
    if change == 'price': payload['items'][0]['clientOdds'] = '1.8'
    if change == 'closed': issue['isBettable'] = False
    if change == 'minimum': pricing['minOdds'] = '1.2'
    attempt = {'option': 'tail-main', 'phase': 'floor' if change == 'ambiguous' else 'above'}
    with pytest.raises(AssertionError):
        price_request(plan(), attempt, payload, snapshot, issue, ['-0.024']*10, pricing)


def test_sub_branch_uses_override_and_sub_minimum():
    issue, snapshot, payload, row = source()
    p = plan('branches'); p['options'] = ['tail-sub']
    row['selectionOverrides'] = [{'selection': '0', 'odds': '2.1'}]
    payload['items'][0].update(selection='0', clientOdds='1.9')
    _, expected, minimum = price_request(p, {'option': 'tail-sub', 'phase': 'A'}, payload, snapshot, issue, ['-.02']*10, row)
    assert str(expected) == '1.90' and minimum == '1.3'


@pytest.mark.parametrize('actual,expected', [
    ('4.7109000000000005', '4.7109'),
    ('3.9675999999999996', '3.9676'),
    ('12.1661', '12.1661'),
])
def test_client_quote_accepts_only_ieee_transport_tail(actual, expected):
    assert client_quote_matches(actual, expected)


@pytest.mark.parametrize('actual', ['4.7108', '4.71', '4.710900001', 'NaN', 'Infinity'])
def test_client_quote_rejects_price_changes_and_nonfinite(actual):
    assert not client_quote_matches(actual, '4.7109')


def test_transport_tail_does_not_change_exact_odds_or_frozen_check():
    issue, snapshot, payload, row = source()
    row.update(baseOdds='4.8109', minOdds='3.8487')
    payload['items'][0]['clientOdds'] = 4.8109 - .1
    _, expected, _ = price_request(plan('branches'), {'option': 'tail-main', 'phase': 'A'},
                                   payload, snapshot, issue, ['-.01'] * 10, row)
    assert str(expected) == '4.7109'
    a = attempt()
    a['source']['baseOdds'] = '4.7209'
    r = record()
    r['odds'] = '4.7109000000000005'
    with pytest.raises(AssertionError):
        expected_settlement(a, r)


@pytest.mark.parametrize('key,value', [('batch_id', '../old'), ('amount', 0), ('amount', 'NaN'),
                                      ('max_bets', 99), ('max_total', 1), ('options', ['missing']),
                                      ('options', ['tail-main', 'tail-main']), ('game', 'markSix')])
def test_invalid_plan_fails_before_execution(key, value):
    p = plan(); p[key] = value
    with pytest.raises(AssertionError): validate_plan(p)


def test_sub_unset_plan_requires_same_play_main_and_sub_pair():
    """2026-09-29 新版文件：副差分未設即為 0；計畫須同一玩法主副各一注才能對照。"""
    p = plan('branches'); p.update(kind='sub-unset', options=['special-sub', 'special-main'], max_bets=2, max_total='2')
    assert validate_plan(p)['kind'] == 'sub-unset'
    for options in (['special-main', 'special-main-ox'], ['tail-sub', 'special-main'], ['special-sub']):
        bad = dict(p, options=options, max_bets=len(options), max_total=str(len(options)))
        with pytest.raises(AssertionError): validate_plan(bad)


def test_multi_round_plan_counts_rounds_in_approved_cap():
    """多期批次：批准上限＝選項×階段×期數；少算或多算期數都拒絕。"""
    p = plan('branches'); p.update(options=['tail-main', 'tail-sub'], rounds=5, max_bets=10, max_total='10')
    assert validate_plan(p)['rounds'] == 5
    p['max_bets'] = 2; p['max_total'] = '2'
    with pytest.raises(AssertionError): validate_plan(p)


@pytest.mark.parametrize('rounds', [0, 51, '3', 2.0])
def test_invalid_rounds_rejected(rounds):
    p = plan(); p['rounds'] = rounds
    with pytest.raises(AssertionError): validate_plan(p)


def test_already_won_only_counts_same_phase_option_settled_win():
    """只有同階段、同選項、且自然結算為中獎的既有注單，才可讓後續期數跳過。"""
    attempts = [{'phase': 'A', 'option': 'tail-main', 'serialNumber': '1'},
                {'phase': 'A', 'option': 'tail-sub', 'serialNumber': '2'},
                {'phase': 'A', 'option': 'tail-main', 'sent': True}]
    rows = [{'serialNumber': '1', 'outcome': 'lost'}, {'serialNumber': '2', 'outcome': 'won'}]
    assert not already_won(attempts, rows, 'A', 'tail-main')
    assert already_won(attempts, rows, 'A', 'tail-sub')
    assert not already_won(attempts, rows, 'B', 'tail-sub')
    rows[0]['outcome'] = 'won'
    assert already_won(attempts, rows, 'A', 'tail-main')


def test_persistent_ledger_prevents_resend_and_over_budget(tmp_path):
    p = plan('branches'); path = tmp_path/'ledger.json'
    ledger = BatchLedger(path, p)
    a = {'amount': '1'}; ledger.data['attempts'].append(a)
    ledger.sent(a, {}, {}, '1.7', ['-.01']*10, '1.4')
    assert json.loads(path.read_text(encoding='utf-8'))['attempts'][0]['sent']
    with pytest.raises(AssertionError): ledger.sent(a, {}, {}, '1.7', [], '1.4')
    b = {'amount': '1'}; ledger.data['attempts'].append(b)
    with pytest.raises(AssertionError): ledger.sent(b, {}, {}, '1.7', [], '1.4')
    with pytest.raises(FileExistsError): BatchLedger(path, p)


def test_membership_duplicate_is_not_silently_overwritten():
    rows = [{'serialNumber': '1'}, {'serialNumber': '1'}, {'serialNumber': '2'}]
    assert select_unique(rows, '2')['serialNumber'] == '2'
    with pytest.raises(AssertionError): select_unique(rows, '1')
    with pytest.raises(AssertionError): select_unique(rows, '3')


def test_changed_pagination_count_is_not_accepted():
    class Client:
        def _get(self, path, params):
            return {'totalCount': 2 if params['pageIndex'] == 1 else 3,
                    'pageCount': 2, 'items': [{'serialNumber': str(params['pageIndex'])}]}
    with pytest.raises(AssertionError): read_bets(Client(), 7, '2030-01-01', ('settled',))


def record(outcome='won'):
    return {'serialNumber': '1', 'gameId': 'bingo6', 'issueNumber': 123, 'playTypeId': 'tailNumberHit',
            'panelId': 'a', 'selection': '1', 'betTime': '2030-01-01T00:00:00Z', 'betAmount': 1,
            'odds': '1.7719', 'rebate': 0, 'outcome': outcome, 'payout': '1.77' if outcome == 'won' else 0,
            'layerShares': [{'level': 'company', 'shareAmount': '.1'}]
                           + [{'level': f'agent{i}', 'shareAmount': '.1'} for i in range(1, 10)]}


def attempt():
    return {'serialNumber': '1', 'play': 'tailNumberHit', 'selection': '1', 'option': 'tail-main',
            'source': {'baseOdds': '1.7819', 'selectionOverrides': []}, 'gaps': ['0']*9+['-.01'],
            'minimum': '1.4255', 'initial_record': record()}


def test_unconfirmed_rounding_does_not_turn_into_pass():
    r = expected_settlement(attempt(), record(), rounding=None)
    assert r['payout_ok'] is None
    assert r['expected_revenue'][-1] == '0.009'


def test_default_rounding_judges_payout_half_up_2():
    """2026-10-06 Aaron 裁定派彩四捨五入到 2 位：預設就判派彩，1×1.7719 應派 1.77。"""
    r = expected_settlement(attempt(), record())
    assert r['payout_ok'] is True and r['expected_payout'] == '1.77'


def test_payout_mismatch_fails_with_serial_and_values():
    class Client:
        def _get(self, path, params):
            assert path.endswith('/Bets')
            return {'totalCount': 1, 'pageCount': 1, 'items': [dict(record(), payout='1.78')]}
    e = {'attempts': [attempt()], 'day': '2030-01-01', 'accounts': [{'id': i} for i in range(1, 11)]}
    with pytest.raises(AssertionError, match='派彩與已確認規格不符：注單 1.*實際 1.78，應為 1.77'):
        check_settlement(Client(), e)


def test_losing_bet_has_zero_revenue_and_payout():
    r = expected_settlement(attempt(), record('lost'))
    assert r['payout_ok'] is True and all(float(x) == 0 for x in r['expected_revenue'])


def test_unassigned_share_amount_is_not_treated_as_holding():
    """公司＋九層合計少於投注額時，不把差額反推成總控佔成（2026-09-29 新版文件）。"""
    r = record()
    r['betAmount'] = 2
    with pytest.raises(AssertionError, match='不從差額反推'):
        expected_settlement(attempt(), r)


def test_unknown_share_level_stops_settlement_check():
    r = record()
    r['layerShares'].append({'level': 'holding', 'shareAmount': '0'})
    with pytest.raises(AssertionError, match='非公司＋九層'):
        expected_settlement(attempt(), r)


def test_duplicate_frozen_share_level_is_rejected():
    r = record()
    r['layerShares'].append(dict(r['layerShares'][0]))
    with pytest.raises(AssertionError):
        expected_settlement(attempt(), r)


@pytest.mark.parametrize('extra_count', [0, 1])
def test_settlement_compares_nine_levels_and_detects_unrelated_bets(extra_count):
    class Client:
        def _get(self, path, params):
            if path.endswith('/Bets'):
                return {'totalCount': 1, 'pageCount': 1, 'items': [record()]}
            level = params['parentId']
            return [{'selection': '1', 'ancestorLevel': level, 'betCount': 1 + extra_count,
                     'betAmount': 1, 'oddsGapAmount': '.009' if level == 9 else 0}]
    e = {'attempts': [attempt()], 'day': '2030-01-01',
         'accounts': [{'id': i} for i in range(1, 11)],
         'before_reports': {f'{i}-tailNumberHit': [] for i in range(1, 10)}}
    result = check_settlement(Client(), e)
    assert len(result['revenues']) == 9
    assert all(r['ok'] is (extra_count == 0) for r in result['revenues'])
    assert result['rounding_pending'] is False


@pytest.mark.parametrize('raw,report,prior,ok', [
    ('0.00196', '0.0020', False, True),    # Snotra-035 實例：兩注 0.00084＋0.00112，加總後才取 4 位
    ('0.00196', '0.0019', False, False),   # 逐注先取位再加總（0.0008＋0.0011）不是現行規格
    ('0.02106', '0.0211', False, True),    # 單注收益 5 位小數：未取位值直接等值比較會誤判
    ('0.00196', '0.0019', True, True),     # 群組原有舊注：前後值各自取位，增量差 0.0001 以內
    ('0.00196', '0.0022', True, False),
])
def test_revenue_group_total_is_rounded_after_sum(raw, report, prior, ok):
    """2026-10-07 Aaron 指示：報表群組合計＝各注收益加總後才四捨五入到 4 位（《賠率差公式》取位條②）。"""
    from decimal import Decimal
    assert revenue_matches(Decimal(raw), Decimal(report), prior) is ok


def test_frozen_record_change_detected_after_restore():
    changed = record(); changed['odds'] = '9'
    with pytest.raises(AssertionError): frozen_checks([attempt()], [changed])


def test_unsettled_batch_returns_pending_without_querying_revenues():
    class Client:
        def _get(self, path, params):
            assert path.endswith('/Bets')
            return {'totalCount': 0, 'pageCount': 0, 'items': []}
    e = {'attempts': [attempt()], 'day': '2030-01-01', 'accounts': [{'id': 7}]}
    assert check_settlement(Client(), e)['pending'] == ['1']


def test_default_entry_does_not_request_browser_or_login(monkeypatch):
    monkeypatch.delenv('XZH_GAP_REGRESSION_PLAN', raising=False)
    module = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tests/xzh/test_odds_gap_betting_regression.py'))
    class Request:
        def getfixturevalue(self, name):
            pytest.fail('未提供計畫時不應取得瀏覽器或登入fixture')
    with pytest.raises(pytest.skip.Exception): module['_execute'](Request(), 'minimum')
