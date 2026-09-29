"""投注時序情境：UI 下注、不可盲目重送、自然結算與唯讀凍結稽核。"""
import json
import os
import re
import time
from datetime import datetime

import allure
import pytest

from xzh_qa.config_loader import player_credentials, qat
from xzh_qa.odds_gap_audit import AuditBlocked, load_audit, require, verify_pricing, verify_settlement
from xzh_qa.odds_gap_client import GAMES, gap_values
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_safety import guarded_gaps, guarded_authorization
from xzh_qa.odds_gap_report_checks import verify_live_records
from xzh_qa.pages.player_bet_page import PlayerBetPage


def audit_preflight():
    """缺來源時先阻塞，不建立無法驗算的額外注單。"""
    path = os.environ.get("XZH_GAP_FROZEN_AUDIT", "")
    day = datetime.now().date().isoformat()
    load_audit(path, day, scope_games())
    return path, day


def submit_once(player, run, game, label, plan):
    """一次 UI 送出；任何不明回應只留證，不重試或取消注單。"""
    player.select_game(GAMES[game])
    require(player.is_open(), f"{game} 尚未開盤或已封盤")
    issue = player.current_issue()
    run.log({"phase": "bet_intent", "game": game, "label": label, "issue": issue,
             "amount": plan["amount"], "category": plan["category"], "option": plan["optionIndex"]})
    responses = []
    def observe(response):
        if "/api/Bets" in response.url and response.request.method == "POST":
            responses.append({"status": response.status, "body": response.text(),
                              "payload": response.request.post_data_json})
    player.page.on("response", observe)
    try:
        player.place_standard_category_bet(plan["category"], amount=str(plan["amount"]),
                                           option_index=plan["optionIndex"], sub_item=plan.get("subItem"))
        require(len(responses) == 1, "下注回應無法唯一辨識，禁止重送")
        response = responses[0]
        run.dump(f"bet-{game}-{label}.json", response)
        require(response["status"] in (200, 201), f"下注失敗 HTTP {response['status']}，不重試")
        bet_id = response["body"].strip().strip('"')
        require(bool(re.fullmatch(r"\d+", bet_id)), "未取得唯一注單 ID，禁止重送")
        run.log({"phase": "bet_accepted", "game": game, "label": label, "betId": bet_id, "issue": issue})
        return bet_id
    except BaseException as exc:
        run.dump(f"bet-unresolved-{game}-{label}.json", {"responses": responses, "error": str(exc)})
        raise
    finally:
        player.page.remove_listener("response", observe)


def await_records(path, day, games, ids, page, run, member_ctx):
    """只輪詢外部唯讀稽核匯出；不觸發開獎或結算。"""
    timeout = int(os.environ.get("XZH_GAP_SETTLEMENT_TIMEOUT", "120"))
    deadline = time.monotonic() + timeout
    while True:
        audit = load_audit(path, day, games)
        records = {str(r["betId"]): r for r in audit["records"]}
        if all(str(i) in records for i in ids):
            client = member_ctx.reference_client
            live = client.all_member_bets(member_ctx.target_user_id, day, games)
            verify_live_records(audit, live)
            return [records[str(i)] for i in ids]
        if time.monotonic() >= deadline:
            raise AuditBlocked(f"自然結算／凍結匯出等待逾時，注單 {ids} 保留，不重送；來源 {path}")
        run.log({"phase": "waiting_natural_settlement", "betIds": ids})
        page.wait_for_timeout(5000)


def load_bet_plan():
    path = os.environ.get("XZH_GAP_BET_PLAN", "")
    require(bool(path), "缺 XZH_GAP_BET_PLAN：需對齊玩法ID、UI分類、主副欄及投注選項")
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError) as exc:
        raise AuditBlocked(f"投注計畫不可讀：{exc}")
    for game in scope_games():
        p = plan.get(game, {})
        require(all(k in p for k in ("playTypeId", "field", "category", "optionIndex", "amount")), f"{game} 投注映射不完整")
        require(p["field"] in ("oddsGap", "subOddsGap") and dec(p["amount"]) > 0, "非法欄位／金額")
    return plan


def run_ab(browser, gap_context, run):
    context = None
    try:
        path, day = audit_preflight()
        plans = load_bet_plan()
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        player = PlayerBetPage(context.new_page())
        player.login(qat()["frontend_url"], *player_credentials())
        pairs = []
        ctx = gap_context(9)
        for game in scope_games():
            plan = plans[game]
            rows = ctx.open(game)
            index = next((i for i,r in enumerate(rows) if r["playTypeId"] == plan["playTypeId"]), None)
            require(index is not None, f"{game} 無指定玩法")
            field = plan["field"]
            original = dec(rows[index][field])
            target = original - dec("0.001")
            a = submit_once(player, run, game, "A", plan)
            with guarded_gaps(ctx, game, rows) as transaction:
                entered = ctx.setting.set_value(index, int(field == "subOddsGap"), target)
                assert entered == target, "A/B 新設定未正確進入 UI，停止保存與 B 下注"
                require(gap_values(ctx.api_rows(game)) == gap_values(rows), "A 注後設定被他人改動")
                transaction["expected"] = {(plan["playTypeId"], field): target}
                transaction["attempted"] = True
                saved = ctx.setting.save()
                assert saved["status"] in (200, 204), "A/B 之間保存失敗"
                assert gap_values(ctx.api_rows(game))[(plan["playTypeId"], field)] == target
                changed_at = datetime.now().astimezone()
                b = submit_once(player, run, game, "B", plan)
                # 兩筆凍結後即可還原；後續只等待自然結算。
            records = await_records(path, day, scope_games(), [a, b], player.page, run, ctx)
            first, second = records
            for r in records:
                require(r["gameId"] == game and r["playTypeId"] == plan["playTypeId"], "凍結注單玩法與UI計畫不符")
                require(dec(r["betAmount"]) == dec(plan["amount"]), "凍結投注額與UI計畫不符")
                verify_pricing(r)
                verify_settlement(r)
            require(datetime.fromisoformat(first["betAt"]) < changed_at < datetime.fromisoformat(second["betAt"]), "A/修改/B 時序不符")
            assert dec(first["chainGapsAtBet"][9]) == original and dec(second["chainGapsAtBet"][9]) == target, "A/B 未各自保留下注時差分"
            require(first["diffs"] != second["diffs"] and first["outcome"] == second["outcome"] == "won", "A/B 缺可區分新舊差分的中獎樣本")
            require(first["actualGapMoney"] != second["actualGapMoney"], "A/B 九層收益無可辨識差異，樣本不足")
            pairs.append({"game": game, "A": a, "B": b, "restored": True})
        run.dump("b100-pairs.json", pairs)
    except AuditBlocked as exc:
        pytest.skip(f"BLOCKED：{exc}")
    finally:
        if context is not None:
            context.close()


def run_authorization(browser, gap_context, run, indexes=None):
    """每對父子先驗設定保留；具備凍結来源時再送關閉／恢復兩筆新注。"""
    context, player, reason = None, None, None
    try:
        try:
            path, day = audit_preflight()
            plans = load_bet_plan()
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            player = PlayerBetPage(context.new_page())
            player.login(qat()["frontend_url"], *player_credentials())
            member_ctx = gap_context(9)
            member_ctx.open(scope_games()[0])
        except AuditBlocked as exc:
            reason = str(exc)
        pairs = []
        if indexes is None:
            raw = os.environ.get("XZH_GAP_AUTH_LEVELS", "")
            indexes = [int(x)-1 for x in raw.split(",")] if raw else list(range(9))
        require(all(0 <= i < 9 for i in indexes), "授權層級必須為1～9")
        for index in indexes:
            parent, child = gap_context(index), gap_context(index+1)
            before = {g: gap_values(child.open(g)) for g in scope_games()}
            bets = []
            enabled_bets = {}
            with guarded_authorization(parent) as state:
                def enable_for_cycle():
                    state.update(attempted=True, expected=True)
                    enabled = parent.setting.set_earn_odds_gap(True)
                    assert enabled["status"] in (200, 204), "授權啟用保存失敗"
                    parent.setting.open_target(parent.level_name, parent.account, require_gap=False)
                    assert parent.setting.is_earn_odds_gap_checked() is True, "授權啟用讀回不符"
                    state["last_verified"] = True

                # 原本關閉也可驗完整開關循環，finally 必須還原成關閉。
                if not state["original"]:
                    enable_for_cycle()
                state.update(attempted=True, expected=False)
                response = parent.setting.set_earn_odds_gap(False)
                assert response["status"] in (200,204), "撤銷授權保存失敗"
                parent.setting.open_target(parent.level_name, parent.account, require_gap=False)
                assert parent.setting.is_earn_odds_gap_checked() is False, "授權撤銷讀回不符"
                state["last_verified"] = False
                child.setting.open_target(child.level_name, child.account, require_gap=False)
                visible = child.setting.has_gap_tab()
                # 若撤銷後 GET 被權限拒絕，保留「不可讀」，待恢復後核對原值。
                revoked = {}
                revoked_state = {}
                from xzh_qa.odds_gap_client import ReadOnlyApiError
                for game in scope_games():
                    try:
                        revoked_rows = child.api_rows(game)
                        revoked[game] = gap_values(revoked_rows) == before[game]
                        revoked_state[game] = [{"play": r["playTypeId"], "isEffective": r.get("isEffective")} for r in revoked_rows]
                        assert revoked[game], "撤銷授權後原差分被修改"
                    except ReadOnlyApiError as exc:
                        if exc.status != 403: raise
                        revoked[game] = "BLOCKED:403"
                if player:
                    for game in scope_games():
                        bets.append((game, submit_once(player, run, game, f"off-{index}", plans[game])))
                if not state["original"]:
                    enable_for_cycle()
                    if player:
                        for game, _ in bets:
                            enabled_bets[game] = submit_once(player, run, game, f"on-{index}", plans[game])
            after = {g: gap_values(child.open(g)) for g in scope_games()}
            assert after == before, "授權恢復後原差分未保留"
            if player:
                for game, off in bets:
                    on = enabled_bets[game] if game in enabled_bets else submit_once(player, run, game, f"on-{index}", plans[game])
                    off_r, on_r = await_records(path, day, scope_games(), [off,on], player.page, run, member_ctx)
                    for r in (off_r,on_r): verify_pricing(r)
                    assert off_r["gameId"] == on_r["gameId"] == game, "授權投注樣本彩種不符"
                    assert all(dec(x) == 0 for x in off_r["diffs"][index+1:]), "撤銷後該受益層及以下凍結差未歸零"
                    require(any(dec(x) > 0 for x in on_r["diffs"][index+1:]), "恢復後無非零有效差，無法證明恢復生效")
            pairs.append({"parent": parent.account, "child": child.account,
                          "original_authorized": state["original"],
                          "tab_when_revoked": visible, "values_when_revoked": revoked,
                          "effective_when_revoked": revoked_state,
                          "restored": after == before, "bet_validation": reason or "verified"})
            run.dump("b88-pairs.json", pairs)
        allure.attach(json.dumps(pairs,ensure_ascii=False), "B88授權與還原",allure.attachment_type.JSON)
        if reason:
            pytest.skip(f"BLOCKED（部分）：入口／原值保留已執行；投注生效未驗：{reason}")
    except AuditBlocked as exc:
        pytest.skip(f"BLOCKED：{exc}")
    finally:
        if context is not None: context.close()
