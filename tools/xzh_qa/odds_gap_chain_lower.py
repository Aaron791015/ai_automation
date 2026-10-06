# -*- coding: utf-8 -*-
"""B120／B121：其餘連肖／連尾玩法「一般成員較低」——公司即时盘面把一般成員（蛇／1尾）本期賠率調低，
使它的候選價低於副標籤成員（马／0尾），驗證同時含兩者的注以一般成員的主層價成交。

用途：二肖连中已有 B112（差分皆 0）與 B106（有差分），由 `odds_gap_chain_winner` 處理、一次只做一個玩法。
      本模組沿用 `odds_gap_chain_plays` 的玩法定義（三～五肖连中、二～四尾连不中）與注單核對，把這兩型推廣到其餘玩法：
        B120（with_gap=False，B112 推廣）十層差分皆 0、只調低：受測注＝主賠率 − 偏移量（主層）；對照注＝副賠率（副層）。
        B121（with_gap=True，B106 推廣）十層主／副差分各層同值（先試 −0.01／−0.02，區間不足改 −0.001／−0.002）再調低：
             受測注＝（主賠率 − 偏移量）＋Σ主差分（主層）；對照注＝副賠率＋Σ副差分（副層）。
      偏移量依下注當下的公司賠率計算（`plan_offset`）；不存在可行偏移量的玩法列「不適用」，不下注、不算失敗
      （現行賠率下三尾连不中的副賠率等於主最低、四尾连不中的主最低高於副賠率，皆不成立）。
      2026-10-05 以臨時腳本在 QAT 實跑：B120 型 8／8、B121 型 8／8 相符；交接 T104③ 收進 repo 改寫成本模組。
      2026-10-06 正式案例首跑（`gap-b120-20261006-a3`／`gap-b121-20261006-a1`）皆 8／8 相符、偏移與差分全數還原。

使用方式（由 `tests/xzh/test_odds_gap_betting_regression.py` 的 B120／B121 呼叫）：
    run_chain_lower(browser, gap_context, run, ledger_path, with_gap=False, case="B120")
    離線可用 `plan_offset`／`design_play` 算偏移量與期望價（不連線）。

前置條件：
- 已取得本鏈鎖（pytest autouse fixture）；調低期間另持另一條帳號鏈的鎖（公司盤面調整會影響兩條鏈的下注），
  取不到就該玩法列受阻、不調整、不下注。
- 注數（每個成立的玩法 2 注各 2 元）與公司本期手動偏移須經 Aaron 批准；十層該玩法差分開工時須皆為 0。
- 被測行為（下注）走會員前台 UI；手動偏移、差分設定走 UI；API 只用於讀取驗證。
- 帳本在送出前落檔，同一批不可重送；偏移在同一個 finally 依讀回值加回、步進值改回原值；差分由 `guarded_gaps` 由上往下還原。
"""
from __future__ import annotations

import json
import re
import time
from contextlib import ExitStack
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import allure

from xzh_qa.config_loader import chain_lock_name, player_credentials, qat
from xzh_qa.odds_gap_chain_plays import (AMOUNT, CHAIN_PLAYS, ChainPlay, _bet_id_from, _client_get, _collect_records,
                                         baseline_diff, board_rows, judge)
from xzh_qa.odds_gap_chain_winner import (DEFAULT_STEP, GAME, GAME_NAME, ChainWinnerLedger, _click_member,
                                          _close_dialogs, _set_step, _wait_fresh_issue, board_member_price,
                                          chain_frozen_odds, gap_columns_to_write, split_offset)
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_regression import remaining_seconds, reports
from xzh_qa.odds_gap_run_state import ChainBusy
from xzh_qa.odds_gap_safety import guarded_gaps, restore_equal, strict_gap_values
from xzh_qa.pages.player_bet_page import PlayerBetPage

#: 適用玩法（二肖连中由 B106／B112 處理）。三尾／四尾在現行賠率下不成立，仍依當下讀值判斷後列不適用。
PLAYS = ("chainZodiac3Hit", "chainZodiac4Hit", "chainZodiac5Hit", "chainTail2Miss", "chainTail3Miss", "chainTail4Miss")
#: 被調低的一般成員（盤面列名, selectionKey）：連肖＝蛇；連尾＝1尾（盤面列名「1尾尾」，以子字串「1尾」比對）。
OFFSET_MEMBER = {"zodiac": ("蛇", "snake"), "tail": ("1尾", "1")}
#: B121 每層（主, 副）差分候選，依序試，第一組有可行偏移量的採用（二尾连不中區間窄，要用第二組）。
GAP_CANDIDATES = ((Decimal("-0.01"), Decimal("-0.02")), (Decimal("-0.001"), Decimal("-0.002")))
#: 偏移量的候選倍數：先粗後細，同一倍數內取點擊次數最少、其次最接近區間中點。
OFFSET_UNITS = (Decimal("0.05"), Decimal("0.01"), Decimal("0.005"), Decimal("0.001"))
#: 兩條帳號鏈的鎖檔名；調低期間另持「另一條」。
CHAIN_LOCKS = ("aaa111-through-aaa010", "bbb111-through-bbb010")
OTHER_LOCK_TIMEOUT = 120
BET_MIN_SECONDS = 22
CLICK_SECONDS = 3


class OffsetNotRestored(AssertionError):
    """偏移加回後讀回不等於原賠率：停止後續玩法。"""


# ---------------------------------------------------------------- 純計算（離線可測）

def plan_offset(pricing: dict, main_total=0, sub_total=0):
    """依公司賠率與差分合計找偏移量 d；回傳（計畫 dict 或 None, 算式說明）。

    候選價＝max(下限, 解析價＋差分合計)。條件：
      受測注的一般成員調低後低於副標籤成員：(P−d)+Σ主 ＜ S+Σ副 → d ＞ (P−S)+(Σ主−Σ副)
      一般成員調低後不觸到主最低：            (P−d)+Σ主 ＞ 主最低 → d ＜ (P−主最低)+Σ主
      副層不觸底：S+Σ副 ＞ 副最低；對照注（不含被調低成員）副層較低：S+Σ副 ＜ P+Σ主
    d 兩端各留 max(0.05, 區間寬×25%)，依 `OFFSET_UNITS` 先粗後細取點擊次數最少、其次最接近中點。
    """
    P, Pmin, S = dec(pricing["odds"]), dec(pricing["minOdds"]), dec(pricing["subOdds"])
    Smin = dec(pricing["subMinOdds"]) if pricing.get("subMinOdds") is not None else Pmin
    Gm, Gs = dec(main_total), dec(sub_total)
    lo, hi = (P - S) + (Gm - Gs), (P - Pmin) + Gm
    text = (f"d∈((主賠率−副賠率)+(Σ主−Σ副), (主賠率−主最低)+Σ主)＝(({P}−{S})+({Gm}−{Gs}), ({P}−{Pmin})+({Gm}))"
            f"＝({lo}, {hi})")
    if lo >= hi:
        return None, text + "；區間為空（一般成員調低到低於副標籤成員前就先觸到主最低）"
    if not S + Gs > Smin:
        return None, text + f"；副層 {S + Gs} 觸到副最低 {Smin}"
    if not S + Gs < P + Gm:
        return None, text + f"；對照注副層 {S + Gs} 不低於主層 {P + Gm}"
    margin = max(Decimal("0.05"), (hi - lo) * Decimal("0.25"))
    for unit in OFFSET_UNITS:
        d = max(unit, (lo / unit).to_integral_value(rounding=ROUND_CEILING) * unit)
        candidates = []
        while d < hi:
            if d > lo and min(d - lo, hi - d) >= margin:
                candidates.append(d)
            d += unit
        if candidates:
            best = min(candidates, key=lambda x: (len(split_offset(x)), abs(x - (lo + hi) / 2)))
            return {"d": best, "lo": lo, "hi": hi, "margin": margin, "offset_price": P - best,
                    "steps": split_offset(best)}, text
    return None, text + f"；區間寬 {hi - lo} 不足以兩端各留 {margin}"


def bet_prices(cfg: ChainPlay, start: int, pricing: dict, offset_price) -> dict:
    """一注各成員本期應有的盤面價：被調低成員＝調低後價、副標籤成員＝副賠率、其餘＝主賠率。"""
    offset_key = OFFSET_MEMBER[cfg.kind][1]
    return {k: dec(offset_price) if k == offset_key else dec(pricing["subOdds"] if k == cfg.exception_key else pricing["odds"])
            for k in cfg.keys(start)}


def design_play(play: str, pricing: dict, with_gap: bool) -> dict:
    """某玩法的設計：每層差分、合計、偏移量、受測／對照兩注的期望成交價；不成立時 `plan` 為 None 並附原因。

    期望價用獨立算式，再與 `chain_frozen_odds`（先扣再比、同價取主層）交叉核對，兩者不一致就不設計（不下注）。
    """
    cfg = CHAIN_PLAYS[play]
    offset_key = OFFSET_MEMBER[cfg.kind][1]
    assert offset_key in cfg.keys(cfg.tested_start) and cfg.exception_key in cfg.keys(cfg.tested_start), \
        f"{play} 受測注須同時含被調低成員與副標籤成員"
    assert offset_key not in cfg.keys(cfg.control_start) and cfg.exception_key in cfg.keys(cfg.control_start), \
        f"{play} 對照注須含副標籤成員、不含被調低成員"
    P, Pmin, S = dec(pricing["odds"]), dec(pricing["minOdds"]), dec(pricing["subOdds"])
    min_sub = dec(pricing["subMinOdds"]) if pricing.get("subMinOdds") is not None else None
    tries = []
    for gm, gs in (GAP_CANDIDATES if with_gap else ((Decimal(0), Decimal(0)),)):
        Gm, Gs = gm * 10, gs * 10
        plan, text = plan_offset(pricing, Gm, Gs)
        tries.append({"per_layer": [str(gm), str(gs)], "feasible": plan is not None, "detail": text})
        if not plan:
            continue
        d, offset_price = plan["d"], plan["offset_price"]
        tested = {"expected": offset_price + Gm, "tier": "main",
                  "formula": f"(主賠率−偏移量)+Σ主＝({P}−{d})+({Gm})＝{offset_price + Gm}"
                             f"（候選：被調低成員 {offset_price + Gm}／副標籤成員 {S + Gs}／其餘成員 {P + Gm}）"}
        control = {"expected": S + Gs, "tier": "sub",
                   "formula": f"副賠率+Σ副＝{S}+({Gs})＝{S + Gs}（候選：副標籤成員 {S + Gs}／其餘成員 {P + Gm}）"}
        for name, start, exp in (("tested", cfg.tested_start, tested), ("control", cfg.control_start, control)):
            impl = chain_frozen_odds(bet_prices(cfg, start, pricing, offset_price), {cfg.exception_key}, Gm, Gs, Pmin, min_sub)
            assert (impl["expected"], impl["tier"]) == (exp["expected"], exp["tier"]), \
                f"{play}／{name} 獨立算式 {exp['expected']}（{exp['tier']}）與 chain_frozen_odds {impl} 不一致"
        wrong = {"誤取副標籤成員：副賠率+Σ副": S + Gs}
        if with_gap:
            wrong["副差分誤扣在被調低成員：(主賠率−偏移量)+Σ副"] = offset_price + Gs
        return {"play": play, "plan": plan, "tries": tries, "per_layer": (gm, gs), "main_total": Gm, "sub_total": Gs,
                "tested": tested, "control": control, "wrong": wrong}
    return {"play": play, "plan": None, "tries": tries, "not_applicable": tries[-1]["detail"]}


def other_chain_lock() -> str:
    """另一條帳號鏈的鎖檔名（本鏈由 `XZH_CHAIN` 決定）。"""
    current = chain_lock_name()
    assert current in CHAIN_LOCKS, f"未知的帳號鏈鎖 {current}"
    return next(name for name in CHAIN_LOCKS if name != current)


# ---------------------------------------------------------------- 即時盤面操作

def open_chain_board(page, tab: str):
    """公司「即时盘面」→ 宾果六合彩 →「连肖」或「连尾」。"""
    page.get_by_role("menuitem", name="即时盘面", exact=True).click()
    page.wait_for_timeout(1500)
    _close_dialogs(page)
    page.get_by_text(GAME_NAME, exact=True).first.click()
    page.wait_for_timeout(1500)
    page.get_by_text(tab, exact=True).first.click()
    page.wait_for_timeout(1500)
    _close_dialogs(page)


def read_step(page) -> Decimal:
    """「赔率调整」步進值下拉目前的值（只讀）。"""
    box = page.locator(".el-select.control-select").filter(has_text=re.compile(r"^\s*\d+(\.\d+)?\s*$"))
    assert box.count() == 1, "找不到唯一的步進值下拉"
    return dec(box.first.inner_text().strip())


def ensure_step(page, step):
    if read_step(page) != dec(step):
        _set_step(page, str(dec(step)))


def _issue(top) -> dict:
    return next(r for r in _client_get(top, "/api/Issues/Current", {}) if r["gameId"] == GAME)


def member_odds(top, issue_number, cfg: ChainPlay, key: str) -> Decimal:
    return dec(board_rows(top, issue_number, cfg)[key]["odds"])


def click_checked(top, issue_number, cfg: ChainPlay, label: str, key: str, direction: str, step, journal: list):
    """點一次減／加，輪詢讀回盤面確認剛好變動一個步進；不符就報錯、不再點。"""
    step = dec(step)
    before = member_odds(top, issue_number, cfg, key)
    expected = before - step if direction == "minus" else before + step
    _click_member(top.page, direction, cfg.label, label)
    deadline = time.monotonic() + 8
    after = member_odds(top, issue_number, cfg, key)
    while after != expected and time.monotonic() < deadline:
        time.sleep(0.5)
        after = member_odds(top, issue_number, cfg, key)
    journal.append({"direction": direction, "step": str(step), "before": str(before), "after": str(after),
                    "expected": str(expected), "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    assert after == expected, f"{cfg.label}／{label} 按{'減' if direction == 'minus' else '加'}號後盤面 {after}，預期 {expected}"
    return after


def restore_member(top, cfg: ChainPlay, label: str, key: str, base, step, journal: list) -> tuple:
    """依「目前盤面值 vs 原賠率」把偏移加回（換期後新期本來就是原賠率，不點）；步進值改回 `step`。回傳（讀回值, 期號）。"""
    issue = _issue(top)
    current = member_odds(top, issue["issueNumber"], cfg, key)
    if current != dec(base):
        direction = "plus" if current < dec(base) else "minus"
        for s in split_offset(abs(current - dec(base))):
            ensure_step(top.page, s)
            click_checked(top, issue["issueNumber"], cfg, label, key, direction, s, journal)
    ensure_step(top.page, step)
    return member_odds(top, issue["issueNumber"], cfg, key), issue["issueNumber"]


# ---------------------------------------------------------------- 主流程

def run_chain_lower(browser, gap_context, run, ledger_path, with_gap: bool, case: str, plays=None,
                    max_bets=None, baseline_path=None, progress=None):
    """B120（with_gap=False）／B121（with_gap=True）：逐玩法等新期 → 持另一條鏈的鎖調低一般成員 → 同期下受測與對照兩注
    → 加回偏移並讀回 → 下一個玩法；最後讀回凍結賠率、還原十層差分並全表比對。

    `plays`：只做這些玩法（續跑用，預設 `PLAYS`）；`max_bets`：批准注數上限（成立玩法數×2 超過就不開始）；
    `baseline_path`：全表基準 JSON；`progress(event)`：進度回呼。回傳帳本 dict；判定失敗在偏移移除、
    差分還原與核對完成後才 assert。另一條鏈的鎖取不到或盤面已被別人調整的玩法列在 `blocked`，不算失敗也不算通過。
    """
    plays = list(plays or PLAYS)
    assert set(plays) <= set(PLAYS), f"不支援的玩法 {sorted(set(plays) - set(PLAYS))}"
    ledger = ChainWinnerLedger(ledger_path, bets=[(f"{p}:{n}",) for p in plays for n in ("tested", "control")],
                               offset=0, case=case)
    data = ledger.data
    data.update(kind="chain-lower", with_gap=with_gap, plays=plays, play=None, offset=None,
                designs={}, not_applicable={}, blocked=[], offsets={}, play_errors=[])
    day = datetime.now().astimezone().date().isoformat()
    contexts = [gap_context(i, via="company") for i in range(10)]
    originals = [c.open(GAME) for c in contexts]
    member, top = contexts[9], contexts[0]
    client = member.reference_client
    pricing_all = client.odds_setting(GAME)
    designs = {}
    for p in plays:
        cfg = CHAIN_PLAYS[p]
        pricing = pricing_all[p]
        assert pricing.get("subOddsLabel") == cfg.exception_label, \
            f"{p} 副標籤已變（{pricing.get('subOddsLabel')}），需重新核對計畫"
        layers = [next(r for r in rows if r["playTypeId"] == p) for rows in originals]
        assert all(dec(r["oddsGap"] or 0) == 0 and dec(r["subOddsGap"] or 0) == 0 and r["isEffective"] for r in layers), \
            f"{p} 十層差分開工時須皆為 0 且生效；不動別人的值，停止本批"
        design = design_play(p, pricing, with_gap)
        data["designs"][p] = design
        if design["plan"] is None:
            data["not_applicable"][p] = design["not_applicable"]
        else:
            designs[p] = design
    runnable = [p for p in plays if p in designs]
    assert runnable, f"所有玩法在當下賠率下皆不成立：{data['not_applicable']}"
    if max_bets is not None:
        assert 2 * len(runnable) <= int(max_bets), \
            f"本批需 {2 * len(runnable)} 注，超過批准上限 {max_bets} 注；以玩法參數縮小範圍"
    data.update(day=day, runnable=runnable, accounts=[{"account": c.account, "id": c.target_user_id} for c in contexts],
                pricing={p: pricing_all[p] for p in plays}, originals=originals)
    ledger.save()
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8")) if baseline_path else None
    if baseline:
        with allure.step("寫入前：十層三彩種全表與基準逐格比對，須 0 差異"):
            cells, diffs = baseline_diff(contexts, baseline)
            data["table_before"] = {"cells": cells, "diffs": diffs}
            ledger.save()
            assert not diffs, f"寫入前全表與基準有 {len(diffs)} 格差異，不動別人的值、停止本批：{diffs[:3]}"
    data["before_reports"] = reports(client, data["accounts"], day, set(runnable))
    ledger.save()
    other_lock = other_chain_lock()
    active = {}
    with ExitStack() as stack:
        # 反向進入守衛，使結束時由上（aaa111）往下（aaa010）還原
        transactions = [None] * 10
        for i in reversed(range(10)):
            transactions[i] = stack.enter_context(guarded_gaps(contexts[i], GAME, originals[i]))
        if with_gap:
            with allure.step("公司逐層保存各玩法的十層主差分與副差分並讀回（已是目標值的欄不寫）"):
                for c, tr in zip(contexts, transactions):
                    rows = c.open(GAME)
                    index = {r["playTypeId"]: n for n, r in enumerate(rows)}
                    wrote = False
                    for p in runnable:
                        for column, value in gap_columns_to_write(rows[index[p]], *designs[p]["per_layer"]):
                            entered = c.setting.set_value(index[p], column, value)
                            assert entered == value
                            tr["expected"][(p, "subOddsGap" if column else "oddsGap")] = entered
                            wrote = True
                    if wrote:
                        tr["attempted"] = True
                        assert c.setting.save()["status"] in (200, 204)
                        actual = strict_gap_values(c.api_rows(GAME))
                        assert all(actual[k] == v for k, v in tr["expected"].items()), f"{c.account} 保存後讀回不符"
        phase_rows = [c.api_rows(GAME) for c in contexts]
        for p in runnable:
            chain_rows = [next(r for r in rows if r["playTypeId"] == p) for rows in phase_rows]
            assert all(r["isEffective"] for r in chain_rows), f"{p} 十層差分須皆生效"
            totals = (sum((dec(r["oddsGap"] or 0) for r in chain_rows), Decimal(0)),
                      sum((dec(r["subOddsGap"] or 0) for r in chain_rows), Decimal(0)))
            assert totals == (designs[p]["main_total"], designs[p]["sub_total"]), \
                f"{p} 讀回合計 {totals} ≠ 設計 {designs[p]['main_total']}／{designs[p]['sub_total']}"
        data["phase_rows"] = phase_rows
        ledger.save()
        assert all(client.odds_setting(GAME)[p] == pricing_all[p] for p in runnable), "公司基準／最低賠率異動，停止下注"
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
            clock = {"company": time.monotonic(), "player": time.monotonic()}
            original_step = {"value": None}
            try:
                for p in runnable:
                    _play_with_offset(p, designs[p], pricing_all[p], top, client, player, active, run, other_lock,
                                      data, ledger, clock, original_step, progress)
            finally:
                _collect_records(data, top, member, day, ledger)
    # 守衛已於離開 with 時由上往下還原；再次核對與全表比對
    final = [c.api_rows(GAME) for c in contexts]
    data["restored"] = all(restore_equal(c.account, GAME, b, a) for c, a, b in zip(contexts, final, originals))
    if baseline:
        cells, diffs = baseline_diff(contexts, baseline)
        data["table_after"] = {"cells": cells, "diffs": diffs}
    data["offset_removed"] = all(o.get("restored", True) for o in data["offsets"].values())
    ledger.save()
    run.dump("chain-lower.json", data)
    allure.attach(json.dumps(data, ensure_ascii=False, default=str), f"{case} 計畫／實際／還原", allure.attachment_type.JSON)
    failures, rows = judge(data["attempts"])
    allure.attach("\n".join(rows + [f"{p}：不適用（{why}）" for p, why in data["not_applicable"].items()]
                            + [f"{b['play']}：受阻（{b['reason']}）" for b in data["blocked"]]),
                  f"{case} 逐注核對：玩法／選號／預期／送出價／凍結價", allure.attachment_type.TEXT)
    failures += [f"{e['play']}：{e['error']}" for e in data["play_errors"]]
    if not data["offset_removed"]:
        failures.append("本期手動偏移未完全加回，停止後續操作")
    if not data["restored"]:
        failures.append("十層差分未還原，停止後續操作")
    if baseline and data["table_after"]["diffs"]:
        failures.append(f"還原後全表與基準有 {len(data['table_after']['diffs'])} 格差異")
    data["failures"] = failures
    ledger.save()
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures)
    return data


def _play_with_offset(p, design, pricing, top, client, player, active, run, other_lock, data, ledger, clock,
                      original_step, progress):
    """一個玩法：等新期 → 持另一條鏈的鎖 → 調低一般成員並讀回 → 下受測／對照兩注 → 加回並讀回。

    下注中途出錯記進 `play_errors` 後繼續下一個玩法（偏移已加回）；偏移加回失敗丟 `OffsetNotRestored` 停止全批。
    """
    cfg = CHAIN_PLAYS[p]
    plan = design["plan"]
    label, key = OFFSET_MEMBER[cfg.kind]
    base = dec(pricing["odds"])
    record = data["offsets"].setdefault(p, {"member": label, "d": str(plan["d"]), "clicks": []})
    need = 70 + 2 * len(plan["steps"]) * CLICK_SECONDS + 25
    if top.recover and time.monotonic() - clock["company"] > 300:
        top.recover()
        clock["company"] = time.monotonic()
    if time.monotonic() - clock["player"] > 900:
        player.login(qat()["frontend_url"], *player_credentials())
        player.select_game(GAME_NAME)
        clock["player"] = time.monotonic()
    with allure.step(f"{cfg.label}：等剩餘至少 {need} 秒的新期，持另一條帳號鏈的鎖，把「{label}」本期賠率調低 {plan['d']} 後"
                     f"同一期下受測、對照兩注各2元，再加回並讀回"):
        issue = _wait_fresh_issue(client, top.page, min_seconds=need, timeout=900, observed=top.observed)
        issue_number = issue["issueNumber"]
        record.update(issue=issue_number, need_seconds=need)
        ledger.save()
        try:
            lock = run.chain_lock(other_lock, timeout=OTHER_LOCK_TIMEOUT)
            lock.__enter__()
        except ChainBusy as exc:
            data["blocked"].append({"play": p, "reason": f"另一條帳號鏈的鎖 {other_lock} 取不到：{exc}"})
            record["restored"] = True  # 未調整
            ledger.save()
            return
        try:
            open_chain_board(top.page, cfg.category)
            if str(_issue(top)["issueNumber"]) != str(issue_number):
                data["blocked"].append({"play": p, "reason": "開盤面期間已換期，未調整、未下注"})
                record["restored"] = True
                return
            rows = board_rows(top, issue_number, cfg)
            record["board_before"] = {k: {"odds": r["odds"], "subOdds": r.get("subOdds"),
                                          "hasManualOffset": r.get("hasManualOffset")} for k, r in rows.items()}
            # 盤面上副標籤成員（马／0尾）的 odds 欄本來就顯示副賠率（subOdds 欄為空），其餘成員顯示主賠率；
            # 2026-10-06 首次實跑曾因此把副標籤成員誤判為「已有其他偏移」而全數受阻（0 注、0 點擊）。
            sub_base = dec(pricing["subOdds"])
            adjusted = {k: r["odds"] for k, r in rows.items()
                        if dec(r["odds"]) != (sub_base if k == cfg.exception_key else base)
                        or r.get("hasManualOffset") or r.get("hasSubManualOffset")}
            if adjusted:
                record["board_adjusted"] = adjusted
                data["blocked"].append({"play": p, "reason": f"調整前盤面已有其他偏移（成員賠率不等於公司賠率）：{adjusted}，不動"})
                record["restored"] = True
                return
            step_now = read_step(top.page)
            original_step["value"] = original_step["value"] or step_now
            record["step_before"] = str(step_now)
            record["restored"] = False
            try:
                for step in plan["steps"]:
                    ensure_step(top.page, step)
                    click_checked(top, issue_number, cfg, label, key, "minus", step, record["clicks"])
                lowered = member_odds(top, issue_number, cfg, key)
                record["offset_read_back"] = str(lowered)
                assert lowered == plan["offset_price"], f"{cfg.label}／{label} 調低後 {lowered} ≠ 計畫 {plan['offset_price']}"
                for name, start in cfg.bets:
                    _place_bet(p, name, start, design, pricing, top, player, active, issue_number, data, ledger)
                    if progress:
                        progress({"step": f"{p}:{name} 已送出"})
            except Exception as exc:  # 下注結果不明不重送：記下後照樣加回偏移
                data["play_errors"].append({"play": p, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
                ledger.save()
            finally:
                step_back = original_step["value"] or dec(DEFAULT_STEP)
                try:
                    final, final_issue = restore_member(top, cfg, label, key, base, step_back, record["clicks"])
                except Exception as exc:
                    record["restore_first_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                    open_chain_board(top.page, cfg.category)
                    final, final_issue = restore_member(top, cfg, label, key, base, step_back, record["clicks"])
                record.update(final_odds=str(final), final_issue=final_issue, step_after=str(read_step(top.page)),
                              restored=final == base)
                ledger.save()
                if final != base:
                    raise OffsetNotRestored(f"{cfg.label}／{label} 加回後讀回 {final}，原賠率 {base}；停止後續玩法")
        finally:
            lock.__exit__(None, None, None)


def _place_bet(p, name, start, design, pricing, top, player, active, issue_number, data, ledger):
    """送出前核對期別、剩餘時間與盤面各成員價，再走會員前台送出一注並記下送出價。"""
    cfg = CHAIN_PLAYS[p]
    plan, expected = design["plan"], design[name]
    current = _issue(top)
    assert str(current["issueNumber"]) == str(issue_number) and current["isBettable"], "期別已切換或不可下注，不下這注"
    remaining = remaining_seconds(current)
    assert remaining >= BET_MIN_SECONDS, f"剩餘 {remaining:.0f} 秒不足 {BET_MIN_SECONDS} 秒，不下這注"
    keys, names = cfg.keys(start), cfg.names(start)
    board = board_rows(top, issue_number, cfg)
    assert all(k in board for k in keys), f"{p} 盤面缺成員 {keys}"
    prices = {k: board_member_price(board[k], k == cfg.exception_key, configured_sub=pricing["subOdds"]) for k in keys}
    want = bet_prices(cfg, start, pricing, plan["offset_price"])
    assert prices == want, f"{p}／{name} 盤面價 {prices} ≠ 預期 {want}（盤面有未預期的調整），不下這注"
    win_main = expected["tier"] == "main"
    gm, gs = design["per_layer"]
    minimum = dec(pricing["minOdds"]) if win_main else dec(pricing["subMinOdds"] if pricing.get("subMinOdds") is not None
                                                             else pricing["minOdds"])
    base = plan["offset_price"] if win_main else dec(pricing["subOdds"])
    attempt = {"play": p, "bet": name, "label": cfg.label, "start": start, "members": list(names), "keys": list(keys),
               "selection": ",".join(keys), "issue": issue_number, "remaining_at_send": round(remaining, 1),
               "member_prices": {k: str(v) for k, v in prices.items()}, "board": {k: board[k] for k in keys},
               "expected": {"expected": str(expected["expected"]), "tier": expected["tier"], "formula": expected["formula"]},
               "wrong": {k: str(v) for k, v in design["wrong"].items()}, "amount": AMOUNT, "sent": True, "posts": [],
               # 注單層的獨立驗算輸入（供結算核對 `check_settlement`）：勝出鏈的本期解析價、各層差分、有效最低
               "source": {"baseOdds": str(base), "selectionOverrides": []},
               "gaps": [str(gm if win_main else gs)] * 10, "minimum": str(min(minimum, base))}
    data["attempts"].append(attempt)
    ledger.save()
    active.clear()
    active.update(active=True, posts=attempt["posts"])
    try:
        attempt["message"] = player.place_combo_target_bet(cfg.category, cfg.label, amount=AMOUNT, selection_offset=start)
    except Exception as exc:
        attempt["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        ledger.save()
        raise
    finally:
        active.clear()
    sent = next((x for x in reversed(attempt["posts"]) if x.get("status") in (200, 201)), None)
    # POST /api/Bets 回應本文是內部注單 ID，不是報表的 serialNumber；serialNumber 於收尾依選號配對
    attempt["betId"] = _bet_id_from(sent.get("response") if sent else None, attempt.get("message"))
    item = ((sent or {}).get("payload") or {}).get("items", [{}])[0]
    attempt.update(client_odds=item.get("clientOdds"), client_sub_odds=item.get("clientSubOdds"),
                   payload_selection=item.get("selection"))
    ledger.save()
