"""由正式回歸帳本續查自然結算；不下注、不修改站台、不等待開獎。

若尚未結算，保留 partial 資料供下一次唯讀續查；金額取位不從產品反推規格。
"""
from decimal import ROUND_DOWN, ROUND_HALF_UP

from xzh_qa.odds_gap_oracle import dec, player_odds, level_diffs, gap_money
from xzh_qa.odds_gap_regression import read_bets, select_unique, reports, frozen_checks


def expected_settlement(attempt, record, rounding=None):
    source = attempt['source']
    override = next((r for r in source.get('selectionOverrides', []) if r['selection'] == attempt['selection']), None)
    base = override['odds'] if override else source['baseOdds']
    odds = player_odds(base, attempt['gaps'], attempt['minimum'])
    assert dec(record['odds']) == odds, '結算賠率與下注時獨立來源不符'
    outcome = record['outcome']
    assert outcome in ('won', 'lost', 'tie', 'canceled', 'cancelled', 'refunded'), '未知結算狀態'
    raw = dec(record['betAmount']) * (odds if outcome == 'won' else (0 if outcome == 'lost' else 1))
    rules = {'half_up_2': ROUND_HALF_UP, 'down_2': ROUND_DOWN}
    assert rounding in (None, *rules), '未支援的取位規格'
    expected_payout = raw.quantize(dec('.01'), rounding=rules[rounding]) if rounding else raw
    known = rounding is not None or raw == raw.quantize(dec('.01'))
    payout_ok = dec(record['payout']) == expected_payout if known else None
    shares = {r['level']: r['shareAmount'] for r in record['layerShares']}
    assert len(shares) == len(record['layerShares']), '下注時凍結占成層級重複'
    assert all(f'agent{n}' in shares for n in range(1, 10)), '缺下注時凍結占成'
    # 2026-09-29 新版文件：上繳額須先扣自營總控鏈前後兩段佔成。注單明細只列公司與九層，
    # 差額分不出是總控佔成還是缺層，故不反推；有未知層或差額即停止，待取得總控佔成來源再驗。
    assert set(shares) == {'company', *(f'agent{n}' for n in range(1, 10))}, f'凍結占成層級非公司＋九層：{sorted(shares)}'
    unassigned = dec(record['betAmount']) - sum(dec(v) for v in shares.values())
    assert unassigned == 0, (f'公司＋九層凍結占成與投注額差 {unassigned}；可能為自營總控佔成，'
                             '需取得總控兩段佔成來源後再驗，不從差額反推')
    diffs = level_diffs(base, attempt['gaps'], attempt['minimum'])
    amounts = [shares[f'agent{n}'] for n in range(1, 10)]
    money = [gap_money(record['betAmount'], amounts, diffs, n) if outcome == 'won' else dec(0) for n in range(1, 10)]
    return {'serialNumber': str(record['serialNumber']), 'company_source': str(base),
            'expected_odds': str(odds), 'actual_odds': str(record['odds']), 'outcome': outcome,
            'expected_payout': str(expected_payout), 'actual_payout': record['payout'],
            'payout_ok': payout_ok, 'expected_revenue': list(map(str, money))}


def check_settlement(client, evidence, rounding=None):
    attempts = [a for a in evidence['attempts'] if 'serialNumber' in a]
    assert attempts, '帳本沒有已確認成功的注單，先處理送出狀態'
    day, accounts = evidence['day'], evidence['accounts']
    settled = read_bets(client, accounts[-1]['id'], day, ('settled',))
    ids = {str(r['serialNumber']) for r in settled}
    pending = [a['serialNumber'] for a in attempts if a['serialNumber'] not in ids]
    if pending:
        return {'pending': pending, 'checked': [], 'note': '未自然結算，不追加投注'}
    frozen = frozen_checks(attempts, settled)
    checks, groups = [], {}
    for a in attempts:
        record = select_unique(settled, a['serialNumber'])
        check = expected_settlement(a, record, rounding)
        assert check['payout_ok'] is not False, '派彩與已確認規格不符'
        checks.append(check)
        for n, money in enumerate(check['expected_revenue'], 1):
            group = groups.setdefault((n, a['play'], a['selection']), {'count': 0, 'amount': dec(0), 'money': dec(0)})
            group['count'] += 1
            group['amount'] += dec(record['betAmount'])
            group['money'] += dec(money)
    after = reports(client, accounts, day, {a['play'] for a in attempts})
    revenues = []
    for (level, play, selection), expected in groups.items():
        def rows(body):
            return body['items'] if isinstance(body, dict) else body
        key = f'{level}-{play}'
        b = [r for r in rows(evidence['before_reports'][key]) if r.get('selection') == selection]
        a = [r for r in rows(after[key]) if r.get('selection') == selection]
        assert len(b) <= 1 and len(a) == 1, '收益分组缺失或重複'
        before, actual = (b[0] if b else {}), a[0]
        if 'ancestorLevel' in actual:
            assert actual['ancestorLevel'] == level, '收益受益層錯配'
        values = {'count': actual['betCount'] - before.get('betCount', 0),
                  'amount': dec(actual['betAmount']) - dec(before.get('betAmount', 0)),
                  'money': dec(actual['oddsGapAmount']) - dec(before.get('oddsGapAmount', 0))}
        revenues.append({'level': level, 'play': play, 'selection': selection, 'expected': expected, 'actual': values, 'ok': values == expected})
    return {'pending': [], 'checked': checks, 'frozen': frozen, 'revenues': revenues, 'after_reports': after,
            'missing_winners': sorted({a['option'] for a, c in zip(attempts, checks) if c['outcome'] != 'won'}),
            'rounding_pending': any(c['payout_ok'] is None for c in checks)}
