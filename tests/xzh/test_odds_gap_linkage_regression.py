"""B92 正式代表連動回歸：依當期來源驗算，不依賴歷史批次。"""
import json
from decimal import Decimal

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES, ancestor_sum
from xzh_qa.odds_gap_flows import API_TOLERANCE, load_ancestor_rows
from xzh_qa.odds_gap_oracle import dec, remaining_gap
from xzh_qa.odds_gap_safety import guarded_gaps, strict_gap_values

FIELDS = [('bonusNumberA', 'oddsGap'), ('pickTwoHitBonus', 'subOddsGap')]


def observable(rows):
    return {(r['playTypeId'], key): r.get(key) for r in rows for key in
            ('oddsGap', 'subOddsGap', 'remainingOddsGap', 'remainingSubOddsGap', 'isEffective')}


@pytest.mark.write_action
@pytest.mark.parametrize('game', ['bingo6'])
@allure.title('B92：修改五級主副代表差分，上級不變、下級正確連動並還原')
def test_odds_gap_representative_linkage(game, gap_context, odds_gap_run):
    """前置條件：公司QAT帳號鏈可用，記錄四／五／六級及會員三彩種原值。
    操作步驟：五級特碼A主欄及二中特副欄各減0.001→保存→讀回→還原。
    預期結果：自身及下級剩餘同步減0.001，上級與其他欄保持原值。
    佐證方式：獨立平台上限、公式、UI值、控制組及還原Allure附件。
    已知問題：來源變動或超出額度時停止；代表結果不等於全欄保存通過。
    """
    contexts = {i: gap_context(i, via='company') for i in (3, 4, 5, 9)}
    writer = contexts[4]
    reference = writer.reference_client
    cap, independent = reference.cap_rate()
    if not independent:
        pytest.skip('BLOCKED：缺本次平台上限證據，未寫入')
    for ctx in contexts.values():
        ctx.open(game)
    odds_before = {g: reference.odds_setting(g) for g in GAMES}
    results = []
    for play, field in FIELDS:
        rem = 'remainingSubOddsGap' if field == 'subOddsGap' else 'remainingOddsGap'
        col = int(field == 'subOddsGap')
        ancestors = {i: load_ancestor_rows(ctx, game) for i, ctx in contexts.items()}
        if any(v is None for v in ancestors.values()):
            pytest.skip('BLOCKED：祖先來源不足，未寫入')
        before = {(i, g): ctx.api_rows(g) for i, ctx in contexts.items() for g in GAMES}
        rows = writer.open(game)
        assert strict_gap_values(rows) == strict_gap_values(before[(4, game)])
        indexes = {r['playTypeId']: n for n, r in enumerate(rows)}
        assert play in indexes, '代表玩法缺失'
        row = rows[indexes[play]]
        if row.get(field) is None or row.get(rem) is None:
            pytest.skip('BLOCKED：目標欄原始值不足，未寫入')
        delta = Decimal('-0.001')
        target = dec(row[field]) + delta
        if any(dec(next(r for r in before[(i, game)] if r['playTypeId'] == play)[rem]) < -delta
               for i in (4, 5, 9)):
            pytest.skip('BLOCKED：本層或下級額度不足，未寫入')
        evidence = {'game': game, 'play': play, 'field': field, 'target': str(target),
                    'delta': str(delta), 'checks': [], 'controls': [], 'restored': False}
        odds_gap_run.dump(f'before-{game}-{play}.json', {
            'rows': {f'{i}-{g}': value for (i, g), value in before.items()},
            'ancestors': ancestors, 'odds': odds_before, 'cap': cap})
        try:
            with guarded_gaps(writer, game, rows) as tx:
                with allure.step('公司修改五級代表欄，UI保存並重載'):
                    entered = writer.setting.set_value(indexes[play], col, target)
                    assert entered == target, 'UI輸入值不符'
                    tx['expected'][(play, field)] = entered
                    tx['attempted'] = True
                    saved = writer.setting.save()
                    evidence['save_status'] = saved['status']
                    assert saved['status'] in (200, 204), 'UI保存失敗'
                    writer.setting.reload_tab(game)
                after = {(i, g): ctx.api_rows(g) for i, ctx in contexts.items() for g in GAMES}
                with allure.step('核對四級控制組、五級自身、六級及會員的公式、差值與其他彩種'):
                    for i, ctx in contexts.items():
                        before_row = next(r for r in before[(i, game)] if r['playTypeId'] == play)
                        after_row = next(r for r in after[(i, game)] if r['playTypeId'] == play)
                        pricing = odds_before[game][play]
                        base = pricing.get('subOdds' if col else 'odds')
                        low = pricing.get('subMinOdds') if col else pricing.get('minOdds')
                        if col and low is None:
                            low = pricing.get('minOdds')
                        assert base is not None and low is not None, '缺基準或最低原始值'
                        ancestor = ancestor_sum(ancestors[i]).get((play, field), Decimal(0))
                        expected = remaining_gap(base, low, after_row[field],
                                                 ancestor + (delta if i > 4 else 0), cap)
                        actual = dec(after_row[rem])
                        expected_delta = delta if i >= 4 else Decimal(0)
                        evidence['checks'].append({'account': ctx.account,
                            'expected': str(expected), 'actual': str(actual),
                            'expected_delta': str(expected_delta),
                            'actual_delta': str(actual - dec(before_row[rem])),
                            'formula_ok': abs(actual - expected) <= API_TOLERANCE,
                            'delta_ok': abs(actual-dec(before_row[rem])-expected_delta) <= API_TOLERANCE})
                        for g in GAMES:
                            old, new = observable(before[(i, g)]), observable(after[(i, g)])
                            allowed = set()
                            if g == game and i >= 4:
                                allowed.add((play, rem))
                                if i == 4:
                                    allowed.add((play, field))
                            changed = [str(k) for k in set(old) | set(new)
                                       if k not in allowed and old.get(k) != new.get(k)]
                            evidence['controls'].append({'account': ctx.account, 'game': g,
                                                         'unexpected_changes': changed})
                        ctx.open(game)
                        ui_rows = ctx.setting.read_rows()
                        api_rows = ctx.api_rows(game)
                        ctx.setting.wait_rows_match(api_rows)
                        n = next(n for n, r in enumerate(api_rows) if r['playTypeId'] == play)
                        ui_value = dec(ui_rows[n]['inputs'][col])
                        evidence['checks'][-1]['ui_gap_ok'] = ui_value == dec(after_row[field])
                    evidence['pricing_stable'] = all(reference.odds_setting(g) == odds_before[g] for g in GAMES)
        finally:
            evidence['restored'] = tx['restored'] if 'tx' in locals() else False
            odds_gap_run.dump(f'linkage-{game}-{play}.json', evidence)
            allure.attach(json.dumps(evidence, ensure_ascii=False, indent=2),
                          f'{game}-{play}實際與期望', allure.attachment_type.JSON)
        final = {(i, g): ctx.api_rows(g) for i, ctx in contexts.items() for g in GAMES}
        restored = all(observable(final[k]) == observable(before[k]) for k in before)
        odds_gap_run.dump(f'restore-linkage-{game}-{play}.json', {'all_observed_equal': restored})
        assert evidence['restored'] and restored, '還原後本層／下級／控制組不一致'
        assert evidence['pricing_stable'], '基準來源期間變動，本輪判準無效'
        assert all(c['formula_ok'] and c['delta_ok'] and c['ui_gap_ok'] for c in evidence['checks'])
        assert all(not c['unexpected_changes'] for c in evidence['controls'])
        results.append(evidence)
    assert len(results) == 2
