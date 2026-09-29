"""正式賓果基本回歸入口：獨立批次計畫，不讀 scratchpad 或固定日期／注單。

前置：依驗收操作文件提供 XZH_GAP_REGRESSION_PLAN 與同批批准識別。
缺計畫時在登入前 skip；下注結果不明不重送。自然結算另用唯讀入口。
"""
import json
import os
from pathlib import Path

import allure
import pytest

from xzh_qa.odds_gap_regression import BatchLedger, run_batch, validate_plan
from xzh_qa.odds_gap_regression_settlement import check_settlement

ROOT = Path(__file__).resolve().parents[2]


def _execute(request, kind):
    path = os.environ.get('XZH_GAP_REGRESSION_PLAN')
    if not path:
        pytest.skip('未提供本輪投注計畫；不啟動瀏覽器或下注')
    plan = validate_plan(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    if plan['kind'] != kind:
        pytest.skip('本批計畫未選取此情境')
    assert os.environ.get('XZH_GAP_REGRESSION_APPROVAL') == plan['batch_id'], '缺同批具體注數與總額批准識別'
    with allure.step('核對本批彩種、玩法、主副選項、批准注數及總額，建立不可重送帳本'):
        ledger = BatchLedger(ROOT / 'reports' / 'odds_gap_regression' / plan['batch_id'] / 'ledger.json', plan)
        allure.attach(json.dumps(plan, ensure_ascii=False), '測試範圍：本批賓果玩法與金額', allure.attachment_type.JSON)
    with allure.step('依計畫從UI保存差分與下注，核對新舊注單並還原設定'):
        run_batch(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                  request.getfixturevalue('odds_gap_run'), ledger)


@pytest.mark.write_action
@allure.title('功能驗證 B101：賓果主副代表下注，選對差分並保留凍結值')
def test_odds_gap_branches_regression(request):
    """前置條件：已批准branches計畫、QAT帳號鏈可用，記錄十層原值。
    操作步驟：UI輸入主-0.01副-0.02，保存→代表選項下注→還原。
    預期結果：各注使用對應主副鏈與最低值，還原後凍結不變。
    佐證方式：批次帳本、同期定價、實際注單及Allure。
    已知問題：副標籤異動或封盤停止；不擴稱所有玩法中獎通過。
    """
    _execute(request, 'branches')


@pytest.mark.write_action
@allure.title('功能驗證 B100：賓果A下注後改差分再下B，舊新注各自保留賠率')
def test_odds_gap_ab_regression(request):
    """前置條件：已批准ab計畫，選項与單注額明確，記錄十層原值。
    操作步驟：A主-0.01副-0.02下注→B主-0.02副-0.01下注→還原。
    預期結果：A保持原凍結值、B使用新差分，還原全部欄位。
    佐證方式：兩階段期號、定價快照、正式序號與Allure。
    已知問題：結算由唯讀入口接續，未結算不推定收益通過。
    """
    _execute(request, 'ab')


@pytest.mark.write_action
@allure.title('功能驗證 B88：賓果九級授權開關與恢復，新注生效且舊注不變')
def test_odds_gap_authorization_betting_regression(request):
    """前置條件：已批准authorization計畫、九級原授權開啟、記錄原值。
    操作步驟：設定尾數中主-0.01→開啟／關閉／恢復各下一注→還原。
    預期結果：會員差分隨九級授權休眠／恢復，舊注保留原值。
    佐證方式：授權讀回、當期公司來源、三筆注單與還原附件。
    已知問題：只驗九級至會員代表；深層混合授權依2026-09-29新版文件規格上不存在，由TC-004確認不能跳級開啟。
    """
    _execute(request, 'authorization')


@pytest.mark.write_action
@allure.title('功能驗證 B101：賓果尾數中未觸底與超過下限，凍結賠率取正確最低值')
def test_odds_gap_minimum_odds_regression(request):
    """前置條件：已批准minimum計畫，尾數中1尾、A盤、兩注，讀當期基準與最低值。
    操作步驟：十層各-0.0001下注→以基準減最低值計算足以觸底的四位差分下注→還原。
    預期結果：未觸底取基準加差分；觸底取最低值；兩筆各自凍結且不重送。
    佐證方式：獨立source／gaps／minimum、clientOdds及正式注單實際值。
    已知問題：只驗玩家下限保護，不以此推定各層縮減收益順序。
    """
    _execute(request, 'minimum')


@pytest.mark.write_action
@allure.title('功能驗證 B107：賓果只設主差分時，副層成交的注單是否不扣差分')
def test_odds_gap_sub_unset_regression(request):
    """前置條件：已批准sub-unset計畫（同一玩法主副各一注、單注額明確），記錄十層原值。
    操作步驟：十層主差分各-0.01、副差分維持0，保存讀回→副標籤選項與主選項各下一注→還原。
    預期結果：副層注單凍結賠率＝當期公司副賠率（不改扣主差分）；主層注單＝max(主最低, 主賠率−0.10)；還原全部欄位。
    佐證方式：批次帳本、同期定價、正式序號與Allure。
    已知問題：依2026-09-29新版文件「副差分未設即為0、不退回主差分」；只驗下注凍結，結算由唯讀入口接續。
    """
    _execute(request, 'sub-unset')


@pytest.mark.smoke
@allure.title('功能驗證 B98／B99：唯讀查回指定批次結算，核對凍結與九層收益')
def test_odds_gap_regression_settlement(request):
    """前置條件：XZH_GAP_REGRESSION_LEDGER指向已還原批次，不新增投注。
    操作步驟：登入公司確認會員→查回帳本序號與收益→逐注驗算。
    預期結果：凍結不變，收益與凍結占成及下注來源一致，缺中獎／取位規格列待補。
    佐證方式：結算附件列實際／期望、筆數、金額及收益範圍。
    已知問題：未自然結算立即SKIP不等待，混入其他注單時不得判通過。
    """
    path = os.environ.get('XZH_GAP_REGRESSION_LEDGER')
    if not path:
        pytest.skip('未指定既有帳本，不登入、不下注')
    evidence = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    validate_plan(evidence['plan'])
    assert evidence['restored'], '先處理未還原批次'
    with allure.step('UI核對會員身份後唯讀查回指定批次的注單與九層收益'):
        member = request.getfixturevalue('gap_context')(9, via='company')
        member.open('bingo6')
        assert member.account == evidence['accounts'][-1]['account'] and member.target_user_id == evidence['accounts'][-1]['id']
        chain = [r for r in member.reference_client.share_ancestors(member.target_user_id) if r['level'] != 'company']
        assert [{'account': r['account'], 'id': r['id']} for r in chain] == evidence['accounts'], '目前帳號鏈與下注時不同'
        result = check_settlement(member.reference_client, evidence, os.environ.get('XZH_PAYOUT_ROUNDING') or None)
        request.getfixturevalue('odds_gap_run').dump('settlement.json', result)
        allure.attach(json.dumps(result, ensure_ascii=False, default=str), '指定批次結算實際與期望', allure.attachment_type.JSON)
    if result['pending']:
        pytest.skip('指定注單尚未自然結算；保留帳本唯讀續查')
    assert all(r['ok'] for r in result['revenues']), '收益不符或報表混入其他注單'
    if result['missing_winners'] or result['rounding_pending']:
        pytest.skip('已核對可判定結果；缺中獎分支或派彩取位規格，詳附件')


@pytest.mark.write_action
@allure.title('功能驗證 B106：賓果连肖各成員套用差分與下限後取會員最終最低賠率')
def test_odds_gap_chain_winner_regression(request):
    """平台案例：功能驗證 B106：賓果连肖各成員套用差分與下限後取會員最終最低賠率
    前置條件：XZH_GAP_CHAIN_WINNER_BATCH 指定本批識別；XZH_GAP_CHAIN_WINNER_OFFSET（預設0.8）與 XZH_GAP_CHAIN_WINNER_BETS（預設兩注）指定偏移量與注單；注數、金額與公司本期手動偏移須經 Aaron 批准，記錄十層原值。
    測試範圍：宾果六合彩「二肖连中」；主受測「蛇＋马」、對照「马＋羊」。
    步驟：
    1. 公司逐層把十層「二肖连中」主差分各設-0.01、副差分（马）各設-0.02，保存後讀回。
    2. 公司即时盘面：步進值改為本批偏移量，按「二肖连中」蛇的減號一次（本期手動偏移；0.8時蛇4.8109→4.0109、0.85時→3.9609）。
    3. 會員前台同一期下本批指定的注單（「蛇＋马」、對照「马＋羊」）各2元，讀回凍結賠率。
    4. 按蛇的加號移除偏移、步進值改回0.005，十層差分還原並讀回。
    預期結果：各成員先套用差分與下限，再取最低會員賠率。偏移0.8時蛇最終3.9109、马最終3.8676，兩注均為3.8676（副層）；偏移0.85時蛇最終3.8609低於马3.8676，「蛇＋马」應為3.8609並走主層。
    佐證方式：批次帳本、偏移前後盤面API、注單序號與凍結賠率、Allure。
    已知問題：依2026-09-29 Aaron澄清（會員最終賠率取最低；主副同價層別待確認）；公司手動偏移會影響當期全站二肖连中蛇的賠率，僅本期有效並於結束時移除。
    """
    batch = os.environ.get('XZH_GAP_CHAIN_WINNER_BATCH')
    if not batch:
        pytest.skip('未提供本批識別；不啟動瀏覽器或下注')
    allure.attach('各成員先套用對應差分與下限，再比較會員最終價；不先比較公司價。',
                  name='預期結果：偏移0.8時兩注均為3.8676；偏移0.85時蛇＋马為3.8609並走主層')
    from xzh_qa.odds_gap_chain_winner import BETS, OFFSET, run_chain_winner
    names = [n for n in os.environ.get('XZH_GAP_CHAIN_WINNER_BETS', '').split(',') if n]
    bets = tuple(b for b in BETS if not names or b[0] in names)
    assert bets and (not names or len(bets) == len(names)), '指定的注單名稱不存在'
    run_chain_winner(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                     request.getfixturevalue('odds_gap_run'),
                     ROOT / 'reports' / 'odds_gap_regression' / batch / 'ledger.json',
                     offset=os.environ.get('XZH_GAP_CHAIN_WINNER_OFFSET') or OFFSET, bets=bets)
