# -*- coding: utf-8 -*-
"""B120／B121 連肖／連尾「一般成員較低」的調整量與期望價：離線向量（2026-10-05 實跑當下的賓果 OddsSetting）；不連線、不下注。"""
from decimal import Decimal as D

import pytest

from xzh_qa import config_loader, odds_gap_chain_lower as lower
from xzh_qa.odds_gap_chain_plays import CHAIN_PLAYS
from xzh_qa.odds_gap_chain_winner import split_offset

#: 2026-10-05 讀到的賓果 OddsSetting（`reports/odds_gap_regression/chain-general-lower-20261005-a1/ledger-bingo.json`）
PRICING = {
    "chainZodiac3Hit": dict(odds=12.2661, minOdds=9.8129, subOdds=10.2866, subMinOdds=8.2293),
    "chainZodiac4Hit": dict(odds=35.866, minOdds=28.6928, subOdds=29.801, subMinOdds=23.8408),
    "chainZodiac5Hit": dict(odds=127.184, minOdds=101.7472, subOdds=104.5579, subMinOdds=83.6463),
    "chainTail2Miss": dict(odds=5.5123, minOdds=4.4098, subOdds=4.5476, subMinOdds=3.6381),
    "chainTail3Miss": dict(odds=15.7602, minOdds=12.6082, subOdds=12.6082, subMinOdds=10.0866),
    "chainTail4Miss": dict(odds=54.3215, minOdds=43.4572, subOdds=41.6465, subMinOdds=33.3172),
}

#: 玩法 →（調整量, 受測注, 對照注）。B120 取自 10/05 臨時腳本實跑的調整量與成交價（8／8 相符），不由被測函式反推。
NO_GAP = {
    "chainZodiac3Hit": ("2.10", "10.1661", "10.2866"),
    "chainZodiac4Hit": ("6.50", "29.366", "29.801"),
    "chainZodiac5Hit": ("24.00", "103.184", "104.5579"),
    "chainTail2Miss": ("1.05", "4.4623", "4.5476"),
}
#: B121：每層（主, 副）差分、調整量、受測注、對照注。三肖／四肖／二尾同 10/05 實跑；五肖 10/05 用 23.00，
#: 本選法（點擊次數最少、其次接近中點、兩端各留 25%）固定取 24.00 → 受測注 (127.184−24.00)−0.10＝103.084。
WITH_GAP = {
    "chainZodiac3Hit": (("-0.01", "-0.02"), "2.20", "9.9661", "10.0866"),
    "chainZodiac4Hit": (("-0.01", "-0.02"), "6.50", "29.266", "29.601"),
    "chainZodiac5Hit": (("-0.01", "-0.02"), "24.00", "103.084", "104.3579"),
    "chainTail2Miss": (("-0.001", "-0.002"), "1.03", "4.4723", "4.5276"),
}


@pytest.mark.parametrize("play", sorted(NO_GAP))
def test_without_gap_reproduces_live_offset_and_prices(play):
    d, tested, control = NO_GAP[play]
    design = lower.design_play(play, PRICING[play], with_gap=False)
    assert design["plan"]["d"] == D(d)
    assert (design["tested"]["expected"], design["tested"]["tier"]) == (D(tested), "main")
    assert (design["control"]["expected"], design["control"]["tier"]) == (D(control), "sub")


@pytest.mark.parametrize("play", sorted(WITH_GAP))
def test_with_gap_picks_per_layer_gap_and_offset(play):
    (gm, gs), d, tested, control = WITH_GAP[play]
    design = lower.design_play(play, PRICING[play], with_gap=True)
    assert design["per_layer"] == (D(gm), D(gs))
    assert (design["main_total"], design["sub_total"]) == (D(gm) * 10, D(gs) * 10)
    assert design["plan"]["d"] == D(d)
    assert (design["tested"]["expected"], design["tested"]["tier"]) == (D(tested), "main")
    assert (design["control"]["expected"], design["control"]["tier"]) == (D(control), "sub")
    # 兩種錯誤路徑都要和期望價不同，樣本才有鑑別力
    assert all(v != design["tested"]["expected"] for v in design["wrong"].values())


@pytest.mark.parametrize("with_gap", [False, True])
@pytest.mark.parametrize("play", ["chainTail3Miss", "chainTail4Miss"])
def test_tail3_tail4_not_applicable_under_current_odds(play, with_gap):
    design = lower.design_play(play, PRICING[play], with_gap=with_gap)
    assert design["plan"] is None and "區間為空" in design["not_applicable"]


@pytest.mark.parametrize("play", sorted(NO_GAP))
@pytest.mark.parametrize("with_gap", [False, True])
def test_offset_keeps_margin_inside_interval_and_is_clickable(play, with_gap):
    design = lower.design_play(play, PRICING[play], with_gap=with_gap)
    plan = design["plan"]
    assert plan["lo"] + plan["margin"] <= plan["d"] <= plan["hi"] - plan["margin"]
    assert sum(plan["steps"], D(0)) == plan["d"] and plan["steps"] == split_offset(plan["d"])
    # 受測注被調低成員扣主差分後仍高於主最低（沒有觸底）
    assert plan["offset_price"] + design["main_total"] > D(str(PRICING[play]["minOdds"]))


@pytest.mark.parametrize("play", lower.PLAYS)
def test_tested_bet_has_offset_and_exception_members_control_only_exception(play):
    cfg = CHAIN_PLAYS[play]
    offset_key = lower.OFFSET_MEMBER[cfg.kind][1]
    assert {offset_key, cfg.exception_key} <= set(cfg.keys(cfg.tested_start))
    assert offset_key not in cfg.keys(cfg.control_start) and cfg.exception_key in cfg.keys(cfg.control_start)


def test_bet_prices_marks_lowered_exception_and_other_members():
    cfg = CHAIN_PLAYS["chainZodiac3Hit"]
    prices = lower.bet_prices(cfg, cfg.tested_start, PRICING["chainZodiac3Hit"], D("10.1661"))
    assert prices == {"dragon": D("12.2661"), "snake": D("10.1661"), "horse": D("10.2866")}


def test_plan_rejects_when_control_sub_layer_not_lower_than_main():
    plan, text = lower.plan_offset(dict(odds=5, minOdds=3, subOdds=6, subMinOdds=2))
    assert plan is None and "不低於主層" in text


def test_plan_rejects_when_sub_layer_hits_sub_minimum():
    plan, text = lower.plan_offset(dict(odds=10, minOdds=5, subOdds=8, subMinOdds=8))
    assert plan is None and "觸到副最低" in text


@pytest.mark.parametrize("current, other", [("aaa111-through-aaa010", "bbb111-through-bbb010"),
                                            ("bbb111-through-bbb010", "aaa111-through-aaa010")])
def test_other_chain_lock_is_the_opposite_chain(monkeypatch, current, other):
    monkeypatch.setattr(lower, "chain_lock_name", lambda: current)
    assert lower.other_chain_lock() == other


def test_other_chain_lock_rejects_unknown_chain(monkeypatch):
    monkeypatch.setattr(lower, "chain_lock_name", lambda: "ccc111-through-ccc010")
    with pytest.raises(AssertionError, match="未知的帳號鏈鎖"):
        lower.other_chain_lock()


def test_default_chain_lock_name_is_listed():
    assert config_loader.chain_lock_name() in lower.CHAIN_LOCKS


# ---------------------------------------------------------------- 流程：調低→下注→加回（假盤面，不連線）

import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from xzh_qa.odds_gap_run_state import ChainBusy  # noqa: E402


class FakeBoard:
    """假的公司即时盘面：記住各成員本期賠率與目前步進值；按減／加號就依步進值變動被點的成員。"""

    def __init__(self, play, step="0.005", plus_works=True):
        self.cfg = CHAIN_PLAYS[play]
        self.base = D(str(PRICING[play]["odds"]))
        keys = set(self.cfg.keys(self.cfg.tested_start)) | set(self.cfg.keys(self.cfg.control_start))
        self.odds = {k: self.base for k in keys}
        # 真實盤面：副標籤成員（马／0尾）的 odds 欄本來就顯示副賠率（2026-10-06 首次實跑量到），不是主賠率
        self.odds[self.cfg.exception_key] = D(str(PRICING[play]["subOdds"]))
        self.initial = dict(self.odds)
        self.step, self.plus_works, self.log = D(step), plus_works, []

    def install(self, monkeypatch):
        label_to_key = {label: key for label, key in lower.OFFSET_MEMBER.values()}
        monkeypatch.setattr(lower, "board_rows", lambda top, issue, cfg: {
            k: {"odds": str(v), "subOdds": None, "hasManualOffset": v != self.initial[k]} for k, v in self.odds.items()})
        monkeypatch.setattr(lower, "read_step", lambda page: self.step)
        monkeypatch.setattr(lower, "ensure_step", lambda page, step: setattr(self, "step", D(str(step))))
        monkeypatch.setattr(lower, "open_chain_board", lambda page, tab: self.log.append(("open", tab)))
        monkeypatch.setattr(lower, "_issue", lambda top: {"gameId": "bingo6", "issueNumber": 1, "isBettable": True})
        monkeypatch.setattr(lower, "_wait_fresh_issue", lambda *a, **k: {"issueNumber": 1})

        def click(page, direction, play_label, member):
            self.log.append((direction, str(self.step)))
            if direction == "plus" and not self.plus_works:
                return
            key = label_to_key[member]
            self.odds[key] += -self.step if direction == "minus" else self.step
        monkeypatch.setattr(lower, "_click_member", click)


class FakeRun:
    def __init__(self, busy=False):
        self.busy, self.released = busy, False

    @contextmanager
    def chain_lock(self, name, timeout=0.0):
        if self.busy:
            raise ChainBusy(f"帳號鏈 {name} 已被占用")
        try:
            yield
        finally:
            self.released = True


def _call(play, monkeypatch, run, place_bet):
    monkeypatch.setattr(lower, "_place_bet", place_bet)
    design = lower.design_play(play, PRICING[play], with_gap=False)
    data = {"offsets": {}, "blocked": [], "play_errors": [], "attempts": []}
    top = SimpleNamespace(page=object(), recover=None, observed={})
    lower._play_with_offset(play, design, PRICING[play], top, object(), object(), {}, run, "bbb111-through-bbb010",
                            data, SimpleNamespace(save=lambda: None),
                            {"company": time.monotonic(), "player": time.monotonic()}, {"value": None}, None)
    return design, data


def test_offset_is_restored_even_if_a_bet_fails(monkeypatch):
    board, run = FakeBoard("chainTail2Miss"), FakeRun()
    board.install(monkeypatch)
    seen = []

    def place_bet(p, name, *args):
        seen.append(board.odds["1"])
        raise RuntimeError("前台送出逾時")
    design, data = _call("chainTail2Miss", monkeypatch, run, place_bet)
    assert seen == [design["plan"]["offset_price"]]                     # 下注當下 1尾 已調低到計畫價
    assert board.odds["1"] == board.base and board.step == D("0.005")   # 加回原賠率、步進值改回原值
    assert data["play_errors"] and "前台送出逾時" in data["play_errors"][0]["error"]
    assert data["offsets"]["chainTail2Miss"]["restored"] is True and run.released


def test_other_chain_busy_blocks_play_without_touching_board(monkeypatch):
    board = FakeBoard("chainZodiac3Hit")
    board.install(monkeypatch)
    _, data = _call("chainZodiac3Hit", monkeypatch, FakeRun(busy=True), lambda *a: pytest.fail("不得下注"))
    assert data["blocked"][0]["play"] == "chainZodiac3Hit" and "鎖" in data["blocked"][0]["reason"]
    assert board.log == [] and board.odds == board.initial


def test_board_already_adjusted_by_someone_else_is_blocked(monkeypatch):
    board, run = FakeBoard("chainZodiac3Hit"), FakeRun()
    board.odds["goat"] -= D("0.05")
    board.install(monkeypatch)
    _, data = _call("chainZodiac3Hit", monkeypatch, run, lambda *a: pytest.fail("不得下注"))
    assert "已有其他偏移" in data["blocked"][0]["reason"]
    assert [x for x in board.log if x[0] in ("minus", "plus")] == [] and run.released


def test_sub_label_member_shown_at_sub_odds_is_not_mistaken_for_an_offset(monkeypatch):
    """回歸：首次實跑把盤面上顯示副賠率的副標籤成員（马）誤判為「已有其他偏移」，全數受阻、0 注。"""
    board, run = FakeBoard("chainZodiac3Hit"), FakeRun()
    assert board.odds["horse"] == D("10.2866") != board.base
    board.install(monkeypatch)
    seen = []
    design, data = _call("chainZodiac3Hit", monkeypatch, run, lambda p, name, *a: seen.append((name, board.odds["snake"])))
    assert data["blocked"] == [] and [n for n, _ in seen] == ["tested", "control"]
    assert all(price == design["plan"]["offset_price"] for _, price in seen)
    assert board.odds == board.initial and run.released


def test_sub_label_member_not_at_sub_odds_is_blocked(monkeypatch):
    board, run = FakeBoard("chainZodiac3Hit"), FakeRun()
    board.odds["horse"] = board.base                         # 副標籤成員被改成主賠率＝別人動過
    board.install(monkeypatch)
    _, data = _call("chainZodiac3Hit", monkeypatch, run, lambda *a: pytest.fail("不得下注"))
    assert "已有其他偏移" in data["blocked"][0]["reason"] and "horse" in data["blocked"][0]["reason"]
    assert [x for x in board.log if x[0] in ("minus", "plus")] == []


def test_restore_failure_stops_the_batch_and_releases_lock(monkeypatch):
    board, run = FakeBoard("chainTail2Miss", plus_works=False), FakeRun()
    board.install(monkeypatch)
    ticks = iter(range(10 ** 6))  # 讀回輪詢的 8 秒逾時改用假時鐘，不真的等
    monkeypatch.setattr(lower, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + 2 * next(ticks),
                                                       sleep=lambda s: None))
    with pytest.raises(AssertionError):
        _call("chainTail2Miss", monkeypatch, run, lambda *a: None)
    assert board.odds["1"] != board.base and run.released
