# -*- coding: utf-8 -*-
"""T61：連肖／連尾「主分支」（組合不含副標籤成員）追中獎樣本，核對派彩與九層賠率差金額。

用途：賓果連肖／連尾有副欄的 7 個玩法裡，主分支有中獎樣本的只有二肖连中；三～五肖连中與二～四尾连不中的主分支
      只有輸局。本模組寫入十層各層不同且皆非零、不觸底的差分，逐期對各玩法下「不含副標籤成員」的分散組合
      （連肖不含马、連尾不含 0，每注 2 元），預測某玩法有中獎就停該玩法，到停止時間／額度用完／全部玩法已中獎就停，
      由上往下還原。派彩與九層收益由 `scratchpad/t79-20261002/settle_t79.py` 以帳本唯讀核對（帳本格式同
      `odds_gap_chain_plays`）。

使用方式（由 `tests/xzh/test_odds_gap_betting_regression.py` 的 B119 呼叫）：
    run_chain_main_chase(browser, gap_context, run, ledger_path, "B119", plays, stop_at, max_bets, max_yuan)

前置條件：同 `odds_gap_chain_plays`（已取得鏈鎖、注數／金額經批准、不動公司層設定）。
"""
from __future__ import annotations

import itertools
import json
import random
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import allure

from xzh_qa.config_loader import player_credentials, qat
from xzh_qa.odds_gap_chain_plays import (
    AMOUNT, CHAIN_PLAYS, ZODIAC_KEYS, ZODIAC_NAMES, ChainPlay, _bet_id_from, _client_get, _collect_records,
    baseline_diff, board_rows, expected_price, judge)
from xzh_qa.odds_gap_chain_winner import (
    GAME, GAME_NAME, ChainWinnerLedger, _current_issue, _wait_fresh_issue, gap_columns_to_write)
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_regression import remaining_seconds, reports
from xzh_qa.odds_gap_safety import guarded_gaps, restore_equal, strict_gap_values
from xzh_qa.pages.player_bet_page import PlayerBetPage

#: 每期每玩法注數（依單注中獎率；先做前三個，時間允許再做後三個）
CHASE_PER_ISSUE = {"chainTail2Miss": 10, "chainZodiac3Hit": 10, "chainTail3Miss": 10,
                   "chainZodiac4Hit": 20, "chainTail4Miss": 20, "chainZodiac5Hit": 20}
#: 十層各層不同且皆非零、不觸底；主欄（−0.011～−0.020）與副欄（−0.022～−0.040）用不同值
CHASE_MAIN_LAYERS = [-(Decimal("0.010") + Decimal("0.001") * (i + 1)) for i in range(10)]
CHASE_SUB_LAYERS = [-(Decimal("0.020") + Decimal("0.002") * (i + 1)) for i in range(10)]


def names_for(cfg: ChainPlay, keys) -> tuple:
    """selectionKey 轉畫面名稱（生肖中文名／「N尾」）。"""
    if cfg.kind == "zodiac":
        return tuple(ZODIAC_NAMES[ZODIAC_KEYS.index(k)] for k in keys)
    return tuple(f"{k}尾" for k in keys)


def main_pool(cfg: ChainPlay) -> list:
    """不含副標籤成員的全部組合（selectionKey 元組，依成員順序排序）。"""
    members = [k for k in (ZODIAC_KEYS if cfg.kind == "zodiac" else tuple(str(d) for d in range(10))) if k != cfg.exception_key]
    return list(itertools.combinations(members, cfg.count))


def spread_combos(pool: list, n: int, seed: str, used=()) -> list:
    """從池中挑 n 組互不重複、盡量分散（兩兩重疊成員最少）的組合；`used` 為較早期數已選過的組合，同分時避開。"""
    rng = random.Random(seed)
    candidates = list(pool)
    rng.shuffle(candidates)
    chosen, taken = [], set(used)
    for _ in range(min(n, len(candidates))):
        best, best_score = None, None
        for combo in candidates:
            if combo in chosen:
                continue
            overlaps = [len(set(combo) & set(c)) for c in chosen] or [0]
            score = (max(overlaps), sum(overlaps), combo in taken)
            if best_score is None or score < best_score:
                best, best_score = combo, score
        chosen.append(best)
    return chosen


def win_of(play: str, keys, issue: dict) -> bool:
    """依開獎號碼判輸贏：連肖连中＝所選生肖全部出現在 7 個開獎號碼；連尾连不中＝所選尾數全部沒出現。"""
    draw = issue["drawNumbers"]
    if play.startswith("chainZodiac"):
        have = {ZODIAC_KEYS[(issue["yearZodiacIndex"] - (n - 1)) % 12] for n in draw}
        return all(k in have for k in keys)
    tails = {str(n % 10) for n in draw}
    return all(k not in tails for k in keys)


def place_custom_combo(player, cfg: ChainPlay, keys, amount: str) -> str:
    """前台任意組合下注（`place_combo_target_bet` 只能連續選號）：選分類與子項、逐一點成員、填金額、送出。"""
    import re
    player.clear_selection()
    player.select_combo_target(cfg.category, cfg.label)
    for name in names_for(cfg, keys):
        player.page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}(?:\s|$)")).click()
    player.page.get_by_role("spinbutton").last.fill(amount)
    player.page.wait_for_timeout(300)
    return player._confirm_bet(amount)


def chase_issue_results(top, issue_numbers) -> dict:
    """公司 API 讀已開獎期的號碼；回傳 {期號: issue dict}（尚未開獎的期不在內）。"""
    body = _client_get(top, "/api/Issues", {"gameId": GAME, "pageIndex": 1, "pageSize": 300})
    rows = body["items"] if isinstance(body, dict) else body
    want = {str(n) for n in issue_numbers}
    return {str(r["issueNumber"]): r for r in rows if str(r["issueNumber"]) in want and r.get("drawNumbers")}


class RecoveringClient:
    """公司 client 的唯讀代理：每次 GET 先換新 token，401／403 時由公司頁面重新登入同一身分再讀一次。

    長時間（超過約 10 分鐘）的下注迴圈若直接用原 client，token 逾時會回 401（2026-10-02 段 B 首跑實例）。
    `_wait_fresh_issue` 會對 client 設 headers 屬性，代理只需容納這個賦值。
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.headers = None

    def _get(self, path, params=None):
        return _client_get(self.ctx, path, params or {})


def remaining_issue_seconds(client, issue) -> float:
    """目前期別距離封盤的秒數（以公司 API 的即時狀態為準；已換期或不可下注回 0）。"""
    current = _current_issue(client)
    if str(current["issueNumber"]) != str(issue["issueNumber"]) or not current["isBettable"]:
        return 0.0
    return remaining_seconds(current)


def _mark_wins(data, top, placed_issues, wins):
    """把已開獎期的各注標上預測輸贏；某玩法第一次出現中獎就記入 wins（之後不再對該玩法下注）。"""
    done = chase_issue_results(top, placed_issues)
    for a in data["attempts"]:
        if str(a["issue"]) in done and "predicted_win" not in a and a.get("betId"):
            a["predicted_win"] = win_of(a["play"], a["keys"], done[str(a["issue"])])
            if a["predicted_win"] and a["play"] not in wins:
                wins[a["play"]] = {"issue": a["issue"], "selection": a["selection"], "betId": a.get("betId")}
    data["wins"] = wins


def run_chain_main_chase(browser, gap_context, run, ledger_path, case, plays, stop_at, max_bets, max_yuan,
                         per_issue=None, baseline_path=None, progress=None, skip_plays=()):
    """寫入十層非零差分 → 逐期對各玩法下「不含副標籤成員」的分散組合（每注 2 元）→ 預測某玩法有中獎即停該玩法
    → 到 `stop_at`、額度用完或全部玩法已有中獎就停 → 由上往下還原。回傳帳本；失敗在還原後才 assert。

    `plays`：本段要追的玩法；`skip_plays`：先前段落已中獎的玩法（不再下）；`stop_at`：datetime，之後不再開始新一期。
    """
    plays = [p for p in plays if p in CHASE_PER_ISSUE and p not in skip_plays]
    per_issue = {**CHASE_PER_ISSUE, **(per_issue or {})}
    ledger = ChainWinnerLedger(ledger_path, bets=[("chase",)], offset=0, case=case)
    data = ledger.data
    data.update(scenario="chase", kind="chain-main-chase", plays=plays, max_bets_cap=max_bets, max_yuan_cap=str(max_yuan),
                stop_at=stop_at.isoformat(), per_issue={p: per_issue[p] for p in plays}, skipped_won=list(skip_plays))
    day = datetime.now().astimezone().date().isoformat()
    contexts = [gap_context(i, via="company") for i in range(10)]
    originals = [c.open(GAME) for c in contexts]
    member, top = contexts[9], contexts[0]
    client = member.reference_client
    pricing_all = client.odds_setting(GAME)
    live = RecoveringClient(top)  # 下注迴圈裡所有的即時期別讀取都走代理（token 逾時自動重新登入）
    for p in plays:
        assert pricing_all[p].get("subOddsLabel") == CHAIN_PLAYS[p].exception_label, f"{p} 副標籤已變"
    main_total, sub_total = sum(CHASE_MAIN_LAYERS, Decimal(0)), sum(CHASE_SUB_LAYERS, Decimal(0))
    for p in plays:  # 設計須不觸底（主價最終＝基準＋合計）
        assert dec(pricing_all[p]["odds"]) + main_total > dec(pricing_all[p]["minOdds"]), f"{p} 主差分觸底，設計失效"
    data.update(day=day, accounts=[{"account": c.account, "id": c.target_user_id} for c in contexts],
                pricing={p: pricing_all[p] for p in plays}, originals=originals,
                design={"main_layers": [str(x) for x in CHASE_MAIN_LAYERS], "sub_layers": [str(x) for x in CHASE_SUB_LAYERS],
                        "main_total": str(main_total), "sub_total": str(sub_total)})
    ledger.save()
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8")) if baseline_path else None
    if baseline:
        cells, diffs = baseline_diff(contexts, baseline)
        data["table_before"] = {"cells": cells, "diffs": diffs}
        ledger.save()
        assert not diffs, f"寫入前全表與基準有 {len(diffs)} 格差異，不動別人的值、停止本段：{diffs[:3]}"
    data["before_reports"] = reports(client, data["accounts"], day, set(plays))
    ledger.save()
    layers = list(zip(CHASE_MAIN_LAYERS, CHASE_SUB_LAYERS))
    wins, errors = dict(), 0
    active_post = {}
    used = {p: set() for p in plays}
    placed_issues = []
    with ExitStack() as stack:
        transactions = [None] * 10
        for i in reversed(range(10)):  # 反向進入守衛，結束時由上（aaa111）往下還原
            transactions[i] = stack.enter_context(guarded_gaps(contexts[i], GAME, originals[i]))
        with allure.step("公司逐層保存各玩法十層各層不同的主差分與副差分並讀回（已是目標值的欄不寫）"):
            for i, (c, tr) in enumerate(zip(contexts, transactions)):
                rows = c.open(GAME)
                index = {r["playTypeId"]: n for n, r in enumerate(rows)}
                wrote = False
                for p in plays:
                    for column, value in gap_columns_to_write(rows[index[p]], *layers[i]):
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
        for p in plays:
            chain_rows = [next(r for r in rows if r["playTypeId"] == p) for rows in phase_rows]
            assert all(r["isEffective"] for r in chain_rows)
            got_main = sum((dec(r["oddsGap"] or 0) for r in chain_rows), Decimal(0))
            got_sub = sum((dec(r["subOddsGap"] or 0) for r in chain_rows), Decimal(0))
            assert (got_main, got_sub) == (main_total, sub_total), f"{p} 讀回合計 {got_main}／{got_sub}"
        data["phase_rows"] = phase_rows
        ledger.save()
        with browser.new_context(viewport={"width": 1920, "height": 1080}) as front:
            page = front.new_page()
            page.set_default_timeout(20000)

            def on_request(req):
                if "/api/Bets" in req.url and req.method == "POST" and "posts" in active_post:
                    try:
                        active_post["posts"].append({"payload": req.post_data_json, "at": datetime.now().astimezone().isoformat()})
                    except Exception:
                        active_post["posts"].append({"payload": None})

            def on_response(resp):
                if "/api/Bets" in resp.url and resp.request.method == "POST" and active_post.get("posts"):
                    try:
                        text = resp.text()
                    except Exception:
                        text = ""
                    active_post["posts"][-1].update(status=resp.status, response=text[:400])

            page.on("request", on_request)
            page.on("response", on_response)
            player = PlayerBetPage(page)
            player.login(qat()["frontend_url"], *player_credentials())
            player.select_game(GAME_NAME)
            sent_bets, sent_yuan = 0, Decimal(0)
            try:
                with allure.step("會員前台逐期對各玩法下不含副標籤成員的分散組合，記錄送出價並讀回注單；有中獎的玩法即停"):
                    while True:
                        todo = [p for p in plays if p not in wins]
                        if not todo or datetime.now().astimezone() >= stop_at or sent_bets >= max_bets or sent_yuan >= dec(max_yuan):
                            data["stop_reason"] = ("全部玩法已有中獎" if not todo else "到停止時間" if datetime.now().astimezone() >= stop_at else "額度用完")
                            break
                        need = min(200, int(30 + 4.5 * max(sum(per_issue[p] for p in todo), 50)))  # 這一期預計要下的注數×約 4.5 秒；超過封盤的注會自動略過
                        issue = _wait_fresh_issue(live, top.page, min_seconds=need, observed=top.observed, timeout=600)
                        if datetime.now().astimezone() >= stop_at:
                            data["stop_reason"] = "到停止時間（等新期後）"
                            break
                        if placed_issues and str(issue["issueNumber"]) == str(placed_issues[-1]):
                            top.page.wait_for_timeout(4000)  # 這一期已下過：一期只下一輪，等下一期（避免同期重複下注吃掉額度）
                            continue
                        if placed_issues:  # 上一期的開獎結果要等到才能決定哪些玩法已中獎、不再下（最多等 40 秒）
                            for _ in range(10):
                                if chase_issue_results(top, [placed_issues[-1]]):
                                    break
                                top.page.wait_for_timeout(4000)
                        _mark_wins(data, top, placed_issues, wins)  # 先評估之前各期，有中獎的玩法不再下
                        ledger.save()
                        todo = [p for p in plays if p not in wins]
                        if not todo:
                            data["stop_reason"] = "全部玩法已有中獎"
                            break
                        data.setdefault("issues", []).append(issue["issueNumber"])
                        placed_issues.append(issue["issueNumber"])
                        shift = (len(placed_issues) - 1) % len(todo)
                        for p in todo[shift:] + todo[:shift]:  # 每期輪流從不同玩法開始，避免後面的玩法被餓死
                            cfg, pr = CHAIN_PLAYS[p], pricing_all[p]
                            board = board_rows(top, issue["issueNumber"], cfg)
                            assert all(k in board and dec(board[k]["odds"]) == dec(pr["odds"]) and not board[k].get("hasManualOffset")
                                       for k in board), f"{p} 盤面有調整或缺列，停止該段"
                            # 剩下的玩法變少時，把每期可下的約 50 注窗口平均分給它們（至少維持原設定的每期注數）
                            n_play = max(per_issue[p], 50 // len(todo))
                            combos = spread_combos(main_pool(cfg), n_play, f"{p}-{issue['issueNumber']}", used[p])
                            for n, keys in enumerate(combos, 1):
                                if (remaining_issue_seconds(live, issue) < 25 or sent_bets >= max_bets
                                        or sent_yuan + dec(AMOUNT) > dec(max_yuan)):
                                    break
                                prices = {k: dec(pr["odds"]) for k in keys}
                                exp = expected_price(cfg, pr, prices, main_total, sub_total)
                                assert exp["tier"] == "main" and cfg.exception_key not in keys
                                attempt = {"play": p, "bet": f"i{len(placed_issues)}-{n}", "label": cfg.label,
                                           "members": list(names_for(cfg, keys)), "keys": list(keys), "selection": ",".join(keys),
                                           "issue": issue["issueNumber"], "member_prices": {k: str(v) for k, v in prices.items()},
                                           "expected": {k: str(v) for k, v in exp.items()}, "amount": AMOUNT, "sent": True, "posts": [],
                                           "source": {"baseOdds": str(pr["odds"]), "selectionOverrides": []},
                                           "gaps": [str(x) for x in CHASE_MAIN_LAYERS],
                                           "minimum": str(min(dec(pr["minOdds"]), dec(pr["odds"])))}
                                data["attempts"].append(attempt)
                                ledger.save()
                                active_post.clear()
                                active_post["posts"] = attempt["posts"]
                                try:
                                    attempt["message"] = place_custom_combo(player, cfg, keys, AMOUNT)
                                    errors = 0
                                except Exception as exc:
                                    attempt["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                                    errors += 1
                                    ledger.save()
                                    if errors >= 3:
                                        raise
                                finally:
                                    active_post.clear()
                                sent = next((x for x in reversed(attempt["posts"]) if x.get("status") in (200, 201)), None)
                                attempt["betId"] = _bet_id_from(sent.get("response") if sent else None, attempt.get("message"))
                                item = ((sent or {}).get("payload") or {}).get("items", [{}])[0]
                                attempt["client_odds"] = item.get("clientOdds")
                                attempt["client_sub_odds"] = item.get("clientSubOdds")
                                attempt["payload_selection"] = item.get("selection")
                                if attempt["betId"]:
                                    sent_bets += 1
                                    sent_yuan += dec(AMOUNT)
                                    used[p].add(keys)
                                ledger.save()
                                if progress and attempt["betId"]:
                                    progress({"step": f"{p}:{attempt['bet']} 已送出", "betId": attempt["betId"], "total_bets": sent_bets})
                    data["sent_bets"], data["sent_yuan"] = sent_bets, str(sent_yuan)
            finally:
                _collect_records(data, top, member, day, ledger)
                try:
                    _mark_wins(data, top, placed_issues, wins)
                except Exception as exc:
                    data["results_error"] = str(exc)[:200]
                ledger.save()
    final = [c.api_rows(GAME) for c in contexts]
    data["restored"] = all(restore_equal(c.account, GAME, b, a) for c, a, b in zip(contexts, final, originals))
    if baseline:
        cells, diffs = baseline_diff(contexts, baseline)
        data["table_after"] = {"cells": cells, "diffs": diffs}
    ledger.save()
    run.dump("chain-main-chase.json", data)
    allure.attach(json.dumps({k: v for k, v in data.items() if k not in ("phase_rows", "originals", "before_reports")},
                             ensure_ascii=False, default=str), f"{case} 計畫／實際／還原", allure.attachment_type.JSON)
    failures, rows = judge([a for a in data["attempts"] if a.get("betId")])
    allure.attach("\n".join(rows), f"{case} 逐注核對：玩法／選號／預期／送出價／凍結價", allure.attachment_type.TEXT)
    if not data["restored"]:
        failures.append("十層差分未還原，停止後續操作")
    if baseline and data["table_after"]["diffs"]:
        failures.append(f"還原後全表與基準有 {len(data['table_after']['diffs'])} 格差異")
    data["failures"] = failures
    ledger.save()
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures[:30])
    return data
