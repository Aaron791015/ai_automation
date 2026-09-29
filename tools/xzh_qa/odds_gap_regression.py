"""賓果基本投注回歸的共用計畫、送出守衛與 UI 流程。

使用 tests/xzh/test_odds_gap_betting_regression.py；計畫與批准必須指定同一批次。
不依賴 scratchpad、不重送既有批次；所有設定與投注均走既有 POM。
"""
from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import ROUND_CEILING
from pathlib import Path
import json
import math
import re
import time

import allure

from xzh_qa.config_loader import qat, player_credentials
from xzh_qa.odds_gap_client import ReadOnlyApiError
from xzh_qa.odds_gap_oracle import dec, player_odds
from xzh_qa.odds_gap_safety import guarded_gaps, guarded_authorization, strict_gap_values
from xzh_qa.pages.player_bet_page import PlayerBetPage

GAME = 'bingo6'
KINDS = ('branches', 'ab', 'authorization', 'minimum', 'sub-unset')
FROZEN_KEYS = ('serialNumber', 'gameId', 'issueNumber', 'playTypeId', 'panelId',
               'selection', 'betTime', 'betAmount', 'odds', 'rebate')
# category／UI index／playTypeId／selection／差分欄／副標籤。
OPTIONS = {
    'tail-main': ('尾数中', 1, 'tailNumberHit', '1', 'oddsGap', '0尾'),
    'tail-sub': ('尾数中', 0, 'tailNumberHit', '0', 'subOddsGap', '0尾'),
    'zodiac-main': ('生肖中', 0, 'zodiacHit', 'rat', 'oddsGap', '马'),
    'zodiac-sub': ('生肖中', 6, 'zodiacHit', 'horse', 'subOddsGap', '马'),
    'zodiac-miss-main': ('生肖不中', 0, 'zodiacMiss', 'rat', 'oddsGap', '马'),
    'zodiac-miss-sub': ('生肖不中', 6, 'zodiacMiss', 'horse', 'subOddsGap', '马'),
    'tail-miss-main': ('尾数不中', 1, 'tailNumberMiss', '1', 'oddsGap', '0尾'),
    'tail-miss-sub': ('尾数不中', 0, 'tailNumberMiss', '0', 'subOddsGap', '0尾'),
    'special-main': ('特肖', 0, 'bonusNumberZodiac', 'rat', 'oddsGap', '马'),
    'special-sub': ('特肖', 6, 'bonusNumberZodiac', 'horse', 'subOddsGap', '马'),
    # 特肖主分支其餘生肖（依畫面順序；「马」為副標籤不列入）。代碼若與前台不符，送出守衛會在送出前攔下。
    'special-main-ox': ('特肖', 1, 'bonusNumberZodiac', 'ox', 'oddsGap', '马'),
    'special-main-tiger': ('特肖', 2, 'bonusNumberZodiac', 'tiger', 'oddsGap', '马'),
    'special-main-rabbit': ('特肖', 3, 'bonusNumberZodiac', 'rabbit', 'oddsGap', '马'),
    'special-main-dragon': ('特肖', 4, 'bonusNumberZodiac', 'dragon', 'oddsGap', '马'),
    'special-main-snake': ('特肖', 5, 'bonusNumberZodiac', 'snake', 'oddsGap', '马'),
    'special-main-goat': ('特肖', 7, 'bonusNumberZodiac', 'goat', 'oddsGap', '马'),
    'special-main-monkey': ('特肖', 8, 'bonusNumberZodiac', 'monkey', 'oddsGap', '马'),
    'special-main-rooster': ('特肖', 9, 'bonusNumberZodiac', 'rooster', 'oddsGap', '马'),
    'special-main-dog': ('特肖', 10, 'bonusNumberZodiac', 'dog', 'oddsGap', '马'),
    'special-main-pig': ('特肖', 11, 'bonusNumberZodiac', 'pig', 'oddsGap', '马'),
    'element-main': ('五行', 0, 'fiveElements', 'metal', 'oddsGap', '土'),
    'element-sub': ('五行', 4, 'fiveElements', 'earth', 'subOddsGap', '土'),
    'red': ('色波', 18, 'colorRed', '7-red', 'oddsGap', None),
    'blue': ('色波', 19, 'colorBlue', '7-blue', 'oddsGap', None),
    'green': ('色波', 20, 'colorGreen', '7-green', 'oddsGap', None),
}


def validate_plan(plan):
    """計畫只描述已實作的基本情境；未知欄位/分支不可默認執行。"""
    assert plan.get('kind') in KINDS, '未知回歸情境'
    assert plan.get('game') == GAME and plan.get('panel') == 'a', '目前正式入口限賓果A盤'
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', plan.get('batch_id', '')), '非法批次ID'
    options = plan.get('options', [])
    assert options and len(options) == len(set(options)) and all(x in OPTIONS for x in options), '選項缺失或重複'
    if plan['kind'] in ('authorization', 'minimum'):
        assert options == ['tail-main'], '授權及最低值先限尾數中1尾代表'
    if plan['kind'] == 'sub-unset':
        # 2026-09-29 新版文件：副差分未設即為 0、不退回主差分；須同一玩法主副各一注才能對照
        fields = sorted(OPTIONS[x][4] for x in options)
        assert len(options) == 2 and fields == ['oddsGap', 'subOddsGap'], '副差分未設情境須主副各一個選項'
        assert len({OPTIONS[x][2] for x in options}) == 1, '主副對照須為同一玩法'
    amount = dec(plan.get('amount'))
    assert amount.is_finite() and amount > 0, '金額必須為正有限值'
    rounds = plan_rounds(plan)
    count = len(options) * len(phases(plan)) * rounds
    assert type(plan.get('max_bets')) is int and plan['max_bets'] == count, '批准注數須等於本計畫'
    assert dec(plan.get('max_total')) == amount * count, '批准總額須等於本計畫'
    return plan


def plan_rounds(plan):
    """同一份差分設定下連續下注的期數；預設 1（原行為）。

    rounds > 1 時，已有自然中獎樣本的（階段, 選項）在後續期數跳過，
    實際送出注數可少於批准上限 max_bets，但不得超過。
    """
    rounds = plan.get('rounds', 1)
    assert type(rounds) is int and 1 <= rounds <= 50, '期數須為 1～50 的整數'
    return rounds


def already_won(attempts, rows, phase, option):
    """同階段同選項的既有注單中，是否已有自然結算為中獎者（只讀帳本與報表明細）。"""
    serials = {str(a['serialNumber']) for a in attempts
               if a.get('phase') == phase and a.get('option') == option and 'serialNumber' in a}
    return any(str(r['serialNumber']) in serials and r.get('outcome') == 'won' for r in rows)


def phases(plan):
    return {'branches': ('A',), 'ab': ('A', 'B'),
            'authorization': ('on', 'off', 'restored'), 'minimum': ('above', 'floor'),
            'sub-unset': ('A',)}[plan['kind']]


class BatchLedger:
    """原子佔用批次檔；送出前持久化，因此崩潰後也不能整批重送。"""
    def __init__(self, path, plan):
        validate_plan(plan)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {'schema': 1, 'plan': plan, 'day': datetime.now().astimezone().date().isoformat(),
                     'started': datetime.now().astimezone().isoformat(), 'attempts': [], 'restored': False}
        with self.path.open('x', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def save(self):
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        temp.replace(self.path)

    def sent(self, attempt, payload, source, expected, gaps, minimum):
        assert not attempt.get('sent'), '同一注不可重送'
        sent = [x for x in self.data['attempts'] if x.get('sent')]
        plan = self.data['plan']
        assert len(sent) < plan['max_bets'], '超過本批注數'
        assert sum((dec(x['amount']) for x in sent), dec(0)) + dec(attempt['amount']) <= dec(plan['max_total'])
        attempt.update(sent=True, payload=payload, source=source, expected_odds=str(expected),
                       gaps=list(map(str, gaps)), minimum=str(minimum), sent_at=datetime.now().astimezone().isoformat())
        self.save()


def remaining_seconds(issue):
    return (datetime.fromisoformat(issue['closeTime']) - datetime.now(timezone.utc)).total_seconds()


def client_quote_matches(actual, expected):
    """只容許前端二進位浮點運算尾差；正式凍結賠率仍精確比對。

    QAT連肖原始請求：4.8109 - 0.1送為4.7109000000000005。
    以期望值的兩個浮點間距為界，並封頂1e-12；不是四位取位或派彩規格。
    """
    actual, expected = dec(actual), dec(expected)
    if not actual.is_finite() or not expected.is_finite():
        return False
    if actual == expected:
        return True
    binary = float(expected)
    if not math.isfinite(binary):
        return False
    tolerance = min(dec('1e-12'), dec(str(math.ulp(binary))) * 2)
    return abs(actual - expected) <= tolerance


def price_request(plan, attempt, payload, snapshot, issue, gaps, pricing):
    """只讀獨立公司定價、當期差分快照與最低值；不拿 clientOdds 當期望。"""
    assert issue['status'] == 'open' and issue['isBettable'] and remaining_seconds(issue) >= 10, '封盤或剩餘時間不足'
    assert payload['gameId'] == plan['game'] and payload['panelId'] == plan['panel']
    assert str(payload['issueNumber']) == str(issue['issueNumber']) == str(snapshot['issueNumber'])
    assert snapshot['gameId'] == plan['game']
    assert len(payload['items']) == 1
    item = payload['items'][0]
    _, _, play, selection, field, _ = OPTIONS[attempt['option']]
    assert item['playTypeId'] == play and item['selection'] == selection
    assert dec(item['betAmount']) == dec(plan['amount'])
    row = next(r for r in snapshot['playTypes'] if r['playTypeId'] == play)
    override = next((r for r in row.get('selectionOverrides', []) if r['selection'] == selection), None)
    base = dec(override['odds'] if override else row['baseOdds'])
    minimum = pricing['subMinOdds'] if field == 'subOddsGap' and pricing.get('subMinOdds') is not None else pricing['minOdds']
    snapshot_min = row.get('subMinOdds') if field == 'subOddsGap' else row['minOdds']
    if snapshot_min is None:
        snapshot_min = row['minOdds']
    assert dec(snapshot_min) == dec(minimum), '當期最低值異動'
    if plan['kind'] == 'minimum':
        raw = base + sum(map(dec, gaps), dec(0))
        assert (raw > dec(minimum)) if attempt['phase'] == 'above' else (raw < dec(minimum)), '最低賠率樣本無鑑別力'
    else:
        assert base + sum(map(dec, gaps), dec(0)) > dec(minimum), '基本主副／授權樣本已觸底，無法區分差分效果'
    expected = player_odds(base, gaps, minimum)
    assert client_quote_matches(item['clientOdds'], expected), '送出賠率與獨立公式不符'
    return row, expected, minimum


def read_bets(client, uid, day, states=('settled', 'unsettled')):
    """保留所有明細；只在指定序號核對時判斷唯一，不覆寫重複序號。"""
    rows = []
    for state in states:
        page, total, collected = 1, None, []
        while True:
            data = client._get(f'/api/Reports/Shares/Members/{uid}/Bets', {
                'gameIds': GAME, 'date': day, 'settlementState': state, 'pageIndex': page, 'pageSize': 100})
            if total is None:
                total = data['totalCount']
            assert total == data['totalCount'], '分頁期間總數改變，停止本次讀取'
            collected.extend(data['items'])
            if page >= data['pageCount']:
                break
            page += 1
        assert len(collected) == total, '未讀齊注單'
        rows.extend(collected)
    return rows


def select_unique(rows, serial):
    selected = [r for r in rows if str(r['serialNumber']) == str(serial)]
    assert len(selected) == 1, f'注單{serial}缺失或序號重複'
    return selected[0]


def frozen_checks(attempts, rows):
    checks = []
    for a in attempts:
        if 'serialNumber' not in a:
            continue
        actual = select_unique(rows, a['serialNumber'])
        expected = {k: a['initial_record'][k] for k in FROZEN_KEYS}
        result = {k: actual[k] for k in FROZEN_KEYS}
        checks.append({'serialNumber': a['serialNumber'], 'expected': expected, 'actual': result, 'ok': expected == result})
    assert all(r['ok'] for r in checks), '舊注凍結欄異動'
    return checks


def reports(client, accounts, day, plays):
    return {f'{n+1}-{play}': client._get('/api/Reports/Selections', {
        'gameId': GAME, 'dateFrom': day, 'dateTo': day, 'settlementState': 'settled',
        'playTypeId': play, 'parentId': a['id'], 'companyView': 'false'})
        for n, a in enumerate(accounts[:9]) for play in sorted(plays)}


def run_batch(browser, gap_context, run, ledger):
    """一批 UI 投注與還原；自然結算由另外的唯讀 pytest 接續。"""
    data, plan = ledger.data, ledger.data['plan']
    contexts = [gap_context(i, via='company') for i in range(10)]
    originals = [c.open(GAME) for c in contexts]
    member, parent = contexts[9], contexts[8]
    client = member.reference_client
    accounts = [{'account': c.account, 'id': c.target_user_id} for c in contexts]
    pricing = client.odds_setting(GAME)
    cap, independent = client.cap_rate()
    assert independent, '缺實際平台上限來源'
    fields = {(OPTIONS[o][2], OPTIONS[o][4]) for o in plan['options']}
    for option in plan['options']:
        _, _, play, _, field, label = OPTIONS[option]
        if label is not None:
            assert pricing[play]['subOddsLabel'] == label, '主副標籤已變，需重新核對計畫'
        for rows in originals:
            row = next(r for r in rows if r['playTypeId'] == play)
            assert row[field] is not None and row['isEffective'], '差分欄未生效或不存在'
        if plan['kind'] not in ('minimum',):
            low = pricing[play].get('subMinOdds') if field == 'subOddsGap' else pricing[play]['minOdds']
            if low is None:
                low = pricing[play]['minOdds']
            base = pricing[play]['subOdds'] if field == 'subOddsGap' else pricing[play]['odds']
            assert (dec(base) - dec(low)) * cap >= dec('.20'), '代表差分額度不足'
    data.update(accounts=accounts, originals=originals, pricing=pricing, cap=str(cap),
                before_reports=reports(client, accounts, data['day'], {OPTIONS[o][2] for o in plan['options']}))
    ledger.save()
    with browser.new_context(viewport={'width': 1920, 'height': 1080}) as front:
        page = front.new_page()
        page.set_default_timeout(20000)
        player = PlayerBetPage(page)
        snapshots, issues, headers = [], [], {}
        active, current_gaps = {}, []

        def observe(response):
            req = response.request
            if '/api/Bets' in response.url and req.method == 'POST':
                active.update(status=response.status, response=response.text())
                ledger.save()
            elif req.method == 'GET' and ('/Odds/Snapshot' in response.url or '/Issues/Current' in response.url):
                if req.headers.get('authorization'):
                    headers.update({'Authorization': req.headers['authorization']})
                if response.ok:
                    body = response.json()
                    if '/Odds/Snapshot' in response.url:
                        snapshots.append(body)
                    else:
                        issues.extend(r for r in body if r['gameId'] == GAME)

        def check_issue(after=None, timeout=0):
            """確認當期可下注；timeout>0 時輪詢等待（多期批次用），after 指定須換到新期號。"""
            from xzh_qa.odds_gap_client import OddsGapClient
            assert headers, '未取得前台讀取憑證'
            deadline = time.monotonic() + timeout
            while True:
                current = OddsGapClient.from_page(page, {'headers': headers})._get('/api/Issues/Current')
                issue = next(r for r in current if r['gameId'] == GAME)
                ready = issue['status'] == 'open' and issue['isBettable'] and remaining_seconds(issue) >= 30
                if ready and (after is None or str(issue['issueNumber']) != str(after)):
                    issues.append(issue)
                    return issue
                assert time.monotonic() < deadline, '未開盤或窗口不足，不等待'
                page.wait_for_timeout(5000)

        def bets_now():
            """長批次的公司唯讀憑證會逾時：401／403 時重新登入同一身分再讀一次。"""
            try:
                return read_bets(client, member.target_user_id, data['day'])
            except ReadOnlyApiError as exc:
                if exc.status not in (401, 403):
                    raise
                member.recover()
                client.headers = dict(member.observed['headers'])
                return read_bets(client, member.target_user_id, data['day'])

        def guard(route):
            if '/api/Bets' not in route.request.url or route.request.method != 'POST':
                route.continue_()
                return
            try:
                assert active and not active.get('sent'), '不允許未計畫或重複送出'
                payload = route.request.post_data_json
                source = next(s for s in reversed(snapshots) if s['gameId'] == GAME and str(s['issueNumber']) == str(payload['issueNumber']))
                play = OPTIONS[active['option']][2]
                row, expected, minimum = price_request(plan, active, payload, source, issues[-1], current_gaps, pricing[play])
                ledger.sent(active, payload, row, expected, current_gaps, minimum)
            except Exception as exc:
                active['blocked'] = str(exc)
                ledger.save()
                route.abort()
                return
            route.continue_()

        front.route('**/*', guard)
        page.on('response', observe)
        player.login(qat()['frontend_url'], *player_credentials())
        player.select_game('宾果六合彩')
        check_issue(timeout=360 if plan_rounds(plan) > 1 else 0)
        try:
            with ExitStack() as stack:
                transactions = [stack.enter_context(guarded_gaps(c, GAME, rows)) for c, rows in zip(contexts, originals)]
                auth = stack.enter_context(guarded_authorization(parent)) if plan['kind'] == 'authorization' else None
                if auth is not None:
                    assert auth['original'] is True, '九級初始授權須開啟'
                for phase in phases(plan):
                    with allure.step('依本批主副欄及階段寫入差分，保存後逐欄讀回'):
                        for c, transaction in zip(contexts, transactions):
                            # 授權關閉後會員設定可能唯讀；後兩階段只切授權，保留同一份差分。
                            if plan['kind'] == 'authorization' and phase != 'on':
                                continue
                            rows = c.open(GAME)
                            indexes = {r['playTypeId']: n for n, r in enumerate(rows)}
                            for play, field in fields:
                                if plan['kind'] == 'minimum':
                                    distance = dec(pricing[play]['odds']) - dec(pricing[play]['minOdds'])
                                    assert distance > dec('.001')
                                    value = -dec('.0001') if phase == 'above' else -(distance / 10 + dec('.01')).quantize(dec('.0001'), rounding=ROUND_CEILING)
                                elif plan['kind'] == 'sub-unset':
                                    # 只設主差分；副差分維持 0（未設），驗證副層成交的注單不改扣主差分
                                    value = dec(0) if field == 'subOddsGap' else -dec('.01')
                                else:
                                    value = -dec('.02' if ((phase != 'B') == (field == 'subOddsGap')) else '.01')
                                entered = c.setting.set_value(indexes[play], int(field == 'subOddsGap'), value)
                                assert entered == value
                                transaction['expected'][(play, field)] = entered
                            transaction['attempted'] = True
                            assert c.setting.save()['status'] in (200, 204)
                            actual = strict_gap_values(c.api_rows(GAME))
                            assert all(actual[k] == v for k, v in transaction['expected'].items())
                    if auth is not None:
                        enabled = phase != 'off'
                        parent.setting.open_target(parent.level_name, parent.account, require_gap=False)
                        auth.update(attempted=True, expected=enabled)
                        assert parent.setting.set_earn_odds_gap(enabled)['status'] in (200, 204)
                        parent.setting.open_target(parent.level_name, parent.account, require_gap=False)
                        assert parent.setting.is_earn_odds_gap_checked() is enabled
                        auth['last_verified'] = enabled
                    phase_rows = [c.api_rows(GAME) for c in contexts]
                    data.setdefault('phase_rows', {})[phase] = phase_rows
                    assert all(client.odds_setting(GAME)[play] == pricing[play] for play, _ in fields), '基準／最低值異動'
                    ledger.save()
                    last_issue = None
                    for round_no in range(plan_rounds(plan)):
                        if round_no:
                            if not sent_this_round:
                                break  # 上一輪全部選項都已有中獎樣本
                            # 下一輪須換到新期號，才是獨立的開獎樣本
                            check_issue(after=last_issue, timeout=360)
                        sent_this_round = 0
                        for option in plan['options']:
                            category, index, play, selection, field, _ = OPTIONS[option]
                            rows = [next(r for r in rs if r['playTypeId'] == play) for rs in phase_rows]
                            for n, row in enumerate(rows):
                                should_apply = not (plan['kind'] == 'authorization' and phase == 'off' and n == 9)
                                assert row['isEffective'] is should_apply, '差分生效狀態與本批授權前置不符'
                                assert dec(row[field]) == transactions[n]['expected'][(play, field)], '階段差分讀回異動'
                            current_gaps = [dec(r[field]) if r['isEffective'] else dec(0) for r in rows]
                            if auth is not None:
                                assert rows[9]['isEffective'] is (phase != 'off')
                            before_bets = bets_now()
                            data.setdefault('checks', []).append(frozen_checks(data['attempts'], before_bets))
                            if plan_rounds(plan) > 1 and already_won(data['attempts'], before_bets, phase, option):
                                data.setdefault('skipped', []).append(
                                    {'phase': phase, 'round': round_no, 'option': option, 'reason': '已有中獎樣本'})
                                ledger.save()
                                continue
                            check_issue(timeout=360 if plan_rounds(plan) > 1 else 0)
                            snapshots.clear()
                            page.reload()
                            if '/auth/' in page.url:
                                player.login(qat()['frontend_url'], *player_credentials())
                            player.select_game('宾果六合彩')
                            check_issue()
                            active = {'phase': phase, 'option': option, 'play': play, 'selection': selection,
                                      'field': field, 'amount': plan['amount'], 'sent': False}
                            data['attempts'].append(active)
                            ledger.save()
                            with allure.step('UI送出計畫中的單一選項並核對正式序號、賠率與金額'):
                                player.place_standard_category_bet(category, amount=str(plan['amount']), option_index=index)
                            assert active.get('status') in (200, 201), '回應非成功或不明，禁止重送'
                            after_bets = bets_now()
                            before_ids = {str(r['serialNumber']) for r in before_bets}
                            new = [r for r in after_bets if str(r['serialNumber']) not in before_ids]
                            assert len(new) == 1, '新注不能唯一對應，不繼續'
                            record = new[0]
                            assert record['gameId'] == GAME and record['panelId'] == 'a' and record['playTypeId'] == play and record['selection'] == selection
                            assert str(record['issueNumber']) == str(active['payload']['issueNumber'])
                            assert dec(record['odds']) == dec(active['expected_odds']) and dec(record['betAmount']) == dec(plan['amount'])
                            active.update(serialNumber=str(record['serialNumber']), initial_record=record)
                            last_issue = record['issueNumber']
                            sent_this_round += 1
                            ledger.save()
        finally:
            try:
                try:
                    final = [c.api_rows(GAME) for c in contexts]
                    bets = read_bets(client, member.target_user_id, data['day'])
                except ReadOnlyApiError as exc:
                    if exc.status not in (401, 403):
                        raise
                    member.recover()
                    client.headers = dict(member.observed['headers'])
                    final = [client.gap_setting(c.target_user_id, GAME) for c in contexts]
                    bets = read_bets(client, member.target_user_id, data['day'])
                data.update(final=final, restored=all(strict_gap_values(a) == strict_gap_values(b) for a, b in zip(final, originals)),
                            final_frozen=frozen_checks(data['attempts'], bets), finished=datetime.now().astimezone().isoformat())
            except BaseException as exc:
                data['final_error'] = str(exc)
                raise
            finally:
                ledger.save()
                run.dump('regression-result.json', data)
                allure.attach(json.dumps(data, ensure_ascii=False, default=str), '本批計畫／實際／還原', allure.attachment_type.JSON)
    placed = [a for a in data['attempts'] if 'serialNumber' in a]
    assert data['restored'] and all('serialNumber' in a for a in data['attempts'] if a.get('sent'))
    if plan_rounds(plan) == 1:
        assert len(placed) == plan['max_bets']
    else:
        assert 0 < len(placed) <= plan['max_bets']
