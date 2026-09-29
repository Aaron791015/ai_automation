"""Snotra-005／011：分頁入口與15項副欄名稱的唯讀回歸。"""
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import allure

from qa_common.shot import capture_annotated
from xzh_qa.odds_gap_client import GAMES


LABEL_PLAYS = {
    '特肖', '五行', '生肖中', '生肖不中', '尾数中', '尾数不中',
    '二中特', '三中二', '二肖连中', '三肖连中', '四肖连中', '五肖连中',
    '二尾连不中', '三尾连不中', '四尾连不中',
}


@pytest.mark.smoke
def test_odds_gap_sub_label_screenshots(gap_context, odds_gap_run):
    """平台案例：[畫面驗證] Snotra-011：逐列捲動15項玩法後，三彩種主副名稱與數值是否可見
    前置條件：
    - QAT公司操作員編輯二級aaa222，使用正式設定頁規格；只讀取，無需還原設定。
    測試範圍：
    - 香港六合彩、英國天天彩、賓果六合彩，各15項主副玩法，共45張逐玩法畫面。
    步驟：
    1. 從用户管理搜尋aaa222、點编辑、開赔率差分，依次切换三彩種。
    2. 將特肖、五行、生肖及尾數中／不中、二中特、三中二、二至五肖連中、二至四尾連不中逐列捲至可見區，立即核對副標籤及兩組數值後截圖。
    3. 完成45項後關閉瀏覽器；不保存、不改授權、不下注，無還原事項。
    預期結果：
    - 45項各有可讀的主副名称、兩個差分輸入及兩個剩餘值；副標籤符合正式規格。
    佐證方式：
    - 每項独立紅框截圖、JSON原值及時間；本次補圖只涵蓋公司→二級，不代替先前495項全層驗證。
    已知問題：
    - 原圖只框代表列，內部捲動區其餘列不會因full_page截圖而自動完整顯示。
    """
    spec = json.loads(Path('data/xzh/odds_gap_setting_spec.json').read_text(encoding='utf-8'))
    expected = [r for r in spec['rows'] if r['name'] in LABEL_PLAYS]
    assert len(expected) == 15
    ctx = gap_context(1, via='company')
    records = []
    print(f'SCREENSHOTS {odds_gap_run.dir}', flush=True)
    for game in GAMES:
        with allure.step('開啟二級aaa222的赔率差分，切換香港六合彩、英國天天彩、賓果六合彩'):
            api = ctx.open(game)
            rows = ctx.setting.read_rows()
        for number, wanted in enumerate(expected, 1):
            with allure.step('逐列捲至可見區、核對主副名稱與兩組數值，標注並保存獨立截圖'):
                matches = [(i, r) for i, r in enumerate(rows)
                           if r['name'].split('/')[0].strip() in {wanted['name'], *wanted['nameAliases']}]
                assert len(matches) == 1
                i, actual = matches[0]
                assert actual['name'].split('/', 1)[1].strip() in {wanted['subLabel'], *wanted['subLabelAliases']}
                assert len(actual['inputs']) == len(actual['remaining']) == 2
                row = ctx.setting._rows().nth(i)
                row.scroll_into_view_if_needed()
                row.evaluate("e => { e.scrollIntoView({block:'center'}); e.setAttribute('data-gap-shot','target'); }")
                ctx.page.wait_for_timeout(150)
                bounds = row.bounding_box()
                assert bounds and bounds['y'] > 100 and bounds['y'] + bounds['height'] < 980, bounds
                filename = f'Snotra-011_fixed_{game}_{number:02d}_{wanted["name"]}.png'
                path = Path(odds_gap_run.dir) / filename
                capture_annotated(ctx.page, str(path),
                    marks=[{'selector': '[data-gap-shot="target"]', 'label': f'{actual["name"]}：左值對主項，右值對{wanted["subLabel"]}'}],
                    note=f'Snotra-011 補充修復截圖｜公司→二級aaa222｜{GAMES[game]}｜{number}/15 {actual["name"]}')
                row.evaluate("e => e.removeAttribute('data-gap-shot')")
                record = {'game': game, 'play': wanted['name'], 'expected_sub': wanted['subLabel'],
                          'actual': actual, 'api': api[i], 'screenshot': filename,
                          'observed_at': datetime.now().isoformat(timespec='seconds')}
                records.append(record)
                odds_gap_run.dump('screenshots.json', records)
                allure.attach(json.dumps(record, ensure_ascii=False), filename, allure.attachment_type.JSON)
                print(f'SHOT {game} {number}/15 {actual["name"]}', flush=True)
    assert len(records) == 45


@pytest.mark.smoke
def test_odds_gap_tabs_and_sub_labels(gap_context, odds_gap_run):
    """平台案例：[回歸驗證] Snotra-005／011：開啟各層三彩種後，分頁及15項主副標籤是否完整顯示
    前置條件：
    - QAT既有公司操作員、aaa111～aaa999與會員aaa010；公司差分啟用、一級授權勾選，使用核准設定頁規格。
    測試範圍：
    - 公司一至九級及會員、九級管理會員，共11條路徑；香港六合彩、英國天天彩、賓果六合彩，共33組。
    - 每組核對特肖、五行、生肖中／不中、尾數中／不中、二中特、三中二、二至五肖連中、二至四尾連不中，共15列。
    步驟：
    1. 公司從用户管理逐層搜尋帳號並點编辑，開赔率差分並切換三彩種，立即確認分頁選中及表頭玩法、赔率差分、剩余差分。
    2. 逐列確認15項主名／副標籤、兩個輸入及剩餘值；特肖／馬、五行／土、尾數／0尾、二中特／中二、三中二／中三及連肖／馬、連尾／0尾須符合核准規格。
    3. 由aaa999編輯直屬會員aaa010，重複三彩種入口及15列檢查；全程不保存、不改授權、不下注，關閉瀏覽器，無還原事項。
    預期結果：
    - 33組分頁顯示並可進入，各組15列主副標籤符合規格；差分主副值與對應API一致，共495項。
    佐證方式：
    - 逐組JSON、逐列期望與實際值、標注截圖及公司／一級授權前提；剩餘顯示精度不在本案例判準。
    已知問題：
    - Snotra-006保存403及Snotra-010不中副欄另單追蹤，不以本案例判通過。
    """
    spec = json.loads(Path('data/xzh/odds_gap_setting_spec.json').read_text(encoding='utf-8'))
    expected = [r for r in spec['rows'] if r['name'] in LABEL_PLAYS]
    assert len(expected) == 15, '15項目標與正式規格無法完整對應'
    results = []
    prerequisites = {}
    started = datetime.now().isoformat(timespec='seconds')
    plans = [('company', i) for i in range(10)] + [('parent', 9)]
    print(f'EVIDENCE {odds_gap_run.dir}', flush=True)
    for via, index in plans:
        ctx = None
        for game in GAMES:
            item = {'via': via, 'level': index + 1, 'game': game,
                    'tab_status': 'BLOCKED', 'labels_status': 'BLOCKED'}
            try:
                if ctx is None:
                    ctx = gap_context(index, via=via)
                if via == 'company' and index == 0 and not prerequisites:
                    prerequisites = {
                        'company_status': ctx.client.company_status(),
                        'level1_earn_odds_gap': ctx.setting.is_earn_odds_gap_checked(),
                    }
                with allure.step('從用户管理搜尋目標帳號、點编辑、開赔率差分並切換香港／英國／賓果彩種'):
                    api = ctx.open(game)
                ui = ctx.setting.read_rows()
                headers = ctx.setting.column_headers()
                assert all(h in headers for h in ('玩法', '赔率差分', '剩余差分'))
                assert ui and len(ui) == len(api)
                tab = ctx.page.get_by_role('tab', name='赔率差分', exact=True)
                assert tab.is_visible() and tab.get_attribute('aria-selected') == 'true'
                item.update(account=ctx.account, target_id=ctx.target_user_id,
                            tab_status='PASS', rows=len(ui), headers=headers)
                details = []
                for wanted in expected:
                    names = {wanted['name'], *wanted['nameAliases']}
                    matches = [(i, r) for i, r in enumerate(ui)
                               if r['name'].split('/')[0].strip() in names]
                    detail = {'play': wanted['name'], 'expected_sub': wanted['subLabel'],
                              'status': 'FAIL'}
                    if len(matches) == 1:
                        i, row = matches[0]
                        back = api[i]
                        labels = {wanted['subLabel'], *wanted['subLabelAliases']}
                        split = row['name'].split('/', 1)
                        detail.update(actual_name=row['name'], inputs=row['inputs'],
                                      remaining=row['remaining'], api_sub=back.get('subOddsLabel'),
                                      api_main=back.get('oddsGap'), api_sub_value=back.get('subOddsGap'))
                        values_match = len(row['inputs']) == 2 and all(
                            (actual == '' and raw is None) or
                            (raw is not None and Decimal(actual.replace(',', '')) == Decimal(str(raw)))
                            for actual, raw in zip(row['inputs'], [back.get('oddsGap'), back.get('subOddsGap')]))
                        if (len(split) == 2 and split[1].strip() in labels
                                and back.get('subOddsLabel') in labels and values_match
                                and len(row['remaining']) == 2 and all(row['remaining'])):
                            detail['status'] = 'PASS'
                    else:
                        detail['matches'] = len(matches)
                    details.append(detail)
                item.update(labels=details, labels_status='PASS' if all(
                    d['status'] == 'PASS' for d in details) else 'FAIL')
                name = f'{via}-{index+1}-{game}'
                odds_gap_run.dump(name + '-source.json', {'ui': ui, 'api': api, 'headers': headers})
                tab.evaluate("e => e.setAttribute('data-gap-recheck', 'tab')")
                marks = [{'selector': '[data-gap-recheck="tab"]', 'label': '赔率差分分頁已開啟'}]
                for n, row in enumerate(ui):
                    if row['name'].split('/')[0].strip() in LABEL_PLAYS:
                        ctx.setting._rows().nth(n).evaluate("e => e.setAttribute('data-gap-recheck', 'label')")
                marks.append({'selector': '[data-gap-recheck="label"]', 'label': '主名／副標籤及兩組數值；完整15項見逐列JSON'})
                capture_annotated(ctx.page, str(Path(odds_gap_run.dir) / (name + '.png')),
                                  marks=marks, note=f'Snotra-005／011複驗 {via} {ctx.account} {GAMES[game]}')
                ctx.page.locator('[data-gap-recheck]').evaluate_all(
                    "es => es.forEach(e => e.removeAttribute('data-gap-recheck'))")
                item['screenshot'] = name + '.png'
            except Exception as exc:
                item['error'] = f'{type(exc).__name__}: {str(exc)[:1200]}'
            results.append(item)
            allure.attach(json.dumps(item, ensure_ascii=False, indent=2),
                          f'{via}-{index+1}-{game} 主副名稱期望與實際值',
                          allure.attachment_type.JSON)
            odds_gap_run.dump('bug-regression-results.json', {
                'started': started, 'updated': datetime.now().isoformat(timespec='seconds'),
                'spec_version': spec['version'], 'prerequisites': prerequisites,
                'planned_groups': 33, 'results': results,
            })
            print(f"RECHECK {via} level={index+1} {game}: tab={item['tab_status']} labels={item['labels_status']} error={item.get('error', '')}", flush=True)
    assert prerequisites['company_status']['isEnabled'] is True
    assert prerequisites['level1_earn_odds_gap'] is True
    assert len(results) == 33
    assert all(r['tab_status'] == r['labels_status'] == 'PASS' and not r.get('error') for r in results), odds_gap_run.dir
