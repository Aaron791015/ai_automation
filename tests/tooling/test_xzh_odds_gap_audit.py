"""凍結輸入與產品實值的反例測試，防止無資料／假資料誤判通過。"""
import json
from copy import deepcopy

import pytest

from xzh_qa.odds_gap_audit import (AuditBlocked, load_audit, verify_live_ids,
                                  verify_settlement, verify_pricing, zero_conditions, verify_special, truncation_coverage)
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS


@pytest.fixture
def audit(tmp_path):
    r=dict(betId='123',gameId='markSix',playTypeId='bonusNumberA',selection='01',issue='123',
           betAt='2026-09-16T01:00:00+00:00',settledAt='2026-09-16T02:00:00+00:00',
           inputSource='inputs.json',settlementSource='actual.json',chain=CHAIN_ACCOUNTS,
           memberAccount='aaa010',reportDate='2026-09-16',outcome='won',betAmount='100',
           companyShare='10',agentShares=['10']*9,diffs=['0']+['1']*9,
           actualGapMoney=[str(i*10) for i in range(1,10)],companyResolvedOdds='20',
           minOddsAtBet='1',chainGapsAtBet=['0']+['-1']*9,frozenOdds='11')
    for name in ('inputs.json','actual.json'):
        (tmp_path/name).write_text(json.dumps(r),encoding='utf-8')
    data={'schemaVersion':1,'scope':dict(date='2026-09-16',gameIds=['markSix'],
          memberAccount='aaa010',chain=CHAIN_ACCOUNTS,settlementState='settled',complete=True,betIds=['123']),
          'records':[r]}
    return data,tmp_path/'audit.json'


def read(data,path):
    path.write_text(json.dumps(data),encoding='utf-8')
    return load_audit(str(path),'2026-09-16',['markSix'])


def test_valid_full_scope_and_pricing(audit):
    data,path=audit
    loaded=read(data,path)
    verify_live_ids(loaded,['123'])
    assert verify_settlement(loaded['records'][0])['delta_sum']==0
    assert verify_pricing(loaded['records'][0])==11


@pytest.mark.parametrize('change',[
    lambda d:d.update(records=[]),
    lambda d:d['records'].append(deepcopy(d['records'][0])),
    lambda d:d['scope'].update(complete=False),
    lambda d:d['scope'].update(date='2026-09-15'),
    lambda d:d['scope'].update(gameIds=['bingo6']),
    lambda d:d['records'][0].update(companyShare=None),
    lambda d:d['records'][0].update(diffs=['NaN']*10),
    lambda d:d['records'][0].update(memberAccount='other'),
    lambda d:d['records'][0].update(inputSource='missing.json'),
    lambda d:d['records'][0].update(companyShare='20'),
])
def test_incomplete_or_inconsistent_audit_blocked(audit,change):
    data,path=audit
    change(data)
    with pytest.raises(AuditBlocked):read(data,path)


def rewrite_sources(record,path):
    for name in ('inputs.json','actual.json'):
        (path.parent/name).write_text(json.dumps(record),encoding='utf-8')


def test_holding_share_is_deducted_before_remit(audit):
    """自營總控：公司＋九層＋總控兩段＝投注額，上繳額先扣總控佔成（2026-09-29 新版文件）。"""
    data,path=audit
    record=data['records'][0]
    record.update(betAmount='110',holdingShare='10')
    rewrite_sources(record,path)
    result=verify_settlement(read(data,path)['records'][0])
    assert result['remit'][0]==10 and result['delta_sum']==0


def test_holding_share_is_not_inferred_from_unassigned_amount(audit):
    """投注額多出的差額沒有總控佔成來源時不反推成總控佔成，列 BLOCKED。"""
    data,path=audit
    record=data['records'][0]
    record.update(betAmount='110')
    rewrite_sources(record,path)
    with pytest.raises(AuditBlocked,match='未守恆'):read(data,path)


def test_actual_nonzero_on_loss_fails_not_oracle_only(audit):
    record=audit[0]['records'][0]
    record['outcome']='lost'
    with pytest.raises(AssertionError,match='九層收益錯誤'): verify_settlement(record)


def test_missing_live_bet_is_blocked(audit):
    with pytest.raises(AuditBlocked):verify_live_ids(audit[0],[])


def test_frozen_odds_mismatch_fails(audit):
    record=audit[0]['records'][0]
    record['frozenOdds']='20'
    with pytest.raises(AssertionError):verify_pricing(record)


def test_source_identity_mismatch_is_blocked(audit):
    data,path=audit
    source=json.loads((path.parent/'actual.json').read_text(encoding='utf-8'))
    source['issue']='different-issue'
    (path.parent/'actual.json').write_text(json.dumps(source),encoding='utf-8')
    with pytest.raises(AuditBlocked,match='實值不符'):read(data,path)


def test_fully_clipped_sample_does_not_prove_deepest_first(audit):
    record=deepcopy(audit[0]['records'][0])
    record['companyResolvedOdds']='1'
    record['minOddsAtBet']='1'
    assert truncation_coverage(record)=={'最低賠率截斷'}
    record['companyResolvedOdds']='5'
    assert truncation_coverage(record)=={'最低賠率截斷','最深層優先可辨識'}
    record['chainGapsAtBet']=['0']*9+['-9']
    assert truncation_coverage(record)=={'最低賠率截斷'}


@pytest.mark.parametrize('fault',[None,'duplicate','changing_total','empty_middle'])
def test_live_pagination_requires_every_page_and_stable_unique_ids(fault):
    from urllib.parse import urlsplit,parse_qs
    from xzh_qa.odds_gap_client import OddsGapClient
    client=OddsGapClient(None,'http://unused.invalid',{})
    queries=[]
    def get(path):
        params=parse_qs(urlsplit(path).query)
        queries.append(params)
        page=int(params['pageIndex'][0])
        ids=list(range((page-1)*25,min(page*25,51)))
        if fault=='duplicate' and page==2:ids[0]=0
        if fault=='empty_middle' and page==2:ids=[]
        return {'pageCount':3,'totalCount':52 if fault=='changing_total' and page==2 else 51,
                'items':[{'serialNumber':str(i)} for i in ids]}
    client._get=get
    if fault:
        with pytest.raises(AssertionError):client.all_member_bets(77,'2026-09-16',['markSix','bingo6'])
    else:
        bets=client.all_member_bets(77,'2026-09-16',['markSix','bingo6'])
        assert len(bets)==51
        assert [q['pageIndex'] for q in queries]==[['1'],['2'],['3']]
        assert all(q['gameIds']==['markSix','bingo6'] and q['settlementState']==['settled'] for q in queries)


def test_special_play_cannot_be_labelled_standard(audit):
    record=audit[0]['records'][0]
    record.update(playTypeId='pickTwoHitBonus',rule='standard')
    with pytest.raises(AuditBlocked,match='冒充'):verify_special(record)


@pytest.mark.parametrize('play', [f'miss{count}' for count in range(5, 13)])
@pytest.mark.parametrize('rule', ['standard', 'single-main', 'single-sub'])
def test_unresolved_miss_branch_never_assumes_pricing_rule(audit, play, rule):
    record=audit[0]['records'][0]
    record.update(playTypeId=play,rule=rule)
    with pytest.raises(AuditBlocked,match='規則尚未確認'):verify_special(record)


def test_special_full_coverage_keeps_eight_unresolved_sub_fields():
    from xzh_qa.odds_gap_audit import SPECIAL_REQUIRED
    assert {f'miss{count}:sub' for count in range(5, 13)} <= SPECIAL_REQUIRED


def test_unresolved_special_selection_does_not_block_independent_pricing(audit):
    record=audit[0]['records'][0]
    record.update(playTypeId='miss5',rule='standard')
    assert verify_pricing(record)==11
    with pytest.raises(AuditBlocked,match='規則尚未確認'):verify_special(record)


def test_main_branch_checks_actual_frozen_main_amount(audit):
    record=audit[0]['records'][0]
    record.update(playTypeId='zodiacHit',rule='single-main',frozenSubOddsGap=None,
                  frozenMainOddsGap='0')
    with pytest.raises(AssertionError,match='主差凍結'):verify_special(record)
    record['frozenMainOddsGap']='-9'
    assert verify_special(record)==11


def test_dual_branch_cannot_reuse_missing_other_inputs(audit):
    record=audit[0]['records'][0]
    record.update(playTypeId='pickTwoHitBonus',rule='dual-main',otherPricing={'frozenOdds':'11'})
    with pytest.raises(AuditBlocked,match='不能沿用'):verify_special(record)


def test_dual_branch_checks_both_frozen_sums(audit):
    record=audit[0]['records'][0]
    other={k:deepcopy(record[k]) for k in ('companyResolvedOdds','minOddsAtBet','chainGapsAtBet','frozenOdds','diffs')}
    record.update(playTypeId='pickTwoHitBonus',rule='dual-main',otherPricing=other,
                  frozenMainOddsGap='-9',frozenSubOddsGap='0',isSubOddsWin=False)
    with pytest.raises(AssertionError,match='副差合計'):verify_special(record)
    record['frozenSubOddsGap']='-9'
    assert verify_special(record)==11


def test_seven_all_zero_is_not_sync_evidence(audit):
    record=audit[0]['records'][0]
    record.update(playTypeId='sevenNumberOdd0',rule='seven',sevenRepresentative=0,
                  sevenLeafGaps={'odd0':'0','big0':'0','even7':'0','small7':'0'})
    with pytest.raises(AuditBlocked,match='全零'):verify_special(record)
    record['sevenLeafGaps']={key:'-1' for key in record['sevenLeafGaps']}
    assert verify_special(record)==11
    record['sevenLeafGaps']['big0']='-2'
    with pytest.raises(AssertionError,match='不同步'):verify_special(record)


@pytest.mark.parametrize('play', ['sevenNumberBig3', 'sevenNumberEven4', 'sevenNumberSmall7'])
def test_seven_non_odd_leaves_cannot_be_labelled_standard(audit, play):
    """七碼在注單層有 32 個葉，只認 `sevenNumberOdd` 前綴會讓其餘 24 個葉冒充一般分支直接通過。"""
    record=audit[0]['records'][0]
    record.update(playTypeId=play,rule='standard')
    with pytest.raises(AuditBlocked,match='冒充'):verify_special(record)


@pytest.mark.parametrize('play,k', [('sevenNumberOdd3',3),('sevenNumberBig3',3),
                                    ('sevenNumberEven4',3),('sevenNumberSmall4',3)])
def test_seven_representative_derived_from_leaf_id(audit,play,k):
    """单k≡大k≡双(7−k)≡小(7−k)：代表值由葉 id 反推，四個葉都要回到同一個 k。"""
    record=audit[0]['records'][0]
    record.update(playTypeId=play,rule='seven',
                  sevenLeafGaps={f'odd{k}':'-1',f'big{k}':'-1',f'even{7-k}':'-1',f'small{7-k}':'-1'})
    assert verify_special(record)==11


def test_seven_representative_self_label_cannot_override_leaf(audit):
    """自填的 sevenRepresentative 不得蓋過葉 id 反推的結果。"""
    record=audit[0]['records'][0]
    record.update(playTypeId='sevenNumberBig3',rule='seven',sevenRepresentative=5,
                  sevenLeafGaps={'odd3':'-1','big3':'-1','even4':'-1','small4':'-1'})
    with pytest.raises(AuditBlocked,match='不符'):verify_special(record)


@pytest.mark.parametrize('play', ['positionBigSmall','positionOddEven','positionDigitSumOddEven',
                                  'positionTailBigSmall','sumBigSmall'])
def test_two_way_leaves_cannot_count_as_standard(audit, play):
    """两面也是代表列，注單層 5 個葉不可當一般分支 —— 否則一注就會被當成「一般玩法已驗」。"""
    record=audit[0]['records'][0]
    record.update(playTypeId=play,rule='standard')
    with pytest.raises(AuditBlocked,match='冒充'):verify_special(record)


def test_linked_sub_branch_uses_sub_chain(audit):
    """連肖／連尾贏家為马／0尾時標 linked-sub，須核對副鏈凍結。

    贏家依 2026-09-29 Aaron 指定 `odds-gap (1).md` 判定：各成員先套差分與下限，取會員最終價最低者（同價取主層）；
    取代 2026-09-18「命中副標籤即走副鏈」裁定（Snotra-015 歷史）。本測試只驗標籤對應的凍結欄，不判定贏家。
    """
    record=audit[0]['records'][0]
    record.update(playTypeId='chainZodiac2Hit',rule='linked-sub',
                  frozenMainOddsGap='0',frozenSubOddsGap='-9')
    assert verify_special(record)==11
    record['frozenMainOddsGap']='1'
    with pytest.raises(AssertionError,match='使用副層卻凍結主差'):verify_special(record)


def test_linked_chain_coverage_requires_both_branches():
    """連肖／連尾主副兩支都要有樣本，只驗主鏈不算覆蓋完整。"""
    from xzh_qa.odds_gap_audit import SPECIAL_REQUIRED
    for chain in ('chainZodiac','chainTail'):
        for branch in ('main','sub'):
            assert f'{chain}:{branch}' in SPECIAL_REQUIRED


def test_zero_condition_is_per_level_not_all_levels(audit):
    record=audit[0]['records'][0]
    record['diffs'][2]='0'
    record['actualGapMoney'][1]='0'
    assert '有效差為零' in zero_conditions(record,verify_settlement(record))


@pytest.mark.parametrize('payout', ['100', '99', None])
def test_product_tie_requires_returned_principal_from_settlement_source(audit, payout):
    data,path=audit
    record=data['records'][0]
    record.update(outcome='tie',payout=payout,actualGapMoney=['0']*9)
    (path.parent/'actual.json').write_text(json.dumps(record),encoding='utf-8')
    if payout != '100':
        with pytest.raises(AuditBlocked):read(data,path)
    else:
        loaded=read(data,path)
        result=verify_settlement(loaded['records'][0])
        assert result['gap_money']==[0]*9
        assert zero_conditions(record,result)==['和局退本']


def test_tie_payout_cannot_be_added_without_source_evidence(audit):
    data,path=audit
    record=data['records'][0]
    record.update(outcome='tie',actualGapMoney=['0']*9)
    (path.parent/'actual.json').write_text(json.dumps(record),encoding='utf-8')
    record['payout']='100'
    with pytest.raises(AuditBlocked,match='實值不符'):read(data,path)


def test_unknown_outcome_cannot_be_assumed_zero(audit):
    record=audit[0]['records'][0]
    record.update(outcome='unknown',actualGapMoney=['0']*9)
    with pytest.raises(AuditBlocked,match='明確結算分支'):verify_settlement(record)
