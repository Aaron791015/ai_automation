# -*- coding: utf-8 -*-
"""B106／B112～B115：連肖各層先套差分與下限，再取會員最低成交價；同價取主層。

用途：依 Aaron 指定 odds-gap (1).md §3.4／§4.3 與 chain-zodiac-tail-priced-odds.md §3.3。
      偏移0.8時蛇最終3.9109、马3.8676 → 副層3.8676；偏移0.85時蛇3.8609 → 主層3.8609。
      B112（2026-10-01）：十層差分皆0、蛇偏移0.85 → 蛇3.9609（主層）、马4.0676（副層）。
      B113（2026-10-01）：十層主−0.01／副−0.02、蛇不偏移 → 兩注皆马3.8676（副層）。
      B114（2026-10-01）：各層主−0.0944／−0.0943、副−0.02 → 主副同為3.8676，同價取主層。
      B115（2026-10-01）：各層主−0.13／−0.12、副−0.05 → 主層觸底3.8487，兩注皆马3.5676（副層）。
      本工具只驗成交價；逐層凍結欄與結算另行核對。

使用方式（由 `tests/xzh/test_odds_gap_betting_regression.py` 的 B106／B112～B115 呼叫）：
    run_chain_winner(browser, gap_context, run, ledger_path)                      # B106
    run_chain_winner(..., offset=Decimal("0.85"), gaps=(Decimal(0), Decimal(0)), case="B112")
    run_chain_winner(..., offset=Decimal(0), case="B113")                         # 0＝不偏移
    run_chain_winner(..., offset=Decimal(0), gaps=<十組 (主, 副)>, case="B114")    # 各層不同值
    `gaps` 是十層「二肖连中」主／副差分的目標值；已是目標值的層不寫入、不保存。

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
#: 即时盘面「赔率调整」步進值是固定選項的下拉（2026-09-30 實測；原為可輸入的數字框），
#: 偏移量須拆成這些步進值的多次點擊。
STEP_OPTIONS = tuple(Decimal(v) for v in ("1", "0.5", "0.1", "0.05", "0.01", "0.005", "0.001"))
MAIN_GAP, SUB_GAP = Decimal("-0.01"), Decimal("-0.02")
AMOUNT = "2"
#: 會員前台連續選生肖的起點（鼠牛虎兔龙蛇马羊…）：5＝蛇＋马（按最終價判主副層）、6＝马＋羊（副對照）。
BETS = (("snake-horse", 5, ("蛇", "马")), ("horse-goat", 6, ("马", "羊")))


def chain_frozen_odds(member_prices: dict, exception_members: set, main_total, sub_total,
                      min_main, min_sub) -> dict:
    """依權威文件先扣再比，主副最終同價取主層。

    member_prices 是各成員已完成動態調整的解析價；生效差分合計≤0。
    含例外成員時候選有效下限不得高於候選解析价；缺副下限回退主下限。
    """
    candidates = []
    has_exception = any(member in exception_members for member in member_prices)
    for member, value in member_prices.items():
        sub_tier = member in exception_members
        price = dec(value)
        total = dec(sub_total) if sub_tier and sub_total is not None else dec(main_total) if not sub_tier else Decimal(0)
        floor = dec(min_sub if min_sub is not None else min_main) if sub_tier else dec(min_main)
        if has_exception:
            floor = min(floor, price)
        candidates.append({"winner": member, "tier": "sub" if sub_tier else "main",
                           "company_price": price, "expected": max(floor, price + total)})
    return min(candidates, key=lambda row: (row["expected"], row["tier"] == "sub", row["company_price"], row["winner"]))


def board_member_price(row: dict, sub_tier: bool, configured_sub=None) -> Decimal:
    """盤面缺副價時使用明確提供的副基準，不把主價當副價。

    此回退僅供本案例無副手動偏移的基準向量；有副動態價時優先採用，
    涉及副層跳水的案例須另取得完整動態解析來源。
    """
    field = "subOdds" if sub_tier else "odds"
    if sub_tier and row.get(field) is None and configured_sub is not None:
        assert not row.get("hasManualOffset") and not row.get("hasSubManualOffset"), "副價未提供且存在偏移，不可回退基準"
        return dec(configured_sub)
    assert row.get(field) is not None, f"盤面缺少候選賠率欄 {field}，不可判定成交價"
    return dec(row[field])


def gap_columns_to_write(row: dict, main_target, sub_target) -> list:
    """回傳本層要寫入的 (欄位序, 目標值)：0＝主差分、1＝副差分；已等於目標值（NULL 視同 0）的欄不寫。

    B112 要求十層差分皆為 0：多數情況各層本來就是 0，不重複保存，免得產生同值保存。
    """
    columns = []
    for column, field, target in ((0, "oddsGap", main_target), (1, "subOddsGap", sub_target)):
        if dec(row.get(field) or 0) != dec(target):
            columns.append((column, dec(target)))
    return columns


def expand_layer_gaps(gaps) -> list:
    """把 (主, 副) 一組展開成十層同值；已是十組則逐層轉 Decimal。差分只能 ≤0。"""
    if len(gaps) == 10 and all(isinstance(g, (tuple, list)) for g in gaps):
        layers = [(dec(m), dec(s)) for m, s in gaps]
    else:
        assert len(gaps) == 2, "gaps 須為 (主, 副) 一組或十組"
        layers = [(dec(gaps[0]), dec(gaps[1]))] * 10
    assert all(m <= 0 and s <= 0 for m, s in layers), "差分只能為 0 或負數"
    return layers


class ChainWinnerLedger:
    """原子佔用帳本；送出前持久化，崩潰後不可整批重送。"""

    def __init__(self, path: Path, bets=BETS, offset=OFFSET, case="B106"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"schema": 1, "case": case, "game": GAME, "play": PLAY, "amount": AMOUNT,
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


def split_offset(offset) -> list:
    """把偏移量拆成步進選項的點擊序列（由大到小）；湊不出整數倍就拒絕，不近似。"""
    rest, steps = dec(offset), []
    assert rest > 0, "偏移量須為正數"
    for step in STEP_OPTIONS:
        while rest >= step:
            steps.append(step)
            rest -= step
    assert rest == 0, f"偏移 {offset} 無法以步進選項 {[str(s) for s in STEP_OPTIONS]} 組成"
    return steps


def _set_step(page, value: str):
    """「赔率调整」步進值下拉（唯讀 el-select，只能選固定選項）：點開後選完全相符的選項。"""
    box = page.locator(".el-select.control-select").filter(has_text=re.compile(r"^\s*\d+(\.\d+)?\s*$"))
    assert box.count() == 1, "找不到唯一的步進值下拉"
    box.first.click()
    page.wait_for_timeout(300)
    page.locator(".el-select-dropdown:visible .el-select-dropdown__item").filter(
        has_text=re.compile(rf"^\s*{re.escape(str(value))}\s*$")).first.click()
    page.wait_for_timeout(300)
    if page.locator(".el-select-dropdown:visible").count():
        page.keyboard.press("Escape")
    assert dec(box.first.inner_text().strip()) == dec(value), f"步進值未設為 {value}"


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


def _wait_fresh_issue(client, page, min_seconds=150, timeout=420, observed=None):
    deadline = time.monotonic() + timeout
    while True:
        if observed and observed.get("headers"):
            client.headers = dict(observed["headers"])
        issue = _current_issue(client)
        if issue["status"] == "open" and issue["isBettable"] and remaining_seconds(issue) >= min_seconds:
            return issue
        assert time.monotonic() < deadline, "等不到剩餘時間足夠的賓果新期，未套偏移、未下注"
        page.wait_for_timeout(5000)


def _apply_snake_offset(company, client, issue_number, offset, data, ledger, board_state):
    """公司即时盘面：把偏移量拆成步進選項，逐次選步進值並按蛇的減號；回傳偏移後的盤面列。"""
    with allure.step("公司即时盘面：依步進選項拆分本批偏移量，逐次選步進值並按「二肖连中」蛇的減號（本期手動偏移）"):
        _open_chain_board(company)
        before = _board_member(client, issue_number)[OFFSET_KEY]
        steps = split_offset(offset)
        data["board"] = {"before": before, "steps": [str(s) for s in steps]}
        ledger.save()
        board_state["offset_applied"] = True
        for step in steps:
            _set_step(company, str(step))
            _click_member(company, "minus")
        after = _board_member(client, issue_number)[OFFSET_KEY]
        data["board"]["after"] = after
        ledger.save()
        assert after["hasManualOffset"] and dec(after["odds"]) == dec(before["odds"]) - offset, \
            f"蛇偏移後盤面賠率 {after['odds']}，預期 {dec(before['odds']) - offset}"
    return after


def run_chain_winner(browser, gap_context, run, ledger_path, offset=OFFSET, bets=BETS,
                     gaps=(MAIN_GAP, SUB_GAP), case="B106"):
    """`offset`：蛇的本期手動偏移量（0.8時最終取马3.8676；0.85時取蛇3.8609，實跑依當期解析價計算）；
    須能以 `STEP_OPTIONS` 組成（0.85＝0.5＋0.1×3＋0.05，逐次選步進值按減號）；0＝不偏移（B113）。
    `bets`：本批要下的注（BETS 子集），批准注數以此為準。
    `gaps`：十層「二肖连中」(主差分, 副差分) 目標值；一組＝十層同值（B112 傳 (0, 0)），
            或依 aaa111～aaa010 順序給十組（B114／B115 各層不同值）。
    `case`：帳本與 allure 附件標示的案例編號。"""
    offset = dec(offset)
    layer_gaps = expand_layer_gaps(gaps)
    assert offset >= 0, "偏移量不可為負數"
    assert bets and set(bets) <= set(BETS), "本批注單須為 BETS 的非空子集"
    ledger = ChainWinnerLedger(ledger_path, bets, offset, case)
    data = ledger.data
    data["gap_targets"] = [[str(m), str(s)] for m, s in layer_gaps]
    contexts = [gap_context(i, via="company") for i in range(10)]
    originals = [c.open(GAME) for c in contexts]
    member = contexts[9]
    client = member.reference_client
    pricing = client.odds_setting(GAME)[PLAY]
    assert pricing.get("subOddsLabel") == "马", "二肖连中副標籤已變，需重新核對計畫"
    main, sub = dec(pricing["odds"]), dec(pricing["subOdds"])
    min_main = dec(pricing["minOdds"])
    min_sub = dec(pricing["subMinOdds"]) if pricing.get("subMinOdds") is not None else min_main
    if offset > 0:
        assert main - offset < sub, "偏移後蛇的公司價須低於马的副賠率，才能驗證「含马但一般成員公司價最低時走主層」"
    data.update(accounts=[{"account": c.account, "id": c.target_user_id} for c in contexts],
                pricing=pricing, originals=originals)
    ledger.save()
    company = contexts[0].page
    board_state = {"offset_applied": False}
    with ExitStack() as stack:
        transactions = [stack.enter_context(guarded_gaps(c, GAME, rows)) for c, rows in zip(contexts, originals)]
        with allure.step("十層二肖连中主差分與副差分改成本批指定值後保存並逐層讀回（已是指定值的層不重複保存）"):
            for c, transaction, target in zip(contexts, transactions, layer_gaps):
                rows = c.open(GAME)
                index = next(n for n, r in enumerate(rows) if r["playTypeId"] == PLAY)
                columns = gap_columns_to_write(rows[index], *target)
                if not columns:
                    continue
                for column, value in columns:
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
        assert all(not gap_columns_to_write(r, *t) for r, t in zip(chain_rows, layer_gaps)), "十層差分讀回不等於本批指定值"
        main_total = sum((dec(r["oddsGap"] or 0) for r in chain_rows), Decimal(0))
        sub_total = sum((dec(r["subOddsGap"] or 0) for r in chain_rows), Decimal(0))
        data.update(main_total=str(main_total), sub_total=str(sub_total), phase_rows=phase_rows)
        ledger.save()
        with browser.new_context(viewport={"width": 1920, "height": 1080}) as front:
            player_page = front.new_page()
            player_page.set_default_timeout(20000)
            player = PlayerBetPage(player_page)
            player.login(qat()["frontend_url"], *player_credentials())
            player.select_game(GAME_NAME)
            try:
                issue = _wait_fresh_issue(client, company, observed=contexts[0].observed)
                data["issue"] = issue["issueNumber"]
                data["issue_snapshot"] = issue
                if offset == 0:
                    with allure.step("讀公司即时盘面「二肖连中」蛇、马、羊本期賠率，確認皆等於公司賠率、沒有調整（本批不偏移）"):
                        live_rows = _board_member(client, issue["issueNumber"])
                        after = live_rows[OFFSET_KEY]
                        data["board"] = {"before": after, "steps": [],
                                         "members": {k: live_rows[k] for k in ("snake", "horse", "goat")}}
                        ledger.save()
                        # 同期先減後加會留下 hasManualOffset=true 但淨偏移 0，所以以賠率是否等於公司賠率判定
                        assert all(dec(live_rows[k]["odds"]) == main for k in ("snake", "horse", "goat")), \
                            "本期蛇／马／羊賠率不等於公司賠率（已有調整），停止本批"
                else:
                    after = _apply_snake_offset(company, client, issue["issueNumber"], offset, data, ledger, board_state)
                snake_price = dec(after["odds"])
                for name, start, members in bets:
                    current = _current_issue(client)
                    assert str(current["issueNumber"]) == str(issue["issueNumber"]) and current["isBettable"], "期別已切換或不可下注，停止本批"
                    live_rows = _board_member(client, issue["issueNumber"])
                    keys = {"蛇": "snake", "马": "horse", "羊": "goat"}
                    prices = {m: board_member_price(live_rows[keys[m]], m == "马", configured_sub=sub) for m in members}
                    expected = chain_frozen_odds(prices, {"马"}, main_total, sub_total, min_main, min_sub)
                    if name == "snake-horse" and offset == Decimal("0.85"):
                        assert expected["tier"] == "main", "當期蛇最終價未低於马，本批未覆蓋Snotra-018，不下注"
                    attempt = {"name": name, "members": members, "expected": {k: str(v) for k, v in expected.items()},
                               "member_prices": {k: str(v) for k, v in prices.items()},
                               "member_rows": {m: live_rows[keys[m]] for m in members}, "sent": True}
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
                    with allure.step("依已套用的淨偏移逐次按蛇的加號移除本期手動偏移，步進值改回0.005並讀回"):
                        _open_chain_board(company)
                        current = _current_issue(client)
                        member_row = _board_member(client, current["issueNumber"]).get(OFFSET_KEY, {})
                        before_odds = dec(((data.get("board") or {}).get("before") or {}).get("odds") or 0)
                        if str(current["issueNumber"]) == str(data.get("issue")) and member_row.get("hasManualOffset"):
                            # 以「偏移前賠率 − 目前賠率」算淨偏移，中途失敗只套了一部分也能加回原值
                            applied = before_odds - dec(member_row.get("odds") or before_odds)
                            for step in (split_offset(applied) if applied > 0 else []):
                                _set_step(company, str(step))
                                _click_member(company, "plus")
                            member_row = _board_member(client, current["issueNumber"]).get(OFFSET_KEY, {})
                        _set_step(company, DEFAULT_STEP)
                        # 同一期減後再加，後端 hasManualOffset 仍為 true（淨偏移 0 的紀錄留到本期結束）；
                        # 以「賠率回到偏移前」或「已換期」判定移除，旗標另存佐證。
                        data["offset_removed"] = (str(current["issueNumber"]) != str(data.get("issue"))
                                                  or dec(member_row.get("odds") or 0) == before_odds)
                        data["board_final"] = member_row
                        ledger.save()
                elif offset == 0:
                    data["offset_removed"] = True  # 本批不偏移，沒有要移除的偏移
                    ledger.save()
    final = [c.api_rows(GAME) for c in contexts]
    data["restored"] = all(strict_gap_values(a) == strict_gap_values(b) for a, b in zip(final, originals))
    ledger.save()
    run.dump("chain-winner.json", data)
    allure.attach(json.dumps(data, ensure_ascii=False, default=str), f"{case} 計畫／實際／還原", allure.attachment_type.JSON)
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
