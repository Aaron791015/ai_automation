# -*- coding: utf-8 -*-
"""B108（交接 T66）：賠率差分變更是否在「操作日志」與帳號「日志」兩個入口都查得到同一批紀錄。
B109～B111（2026-09-30）：操作日誌四項邊界規格——同值保存、保存失敗不留紀錄；授權開關記在「账号」類型。

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
from collections import Counter
from datetime import datetime

import allure
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from xzh_qa.config_loader import admin_credentials
from xzh_qa.odds_gap_client import GAMES, gap_values
from xzh_qa.odds_gap_flows import scope_games
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_oplog import (ACCOUNT_TOPIC, ACCOUNT_TOPIC_LABEL, EARN_ODDS_GAP, PERMISSION_FIELD, TAIPEI,
                                   TOPIC, TOPIC_LABEL, AuditLogReader, compare_ui_batch, expected_records, for_target,
                                   match_expected, normalize, parse_ui_row, permission_change, play_label, ui_time,
                                   unexpected_records)
from xzh_qa.odds_gap_safety import guarded_authorization, guarded_gaps, strict_gap_values
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
    - 多欄保存的分筆方式（一次保存一批、每玩法一筆、主副同筆）即本案例判準；同值保存、保存失敗、授權開關的紀錄規則另由 B109～B111 驗證（2026-09-30 Aaron 裁定規格）。
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


# ---------------------------------------------------------------------------
# B109～B111：操作日誌四項邊界（2026-09-30 Aaron 裁定「就以這樣當規格」，見設定頁規格「操作日誌」）
# 「應該沒有紀錄」一律以紀錄 id 判定（操作前記下最大 id，之後只看比它大的），不靠時間窗；
# 並在同一彩種做一組「改後保存、改回保存」對照，證明同樣的查法查得到新紀錄，0 筆才作數。
# ---------------------------------------------------------------------------

#: B109／B110 的目標：二級 aaa222。一級 aaa111 的特码A 是 Snotra-019 保留資料，避開。
BOUNDARY_TARGET = 1
#: B110 用來讓保存失敗的輸入（差分不得為正，B91）
POSITIVE_INPUT = "1"
#: 下級仍開啟時取消上級授權的拒絕提示（Snotra-012 已修復後的正式行為）
REJECT_MESSAGE = "下级已允许赚取赔率差，请先修改下级"


def _field_name(item: dict) -> str:
    return f"{item['play']}／{'副差分' if item['col'] else '差分'}"


def _viewer_pages(odds_gap_login, company_account: str) -> dict:
    """查閱者：公司，以及目標 aaa222 的上級 aaa111。"""
    return {company_account: odds_gap_login("__company__"), CHAIN_ACCOUNTS[0]: odds_gap_login(CHAIN_ACCOUNTS[0])}


def _new_for_target(pages: dict, day: str, mark: int, *, account: str, game_name: str | None,
                    target_user_id: int, topic: str = TOPIC) -> dict:
    """每位查閱者、兩個入口：id 大於 mark 且屬於該帳號（彩種）的紀錄。"""
    out = {}
    for viewer, page in pages.items():
        reader = AuditLogReader(page)
        for entry, uid in (("操作日志", None), ("帳號日志", target_user_id)):
            items = reader.records_after(day, mark, topic=topic, target_user_id=uid)
            out[f"{viewer}｜{entry}"] = for_target(items, account, game_name, scoped=uid is not None)
    return out


def _ui_latest(pages: dict, type_label: str, prefix: str) -> dict:
    """各查閱者在「操作日志」選定類型後，目标以 prefix 開頭的最新一列（沒有則 None）。"""
    out = {}
    for viewer, page in pages.items():
        log_page = OperationLogPage(page)
        log_page.open_fresh()
        log_page.select_type(type_label)
        rows = log_page.rows_for(prefix)
        out[viewer] = rows[0] if rows else None
    return out


def _control_pair(ctx, game_id: str, game_name: str, pages: dict, day: str, operator: str) -> dict:
    """對照組：第一個可改欄改成原值減一步並保存、再改回原值並保存——規格「中途有保存則每次各記一筆」。"""
    rows = ctx.open(game_id)
    plan, _ = _plan(ctx, game_id, rows)
    item = plan[0]
    mark = AuditLogReader(next(iter(pages.values()))).latest_id(day)
    with guarded_gaps(ctx, game_id, rows) as transaction:
        after = ctx.setting.set_value(item["row"], item["col"], item["new"])
        transaction["expected"] = {(item["play_id"], item["field"]): after}
        transaction["attempted"] = True
        saved = ctx.setting.save()
        rows_mid = ctx.api_rows(game_id)
    rows_final = ctx.api_rows(game_id)
    expected_set = expected_records(rows, rows_mid, game_name)
    expected_restore = expected_records(rows_mid, rows_final, game_name)
    found = _new_for_target(pages, day, mark, account=ctx.account, game_name=game_name,
                            target_user_id=ctx.target_user_id)
    results = {}
    for key, items in found.items():
        scoped = key.endswith("帳號日志")
        records = [normalize(i, None if scoped else ctx.account) for i in items]
        m_set, m_restore = match_expected(expected_set, records, operator), match_expected(expected_restore, records, operator)
        results[key] = {"count": len(records), "set_ok": m_set["ok"], "restore_ok": m_restore["ok"],
                        "unexpected": [r["entity"] for r in unexpected_records(records, m_set, m_restore)],
                        "latest": max(records, key=lambda r: r["id"]) if records else None}
    return {"field": _field_name(item), "old": item["old"], "new": item["new"], "save_status": saved["status"],
            "restored": transaction["restored"], "expected": len(expected_set) + len(expected_restore),
            "results": results}


def _control_failures(tag: str, control: dict, ui_control: dict, company_account: str) -> list[str]:
    out = []
    if control["expected"] != 2 or not control["restored"]:
        out.append(f"{tag}：對照組「{control['field']}」保存 HTTP {control['save_status']}、"
                   f"改回{'成功' if control['restored'] else '失敗'}，應有紀錄 {control['expected']} 筆（應為 2）")
    for key, r in control["results"].items():
        if r["count"] != 2 or not (r["set_ok"] and r["restore_ok"]) or r["unexpected"]:
            out.append(f"{tag}：對照組 {key} 查到 {r['count']} 筆（應為 2 筆且前後值相符），本組「0 筆」不能作數")
    latest = control["results"].get(f"{company_account}｜操作日志", {}).get("latest")
    for viewer, cells in ui_control.items():
        want = (latest["raw_entity"], ui_time(latest["at"])) if latest else None
        got = (cells[3], cells[9]) if cells else None
        if want is None or got != want:
            out.append(f"{tag}：對照組畫面（{viewer}）最新一列 {got}，應為 {want}")
    return out


def _zero_failures(tag: str, found: dict, ui_before: dict, ui_after: dict) -> list[str]:
    out = []
    for key, items in found.items():
        for item in items[:3]:
            out.append(f"{tag}：{key} 出現紀錄「{item.get('entityId')}」{item.get('fields')} "
                       f"{item.get('beforeValues')}→{item.get('afterValues')}（操作者 {item.get('operatorAccount')}），應為 0 筆")
    for viewer, cells in ui_after.items():
        before = ui_before.get(viewer)
        if cells != before:
            out.append(f"{tag}：畫面（{viewer}）目標帳號本彩種最新一列由 {before and before[3:10]} "
                       f"變成 {cells and cells[3:10]}，應不變")
    return out


def _zero_lines(found: dict) -> list[str]:
    return [f"- {key}：新增 {len(items)} 筆（應為 0）" for key, items in found.items()]


def _control_lines(control: dict) -> list[str]:
    lines = [f"對照組「{control['field']}」{control['old']}→{control['new']}→{control['old']}，"
             f"兩次保存（第一次 HTTP {control['save_status']}），應各記一筆共 2 筆："]
    lines += [f"- {key}：{r['count']} 筆，修改{'相符' if r['set_ok'] else '不符'}、"
              f"改回{'相符' if r['restore_ok'] else '不符'}、多出 {len(r['unexpected'])}"
              for key, r in control["results"].items()]
    return lines


def _unchanged_saves(ctx, game_id: str) -> dict:
    """(a) 不改任何值直接保存；(b) 每欄改成原值減一步、再改回原值，全部改完才保存一次。"""
    rows = ctx.open(game_id)
    plan, skipped = _plan(ctx, game_id, rows)
    out = {"planned": len(plan), "skipped": skipped, "input_problems": []}
    with guarded_gaps(ctx, game_id, rows) as transaction:
        transaction["attempted"] = True
        out["plain_status"] = ctx.setting.save(allow_no_request=True)["status"]
        out["plain_equal"] = strict_gap_values(ctx.api_rows(game_id)) == strict_gap_values(rows)
    rows = ctx.open(game_id)
    with guarded_gaps(ctx, game_id, rows) as transaction:
        for item in plan:
            middle = ctx.setting.set_value(item["row"], item["col"], item["new"])
            final = ctx.setting.set_value(item["row"], item["col"], item["old"])
            if middle != item["new"] or final != item["old"]:
                out["input_problems"].append(f"{_field_name(item)}：改成 {middle}、改回 {final}（原值 {item['old']}）")
        transaction["expected"] = {(i["play_id"], i["field"]): i["new"] for i in plan}
        transaction["attempted"] = True
        out["edited_status"] = ctx.setting.save(allow_no_request=True)["status"]
        out["edited_equal"] = strict_gap_values(ctx.api_rows(game_id)) == strict_gap_values(rows)
    return out


def _failed_save(ctx, game_id: str) -> dict:
    """每欄輸入正數後保存一次；差分不得為正（B91），保存應未成功、設定不變。"""
    rows = ctx.open(game_id)
    plan, skipped = _plan(ctx, game_id, rows)
    focus = []
    with guarded_gaps(ctx, game_id, rows) as transaction:
        for item in plan:
            after = ctx.setting.fill_raw(item["row"], item["col"], POSITIVE_INPUT)
            focus.append(after)
            try:
                transaction["expected"][(item["play_id"], item["field"])] = dec(after)
            except Exception:
                pass
        transaction["attempted"] = True
        saved = ctx.setting.save(allow_no_request=True)
        messages = ctx.setting.messages()
        bounced = ctx.setting.bounced_to_login()
        ctx.setting.reload_tab(game_id)
        unchanged = strict_gap_values(ctx.api_rows(game_id)) == strict_gap_values(rows)
    return {"planned": len(plan), "skipped": skipped, "save_status": saved["status"],
            "save_body": (saved["body"] or "")[:300], "messages": messages, "bounced": bounced,
            "unchanged": unchanged, "after_focus": dict(Counter(focus)), "restored": transaction["restored"]}


def _describe_zero_group(head: list[str], found: dict, ui_before: dict, ui_after: dict, control: dict,
                         failures: list[str]) -> str:
    lines = head + ["步驟 1 之後新增紀錄（實際 vs 期望 0）："] + _zero_lines(found)
    lines += [f"- 畫面（{v}）最新一列前後{'相同' if ui_after[v] == ui_before.get(v) else '不同'}（期望相同）" for v in ui_after]
    lines += _control_lines(control)
    return "\n".join(lines + ["判定：" + ("通過" if not failures else "；".join(failures[:5]))])


@allure.suite("赔率差分")
@allure.sub_suite("操作日志")
@allure.title('[功能驗證] B109：赔率差分：未改值直接保存、或改過又改回原值才保存時，「操作日志」與帳號「日志」是否都不產生紀錄')
@allure.severity(allure.severity_level.NORMAL)
@pytest.mark.write_action
def test_odds_gap_unchanged_save_not_logged(gap_context, odds_gap_login, odds_gap_run):
    """平台案例：[功能驗證] B109：赔率差分：未改值直接保存、或改過又改回原值才保存時，「操作日志」與帳號「日志」是否都不產生紀錄
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；對照組會改動一欄差分再改回原值（QAT 寫入已預先授權）。
    - 環境：QAT；公司 aaron01 與 aaa111 可登入；執行期間不讓其他 session 使用這些帳號（同帳號互踢）。
    - 來源：新綜合_賠率差分設定頁規格.md「操作日誌」四項邊界規格（Aaron 2026-09-30 裁定）。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 操作路徑：公司修改二級代理 aaa222；一級代理 aaa111 修改直屬下級 aaa222。各層級的保存與紀錄方式由 B108 涵蓋，本案例只驗值沒有變動的保存。
    - 查閱者：公司與 aaa111，「操作日志」與帳號「日志」兩個入口都核對；畫面由操作者與公司核對。
    - 設定列（正式規格 101 列）：特码A／特码B／正码／正特码A／正特码B／六肖／两面／特肖／五行／生肖中／生肖不中／尾数中／尾数不中／二全中／二中特／二特串／三全中／三中二／四全中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六／红单／红双／红大／红小／红波／蓝单／蓝双／蓝大／蓝小／蓝波／绿单／绿双／绿大／绿小／绿波。
    - 主副欄：每列主欄；下列另含副欄：特肖／五行／生肖中／生肖不中／尾数中／尾数不中／二中特／三中二／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中。共 116 欄。
    - 對照組：每彩種第一個設定列（特码A）主欄改後保存、改回再保存一次，證明同樣的查法查得到新紀錄。
    步驟：
    1. 操作者進入用户管理 → aaa222「编辑」→「赔率差分」並切換彩種，不改任何值直接點「保存」；再把測試範圍所列每一欄改成原值減 0.0001、按 Tab 後改回原值，全部改完才點「保存」。
    2. 查閱者進入「操作日志」與 aaa222 的「日志」，「类型」選「赔率差分设定」，查看步驟 1 之後是否出現 aaa222 本彩種的新紀錄。
    3. 對照：特码A 主欄改成原值減 0.0001 並點「保存」，再改回原值並點「保存」，查看兩個入口是否各出現 2 筆。
    預期結果：
    - 步驟 1 兩次保存後讀回值皆與原值相同；兩個入口都沒有 aaa222 本彩種的新紀錄，「操作日志」畫面上該帳號本彩種最新一列不變。
    - 對照組兩次保存各記一筆（「原值→原值減 0.0001」「原值減 0.0001→原值」），兩個入口都查得到，畫面最新一列為改回的那一筆。
    佐證方式：
    - 逐組附件：兩次保存的回應與讀回結果、各查閱者各入口新增筆數、畫面最新一列前後對照、對照組筆數與前後值；比對資料存於本次執行目錄。
    已知問題：
    - 「值沒有變動」以伺服器讀回值判定；中途改過的值只存在輸入框、沒有送到伺服器。
    """
    company_account = admin_credentials()[0]
    day = datetime.now(TAIPEI).date().isoformat()
    games, vias = scope_games(), _scope_vias()
    allure.dynamic.parameter("彩種", "、".join(GAMES[g] for g in games))
    allure.dynamic.parameter("操作路徑", "、".join(vias))
    groups, failures = [], []
    for via in vias:
        ctx = gap_context(BOUNDARY_TARGET, via=via)
        operator = company_account if via == "company" else CHAIN_ACCOUNTS[0]
        pages = _viewer_pages(odds_gap_login, company_account)
        ui_pages = {v: pages[v] for v in dict.fromkeys([operator, company_account])}
        for game_id in games:
            game_name = GAMES[game_id]
            prefix = f"{ctx.account} / {game_name} / "
            tag = f"{game_name}／{ctx.account}（{operator}）"
            with allure.step("操作者與公司進入「操作日志」，「类型」選「赔率差分设定」，記下 aaa222 本彩種最新一列"):
                ui_before = _ui_latest(ui_pages, TOPIC_LABEL, prefix)
            mark = AuditLogReader(pages[company_account]).latest_id(day)
            with allure.step("操作者進入 aaa222「赔率差分」，不改值直接點「保存」；再把每一欄改成原值減 0.0001、按 Tab 後改回原值，全部改完才點「保存」"):
                same = _unchanged_saves(ctx, game_id)
            with allure.step("公司與 aaa111 讀取「操作日志」與 aaa222「日志」中步驟之後新增的 aaa222 本彩種紀錄"):
                found = _new_for_target(pages, day, mark, account=ctx.account, game_name=game_name,
                                        target_user_id=ctx.target_user_id)
            with allure.step("操作者與公司重新進入「操作日志」，「类型」選「赔率差分设定」，核對 aaa222 本彩種最新一列是否不變"):
                ui_after = _ui_latest(ui_pages, TOPIC_LABEL, prefix)
            with allure.step("對照組：特码A 主欄改成原值減 0.0001 並點「保存」，再改回原值並點「保存」，核對兩入口各有 2 筆且畫面最新一列為改回的那筆"):
                control = _control_pair(ctx, game_id, game_name, pages, day, operator)
                ui_control = _ui_latest(ui_pages, TOPIC_LABEL, prefix)
            group_failures = []
            if same["plain_status"] not in (None, 200, 204) or same["edited_status"] not in (None, 200, 204):
                group_failures.append(f"{tag}：保存回應 HTTP {same['plain_status']}／{same['edited_status']}（應為成功或未送出）")
            if not (same["plain_equal"] and same["edited_equal"]):
                group_failures.append(f"{tag}：保存後讀回值與原值不同（不改值：{same['plain_equal']}；改回原值：{same['edited_equal']}）")
            group_failures += [f"{tag}：輸入框 {x}" for x in same["input_problems"][:5]]
            group_failures += _zero_failures(tag, found, ui_before, ui_after)
            group_failures += _control_failures(tag, control, ui_control, company_account)
            head = [f"彩種：{game_name}｜目標：{ctx.account}｜操作者：{operator}（{via}）",
                    f"不改值直接保存：HTTP {same['plain_status']}（None＝畫面未送出），讀回{'等於' if same['plain_equal'] else '不等於'}原值（期望等於）",
                    f"{same['planned']} 欄改成原值減 0.0001 再改回、最後保存：HTTP {same['edited_status']}，"
                    f"讀回{'等於' if same['edited_equal'] else '不等於'}原值（期望等於）；輸入框異常 {len(same['input_problems'])} 欄",
                    f"未改動：{json.dumps(same['skipped'], ensure_ascii=False) if same['skipped'] else '無'}"]
            allure.attach(_describe_zero_group(head, found, ui_before, ui_after, control, group_failures),
                          name="單組比對結果", attachment_type=allure.attachment_type.TEXT)
            odds_gap_run.dump(f"b109-{via}-{game_id}.json", {"same": same, "found": found, "ui_before": ui_before,
                                                             "ui_after": ui_after, "control": control, "ui_control": ui_control})
            groups.append(tag)
            failures += group_failures
    allure.attach(f"共 {len(groups)} 組：{'、'.join(groups)}；失敗項 {len(failures)}", name="執行總覽",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures[:40])


@allure.suite("赔率差分")
@allure.sub_suite("操作日志")
@allure.title('[邊界驗證] B110：赔率差分：輸入正數而保存未成功時，「操作日志」與帳號「日志」是否都不產生紀錄')
@allure.severity(allure.severity_level.NORMAL)
@pytest.mark.write_action
def test_odds_gap_failed_save_not_logged(gap_context, odds_gap_login, odds_gap_run):
    """平台案例：[邊界驗證] B110：赔率差分：輸入正數而保存未成功時，「操作日志」與帳號「日志」是否都不產生紀錄
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；對照組會改動一欄差分再改回原值（QAT 寫入已預先授權）。
    - 環境：QAT；公司 aaron01 與 aaa111 可登入；執行期間不讓其他 session 使用這些帳號（同帳號互踢）。
    - 來源：新綜合_賠率差分設定頁規格.md「操作日誌」四項邊界規格（Aaron 2026-09-30 裁定）；差分不得為正（B91）。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 操作路徑：公司修改二級代理 aaa222；一級代理 aaa111 修改直屬下級 aaa222。
    - 查閱者：公司與 aaa111，「操作日志」與帳號「日志」兩個入口都核對；畫面由操作者與公司核對。
    - 設定列（正式規格 101 列）：特码A／特码B／正码／正特码A／正特码B／六肖／两面／特肖／五行／生肖中／生肖不中／尾数中／尾数不中／二全中／二中特／二特串／三全中／三中二／四全中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六／红单／红双／红大／红小／红波／蓝单／蓝双／蓝大／蓝小／蓝波／绿单／绿双／绿大／绿小／绿波。
    - 主副欄：每列主欄；下列另含副欄：特肖／五行／生肖中／生肖不中／尾数中／尾数不中／二中特／三中二／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中。共 116 欄。 每一欄都輸入正數 1 後保存一次。
    - 對照組：每彩種第一個設定列（特码A）主欄改後保存、改回再保存一次，證明同樣的查法查得到新紀錄。
    - 公司保存下級回 403 的失敗（Snotra-006）已修復，無法再由 UI 重現；其歷史日誌核對見規格。
    步驟：
    1. 操作者進入用户管理 → aaa222「编辑」→「赔率差分」並切換彩種，把測試範圍所列每一欄輸入 1、按 Tab 後點「保存」，重新整理頁面讀回。
    2. 查閱者進入「操作日志」與 aaa222 的「日志」，「类型」選「赔率差分设定」，查看步驟 1 之後是否出現 aaa222 本彩種的新紀錄。
    3. 對照：特码A 主欄改成原值減 0.0001 並點「保存」，再改回原值並點「保存」，查看兩個入口是否各出現 2 筆。
    預期結果：
    - 步驟 1 保存未成功（畫面未送出或回應失敗），重新整理後每一欄仍為原值。
    - 兩個入口都沒有 aaa222 本彩種的新紀錄，「操作日志」畫面上該帳號本彩種最新一列不變；對照組兩個入口各查得到 2 筆。
    佐證方式：
    - 逐組附件：保存回應／提示、失焦後輸入框的值、讀回結果、各查閱者各入口新增筆數、畫面最新一列前後對照、對照組筆數；比對資料存於本次執行目錄。
    已知問題：
    - 若正數被保存成功，屬 B91 的正數規則缺陷，本案例同時列失敗並保留佐證。
    """
    company_account = admin_credentials()[0]
    day = datetime.now(TAIPEI).date().isoformat()
    games, vias = scope_games(), _scope_vias()
    allure.dynamic.parameter("彩種", "、".join(GAMES[g] for g in games))
    allure.dynamic.parameter("操作路徑", "、".join(vias))
    groups, failures = [], []
    for via in vias:
        ctx = gap_context(BOUNDARY_TARGET, via=via)
        operator = company_account if via == "company" else CHAIN_ACCOUNTS[0]
        pages = _viewer_pages(odds_gap_login, company_account)
        ui_pages = {v: pages[v] for v in dict.fromkeys([operator, company_account])}
        for game_id in games:
            game_name = GAMES[game_id]
            prefix = f"{ctx.account} / {game_name} / "
            tag = f"{game_name}／{ctx.account}（{operator}）"
            with allure.step("操作者與公司進入「操作日志」，「类型」選「赔率差分设定」，記下 aaa222 本彩種最新一列"):
                ui_before = _ui_latest(ui_pages, TOPIC_LABEL, prefix)
            mark = AuditLogReader(pages[company_account]).latest_id(day)
            with allure.step("操作者進入 aaa222「赔率差分」，每一欄輸入 1、按 Tab 後點「保存」，重新整理頁面讀回"):
                failed = _failed_save(ctx, game_id)
            with allure.step("公司與 aaa111 讀取「操作日志」與 aaa222「日志」中步驟之後新增的 aaa222 本彩種紀錄"):
                found = _new_for_target(pages, day, mark, account=ctx.account, game_name=game_name,
                                        target_user_id=ctx.target_user_id)
            with allure.step("操作者與公司重新進入「操作日志」，「类型」選「赔率差分设定」，核對 aaa222 本彩種最新一列是否不變"):
                ui_after = _ui_latest(ui_pages, TOPIC_LABEL, prefix)
            with allure.step("對照組：特码A 主欄改成原值減 0.0001 並點「保存」，再改回原值並點「保存」，核對兩入口各有 2 筆且畫面最新一列為改回的那筆"):
                control = _control_pair(ctx, game_id, game_name, pages, day, operator)
                ui_control = _ui_latest(ui_pages, TOPIC_LABEL, prefix)
            group_failures = []
            status = failed["save_status"]
            if status is not None and 200 <= status < 300:
                group_failures.append(f"{tag}：輸入正數後保存回應 HTTP {status}（應未成功；屬 B91 正數規則）")
            if not failed["unchanged"]:
                group_failures.append(f"{tag}：輸入正數保存後讀回值與原值不同（正數被保存；屬 B91 正數規則）")
            group_failures += _zero_failures(tag, found, ui_before, ui_after)
            group_failures += _control_failures(tag, control, ui_control, company_account)
            head = [f"彩種：{game_name}｜目標：{ctx.account}｜操作者：{operator}（{via}）",
                    f"{failed['planned']} 欄輸入 {POSITIVE_INPUT}，失焦後輸入框的值：{failed['after_focus']}",
                    f"保存：HTTP {status}（None＝畫面未送出；期望未成功）；提示：{failed['messages'] or '無'}；回應：{failed['save_body']}",
                    f"重新整理後讀回{'等於' if failed['unchanged'] else '不等於'}原值（期望等於）",
                    f"未改動：{json.dumps(failed['skipped'], ensure_ascii=False) if failed['skipped'] else '無'}"]
            allure.attach(_describe_zero_group(head, found, ui_before, ui_after, control, group_failures),
                          name="單組比對結果", attachment_type=allure.attachment_type.TEXT)
            odds_gap_run.dump(f"b110-{via}-{game_id}.json", {"failed": failed, "found": found, "ui_before": ui_before,
                                                             "ui_after": ui_after, "control": control, "ui_control": ui_control})
            groups.append(tag)
            failures += group_failures
    allure.attach(f"共 {len(groups)} 組：{'、'.join(groups)}；失敗項 {len(failures)}", name="執行總覽",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures[:40])


def _auth_state(ctx) -> bool | None:
    ctx.setting.open_target(ctx.level_name, ctx.account, require_gap=False)
    return ctx.setting.is_earn_odds_gap_checked()


def _attempt_revoke(ctx) -> dict:
    """下級仍開啟時取消授權並點「保存」：只記錄回應與提示，不重試。"""
    page = ctx.page
    ctx.setting.open_basic_info()
    if ctx.setting.earn_odds_gap_checkbox().is_checked():
        ctx.setting.earn_odds_gap_label().click()
    status, body = None, ""
    try:
        with page.expect_response(lambda r: "/api/Users/" in r.url and r.request.method in ("PUT", "POST", "PATCH"),
                                  timeout=10000) as caught:
            page.get_by_role("button", name="保存", exact=True).click()
        status, body = caught.value.status, caught.value.text()[:500]
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(800)
    messages = [t.strip() for t in page.locator(".el-message, .el-message-box, .el-notification").all_inner_texts()
                if t.strip()]
    modal = page.locator(".el-message-box:visible")
    if modal.count():
        modal.get_by_role("button", name="确认", exact=True).click()
    return {"status": status, "body": body, "messages": messages,
            "matched": REJECT_MESSAGE in "\n".join(messages + [body])}


def _authorization_failures(company_account, *, off, off_read, on, on_read, attempt, guard_read,
                            leaf_records, guard_records, gap_found, ui_leaf, ui_guard, ui_guard_before) -> list[str]:
    failures = []
    for label, result, read, want in (("取消", off, off_read, False), ("勾回", on, on_read, True)):
        if not 200 <= result["status"] < 300 or read is not want:
            failures.append(f"aaa999：{label}「赚取赔率差」保存 HTTP {result['status']}、重新開啟為 {read}（應成功且為 {want}）")
    if (attempt["status"] is not None and 200 <= attempt["status"] < 300) or guard_read is not True or not attempt["matched"]:
        failures.append(f"aaa888：取消授權應被拒並提示「{REJECT_MESSAGE}」，實際 HTTP {attempt['status']}、"
                        f"提示 {attempt['messages'] or attempt['body']}、重新開啟為 {guard_read}")
    changes = [permission_change(r) for r in leaf_records]
    if (changes != [([], [EARN_ODDS_GAP]), ([EARN_ODDS_GAP], [])]
            or any(r.get("fields") != [PERMISSION_FIELD] for r in leaf_records)
            or any(r.get("operatorAccount") != company_account or r.get("action") != "update" for r in leaf_records)):
        failures.append(f"aaa999「账号」類型新增 {len(leaf_records)} 筆，權限增減 {changes}、变更项 "
                        f"{[r.get('fields') for r in leaf_records]}、操作者 {[r.get('operatorAccount') for r in leaf_records]}；"
                        f"應為 2 筆「权限」：先移除「{EARN_ODDS_GAP}」、再加回，操作者 {company_account}")
    for item in guard_records[:3]:
        failures.append(f"aaa888 取消被拒後「账号」類型出現紀錄 {item.get('fields')} {permission_change(item)}，應為 0 筆")
    for (account, entry), items in gap_found.items():
        for item in items[:3]:
            failures.append(f"{account}「赔率差分设定」類型（{entry}）出現紀錄「{item.get('entityId')}」，應為 0 筆")
    want_ui = [(r["entityId"], ui_time(r["createdAt"])) for r in sorted(leaf_records, key=lambda r: r["id"], reverse=True)]
    if ([(c[3], c[9]) for c in ui_leaf[:2]] != want_ui
            or any(c[1] != ACCOUNT_TOPIC_LABEL or c[2] != "修改" or c[4] != PERMISSION_FIELD for c in ui_leaf[:2])):
        failures.append(f"畫面「账号」類型 aaa999 最新兩列 {[(c[1], c[2], c[3], c[4], c[9]) for c in ui_leaf[:2]]}，"
                        f"應為 {want_ui}（账号／修改／权限）")
    if ui_guard != ui_guard_before:
        failures.append(f"畫面「账号」類型 aaa888 最新一列由 {ui_guard_before and ui_guard_before[3:10]} "
                        f"變成 {ui_guard and ui_guard[3:10]}，應不變")
    return failures


@allure.suite("赔率差分")
@allure.sub_suite("操作日志")
@allure.title('[功能驗證] B111：赚取赔率差：關閉再開啟授權並保存後，「操作日志」的「账号」類型是否各記一筆「权限」變更且不出現在「赔率差分设定」；取消被拒時是否不產生紀錄')
@allure.severity(allure.severity_level.NORMAL)
@pytest.mark.write_action
def test_odds_gap_authorization_toggle_logged_under_account_type(gap_context, odds_gap_login, odds_gap_run):
    """平台案例：[功能驗證] B111：赚取赔率差：關閉再開啟授權並保存後，「操作日志」的「账号」類型是否各記一筆「权限」變更且不出現在「赔率差分设定」；取消被拒時是否不產生紀錄
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；會關閉再開啟 aaa999 的「赚取赔率差」，並嘗試取消 aaa888 的授權（應被拒），結束時核對皆為原值（QAT 寫入已預先授權）。
    - 環境：QAT；公司 aaron01 可登入；aaa888、aaa999 的「赚取赔率差」原本皆已勾選；執行期間不讓其他 session 使用該帳號。
    - 來源：新綜合_賠率差分設定頁規格.md「操作日誌」四項邊界規格（Aaron 2026-09-30 裁定）。
    測試範圍：
    - 帳號層授權，不分彩種與玩法：aaa999（九級，無下級代理，可取消）與 aaa888（下級 aaa999 仍勾選，取消應被拒）。
    - 查閱者：公司；「操作日志」與兩帳號的帳號「日志」。帳號「日志」的「账号」類型規格未要求，只記錄觀察，不列判準。
    步驟：
    1. 公司進入「操作日志」，「类型」選「账号」，記下 aaa999、aaa888 最新一列。
    2. 公司進入用户管理 → aaa999「编辑」→「基本资料」，取消勾選「赚取赔率差」並點「保存」，重新開啟後再勾回並點「保存」。
    3. 公司進入 aaa888「编辑」→「基本资料」，取消勾選「赚取赔率差」並點「保存」，記下提示，重新開啟確認仍為勾選。
    4. 公司重新進入「操作日志」分別選「账号」與「赔率差分设定」，並讀取兩帳號的「日志」，核對步驟 2、3 之後新增的紀錄。
    預期結果：
    - aaa999 兩次保存成功，重新開啟分別為未勾選、勾選；「操作日志」「账号」類型新增 2 筆：变更项「权限」，第一筆移除「赚取赔率差」、第二筆加回，操作者 aaron01，畫面最新兩列即這兩筆。
    - aaa888 保存被拒，提示「下级已允许赚取赔率差，请先修改下级」，重新開啟仍為勾選；「账号」類型沒有 aaa888 的新紀錄，畫面最新一列不變。
    - 「赔率差分设定」類型在兩個入口都沒有 aaa999、aaa888 的新紀錄。
    佐證方式：
    - 附件：兩次保存與被拒的回應、提示、重新開啟讀回值；各類型各入口新增紀錄的前後權限差集；畫面最新列前後對照；比對資料存於本次執行目錄。
    已知問題：
    - 平台層差分總開關不在本規格內，未驗。
    """
    company_account = admin_credentials()[0]
    day = datetime.now(TAIPEI).date().isoformat()
    leaf, guard = gap_context(8, via="company"), gap_context(7, via="company")
    user_ids = {}
    for ctx in (leaf, guard):
        ctx.open("markSix")
        user_ids[ctx.account] = ctx.target_user_id
    page = odds_gap_login("__company__")
    reader = AuditLogReader(page)
    with allure.step("公司讀取 aaa999、aaa888 的「赚取赔率差」原值（兩者皆須為勾選）"):
        original = {leaf.account: _auth_state(leaf), guard.account: _auth_state(guard)}
        allure.attach(json.dumps(original, ensure_ascii=False), name="授權原值（期望皆為 true）",
                      attachment_type=allure.attachment_type.JSON)
        if not all(v is True for v in original.values()):
            pytest.skip(f"BLOCKED：aaa999、aaa888 的「赚取赔率差」須皆為勾選，實際 {original}；不自動改造前置")
    with allure.step("公司進入「操作日志」，「类型」選「账号」，記下 aaa999、aaa888 最新一列"):
        log_page = OperationLogPage(page)
        log_page.open_fresh()
        log_page.select_type(ACCOUNT_TOPIC_LABEL)
        ui_before = {a: (log_page.rows_for(a) or [None])[0] for a in (leaf.account, guard.account)}
    mark = max(reader.latest_id(day, ACCOUNT_TOPIC), reader.latest_id(day, TOPIC))
    with allure.step("公司進入 aaa999「编辑」→「基本资料」，取消勾選「赚取赔率差」並點「保存」，重新開啟後再勾回並點「保存」"):
        with guarded_authorization(leaf) as state:
            state["attempted"], state["expected"] = True, False
            off = leaf.setting.set_earn_odds_gap(False)
            off_read = _auth_state(leaf)
            state["last_verified"], state["expected"] = off_read, True
            on = leaf.setting.set_earn_odds_gap(True)
            on_read = _auth_state(leaf)
            state["last_verified"] = on_read
    with allure.step("公司進入 aaa888「编辑」→「基本资料」，在 aaa999 仍勾選時取消勾選「赚取赔率差」並點「保存」，記下提示後重新開啟"):
        with guarded_authorization(guard) as state:
            state["attempted"], state["expected"] = True, False
            attempt = _attempt_revoke(guard)
            guard_read = _auth_state(guard)
            state["last_verified"] = guard_read
    with allure.step("公司讀取「操作日志」與 aaa999、aaa888「日志」中步驟之後新增的「账号」與「赔率差分设定」紀錄"):
        found = {}
        for account in (leaf.account, guard.account):
            for topic in (ACCOUNT_TOPIC, TOPIC):
                for entry, uid in (("操作日志", None), ("帳號日志", user_ids[account])):
                    items = reader.records_after(day, mark, topic=topic, target_user_id=uid)
                    found[(account, topic, entry)] = for_target(items, account, scoped=uid is not None)
    with allure.step("公司重新進入「操作日志」，「类型」選「账号」，核對 aaa999 最新兩列與 aaa888 最新一列"):
        log_page.open_fresh()
        log_page.select_type(ACCOUNT_TOPIC_LABEL)
        ui_leaf, ui_guard = log_page.rows_for(leaf.account), (log_page.rows_for(guard.account) or [None])[0]
    leaf_records = found[(leaf.account, ACCOUNT_TOPIC, "操作日志")]
    guard_records = found[(guard.account, ACCOUNT_TOPIC, "操作日志")]
    gap_found = {(a, e): found[(a, TOPIC, e)] for a in (leaf.account, guard.account) for e in ("操作日志", "帳號日志")}
    failures = _authorization_failures(company_account, off=off, off_read=off_read, on=on, on_read=on_read,
                                       attempt=attempt, guard_read=guard_read, leaf_records=leaf_records,
                                       guard_records=guard_records, gap_found=gap_found, ui_leaf=ui_leaf,
                                       ui_guard=ui_guard, ui_guard_before=ui_before[guard.account])
    scoped_leaf = found[(leaf.account, ACCOUNT_TOPIC, "帳號日志")]
    lines = [f"授權原值：{original}（期望皆為 True）",
             f"aaa999 取消：HTTP {off['status']}，重新開啟 {off_read}（期望 False）；勾回：HTTP {on['status']}，重新開啟 {on_read}（期望 True）",
             f"aaa888 取消：HTTP {attempt['status']}，提示 {attempt['messages'] or attempt['body']}"
             f"（期望被拒並提示「{REJECT_MESSAGE}」），重新開啟 {guard_read}（期望 True）",
             f"「操作日志」「账号」類型 aaa999 新增 {len(leaf_records)} 筆（期望 2）："]
    lines += [f"- {ui_time(r['createdAt'])} 变更项 {r.get('fields')}：新增 {a}、移除 {b}，操作者 {r.get('operatorAccount')}"
              for r, (a, b) in zip(leaf_records, [permission_change(r) for r in leaf_records])]
    lines.append(f"「操作日志」「账号」類型 aaa888 新增 {len(guard_records)} 筆（期望 0）")
    lines += [f"「赔率差分设定」類型 {a}（{e}）新增 {len(items)} 筆（期望 0）" for (a, e), items in gap_found.items()]
    lines.append(f"觀察（不列判準）：aaa999 帳號「日志」「账号」類型新增 {len(scoped_leaf)} 筆，"
                 f"權限增減 {[permission_change(r) for r in scoped_leaf]}；"
                 f"aaa888 新增 {len(found[(guard.account, ACCOUNT_TOPIC, '帳號日志')])} 筆")
    lines.append(f"畫面 aaa999 最新兩列：{[(c[1], c[2], c[3], c[4], c[9]) for c in ui_leaf[:2]]}")
    lines.append(f"畫面 aaa888 最新一列前後{'相同' if ui_guard == ui_before[guard.account] else '不同'}（期望相同）")
    allure.attach("\n".join(lines + ["判定：" + ("通過" if not failures else "；".join(failures[:5]))]),
                  name="授權切換與日誌比對結果", attachment_type=allure.attachment_type.TEXT)
    odds_gap_run.dump("b111.json", {"original": original, "off": off, "on": on, "off_read": off_read, "on_read": on_read,
                                    "attempt": attempt, "guard_read": guard_read, "ui_before": ui_before,
                                    "ui_leaf": ui_leaf[:2], "ui_guard": ui_guard,
                                    "found": {"｜".join(k): v for k, v in found.items()}})
    assert not failures, "判準（attach 佐證）\n驗證失敗：\n- " + "\n- ".join(failures[:40])
