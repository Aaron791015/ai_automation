# -*- coding: utf-8 -*-
"""T79：其餘連肖／連尾玩法（三～五肖连中、二～四尾连不中）比照 B112～B115 的差分設計、期望價與一批多玩法下注流程。

用途：二肖连中已有 B112～B115（`odds_gap_chain_winner.run_chain_winner`，一次只處理一個玩法）。
      本模組把「玩法」參數化，並讓一個情境一次寫入全部適用玩法的十層差分、同一期依序下注，
      避免每個（玩法×情境）都重做十層保存與還原。三個情境（不含要動公司盤面偏移的 B112／B106 型，
      其餘玩法的這兩型由 `odds_gap_chain_lower` 的 B120／B121 處理）：
        flat   十層主 −0.01／副 −0.02、不偏移（B113 型）
        tie    主副扣完差分後同價，同價取主層（B114 型；四尾不適用，見 `NOT_APPLICABLE`）
        floor  主層觸到最低賠率、副層仍較低（B115 型）

使用方式（由 `tests/xzh/test_odds_gap_betting_regression.py` 的 B116～B118 呼叫）：
    run_chain_scenario(browser, gap_context, run, ledger_path, "flat", case="B116")
    離線可用 `scenario_layers`／`expected_price` 算差分設計與期望價（不連線）。

前置條件：
- 已取得鏈鎖（pytest 的 autouse fixture 會取）；注數／金額已經 Aaron 批准；公司 OddsSetting 以開工當下為準。
- 被測行為（下注）走會員前台 UI；差分設定也走 UI；API 只用於讀取驗證。
- 帳本在送出前落檔，同一批不可重送；結束一律依 `guarded_gaps` 由上往下還原本批寫過的格。
"""
from __future__ import annotations

import json
import re
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import allure

from xzh_qa.config_loader import player_credentials, qat
from xzh_qa.odds_gap_chain_winner import (
    GAME, GAME_NAME, ChainWinnerLedger, board_member_price, chain_frozen_odds, gap_columns_to_write,
    _current_issue, _wait_fresh_issue)
from xzh_qa.odds_gap_client import ReadOnlyApiError
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_regression import client_quote_matches, read_bets, reports, select_unique
from xzh_qa.odds_gap_safety import (guarded_gaps, is_null_to_zero, registered_null_to_zero,
                                    restore_equal, strict_gap_values)
from xzh_qa.pages.player_bet_page import PlayerBetPage

ZODIAC_KEYS = ("rat", "ox", "tiger", "rabbit", "dragon", "snake", "horse", "goat", "monkey", "rooster", "dog", "pig")
ZODIAC_NAMES = ("鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪")
AMOUNT = "2"
SCENARIOS = ("flat", "tie", "floor", "zero")  # zero＝十層皆 0（不寫差分）：只用於探針，確認候選價在無差分時的行為
TICK = Decimal("0.0001")


@dataclass(frozen=True)
class ChainPlay:
    """一個連肖／連尾玩法的下注與盤面設定。`tested_start`／`control_start` 是前台連續選取的起點。"""

    play: str            # playTypeId
    label: str           # 前台子項（也是設定頁玩法名）
    category: str        # `place_combo_target_bet` 的分類：连肖／连尾
    board_category: str  # `/api/LiveTrading` 的 category
    kind: str            # zodiac／tail
    count: int
    exception_label: str  # 副標籤（畫面文字）
    exception_key: str    # 副標籤成員的 selectionKey
    tested_start: int
    control_start: int

    def keys(self, start: int) -> tuple:
        if self.kind == "zodiac":
            return tuple(ZODIAC_KEYS[(start + i) % 12] for i in range(self.count))
        return tuple(str((start + i) % 10) for i in range(self.count))

    def names(self, start: int) -> tuple:
        if self.kind == "zodiac":
            return tuple(ZODIAC_NAMES[(start + i) % 12] for i in range(self.count))
        return tuple(f"{(start + i) % 10}尾" for i in range(self.count))

    @property
    def bets(self) -> tuple:
        """（名稱, 前台起點）：受測＝含副標籤成員且含「蛇／1尾」一側，對照＝含副標籤成員、由「马／0尾」起算或前移。"""
        return (("tested", self.tested_start), ("control", self.control_start))


#: T79 列的下注組合：連肖受測以「…蛇,马」結尾、對照「马,羊…」；連尾受測含「0尾,1尾」、對照「…9,0」。
CHAIN_PLAYS = {p.play: p for p in (
    ChainPlay("chainZodiac3Hit", "三肖连中", "连肖", "ChainZodiac", "zodiac", 3, "马", "horse", 4, 6),
    ChainPlay("chainZodiac4Hit", "四肖连中", "连肖", "ChainZodiac", "zodiac", 4, "马", "horse", 3, 6),
    ChainPlay("chainZodiac5Hit", "五肖连中", "连肖", "ChainZodiac", "zodiac", 5, "马", "horse", 2, 6),
    ChainPlay("chainTail2Miss", "二尾连不中", "连尾", "ChainTail", "tail", 2, "0", "0", 0, 9),
    ChainPlay("chainTail3Miss", "三尾连不中", "连尾", "ChainTail", "tail", 3, "0", "0", 9, 8),
    ChainPlay("chainTail4Miss", "四尾连不中", "连尾", "ChainTail", "tail", 4, "0", "0", 8, 7),
)}

#: 「tie」情境：副差分合計（主差分合計由 `主基準 − (副基準＋副合計)` 反算）。三尾副基準恰等於主最低，副合計取 0。
TIE_SUB_TOTAL = {
    "chainZodiac3Hit": Decimal("-0.20"), "chainZodiac4Hit": Decimal("-0.20"), "chainZodiac5Hit": Decimal("-0.20"),
    "chainTail2Miss": Decimal("-0.10"), "chainTail3Miss": Decimal("0"),
}
#: 四尾連不中：主最低（43.4572）高於副基準（41.6465），不偏移時主層最終價恆≥主最低＞副層價，不可能同價。
NOT_APPLICABLE = {("tie", "chainTail4Miss"): "主最低高於副基準，主層價恆大於副層價，不可能同價"}
#: 「floor」情境：（主差分合計, 副差分合計），使主層觸到最低賠率、副層未觸底且較低。
FLOOR_TOTALS = {
    "chainZodiac3Hit": (Decimal("-2.80"), Decimal("-1.00")), "chainZodiac4Hit": (Decimal("-7.50"), Decimal("-3.00")),
    "chainZodiac5Hit": (Decimal("-25.80"), Decimal("-10.00")), "chainTail2Miss": (Decimal("-1.40"), Decimal("-0.50")),
    "chainTail3Miss": (Decimal("-3.50"), Decimal("-1.20")), "chainTail4Miss": (Decimal("-11.50"), Decimal("-4.00")),
}


def applicable_plays(scenario: str, plays=None) -> list:
    assert scenario in SCENARIOS, f"未知情境 {scenario}"
    return [p for p in CHAIN_PLAYS if (plays is None or p in plays) and (scenario, p) not in NOT_APPLICABLE]


def split_total(total, layers: int = 10) -> list:
    """把（負）合計平均拆到各層，四位小數不整除時把 0.0001 分給前幾層；各層和精確等於合計。"""
    total = dec(total)
    assert total <= 0, "差分合計只能為 0 或負數"
    units = int((-total / TICK).to_integral_value())
    assert dec(units) * TICK == -total, f"合計 {total} 超過四位小數"
    base, extra = divmod(units, layers)
    return [-(dec(base + (1 if i < extra else 0)) * TICK) for i in range(layers)]


def scenario_totals(scenario: str, play: str, pricing: dict) -> tuple:
    """回傳（主差分合計, 副差分合計）；不適用的組合丟 `KeyError`。"""
    odds, sub = dec(pricing["odds"]), dec(pricing["subOdds"])
    if scenario == "zero":
        return Decimal(0), Decimal(0)
    if scenario == "flat":
        return Decimal("-0.10"), Decimal("-0.20")
    if scenario == "tie":
        assert (scenario, play) not in NOT_APPLICABLE, NOT_APPLICABLE[(scenario, play)]
        sub_total = TIE_SUB_TOTAL[play]
        return -(odds - (sub + sub_total)), sub_total
    return FLOOR_TOTALS[play]


def scenario_layers(scenario: str, play: str, pricing: dict) -> list:
    """十層（aaa111→aaa010）的（主差分, 副差分）。"""
    main_total, sub_total = scenario_totals(scenario, play, pricing)
    if scenario == "flat":
        return [(Decimal("-0.01"), Decimal("-0.02"))] * 10
    return list(zip(split_total(main_total), split_total(sub_total)))


def candidate_prices(pricing: dict, main_total, sub_total) -> dict:
    """主層／副層候選的最終價（先扣差分再以各自最低截斷）；供設計驗證與報告。"""
    main = max(dec(pricing["minOdds"]), dec(pricing["odds"]) + dec(main_total))
    sub_min = dec(pricing["subMinOdds"]) if pricing.get("subMinOdds") is not None else dec(pricing["minOdds"])
    sub = max(sub_min, dec(pricing["subOdds"]) + dec(sub_total))
    return {"main": main, "sub": sub}


def expected_price(cfg: ChainPlay, pricing: dict, member_prices: dict, main_total, sub_total) -> dict:
    """含副標籤成員的一注：依 `chain_frozen_odds`（先扣再比、同價取主層、含例外成員的有效下限）算成交價與層別。"""
    min_main = dec(pricing["minOdds"])
    min_sub = dec(pricing["subMinOdds"]) if pricing.get("subMinOdds") is not None else None
    return chain_frozen_odds(member_prices, {cfg.exception_key}, main_total, sub_total, min_main, min_sub)


def design_row(scenario: str, play: str, pricing: dict) -> dict:
    """某玩法在某情境的完整設計：各層差分、合計、兩層候選價與預期成交價（含副標籤成員的注）。"""
    cfg = CHAIN_PLAYS[play]
    main_total, sub_total = scenario_totals(scenario, play, pricing)
    layers = scenario_layers(scenario, play, pricing)
    assert sum((m for m, _ in layers), Decimal(0)) == main_total and sum((s for _, s in layers), Decimal(0)) == sub_total
    cand = candidate_prices(pricing, main_total, sub_total)
    exp = expected_price(cfg, pricing, {"__main__": dec(pricing["odds"]), cfg.exception_key: dec(pricing["subOdds"])},
                         main_total, sub_total)
    tier = "main" if cand["main"] <= cand["sub"] else "sub"
    assert exp["expected"] == min(cand["main"], cand["sub"]) and exp["tier"] == tier
    return {"play": play, "scenario": scenario, "main_total": main_total, "sub_total": sub_total, "layers": layers,
            "candidates": cand, "expected": exp["expected"], "tier": tier,
            "main_floored": dec(pricing["odds"]) + main_total < dec(pricing["minOdds"])}


# ---------------------------------------------------------------- 即時盤面與注單

def _client_get(ctx, path, params):
    """公司 client 的唯讀 GET；token 逾時（401／403）時由 `ctx.recover` 重新登入同一身分再讀一次。"""
    latest = ctx.observed.get("headers", {}).get("Authorization")
    if latest:
        ctx.client.headers["Authorization"] = latest
    try:
        return ctx.client._get(path, params)
    except ReadOnlyApiError as exc:
        if exc.status not in (401, 403) or not ctx.recover:
            raise
        ctx.recover()
        ctx.client.headers = dict(ctx.observed["headers"])
        return ctx.client._get(path, params)


def board_rows(ctx, issue_number, cfg: ChainPlay) -> dict:
    body = _client_get(ctx, "/api/LiveTrading", {"gameId": GAME, "issueNumber": issue_number, "category": cfg.board_category})
    return {s["selectionKey"]: s for s in body.get("selections", []) if s["playTypeId"] == cfg.play}


def baseline_diff(contexts, baseline: dict, games=("bingo6", "ukLucky7", "markSix")) -> tuple:
    """十層×三彩種×設定列×主副兩欄與基準逐格比對（含 NULL 與 0 的差別；唯一例外是已登記的副欄 NULL→0，
    見 odds_gap_safety.NULL_TO_ZERO_REGISTRY）；回傳（格數, 差異清單）。"""
    allowed = registered_null_to_zero()
    total, diffs = 0, []
    for n, level in enumerate(baseline["levels"]):
        c = contexts[n]
        for g in games:
            rows = c.api_rows(g)
            base = {r["playTypeId"]: r for r in level["games"][g]}
            assert [r["playTypeId"] for r in rows] == [r["playTypeId"] for r in level["games"][g]], "玩法順序與基準不同"
            for r in rows:
                for f in ("oddsGap", "subOddsGap"):
                    total += 1
                    a, b = r[f], base[r["playTypeId"]][f]
                    if (a is None) != (b is None) or (a is not None and dec(a) != dec(b)):
                        if is_null_to_zero(f, b, a) and (level["account"], g, r["playTypeId"], f) in allowed:
                            continue
                        diffs.append({"account": level["account"], "game": g, "play": r["playTypeId"], "field": f,
                                      "baseline": b, "now": a})
    return total, diffs


def _bet_id_from(text, message):
    """POST /api/Bets 成功回應本文就是內部注單 ID；取不到時才從回報訊息「注單#N」取。"""
    if text and re.fullmatch(r"\s*\d+\s*", text):
        return text.strip()
    match = re.search(r"注單#(\d+)", message or "")
    return match.group(1) if match else None


def _selection_tokens(selection) -> frozenset:
    """把「dragon,snake」「龙,蛇」「0尾,1尾」等寫法一律轉成 selectionKey 集合，供配對報表注單。"""
    by_name = dict(zip(ZODIAC_NAMES, ZODIAC_KEYS))
    tokens = set()
    for token in str(selection).replace("，", ",").split(","):
        token = token.strip()
        token = by_name.get(token, token[:-1] if token.endswith("尾") else token)
        tokens.add(token)
    return frozenset(tokens)


def match_record(rows, attempt):
    """依玩法、期號與選號集合在報表注單中找唯一一筆；找不到或不唯一就丟錯（不猜）。"""
    want = frozenset(attempt["keys"])
    found = [r for r in rows if r["playTypeId"] == attempt["play"] and str(r["issueNumber"]) == str(attempt["issue"])
             and _selection_tokens(r["selection"]) == want]
    assert len(found) == 1, f"{attempt['play']} 期 {attempt['issue']} 選號 {sorted(want)} 配對到 {len(found)} 筆注單"
    return found[0]


def run_chain_scenario(browser, gap_context, run, ledger_path, scenario, case, plays=None, bets=None,
                       baseline_path=None, progress=None):
    """一個情境：寫入適用玩法的十層差分 → 同一期依序下注（每玩法兩注各 2 元）→ 由上往下還原 → 全表比對。

    `plays`：只做這些玩法（續跑用）；`bets`：只做這些注名（tested／control）；`baseline_path`：全表基準 JSON。
    `progress(event: dict)`：每注完成時的回呼（供外部進度檔）。回傳帳本 dict；失敗在還原與核對完成後才 assert。
    """
    plays = applicable_plays(scenario, plays)
    names = [b for b in (bets or ("tested", "control"))]
    ledger = ChainWinnerLedger(ledger_path, bets=[(f"{p}:{n}",) for p in plays for n in names], offset=0, case=case)
    data = ledger.data
    data.update(scenario=scenario, plays=plays, kind="chain-plays", not_applicable={f"{s}:{p}": why for (s, p), why in NOT_APPLICABLE.items() if s == scenario})
    day = datetime.now().astimezone().date().isoformat()
    contexts = [gap_context(i, via="company") for i in range(10)]
    originals = [c.open(GAME) for c in contexts]
    member, top = contexts[9], contexts[0]
    client = member.reference_client
    pricing_all = client.odds_setting(GAME)
    designs = {}
    for p in plays:
        row = pricing_all[p]
        assert row.get("subOddsLabel") == CHAIN_PLAYS[p].exception_label, f"{p} 副標籤已變（{row.get('subOddsLabel')}），需重新核對計畫"
        designs[p] = design_row(scenario, p, row)
    data.update(day=day, accounts=[{"account": c.account, "id": c.target_user_id} for c in contexts],
                pricing={p: pricing_all[p] for p in plays},
                design={p: {"main_total": str(d["main_total"]), "sub_total": str(d["sub_total"]),
                            "layers": [[str(m), str(s)] for m, s in d["layers"]],
                            "candidates": {k: str(v) for k, v in d["candidates"].items()},
                            "expected": str(d["expected"]), "tier": d["tier"], "main_floored": d["main_floored"]}
                        for p, d in designs.items()},
                originals=originals)
    ledger.save()
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8")) if baseline_path else None
    if baseline:
        with allure.step("寫入前：十層三彩種全表與基準逐格比對，須 0 差異"):
            cells, diffs = baseline_diff(contexts, baseline)
            data["table_before"] = {"cells": cells, "diffs": diffs}
            ledger.save()
            assert not diffs, f"寫入前全表與基準有 {len(diffs)} 格差異，不動別人的值、停止本批：{diffs[:3]}"
    data["before_reports"] = reports(client, data["accounts"], day, set(plays))
    ledger.save()
    posts, active = [], {}
    results = []
    with ExitStack() as stack:
        # 反向進入守衛，使結束時由上（aaa111）往下（aaa010）還原
        transactions = [None] * 10
        for i in reversed(range(10)):
            transactions[i] = stack.enter_context(guarded_gaps(contexts[i], GAME, originals[i]))
        with allure.step("公司逐層保存本情境各玩法的十層主差分與副差分並讀回（已是目標值的欄不寫）"):
            for i, (c, tr) in enumerate(zip(contexts, transactions)):
                rows = c.open(GAME)
                index = {r["playTypeId"]: n for n, r in enumerate(rows)}
                wrote = False
                for p in plays:
                    main_i, sub_i = designs[p]["layers"][i]
                    for column, value in gap_columns_to_write(rows[index[p]], main_i, sub_i):
                        entered = c.setting.set_value(index[p], column, value)
                        assert entered == value
                        tr["expected"][(p, "subOddsGap" if column else "oddsGap")] = entered
                        wrote = True
                if wrote:
                    tr["attempted"] = True
                    assert c.setting.save()["status"] in (200, 204)
                    actual = strict_gap_values(c.api_rows(GAME))
                    assert all(actual[k] == v for k, v in tr["expected"].items()), f"{c.account} 保存後讀回不符"
                if progress:
                    progress({"step": f"寫入差分 {c.account} 完成"})
        phase_rows = [c.api_rows(GAME) for c in contexts]
        totals = {}
        for p in plays:
            chain_rows = [next(r for r in rows if r["playTypeId"] == p) for rows in phase_rows]
            assert all(r["isEffective"] for r in chain_rows), f"{p} 十層差分須皆生效"
            main_total = sum((dec(r["oddsGap"] or 0) for r in chain_rows), Decimal(0))
            sub_total = sum((dec(r["subOddsGap"] or 0) for r in chain_rows), Decimal(0))
            assert (main_total, sub_total) == (designs[p]["main_total"], designs[p]["sub_total"]), \
                f"{p} 讀回合計 {main_total}／{sub_total} ≠ 設計 {designs[p]['main_total']}／{designs[p]['sub_total']}"
            totals[p] = (main_total, sub_total)
        data.update(phase_rows=phase_rows, totals={p: [str(a), str(b)] for p, (a, b) in totals.items()})
        ledger.save()
        assert all(client.odds_setting(GAME)[p] == pricing_all[p] for p in plays), "寫入後公司基準／最低賠率異動，停止下注"
        with browser.new_context(viewport={"width": 1920, "height": 1080}) as front:
            page = front.new_page()
            page.set_default_timeout(20000)

            def on_request(req):
                if "/api/Bets" in req.url and req.method == "POST" and "active" in active:
                    try:
                        active["posts"].append({"payload": req.post_data_json, "at": datetime.now().astimezone().isoformat()})
                    except Exception:
                        active["posts"].append({"payload": None})

            def on_response(resp):
                if "/api/Bets" in resp.url and resp.request.method == "POST" and "active" in active and active["posts"]:
                    try:
                        text = resp.text()
                    except Exception:
                        text = ""
                    active["posts"][-1].update(status=resp.status, response=text[:400])

            page.on("request", on_request)
            page.on("response", on_response)
            player = PlayerBetPage(page)
            player.login(qat()["frontend_url"], *player_credentials())
            player.select_game(GAME_NAME)
            try:
                with allure.step("會員前台同一期依序下各玩法的兩注，記錄送出價並讀回正式注單的凍結賠率"):
                    issue = _wait_fresh_issue(client, top.page, min_seconds=140, observed=top.observed)
                    data["issue"] = issue["issueNumber"]
                    data["issue_snapshot"] = issue
                    ledger.save()
                    for p in plays:
                        cfg = CHAIN_PLAYS[p]
                        main_total, sub_total = totals[p]
                        for name, start in [b for b in cfg.bets if b[0] in names]:
                            current = _current_issue(client)
                            assert str(current["issueNumber"]) == str(issue["issueNumber"]) and current["isBettable"], \
                                "期別已切換或不可下注，停止本批（未送出的注請以續跑補下）"
                            keys, member_names = cfg.keys(start), cfg.names(start)
                            board = board_rows(top, issue["issueNumber"], cfg)
                            assert all(k in board for k in keys), f"{p} 盤面缺成員 {keys}"
                            prices = {k: board_member_price(board[k], k == cfg.exception_key, configured_sub=pricing_all[p]["subOdds"])
                                      for k in keys}
                            # 沒有手動偏移／調整：非副標籤成員的盤面價須等於公司基準，副標籤成員等於副基準
                            for k, v in prices.items():
                                want = dec(pricing_all[p]["subOdds"] if k == cfg.exception_key else pricing_all[p]["odds"])
                                assert v == want, f"{p} 成員 {k} 盤面價 {v} ≠ 公司基準 {want}（盤面有調整），停止本批"
                            exp = expected_price(cfg, pricing_all[p], prices, main_total, sub_total)
                            attempt = {"play": p, "bet": name, "label": cfg.label, "start": start, "members": list(member_names),
                                       "keys": list(keys), "selection": ",".join(keys), "issue": issue["issueNumber"],
                                       "member_prices": {k: str(v) for k, v in prices.items()}, "board": {k: board[k] for k in keys},
                                       "expected": {k: str(v) for k, v in exp.items()}, "amount": AMOUNT, "sent": True,
                                       "posts": []}
                            # 注單層的獨立驗算輸入（供結算核對 `check_settlement`）：勝出鏈的基準、各層差分、有效最低
                            win_tier = exp["tier"]
                            pr = pricing_all[p]
                            idx = 0 if win_tier == "main" else 1
                            attempt["source"] = {"baseOdds": str(pr["odds"] if win_tier == "main" else pr["subOdds"]), "selectionOverrides": []}
                            attempt["gaps"] = [str(designs[p]["layers"][n][idx]) for n in range(10)]
                            floor = dec(pr["minOdds"]) if win_tier == "main" else dec(pr["subMinOdds"] if pr.get("subMinOdds") is not None else pr["minOdds"])
                            attempt["minimum"] = str(min(floor, dec(attempt["source"]["baseOdds"])))
                            data["attempts"].append(attempt)
                            ledger.save()
                            active.clear()
                            active.update(active=True, posts=attempt["posts"])
                            try:
                                attempt["message"] = player.place_combo_target_bet(cfg.category, cfg.label, amount=AMOUNT, selection_offset=start)
                            except Exception as exc:  # 結果不明不重送：留下狀態，交由唯讀核對
                                attempt["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                                ledger.save()
                                raise
                            finally:
                                active.clear()
                            sent = next((x for x in reversed(attempt["posts"]) if x.get("status") in (200, 201)), None)
                            # POST /api/Bets 回應本文是內部注單 ID（短數字），不是報表的 serialNumber；serialNumber 於收尾依選號配對
                            attempt["betId"] = _bet_id_from(sent.get("response") if sent else None, attempt.get("message"))
                            item = ((sent or {}).get("payload") or {}).get("items", [{}])[0]
                            attempt["client_odds"] = item.get("clientOdds")
                            attempt["client_sub_odds"] = item.get("clientSubOdds")
                            attempt["payload_selection"] = item.get("selection")
                            ledger.save()
                            if progress:
                                progress({"step": f"{p}:{name} 已送出", "betId": attempt["betId"]})
            finally:
                _collect_records(data, top, member, day, ledger)
    # 守衛已於離開 with 時由上往下還原；再次核對與全表比對
    final = [c.api_rows(GAME) for c in contexts]
    data["restored"] = all(restore_equal(c.account, GAME, b, a) for c, a, b in zip(contexts, final, originals))
    if baseline:
        cells, diffs = baseline_diff(contexts, baseline)
        data["table_after"] = {"cells": cells, "diffs": diffs}
    ledger.save()
    run.dump("chain-plays.json", data)
    allure.attach(json.dumps(data, ensure_ascii=False, default=str), f"{case} 計畫／實際／還原", allure.attachment_type.JSON)
    failures, rows = judge(data["attempts"])
    allure.attach("\n".join(rows), f"{case} 逐注核對：玩法／選號／兩層候選價／預期／送出價／凍結價", allure.attachment_type.TEXT)
    if not data["restored"]:
        failures.append("十層差分未還原，停止後續操作")
    if baseline and data["table_after"]["diffs"]:
        failures.append(f"還原後全表與基準有 {len(data['table_after']['diffs'])} 格差異")
    data["failures"] = failures
    ledger.save()
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    return data


def _collect_records(data, top, member, day, ledger):
    """讀回正式注單的凍結賠率並掛到各注（中途失敗也要做，才看得到已送出的注）；讀取失敗記在帳本，不遮蓋原錯誤。"""
    try:
        rows_after = _read_bets_retry(top, member, day)
    except Exception as exc:
        data["records_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        ledger.save()
        return
    for a in data["attempts"]:
        if not a.get("betId"):
            continue
        try:
            record = match_record(rows_after, a)
            a["serialNumber"] = str(record["serialNumber"])
            a["record"] = record
            a["initial_record"] = record
        except Exception as exc:
            a["record_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    ledger.save()


def _read_bets_retry(top, member, day):
    """讀會員當日注單；先換新 token（必要時重新登入），結算時分頁總數變動就重讀（最多 3 次）。"""
    last = None
    for _ in range(3):
        try:
            _client_get(top, "/api/Issues/Current", {})
            return read_bets(top.client, member.target_user_id, day)
        except AssertionError as exc:
            last = exc
    raise last


def judge(attempts) -> tuple:
    """逐注核對：送出價、凍結價與獨立期望價；回傳（失敗清單, 逐注文字列）。"""
    failures, rows = [], []
    for a in attempts:
        exp = dec(a["expected"]["expected"])
        record = a.get("record")
        frozen = dec(record["odds"]) if record else None
        sent = a.get("client_odds")
        sent_ok = client_quote_matches(sent, exp) if sent is not None else False
        frozen_ok = frozen == exp if frozen is not None else False
        rows.append(f"{a['label']}／{a['bet']}／{'＋'.join(a['members'])}／成交層 {a['expected']['tier']}／預期 {exp}／送出 {sent}／凍結 {frozen}／"
                    f"{'符合' if sent_ok and frozen_ok else '不符'}／注單 {a.get('serialNumber')}")
        if not a.get("serialNumber") or record is None:
            failures.append(f"{a['label']}／{a['bet']}：沒有取得正式注單，無法核對凍結賠率")
            continue
        picked = a.get("payload_selection")
        if picked is None or sorted(str(picked).split(",")) != sorted(a["keys"]):
            failures.append(f"{a['label']}／{a['bet']}：送出的選號 {picked} 與計畫 {','.join(a['keys'])} 不同")
        if not sent_ok:
            failures.append(f"{a['label']}／{a['bet']}（{'＋'.join(a['members'])}）：送出價 {sent}，預期 {exp}（{a['expected']['tier']}層）")
        if not frozen_ok:
            failures.append(f"{a['label']}／{a['bet']}（{'＋'.join(a['members'])}）：凍結價 {frozen}，預期 {exp}（{a['expected']['tier']}層）")
    return failures, rows
