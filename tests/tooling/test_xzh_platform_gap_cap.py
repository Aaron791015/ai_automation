"""上限百分比來源與單位的離線判準，禁止缺來源時假通過。"""
from decimal import Decimal

import pytest

from xzh_qa.odds_gap_client import OddsGapClient
from xzh_qa.pages.platform_system_page import percent_to_rate


@pytest.mark.parametrize('raw,expected', [('80', '0.8'), ('0', '0'), ('100', '1'), ('12.34', '0.1234')])
def test_percentage_units(raw, expected):
    assert percent_to_rate(raw) == Decimal(expected)


@pytest.mark.parametrize('raw', ['', 'NaN', 'Infinity', '-1', '100.01', '80%'])
def test_invalid_percentage_blocked(raw):
    with pytest.raises((ValueError, ArithmeticError)):
        percent_to_rate(raw)


def test_cap_requires_company1_live_evidence():
    client = OddsGapClient(None, 'http://company1.snotra.qat', {})
    assert client.cap_rate() == (Decimal('0.8'), False)
    evidence = dict(source='platform-company-edit', account='company1', label='赔率差上限',
                    unit='%', percent='75', rate='0.75', observed_at='2026-09-17T04:00:00Z')
    client.platform_cap_evidence = evidence
    assert client.cap_rate() == (Decimal('0.75'), True)
    for key, value in [('account', 'company2'), ('source', 'snapshot'), ('unit', ''),
                       ('percent', ''), ('rate', '75'), ('observed_at', None), ('error', 'timeout')]:
        client.platform_cap_evidence = {**evidence, key: value}
        assert client.cap_rate()[1] is False
