"""B89：依使用者核准規格逐層唯讀核對，不使用歷史快照作完整性判準。"""
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES


from xzh_qa.odds_gap_spec import compare_spec


@pytest.mark.smoke
@allure.step('唯讀核對公司與直屬上級的十層三彩種，依正式101列116欄規格逐欄比對')
def test_odds_gap_approved_spec_all_levels(gap_context, odds_gap_run):
    """前置條件：QAT既有授權帳號鏈與已確認設定頁規格。
    操作步驟：公司及直屬上級各沿UI開啟一至九級與會員，讀取三彩種全部列及主副欄。
    預期結果：各組符合101列116欄（2026-09-24不中改單一輸入欄）、核准名稱及副標籤，畫面值與GET一致。
    佐證方式：逐組JSON、完整頁面截圖、逐欄判定；本案例不輸入、不保存、不切換授權。
    """
    spec = json.loads(Path('data/xzh/odds_gap_setting_spec.json').read_text(encoding='utf-8'))
    results = []
    started = time.monotonic()
    vias = os.environ.get('XZH_GAP_SPEC_VIA', 'company,parent').split(',')
    requested_levels = {int(x) for x in os.environ.get('XZH_GAP_SPEC_LEVELS', '1,2,3,4,5,6,7,8,9,10').split(',')}
    assert vias and set(vias) <= {'company', 'parent'} and requested_levels <= set(range(1, 11))
    planned = [(via, index) for via in vias for index in range(0 if via == 'company' else 1, 10) if index + 1 in requested_levels]
    assert planned
    for via in vias:
        for index in range(0 if via == 'company' else 1, 10):
            if index + 1 not in requested_levels:
                continue
            ctx = None
            for game in GAMES:
                item = {'via': via, 'level': index + 1, 'game': game}
                tick = time.monotonic()
                try:
                    if ctx is None:
                        ctx = gap_context(index, via=via)
                    seen = len(ctx.observed['target_user_ids'])
                    ctx.setting.open_target(ctx.level_name, ctx.account)
                    ctx.setting.select_game(game)
                    for _ in range(50):
                        if ctx.observed['target_user_ids'][seen:]:
                            break
                        ctx.page.wait_for_timeout(100)
                    ids = ctx.observed['target_user_ids'][seen:]
                    assert ids and len(set(ids)) == 1, '未取得唯一的UI目標ID'
                    ctx._user_id = ids[0]
                    api = ctx.api_rows(game)
                    for _ in range(30):
                        ui = ctx.setting.read_rows()
                        if [r['name'].split('/')[0].strip() for r in ui] == [r['playTypeName'].split('/')[0].strip() for r in api]:
                            break
                        ctx.page.wait_for_timeout(200)
                    ui = ctx.setting.read_rows()
                    headers = ctx.setting.column_headers()
                    name = f'{via}-{index+1}-{game}'
                    odds_gap_run.dump(name + '-source.json', {'api': api, 'ui': ui, 'headers': headers})
                    assert [r['name'].split('/')[0].strip() for r in ui] == [r['playTypeName'].split('/')[0].strip() for r in api], 'UI/API列無法對齊'
                    item.update(account=ctx.account, **compare_spec(spec, ui, api, headers))
                    ctx.page.screenshot(path=str(Path(odds_gap_run.dir) / (name + '.png')), full_page=True)
                except Exception as exc:
                    item.update(status='BLOCKED', error=str(exc)[:1200])
                item['seconds'] = round(time.monotonic() - tick, 2)
                results.append(item)
                odds_gap_run.dump('approved-spec-results.json', {'version': spec['version'], 'seconds': round(time.monotonic()-started, 2), 'results': results})
                print(f"SPEC {via} level={index+1} {game}: {item['status']} rows={item.get('rows')} inputs={item.get('inputs')}", flush=True)
    allure.attach(json.dumps(results, ensure_ascii=False), '正式規格逐欄期望與實際結果', allure.attachment_type.JSON)
    assert len(results) == len(planned) * 3
    assert all(r['status'] == 'PASS' for r in results), f'核准規格未全數符合，詳見 {odds_gap_run.dir}'
