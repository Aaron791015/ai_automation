"""正式賓果基本回歸入口：獨立批次計畫，不讀 scratchpad 或固定日期／注單。

前置：依驗收操作文件提供 XZH_GAP_REGRESSION_PLAN 與同批批准識別。
缺計畫時在登入前 skip；下注結果不明不重送。自然結算另用唯讀入口。
"""
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import allure
import pytest

from xzh_qa.odds_gap_regression import BatchLedger, run_batch, validate_plan
from xzh_qa.odds_gap_regression_settlement import PAYOUT_ROUNDING, check_settlement

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
    預期結果：凍結不變；派彩＝本金×凍結賠率四捨五入到 2 位，不符即失敗；收益與凍結占成及下注來源一致；本批沒有中獎的選項列待補。
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
        result = check_settlement(member.reference_client, evidence, os.environ.get('XZH_PAYOUT_ROUNDING') or PAYOUT_ROUNDING)
        request.getfixturevalue('odds_gap_run').dump('settlement.json', result)
        allure.attach(json.dumps(result, ensure_ascii=False, default=str), '指定批次結算實際與期望', allure.attachment_type.JSON)
    if result['pending']:
        pytest.skip('指定注單尚未自然結算；保留帳本唯讀續查')
    assert all(r['ok'] for r in result['revenues']), '收益不符或報表混入其他注單'
    if result['missing_winners']:
        pytest.skip('派彩與收益已核對相符；本批有選項沒有中獎，缺中獎樣本列待補，詳附件')


@pytest.mark.write_action
@allure.title('功能驗證 B106：賓果连肖先套差分與下限再取最低，同價取主層')
def test_odds_gap_chain_winner_regression(request):
    """平台案例：功能驗證 B106：賓果连肖先套差分與下限再取最低，同價取主層
    前置條件：XZH_GAP_CHAIN_WINNER_BATCH 指定本批識別；XZH_GAP_CHAIN_WINNER_OFFSET（預設0.8）與 XZH_GAP_CHAIN_WINNER_BETS（預設兩注）指定偏移量與注單；注數、金額與公司本期手動偏移須經 Aaron 批准，記錄十層原值。
    測試範圍：宾果六合彩「二肖连中」；主受測「蛇＋马」、對照「马＋羊」。
    步驟：
    1. 公司逐層把十層「二肖连中」主差分各設-0.01、副差分（马）各設-0.02，保存後讀回。
    2. 公司即时盘面：「赔率调整」步進值只能選0.001～1的固定選項，依序選步進值並按「二肖连中」蛇的減號，合計等於本批偏移量（本期手動偏移；0.85＝0.5一次、0.1三次、0.05一次，蛇4.8109→3.9609；0.8時→4.0109）。
    3. 會員前台同一期下本批指定的注單（「蛇＋马」、對照「马＋羊」）各2元，讀回凍結賠率。
    4. 以同樣方式按蛇的加號移除偏移、步進值改回0.005，十層差分還原並讀回。
    預期結果：各候選先套差分與有效下限，再取會員最終最低價；主副最終同價取主層。偏移0.8時「蛇＋马」應為3.8676（副層）；偏移0.85時應為3.8609（主層）；對照「马＋羊」為3.8676（副層）。含例外成員的候選有效下限不高於該候選解析價。
    佐證方式：批次帳本、偏移前後盤面API、注單序號與凍結賠率、Allure。
    已知問題：Snotra-018（偏移0.85應3.8609、修復前實際3.8676）已於2026-10-05重新下注確認成交價修復並關單，偏移0.8樣本一向符合；依Aaron指定odds-gap (1).md §3.4／§4.3及chain-zodiac-tail-priced-odds.md §3.3；公司手動偏移會影響當期全站二肖连中蛇的賠率，僅本期有效並於結束時移除。
    """
    batch = os.environ.get('XZH_GAP_CHAIN_WINNER_BATCH')
    if not batch:
        pytest.skip('未提供本批識別；不啟動瀏覽器或下注')
    allure.attach('各候選先套差分與有效下限，再取會員最低賠率；最終同價取主層。',
                  name='預期結果：偏移0.8時蛇＋马為3.8676（副層）、偏移0.85時為3.8609（主層）；马＋羊為3.8676（副層）')
    from xzh_qa.odds_gap_chain_winner import BETS, OFFSET, run_chain_winner
    names = [n for n in os.environ.get('XZH_GAP_CHAIN_WINNER_BETS', '').split(',') if n]
    bets = tuple(b for b in BETS if not names or b[0] in names)
    assert bets and (not names or len(bets) == len(names)), '指定的注單名稱不存在'
    run_chain_winner(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                     request.getfixturevalue('odds_gap_run'),
                     ROOT / 'reports' / 'odds_gap_regression' / batch / 'ledger.json',
                     offset=os.environ.get('XZH_GAP_CHAIN_WINNER_OFFSET') or OFFSET, bets=bets)


def _run_chain_variant(request, env_name, case, offset, gaps):
    """B112～B115 共用：`env_name` 指定本批識別，沒給就在登入前 skip；兩注固定為「蛇,马」與「马,羊」各2元。"""
    batch = os.environ.get(env_name)
    if not batch:
        pytest.skip('未提供本批識別；不啟動瀏覽器或下注')
    from xzh_qa.odds_gap_chain_winner import run_chain_winner
    run_chain_winner(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                     request.getfixturevalue('odds_gap_run'),
                     ROOT / 'reports' / 'odds_gap_regression' / batch / 'ledger.json',
                     offset=offset, gaps=gaps, case=case)


@pytest.mark.write_action
@allure.title('[邏輯驗證] B112：连肖：十層差分皆為 0、只把蛇本期賠率調低 0.85 時，「蛇,马」是否以蛇的較低賠率成交')
def test_odds_gap_chain_offset_without_gap_regression(request):
    """平台案例：[邏輯驗證] B112：连肖：十層差分皆為 0、只把蛇本期賠率調低 0.85 時，「蛇,马」是否以蛇的較低賠率成交
    前置條件：XZH_GAP_CHAIN_NOGAP_BATCH 指定本批識別；注數（2注各2元）與公司本期手動偏移須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用。
    測試範圍：宾果六合彩「二肖连中」，主受測「蛇＋马」、對照「马＋羊」；只適用這一個玩法，因為要在同一期做公司手動偏移再下注（宾果為高頻彩種），且马是二肖连中的副標籤（例外成員）。這是 Snotra-018 的對照情境，用來排除差分的影響。
    步驟：
    1. 公司讀回十層（aaa111～aaa999、會員 aaa010）「赔率差分」的「二肖连中」主差分與副差分，不是 0 的層改成 0 並保存。
    2. 公司「即时盘面」→ 宾果六合彩 → 连肖：「赔率调整」依序選 0.5、0.1、0.1、0.1、0.05，每選一次按「二肖连中」蛇的「−」（合計 −0.85，蛇 4.8109→3.9609）。
    3. 會員前台同一期「生肖连」→「二肖连中」下「蛇＋马」、「马＋羊」各 2 元，讀回注單賠率。
    4. 依序按蛇的「＋」加回偏移、步進值改回 0.005；改過的差分還原並逐層讀回。
    預期結果：「蛇＋马」＝3.9609（蛇偏移後低於马的副賠率 4.0676，取蛇、主層）；「马＋羊」＝4.0676（马的副賠率，副層）。差分為 0，不扣任何差分。
    佐證方式：批次帳本（十層差分讀回、偏移前後盤面、注單序號與凍結賠率）、Allure 附件。
    已知問題：2026-10-01 期115055472 以腳本實測，「蛇＋马」實際 4.0676（取马的副賠率），對照「马＋羊」4.0676 符合，已開 Snotra-021；2026-10-05 期115056332 重新下注「蛇＋马」3.9609、「马＋羊」4.0676 皆符合，Snotra-021 已修復關單；公司手動偏移會影響當期全站二肖连中蛇的賠率，只在本期有效並於結束時移除。
    """
    allure.attach('十層差分皆為 0；蛇偏移 −0.85 後 3.9609 低於马副賠率 4.0676 → 蛇＋马取蛇 3.9609（主層）；马＋羊取马 4.0676（副層）。',
                  name='預期結果：蛇＋马為3.9609（主層）、马＋羊為4.0676（副層）')
    _run_chain_variant(request, 'XZH_GAP_CHAIN_NOGAP_BATCH', 'B112', Decimal('0.85'), (Decimal(0), Decimal(0)))


@pytest.mark.write_action
@allure.title('[邏輯驗證] B113：连肖：十層主差分各 −0.01、副差分各 −0.02 且不調整賠率時，含马的兩注是否都以马的副賠率扣副差分成交')
def test_odds_gap_chain_gap_without_offset_regression(request):
    """平台案例：[邏輯驗證] B113：连肖：十層主差分各 −0.01、副差分各 −0.02 且不調整賠率時，含马的兩注是否都以马的副賠率扣副差分成交
    前置條件：XZH_GAP_CHAIN_NOOFFSET_BATCH 指定本批識別；注數（2注各2元）須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值。
    測試範圍：宾果六合彩「二肖连中」，「蛇＋马」與「马＋羊」；只適用這一個玩法，因為马是二肖连中的副標籤（例外成員）。這是 Snotra-018 的對照情境：不做手動偏移時，含马的組合本來就應走马的副層。
    步驟：
    1. 公司在十層（aaa111～aaa999、會員 aaa010）「赔率差分」把「二肖连中」主差分各設 −0.01、副差分各設 −0.02，保存後逐層讀回（合計主 −0.10、副 −0.20）。
    2. 確認公司「即时盘面」宾果六合彩「二肖连中」蛇、马、羊本期賠率皆等於公司賠率 4.8109，沒有手動偏移。
    3. 會員前台同一期「生肖连」→「二肖连中」下「蛇＋马」、「马＋羊」各 2 元，讀回注單賠率。
    4. 十層差分還原並逐層讀回。
    預期結果：兩注皆＝3.8676（马的副賠率 4.0676 − 副差分合計 0.20，低於蛇／羊 4.8109 − 0.10 ＝ 4.7109，取马、副層）。
    佐證方式：批次帳本（十層差分讀回、盤面賠率、注單序號與凍結賠率）、Allure 附件。
    已知問題：2026-10-01 期115055474 以腳本實測兩注皆 3.8676，符合。
    """
    allure.attach('马副賠率 4.0676 − 0.20 ＝ 3.8676；蛇／羊 4.8109 − 0.10 ＝ 4.7109 → 兩注皆取马 3.8676（副層）。',
                  name='預期結果：蛇＋马與马＋羊皆為3.8676（副層）')
    _run_chain_variant(request, 'XZH_GAP_CHAIN_NOOFFSET_BATCH', 'B113', Decimal(0), (Decimal('-0.01'), Decimal('-0.02')))


#: B114 各層差分（aaa111～aaa999、會員 aaa010）：主差分一至三級 −0.0944、四級至會員 −0.0943，副差分一律 −0.0200；
#: 合計主 −0.9433、副 −0.2000，使蛇（主層）4.8109−0.9433 與马（副層）4.0676−0.2000 同為 3.8676（2026-10-01 Aaron 指定）。
B114_LAYER_GAPS = tuple((Decimal('-0.0944') if level < 3 else Decimal('-0.0943'), Decimal('-0.0200')) for level in range(10))


@pytest.mark.write_action
@allure.title('[邏輯驗證] B114：连肖：十層差分使蛇（主層）與马（副層）扣完後同為 3.8676 時，含马的兩注是否以 3.8676 成交（同價取主層）')
def test_odds_gap_chain_equal_price_layer_gaps_regression(request):
    """平台案例：[邏輯驗證] B114：连肖：十層差分使蛇（主層）與马（副層）扣完後同為 3.8676 時，含马的兩注是否以 3.8676 成交（同價取主層）
    前置條件：XZH_GAP_CHAIN_TIE_BATCH 指定本批識別；注數（2注各2元）須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值。
    測試範圍：宾果六合彩「二肖连中」，「蛇＋马」與「马＋羊」；只適用這一個玩法，因為马是二肖连中的副標籤（例外成員）。各層差分：主差分一至三級（aaa111～aaa333）−0.0944、四級至會員（aaa444～aaa999、aaa010）−0.0943；副差分十層皆 −0.0200。
    步驟：
    1. 公司在十層「赔率差分」依測試範圍逐層設定「二肖连中」主差分與副差分，保存後逐層讀回（合計主 −0.9433、副 −0.2000）。
    2. 確認公司「即时盘面」宾果六合彩「二肖连中」蛇、马、羊本期賠率皆等於公司賠率 4.8109，沒有手動偏移。
    3. 會員前台同一期「生肖连」→「二肖连中」下「蛇＋马」、「马＋羊」各 2 元，讀回注單賠率。
    4. 十層差分還原並逐層讀回。
    預期結果：主層 4.8109 − 0.9433 ＝ 3.8676（高於主最低 3.8487）、副層马 4.0676 − 0.2000 ＝ 3.8676（高於副最低 3.2541），兩層同價取主層：「蛇＋马」取蛇、「马＋羊」取羊，兩注皆＝3.8676。
    佐證方式：批次帳本（十層差分讀回、盤面賠率、注單序號與凍結賠率）、Allure 附件。
    已知問題：兩層同為 3.8676，注單賠率無法分辨系統取主層或副層；層別要靠逐層凍結的代理賠率（尚無可讀來源，交接 T71②）或中獎後各層「赔率差金额」判定，本案例只判成交價。主差分合計超過剩餘差分（超扣），依 2026-09-29 新版文件保存時不檢查超扣。原「主層觸底」設定（主 −0.13／−0.12、副 −0.05）2026-10-01 改編號為 B115，兩個版本並存。
    """
    allure.attach('主層 4.8109 − 0.9433 ＝ 3.8676；马副層 4.0676 − 0.2000 ＝ 3.8676；同價取主層 → 蛇＋马取蛇、马＋羊取羊，兩注皆 3.8676。',
                  name='預期結果：蛇＋马與马＋羊皆為3.8676（同價取主層）')
    _run_chain_variant(request, 'XZH_GAP_CHAIN_TIE_BATCH', 'B114', Decimal(0), B114_LAYER_GAPS)


#: B115 各層差分（aaa111～aaa999、會員 aaa010）：一至四級主 −0.13、五級至會員主 −0.12，副一律 −0.05；合計主 −1.24、副 −0.50（2026-10-01 Aaron 指定）。
B115_LAYER_GAPS = tuple((Decimal('-0.13') if level < 4 else Decimal('-0.12'), Decimal('-0.05')) for level in range(10))


@pytest.mark.write_action
@allure.title('[邏輯驗證] B115：连肖：十層主差分合計 −1.24 使主層觸到最低賠率、副差分合計 −0.50 時，含马的兩注是否都以马扣副差分後的賠率成交')
def test_odds_gap_chain_floor_with_layer_gaps_regression(request):
    """平台案例：[邏輯驗證] B115：连肖：十層主差分合計 −1.24 使主層觸到最低賠率、副差分合計 −0.50 時，含马的兩注是否都以马扣副差分後的賠率成交
    前置條件：XZH_GAP_CHAIN_FLOOR_BATCH 指定本批識別；注數（2注各2元）須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值。
    測試範圍：宾果六合彩「二肖连中」，「蛇＋马」與「马＋羊」；只適用這一個玩法，因為马是二肖连中的副標籤（例外成員）。各層差分：一至四級（aaa111～aaa444）主 −0.13、副 −0.05；五級至會員（aaa555～aaa999、aaa010）主 −0.12、副 −0.05。
    步驟：
    1. 公司在十層「赔率差分」依測試範圍逐層設定「二肖连中」主差分與副差分，保存後逐層讀回（合計主 −1.24、副 −0.50）。
    2. 確認公司「即时盘面」宾果六合彩「二肖连中」蛇、马、羊本期賠率皆等於公司賠率 4.8109，沒有手動偏移。
    3. 會員前台同一期「生肖连」→「二肖连中」下「蛇＋马」、「马＋羊」各 2 元，讀回注單賠率。
    4. 十層差分還原並逐層讀回。
    預期結果：主層 4.8109 − 1.24 ＝ 3.5709 低於主最低 3.8487，蛇／羊最終為 3.8487；副層马 4.0676 − 0.50 ＝ 3.5676，高於副最低 3.2541；兩注皆＝3.5676（取马、副層）。
    佐證方式：批次帳本（十層差分讀回、盤面賠率、注單序號與凍結賠率）、Allure 附件。
    已知問題：主差分合計超過剩餘差分（超扣）；依 2026-09-29 新版文件保存時不檢查超扣，若保存被拒則本案例在設定步驟失敗並還原。兩注皆由马定價，無法鑑別 Snotra-018（含马即取副價）的問題；逐層凍結欄與觸底縮減順序不在本案例判定。2026-10-01 以 B114 編號首跑（期115055484）PASS，同日改編號為 B115。
    """
    allure.attach('主層 4.8109 − 1.24 ＝ 3.5709，觸底為 3.8487；马副層 4.0676 − 0.50 ＝ 3.5676（高於副最低 3.2541）→ 兩注皆取马 3.5676（副層）。',
                  name='預期結果：蛇＋马與马＋羊皆為3.5676（副層）')
    _run_chain_variant(request, 'XZH_GAP_CHAIN_FLOOR_BATCH', 'B115', Decimal(0), B115_LAYER_GAPS)


def _chain_plays_progress():
    """`XZH_GAP_CHAIN_PLAYS_PROGRESS` 指定檔案時，每個進度事件附加一行 JSON（外部監看用）。"""
    path = os.environ.get('XZH_GAP_CHAIN_PLAYS_PROGRESS')
    if not path:
        return None

    def write(event):
        with open(path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps({'at': datetime.now().astimezone().isoformat(timespec='seconds'), **event}, ensure_ascii=False) + '\n')
    return write


def _run_chain_plays(request, env_name, case, scenario):
    """B116～B118 共用：`env_name` 指定本批識別，沒給就在登入前 skip；每玩法兩注各2元，一個情境同一期連續下完。

    `XZH_GAP_CHAIN_PLAYS_ONLY`（玩法ID，逗號分隔）與 `XZH_GAP_CHAIN_PLAYS_BETS`（tested／control）供續跑補下；
    `XZH_GAP_CHAIN_PLAYS_BASELINE` 指向全表基準 JSON 時，寫入前與還原後各做一次十層三彩種逐格比對。
    """
    batch = os.environ.get(env_name)
    if not batch:
        pytest.skip('未提供本批識別；不啟動瀏覽器或下注')
    from xzh_qa.odds_gap_chain_plays import run_chain_scenario
    only = [p for p in os.environ.get('XZH_GAP_CHAIN_PLAYS_ONLY', '').split(',') if p] or None
    bets = [b for b in os.environ.get('XZH_GAP_CHAIN_PLAYS_BETS', '').split(',') if b] or None
    run_chain_scenario(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                       request.getfixturevalue('odds_gap_run'),
                       ROOT / 'reports' / 'odds_gap_regression' / batch / 'ledger.json',
                       scenario, case, plays=only, bets=bets,
                       baseline_path=os.environ.get('XZH_GAP_CHAIN_PLAYS_BASELINE') or None,
                       progress=_chain_plays_progress())


@pytest.mark.write_action
@allure.title('[邏輯驗證] B116：连肖／连尾：十層主差分各 −0.01、副差分各 −0.02 且不調整賠率時，含副標籤成員的每一注是否都以副賠率扣副差分成交')
def test_odds_gap_chain_plays_flat_regression(request):
    """平台案例：[邏輯驗證] B116：连肖／连尾：十層主差分各 −0.01、副差分各 −0.02 且不調整賠率時，含副標籤成員的每一注是否都以副賠率扣副差分成交
    前置條件：XZH_GAP_CHAIN_PLAYS_FLAT_BATCH 指定本批識別；注數（6個玩法×2注各2元）須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值；不做公司手動偏移。
    測試範圍：宾果六合彩「生肖连」的三肖连中、四肖连中、五肖连中（副標籤马）與「尾数连」的二尾连不中、三尾连不中、四尾连不中（副標籤0）共6個玩法；每個玩法下「受測」「對照」兩注，兩注都含副標籤成員。只適用這6個玩法：二肖连中已由 B112～B115 驗證，其餘連肖／連尾玩法沒有副賠率；本案例目前只在宾果六合彩執行（高頻彩種、可同期連續下注），英國天天彩每日一期、香港六合彩目前無開盤期，待排程後比照。
    步驟：
    1. 公司在十層（aaa111～aaa999、會員 aaa010）「赔率差分」依測試範圍的6個玩法把主差分各設 −0.01、副差分各設 −0.02，保存後逐層讀回（每個玩法合計主 −0.10、副 −0.20）。
    2. 確認公司「即时盘面」宾果六合彩「连肖」「连尾」各玩法成員的本期賠率皆等於公司賠率，沒有手動偏移。
    3. 會員前台同一期依序在「生肖连」「尾数连」下測試範圍各玩法的受測、對照兩注各2元，記錄送出賠率並讀回注單賠率。
    4. 十層差分由上往下還原並逐層讀回，再把全表與原始設定逐格比對。
    預期結果：每注先扣差分再比，副層候選＝副賠率 − 0.20 低於主層候選＝主賠率 − 0.10，故每注成交價＝副賠率 − 0.20：三肖连中 10.0866、四肖连中 29.601、五肖连中 104.3579、二尾连不中 4.3476、三尾连不中 12.4082、四尾连不中 41.4465；送出賠率、注單賠率與獨立算式三者相同。
    佐證方式：批次帳本（十層差分讀回、盤面成員賠率、送出請求、注單序號與凍結賠率）、Allure 附件逐注核對表。
    已知問題：兩注都含副標籤成員且不偏移，副層本來就最低，無法鑑別 Snotra-018／021（含副標籤成員時一般成員較低仍取副賠率）；那兩單的情境（差分皆 0、偏移一般成員）屬 B112 型，需動公司盤面偏移；Snotra-018／021 已於 2026-10-05 修復關單，本玩法的 B112 型情境尚未補。
    """
    allure.attach('每注：副賠率 − 0.20 低於主賠率 − 0.10 → 取副層；三肖 10.0866／四肖 29.601／五肖 104.3579／二尾 4.3476／三尾 12.4082／四尾 41.4465。',
                  name='預期結果：6個玩法每注皆為副賠率扣副差分合計 0.20')
    _run_chain_plays(request, 'XZH_GAP_CHAIN_PLAYS_FLAT_BATCH', 'B116', 'flat')


@pytest.mark.write_action
@allure.title('[邏輯驗證] B117：连肖／连尾：十層差分使主層與副層扣完後同價時，含副標籤成員的每一注是否以該價成交（同價取主層）')
def test_odds_gap_chain_plays_tie_regression(request):
    """平台案例：[邏輯驗證] B117：连肖／连尾：十層差分使主層與副層扣完後同價時，含副標籤成員的每一注是否以該價成交（同價取主層）
    前置條件：XZH_GAP_CHAIN_PLAYS_TIE_BATCH 指定本批識別；注數（5個玩法×2注各2元）須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值；不做公司手動偏移。
    測試範圍：宾果六合彩「生肖连」的三肖连中、四肖连中、五肖连中（副標籤马）與「尾数连」的二尾连不中、三尾连不中（副標籤0）共5個玩法；每個玩法下「受測」「對照」兩注，兩注都含副標籤成員。四尾连不中不適用：其主賠率最低值 43.4572 高於副賠率 41.6465，不偏移時主層價恆大於副層價，不可能同價。英國天天彩、香港六合彩目前不執行，原因同 B116。
    步驟：
    1. 公司在十層「赔率差分」依測試範圍的5個玩法逐層設定主差分與副差分，使每個玩法主層與副層扣完後同價（副差分合計：三肖／四肖／五肖 −0.20、二尾 −0.10、三尾 0；主差分合計依主賠率反算），保存後逐層讀回。
    2. 確認公司「即时盘面」宾果六合彩「连肖」「连尾」各玩法成員的本期賠率皆等於公司賠率，沒有手動偏移。
    3. 會員前台同一期依序在「生肖连」「尾数连」下測試範圍各玩法的受測、對照兩注各2元，記錄送出賠率並讀回注單賠率。
    4. 十層差分由上往下還原並逐層讀回，再把全表與原始設定逐格比對。
    預期結果：主層與副層同價，同價取主層，成交價＝同價值：三肖连中 10.0866（主合計 −2.1795／副 −0.20）、四肖连中 29.601（−6.265／−0.20）、五肖连中 104.3579（−22.8261／−0.20）、二尾连不中 4.4476（−1.0647／−0.10）、三尾连不中 12.6082（−3.152／0，剛好落在主層最低值）；送出賠率、注單賠率與獨立算式三者相同。
    佐證方式：批次帳本（十層差分讀回、盤面成員賠率、送出請求、注單序號與凍結賠率）、Allure 附件逐注核對表。
    已知問題：兩層同價時注單賠率分不出取主層或副層，層別要靠中獎後各層「赔率差金额」判定，本案例只判成交價；主差分合計超過剩餘差分（超扣），依 2026-09-29 新版文件保存時不檢查超扣；四尾连不中的同價設計不存在，不補；B112 型情境待 Snotra-018／021 修正後補。
    """
    allure.attach('主層與副層扣完後同價 → 同價取主層：三肖 10.0866／四肖 29.601／五肖 104.3579／二尾 4.4476／三尾 12.6082（四尾不適用）。',
                  name='預期結果：5個玩法每注皆為主副同價值（同價取主層）')
    _run_chain_plays(request, 'XZH_GAP_CHAIN_PLAYS_TIE_BATCH', 'B117', 'tie')


@pytest.mark.write_action
@allure.title('[邏輯驗證] B118：连肖／连尾：十層主差分合計使主層觸到最低賠率、副層仍較低時，含副標籤成員的每一注是否都以副層賠率成交')
def test_odds_gap_chain_plays_floor_regression(request):
    """平台案例：[邏輯驗證] B118：连肖／连尾：十層主差分合計使主層觸到最低賠率、副層仍較低時，含副標籤成員的每一注是否都以副層賠率成交
    前置條件：XZH_GAP_CHAIN_PLAYS_FLOOR_BATCH 指定本批識別；注數（6個玩法×2注各2元）須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值；不做公司手動偏移。
    測試範圍：宾果六合彩「生肖连」的三肖连中、四肖连中、五肖连中（副標籤马）與「尾数连」的二尾连不中、三尾连不中、四尾连不中（副標籤0）共6個玩法；每個玩法下「受測」「對照」兩注，兩注都含副標籤成員。英國天天彩、香港六合彩目前不執行，原因同 B116。
    步驟：
    1. 公司在十層「赔率差分」依測試範圍的6個玩法逐層設定主差分與副差分，使主層扣差分後低於主賠率最低值（觸底）、副層扣差分後仍高於副賠率最低值（每個玩法合計主／副：三肖 −2.80／−1.00、四肖 −7.50／−3.00、五肖 −25.80／−10.00、二尾 −1.40／−0.50、三尾 −3.50／−1.20、四尾 −11.50／−4.00），保存後逐層讀回。
    2. 確認公司「即时盘面」宾果六合彩「连肖」「连尾」各玩法成員的本期賠率皆等於公司賠率，沒有手動偏移。
    3. 會員前台同一期依序在「生肖连」「尾数连」下測試範圍各玩法的受測、對照兩注各2元，記錄送出賠率並讀回注單賠率。
    4. 十層差分由上往下還原並逐層讀回，再把全表與原始設定逐格比對。
    預期結果：主層觸底成為主賠率最低值，副層較低，每注成交價＝副層價：三肖连中 9.2866、四肖连中 26.801、五肖连中 94.5579、二尾连不中 4.0476、三尾连不中 11.4082、四尾连不中 37.6465；送出賠率、注單賠率與獨立算式三者相同。
    佐證方式：批次帳本（十層差分讀回、盤面成員賠率、送出請求、注單序號與凍結賠率）、Allure 附件逐注核對表。
    已知問題：主差分合計超過剩餘差分（超扣），依 2026-09-29 新版文件保存時不檢查超扣；只驗成交價，觸底後各層縮減順序與逐層凍結欄不在本案例判定；兩注都由副標籤成員定價，無法鑑別 Snotra-018／021；Snotra-018／021 已於 2026-10-05 修復關單，本玩法的 B112 型情境尚未補。
    """
    allure.attach('主層觸底（主賠率最低值）高於副層價 → 每注取副層：三肖 9.2866／四肖 26.801／五肖 94.5579／二尾 4.0476／三尾 11.4082／四尾 37.6465。',
                  name='預期結果：6個玩法每注皆為副層價（主層觸底、副層較低）')
    _run_chain_plays(request, 'XZH_GAP_CHAIN_PLAYS_FLOOR_BATCH', 'B118', 'floor')


@pytest.mark.write_action
@allure.title('[邏輯驗證] B119：连肖／连尾：組合不含副標籤成員時，各注是否都以主賠率扣主差分成交，並追到主分支中獎注供核對派彩與九層賠率差金額')
def test_odds_gap_chain_main_chase_regression(request):
    """平台案例：[邏輯驗證] B119：连肖／连尾：組合不含副標籤成員時，各注是否都以主賠率扣主差分成交，並追到主分支中獎注供核對派彩與九層賠率差金額
    前置條件：XZH_GAP_CHASE_BATCH 指定本批識別（前綴 gap-t61-chainmain-20261002-）；XZH_GAP_CHASE_PLAYS（玩法ID，逗號分隔）、XZH_GAP_CHASE_STOP（停止時間，格式 HH:MM）、XZH_GAP_CHASE_MAX_BETS、XZH_GAP_CHASE_MAX_YUAN 指定本段範圍與額度，須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；記錄十層原值；不做公司手動偏移。
    測試範圍：宾果六合彩「生肖连」的三肖连中、四肖连中、五肖连中與「尾数连」的二尾连不中、三尾连不中、四尾连不中共6個玩法；組合一律不含副標籤成員（连肖不含马、连尾不含0），每期對每個玩法下多組互不重複且盡量分散的組合各2元，某玩法取得中獎後停止該玩法。目前只在宾果六合彩執行（高頻彩種，可逐期追樣本），英國天天彩與香港六合彩待排程。
    步驟：
    1. 公司在十層（aaa111～aaa999、會員 aaa010）「赔率差分」依測試範圍的玩法把主差分設為各層不同的 −0.011～−0.020（合計 −0.155）、副差分設為各層不同的 −0.022～−0.040（合計 −0.310），保存後逐層讀回。
    2. 會員前台逐期在「生肖连」「尾数连」對測試範圍各玩法下不含副標籤成員的分散組合各2元，記錄送出賠率並讀回注單賠率；開獎後某玩法有中獎注就停止該玩法，到停止時間或額度用完也停止。
    3. 十層差分由上往下還原並逐層讀回，再把全表與原始設定逐格比對。
    4. 中獎注自然結算後，唯讀核對派彩（本金×凍結賠率）與公司「报表」九層「赔率差金额」增量是否等於依主鏈各層差分算出的獨立值。
    預期結果：每注先扣差分再比，不含副標籤成員的組合只有主層候選，成交價＝主賠率 − 0.155（二尾连不中 5.3573、三肖连中 12.1111、三尾连不中 15.6052、四肖连中 35.711、四尾连不中 54.1665、五肖连中 127.029）；送出賠率、注單賠率與獨立算式三者相同；中獎注派彩＝本金×凍結賠率，九層賠率差金額依主鏈各層有效差計算。
    佐證方式：批次帳本（十層差分讀回、盤面成員賠率、送出請求、注單序號與凍結賠率、各期開獎號碼與預測輸贏）、Allure 附件逐注核對表、結算核對輸出。
    已知問題：中獎機率低（單注二尾连不中約17.9%、三肖连中約8.0%、三尾连不中約6.3%、四肖连中約2.75%、四尾连不中約1.8%、五肖连中約0.78%），時間內沒追到的玩法只驗到下注價，缺主分支中獎樣本；派彩取位規格未定，只列觀察值。
    """
    batch = os.environ.get('XZH_GAP_CHASE_BATCH')
    if not batch:
        pytest.skip('未提供本批識別；不啟動瀏覽器或下注')
    from xzh_qa.odds_gap_chain_chase import run_chain_main_chase
    plays = [p for p in os.environ.get('XZH_GAP_CHASE_PLAYS', '').split(',') if p]
    assert plays, '須以 XZH_GAP_CHASE_PLAYS 指定玩法'
    hour, minute = os.environ['XZH_GAP_CHASE_STOP'].split(':')
    stop_at = datetime.now().astimezone().replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    skip = [p for p in os.environ.get('XZH_GAP_CHASE_SKIP', '').split(',') if p]
    per_issue = {k: int(v) for k, v in (x.split('=') for x in os.environ.get('XZH_GAP_CHASE_PER_ISSUE', '').split(',') if x)}
    allure.attach('不含副標籤成員的組合只有主層候選：成交價＝主賠率 − 0.155；二尾 5.3573／三肖 12.1111／三尾 15.6052／四肖 35.711／四尾 54.1665／五肖 127.029。',
                  name='預期結果：各注皆為主賠率扣主差分合計 0.155（主層）')
    run_chain_main_chase(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                         request.getfixturevalue('odds_gap_run'),
                         ROOT / 'reports' / 'odds_gap_regression' / batch / 'ledger.json', 'B119', plays, stop_at,
                         int(os.environ.get('XZH_GAP_CHASE_MAX_BETS', '0')), Decimal(os.environ.get('XZH_GAP_CHASE_MAX_YUAN', '0')),
                         per_issue=per_issue, baseline_path=os.environ.get('XZH_GAP_CHAIN_PLAYS_BASELINE') or None,
                         progress=_chain_plays_progress(), skip_plays=skip)


def _run_chain_lower(request, env_name, case, with_gap):
    """B120／B121 共用：`env_name` 指定本批識別，沒給就在登入前 skip；`XZH_GAP_CHAIN_LOWER_MAX_BETS`（批准注數上限）必填。

    `XZH_GAP_CHAIN_LOWER_PLAYS`（玩法ID，逗號分隔）供續跑；`XZH_GAP_CHAIN_PLAYS_BASELINE` 指向全表基準 JSON 時，
    寫入前與還原後各做一次十層三彩種逐格比對。另一條帳號鏈的鎖取不到等受阻玩法，全部核對完才列 SKIP（部分受阻）。
    """
    batch = os.environ.get(env_name)
    if not batch:
        pytest.skip('未提供本批識別；不啟動瀏覽器或下注')
    max_bets = os.environ.get('XZH_GAP_CHAIN_LOWER_MAX_BETS')
    assert max_bets, '須以 XZH_GAP_CHAIN_LOWER_MAX_BETS 指定 Aaron 批准的注數上限'
    from xzh_qa.odds_gap_chain_lower import run_chain_lower
    plays = [p for p in os.environ.get('XZH_GAP_CHAIN_LOWER_PLAYS', '').split(',') if p] or None
    data = run_chain_lower(request.getfixturevalue('browser'), request.getfixturevalue('gap_context'),
                           request.getfixturevalue('odds_gap_run'),
                           ROOT / 'reports' / 'odds_gap_regression' / batch / 'ledger.json',
                           with_gap, case, plays=plays, max_bets=int(max_bets),
                           baseline_path=os.environ.get('XZH_GAP_CHAIN_PLAYS_BASELINE') or None,
                           progress=_chain_plays_progress())
    if data['blocked']:
        pytest.skip('BLOCKED（部分）：' + '；'.join(f"{b['play']} {b['reason']}" for b in data['blocked']))


@pytest.mark.write_action
@allure.title('[邏輯驗證] B120：连肖／连尾：十層差分皆為 0、只把蛇或1尾本期賠率調低到低於副賠率時，同時含副標籤成員與該成員的注是否以調低後的賠率成交')
def test_odds_gap_chain_lower_without_gap_regression(request):
    """平台案例：[邏輯驗證] B120：连肖／连尾：十層差分皆為 0、只把蛇或1尾本期賠率調低到低於副賠率時，同時含副標籤成員與該成員的注是否以調低後的賠率成交
    前置條件：XZH_GAP_CHAIN_LOWER_NOGAP_BATCH 指定本批識別；XZH_GAP_CHAIN_LOWER_MAX_BETS 指定 Aaron 批准的注數上限（現行賠率下 4 個玩法×2注各2元＝8注16元）；公司本期手動偏移須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；測試範圍各玩法的十層差分須皆為 0；調整期間另取另一條帳號鏈的鎖，取不到的玩法列受阻、不調整。
    測試範圍：宾果六合彩「生肖连」的三肖连中、四肖连中、五肖连中（調低蛇，副標籤马）與「尾数连」的二尾连不中、三尾连不中、四尾连不中（調低1尾，副標籤0）共6個玩法；每個玩法下「受測」（含被調低成員與副標籤成員）、「對照」（只含副標籤成員）兩注。二肖连中已由 B112 驗證；三尾连不中（副賠率等於主賠率最低值）與四尾连不中（主賠率最低值高於副賠率）在現行賠率下找不到可行的調整量，執行時依當下賠率判定後列「不適用」、不下注。只在宾果六合彩執行（高頻彩種，可在同一期調整後下注），英國天天彩、香港六合彩待排程。
    步驟：
    1. 讀公司賠率，逐玩法算出調整量，使蛇（或1尾）調低後低於副賠率、又高於主賠率最低值（依 2026-10-05 賠率：三肖 2.10、四肖 6.50、五肖 24.00、二尾 1.05）。
    2. 逐玩法等剩餘時間足夠的新期，公司「即时盘面」宾果六合彩「连肖」或「连尾」依「赔率调整」步進值按該成員的減號，合計等於調整量並讀回。
    3. 會員前台同一期在「生肖连」或「尾数连」下該玩法受測、對照兩注各2元，記錄送出賠率並讀回注單賠率。
    4. 依讀回值按加號加回調整、步進值改回原值並讀回，再做下一個玩法；最後把十層全表與原始設定逐格比對。
    預期結果：受測注由被調低成員以主層成交＝主賠率 − 調整量：三肖连中 12.2661 − 2.10＝10.1661、四肖连中 35.866 − 6.50＝29.366、五肖连中 127.184 − 24.00＝103.184、二尾连不中 5.5123 − 1.05＝4.4623；對照注由副標籤成員以副層成交＝副賠率：10.2866、29.801、104.5579、4.5476；送出賠率、注單賠率與獨立算式三者相同（實跑以下注當下讀到的賠率重算）。
    佐證方式：批次帳本（各玩法調整量算式、每次按鈕前後的盤面賠率、送出請求、注單序號與凍結賠率、加回後讀回）、Allure 附件逐注核對表。
    已知問題：只判成交價，不追中獎樣本（主層中獎樣本已於 2026-10-06 由 Aaron 裁示風險接受）；公司手動偏移會影響當期全站宾果該成員的賠率，只在本期有效，每個玩法結束時加回；2026-10-05 以臨時腳本實跑同一情境 8／8 相符，本案例由其改寫（交接 T104③）。
    """
    allure.attach('受測注＝主賠率 − 調整量（主層）：三肖 10.1661／四肖 29.366／五肖 103.184／二尾 4.4623；對照注＝副賠率（副層）：10.2866／29.801／104.5579／4.5476；三尾、四尾不適用。',
                  name='預期結果：受測注以被調低成員的主層價成交、對照注以副賠率成交')
    _run_chain_lower(request, 'XZH_GAP_CHAIN_LOWER_NOGAP_BATCH', 'B120', with_gap=False)


@pytest.mark.write_action
@allure.title('[邏輯驗證] B121：连肖／连尾：十層主、副差分各層同值且把蛇或1尾本期賠率調低時，同時含副標籤成員與該成員的注是否以調低後賠率扣主差分成交')
def test_odds_gap_chain_lower_with_gap_regression(request):
    """平台案例：[邏輯驗證] B121：连肖／连尾：十層主、副差分各層同值且把蛇或1尾本期賠率調低時，同時含副標籤成員與該成員的注是否以調低後賠率扣主差分成交
    前置條件：XZH_GAP_CHAIN_LOWER_GAP_BATCH 指定本批識別；XZH_GAP_CHAIN_LOWER_MAX_BETS 指定 Aaron 批准的注數上限（現行賠率下 4 個玩法×2注各2元＝8注16元）；公司本期手動偏移與十層差分寫入須經 Aaron 批准；aaa111～aaa999、會員 aaa010 帳號鏈可用；測試範圍各玩法的十層差分開工時須皆為 0，記錄十層原值；調整期間另取另一條帳號鏈的鎖，取不到的玩法列受阻、不調整。
    測試範圍：宾果六合彩「生肖连」的三肖连中、四肖连中、五肖连中（調低蛇，副標籤马）與「尾数连」的二尾连不中、三尾连不中、四尾连不中（調低1尾，副標籤0）共6個玩法；每個玩法下「受測」（含被調低成員與副標籤成員）、「對照」（只含副標籤成員）兩注。二肖连中已由 B106 驗證；三尾连不中、四尾连不中在現行賠率下找不到可行的調整量，執行時依當下賠率判定後列「不適用」、不下注。只在宾果六合彩執行，英國天天彩、香港六合彩待排程。
    步驟：
    1. 讀公司賠率，逐玩法決定每層差分與調整量：每層主 −0.01、副 −0.02（二尾连不中區間太窄改每層主 −0.001、副 −0.002），使蛇（或1尾）調低並扣主差分後低於副層、又高於主賠率最低值（依 2026-10-05 賠率：三肖 2.20、四肖 6.50、五肖 24.00、二尾 1.03）。
    2. 公司在十層（aaa111～aaa999、會員 aaa010）「赔率差分」保存各玩法的主差分與副差分並逐層讀回。
    3. 逐玩法等剩餘時間足夠的新期，公司「即时盘面」把該成員調低並讀回，會員前台同一期在「生肖连」或「尾数连」下受測、對照兩注各2元，記錄送出賠率並讀回注單賠率，再加回調整並讀回。
    4. 十層差分由上往下還原並逐層讀回，再把全表與原始設定逐格比對。
    預期結果：受測注由被調低成員以主層成交＝（主賠率 − 調整量）＋主差分合計：三肖连中（12.2661 − 2.20）− 0.10＝9.9661、四肖连中（35.866 − 6.50）− 0.10＝29.266、五肖连中（127.184 − 24.00）− 0.10＝103.084、二尾连不中（5.5123 − 1.03）− 0.01＝4.4723；對照注由副標籤成員以副層成交＝副賠率＋副差分合計：10.0866、29.601、104.3579、4.5276；送出賠率、注單賠率與獨立算式三者相同（實跑以下注當下讀到的賠率重算）。誤取副標籤成員會是對照注的值，把副差分扣在被調低成員上會是（主賠率 − 調整量）＋副差分合計，兩者都與預期不同。
    佐證方式：批次帳本（各玩法差分與調整量算式、十層差分讀回、每次按鈕前後的盤面賠率、送出請求、注單序號與凍結賠率、加回後讀回）、Allure 附件逐注核對表。
    已知問題：只判成交價，不追中獎樣本（主層中獎樣本已於 2026-10-06 由 Aaron 裁示風險接受）；公司手動偏移會影響當期全站宾果該成員的賠率，只在本期有效，每個玩法結束時加回；2026-10-05 以臨時腳本實跑同一情境 8／8 相符（當時五肖調整量取 23.00、成交 104.084，本案例的選法固定為點擊次數最少且較接近區間中點的 24.00），本案例由其改寫（交接 T104③）。
    """
    allure.attach('受測注＝（主賠率 − 調整量）＋主差分合計（主層）：三肖 9.9661／四肖 29.266／五肖 103.084／二尾 4.4723；對照注＝副賠率＋副差分合計（副層）：10.0866／29.601／104.3579／4.5276；三尾、四尾不適用。',
                  name='預期結果：受測注以被調低成員扣主差分的主層價成交、對照注以副賠率扣副差分成交')
    _run_chain_lower(request, 'XZH_GAP_CHAIN_LOWER_GAP_BATCH', 'B121', with_gap=True)
