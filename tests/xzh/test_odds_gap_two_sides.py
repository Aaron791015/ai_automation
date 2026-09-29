"""兩面缺列回歸：十層三彩種只核對指定玩法存在，不代替完整B89。"""
import json
from pathlib import Path

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES


@pytest.mark.smoke
@allure.step('公司唯讀核對十層三彩種設定頁的兩面列、差分輸入與剩餘欄')
def test_odds_gap_two_sides_all_levels(gap_context, odds_gap_run):
    """前置條件：QAT指定十層帳號鏈，可由公司開啟設定頁。
    操作步驟：逐層切三彩種，等待UI/API列對齊，核對兩面並截圖。
    預期結果：每頁唯一兩面列，具有差分輸入欄與剩餘值；不修改設定。
    佐證方式：各組API/UI原值、截圖與逐組結果，不宣稱其他玩法完整通過。
    """
    results = []
    for index in range(10):
        ctx = gap_context(index, via='company')
        for game in GAMES:
            item = {'level': index+1, 'account': ctx.account, 'game': game, 'via': 'company'}
            try:
                api = ctx.open(game)
                ui = ctx.setting.read_rows()
                matches = [r for r in ui if r['name'].strip() in ('两面', '兩面')]
                backend = [r for r in api if r['playTypeName'].strip() in ('两面', '兩面')]
                item.update(ui=matches, api=backend)
                assert len(matches) == len(backend) == 1, '兩面列缺少或重複'
                assert len(matches[0]['inputs']) == 1, '兩面差分輸入欄缺少'
                assert len(matches[0]['remaining']) == 1 and matches[0]['remaining'][0], '兩面剩餘欄缺少'
                item['status'] = 'PASS'
            except Exception as exc:
                item.update(status='FAIL', error=str(exc)[:1000])
            ctx.page.screenshot(path=str(Path(odds_gap_run.dir) / f'two-sides-{index+1}-{game}.png'), full_page=True)
            results.append(item)
            odds_gap_run.dump('two-sides-results.json', results)
            print(f"TWO_SIDES level={index+1} {game}: {item['status']}", flush=True)
    allure.attach(json.dumps(results, ensure_ascii=False), '兩面逐層三彩種實測', allure.attachment_type.JSON)
    assert len(results) == 30 and all(r['status'] == 'PASS' for r in results)
