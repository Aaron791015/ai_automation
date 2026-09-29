# -*- coding: utf-8 -*-
"""`xzh_qa.odds_gap_chain_winner.chain_frozen_odds` 的手算向量（2026-09-29 新版文件：主副層依贏家成員）。

前置條件：無；不連線、不下注。
"""
import pytest
from decimal import Decimal as D

from xzh_qa.odds_gap_chain_winner import chain_frozen_odds


def test_公司價蛇較低但會員最終價马較低時走副層():
    r = chain_frozen_odds({"蛇": D("4.0109"), "马": D("4.0676")}, {"马"}, D("-0.10"), D("-0.20"), D("3.8487"), D("3.2541"))
    assert r["winner"] == "马" and r["tier"] == "sub" and r["expected"] == D("3.8676")


def test_马最低時整注走副層與副下限():
    r = chain_frozen_odds({"马": D("4.0676"), "羊": D("4.8109")}, {"马"}, D("-0.10"), D("-0.20"), D("3.8487"), D("3.2541"))
    assert r["winner"] == "马" and r["tier"] == "sub" and r["expected"] == D("3.8676")


def test_主層觸底時取主下限():
    r = chain_frozen_odds({"蛇": D("3.9"), "马": D("4.0676")}, {"马"}, D("-0.5"), D("-0.2"), D("3.8487"), D("3.2541"))
    assert r["tier"] == "main" and r["expected"] == D("3.8487")


def test_公司價同值時仍比較扣差分後的會員價():
    r = chain_frozen_odds({"蛇": D("4.0676"), "马": D("4.0676")}, {"马"}, D("-0.1"), D("-0.2"), D("3"), D("3"))
    assert r["winner"] == "马" and r["tier"] == "sub"


def test_主副最終同價不自行指定優先層():
    with pytest.raises(ValueError, match="層別選用規則待確認"):
        chain_frozen_odds({"蛇": "4.0", "马": "4.1"}, {"马"}, "-0.1", "-0.2", "3", "3")


def test_套用下限後才比較最終價():
    r = chain_frozen_odds({"蛇": "3.9", "马": "4.0676"}, {"马"}, "-0.5", "-0.2", "3.9", "3.2541")
    assert r["tier"] == "sub" and r["expected"] == D("3.8676")


def test_偏移0點85時一般成員最終價最低走主層():
    """0.85 樣本：蛇 4.8109−0.85＝3.9609，扣主差分後 3.8609 ＜ 马 4.0676−0.20＝3.8676 → 蛇勝出、主層。"""
    r = chain_frozen_odds({"蛇": D("3.9609"), "马": D("4.0676")}, {"马"}, D("-0.10"), D("-0.20"), D("3.8487"), D("3.2541"))
    assert r["winner"] == "蛇" and r["tier"] == "main" and r["expected"] == D("3.8609")
