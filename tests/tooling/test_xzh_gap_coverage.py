"""離線驗證：缺欄不能從母體消失，抽測與路徑需明確區分。"""
import ast
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal

import pytest

from xzh_qa.odds_gap_spec import load_spec, field_inventory, compare_spec
from xzh_qa.odds_gap_flows import plan_fields, describe_scope


@pytest.fixture
def rows(monkeypatch):
    for key in ('XZH_GAP_FIELDS', 'XZH_GAP_MAX_FIELDS', 'XZH_GAP_BOUNDARY_MODE'):
        monkeypatch.delenv(key, raising=False)
    ids = {'特码A': 'bonusNumberA', '二中特': 'pickTwoHitBonus',
           '单0·大0·双7·小7': 'sevenNumberOdd0'}
    return [dict(playTypeId=ids.get(r['name'], r['specRowId']), playTypeName=r['name'],
                 subOddsLabel=r['subLabel'], oddsGap=0, subOddsGap=0,
                 remainingOddsGap=10, remainingSubOddsGap=10)
            for r in load_spec()['rows']]


def test_missing_subfields_remain_in_full_denominator(rows):
    """規格有副欄、畫面卻缺副欄時，缺欄仍留在分母（2026-09-24 規格101列116欄；不中改單欄，不再有馬副欄）。"""
    for row in rows:
        if row['playTypeName'] == '二中特':
            row['subOddsLabel'] = None
    selected, coverage = field_inventory(rows)
    assert coverage['expected_fields'] == coverage['selected_fields'] == 116
    assert coverage['available_fields'] == 115
    assert len([r for r in selected if 'reason' in r]) == 1
    ctx = SimpleNamespace(account='offline', run=SimpleNamespace(dump=lambda *a: None))
    odds = {r['playTypeId']: dict(odds=20, minOdds=1, subOdds=20, subMinOdds=1) for r in rows}
    fields, blocked = plan_fields(ctx, 'markSix', rows, odds, Decimal('.8'), {})
    assert len(fields) == 115 and len(blocked) == 1


def test_boundary_default_is_four_field_sample(rows, monkeypatch):
    selected, coverage = field_inventory(rows, boundary=True)
    assert len(selected) == 4 and coverage['mode'] == 'sample'
    monkeypatch.setenv('XZH_GAP_BOUNDARY_MODE', 'full')
    assert field_inventory(rows, boundary=True)[1]['selected_fields'] == 116
    assert '執行模式：全量' not in describe_scope()


def test_missing_sample_row_is_retained(rows):
    rows[:] = [r for r in rows if r['playTypeId'] != 'pickTwoHitBonus']
    selected, coverage = field_inventory(rows, boundary=True)
    assert len(selected) == 4 and coverage['available_fields'] == 2


def test_limit_does_not_replace_missing_field(rows, monkeypatch):
    rows.pop(0)
    monkeypatch.setenv('XZH_GAP_MAX_FIELDS', '1')
    selected, coverage = field_inventory(rows)
    assert len(selected) == 1 and 'reason' in selected[0]
    assert coverage['available_fields'] == 0


def test_unknown_selection_and_mode_are_rejected(rows, monkeypatch):
    monkeypatch.setenv('XZH_GAP_FIELDS', 'unknown:oddsGap')
    with pytest.raises(AssertionError): field_inventory(rows)
    monkeypatch.delenv('XZH_GAP_FIELDS')
    monkeypatch.setenv('XZH_GAP_BOUNDARY_MODE', 'typo')
    with pytest.raises(AssertionError): field_inventory(rows, boundary=True)


def test_spec_accepts_reordering_but_rejects_missing_fields(rows):
    rows.reverse()
    ui = [dict(name=r['playTypeName'] + (' / '+r['subOddsLabel'] if r['subOddsLabel'] else ''),
               inputs=['0']*(2 if r['subOddsLabel'] else 1),
               remaining=['10']*(2 if r['subOddsLabel'] else 1)) for r in rows]
    headers=['玩法','赔率差分','剩余差分']
    assert compare_spec(load_spec(), ui, rows, headers)['status'] == 'PASS'
    ui[0]['remaining'][0]='10.00001'
    assert compare_spec(load_spec(), ui, rows, headers)['status'] == 'PASS'
    ui.pop()
    assert compare_spec(load_spec(), ui, rows, headers)['status'] == 'FAIL'


def test_routes_collected_independently(monkeypatch):
    # 僅載入純規劃函式，避免載入UI案例與登入fixture。
    source=Path('tests/xzh/test_odds_gap_acceptance.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    import os
    namespace={'os':os}
    funcs=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('levels','route_scopes')]
    exec(compile(ast.Module(body=funcs,type_ignores=[]), '<routes>', 'exec'), namespace)
    monkeypatch.setenv('XZH_GAP_LEVELS', '1,2,3,4,5,6,7,8,9,10')
    monkeypatch.delenv('XZH_GAP_VIAS', raising=False)
    routes=namespace['route_scopes']()
    assert len(routes)==19 and (0,'parent') not in routes
    assert (1,'company') in routes and (1,'parent') in routes
    monkeypatch.setenv('XZH_GAP_VIAS', 'bad')
    with pytest.raises(AssertionError): namespace['route_scopes']()
