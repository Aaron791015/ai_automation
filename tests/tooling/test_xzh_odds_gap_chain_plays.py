# -*- coding: utf-8 -*-
"""T79 其餘連肖／連尾玩法的差分設計與期望價：離線手算向量（2026-10-02 開工當下的公司 OddsSetting）；不連線、不下注。"""
from decimal import Decimal as D

import pytest

from xzh_qa.odds_gap_chain_plays import (
    CHAIN_PLAYS, NOT_APPLICABLE, applicable_plays, candidate_prices, design_row, expected_price, split_total)

#: 2026-10-02 18:10 讀到的賓果 OddsSetting（與 10/01 14:2x 的 T79 設計值完全相同）
PRICING = {
    "chainZodiac3Hit": dict(odds=12.2661, minOdds=9.8129, subOdds=10.2866, subMinOdds=8.2293),
    "chainZodiac4Hit": dict(odds=35.866, minOdds=28.6928, subOdds=29.801, subMinOdds=23.8408),
    "chainZodiac5Hit": dict(odds=127.184, minOdds=101.7472, subOdds=104.5579, subMinOdds=83.6463),
    "chainTail2Miss": dict(odds=5.5123, minOdds=4.4098, subOdds=4.5476, subMinOdds=3.6381),
    "chainTail3Miss": dict(odds=15.7602, minOdds=12.6082, subOdds=12.6082, subMinOdds=10.0866),
    "chainTail4Miss": dict(odds=54.3215, minOdds=43.4572, subOdds=41.6465, subMinOdds=33.3172),
}

#: （情境, 玩法）→（主合計, 副合計, 預期成交價, 成交層）。數值取自交接 T79 列的手算，不由被測函式反推。
VECTORS = {
    ("flat", "chainZodiac3Hit"): ("-0.10", "-0.20", "10.0866", "sub"),
    ("flat", "chainZodiac4Hit"): ("-0.10", "-0.20", "29.601", "sub"),
    ("flat", "chainZodiac5Hit"): ("-0.10", "-0.20", "104.3579", "sub"),
    ("flat", "chainTail2Miss"): ("-0.10", "-0.20", "4.3476", "sub"),
    ("flat", "chainTail3Miss"): ("-0.10", "-0.20", "12.4082", "sub"),
    ("flat", "chainTail4Miss"): ("-0.10", "-0.20", "41.4465", "sub"),
    ("tie", "chainZodiac3Hit"): ("-2.1795", "-0.20", "10.0866", "main"),
    ("tie", "chainZodiac4Hit"): ("-6.265", "-0.20", "29.601", "main"),
    ("tie", "chainZodiac5Hit"): ("-22.8261", "-0.20", "104.3579", "main"),
    ("tie", "chainTail2Miss"): ("-1.0647", "-0.10", "4.4476", "main"),
    ("tie", "chainTail3Miss"): ("-3.152", "0", "12.6082", "main"),
    ("floor", "chainZodiac3Hit"): ("-2.80", "-1.00", "9.2866", "sub"),
    ("floor", "chainZodiac4Hit"): ("-7.50", "-3.00", "26.801", "sub"),
    ("floor", "chainZodiac5Hit"): ("-25.80", "-10.00", "94.5579", "sub"),
    ("floor", "chainTail2Miss"): ("-1.40", "-0.50", "4.0476", "sub"),
    ("floor", "chainTail3Miss"): ("-3.50", "-1.20", "11.4082", "sub"),
    ("floor", "chainTail4Miss"): ("-11.50", "-4.00", "37.6465", "sub"),
}


@pytest.mark.parametrize("key", sorted(VECTORS))
def test_design_matches_hand_computed_vector(key):
    scenario, play = key
    main_total, sub_total, price, tier = VECTORS[key]
    design = design_row(scenario, play, PRICING[play])
    assert (design["main_total"], design["sub_total"]) == (D(main_total), D(sub_total))
    assert design["expected"] == D(price) and design["tier"] == tier
    assert len(design["layers"]) == 10
    assert sum((m for m, _ in design["layers"]), D(0)) == D(main_total)
    assert sum((s for _, s in design["layers"]), D(0)) == D(sub_total)
    assert all(m <= 0 and s <= 0 for m, s in design["layers"]), "差分只能為 0 或負數"
    assert all(abs(m.as_tuple().exponent) <= 4 and abs(s.as_tuple().exponent) <= 4 for m, s in design["layers"])


def test_tie_means_both_tiers_have_the_same_final_price_and_nothing_is_floored():
    for play in applicable_plays("tie"):
        design = design_row("tie", play, PRICING[play])
        assert design["candidates"]["main"] == design["candidates"]["sub"] == design["expected"]
        assert not design["main_floored"], f"{play} 同價設計不可靠觸底湊成"


def test_floor_means_main_is_floored_and_sub_is_lower_and_not_floored():
    for play in applicable_plays("floor"):
        row = PRICING[play]
        design = design_row("floor", play, row)
        assert design["main_floored"], f"{play} 主層應觸底"
        assert design["candidates"]["main"] == D(str(row["minOdds"]))
        assert D(str(row["subMinOdds"])) < design["candidates"]["sub"] < design["candidates"]["main"]


def test_four_tail_has_no_tie_design_and_reason_is_recorded():
    assert ("tie", "chainTail4Miss") in NOT_APPLICABLE
    assert "chainTail4Miss" not in applicable_plays("tie")
    # 主最低 43.4572 高於副基準 41.6465：主層價恆大於副層價
    row = PRICING["chainTail4Miss"]
    assert D(str(row["minOdds"])) > D(str(row["subOdds"]))
    assert len(applicable_plays("tie")) == 5 and len(applicable_plays("flat")) == 6 == len(applicable_plays("floor"))


def test_total_bets_and_money_match_the_plan():
    groups = sum(len(applicable_plays(s)) for s in ("flat", "tie", "floor"))
    assert groups == 17
    assert groups * 2 == 34


@pytest.mark.parametrize("total,expected_head", [("-2.1795", ["-0.2180"] * 5 + ["-0.2179"] * 5), ("-0.10", ["-0.0100"] * 10),
                                                  ("0", ["0"] * 10)])
def test_split_total_gives_extra_tick_to_first_layers(total, expected_head):
    layers = split_total(D(total))
    assert layers == [D(x) for x in expected_head] and sum(layers, D(0)) == D(total)


def test_split_total_rejects_positive_and_over_precision():
    with pytest.raises(AssertionError):
        split_total(D("0.1"))
    with pytest.raises(AssertionError):
        split_total(D("-0.12345"))


def test_bets_cover_exception_member_and_selection_order():
    # 連肖受測以「…蛇,马」結尾、對照「马,羊…」；連尾受測含「0尾,1尾」、對照「…9,0」
    z3, z4, z5 = (CHAIN_PLAYS[p] for p in ("chainZodiac3Hit", "chainZodiac4Hit", "chainZodiac5Hit"))
    assert z3.names(z3.tested_start) == ("龙", "蛇", "马") and z3.names(z3.control_start) == ("马", "羊", "猴")
    assert z4.names(z4.tested_start) == ("兔", "龙", "蛇", "马") and z4.names(z4.control_start) == ("马", "羊", "猴", "鸡")
    assert z5.names(z5.tested_start) == ("虎", "兔", "龙", "蛇", "马") and z5.names(z5.control_start) == ("马", "羊", "猴", "鸡", "狗")
    t2, t3, t4 = (CHAIN_PLAYS[p] for p in ("chainTail2Miss", "chainTail3Miss", "chainTail4Miss"))
    assert t2.keys(t2.tested_start) == ("0", "1") and t2.keys(t2.control_start) == ("9", "0")
    assert t3.keys(t3.tested_start) == ("9", "0", "1") and t3.keys(t3.control_start) == ("8", "9", "0")
    assert t4.keys(t4.tested_start) == ("8", "9", "0", "1") and t4.keys(t4.control_start) == ("7", "8", "9", "0")
    for cfg in CHAIN_PLAYS.values():
        for _, start in cfg.bets:
            assert cfg.exception_key in cfg.keys(start), f"{cfg.play} 兩注都須含副標籤成員"


def test_expected_price_uses_effective_floor_and_main_on_tie():
    cfg = CHAIN_PLAYS["chainTail3Miss"]
    row = PRICING["chainTail3Miss"]
    # 三尾 tie：主 15.7602−3.152＝12.6082（恰等於主最低），副 12.6082＋0＝12.6082 → 同價取主層
    result = expected_price(cfg, row, {"9": D("15.7602"), "0": D("12.6082"), "1": D("15.7602")}, D("-3.152"), D("0"))
    assert result["expected"] == D("12.6082") and result["tier"] == "main"
    cand = candidate_prices(row, D("-3.152"), D("0"))
    assert cand["main"] == cand["sub"] == D("12.6082")


# ---------------------------------------------------------------- T61 追主分支中獎樣本（odds_gap_chain_chase）
def test_chase_pool_never_contains_exception_member_and_spreads_combos():
    from xzh_qa.odds_gap_chain_chase import main_pool, spread_combos
    for cfg in CHAIN_PLAYS.values():
        pool = main_pool(cfg)
        assert all(cfg.exception_key not in combo and len(combo) == cfg.count for combo in pool)
        picked = spread_combos(pool, 10, "seed")
        assert len(picked) == len(set(picked)) == 10
    # 二尾（9 個非 0 尾數取 2 個＝36 組）10 組互不重複，且兩兩重疊成員不超過 1 個（只有一個成員重疊）
    picked = spread_combos(main_pool(CHAIN_PLAYS["chainTail2Miss"]), 10, "seed")
    assert max(len(set(a) & set(b)) for i, a in enumerate(picked) for b in picked[:i]) <= 1


def test_chase_layers_are_nonzero_distinct_and_never_floor():
    from xzh_qa.odds_gap_chain_chase import CHASE_MAIN_LAYERS, CHASE_SUB_LAYERS
    assert len(set(CHASE_MAIN_LAYERS)) == len(set(CHASE_SUB_LAYERS)) == 10
    assert all(v < 0 for v in CHASE_MAIN_LAYERS + CHASE_SUB_LAYERS) and set(CHASE_MAIN_LAYERS).isdisjoint(CHASE_SUB_LAYERS)
    assert sum(CHASE_MAIN_LAYERS) == D("-0.155") and sum(CHASE_SUB_LAYERS) == D("-0.310")
    for play, row in PRICING.items():
        assert D(str(row["odds"])) + sum(CHASE_MAIN_LAYERS) > D(str(row["minOdds"])), f"{play} 主價不得觸底"


def test_chase_win_rules_for_zodiac_hit_and_tail_miss():
    from xzh_qa.odds_gap_chain_chase import win_of
    # yearZodiacIndex＝0：號碼 n 的生肖索引＝(0 − (n−1)) mod 12 → 1＝鼠、2＝豬、3＝狗…
    issue = {"drawNumbers": [1, 2, 3, 14, 15, 26, 27], "yearZodiacIndex": 0}
    assert win_of("chainZodiac3Hit", ("rat", "pig", "dog"), issue)
    assert not win_of("chainZodiac3Hit", ("rat", "pig", "ox"), issue)
    # 尾數：1,2,3,4,5,6,7 → 連尾不中須所選尾數全部沒出現
    assert win_of("chainTail2Miss", ("8", "9"), issue) and not win_of("chainTail2Miss", ("8", "7"), issue)
    assert win_of("chainTail3Miss", ("0", "8", "9"), issue)
