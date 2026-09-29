"""B98/B99 共用：沿 UI 下鑽、同彩種查詢、完整注單及受益層核對。"""
import json
import os
from datetime import date

import allure
import pytest

from xzh_qa.odds_gap_audit import AuditBlocked, load_audit, require, verify_live_ids, verify_settlement, zero_conditions
from xzh_qa.odds_gap_client import GAMES, OddsGapClient
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec, sum_by_level
from xzh_qa.pages.odds_gap_report_page import OddsGapReportPage
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS


def read_chain(page, day, games):
    observed = OddsGapClient.attach(page)
    report = OddsGapReportPage(page)
    report.goto()
    report.select_games([GAMES[g] for g in games])
    report.query(day, day, settled=True)
    client = OddsGapClient.from_page(page, observed)
    parent_id, amounts, member_id = None, [], None
    evidence = []
    for index, account in enumerate(CHAIN_ACCOUNTS):
        rows = client.share_report(day, day, game_ids=games, parent_id=parent_id)
        row = next((r for r in rows if r["descendantAccount"] == account), None)
        if row is None:
            allure.attach(json.dumps({"date": day, "games": games, "parentId": parent_id,
                                      "expectedAccount": account, "actualRows": rows}, ensure_ascii=False),
                          "報表樣本缺失的唯讀查詢", allure.attachment_type.JSON)
            raise AuditBlocked(f"{day} 報表缺 {account}，無完整鏈樣本")
        ui = report.gap_amount(account)
        require(row.get("oddsGapAmount") is not None, "API 缺收益欄，不視為零")
        actual = dec(row["oddsGapAmount"])
        assert ui == actual, f"{account} UI/API 金額不符：{ui}/{actual}"
        evidence.append({"beneficiary": "公司" if index == 0 else CHAIN_ACCOUNTS[index-1],
                         "descendant": account, "ui": str(ui), "api": str(actual),
                         "playerCount": row.get("playerCount"), "playerBetCount": row.get("playerBetCount"),
                         "playerBetAmount": row.get("playerBetAmount")})
        if index > 0:
            amounts.append(actual)
        if index == 9:
            member_id = row["descendantId"]
            break
        require(row.get("canDrillDown"), f"{account} 不能繼續下鑽")
        parent_id = row["descendantId"]
        report.drill_into(account)
    bets = client.all_member_bets(member_id, day, games)
    allure.attach(json.dumps({"date": day, "games": games, "levels": evidence,
                              "bets": bets}, ensure_ascii=False, default=str),
                  "完整報表範圍與受益層", allure.attachment_type.JSON)
    require(bool(bets), "完整已結算查詢範圍無注單，不能以空合計判定收益正確")
    amount = sum((dec(b["betAmount"]) for b in bets), dec(0))
    for row in evidence:
        require(row["playerCount"] == 1 and row["playerBetCount"] == len(bets)
                and row["playerBetAmount"] is not None and dec(row["playerBetAmount"]) == amount,
                f"{row['descendant']} 報表範圍不等於完整會員注單；可能含其他會員或漏單，不作部分合計比較")
    return amounts, bets


def checked_audit(page):
    day = os.environ.get("XZH_GAP_REPORT_DAY", date.today().isoformat())
    games = scope_games()
    actual, bets = read_chain(page, day, games)
    audit = load_audit(os.environ.get("XZH_GAP_FROZEN_AUDIT", ""), day, games)
    verify_live_records(audit, bets)
    # 每彩種另查完整範圍，防止跨彩種金額互相抵銷。
    for game in games:
        records = [r for r in audit["records"] if r["gameId"] == game]
        game_actual, game_bets = read_chain(page, day, [game])
        subset = {"scope": {**audit["scope"], "gameIds": [game],
                             "betIds": [r["betId"] for r in records]}, "records": records}
        verify_live_records(subset, game_bets)
        expected = sum_by_level(verify_settlement(r) for r in records)
        assert game_actual == expected, f"{game} 完整範圍九層收益不符：{game_actual}/{expected}"
    return audit, actual


def verify_live_records(audit, bets):
    """報表、A/B 與授權投注共用的完整範圍與逐注身分核對。"""
    verify_live_ids(audit, [b["serialNumber"] for b in bets])
    live = {str(b["serialNumber"]): b for b in bets}
    for record in audit["records"]:
        bet = live[str(record["betId"])]
        for a, b in (("gameId", "gameId"), ("playTypeId", "playTypeId"),
                     ("selection", "selection"), ("issue", "issueNumber")):
            require(str(record[a]) == str(bet[b]), f"{a} 與線上注單不符")
        require(dec(record["betAmount"]) == dec(bet["betAmount"]), "投注額與線上注單不符")
        require(record["outcome"] == bet["outcome"], "結算結果與線上注單不符")
        shares = {x["level"]: dec(x["shareAmount"]) for x in bet["layerShares"]}
        require(shares.get("company") == dec(record["companyShare"]), "公司凍結占成不符")
        require([shares.get(f"agent{i}") for i in range(1,10)] == [dec(x) for x in record["agentShares"]], "代理凍結占成不符")


def run_report_check(page, zero=False):
    try:
        audit, actual = checked_audit(page)
        records = audit["records"]
        results = [verify_settlement(r) for r in records]
        assert actual == sum_by_level(results), f"九層報表合計不符：{actual}"
        if zero:
            covered = {g: set() for g in scope_games()}
            for record, result in zip(records, results):
                covered[record["gameId"]].update(zero_conditions(record, result))
            required = {"輸局", "和局退本", "有效差為零", "上繳額為零"}
            require(all(v == required for v in covered.values()), f"四種零收益條件樣本未齊：{covered}")
        else:
            require(all(any(r["gameId"] == g and any(x > 0 for x in result["gap_money"])
                            for r, result in zip(records, results)) for g in scope_games()),
                    "每彩種需有應得非零收益的中獎樣本")
    except AuditBlocked as exc:
        pytest.skip(f"BLOCKED：{exc}；補齊唯讀凍結稽核來源後重跑，不以一致的零值當通過")
