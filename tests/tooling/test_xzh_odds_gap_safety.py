"""離線故障注入：保存成功後逾時、未寫入、部分寫入及他人異動。"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from xzh_qa.odds_gap_client import gap_values
from xzh_qa.odds_gap_run_state import OddsGapRunState, RestoreConflict
from xzh_qa.odds_gap_safety import guarded_gaps, guarded_authorization


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from xzh_qa import odds_gap_spec
    monkeypatch.setattr(odds_gap_spec, 'load_spec', lambda: {
        'version':'offline-fixture', 'rows':[
            dict(specRowId=x, name=x, nameAliases=[], hasSub=False, subLabel=None, subLabelAliases=[])
            for x in ('a','b')]})
    rows = [{"playTypeId":"a","oddsGap":0,"subOddsGap":None},
            {"playTypeId":"b","oddsGap":0,"subOddsGap":None}]
    current = deepcopy(rows)
    pending = {}
    calls = []
    def set_value(index, col, value): pending[(index,col)] = value
    def save():
        calls.append('save')
        for (i,col),value in pending.items(): current[i]['subOddsGap' if col else 'oddsGap'] = value
        pending.clear()
        return {"status":204}
    def opened(game):
        pending.clear()
        return deepcopy(current)
    return SimpleNamespace(account='aaa111',run=OddsGapRunState('test',str(tmp_path)),
                           api_rows=lambda game:deepcopy(current),open=opened,recover=None,
                           setting=SimpleNamespace(set_value=set_value,save=save),
                           current=current,rows=rows,calls=calls)


def test_timeout_after_success_restores_and_preserves_failure(ctx):
    with pytest.raises(TimeoutError):
        with guarded_gaps(ctx,'markSix',ctx.rows) as state:
            state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1.1')})
            ctx.current[0]['oddsGap']=Decimal('-1.1')
            raise TimeoutError('reload failed')
    assert gap_values(ctx.current)==gap_values(ctx.rows)
    assert state['restored']
    assert ctx.calls==['save']


def test_failed_save_without_write_does_not_send_restore(ctx):
    with guarded_gaps(ctx,'markSix',ctx.rows) as state:
        state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1.1')})
    assert state['restored'] and ctx.calls==[]


def test_null_to_zero_drift_is_not_hidden_by_numeric_normalization(ctx):
    with pytest.raises(RestoreConflict,match='快照不一致'):
        with guarded_gaps(ctx,'markSix',ctx.rows) as state:
            state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1')})
            ctx.current[1]['subOddsGap']=0
    assert ctx.current[1]['subOddsGap']==0 and not ctx.calls
    from pathlib import Path
    assert list(Path(ctx.run.dir).glob('restore-diff-*'))


def test_ancestor_queries_use_each_games_own_verified_chain(ctx):
    from xzh_qa.odds_gap_flows import load_ancestor_rows
    chain=[{'id':1,'account':'company1','level':'company'},
           {'id':110,'account':'aaa111','level':'agent1'},
           {'id':220,'account':'aaa222','level':'agent2'},
           {'id':330,'account':'aaa333','level':'agent3'}]
    calls=[]
    def query(user_id,game):
        calls.append((user_id,game))
        return [{'userId':user_id,'game':game}]
    ctx.account='aaa333'
    ctx.target_index=2
    ctx.target_user_id=330
    ctx.reference_client=SimpleNamespace(share_ancestors=lambda user_id:chain,gap_setting=query)
    first=load_ancestor_rows(ctx,'markSix')
    second=load_ancestor_rows(ctx,'bingo6')
    assert calls==[(110,'markSix'),(220,'markSix'),(110,'bingo6'),(220,'bingo6')]
    assert first[0][0]['game']=='markSix' and second[0][0]['game']=='bingo6'
    chain[1]['account']='another-chain'
    with pytest.raises(AssertionError,match='帳號鏈不符'):load_ancestor_rows(ctx,'ukLucky7')
    assert len(calls)==4


def test_partial_write_restores_only_persisted_fields(ctx):
    with guarded_gaps(ctx,'markSix',ctx.rows) as state:
        state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1.1'),('b','oddsGap'):Decimal('-1.1')})
        ctx.current[1]['oddsGap']=Decimal('-1.1')
    assert gap_values(ctx.current)==gap_values(ctx.rows)


def test_conflict_blocks_later_batch_writes(ctx, tmp_path, monkeypatch):
    marker=tmp_path/'stop.json'
    monkeypatch.setenv('XZH_GAP_STOP_FILE',str(marker))
    with pytest.raises(RestoreConflict):
        with guarded_gaps(ctx,'markSix',ctx.rows) as state:
            state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1')})
            ctx.current[0]['oddsGap']=Decimal('-2')
    assert marker.exists()
    with pytest.raises(RestoreConflict,match='停止後續寫入'):
        with guarded_gaps(ctx,'bingo6',ctx.rows):
            pytest.fail('不得進入下一筆寫入')
    assert ctx.calls==[]


def test_boundary_ui_rejection_is_observed_and_every_write_restored(ctx, monkeypatch):
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    monkeypatch.setenv('XZH_GAP_FIELDS','a:oddsGap')
    monkeypatch.delenv('XZH_GAP_BOUNDARY_INPUTS',raising=False)
    monkeypatch.delenv('XZH_GAP_MAX_FIELDS',raising=False)
    for rows in (ctx.rows,ctx.current):
        for row in rows:
            row.update(playTypeName=row['playTypeId'],remainingOddsGap='5',subOddsLabel=None)
    state={'raw':''}
    original_save=ctx.setting.save
    def fill_raw(i,col,raw):
        state['raw']=raw
        value=Decimal(raw).quantize(Decimal('0.0001'),rounding='ROUND_DOWN') if raw not in ('abc','') else Decimal(0)
        ctx.setting.set_value(i,col,value)
        return str(value)
    def save(allow_no_request=False):
        if allow_no_request and state['raw']=='1':
            return {'status':None}
        return original_save()
    ctx.setting.fill_raw=fill_raw
    ctx.setting.paste_raw=lambda *args:None
    ctx.setting.messages=lambda:[]
    ctx.setting.reload_tab=lambda game:None
    ctx.setting.save=save
    with pytest.raises(pytest.skip.Exception,match='部分'):
        check_boundary_inputs(ctx,'markSix',{})
    assert gap_values(ctx.current)==gap_values(ctx.rows)
    import json
    from pathlib import Path
    result=json.loads((Path(ctx.run.dir)/'b91-aaa111-markSix.json').read_text(encoding='utf-8'))
    assert len(result['legal'])==3 and all(x['ok'] for x in result['legal'])
    overdraw=next(x for x in result['legal'] if x['mode']=='overdraw')
    assert overdraw['input']=='-5.0001' and overdraw['expected']=='-5.0001'
    assert not result['positive_persisted']
    assert next(x for x in result['undefined'] if x['input']=='1')['save_status'] is None
    assert result['blocked'][0]['condition']=='貼上文字'


def test_boundary_overdraw_rejected_is_failure_and_restored(ctx, monkeypatch):
    """2026-09-29 新版文件：儲存時不檢查超扣；超扣被拒絕保存要判失敗，不能列待確認。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    monkeypatch.setenv('XZH_GAP_FIELDS','a:oddsGap')
    monkeypatch.delenv('XZH_GAP_BOUNDARY_INPUTS',raising=False)
    monkeypatch.delenv('XZH_GAP_MAX_FIELDS',raising=False)
    for rows in (ctx.rows,ctx.current):
        for row in rows:
            row.update(playTypeName=row['playTypeId'],remainingOddsGap='5',subOddsLabel=None)
    state={'raw':''}
    original_save=ctx.setting.save
    def fill_raw(i,col,raw):
        state['raw']=raw
        value=Decimal(raw).quantize(Decimal('0.0001'),rounding='ROUND_DOWN') if raw not in ('abc','') else Decimal(0)
        ctx.setting.set_value(i,col,value)
        return str(value)
    def save(allow_no_request=False):
        if allow_no_request and state['raw']=='1':
            return {'status':None}
        if state['raw']=='-5.0001':
            return {'status':400}
        return original_save()
    ctx.setting.fill_raw=fill_raw
    ctx.setting.paste_raw=lambda *args:None
    ctx.setting.messages=lambda:[]
    ctx.setting.reload_tab=lambda game:None
    ctx.setting.save=save
    with pytest.raises(AssertionError,match='合法輸入保存 HTTP 400'):
        check_boundary_inputs(ctx,'markSix',{})
    assert gap_values(ctx.current)==gap_values(ctx.rows)


@pytest.mark.parametrize('rounding',['ROUND_DOWN','ROUND_HALF_UP'])
def test_precision_pending_records_both_behaviors_as_blocked_and_restores(ctx, monkeypatch, rounding):
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    monkeypatch.setenv('XZH_GAP_FIELDS','a:oddsGap')
    monkeypatch.setenv('XZH_GAP_BOUNDARY_INPUTS','["-0.12346"]')
    monkeypatch.delenv('XZH_GAP_MAX_FIELDS',raising=False)
    for rows in (ctx.rows,ctx.current):
        for row in rows:
            row.update(playTypeName=row['playTypeId'],remainingOddsGap='5',subOddsLabel=None)
    def fill_raw(i,col,raw):
        value=Decimal(raw).quantize(Decimal('0.0001'),rounding=rounding)
        ctx.setting.set_value(i,col,value)
        return str(value)
    ctx.setting.fill_raw=fill_raw
    ctx.setting.messages=lambda:[]
    ctx.setting.reload_tab=lambda game:None
    original_save=ctx.setting.save
    ctx.setting.save=lambda **kwargs:original_save()
    with pytest.raises(pytest.skip.Exception, match='BLOCKED'):
        check_boundary_inputs(ctx,'markSix',{})
    import json
    from pathlib import Path
    result=json.loads((Path(ctx.run.dir)/'b91-aaa111-markSix.json').read_text(encoding='utf-8'))
    assert result['legal'] == []
    observed=result['undefined'][0]
    assert observed['input']=='-0.12346' and 'expected' not in observed and 'ok' not in observed
    assert Decimal(observed['read_back']) == Decimal('-0.12346').quantize(Decimal('0.0001'), rounding=rounding)
    assert gap_values(ctx.current)==gap_values(ctx.rows)


def test_positive_validation_is_isolated_per_field(ctx, monkeypatch):
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    monkeypatch.setenv('XZH_GAP_FIELDS','a:oddsGap,b:oddsGap')
    monkeypatch.setenv('XZH_GAP_BOUNDARY_INPUTS','["1"]')
    monkeypatch.delenv('XZH_GAP_MAX_FIELDS',raising=False)
    for rows in (ctx.rows,ctx.current):
        for row in rows:
            row.update(playTypeName=row['playTypeId'],remainingOddsGap='5',subOddsLabel=None)
    typed=[]
    sent=[]
    def fill_raw(i,col,raw):
        typed.append(i)
        return raw
    def save(allow_no_request=False):
        sent.append(list(typed))
        typed.clear()
        return {'status':None}
    ctx.setting.fill_raw=fill_raw
    ctx.setting.messages=lambda:[]
    ctx.setting.reload_tab=lambda game:None
    ctx.setting.save=save
    with pytest.raises(pytest.skip.Exception):check_boundary_inputs(ctx,'markSix',{})
    assert sent==[[0],[1]], '不能讓某一欄的驗證擋住其他欄測試'


def test_conflict_is_not_overwritten(ctx):
    with pytest.raises(RestoreConflict):
        with guarded_gaps(ctx,'markSix',ctx.rows) as state:
            state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1.1')})
            ctx.current[0]['oddsGap']=Decimal('-2')
    assert ctx.current[0]['oddsGap']==Decimal('-2') and not ctx.calls
    assert list(__import__('pathlib').Path(ctx.run.dir).glob('restore-pending-*'))


def test_unmodified_field_drift_is_reported_not_overwritten(ctx):
    with pytest.raises(AssertionError,match='最終全欄'):
        with guarded_gaps(ctx,'markSix',ctx.rows) as state:
            state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1.1')})
            ctx.current[0]['oddsGap']=Decimal('-1.1')
            ctx.current[1]['oddsGap']=Decimal('-3')
    assert ctx.current[0]['oddsGap']==0 and ctx.current[1]['oddsGap']==Decimal('-3')


def test_unknown_response_then_successful_read_is_restored(ctx):
    with pytest.raises(ConnectionError):
        with guarded_gaps(ctx,'bingo6',ctx.rows) as state:
            state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1')})
            ctx.current[0]['oddsGap']=Decimal('-1')
            raise ConnectionError('lost response')
    assert state['restored']


def test_authorization_exception_restores_and_reads_back(ctx):
    enabled=[True]
    ctx.level_name='一级代理'
    ctx.setting.open_target=lambda *args,**kwargs:None
    ctx.setting.is_earn_odds_gap_checked=lambda:enabled[0]
    def save(value):
        enabled[0]=value
        return {'status':204}
    ctx.setting.set_earn_odds_gap=save
    with pytest.raises(TimeoutError):
        with guarded_authorization(ctx) as state:
            state.update(attempted=True,expected=False)
            enabled[0]=False
            raise TimeoutError('child page')
    assert enabled[0] is True


@pytest.mark.parametrize('fail_off_request',[False,True])
def test_originally_disabled_authorization_cycles_and_restores_disabled(ctx, monkeypatch, fail_off_request):
    from xzh_qa import odds_gap_scenarios as scenarios
    from xzh_qa.odds_gap_audit import AuditBlocked
    enabled=[False]
    writes=[]
    ctx.level_name='一级代理'
    ctx.setting.open_target=lambda *args,**kwargs:None
    ctx.setting.is_earn_odds_gap_checked=lambda:enabled[0]
    ctx.setting.has_gap_tab=lambda:True
    def save(value):
        writes.append(value)
        if fail_off_request and len(writes)==2:
            raise TimeoutError('撤銷請求未生效')
        enabled[0]=value
        return {'status':204}
    ctx.setting.set_earn_odds_gap=save
    child=SimpleNamespace(**ctx.__dict__)
    child.account='aaa222'
    def blocked():raise AuditBlocked('缺測試凍結來源')
    monkeypatch.setattr(scenarios,'audit_preflight',blocked)
    monkeypatch.setattr(scenarios,'scope_games',lambda:['markSix'])
    with pytest.raises(TimeoutError if fail_off_request else pytest.skip.Exception):
        scenarios.run_authorization(None,lambda i:ctx if i==0 else child,ctx.run,indexes=[0])
    assert writes==([True,False,False] if fail_off_request else [True,False,True,False])
    assert enabled[0] is False
    if fail_off_request:return
    import json
    from pathlib import Path
    result=json.loads((Path(ctx.run.dir)/'b88-pairs.json').read_text(encoding='utf-8'))[0]
    assert result['restored'] and result['original_authorized'] is False
