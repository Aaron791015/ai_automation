"""公司取消賺取賠率差授權的下級檢查；Snotra-012 回歸。

只操作 QAT 指定帳號鏈，所有寫入走 UI。下級未具備條件時 SKIP，
不將既有缺陷標成 xfail；保存成功而違反規則必須 FAIL。
"""
import json
import os
from pathlib import Path
from decimal import Decimal

import allure
import pytest

from qa_common.shot import capture_annotated
from xzh_qa.config_loader import admin_credentials, qat
from xzh_qa.odds_gap_client import GAMES, OddsGapClient
from xzh_qa.pages.login_page import LoginPage
from xzh_qa.pages.dashboard_page import AgentHierarchyPage
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS, OddsGapSettingPage
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

EXPECTED_MESSAGE = '下级已允许赚取赔率差，请先修改下级'
GUARD_GAMES = {key: GAMES[key] for key in os.environ.get('XZH_AUTH_GUARD_GAMES', ','.join(GAMES)).split(',')}
_SESSION_UI_TARGET_IDS = {}


class AuthorizationGuard:
    def __init__(self, page, run):
        self.page, self.run = page, run
        self.settings = OddsGapSettingPage(page)
        self.observed = OddsGapClient.attach(page)
        self.target_ids = _SESSION_UI_TARGET_IDS

    def gap_snapshot(self, name):
        """以UI確認身分後唯讀指定彩種全鏈設定；不把授權休眠誤認為設定清空。"""
        if not self.target_ids:
            for index, account in enumerate(CHAIN_ACCOUNTS):
                count = len(self.observed['target_user_ids'])
                self.settings.open_target(AgentHierarchyPage.LEVELS[index], account)
                if len(GUARD_GAMES) == 1:
                    self.settings.select_game(next(iter(GUARD_GAMES)))
                self.page.wait_for_function('() => document.querySelectorAll("tr input[type=number]").length > 0')
                self.page.wait_for_timeout(300)
                assert len(self.observed['target_user_ids']) > count, f'{account}缺少UI目標識別證據'
                self.target_ids[account] = self.observed['target_user_ids'][-1]
        client = OddsGapClient.from_page(self.page, self.observed)
        actual = {account: {game: client.gap_setting(target_id, game) for game in GUARD_GAMES}
                  for account, target_id in self.target_ids.items()}
        self.run.dump(name + '.json', actual)
        self.run.dump('ui-target-ids.json', self.target_ids)
        return actual

    def read(self, index):
        if '/auth/' in self.page.url:
            login = LoginPage(self.page)
            login.goto(qat()['backend_company_url'])
            login.login(*admin_credentials())
            if login.is_otp_page():
                login.submit_otp('123456')
        try:
            self.settings.open_target(AgentHierarchyPage.LEVELS[index], CHAIN_ACCOUNTS[index], require_gap=False)
        except PlaywrightTimeoutError:
            self.page.reload(wait_until='domcontentloaded')
            self.settings.open_target(AgentHierarchyPage.LEVELS[index], CHAIN_ACCOUNTS[index], require_gap=False)
        self.settings.open_basic_info()
        # 先等基本資料表單載入，避免將尚未渲染誤判為沒有開關。
        self.page.get_by_role('button', name='保存', exact=True).wait_for(state='visible')
        self.page.wait_for_timeout(300)
        checkbox = self.settings.earn_odds_gap_checkbox()
        return checkbox.is_checked() if checkbox.count() else None

    def ui_settings_evidence(self, snapshot, name, index=0):
        """逐彩種讀回代表帳號現有主副欄，並標注主副代表列。"""
        account = CHAIN_ACCOUNTS[index]
        self.settings.open_target(AgentHierarchyPage.LEVELS[index], account)
        evidence = {}
        for game in GUARD_GAMES:
            self.settings.select_game(game)
            api = snapshot[account][game]
            ui = self.settings.wait_rows_match(api)
            checked = 0
            for row, expected in zip(ui, api):
                wanted = [expected.get('oddsGap')]
                if expected.get('subOddsLabel'):
                    wanted.append(expected.get('subOddsGap'))
                assert len(row['inputs']) == len(wanted), f'{account}/{game}/{row["name"]}主副欄數不符'
                for actual, target in zip(row['inputs'], wanted):
                    assert Decimal(actual or '0') == Decimal(str(target or 0)), f'{account}/{game}/{row["name"]} UI/API差分不符'
                    checked += 1
            evidence[game] = {'account': account, 'rows': len(ui), 'fields': checked, 'ui': ui,
                              'api': api, 'equal': True, 'page_url': self.page.url}
            self.run.dump(f'{name}-{game}.json', evidence[game])
            marks = []
            samples = [0] + [i for i, r in enumerate(api) if r.get('subOddsLabel')][:1]
            for i in dict.fromkeys(samples):
                self.settings._rows().nth(i).evaluate('(e, i)=>e.setAttribute("data-guard-ui-row", String(i))', i)
                marks.append({'selector': f'[data-guard-ui-row="{i}"]', 'label': f'{api[i]["playTypeName"]}：UI差分與API原值相符'})
            shot = str(Path(self.run.dir) / f'{name}-{game}.png')
            self.page.mouse.move(5, 5)
            capture_annotated(self.page, shot, marks=marks,
                              note=f'Snotra-012／{account}／{GAMES[game]}／{checked}現有主副欄讀回一致')
            allure.attach.file(shot, name=f'{name}-{game}', attachment_type=allure.attachment_type.PNG)
        self.run.dump(name + '.json', evidence)
        return evidence

    def snapshot(self):
        return {account: self.read(i) for i, account in enumerate(CHAIN_ACCOUNTS)}

    def save(self, enabled, name):
        """不等待特定HTTP：允許正確產品由前端直接阻擋；保留瞬間提示。"""
        responses = []

        def response_received(response):
            if '/api/Users/' in response.url and response.request.method in ('PUT', 'POST', 'PATCH'):
                responses.append({'status': response.status, 'body': response.text()[:2000]})

        self.settings.open_basic_info()
        if self.settings.earn_odds_gap_checkbox().is_checked() != enabled:
            self.settings.earn_odds_gap_label().click()
        self.page.evaluate("""() => {
            window.__gapMessages = [];
            window.__gapObserver?.disconnect();
            const collect = () => document.querySelectorAll(
                '.el-message, .el-notification, [role="alert"], .el-message-box'
            ).forEach(e => { if (e.innerText) window.__gapMessages.push(e.innerText); });
            window.__gapObserver = new MutationObserver(collect);
            window.__gapObserver.observe(document.body, {subtree:true, childList:true, characterData:true});
        }""")
        self.page.on('response', response_received)
        try:
            self.page.get_by_role('button', name='保存', exact=True).click(no_wait_after=True)
            try:
                self.page.wait_for_function(
                    '() => (window.__gapMessages || []).length > 0', timeout=5000)
            except Exception:
                # 沒提示也須留下回應及重開值，交由明確斷言判FAIL。
                pass
            self.page.wait_for_timeout(500)
            messages = self.page.evaluate('() => window.__gapMessages || []')
            body = self.page.locator('body').inner_text()
            evidence = {'responses': responses, 'messages': messages,
                        'messageMatched': EXPECTED_MESSAGE in '\n'.join(messages + [body])}
            self.run.dump(name + '.json', evidence)
            allure.attach(json.dumps(evidence, ensure_ascii=False), name, allure.attachment_type.JSON)
            try:
                self.page.mouse.move(5, 5)
                self.page.wait_for_timeout(300)
                shot = str(Path(self.run.dir) / (name + '.png'))
                marks = []
                if self.settings.earn_odds_gap_label().count():
                    self.settings.earn_odds_gap_label().evaluate("e=>e.setAttribute('data-guard-proof','1')")
                    marks = [{'selector': '[data-guard-proof="1"]', 'label': '本次授權保存目標'}]
                modal = self.page.locator('.el-message-box:visible')
                if modal.count():
                    modal.evaluate("e=>e.setAttribute('data-guard-modal','1')")
                    marks = [{'selector': '[data-guard-modal="1"]', 'label': '實際拒絕提示；預期下級已允許，請先修改下級'}]
                if self.page.locator('.el-message:visible').count():
                    self.page.locator('.el-message:visible').first.evaluate("e=>e.setAttribute('data-guard-toast','1')")
                    marks.append({'selector': '[data-guard-toast="1"]', 'label': '實際提示；預期下級開啟時應拒絕'})
                capture_annotated(self.page, shot,
                    marks=marks,
                    note=f'Snotra-012／嘗試授權={enabled}／HTTP={[r["status"] for r in responses]}／指定提示匹配={evidence["messageMatched"]}',
                    strict=not bool(modal.count()))
                allure.attach.file(shot, name=name, attachment_type=allure.attachment_type.PNG)
            except Exception as exc:
                evidence['captureError'] = str(exc)
                self.run.dump(name + '.json', evidence)
                allure.attach(str(exc), name + '-capture-error', allure.attachment_type.TEXT)
            return evidence
        finally:
            self.page.remove_listener('response', response_received)
            modal = self.page.locator('.el-message-box:visible')
            if modal.count():
                modal.get_by_role('button', name='确认', exact=True).click()
            try:
                self.page.evaluate('() => window.__gapObserver?.disconnect()')
            except Exception:
                pass

    def restore(self, index, baseline):
        """異常／斷言失敗也還原本次目標；其他層異動則停止，不覆蓋。"""
        try:
            account = CHAIN_ACCOUNTS[index]
            current = self.read(index)
            if current != baseline[account]:
                assert current is not None, '還原時找不到授權欄位'
                self.save(baseline[account], 'restore')
                assert self.read(index) == baseline[account], '目標授權還原後仍不一致'
            final = self.snapshot()
            self.run.dump('final.json', final)
            assert final == baseline, '非本次目標層狀態異動，未擅自覆寫'
            self.run.dump('restore-result.json', {'restored': True})
        except Exception as exc:
            self.run.dump('restore-pending.json', {'index': index, 'baseline': baseline, 'error': str(exc)})
            pytest.exit(f'授權還原待處理，停止後續測試：{self.run.dir}', returncode=2)


@pytest.fixture
def auth_guard(odds_gap_login, odds_gap_run):
    return AuthorizationGuard(odds_gap_login('__company__'), odds_gap_run)


@allure.title('[功能] TC-001：公司查看帳號鏈的賺取賠率差授權狀態')
def test_odds_gap_authorization_inventory(auth_guard):
    """前置條件：QAT公司帳號可查看指定十個帳號。
    測試範圍：帳號層授權，不分彩種與玩法。
    操作步驟：逐一進入用戶管理、編輯、基本資料，記錄開關及勾選狀態。
    預期結果：九個代理均有開關；會員無代理授權欄位，與差分生效狀態分開。
    佐證方式：inventory.json及Allure附件；代理未開啟只記錄，不自動更改。
    """
    with allure.step('公司逐一查看一至九級及會員的授權欄位'):
        actual = auth_guard.snapshot()
        auth_guard.run.dump('inventory.json', actual)
        allure.attach(json.dumps(actual, ensure_ascii=False), '各帳號實際授權；null代表無欄位', allure.attachment_type.JSON)
    with allure.step('核對代理有開關，會員不誤列為已關閉'):
        assert all(actual[a] is not None for a in CHAIN_ACCOUNTS[:9])
        assert actual['aaa010'] is None
    recovery_dir = os.environ.get('XZH_AUTH_GUARD_RECOVERY_DIR')
    if recovery_dir:
        previous = Path(recovery_dir)
        old_auth = json.loads((previous / 'baseline.json').read_text(encoding='utf-8'))
        old_gap = json.loads((previous / 'gap-baseline.json').read_text(encoding='utf-8'))
        gap = auth_guard.gap_snapshot('gap-recovery')
        assert actual == old_auth, '前輪授權原值未恢复'
        assert gap == old_gap, '前輪賓果原值未恢复'
        (previous / 'restore-resolved.json').write_text(json.dumps({
            'resolved': True, 'authorization_equal': True, 'gap_equal': True,
            'evidence_run': str(auth_guard.run.dir)}, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.mark.write_action
@pytest.mark.parametrize('index', range(8), ids=CHAIN_ACCOUNTS[:8])
@allure.title('[異常] TC-002：下級仍開啟時取消上級授權應拒絕保存（層索引{index}）')
def test_odds_gap_authorization_reject_enabled_descendants(index, auth_guard):
    """前置條件：公司登入；目標代理及至少一個下級代理授權已開啟。
    測試範圍：一至八級各測一次；帳號權限不分彩種、玩法；九級無下級代理不套此情境。
    操作步驟：讀全鏈原值，取消上級賺取賠率差並保存，擷取提示，重開查看原值。
    預期結果：提示下级已允许赚取赔率差，请先修改下级；不成功保存，所有層原值不變。
    佐證方式：請求回應、提示、重開截圖與前後JSON；finally還原本次目標並重查全鏈。
    """
    account = CHAIN_ACCOUNTS[index]
    with allure.step('讀取目標及整條下級鏈的授權原值'):
        baseline = auth_guard.snapshot()
        auth_guard.run.dump('baseline.json', baseline)
        descendants = [a for a in CHAIN_ACCOUNTS[index + 1:9] if baseline[a] is True]
        if baseline[account] is not True or not descendants:
            pytest.skip('BLOCKED：目標須開啟且至少一個下級代理已開啟；不自動改造前置資料')
        assert auth_guard.read(index) is True
        gap_baseline = auth_guard.gap_snapshot('gap-baseline')
        if index == 0:
            auth_guard.ui_settings_evidence(gap_baseline, 'ui-before')
        recovery_dir = os.environ.get('XZH_AUTH_GUARD_RECOVERY_DIR')
        if recovery_dir:
            previous = Path(recovery_dir)
            old_auth = json.loads((previous / 'baseline.json').read_text(encoding='utf-8'))
            old_gap = json.loads((previous / 'gap-baseline.json').read_text(encoding='utf-8'))
            assert baseline == old_auth, '前輪pending授權快照未恢復，禁止下一次寫入'
            assert gap_baseline == old_gap, '前輪pending賓果快照未恢復，禁止下一次寫入'
            (previous / 'restore-resolved.json').write_text(json.dumps({
                'resolved': True, 'authorization_equal': True, 'gap_equal': True,
                'evidence_run': str(auth_guard.run.dir),
                'note': '新context先唯讀核對全鏈與賓果快照一致；未需還原寫入，原pending保留'
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        assert auth_guard.read(index) is True
    try:
        with allure.step('取消上級授權並保存，保留提示訊息與回應'):
            evidence = auth_guard.save(False, 'attempt')
        with allure.step('重新開啟確認授權仍啟用，核對所有下級未被自動關閉'):
            actual = auth_guard.snapshot()
            auth_guard.run.dump('after-attempt.json', actual)
            auth_guard.read(index)
            auth_guard.settings.earn_odds_gap_label().evaluate("e=>e.setAttribute('data-guard-proof','1')")
            shot = str(Path(auth_guard.run.dir) / 'reopened.png')
            capture_annotated(auth_guard.page, shot,
                marks=[{'selector': '[data-guard-proof="1"]', 'label': f'實際{actual[account]}；預期仍為開啟True'}],
                note=f'Snotra-012／{account}／下級啟用時取消授權須被拒絕')
            allure.attach.file(shot, name='保存後重開：實際與預期', attachment_type=allure.attachment_type.PNG)
            failures = []
            if not evidence['messageMatched']:
                failures.append('沒有指定提示：' + EXPECTED_MESSAGE)
            if any(200 <= r['status'] < 300 for r in evidence['responses']):
                failures.append('授權寫入回應成功，預期拒絕保存')
            if actual != baseline:
                failures.append(f'保存後授權異動：原值{baseline}；實際{actual}')
            gap_after = auth_guard.gap_snapshot('gap-after-attempt')
            if gap_after != gap_baseline:
                failures.append('保存後指定彩種全鏈差分讀值異動，詳見gap快照')
            assert not failures, '\n'.join(failures)
    finally:
        with allure.step('還原本次目標授權並核對全鏈與原值一致'):
            auth_guard.restore(index, baseline)
            gap_final = auth_guard.gap_snapshot('gap-final')
            auth_guard.run.dump('gap-preservation.json', {'groups': len(CHAIN_ACCOUNTS) * len(GUARD_GAMES),
                                                        'games': list(GUARD_GAMES),
                                                        'equal': gap_final == gap_baseline})
            if index == 0:
                auth_guard.ui_settings_evidence(gap_final, 'ui-final')
            assert gap_final == gap_baseline, '最終指定彩種全鏈差分與原值不同；未擅自覆寫'


@pytest.mark.write_action
@allure.title('[邊界] TC-003：九級沒有下級代理授權時可取消並保存')
def test_odds_gap_authorization_leaf_can_disable(auth_guard):
    """前置條件：九級原授權開啟，鏈末會員沒有賺取賠率差開關。
    測試範圍：九級aaa999；屬全部下級代理已關閉條件的零下級邊界。
    操作步驟：讀全鏈，關閉九級保存，重開核對，再還原原值。
    預期結果：沒有下級已允許的錯誤提示，成功保存，只有九級改為關閉。
    佐證方式：baseline／attempt／after-attempt／final及Allure附件。
    """
    with allure.step('確認九級已開啟且會員無代理授權開關'):
        baseline = auth_guard.snapshot()
        auth_guard.run.dump('baseline.json', baseline)
        if baseline['aaa999'] is not True or baseline['aaa010'] is not None:
            pytest.skip('BLOCKED：九級已開啟且會員無開關的前置條件不成立')
        auth_guard.read(8)
    try:
        with allure.step('取消九級授權保存並重新開啟核對'):
            evidence = auth_guard.save(False, 'attempt')
            actual = auth_guard.snapshot()
            auth_guard.run.dump('after-attempt.json', actual)
            expected = dict(baseline, aaa999=False)
            allure.attach(json.dumps({'expected': expected, 'actual': actual}, ensure_ascii=False),
                          '九級保存後全鏈：預期與實際', allure.attachment_type.JSON)
            assert actual == expected, f'預期{expected}；實際{actual}'
            assert not evidence['messageMatched'], '沒有下級代理卻提示先修改下級'
            assert evidence['responses'] and all(200 <= r['status'] < 300 for r in evidence['responses'])
    finally:
        with allure.step('還原九級原授權並重查全鏈'):
            auth_guard.restore(8, baseline)


@pytest.mark.write_action
@allure.title('[回歸] TC-004：由九級往一級逐層取消授權皆可保存且差分設定不變，上級未開啟時九級授權不能開啟')
def test_odds_gap_authorization_all_disabled_and_deep_guard(auth_guard):
    """前置條件：公司登入；一至九級授權原值皆開啟，會員沒有賺取賠率差開關；授權切換只走 UI。
    測試範圍：一至九級代理授權（帳號層權限，不分彩種與玩法）；差分設定保留核對 XZH_AUTH_GUARD_GAMES 指定彩種（預設三彩種）的全鏈設定。
    操作步驟：由九級往一級逐層取消授權並保存；重新開啟一級授權後，進入九級基本資料嘗試開啟授權並保存；最後由一級往九級依序還原並核對。
    預期結果：每層在下級皆已關閉時可成功取消，不出現「下级已允许赚取赔率差，请先修改下级」，差分設定不變；二至八級仍關閉時，九級授權開關不可操作，或保存後重新開啟仍為關閉且其他層不變（2026-09-29 新版文件：開啟須上級先開、不可跳級）；最終授權與差分設定和原值一致。
    佐證方式：positive-results.json、mixed-control.json／png、mixed-result.json、restore-result.json 及 Allure 附件。
    """
    resume_dir = os.environ.get('XZH_AUTH_GUARD_SIDE_RESUME_DIR')
    previous = Path(resume_dir) if resume_dir else None
    current = auth_guard.snapshot()
    baseline = json.loads((previous / 'baseline.json').read_text(encoding='utf-8')) if previous else current
    auth_guard.run.dump('baseline.json', baseline)
    assert all(baseline[a] is True for a in CHAIN_ACCOUNTS[:9]), '此批要求全開原值，禁止猜測還原順序'
    if previous:
        auth_guard.target_ids.update(json.loads((previous / 'ui-target-ids.json').read_text(encoding='utf-8')))
        gap_baseline = json.loads((previous / 'gap-baseline.json').read_text(encoding='utf-8'))
        auth_guard.run.dump('gap-baseline.json', gap_baseline)
    else:
        gap_baseline = auth_guard.gap_snapshot('gap-baseline')

    def stored(snapshot):
        return {a: {g: sorted([(r['playTypeId'], r.get('oddsGap'), r.get('subOddsGap'))
                               for r in rows], key=lambda r: r[0])
                    for g, rows in games.items()} for a, games in snapshot.items()}

    auth_guard.ui_settings_evidence(gap_baseline, 'ui-before')
    expected = dict(baseline)
    results = json.loads((previous / 'positive-results.json').read_text(encoding='utf-8')) if previous else []
    if previous:
        for result in results:
            assert result['passed'], '只允許從已核對成功的批次安全續接'
            expected[result['account']] = False
        auth_guard.run.dump('resume-authorization.json', current)
        assert current == expected, '續接授權不是本輪已知狀態；停止，不覆寫'
        gap_current = auth_guard.gap_snapshot('gap-resume')
        assert stored(gap_current) == stored(gap_baseline), '續接儲存設定與原值不同；停止，不覆寫'
        auth_guard.run.dump('resume-verified.json', {'authorization_equal': True, 'stored_settings_equal': True,
                                                  'source': str(previous), 'completed': len(results)})
    try:
        for index in reversed(range(9)):
            account = CHAIN_ACCOUNTS[index]
            if any(r['account'] == account for r in results):
                continue
            with allure.step(f'{account}：所有下級關閉或無代理下級時取消授權'):
                assert auth_guard.read(index) is True
                evidence = auth_guard.save(False, f'disable-{account}')
                expected[account] = False
                if os.environ.get('XZH_AUTH_GUARD_SIDE_FAST_PREP') == '1' and index > 0:
                    assert auth_guard.read(index) is False, f'{account}必要前置取消未生效'
                    assert evidence['responses'] and all(r['status'] == 204 for r in evidence['responses'])
                    auth_guard.run.log({'phase': 'verified-precondition-only', 'account': account,
                                        'note': '既有8項已通過，這次僅為未完一級及混合情境建立前置'})
                    continue
                actual = auth_guard.snapshot()
                auth_guard.run.dump(f'after-disable-{account}.json', actual)
                gap = auth_guard.gap_snapshot(f'gap-after-disable-{account}')
                passed = actual == expected and stored(gap) == stored(gap_baseline)
                passed = passed and not evidence['messageMatched']
                passed = passed and bool(evidence['responses']) and all(200 <= r['status'] < 300 for r in evidence['responses'])
                results.append({'account': account, 'passed': passed,
                                'authorization_equal': actual == expected,
                                'stored_settings_equal': stored(gap) == stored(gap_baseline)})
                auth_guard.run.dump('positive-results.json', results)
                assert passed, f'{account}無下級開啟卻未成功撤銷，或其他授權／賓果儲存設定異動'
        # 2026-09-29 新版文件：開啟須上級先開、不可跳級，「直屬關閉、深層開啟」在規格上不存在。
        # 做不出這個狀態即符合規格（PASS）；二至八級關閉時九級仍能開啟才是缺陷（FAIL）。不以 API 強造。
        with allure.step('二至八級關閉時嘗試開啟九級授權，確認不能跳級開啟'):
            auth_guard.read(0)
            auth_guard.save(True, 'mixed-enable-aaa111')
            expected['aaa111'] = True
            assert auth_guard.snapshot() == expected
            auth_guard.read(8)
            checkbox = auth_guard.settings.earn_odds_gap_checkbox()
            count = checkbox.count()
            control = {'account': 'aaa999', 'page_url': auth_guard.page.url, 'checkbox_count': count,
                       'is_enabled': checkbox.is_enabled() if count else None,
                       'disabled_attribute': checkbox.get_attribute('disabled') if count else None,
                       'aria_disabled': checkbox.get_attribute('aria-disabled') if count else None,
                       'body_text': auth_guard.page.locator('body').inner_text()}
            auth_guard.run.dump('mixed-control.json', control)
            marks = [{'selector': 'body', 'label': f'aaa999基本資料；授權checkbox數={count}；enabled={control["is_enabled"]}；預期不能開啟'}]
            if count:
                auth_guard.settings.earn_odds_gap_label().evaluate("e=>e.setAttribute('data-mixed-control','1')")
                marks = [{'selector': '[data-mixed-control="1"]', 'label': f'九級授權：enabled={control["is_enabled"]}；disabled={control["disabled_attribute"]}；預期不能開啟'}]
            capture_annotated(auth_guard.page, str(Path(auth_guard.run.dir) / 'mixed-control.png'),
                              marks=marks, note='跳級開啟檢查：一級已開啟、二至八級關閉，九級授權應不能開啟')
            if not count or not checkbox.is_enabled():
                mixed = {'status': 'PASS', 'reason': '上級未開啟時九級授權開關不可操作，符合逐層開啟',
                         'expected': dict(expected), 'control': control}
            else:
                evidence = auth_guard.save(True, 'mixed-enable-aaa999')
                actual = auth_guard.snapshot()
                auth_guard.run.dump('mixed-after-enable.json', actual)
                passed = actual == expected
                mixed = {'status': 'PASS' if passed else 'FAIL',
                         'reason': ('保存後重新開啟九級仍為關閉且其他層不變，符合逐層開啟' if passed
                                    else '二至八級關閉時九級仍被開啟，或其他層授權被異動'),
                         'expected': dict(expected), 'actual': actual, 'evidence': evidence}
                if actual['aaa999'] is True:
                    expected['aaa999'] = True
            auth_guard.run.dump('mixed-result.json', mixed)
            allure.attach(json.dumps(mixed, ensure_ascii=False, default=str),
                          '跳級開啟檢查：預期與實際', allure.attachment_type.JSON)
            assert mixed['status'] == 'PASS', f"{mixed['reason']}：預期{mixed['expected']}；實際{mixed.get('actual')}"
    finally:
        with allure.step('依起始全開快照，由一級到九級還原授權並核對賓果儲存設定'):
            for index, account in enumerate(CHAIN_ACCOUNTS[:9]):
                if auth_guard.read(index) is not True:
                    auth_guard.save(True, f'restore-{account}')
                    assert auth_guard.read(index) is True, f'{account}授權未恢復'
            final = auth_guard.snapshot()
            gap_final = auth_guard.gap_snapshot('gap-final')
            auth_guard.run.dump('final.json', final)
            restored = final == baseline and gap_final == gap_baseline
            auth_guard.run.dump('restore-result.json', {'restored': restored,
                                                      'authorization_equal': final == baseline,
                                                      'full_settings_equal': gap_final == gap_baseline,
                                                      'stored_settings_equal': stored(gap_final) == stored(gap_baseline)})
            assert restored, '相鄰情境最終授權或賓果儲存設定未恢復，停止後續操作'
            auth_guard.ui_settings_evidence(gap_final, 'ui-final')


def _member_gap_view(guard, game):
    """公司開啟會員 aaa010 的赔率差分頁，回傳各列畫面文字與輸入值，並取同一目標的 API 生效狀態。"""
    settings = guard.settings
    count = len(guard.observed['target_user_ids'])
    settings.open_target(AgentHierarchyPage.LEVELS[9], CHAIN_ACCOUNTS[9])
    settings.select_game(game)
    guard.page.wait_for_timeout(800)
    texts = settings._rows().evaluate_all("rs => rs.map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
    rows = settings.read_rows()
    assert len(guard.observed['target_user_ids']) > count, '缺少會員 aaa010 的畫面目標識別證據'
    client = OddsGapClient.from_page(guard.page, guard.observed)
    api = client.gap_setting(guard.observed['target_user_ids'][-1], game)
    return {'rows': rows, 'texts': texts,
            'api': [{'play': r.get('playTypeName'), 'isEffective': r.get('isEffective')} for r in api]}


@pytest.mark.write_action
@allure.title('[畫面驗證] TC-005：九级代理取消「赚取赔率差」後，會員赔率差分頁是否保留原值並標示「目前未生效」')
def test_odds_gap_setting_page_marks_dormant_rows(auth_guard):
    """前置條件：公司登入；九級 aaa999「赚取赔率差」原值開啟；會員 aaa010 可由公司開啟赔率差分頁。
    測試範圍：會員 aaa010 在 XZH_AUTH_GUARD_GAMES 指定彩種（預設英国天天彩、香港六合彩、宾果六合彩）的全部設定列；其差分受益層為九級 aaa999。
    操作步驟：記錄 aaa010 各彩種畫面值；取消 aaa999「赚取赔率差」並保存；重開 aaa010 赔率差分逐彩種核對；最後恢復 aaa999 並重查全鏈授權。
    預期結果：aaa010 各列仍顯示原值；各列 API 生效狀態為否；各列標示「目前未生效」（2026-09-29 新版文件：設定頁顯示不套生效閘門，避免關閉後設定值看起來消失，但列標「目前未生效」提示）。
    佐證方式：取消前後各彩種列文字、輸入值、API 生效狀態、截圖與還原紀錄。
    """
    with allure.step('讀取全鏈授權原值，確認九級已開啟'):
        baseline = auth_guard.snapshot()
        auth_guard.run.dump('baseline.json', baseline)
        if baseline['aaa999'] is not True:
            pytest.skip('BLOCKED：九級原授權須為開啟；不自動改造前置資料')
    before, after, failures = {}, {}, []
    try:
        with allure.step('公司開啟會員赔率差分頁，逐彩種記錄取消授權前的畫面值'):
            for game in GUARD_GAMES:
                before[game] = _member_gap_view(auth_guard, game)
        with allure.step('取消九級「赚取赔率差」並保存，重開確認已關閉'):
            auth_guard.read(8)
            auth_guard.save(False, 'disable-aaa999')
            assert auth_guard.read(8) is False, '九級授權未關閉，無法觀察未生效標示'
        with allure.step('重開會員赔率差分頁，逐彩種核對原值保留、生效狀態與「目前未生效」標示'):
            for game in GUARD_GAMES:
                after[game] = view = _member_gap_view(auth_guard, game)
                name = GUARD_GAMES[game]
                if [r['inputs'] for r in view['rows']] != [r['inputs'] for r in before[game]['rows']]:
                    failures.append(f'{name}：取消授權後畫面差分值與取消前不同')
                if any(r['isEffective'] for r in view['api']):
                    failures.append(f'{name}：取消授權後仍有列生效（API）')
                missing = [t.split(' ')[0] for t in view['texts'] if '未生效' not in t]
                if missing:
                    failures.append(f'{name}：{len(missing)}／{len(view["texts"])} 列沒有「目前未生效」標示（例：{"、".join(missing[:3])}）')
            shot = str(Path(auth_guard.run.dir) / 'dormant-rows.png')
            auth_guard.page.mouse.move(5, 5)
            auth_guard.page.locator('table:visible').first.evaluate("e => e.setAttribute('data-dormant-table', '1')")
            capture_annotated(auth_guard.page, shot, marks=[{'selector': '[data-dormant-table="1"]', 'label': '九級取消授權後的會員差分列；預期各列標示「目前未生效」'}],
                              note='TC-005／aaa999 取消「赚取赔率差」後的 aaa010 赔率差分頁')
            allure.attach.file(shot, name='取消授權後會員赔率差分頁', attachment_type=allure.attachment_type.PNG)
    finally:
        auth_guard.run.dump('dormant-view.json', {'before': before, 'after': after})
        allure.attach(json.dumps({'before': before, 'after': after}, ensure_ascii=False),
                      '取消授權前後：列文字、輸入值與 API 生效狀態', allure.attachment_type.JSON)
        with allure.step('恢復九級原授權並重查全鏈'):
            auth_guard.restore(8, baseline)
    assert not failures, '判準（attach 佐證）\n驗證失敗：\n- ' + '\n- '.join(failures)


@pytest.mark.write_action
@pytest.mark.skipif(not os.environ.get('XZH_AUTH_GUARD_SIDE_RESUME_DIR'),
                    reason='僅於明確指定本輪中斷快照時執行專用還原，不屬日常回歸')
@allure.title('[還原] 專門恢復本輪全鏈授權並核對賓果原值')
def test_odds_gap_authorization_recover_owned_chain(auth_guard):
    previous = Path(os.environ['XZH_AUTH_GUARD_SIDE_RESUME_DIR'])
    baseline = json.loads((previous / 'baseline.json').read_text(encoding='utf-8'))
    gap_baseline = json.loads((previous / 'gap-baseline.json').read_text(encoding='utf-8'))
    auth_guard.target_ids.update(json.loads((previous / 'ui-target-ids.json').read_text(encoding='utf-8')))
    current = auth_guard.snapshot()
    auth_guard.run.dump('before-recovery.json', current)
    assert all(current[a] is False for a in CHAIN_ACCOUNTS[:9]), '只恢復本輪已核對的全關狀態'
    gap_current = auth_guard.gap_snapshot('gap-before-recovery')
    def stored(snapshot):
        return {a: {g: [(r['playTypeId'], r.get('oddsGap'), r.get('subOddsGap')) for r in rows]
                    for g, rows in games.items()} for a, games in snapshot.items()}
    assert stored(gap_current) == stored(gap_baseline), '非本輪授權設定異動，停止覆寫'
    results = []
    for index, account in enumerate(CHAIN_ACCOUNTS[:9]):
        error = None
        for attempt in range(2):
            try:
                if auth_guard.read(index) is not True:
                    auth_guard.save(True, f'recovery-{account}-{attempt}')
                assert auth_guard.read(index) is True
                error = None
                break
            except Exception as exc:
                error = str(exc)
                auth_guard.page.reload(wait_until='domcontentloaded')
        results.append({'account': account, 'restored': error is None, 'error': error})
        auth_guard.run.dump('recovery-progress.json', results)
    final = auth_guard.snapshot()
    gap_final = auth_guard.gap_snapshot('gap-final')
    auth_guard.run.dump('final.json', final)
    resolved = final == baseline and gap_final == gap_baseline
    result = {'resolved': resolved, 'authorization_equal': final == baseline,
              'gap_equal': gap_final == gap_baseline, 'evidence_run': str(auth_guard.run.dir)}
    auth_guard.run.dump('restore-result.json', result)
    (previous / 'restore-resolved.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    assert resolved, '仍有未恢復項，詳見recovery-progress與final'
