# -*- coding: utf-8 -*-
"""依 odds-gap (1).md §3.4／§4.3 的離線手算向量；不連線、不下注。"""
from decimal import Decimal as D
import pytest
from xzh_qa.odds_gap_chain_winner import chain_frozen_odds


@pytest.mark.parametrize("prices,main,sub,floor,subfloor,winner,tier,expected", [
    ({"蛇":"4.0109","马":"4.0676"},"-0.10","-0.20","3.8487","3.2541","马","sub","3.8676"),
    ({"蛇":"3.9609","马":"4.0676"},"-0.10","-0.20","3.8487","3.2541","蛇","main","3.8609"),
    ({"马":"4.0676","羊":"4.8109"},"-0.10","-0.20","3.8487","3.2541","马","sub","3.8676"),
    ({"蛇":"4.1","马":"4.0676"},"-0.3","-0.02","3","3","蛇","main","3.8"),
    ({"蛇":"3.9","马":"4.0676"},"-0.5","-0.2","3.8487","3.2541","蛇","main","3.8487"),
    ({"蛇":"3.9","马":"4.0676"},"-0.5","-0.2","3.9","3.2541","马","sub","3.8676"),
    ({"蛇":"4.0676","马":"4.0676"},"-0.1","-0.2","3","3","马","sub","3.8676"),
    ({"蛇":"4.8109","龙":"4.8109"},"-0.1","-0.2","3.8487","3.2541","蛇","main","4.7109"),
    ({"蛇":"4.5","马":"3.2"},"-0.1","-0.2","3.8","3.5","马","sub","3.2"),
    ({"蛇":"4.5","马":"3.2"},"-0.1",None,"3.8",None,"马","sub","3.2"),
])
def test_final_member_price(prices, main, sub, floor, subfloor, winner, tier, expected):
    result = chain_frozen_odds(prices, {"马"}, main, sub, floor, subfloor)
    # 同層同值成員不限定名稱；成交價與層別才是此案例判準。
    assert result["tier"] == tier and result["expected"] == D(expected)
    if len(set(prices.values())) > 1 or "马" in prices:
        assert result["winner"] == winner


@pytest.mark.parametrize("prices", [{"马":"4.1","蛇":"4.0"}, {"蛇":"4.0","马":"4.1"}])
def test_final_tie_uses_main_regardless_of_member_order(prices):
    result = chain_frozen_odds(prices, {"马"}, "-0.1", "-0.2", "3", "3")
    assert result["winner"] == "蛇" and result["tier"] == "main" and result["expected"] == D("3.9")


def test_board_exception_reads_sub_price_not_main():
    from xzh_qa.odds_gap_chain_winner import board_member_price
    row = {"odds": 4.8109, "subOdds": 4.0676}
    assert board_member_price(row, True) == D("4.0676")
    assert board_member_price(row, False) == D("4.8109")
    with pytest.raises(AssertionError, match="subOdds"):
        board_member_price({"odds": 4.8109}, True)


@pytest.mark.parametrize("offset,steps", [
    ("0.85", ["0.5", "0.1", "0.1", "0.1", "0.05"]),
    ("0.8", ["0.5", "0.1", "0.1", "0.1"]),
    ("0.005", ["0.005"]),
    ("1.057", ["1", "0.05", "0.005", "0.001", "0.001"]),
])
def test_offset_split_into_step_options(offset, steps):
    from xzh_qa.odds_gap_chain_winner import split_offset
    assert [str(s) for s in split_offset(offset)] == steps


@pytest.mark.parametrize("offset", ["0.0005", "0", "-0.1"])
def test_offset_not_composable_is_rejected(offset):
    from xzh_qa.odds_gap_chain_winner import split_offset
    with pytest.raises(AssertionError):
        split_offset(offset)


@pytest.mark.parametrize("prices,main,sub,winner,tier,expected", [
    # B112：十層差分皆0、蛇偏移0.85
    ({"蛇":"3.9609","马":"4.0676"},"0","0","蛇","main","3.9609"),
    ({"马":"4.0676","羊":"4.8109"},"0","0","马","sub","4.0676"),
    # B113：主−0.10、副−0.20、不偏移
    ({"蛇":"4.8109","马":"4.0676"},"-0.10","-0.20","马","sub","3.8676"),
    ({"马":"4.0676","羊":"4.8109"},"-0.10","-0.20","马","sub","3.8676"),
    # B115：主−1.24 觸底 3.8487、副−0.50 得 3.5676
    ({"蛇":"4.8109","马":"4.0676"},"-1.24","-0.50","马","sub","3.5676"),
    ({"马":"4.0676","羊":"4.8109"},"-1.24","-0.50","马","sub","3.5676"),
    # B114 現行：主−0.9433、副−0.2000 → 主副同為 3.8676，同價取主層
    ({"蛇":"4.8109","马":"4.0676"},"-0.9433","-0.2000","蛇","main","3.8676"),
    ({"马":"4.0676","羊":"4.8109"},"-0.9433","-0.2000","羊","main","3.8676"),
])
def test_chain_variant_vectors(prices, main, sub, winner, tier, expected):
    result = chain_frozen_odds(prices, {"马"}, main, sub, "3.8487", "3.2541")
    assert (result["winner"], result["tier"], result["expected"]) == (winner, tier, D(expected))


def test_main_floor_applies_when_not_winning():
    result = chain_frozen_odds({"蛇": "4.8109", "龙": "4.8109"}, {"马"}, "-1.24", "-0.50", "3.8487", "3.2541")
    assert result["tier"] == "main" and result["expected"] == D("3.8487")


@pytest.mark.parametrize("row,target,columns", [
    ({"oddsGap": 0.0, "subOddsGap": 0.0}, ("0", "0"), []),
    ({"oddsGap": 0.0, "subOddsGap": None}, ("0", "0"), []),
    ({"oddsGap": -0.01, "subOddsGap": 0.0}, ("0", "0"), [(0, D("0"))]),
    ({"oddsGap": 0.0, "subOddsGap": 0.0}, ("-0.01", "-0.02"), [(0, D("-0.01")), (1, D("-0.02"))]),
    ({"oddsGap": -0.01, "subOddsGap": -0.02}, ("-0.01", "-0.02"), []),
])
def test_gap_columns_to_write_skips_layers_already_on_target(row, target, columns):
    from xzh_qa.odds_gap_chain_winner import gap_columns_to_write
    assert gap_columns_to_write(row, *target) == columns


def test_expand_layer_gaps_single_pair_and_ten_layers():
    from xzh_qa.odds_gap_chain_winner import expand_layer_gaps
    assert expand_layer_gaps(("-0.01", "-0.02")) == [(D("-0.01"), D("-0.02"))] * 10
    layers = [("-0.0944", "-0.0200")] * 3 + [("-0.0943", "-0.0200")] * 7
    expanded = expand_layer_gaps(layers)
    assert sum(m for m, _ in expanded) == D("-0.9433") and sum(s for _, s in expanded) == D("-0.2000")
    with pytest.raises(AssertionError):
        expand_layer_gaps(("0.01", "0"))
    with pytest.raises(AssertionError):
        expand_layer_gaps([("-0.1", "-0.1")] * 3)


def test_board_missing_sub_uses_explicit_sub_baseline_without_offset():
    from xzh_qa.odds_gap_chain_winner import board_member_price
    assert board_member_price({"odds":4.8109,"subOdds":None}, True, "4.0676") == D("4.0676")
    with pytest.raises(AssertionError, match="偏移"):
        board_member_price({"odds":4.8109,"hasManualOffset":True}, True, "4.0676")
