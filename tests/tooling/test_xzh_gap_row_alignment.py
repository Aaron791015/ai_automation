"""保護保存及還原前的UI/API列對齊，接受新版副標籤但拒絕錯列。"""
from types import SimpleNamespace

import pytest

from xzh_qa.pages.odds_gap_setting_page import OddsGapSettingPage


@pytest.mark.parametrize('name,valid', [
    ('二中特', True), ('二中特 / 中二', True),
    ('二中特 / 中三', False), ('三中二 / 中二', False),
])
def test_row_alignment_with_sub_label(name, valid):
    page = OddsGapSettingPage(SimpleNamespace(wait_for_timeout=lambda _: None))
    rows = [{'name': name, 'inputs': ['0', '0'], 'remaining': ['1', '1']}]
    page.read_rows = lambda: rows
    api = [{'playTypeName': '二中特', 'subOddsLabel': '中二'}]
    if valid:
        assert page.wait_rows_match(api, timeout_ms=200) == rows
    else:
        with pytest.raises(AssertionError):
            page.wait_rows_match(api, timeout_ms=200)


def _page_with_reads(reads):
    """每次 read_rows 依序回傳 reads 的下一筆（最後一筆重複），模擬重載後數值晚綁上。"""
    page = OddsGapSettingPage(SimpleNamespace(wait_for_timeout=lambda _: None))
    state = {'n': 0}

    def read_rows():
        rows = reads[min(state['n'], len(reads) - 1)]
        state['n'] += 1
        return rows
    page.read_rows = read_rows
    return page


API = [{'playTypeName': '特肖', 'oddsGap': -1.1, 'subOddsGap': -0.001},
       {'playTypeName': '五不中', 'oddsGap': 0.0, 'subOddsGap': None}]


def test_values_bound_late_waits_until_match():
    """★ 2026-09-23 回歸：列名先出現、數值晚綁上時，要等到與 API 一致才讀。"""
    stale = [{'name': '特肖', 'inputs': ['0.0000', '0.0000']}, {'name': '五不中', 'inputs': ['0.0000']}]
    bound = [{'name': '特肖', 'inputs': ['-1.1000', '-0.0010']}, {'name': '五不中', 'inputs': ['0.0000']}]
    sync = _page_with_reads([stale, stale, bound]).wait_values_match(API, timeout_ms=1000)
    assert sync['matched'] and sync['rows'] == bound
    assert sync['first_mismatches'] == 2 and sync['waited_ms'] == 400


def test_values_never_match_returns_last_read_for_caller_to_fail():
    """畫面真的顯示錯值時，逾時後原樣回傳，不可被當成一致。"""
    wrong = [{'name': '特肖', 'inputs': ['0.0000', '-0.0010']}, {'name': '五不中', 'inputs': ['0.0000']}]
    sync = _page_with_reads([wrong]).wait_values_match(API, timeout_ms=600)
    assert not sync['matched'] and sync['rows'] == wrong and sync['waited_ms'] == 600
