"""由正式回歸帳本續查自然結算；不下注、不修改站台、不等待開獎。

若尚未結算，保留 partial 資料供下一次唯讀續查；金額取位不從產品反推規格。
"""
from decimal import ROUND_DOWN, ROUND_HALF_UP

from xzh_qa.odds_gap_oracle import dec, player_odds, level_diffs, gap_money
from xzh_qa.odds_gap_regression import read_bets, select_unique, reports, frozen_checks

# 派彩＝本金×凍結賠率，四捨五入到 2 位（2026-10-06 Aaron 裁定，見《新綜合_賠率差公式》「結算公式」取位條）。
# 明確傳 rounding=None 才回到「取位未定、派彩不判」的舊行為。
PAYOUT_ROUNDING = 'half_up_2'

# 報表「赔率差金额」群組合計＝各注收益「加總後」才四捨五入到 4 位（逐注不先取位）。
# 2026-10-07 Aaron 指示改寫，見《新綜合_賠率差公式》「結算公式」取位條②；Snotra-035 因此撤銷。
REVENUE_QUANTUM = dec('.0001')


def revenue_matches(expected_raw, actual_increment, had_prior_bets):
    """群組收益比對。

    群組原本沒有本批以外的注單：報表增量必須等於「本批各注未取位收益加總後四捨五入到 4 位」。
    群組原本就有舊注：報表前、後兩個值各自取過 4 位，增量與本批未取位加總最多差 0.0001，
    只能以此上限判定（無法得知舊注的未取位值）。
    """
    if not had_prior_bets:
        return actual_increment == expected_raw.quantize(REVENUE_QUANTUM, rounding=ROUND_HALF_UP)
    return abs(actual_increment - expected_raw) <= REVENUE_QUANTUM


def expected_settlement(attempt, record, rounding=PAYOUT_ROUNDING):
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


def check_settlement(client, evidence, rounding=PAYOUT_ROUNDING):
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
        assert check['payout_ok'] is not False, (
            f"派彩與已確認規格不符：注單 {check['serialNumber']}（{check['outcome']}）"
            f"實際 {check['actual_payout']}，應為 {check['expected_payout']}（{rounding}）")
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
        had_prior = before.get('betCount', 0) > 0
        ok = (values['count'] == expected['count'] and values['amount'] == expected['amount']
              and revenue_matches(expected['money'], values['money'], had_prior))
        revenues.append({'level': level, 'play': play, 'selection': selection, 'expected': expected, 'actual': values,
                         'expected_report_money': str(expected['money'].quantize(REVENUE_QUANTUM, rounding=ROUND_HALF_UP)),
                         'money_rule': 'increment_within_0.0001' if had_prior else 'sum_then_round4', 'ok': ok})
    return {'pending': [], 'checked': checks, 'frozen': frozen, 'revenues': revenues, 'after_reports': after,
            'missing_winners': sorted({a['option'] for a, c in zip(attempts, checks) if c['outcome'] != 'won'}),
            'rounding_pending': any(c['payout_ok'] is None for c in checks)}
