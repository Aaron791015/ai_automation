"""離線故障注入：保存成功後逾時、未寫入、部分寫入及他人異動。"""
import json
from copy import deepcopy
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from xzh_qa.odds_gap_client import gap_values
from xzh_qa.odds_gap_run_state import OddsGapRunState, RestoreConflict
from xzh_qa.odds_gap_safety import guarded_gaps, guarded_authorization


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from xzh_qa import odds_gap_spec, odds_gap_safety
    monkeypatch.setattr(odds_gap_safety, 'NULL_TO_ZERO_REGISTRY', tmp_path/'null-to-zero-registry.json')
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
    from xzh_qa.odds_gap_safety import registered_null_to_zero
    assert registered_null_to_zero()==set()


def test_saved_row_sub_null_to_zero_is_tolerated_and_registered(ctx):
    """2026-10-06 方案 B：UI 保存 a 列會把 a 的副欄 NULL 送成 0、寫不回 NULL；只容許本批保存過的列並登記。"""
    from xzh_qa.odds_gap_safety import registered_null_to_zero
    with guarded_gaps(ctx,'markSix',ctx.rows) as state:
        state.update(attempted=True,expected={('a','oddsGap'):Decimal('-1.1')})
        ctx.current[0].update(oddsGap=Decimal('-1.1'),subOddsGap=0)
    assert state['restored'] and ctx.calls==['save']
    assert ctx.current[0]['oddsGap']==0 and ctx.current[0]['subOddsGap']==0
    assert registered_null_to_zero()=={('aaa111','markSix','a','subOddsGap')}


def test_restore_equal_tolerates_only_registered_sub_null_to_zero(ctx):
    from xzh_qa.odds_gap_safety import register_null_to_zero, restore_equal
    register_null_to_zero('aaa111','markSix',[('a','subOddsGap')],'offline')
    assert restore_equal('aaa111','markSix',ctx.rows,[dict(ctx.rows[0],subOddsGap=0),ctx.rows[1]])
    assert not restore_equal('aaa222','markSix',ctx.rows,[dict(ctx.rows[0],subOddsGap=0),ctx.rows[1]])
    assert not restore_equal('aaa111','bingo6',ctx.rows,[dict(ctx.rows[0],subOddsGap=0),ctx.rows[1]])
    assert not restore_equal('aaa111','markSix',ctx.rows,[ctx.rows[0],dict(ctx.rows[1],subOddsGap=0)])
    assert not restore_equal('aaa111','markSix',ctx.rows,[dict(ctx.rows[0],subOddsGap=Decimal('-0.01')),ctx.rows[1]])
    zero=[dict(r,subOddsGap=0) for r in ctx.rows]
    assert not restore_equal('aaa111','markSix',zero,[dict(zero[0],subOddsGap=None),zero[1]])


def test_baseline_diff_tolerates_only_registered_sub_null_to_zero(ctx):
    from xzh_qa.odds_gap_chain_plays import baseline_diff
    from xzh_qa.odds_gap_safety import register_null_to_zero
    register_null_to_zero('aaa111','markSix',[('a','subOddsGap')],'offline')
    ctx.current[0]['subOddsGap']=0
    ctx.current[1]['subOddsGap']=0
    baseline={'levels':[{'account':'aaa111','games':{'markSix':deepcopy(ctx.rows)}}]}
    cells,diffs=baseline_diff([ctx],baseline,games=('markSix',))
    assert cells==4
    assert diffs==[{'account':'aaa111','game':'markSix','play':'b','field':'subOddsGap','baseline':None,'now':0}]


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


_Q4 = Decimal('0.0001')


class _FakeBoundaryUI:
    """離線假前端：把「輸入→失焦後畫面值」「保存送不送出」「提示」做成可替換規則，驗 B91 的判定與還原。

    預設為規格行為（2026-10-06）：超位小數四捨五入到 4 位、`-.5`／`-1.`／`-0`／`0.0000`／`-01.1` 照規格存成；
    非數字（`abc`、`--1`）、清空、含逗號、正數都不保存並顯示提示。
    `current_qat=True` 重現 2026-10-05 的實測現況：非數字與清空失焦變 0.0000、含逗號被拿掉逗號，
    皆照存且沒有任何提示（Snotra-032）；正數仍被擋下。
    """

    def __init__(self, ctx, monkeypatch, *, current_qat=False, rounding=ROUND_HALF_UP, clipboard=False,
                 hint_mode='inline', shows_raw_abc=False, status_by_input=None, block_inputs=(), permanent=()):
        from xzh_qa import odds_gap_flows
        self.current_qat = current_qat
        self.rounding = rounding
        self.hint_mode = hint_mode            # inline：失焦即出現；late：點保存後才出現；toast：右下角通知
        self.shows_raw_abc = shows_raw_abc    # 現況下 abc 失焦後欄位仍顯示 abc（非數字），但保存的是 0
        self.status_by_input = status_by_input or {}
        self.block_inputs = set(block_inputs)
        self.raw = None
        self.persist = None
        self.hints = []
        self.hints_visible = False
        self.armed = False
        self.toast = []
        self.permanent = list(permanent)      # 列內常駐的錯誤類節點文字（輸入前就存在，不算提示）
        self.original_save = ctx.setting.save
        original_open = ctx.open
        ctx.open = lambda game: (setattr(self, 'hints_visible', False), original_open(game))[1]   # 重新開啟頁面後提示消失
        ctx.setting.fill_raw = self.fill_raw
        # clipboard：'api'（True）＝瀏覽器剪貼簿 API 可用；'fallback'＝只有 execCommand('copy')（QAT 是 http）；其餘＝皆不可用
        self.clip = None
        ctx.setting.paste_raw = self.fill_raw if clipboard in (True, 'api') else (lambda *args: None)
        ctx.page = SimpleNamespace(evaluate=self.set_clip if clipboard == 'fallback' else (lambda js, text: False),
                                   keyboard=SimpleNamespace(press=lambda key: None))
        ctx.setting.input_box = lambda i, col: _FakeBox(self, i, col)
        ctx.setting.messages = lambda: list(self.toast)
        ctx.setting.reload_tab = lambda game: None
        ctx.setting.save = self.save
        self.ctx = ctx
        monkeypatch.setattr(odds_gap_flows, 'read_row_hints',
                            lambda c, row, wait_ms=600: self.permanent + (list(self.hints) if self.hints_visible else []))

    def set_clip(self, js, text):
        assert 'execCommand' in js
        self.clip = text
        return True

    def blur(self, raw):
        """回傳（失焦後畫面值, 保存時實際送出的值或 None＝不送出, 提示清單）。"""
        text = raw.strip()
        if text in self.block_inputs:
            return text, None, []
        if text in ('', 'abc', '--1') or ',' in text:
            if not self.current_qat:
                return text, None, ['请输入正确的赔率']
            if ',' in text:
                value = Decimal(text.replace(',', ''))
                return str(value.quantize(_Q4)), value, []
            return ('abc' if self.shows_raw_abc and text == 'abc' else '0.0000'), Decimal(0), []
        value = Decimal(text)
        if value > 0:
            return str(value.quantize(_Q4)), None, ['只允许输入最大值 0']
        value = value.quantize(_Q4, rounding=self.rounding)
        return str(value), value, []

    def fill_raw(self, i, col, raw):
        shown, persist, hints = self.blur(raw)
        self.raw, self.persist, self.hints, self.armed = raw, persist, hints, True
        self.hints_visible = bool(hints) and self.hint_mode == 'inline'
        if persist is not None:
            self.ctx.setting.set_value(i, col, persist)
        return shown

    def save(self, allow_no_request=False):
        armed, self.armed = self.armed, False
        if armed:
            status = self.status_by_input.get(self.raw)
            if status is not None:
                self.toast = []
                return {'status': status}
            if self.persist is None:
                if self.hint_mode == 'late':
                    self.hints_visible = True
                self.toast = list(self.hints) if self.hint_mode == 'toast' else []
                return {'status': None}
        result = self.original_save()
        self.toast = ['更新成功'] if armed else []
        return result


class _FakeBox:
    """假輸入框：fill 清空、Ctrl+V 貼上剪貼簿文字（走與手動輸入同一套失焦規則）、input_value 讀失焦後的值。"""

    def __init__(self, ui, row, col):
        self.ui, self.row, self.col, self.shown = ui, row, col, ''

    def fill(self, text, force=False):
        self.shown = text

    def press(self, key):
        assert key == 'Control+V' and self.ui.clip is not None
        self.shown = self.ui.fill_raw(self.row, self.col, self.ui.clip)

    def input_value(self):
        return self.shown


def _prepare_boundary(ctx, monkeypatch, fields='a:oddsGap', inputs=None, original=Decimal(0)):
    monkeypatch.setenv('XZH_GAP_FIELDS', fields)
    monkeypatch.delenv('XZH_GAP_MAX_FIELDS', raising=False)
    if inputs is None:
        monkeypatch.delenv('XZH_GAP_BOUNDARY_INPUTS', raising=False)
    else:
        monkeypatch.setenv('XZH_GAP_BOUNDARY_INPUTS', json.dumps(inputs))
    for rows in (ctx.rows, ctx.current):
        for row in rows:
            row.update(playTypeName=row['playTypeId'], remainingOddsGap='5', subOddsLabel=None)
        rows[0]['oddsGap'] = original


def _boundary_result(ctx):
    return json.loads((Path(ctx.run.dir) / 'b91-aaa111-markSix.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('clipboard', ['api', 'fallback'])
def test_boundary_spec_conforming_ui_passes_every_condition_and_restores(ctx, monkeypatch, clipboard):
    """2026-10-06 規格：照存／存成的值讀回相符，應阻擋的輸入三條件齊備，正數不被保存；每筆寫入都還原。

    貼上兩條路徑都要能執行：瀏覽器剪貼簿 API（https）與 execCommand('copy')（QAT 是 http，API 不存在）。
    """
    from xzh_qa.odds_gap_flows import check_boundary_inputs, LEGAL_INPUTS, MUST_BLOCK_INPUTS
    _prepare_boundary(ctx, monkeypatch)
    ui = _FakeBoundaryUI(ctx, monkeypatch, clipboard=clipboard)
    result = check_boundary_inputs(ctx, 'markSix', {})
    assert gap_values(ctx.current) == gap_values(ctx.rows)
    assert result['undefined'] == [] and result['blocked'] == []
    assert len(result['legal']) == len(LEGAL_INPUTS) + 1 + 1, '照存條件＝表列＋貼上含空格＋超扣'
    assert all(x['ok'] for x in result['legal'])
    by_input = {x['input']: x for x in result['legal'] if x['mode'] == 'type'}
    for raw, expected in (('-0.12346', '-0.1235'), ('-0.00019', '-0.0002'), ('-0.00001', '0'), ('-.5', '-0.5'),
                          ('-1.', '-1'), ('-0', '0'), ('0.0000', '0'), ('-01.1', '-1.1'), ('-1000', '-1000')):
        assert by_input[raw]['read_back'] == Decimal(expected) and by_input[raw]['save_status'] == 204, raw
    paste_store = next(x for x in result['legal'] if x['mode'] == 'paste')
    assert paste_store['input'] == ' -1.1 ' and paste_store['read_back'] == Decimal('-1.1')
    overdraw = next(x for x in result['legal'] if x['mode'] == 'overdraw')
    assert overdraw['input'] == '-5.0001' and overdraw['expected'] == Decimal('-5.0001')
    assert len(result['must_block']) == len(MUST_BLOCK_INPUTS) + 1, '應阻擋＝表列＋貼上非數字'
    for x in result['must_block']:
        assert x['ok'] and x['save_status'] is None and x['read_back'] == x['original'] and x['hints'], x['input']
    assert len(result['positive']) == 1 and not result['positive_persisted']
    assert result['positive'][0]['save_status'] is None and result['positive'][0]['inline_hints']
    assert (ui.clip is not None) == (clipboard == 'fallback')


def test_boundary_without_clipboard_skips_only_the_paste_conditions(ctx, monkeypatch):
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch)
    _FakeBoundaryUI(ctx, monkeypatch, clipboard=False)
    with pytest.raises(pytest.skip.Exception, match='BLOCKED（部分）'):
        check_boundary_inputs(ctx, 'markSix', {})
    result = _boundary_result(ctx)
    assert [x['condition'] for x in result['blocked']] == ['貼上非數字文字', '貼上前後有空格的 -1.1，空格自動去掉']
    assert all("execCommand('copy') 皆不可用" in x['reason'] for x in result['blocked'])
    assert all(x['ok'] for x in result['legal'] + result['must_block'])
    assert gap_values(ctx.current) == gap_values(ctx.rows)


@pytest.mark.parametrize('shows_raw_abc', [False, True])
def test_boundary_current_qat_behavior_fails_with_snotra_032(ctx, monkeypatch, shows_raw_abc):
    """2026-10-05 現況：非數字、清空存成 0，含逗號被拿掉逗號，皆無提示 → 四種輸入（含貼上）都判 FAIL；其餘條件仍 PASS。

    shows_raw_abc=True：abc 失焦後欄位仍是文字（沒有確定送出值）但實際保存 0，
    守衛必須依讀回的實際值還原，否則測試資料留在被改過的狀態。
    """
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, original=Decimal('-0.01'))
    _FakeBoundaryUI(ctx, monkeypatch, current_qat=True, clipboard=True, shows_raw_abc=shows_raw_abc)
    with pytest.raises(AssertionError, match='Snotra-032') as caught:
        check_boundary_inputs(ctx, 'markSix', {})
    message = str(caught.value)
    assert '不符規格 5 項' in message and '合法輸入' not in message
    assert gap_values(ctx.current) == gap_values(ctx.rows), '每一筆寫入都要還原'
    result = _boundary_result(ctx)
    assert all(x['ok'] for x in result['legal']) and not result['positive_persisted']
    failed = {(x['mode'], x['input']): x for x in result['must_block']}
    assert set(failed) == {('type', 'abc'), ('type', '--1'), ('type', ''), ('type', '-1,000'), ('paste', 'abc')}
    assert not any(x['ok'] for x in failed.values())
    for x in failed.values():
        assert x['save_status'] == 204 and not x['save_refused'] and not x['unchanged'] and not x['hint_seen']
        assert x['hints'] == [], '右下角「更新成功」不算提示'
    assert Decimal(failed[('type', 'abc')]['read_back']) == 0
    assert Decimal(failed[('type', '-1,000')]['read_back']) == Decimal('-1000')
    assert any('保存成功（HTTP 204）' in r for r in failed[('type', '')]['reasons'])


@pytest.mark.parametrize('hint_mode', ['inline', 'late', 'toast'])
def test_boundary_must_block_accepts_hint_in_row_after_save_or_in_toast(ctx, monkeypatch, hint_mode):
    """提示的位置不限：列內行內紅字（失焦即出現或點保存後才出現）、右下角通知皆算；用字不比對。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['abc', ''], original=Decimal('-0.01'))
    _FakeBoundaryUI(ctx, monkeypatch, hint_mode=hint_mode)
    result = check_boundary_inputs(ctx, 'markSix', {})
    assert [x['input'] for x in result['must_block']] == ['abc', '']
    assert all(x['ok'] and x['hint_seen'] for x in result['must_block'])
    where = {'inline': 'inline_hints', 'late': 'hints_after_save'}.get(hint_mode)
    if where:
        assert all(x[where] for x in result['must_block'])
    else:
        assert all(x['inline_hints'] == [] and x['messages'] == ['请输入正确的赔率'] for x in result['must_block'])
    assert gap_values(ctx.current) == gap_values(ctx.rows)


@pytest.mark.parametrize('permanent', [(), ('剩余差分 0.0000',)])
def test_boundary_must_block_fails_when_no_hint_even_if_save_refused(ctx, monkeypatch, permanent):
    """擋下保存但沒有新出現的提示要判失敗；列內原本就有的錯誤類節點文字不能冒充提示。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['abc'], original=Decimal('-0.01'))
    ui = _FakeBoundaryUI(ctx, monkeypatch, permanent=permanent)
    ui.blur = lambda raw: (raw, None, [])   # 擋下保存但沒有任何提示
    with pytest.raises(AssertionError, match=r"畫面沒有任何提示") as caught:
        check_boundary_inputs(ctx, 'markSix', {})
    assert '保存成功' not in str(caught.value) and '讀回' not in str(caught.value)
    assert gap_values(ctx.current) == gap_values(ctx.rows)


@pytest.mark.parametrize('status,original,read_back,hints,ok,expect_reasons', [
    (None, 0, 0, ['x'], True, []),
    (400, 0, 0, ['x'], True, []),
    (422, 0, 0, ['x'], True, []),
    (204, 0, 0, ['x'], False, ['保存成功']),
    (200, 0, 0, ['x'], False, ['保存成功']),
    (None, 0, 0, [], False, ['沒有任何提示']),
    (None, Decimal('-0.01'), 0, ['x'], False, ['讀回']),
    (204, Decimal('-0.01'), 0, [], False, ['保存成功', '讀回', '沒有任何提示']),
])
def test_must_block_requires_all_three_points(status, original, read_back, hints, ok, expect_reasons):
    from xzh_qa.odds_gap_flows import judge_must_block
    verdict = judge_must_block(status, Decimal(original), Decimal(read_back), hints)
    assert verdict['ok'] is ok
    assert len(verdict['reasons']) == len(expect_reasons)
    for part, reason in zip(expect_reasons, verdict['reasons']):
        assert part in reason


@pytest.mark.parametrize('rounding', [ROUND_DOWN, ROUND_HALF_UP])
def test_precision_rounds_half_up_passes_and_truncation_fails(ctx, monkeypatch, rounding):
    """2026-10-06 規格：超位小數前端四捨五入到 4 位才符合；向零截斷（-0.1234、-0.0001）判 FAIL，仍還原。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['-0.12346', '-0.00019'])
    _FakeBoundaryUI(ctx, monkeypatch, rounding=rounding)
    if rounding == ROUND_HALF_UP:
        result = check_boundary_inputs(ctx, 'markSix', {})
        assert [(x['input'], x['read_back']) for x in result['legal']] == [
            ('-0.12346', Decimal('-0.1235')), ('-0.00019', Decimal('-0.0002'))]
        assert all(x['ok'] for x in result['legal'])
    else:
        with pytest.raises(AssertionError) as caught:
            check_boundary_inputs(ctx, 'markSix', {})
        message = str(caught.value)
        assert '輸入 \'-0.12346\'' in message and '讀回 -0.1234，期望 -0.1235' in message
        assert '讀回 -0.0001，期望 -0.0002' in message and 'Snotra-032' not in message
        assert not any(x['ok'] for x in _boundary_result(ctx)['legal'])
    assert gap_values(ctx.current) == gap_values(ctx.rows)


def test_boundary_store_condition_not_sent_is_recorded_and_other_conditions_continue(ctx, monkeypatch):
    """規格要存成的輸入若被前端擋下（沒送出保存）要判 FAIL，且其餘條件照常跑完、不因此中斷。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['-.5', '-1.', '-0.0001'])
    _FakeBoundaryUI(ctx, monkeypatch, block_inputs={'-.5'})
    with pytest.raises(AssertionError, match='合法輸入保存 HTTP None') as caught:
        check_boundary_inputs(ctx, 'markSix', {})
    assert '不符規格 1 項' in str(caught.value)
    result = _boundary_result(ctx)
    assert [(x['input'], x['ok']) for x in result['legal']] == [('-0.0001', True), ('-.5', False), ('-1.', True)]
    assert gap_values(ctx.current) == gap_values(ctx.rows)


def test_boundary_overdraw_rejected_is_failure_and_restored(ctx, monkeypatch):
    """2026-09-29 新版文件：儲存時不檢查超扣；超扣被拒絕保存要判失敗，不能列待確認。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch)
    _FakeBoundaryUI(ctx, monkeypatch, clipboard=True, status_by_input={'-5.0001': 400})
    with pytest.raises(AssertionError, match='合法輸入保存 HTTP 400'):
        check_boundary_inputs(ctx, 'markSix', {})
    assert gap_values(ctx.current) == gap_values(ctx.rows)


def test_boundary_unexpected_status_stops_immediately(ctx, monkeypatch):
    """非驗證類的回應（403、500 等）仍立即中止，不當成輸入判定；已寫入的由守衛還原。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['0'])
    _FakeBoundaryUI(ctx, monkeypatch, status_by_input={'0': 403})
    with pytest.raises(AssertionError, match='合法輸入保存 HTTP 403'):
        check_boundary_inputs(ctx, 'markSix', {})
    assert gap_values(ctx.current) == gap_values(ctx.rows)


def test_boundary_store_requires_successful_save_even_when_value_equals_original(ctx, monkeypatch):
    """原值本來就等於期望值（皆為 0）時，保存被拒（HTTP 400）仍要判失敗，不能只靠讀回相等。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['0'])
    _FakeBoundaryUI(ctx, monkeypatch, status_by_input={'0': 400})
    with pytest.raises(AssertionError, match='合法輸入保存 HTTP 400'):
        check_boundary_inputs(ctx, 'markSix', {})
    assert _boundary_result(ctx)['legal'][0]['read_back'] == '0'
    assert gap_values(ctx.current) == gap_values(ctx.rows)


def test_boundary_input_filter_accepts_new_conditions_and_rejects_unknown(ctx, monkeypatch):
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['', '-1,000'], original=Decimal('-0.01'))
    _FakeBoundaryUI(ctx, monkeypatch)
    result = check_boundary_inputs(ctx, 'markSix', {})
    assert [x['input'] for x in result['must_block']] == ['', '-1,000'] and result['legal'] == []
    _prepare_boundary(ctx, monkeypatch, inputs=['nope'])
    with pytest.raises(AssertionError, match='指定了未知邊界輸入'):
        check_boundary_inputs(ctx, 'markSix', {})


def test_positive_validation_is_isolated_per_field(ctx, monkeypatch):
    """正數的現行判定不變：逐欄單獨送出，某一欄被擋不會掩蓋其他欄；不得被保存成有效正差分。"""
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, fields='a:oddsGap,b:oddsGap', inputs=['1'])
    ui = _FakeBoundaryUI(ctx, monkeypatch)
    typed, sent = [], []
    fill, save = ctx.setting.fill_raw, ctx.setting.save
    def typing(i, col, raw):
        typed.append(i)
        return fill(i, col, raw)
    def saving(allow_no_request=False):
        sent.append(list(typed))
        typed.clear()
        return save(allow_no_request)
    ctx.setting.fill_raw, ctx.setting.save = typing, saving
    result = check_boundary_inputs(ctx, 'markSix', {})
    assert sent == [[0], [1]], '不能讓某一欄的驗證擋住其他欄測試'
    assert len(result['positive']) == 2 and not result['positive_persisted'] and ui.armed is False


def test_positive_saved_is_failure_and_restored(ctx, monkeypatch):
    from xzh_qa.odds_gap_flows import check_boundary_inputs
    _prepare_boundary(ctx, monkeypatch, inputs=['1'])
    ui = _FakeBoundaryUI(ctx, monkeypatch)
    ui.blur = lambda raw: ('1.0000', Decimal('1'), [])   # 缺陷情境：正數被保存
    with pytest.raises(AssertionError, match='正數被保存為有效正差分'):
        check_boundary_inputs(ctx, 'markSix', {})
    assert gap_values(ctx.current) == gap_values(ctx.rows)


def test_read_row_hints_strips_dedupes_and_waits_only_while_empty():
    from xzh_qa.odds_gap_flows import read_row_hints
    def make(reads):
        calls, waits, picked = [], [], []
        row = SimpleNamespace(locator=lambda selector: SimpleNamespace(
            all_inner_texts=lambda: calls.append(selector) or reads[min(len(calls) - 1, len(reads) - 1)]))
        setting = SimpleNamespace(_rows=lambda: SimpleNamespace(nth=lambda index: picked.append(index) or row))
        page = SimpleNamespace(wait_for_timeout=waits.append)
        return SimpleNamespace(setting=setting, page=page), calls, waits, picked
    ctx, calls, waits, picked = make([[], ['', ' 只允许输入最大值 0 ', '只允许输入最大值 0']])
    assert read_row_hints(ctx, 3) == ['只允许输入最大值 0']
    assert picked == [3] and calls == ['[class*="error"]'] * 2 and waits == [100]
    ctx, calls, waits, _ = make([[]])
    assert read_row_hints(ctx, 0, wait_ms=300) == [] and waits == [100, 100, 100]


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
