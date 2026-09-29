"""正式規格欄位盤點與共用比較。"""
import json
import os
from decimal import Decimal
from pathlib import Path


def load_spec():
    return json.loads((Path(__file__).resolve().parents[2] / 'data/xzh/odds_gap_setting_spec.json').read_text(encoding='utf-8'))


def compare_spec(spec, ui, api, headers):
    issues, fields, observations = [], [], []
    if not all(x in headers for x in ('玩法', '赔率差分', '剩余差分')):
        issues.append({'kind': 'headers', 'actual': headers})
    if len(ui) != len(api) or any(u['name'].split('/')[0].strip() != a['playTypeName'].split('/')[0].strip() for u,a in zip(ui,api)):
        return dict(status='FAIL', rows=len(ui), inputs=sum(len(r['inputs']) for r in ui),
                    issues=[{'kind':'ui_api_alignment'}], fields=[], observations=[])
    matched = set()
    for expected in spec['rows']:
        names = [expected['name'], *expected['nameAliases']]
        found = [i for i, row in enumerate(ui) if row['name'].split('/')[0].strip() in names]
        for column in range(2 if expected['hasSub'] else 1):
            result = {'id': expected['specRowId'], 'play': expected['name'],
                      'field': 'sub' if column else 'main', 'status': 'PASS'}
            if len(found) != 1:
                result.update(status='FAIL', reason='missing_row' if not found else 'duplicate_row')
            else:
                i = found[0]
                matched.add(i)
                row, backend = ui[i], api[i]
                if len(row['inputs']) <= column:
                    result.update(status='FAIL', reason='missing_input')
                elif len(row['remaining']) <= column or not row['remaining'][column]:
                    result.update(status='FAIL', reason='missing_remaining')
                elif column and backend.get('subOddsLabel') not in [expected['subLabel'], *expected['subLabelAliases']]:
                    result.update(status='FAIL', reason='sub_label', actual=backend.get('subOddsLabel'))
                elif column and ('/' not in row['name'] or row['name'].split('/', 1)[1].strip() not in [expected['subLabel'], *expected['subLabelAliases']]):
                    result.update(status='FAIL', reason='ui_sub_label', actual=row['name'])
                else:
                    for values, key in [('inputs', 'subOddsGap' if column else 'oddsGap'),
                                        ('remaining', 'remainingSubOddsGap' if column else 'remainingOddsGap')]:
                        actual = row[values][column]
                        raw = backend.get(key)
                        if raw is None and values == 'inputs' and actual == '':
                            continue
                        try:
                            equal = Decimal(actual.replace(',', '')) == Decimal(str(raw))
                        except Exception:
                            equal = False
                        if not equal:
                            if values == 'remaining':
                                observations.append({'play': expected['name'], 'field': result['field'],
                                                     'status': 'OBSERVATION', 'reason': 'remaining_display_precision_excluded',
                                                     'ui': actual, 'api': raw})
                                continue
                            result.update(status='FAIL', reason='ui_api_value', source=values, ui=actual, api=raw)
                            break
                        if values == 'inputs' and Decimal(actual) > 0:
                            result.update(status='FAIL', reason='positive_gap', actual=actual)
                if column == 0 and len(row['inputs']) != (2 if expected['hasSub'] else 1):
                    issues.append({'kind': 'input_count', 'play': expected['name'], 'actual': len(row['inputs'])})
            fields.append(result)
    for i, row in enumerate(ui):
        if i not in matched:
            issues.append({'kind': 'unexpected_row', 'name': row['name']})
    return {'status': 'FAIL' if issues or any(f['status'] == 'FAIL' for f in fields) else 'PASS',
            'rows': len(ui), 'inputs': sum(len(r['inputs']) for r in ui),
            'issues': issues, 'fields': fields, 'observations': observations}


DEFAULT_FIELDS = {('bonusNumberA', 'oddsGap'), ('pickTwoHitBonus', 'oddsGap'),
                  ('pickTwoHitBonus', 'subOddsGap'), ('sevenNumberOdd0', 'oddsGap')}


def field_inventory(rows, *, boundary=False):
    """依規格選欄，缺失欄保留於母體與選取範圍。"""
    spec = load_spec()
    mode = os.environ.get('XZH_GAP_BOUNDARY_MODE', 'sample') if boundary else 'full'
    assert mode in ('full', 'sample'), 'XZH_GAP_BOUNDARY_MODE 須 full 或 sample'
    raw = os.environ.get('XZH_GAP_FIELDS', '').strip()
    requested = {tuple(x.strip().split(':')) for x in raw.split(',')} if raw else None
    limit_raw = os.environ.get('XZH_GAP_MAX_FIELDS', '').strip()
    assert not limit_raw or (limit_raw.isdigit() and int(limit_raw)>0), '欄位上限須為正整數'
    inventory = []
    for expected in spec['rows']:
        names = [expected['name'], *expected['nameAliases']]
        matches = [(i,r) for i,r in enumerate(rows) if r['playTypeName'].split('/')[0].strip() in names]
        for col in range(2 if expected['hasSub'] else 1):
            item = dict(spec_id=expected['specRowId'], play=expected['name'],
                        field='subOddsGap' if col else 'oddsGap', col=col)
            if len(matches) != 1:
                item.update(play_id=expected['specRowId'], reason='規格玩法缺列或重複，無法唯一對應API')
            else:
                i,row=matches[0]; item.update(row=i, play_id=row['playTypeId'])
                if col and row.get('subOddsLabel') not in [expected['subLabel'], *expected['subLabelAliases']]:
                    item['reason']='規格副欄缺失或標籤不符'
            inventory.append(item)
    if requested:
        known={(x['play_id'],x['field']) for x in inventory} | {(x['spec_id'],x['field']) for x in inventory}
        assert requested <= known, f'指定欄位無法對應規格：{requested-known}'
        selected=[x for x in inventory if (x['play_id'],x['field']) in requested or (x['spec_id'],x['field']) in requested]
    elif mode=='sample':
        selected=[x for x in inventory if (x['play_id'],x['field']) in DEFAULT_FIELDS]
        # 代表欄缺失時仍保留受阻項。
        expected_names={'特码A','二中特','单0·大0·双7·小7'}
        selected += [x for x in inventory if 'reason' in x and x['play'] in expected_names and x not in selected]
    else:
        selected=inventory
    if limit_raw: selected=selected[:int(limit_raw)]
    assert selected, '沒有對應規格欄位'
    coverage=dict(spec_version=spec['version'], expected_fields=len(inventory), selected_fields=len(selected),
                  available_fields=sum('reason' not in x for x in selected),
                  mode='full' if len(selected)==len(inventory) else 'sample', fields=selected)
    return selected, coverage
