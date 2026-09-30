# -*- coding: utf-8 -*-
"""B108（交接 T66）：賠率差分變更是否在「操作日志」與帳號「日志」兩個入口都查得到同一批紀錄。

用途：由 UI 整批修改差分並保存、再由 UI 改回原值後，核對兩個入口各查閱者看到的紀錄——
      每個有變動的玩法一筆，变更项／变更前值／变更后值與保存前後讀回值一致，操作者正確，
      兩入口為同一批紀錄；並在操作者與公司的畫面上展開兩批「共 N 笔」逐列比對。
使用方式（write_action，會改動 QAT 測試帳號鏈的差分並還原；QAT 寫入依 CLAUDE.md §5 已預先授權）：
    $env:XZH_GAP_LOG_VIAS="company,parent"   # 操作路徑，預設兩條都跑
    $env:XZH_GAP_LOG_LEVELS="1,2,...,10"      # 目標層級（1＝aaa111 … 10＝會員 aaa010），預設全部
    $env:XZH_GAP_GAMES="bingo6"               # 彩種，預設三彩種（沿用 scope_games）
    pytest tests/xzh/test_odds_gap_operation_log.py -m write_action
    ⚠️ 完整實跑要分段（每段 ≤5 組，例：company 1～5／6～10、parent 2～6／7～10，逐彩種）：2026-09-30 T66
       同一瀏覽器連跑到第 10 組時，公司頁兩度在點選單「用户管理」時失去回應（20 秒逾時），新開瀏覽器無法重現。
前置條件：
- 公司 aaron01 與 aaa111～aaa999 的測試密碼可用；本案例會登入公司與目標的全部上級代理，
  同帳號他處登入會互踢，執行期間不要讓其他 session 使用這些帳號。
- 整條帳號鏈共用 `odds_gap_chain_exclusive` 鎖；還原異常由 `guarded_gaps` 停手並留紀錄。
- aaa111 宾果六合彩／香港六合彩「特码A」主欄是 Snotra-019 的重現前提，不改動（見交接 §5）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import allure
import pytest

from xzh_qa.config_loader import admin_credentials
from xzh_qa.odds_gap_client import GAMES, gap_values
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_oplog import (TAIPEI, TOPIC_LABEL, AuditLogReader, compare_ui_batch, expected_records,
                                   match_expected, parse_ui_row, play_label, ui_time, unexpected_records)
from xzh_qa.odds_gap_safety import guarded_gaps, strict_gap_values
from xzh_qa.odds_gap_spec import field_inventory
from xzh_qa.pages.dashboard_page import AgentHierarchyPage
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS
from xzh_qa.pages.operation_log_page import OperationLogPage

#: 每欄在原值上再減一步，確保每個玩法都有變動且不會變成正數
DELTA = dec("-0.0001")
#: Snotra-019 保留資料：(帳號, 彩種, 玩法, 欄位) 不改動
RESERVED = {("aaa111", "bingo6", "特码A", "oddsGap"): "Snotra-019 重現前提保留（交接 §5）",
            ("aaa111", "markSix", "特码A", "oddsGap"): "Snotra-019 重現前提保留（交接 §5）"}


def _scope_vias() -> list[str]:
    raw = os.environ.get("XZH_GAP_LOG_VIAS", "company,parent")
    vias = [x.strip() for x in raw.split(",") if x.strip()]
    assert vias and set(vias) <= {"company", "parent"} and len(set(vias)) == len(vias), "XZH_GAP_LOG_VIAS 非法"
    return vias


def _scope_levels() -> set[int]:
    raw = os.environ.get("XZH_GAP_LOG_LEVELS", ",".join(str(i) for i in range(1, 11)))
    levels = {int(x) for x in raw.split(",") if x.strip()}
    assert levels and levels <= set(range(1, 11)), "XZH_GAP_LOG_LEVELS 須為 1～10"
    return levels


def _plan(ctx, game_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """依正式規格列出本次要改的每一欄（原值再減一步）；保留資料與規格缺欄另列。"""
    fields, skipped = [], []
    inventory, _coverage = field_inventory(rows)
    for entry in inventory:
        if "reason" in entry:
            skipped.append({"play": entry["play"], "field": entry["field"], "reason": entry["reason"]})
            continue
        row = rows[entry["row"]]
        reason = RESERVED.get((ctx.account, game_id, play_label(row), entry["field"]))
        if reason:
            skipped.append({"play": play_label(row), "field": entry["field"], "reason": reason})
            continue
        old = row.get(entry["field"])
        if old is None:
            skipped.append({"play": play_label(row), "field": entry["field"], "reason": "原值為空，不能猜成零"})
            continue
        fields.append({"row": entry["row"], "col": entry["col"], "play_id": row["playTypeId"],
                       "play": play_label(row), "field": entry["field"], "old": dec(old), "new": dec(old) + DELTA})
    return fields, skipped


def _change_and_restore(ctx, game_id: str) -> dict:
    """UI 修改全部可測欄並保存 → 讀回 → UI 改回原值並保存（guarded_gaps 收尾）→ 讀回。"""
    rows_before = ctx.open(game_id)
    plan, skipped = _plan(ctx, game_id, rows_before)
    assert plan, "沒有可改動的欄位"
    since = datetime.now(TAIPEI)
    with guarded_gaps(ctx, game_id, rows_before) as transaction:
        for item in plan:
            item["after_input"] = ctx.setting.set_value(item["row"], item["col"], item["new"])
        transaction["expected"] = {(i["play_id"], i["field"]): i["after_input"] for i in plan}
        transaction["attempted"] = True
        saved = ctx.setting.save()
        bounced = ctx.setting.bounced_to_login()
        rows_after = ctx.api_rows(game_id)
    rows_final = ctx.api_rows(game_id)
    until = datetime.now(TAIPEI)
    after_values = gap_values(rows_after)
    not_saved = [f"{i['play']}／{'副差分' if i['col'] else '差分'}：輸入 {i['new']}，讀回 {after_values.get((i['play_id'], i['field']))}"
                 for i in plan if after_values.get((i["play_id"], i["field"])) != i["new"]]
    return {"rows_before": rows_before, "rows_after": rows_after, "rows_final": rows_final,
            "plan": plan, "skipped": skipped, "since": since, "until": until,
            "save_status": saved["status"], "bounced": bounced, "not_saved": not_saved,
            "restored": transaction["restored"],
            "restore_equal": strict_gap_values(rows_final) == strict_gap_values(rows_before)}


def _api_check(page, *, day, change, operator, account, game_name, target_user_id,
               expected_set, expected_restore) -> dict:
    """單一查閱者、兩個入口：逐筆比對兩次保存，並核對兩入口是同一批紀錄。"""
    reader = AuditLogReader(page)
    out = {}
    for entry, uid in (("操作日志", None), ("帳號日志", target_user_id)):
        records = reader.records(day, change["since"], change["until"], operator=operator, account=account,
                                 game_name=game_name, target_user_id=uid)
        set_match = match_expected(expected_set, records, operator)
        restore_match = match_expected(expected_restore, records, operator)
        out[entry] = {"records": records, "set": set_match, "restore": restore_match,
                      "unexpected": unexpected_records(records, set_match, restore_match)}
    ids = {entry: ({k: r["id"] for k, r in v["set"]["matched"].items()},
                   {k: r["id"] for k, r in v["restore"]["matched"].items()}) for entry, v in out.items()}
    out["same_records"] = ids["操作日志"] == ids["帳號日志"]
    return out


def _ui_check(page, *, entry, account, level_name, game_name, batches) -> list[str]:
    """在畫面上篩選「赔率差分设定」，展開本次兩批並與同一查閱者的 API 紀錄逐列比對。"""
    log_page = OperationLogPage(page)
    if entry == "操作日志":
        log_page.goto()
    else:
        hierarchy = AgentHierarchyPage(page)
        hierarchy.goto()
        hierarchy.switch_tab(level_name)
        hierarchy.search_account(account)
        hierarchy.open_logs_page(account)
    log_page.select_type(TOPIC_LABEL)
    problems = []
    for label, records in batches:
        head = next((r for r in records if r["id"] == r["head"]), None)
        if head is None:
            problems.append(f"{label}：API 沒有這批的代表紀錄，無法在畫面定位")
            continue
        time_text = ui_time(head["head_at"])
        if head["batch_count"] > 1:
            log_page.expand_batch(head["raw_entity"], time_text)
        cells = log_page.batch_cells(head["raw_entity"], time_text)
        if cells is None:
            problems.append(f"{label}：第 1 頁找不到「{head['raw_entity']}」{time_text} 這一列")
            continue
        ui_rows = [parse_ui_row(c) for c in cells]
        bad_type = [r["type"] for r in ui_rows if r["type"] != TOPIC_LABEL or r["action"] != "修改"]
        if bad_type:
            problems.append(f"{label}：类型／操作动作不是「{TOPIC_LABEL}／修改」：{sorted(set(bad_type))}")
        problems += [f"{label}：{p}" for p in compare_ui_batch(
            ui_rows, records, account=account if entry == "操作日志" else None)]
    return problems


def _describe(group: dict) -> str:
    lines = [f"彩種：{group['game']}｜目標：{group['account']}｜操作者：{group['operator']}（{group['via']}）",
             f"改動欄位 {group['planned']} 欄、應有紀錄：修改 {group['expected_set']} 筆／改回 {group['expected_restore']} 筆；"
             f"保存 HTTP {group['save_status']}，還原{'一致' if group['restore_equal'] else '不一致'}",
             f"未改動：{json.dumps(group['skipped'], ensure_ascii=False) if group['skipped'] else '無'}"]
    for viewer, result in group["viewers"].items():
        for entry in ("操作日志", "帳號日志"):
            r = result[entry]
            lines.append(f"- 查閱者 {viewer}｜{entry}：修改 {len(r['set']['matched'])}/{group['expected_set']}、"
                         f"改回 {len(r['restore']['matched'])}/{group['expected_restore']}、"
                         f"缺 {len(r['set']['missing']) + len(r['restore']['missing'])}、"
                         f"值不符 {len(r['set']['mismatched']) + len(r['restore']['mismatched'])}、"
                         f"多出 {len(r['unexpected'])}")
        lines.append(f"- 查閱者 {viewer}｜兩入口為同一批紀錄：{'是' if result['same_records'] else '否'}")
    for viewer, problems in group["ui"].items():
        lines.append(f"- 畫面抽查 {viewer}：{'一致' if not problems else '；'.join(problems[:6])}")
    return "\n".join(lines)


def _failures(group: dict) -> list[str]:
    tag = f"{group['game']}／{group['account']}（{group['operator']}）"
    out = []
    if group["save_status"] not in (200, 204) or group["bounced"]:
        out.append(f"{tag}：保存失敗 HTTP {group['save_status']}，跳登入={group['bounced']}")
    out += [f"{tag}：{x}" for x in group["not_saved"][:5]]
    if not group["restore_equal"]:
        out.append(f"{tag}：改回原值後讀回與原值不一致")
    for viewer, result in group["viewers"].items():
        for entry in ("操作日志", "帳號日志"):
            r = result[entry]
            for kind in ("set", "restore"):
                label = "修改" if kind == "set" else "改回"
                for item in r[kind]["missing"][:3]:
                    out.append(f"{tag}：{viewer}「{entry}」查無「{item['entity']}」的{label}紀錄")
                for item in r[kind]["mismatched"][:3]:
                    out.append(f"{tag}：{viewer}「{entry}」「{item['entity']}」{label}紀錄{item['reason']}")
                for item in r[kind]["duplicated"][:3]:
                    out.append(f"{tag}：{viewer}「{entry}」「{item['entity']}」{label}紀錄重複 {item['ids']}")
            for item in r["unexpected"][:3]:
                out.append(f"{tag}：{viewer}「{entry}」多出未改動玩法的紀錄「{item['entity']}」{item['fields']}")
        if not result["same_records"]:
            out.append(f"{tag}：{viewer} 的兩個入口不是同一批紀錄")
    for viewer, problems in group["ui"].items():
        out += [f"{tag}：畫面（{viewer}）{p}" for p in problems[:3]]
    return out


@allure.suite("赔率差分")
@allure.sub_suite("操作日志")
@allure.title('[功能驗證] B108：赔率差分：修改並保存差分、再改回原值後，「操作日志」與帳號「日志」是否都查得到每個玩法的變更前後值')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
def test_odds_gap_change_recorded_in_both_log_entries(gap_context, odds_gap_login, odds_gap_run):
    """平台案例：[功能驗證] B108：赔率差分：修改並保存差分、再改回原值後，「操作日志」與帳號「日志」是否都查得到每個玩法的變更前後值
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；會改動測試帳號鏈的差分並改回原值（QAT 寫入已預先授權）。
    - 環境：QAT；公司 aaron01 與 aaa111～aaa999 可登入；執行期間不讓其他 session 使用這些帳號（同帳號互踢）。
    - 來源：新綜合_賠率差分設定頁規格.md「操作日誌」（Aaron 2026-09-29 確認）；交接 T66。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 操作路徑：公司修改 aaa111～aaa999 與會員 aaa010（10 組）；各層代理修改直屬下級 aaa111→aaa222～aaa999→aaa010（9 組）。
    - 查閱者：公司，以及目標帳號的每一層上級代理（兩個入口都核對）；畫面逐列比對由操作者與公司進行。
    - 設定列（正式規格 101 列）：特码A／特码B／正码／正特码A／正特码B／六肖／两面／特肖／五行／生肖中／生肖不中／尾数中／尾数不中／二全中／二中特／二特串／三全中／三中二／四全中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六／红单／红双／红大／红小／红波／蓝单／蓝双／蓝大／蓝小／蓝波／绿单／绿双／绿大／绿小／绿波。
    - 主副欄：每列主欄；下列另含副欄：特肖／五行／生肖中／生肖不中／尾数中／尾数不中／二中特／三中二／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中。共 116 欄。
    - 不改動：aaa111 的宾果六合彩、香港六合彩「特码A」主欄（Snotra-019 重現前提保留）；其餘層級照常覆蓋。
    步驟：
    1. 操作者進入用户管理 → 目標帳號「编辑」→「赔率差分」並切換彩種，將測試範圍所列每一欄改為原值再減 0.0001 後點「保存」，讀回保存值；再把每一欄改回原值並點「保存」。
    2. 查閱者進入「操作日志」，「类型」選「赔率差分设定」，展開本次兩批「共 N 笔」，核對每個玩法的目标、变更项、变更前值、变更后值與操作者。
    3. 查閱者進入用户管理 → 目標帳號的「日志」，「类型」選「赔率差分设定」，同樣展開核對，並確認與「操作日志」是同一批紀錄。
    預期結果：
    - 修改與改回各產生一批紀錄，每個有變動的玩法一筆；目标為「帳號 / 彩種 / 玩法」（帳號「日志」頁為「彩種 / 玩法」），七碼記代表列（如「单0」）。
    - 变更项只列有變動的「差分」「副差分」；变更前值與变更后值等於保存前、保存後讀回值；操作者為實際操作帳號；类型「赔率差分设定」、操作动作「修改」。
    - 公司與目標的每一層上級，在兩個入口都查得到同兩批紀錄；沒有變動的玩法不出現紀錄。
    佐證方式：
    - 逐組附件：應有／實際筆數、缺漏、值不符、多出、兩入口是否為同一批紀錄、畫面逐列比對結果；完整比對資料存於本次執行目錄。
    已知問題：
    - 同值保存、保存失敗是否留紀錄、多欄保存如何分筆、授權開關是否歸同一類型：規格未定，不列入判準。
    - 公司以外的上級代理以畫面背後同一支查詢核對，畫面逐列比對只由操作者與公司進行。
    """
    company_account = admin_credentials()[0]
    day = datetime.now(TAIPEI).date().isoformat()
    games, vias, levels = scope_games(), _scope_vias(), _scope_levels()
    # 分段執行時各段是同一個 nodeid；帶上範圍參數，allure 才不會把不同段當成同一案例的重試而隱藏
    allure.dynamic.parameter("彩種", "、".join(GAMES[g] for g in games))
    allure.dynamic.parameter("操作路徑", "、".join(vias))
    allure.dynamic.parameter("目標層級", ",".join(str(x) for x in sorted(levels)))
    allure.attach(f"操作路徑：{'、'.join(vias)}\n目標層級：{sorted(levels)}\n彩種：{'、'.join(GAMES[g] for g in games)}",
                  name="本次執行範圍", attachment_type=allure.attachment_type.TEXT)
    groups, failures = [], []
    for via in vias:
        for index in range(0 if via == "company" else 1, 10):
            if index + 1 not in levels:
                continue
            ctx = gap_context(index, via=via)
            operator = company_account if via == "company" or index == 0 else CHAIN_ACCOUNTS[index - 1]
            company_page = odds_gap_login("__company__")
            viewers = {company_account: company_page}
            viewers.update({CHAIN_ACCOUNTS[j]: odds_gap_login(CHAIN_ACCOUNTS[j]) for j in range(index)})
            for game_id in games:
                game_name = GAMES[game_id]
                with allure.step("操作者修改測試範圍所列每一欄並保存、讀回，再改回原值並保存"):
                    change = _change_and_restore(ctx, game_id)
                expected_set = expected_records(change["rows_before"], change["rows_after"], game_name)
                expected_restore = expected_records(change["rows_after"], change["rows_final"], game_name)
                group = {"via": via, "account": ctx.account, "operator": operator, "game": game_name,
                         "planned": len(change["plan"]), "skipped": change["skipped"],
                         "expected_set": len(expected_set), "expected_restore": len(expected_restore),
                         "save_status": change["save_status"], "bounced": change["bounced"],
                         "not_saved": change["not_saved"], "restore_equal": change["restore_equal"],
                         "viewers": {}, "ui": {}}
                with allure.step("各查閱者讀取「操作日志」與帳號「日志」的赔率差分设定紀錄並逐筆比對"):
                    for viewer, page in viewers.items():
                        group["viewers"][viewer] = _api_check(
                            page, day=day, change=change, operator=operator, account=ctx.account,
                            game_name=game_name, target_user_id=ctx.target_user_id,
                            expected_set=expected_set, expected_restore=expected_restore)
                with allure.step("操作者與公司在畫面上展開本次兩批紀錄並逐列比對"):
                    for viewer in dict.fromkeys([operator, company_account]):
                        result = group["viewers"][viewer]
                        problems = []
                        for entry in ("操作日志", "帳號日志"):
                            batches = [("修改", list(result[entry]["set"]["matched"].values())),
                                       ("改回", list(result[entry]["restore"]["matched"].values()))]
                            problems += [f"「{entry}」{p}" for p in _ui_check(
                                viewers[viewer], entry=entry, account=ctx.account, level_name=ctx.level_name,
                                game_name=game_name, batches=batches)]
                        group["ui"][viewer] = problems
                odds_gap_run.dump(f"oplog-{via}-{ctx.account}-{game_id}.json", {
                    **{k: v for k, v in group.items() if k != "viewers"},
                    "plan": change["plan"],
                    "viewers": {v: {e: {"set": r[e]["set"], "restore": r[e]["restore"], "unexpected": r[e]["unexpected"]}
                                    for e in ("操作日志", "帳號日志")} | {"same_records": r["same_records"]}
                                for v, r in group["viewers"].items()}})
                allure.attach(_describe(group), name="單組比對結果", attachment_type=allure.attachment_type.TEXT)
                failures += _failures(group)
                groups.append(group)
    summary = [f"共 {len(groups)} 組（操作路徑×目標×彩種）；失敗項 {len(failures)}"]
    summary += [f"- {g['game']}／{g['account']}（{g['operator']}）：改動 {g['planned']} 欄、紀錄 {g['expected_set']}＋{g['expected_restore']} 筆"
                for g in groups]
    allure.attach("\n".join(summary), name="執行總覽", attachment_type=allure.attachment_type.TEXT)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures[:40])
