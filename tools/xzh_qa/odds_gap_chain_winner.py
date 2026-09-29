# -*- coding: utf-8 -*-
"""B106：連肖各成員套用差分與下限後，整注取會員最終最低賠率。

用途：依 2026-09-29 Aaron澄清「會員最後拿到的賠率取最低」及賠率差文件「連肖／連尾主副層跟著贏家成員走」——一注拆成多個成員各自套用差分與下限、
      取最低價成員當整注賠率；贏家是一般成員時用主差分、主下限，即使注單含马。
      以公司「即时盘面」本期手動偏移把「蛇」的公司價調到低於马的副賠率，會員下「蛇＋马」與對照「马＋羊」各一注。
      偏移 0.8 時蛇最終 3.9109 仍高於马 3.8676，驗的是「不先用公司價選生肖」；一般生肖最終價最低的情況需更大偏移（另需核准）。

使用方式（由 `tests/xzh/test_odds_gap_betting_regression.py::test_odds_gap_chain_winner_regression` 呼叫）：
    run_chain_winner(browser, gap_context, run, ledger_path)

前置條件：
- Aaron 已批准本批注數／金額與公司手動偏移（會影響當期全站賓果二肖连中「蛇」賠率，偏移只在本期有效）。
- 被測行為（下注）走會員前台 UI；手動偏移、差分設定也走 UI；API 只用於讀取驗證。
- 帳本在送出前落檔，同一批不可重送；finally 一律移除偏移、還原步進值與十層差分。
"""
from __future__ import annotations

import json
import re
import time
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import allure

from xzh_qa.config_loader import player_credentials, qat
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_regression import read_bets, remaining_seconds
from xzh_qa.odds_gap_safety import guarded_gaps, strict_gap_values
from xzh_qa.pages.player_bet_page import PlayerBetPage

GAME, GAME_NAME = "bingo6", "宾果六合彩"
PLAY, PLAY_LABEL = "chainZodiac2Hit", "二肖连中"
OFFSET_MEMBER, OFFSET_KEY = "蛇", "snake"
OFFSET = Decimal("0.8")
DEFAULT_STEP = "0.005"
MAIN_GAP, SUB_GAP = Decimal("-0.01"), Decimal("-0.02")
AMOUNT = "2"
#: 會員前台連續選生肖的起點（鼠牛虎兔龙蛇马羊…）：5＝蛇＋马（公司價與最終價排序反轉受測）、6＝马＋羊（副對照）。
BETS = (("snake-horse", 5, ("蛇", "马")), ("horse-goat", 6, ("马", "羊")))


def chain_frozen_odds(member_prices: dict, exception_members: set, main_total, sub_total,
                      min_main, min_sub) -> dict:
    """連肖整注凍結賠率：各成員套用差分與下限後取最低價為贏家，主副層依贏家是否為例外成員決定。

    - `member_prices`：{成員: 公司層解析價}；例外成員（马）已用副賠率。
    - `main_total`／`sub_total`：十層生效主／副差分合計（≤0）。
    - 下限：主層 `min_main`；副層 `min_sub`（無副下限時由呼叫端傳主下限）。
    """
    candidates = []
    for member, value in member_prices.items():
        sub_tier = member in exception_members
        price = dec(value)
        total, floor = (dec(sub_total), dec(min_sub)) if sub_tier else (dec(main_total), dec(min_main))
        candidates.append({"winner": member, "tier": "sub" if sub_tier else "main",
                           "company_price": price, "expected": max(floor, price + total)})
    lowest = min(row["expected"] for row in candidates)
    winners = [row for row in candidates if row["expected"] == lowest]
    if len({row["tier"] for row in winners}) > 1:
        raise ValueError("主副最終價同值：層別選用規則待確認")
    return winners[0]



class ChainWinnerLedger:
    """原子佔用帳本；送出前持久化，崩潰後不可整批重送。"""

    def __init__(self, path: Path, bets=BETS, offset=OFFSET):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"schema": 1, "case": "B106", "game": GAME, "play": PLAY, "amount": AMOUNT,
                     "max_bets": len(bets), "offset": str(offset), "bets": [b[0] for b in bets], "started": datetime.now().astimezone().isoformat(),
                     "attempts": [], "restored": False, "offset_removed": False}
        with self.path.open("x", encoding="utf-8") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)

    def save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temp.replace(self.path)


def _close_dialogs(page):
    for _ in range(3):
        box = page.locator(".el-message-box:visible")
        if not box.count():
            return
        box.get_by_role("button").first.click()
        page.wait_for_timeout(300)


def _open_chain_board(page):
    """公司「即时盘面」→ 宾果六合彩 → 连肖。"""
    page.get_by_role("menuitem", name="即时盘面", exact=True).click()
    page.wait_for_timeout(1500)
    _close_dialogs(page)
    page.get_by_text(GAME_NAME, exact=True).first.click()
    page.wait_for_timeout(1500)
    page.get_by_text("连肖", exact=True).first.click()
    page.wait_for_timeout(1500)
    _close_dialogs(page)


def _set_step(page, value: str):
    box = page.locator("input.el-input__inner[type=number]").first
    box.fill(value)
    box.press("Tab")
    page.wait_for_timeout(300)
    assert dec(box.input_value()) == dec(value), f"步進值未設為 {value}"


def _click_member(page, direction: str):
    group = page.locator(".group").filter(has=page.locator(".group-label", has_text=PLAY_LABEL)).filter(
        has_not=page.locator(".group-label", has_text="不中"))
    row = group.first.locator("tbody tr").filter(has=page.locator("span.sel-name", has_text=OFFSET_MEMBER))
    assert row.count() == 1, f"{PLAY_LABEL} 找不到唯一的「{OFFSET_MEMBER}」列"
    kind = "el-button--danger" if direction == "minus" else "el-button--primary"
    row.first.locator(f"button.odds-btn.{kind}").click()
    page.wait_for_timeout(800)
    box = page.locator(".el-message-box:visible")
    if box.count():
        # 偏移需確認時明確按「确定／确认」，不以「第一顆按鈕」猜測
        box.get_by_role("button", name=re.compile(r"^(确定|确认)$")).first.click()
    page.wait_for_timeout(1200)


def _board_member(client, issue_number):
    body = client._get("/api/LiveTrading", {"gameId": GAME, "issueNumber": issue_number, "category": "ChainZodiac"})
    rows = [s for s in body.get("selections", []) if s["playTypeId"] == PLAY]
    return {s["selectionKey"]: s for s in rows}


def _current_issue(client):
    return next(r for r in client._get("/api/Issues/Current") if r["gameId"] == GAME)


def _wait_fresh_issue(client, page, min_seconds=150, timeout=420):
    deadline = time.monotonic() + timeout
    while True:
        issue = _current_issue(client)
        if issue["status"] == "open" and issue["isBettable"] and remaining_seconds(issue) >= min_seconds:
            return issue
        assert time.monotonic() < deadline, "等不到剩餘時間足夠的賓果新期，未套偏移、未下注"
        page.wait_for_timeout(5000)


def run_chain_winner(browser, gap_context, run, ledger_path, offset=OFFSET, bets=BETS):
    """`offset`：蛇的本期手動偏移量（預設0.8；0.85時蛇最終3.8609低於马3.8676，驗一般生肖最終價最低走主層）。
    `bets`：本批要下的注（BETS 子集），批准注數以此為準。"""
    offset = dec(offset)
    assert bets and set(bets) <= set(BETS), "本批注單須為 BETS 的非空子集"
    ledger = ChainWinnerLedger(ledger_path, bets, offset)
    data = ledger.data
    contexts = [gap_context(i, via="company") for i in range(10)]
    originals = [c.open(GAME) for c in contexts]
    member = contexts[9]
    client = member.reference_client
    pricing = client.odds_setting(GAME)[PLAY]
    assert pricing.get("subOddsLabel") == "马", "二肖连中副標籤已變，需重新核對計畫"
    main, sub = dec(pricing["odds"]), dec(pricing["subOdds"])
    min_main = dec(pricing["minOdds"])
    min_sub = dec(pricing["subMinOdds"]) if pricing.get("subMinOdds") is not None else min_main
    assert main - offset < sub, "偏移後蛇的公司價須低於马的副賠率，才能驗證「不先用公司價選生肖」；誰勝出依扣差分與下限後的最終價判定"
    data.update(accounts=[{"account": c.account, "id": c.target_user_id} for c in contexts],
                pricing=pricing, originals=originals)
    ledger.save()
    company = contexts[0].page
    board_state = {"offset_applied": False}
    with ExitStack() as stack:
        transactions = [stack.enter_context(guarded_gaps(c, GAME, rows)) for c, rows in zip(contexts, originals)]
        with allure.step("十層二肖连中主差分各-0.01、副差分各-0.02，保存後逐層讀回"):
            for c, transaction in zip(contexts, transactions):
                rows = c.open(GAME)
                index = next(n for n, r in enumerate(rows) if r["playTypeId"] == PLAY)
                for column, value in ((0, MAIN_GAP), (1, SUB_GAP)):
                    entered = c.setting.set_value(index, column, value)
                    assert entered == value
                    transaction["expected"][(PLAY, "subOddsGap" if column else "oddsGap")] = entered
                transaction["attempted"] = True
                assert c.setting.save()["status"] in (200, 204)
                actual = strict_gap_values(c.api_rows(GAME))
                assert all(actual[k] == v for k, v in transaction["expected"].items())
        phase_rows = [c.api_rows(GAME) for c in contexts]
        chain_rows = [next(r for r in rows if r["playTypeId"] == PLAY) for rows in phase_rows]
        assert all(r["isEffective"] for r in chain_rows), "十層差分須皆生效"
        main_total = sum((dec(r["oddsGap"]) for r in chain_rows), Decimal(0))
        sub_total = sum((dec(r["subOddsGap"]) for r in chain_rows), Decimal(0))
        data.update(main_total=str(main_total), sub_total=str(sub_total), phase_rows=phase_rows)
        ledger.save()
        with browser.new_context(viewport={"width": 1920, "height": 1080}) as front:
            player_page = front.new_page()
            player_page.set_default_timeout(20000)
            player = PlayerBetPage(player_page)
            player.login(qat()["frontend_url"], *player_credentials())
            player.select_game(GAME_NAME)
            try:
                issue = _wait_fresh_issue(client, company)
                data["issue"] = issue["issueNumber"]
                with allure.step("公司即时盘面：步進值改為本批偏移量，按「二肖连中」蛇的減號一次（本期手動偏移）"):
                    _open_chain_board(company)
                    before = _board_member(client, issue["issueNumber"])[OFFSET_KEY]
                    _set_step(company, str(offset))
                    board_state["offset_applied"] = True
                    _click_member(company, "minus")
                    after = _board_member(client, issue["issueNumber"])[OFFSET_KEY]
                    data["board"] = {"before": before, "after": after}
                    ledger.save()
                    assert after["hasManualOffset"] and dec(after["odds"]) == dec(before["odds"]) - offset, \
                        f"蛇偏移後盤面賠率 {after['odds']}，預期 {dec(before['odds']) - offset}"
                snake_price = dec(after["odds"])
                for name, start, members in bets:
                    prices = {m: (sub if m == "马" else (snake_price if m == OFFSET_MEMBER else main)) for m in members}
                    expected = chain_frozen_odds(prices, {"马"}, main_total, sub_total, min_main, min_sub)
                    attempt = {"name": name, "members": members, "expected": {k: str(v) for k, v in expected.items()},
                               "sent": True}
                    data["attempts"].append(attempt)
                    ledger.save()
                    before_ids = {str(r["serialNumber"]) for r in read_bets(client, member.target_user_id, datetime.now().astimezone().date().isoformat())}
                    with allure.step("會員前台下「二肖连中」一注並讀回正式注單凍結賠率"):
                        attempt["message"] = player.place_combo_target_bet("连肖", PLAY_LABEL, amount=AMOUNT, selection_offset=start)
                    after_bets = read_bets(client, member.target_user_id, datetime.now().astimezone().date().isoformat())
                    new = [r for r in after_bets if str(r["serialNumber"]) not in before_ids]
                    assert len(new) == 1, "新注不能唯一對應，不繼續"
                    record = new[0]
                    attempt.update(serialNumber=str(record["serialNumber"]), record=record)
                    ledger.save()
                    assert record["playTypeId"] == PLAY and str(record["issueNumber"]) == str(issue["issueNumber"])
            finally:
                if board_state["offset_applied"]:
                    with allure.step("按蛇的加號移除本期手動偏移，步進值改回0.005並讀回"):
                        _open_chain_board(company)
                        current = _current_issue(client)
                        member_row = _board_member(client, current["issueNumber"]).get(OFFSET_KEY, {})
                        if str(current["issueNumber"]) == str(data.get("issue")) and member_row.get("hasManualOffset"):
                            _set_step(company, str(offset))
                            _click_member(company, "plus")
                            member_row = _board_member(client, current["issueNumber"]).get(OFFSET_KEY, {})
                        _set_step(company, DEFAULT_STEP)
                        # 同一期減後再加，後端 hasManualOffset 仍為 true（淨偏移 0 的紀錄留到本期結束）；
                        # 以「賠率回到偏移前」或「已換期」判定移除，旗標另存佐證。
                        before_odds = dec(((data.get("board") or {}).get("before") or {}).get("odds") or 0)
                        data["offset_removed"] = (str(current["issueNumber"]) != str(data.get("issue"))
                                                  or dec(member_row.get("odds") or 0) == before_odds)
                        data["board_final"] = member_row
                        ledger.save()
    final = [c.api_rows(GAME) for c in contexts]
    data["restored"] = all(strict_gap_values(a) == strict_gap_values(b) for a, b in zip(final, originals))
    ledger.save()
    run.dump("chain-winner.json", data)
    allure.attach(json.dumps(data, ensure_ascii=False, default=str), "B106 計畫／實際／還原", allure.attachment_type.JSON)
    failures = []
    for attempt in data["attempts"]:
        actual = dec(attempt["record"]["odds"])
        expected = dec(attempt["expected"]["expected"])
        if actual != expected:
            failures.append(f"{'＋'.join(attempt['members'])}：凍結 {actual}，預期 {expected}"
                            f"（贏家 {attempt['expected']['winner']}／{attempt['expected']['tier']}層）")
    if not data["restored"]:
        failures.append("十層差分未還原，停止後續操作")
    if not data["offset_removed"]:
        failures.append("蛇的本期手動偏移未移除，停止後續操作")
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    return data
