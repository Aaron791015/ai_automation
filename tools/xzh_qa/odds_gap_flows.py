# -*- coding: utf-8 -*-
"""賠率差測試的**共用操作流程**：把 B88～B92 的逐格操作、佐證與還原收斂成可重用的函式。

用途：`tests/xzh/test_user_management.py` 的 33 個賠率差函式各自只負責「我是哪一層、哪一類」，
      實際的開啟／輸入／保存／讀回／還原一律走這裡，避免 33 份幾乎相同的程式碼各自漂移。

使用方式：
    from xzh_qa.odds_gap_flows import GapContext, check_rows, run_save_flow

前置條件：已登入**有權編輯該目標**的身分（一級由公司；二～九級與會員由其直屬上級）。

⚠️ 三條不因方便而放寬的紀律（CLAUDE.md §5、規劃 §13）：
1. **被測行為一律走 UI**：輸入、加減、保存都用 UI；API 只用於前置讀取與讀回驗證。
2. **只還原本次修改**，且還原前重讀線上值確認仍是本次寫入值（`OddsGapRunState.restore_guard`）。
3. **已知缺陷不改判**：保存 403／跳登入（Snotra-006）一律回報失敗並留證，
   ⛔ 不自動改走直屬上級路徑再宣稱公司路徑通過。
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR

import allure
import pytest

from xzh_qa.odds_gap_spec import load_spec, compare_spec, field_inventory
from xzh_qa.odds_gap_safety import guarded_gaps, strict_gap_values

from xzh_qa.odds_gap_client import GAMES, OddsGapClient, ReadOnlyApiError, ancestor_sum, gap_values
from xzh_qa.odds_gap_oracle import dec, remaining_gap
from xzh_qa.odds_gap_run_state import OddsGapRunState
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS, OddsGapSettingPage

#: 正常值覆蓋要求「非零整數＋小數部分」（Aaron 2026-09-09 裁定），額度不足才退到 -0.001。
NORMAL_INPUT = Decimal("-1.1")
SMALL_INPUT = Decimal("-0.001")
#: 實測的 number 元件步進值。
STEP = Decimal("0.0001")
#: UI 剩餘欄只顯示四位小數，API 保留更多位——比對時分開看顯示精度與計算精度。
UI_DISPLAY_TOLERANCE = Decimal("0.00005")
API_TOLERANCE = Decimal("0.00000001")


def scope_games() -> list[str]:
    """本次執行要覆蓋哪些彩種。`XZH_GAP_GAMES=markSix,bingo6` 可縮小範圍（抽測模式）。

    ⚠️ 預設為三彩種全量；縮小範圍時 `describe_scope()` 會把實際範圍寫進 Allure 附件，
    ⛔ 不可用抽測結果宣稱全量覆蓋。
    """
    raw = os.environ.get("XZH_GAP_GAMES", "").strip()
    if not raw:
        return list(GAMES)
    games = [x.strip() for x in raw.split(",")]
    assert games and len(set(games)) == len(games) and all(g in GAMES for g in games), "彩種範圍非法或重複"
    return games


def scope_limit() -> int | None:
    """每個彩種最多測幾欄。`XZH_GAP_MAX_FIELDS=1` 即規劃 §15 的「修復抽測」模式。"""
    raw = os.environ.get("XZH_GAP_MAX_FIELDS", "").strip()
    if not raw:
        return None
    assert raw.isdigit() and int(raw) > 0, "XZH_GAP_MAX_FIELDS 須為正整數，拒絕默默擴成全量"
    return int(raw)


def selected_field(play_id, field):
    """逗號分隔 playTypeId:oddsGap/subOddsGap；空值為全欄。"""
    raw = os.environ.get("XZH_GAP_FIELDS", "").strip()
    return not raw or f"{play_id}:{field}" in raw.split(",")


def describe_scope() -> str:
    return (f"彩種範圍：{'、'.join(GAMES[g] for g in scope_games())}\n"
            f"指定欄位：{os.environ.get('XZH_GAP_FIELDS') or '依案例模式'}\n"
            f"每彩種欄位上限：{scope_limit()}\n"
            "此為要求範圍；實際模式、缺失與可測數依逐組coverage附件，不代表已全量通過。")


@dataclass
class GapContext:
    """一次賠率差設定操作的上下文：誰在操作、操作哪個目標、證據往哪裡寫。

    `observed` 是 `OddsGapClient.attach(page)` 的回傳值；`target_user_id` 從其中取得，
    ⛔ 不做 `68 + 層級` 這類推導。
    """

    page: object
    target_index: int                 # 0＝一级代理 aaa111 … 9＝会员 aaa010
    run: OddsGapRunState
    client: OddsGapClient
    observed: dict
    #: 祖先鏈各層的設定列（由淺到深，不含本層）；`None` ＝ 取不到（權限或未載入）。
    #: 取不到時剩餘差分的**絕對值**核對列 BLOCKED，只驗證「改動量 ↔ 剩餘變化量」的相對關係。
    ancestor_rows: object = None
    #: 讀「基準／最低賠率」與上限比例用的**公司身分**唯讀 client。
    #: ⚠️ 代理身分讀 `/api/OddsSetting` 會回 403（2026-09-09 實測），
    #: 所以獨立公式的基準值一定要由公司身分取；`None` 時退回操作者自己的 client。
    reference_client: object = None
    recover: object = None
    setting: OddsGapSettingPage = field(init=False)
    _user_id: object = field(default=None, init=False)

    def __post_init__(self):
        self.setting = OddsGapSettingPage(self.page)

    @property
    def account(self) -> str:
        return CHAIN_ACCOUNTS[self.target_index]

    @property
    def level_name(self) -> str:
        from xzh_qa.pages.dashboard_page import AgentHierarchyPage
        return AgentHierarchyPage.LEVELS[self.target_index]

    def open(self, game_id: str) -> list[dict]:
        """開啟目標的賠率差分頁並切到指定彩種，回傳與畫面對齊後的 API 設定列。"""
        # 先等前一個目標的請求收完：同頁連續開啟時，上一層晚到的回應曾被算進本層
        # （2026-09-23 還原收尾攔到 {76, 77}）。
        # networkidle 仍擋不住更晚到的回應（2026-09-24 攔到 {69, 70}）：攔到多個 id 時等一下由畫面重開，最多 3 次。
        for attempt in range(3):
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            seen = len(self.observed["target_user_ids"])
            self.setting.open_target(self.level_name, self.account)
            self.setting.select_game(game_id)
            new_ids = self.observed["target_user_ids"][seen:]
            for _ in range(50):
                if new_ids:
                    break
                self.page.wait_for_timeout(100)
                new_ids = self.observed["target_user_ids"][seen:]
            if len(set(new_ids)) <= 1:
                break
            self.page.wait_for_timeout(1500)
        assert new_ids, (f"開啟 {self.account} 的賠率差分頁後沒有攔到 targetUserId，"
                         f"無法在不猜測的前提下取得 userId")
        assert len(set(new_ids)) == 1, f"同一次開啟卻攔到多個 targetUserId：{set(new_ids)}"
        self._user_id = new_ids[0]
        api_rows = self.api_rows(game_id)
        self.setting.wait_rows_match(api_rows)
        return api_rows

    def api_rows(self, game_id: str) -> list[dict]:
        """讀線上設定列；先換成頁面最新的 Authorization，401／403 時重新登入同一身分再讀一次。

        多個 GapContext 共用同一公司頁面時，各自的 client 保留建立當下的 token，
        長批次（約 5 分鐘以上）會過期（2026-09-23 還原收尾 401）。
        """
        latest = self.observed.get("headers", {}).get("Authorization")
        if latest:
            self.client.headers["Authorization"] = latest
        try:
            return self.client.gap_setting(self.target_user_id, game_id)
        except ReadOnlyApiError as exc:
            if exc.status not in (401, 403) or not self.recover:
                raise
            self.recover()
            self.client.headers = dict(self.observed["headers"])
            return self.client.gap_setting(self.target_user_id, game_id)

    @property
    def target_user_id(self) -> int:
        """目標帳號的 userId——由 `open()` 從前端自己發出的請求攔截而來（已驗證身分）。"""
        assert self._user_id is not None, "尚未開啟目標的賠率差分頁，無法取得 targetUserId"
        return int(self._user_id)


def attach(name: str, text: str) -> None:
    allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)


def load_ancestor_rows(ctx, game_id):
    """UI 確認目標 ID，再由唯讀祖先鏈逐帳號核對；每個 GET 使用本彩種。"""
    ctx.open(game_id)
    if ctx.target_index == 0:
        return []
    client = ctx.reference_client
    try:
        chain = client.share_ancestors(ctx.target_user_id)
        agents = [r for r in chain if r.get("level") != "company"]
        assert [r.get("account") for r in agents] == CHAIN_ACCOUNTS[:ctx.target_index+1], "唯讀祖先鏈與 UI 指定帳號鏈不符，停止寫入"
        assert agents[-1]["id"] == ctx.target_user_id, "祖先查詢末端與 UI 目標 ID 不符"
        rows = [client.gap_setting(node["id"], game_id) for node in agents[:-1]]
        assert all(rows), "某層祖先設定為空，不能當零值"
        ctx.run.dump(f"ancestors-{ctx.account}-{game_id}.json",
                     {"game": game_id, "target": ctx.account, "chain": chain, "rows": rows})
        return rows
    except ReadOnlyApiError as exc:
        ctx.run.log({"phase": "ancestor_source_blocked", "game": game_id,
                     "target": ctx.account, "error": str(exc)})
        return None


# --------------------------------------------------------------------------
# B89：顯示與玩法完整性
# --------------------------------------------------------------------------

def check_rows(ctx: GapContext, game_id: str, manifest: dict) -> dict:
    """逐列核對表頭、列名與主副欄是否符合正式規格；歷史快照不作判準。

    回傳 `{headers, ui_names, expected_names, missing, unexpected, sub_mismatch}`；
    由呼叫端斷言，本函式只負責取得事實並產出可讀佐證。
    """
    api_rows = ctx.open(game_id)
    ui_rows = ctx.setting.read_rows()
    spec = load_spec()
    comparison = compare_spec(spec, ui_rows, api_rows, ctx.setting.column_headers())
    ui_names = [r['name'] for r in ui_rows]
    missing = [f for f in comparison['fields'] if f.get('reason') == 'missing_row']
    unexpected = [x for x in comparison['issues'] if x['kind'] == 'unexpected_row']
    sub_mismatch = [f for f in comparison['fields'] if f['status'] != 'PASS']
    result = dict(comparison, headers=ctx.setting.column_headers(), ui_names=ui_names,
                  baseline_kind=spec['version'], spec_completeness=comparison['status'],
                  expected_names=[r['name'] for r in spec['rows']], missing=missing,
                  unexpected=unexpected, sub_mismatch=sub_mismatch,
                  ui_row_count=len(ui_rows), ui_column_count=comparison['inputs'],
                  expected_row_count=spec['scope']['rowCountPerGame'],
                  expected_column_count=spec['scope']['fieldCountPerGame'])
    restore_baseline = os.environ.get("XZH_GAP_RESTORE_BASELINE")
    if restore_baseline:
        baseline = json.loads(Path(restore_baseline).read_text(encoding="utf-8"))[ctx.account][game_id]
        result["restore_snapshot_source"] = baseline["source"]
        result["final_restoration_equal"] = strict_gap_values(api_rows) == strict_gap_values(baseline["rows"])
    ctx.run.dump(f"b89-{ctx.account}-{game_id}.json", result)
    attach(f"{GAMES[game_id]}｜{ctx.account} 正式規格核對", json.dumps(result, ensure_ascii=False, default=str))
    assert comparison['status'] == 'PASS', '玩法／主副欄與正式規格不符，詳見逐欄附件'
    if restore_baseline:
        assert result["final_restoration_equal"], f"最終還原與本批最早原值快照不同：{ctx.account}/{game_id}"
        ctx.run.log({"phase": "final_restoration_verified", "account": ctx.account,
                     "game": game_id, "source": baseline["source"], "equal": True})
    return result


# --------------------------------------------------------------------------
# B90／B92：逐欄輸入、加減、保存、重載、剩餘公式核對、還原
# --------------------------------------------------------------------------

def plan_fields(ctx: GapContext, game_id: str, api_rows: list[dict],
                odds: dict, cap_rate: Decimal, ancestors: dict) -> tuple[list[dict], list[dict]]:
    """依當下剩餘額度規劃每一欄要輸入什麼值，回傳 `(可測欄位, 受阻欄位)`。

    每欄另附獨立算式所需的全部輸入（基準／最低／比例／祖先合計／原值），供 B92 比對。
    """
    fields, blocked = [], []
    inventory, coverage = field_inventory(api_rows)
    ctx.run.dump(f"coverage-{ctx.account}-{game_id}.json", coverage)
    for entry in inventory:
        if 'reason' in entry:
            blocked.append(entry)
            continue
        row_index, col_index = entry['row'], entry['col']
        row = api_rows[row_index]
        gap_key = entry['field']
        remaining_key = 'remainingSubOddsGap' if col_index else 'remainingOddsGap'
        setting = odds.get(row["playTypeId"])
        if setting is None:
            blocked.append({"play": row["playTypeName"], "field": gap_key,
                            "reason": "OddsSetting 缺此玩法的基準／最低賠率"})
            continue
        is_sub = col_index == 1
        raw_base = setting.get("subOdds" if is_sub else "odds")
        raw_low = (setting["subMinOdds"] if setting.get("subMinOdds") is not None
                   else setting.get("minOdds")) if is_sub else setting.get("minOdds")
        if raw_base is None or raw_low is None or row.get(gap_key) is None or row.get(remaining_key) is None:
            blocked.append({"play": row["playTypeName"], "field": gap_key,
                            "reason": "基準／最低／原值／剩餘有空值，不能猜成零或保證精確還原"})
            continue
        base, low = dec(raw_base), dec(raw_low)
        old = dec(row[gap_key])
        budget = dec(row[remaining_key])
        step = NORMAL_INPUT if budget >= (-NORMAL_INPUT + STEP) else SMALL_INPUT
        if budget < -step + STEP:
            blocked.append({"play": row["playTypeName"], "field": gap_key,
                            "reason": "剩餘額度不足以輸入 -0.001 並再減一步，無法完成完整步進條件",
                            "remaining": str(budget)})
            continue
        ancestor = ancestors.get((row["playTypeId"], gap_key), Decimal(0))
        target = old + step
        fields.append({
            "row": row_index, "col": col_index, "play_id": row["playTypeId"],
            "play": row["playTypeName"], "field": gap_key, "remaining_key": remaining_key,
            "old": old, "input": target, "step": step,
            "base_odds": base, "min_odds": low, "cap_rate": cap_rate,
            "ancestor_sum": ancestor,
            "expected_remaining": remaining_gap(base, low, target, ancestor, cap_rate),
        })
    coverage.update(executable_fields=len(fields), blocked_fields=blocked)
    ctx.run.dump(f"coverage-{ctx.account}-{game_id}.json", coverage)
    attach('保存實際欄位範圍', json.dumps(coverage, ensure_ascii=False, default=str))
    return fields, blocked


def run_save_flow(ctx: GapContext, game_id: str, manifest: dict, *,
                  verify_step_buttons: bool = True,
                  verify_remaining_formula: bool = False) -> dict:
    """B90（保存流程）與 B92（剩餘差分公式）的共用主流程。

    流程：讀原值快照 → 規劃每欄輸入 → 逐欄輸入／Tab／−／＋ → UI 保存（攔 PUT）→
          重載重讀 → 逐欄比對（保存值、未操作欄、剩餘公式）→ 受控還原。

    回傳結構化結果；⛔ 本函式**不**吞任何失敗：保存非 2xx、跳登入、欄位不符都原樣回報。
    """
    api_rows = ctx.open(game_id)
    key = f"{ctx.account}-{game_id}"
    ctx.run.snapshot(key, api_rows)
    before = gap_values(api_rows)

    reference = ctx.reference_client or ctx.client
    odds = reference.odds_setting(game_id)
    cap_rate, cap_rate_independent = reference.cap_rate()
    ctx.run.dump(f"cap-source-{key}.json", getattr(reference, "cap_rate_evidence", {}))
    ancestors_available = ctx.ancestor_rows is not None
    formula_available = ancestors_available and cap_rate_independent
    ancestors = ancestor_sum(ctx.ancestor_rows) if ancestors_available else {}

    fields, blocked = plan_fields(ctx, game_id, api_rows, odds, cap_rate, ancestors)
    # 保存前的剩餘值，供「改動量 ↔ 剩餘變化量」的相對核對（此檢查不需要祖先資料）
    for item in fields:
        item["remaining_before"] = dec(api_rows[item["row"]][item["remaining_key"]])
    ctx.run.dump(f"plan-{key}.json", {"fields": fields, "blocked": blocked})
    if not fields:
        pytest.skip(f"BLOCKED：{key} 無可測欄位（額度或必要原始值不足，共 {len(blocked)} 欄），見 plan 附件")

    # ---- 逐欄輸入（被測行為，走 UI） ----
    step_checks = []
    for item in fields:
        actual = ctx.setting.set_value(item["row"], item["col"], item["input"])
        item["after_input"] = actual
        if verify_step_buttons:
            after_down = ctx.setting.step_down(item["row"], item["col"])
            after_up = ctx.setting.step_up(item["row"], item["col"])
            item["after_step_down"] = after_down
            item["after_step_up"] = after_up
            step_checks.append(after_down == item["input"] - STEP and after_up == item["input"])
    ctx.run.log({"phase": "input", "key": key, "fields": len(fields)})

    # 保存前確認期間沒有他人異動（本框架的鎖擋不住人工）
    drifted = gap_values(ctx.api_rows(game_id)) != before
    assert not drifted, f"{key}：保存前重讀發現目標設定已被他人變更，停止本輪並保留現況"

    with guarded_gaps(ctx, game_id, api_rows) as transaction:
        # 還原比對的是實際送出前 UI 值；產品若把期望輸入改掉，仍須能收尾並保留測試失敗。
        transaction["expected"] = {(f["play_id"], f["field"]):
                                   f["after_step_up"] if verify_step_buttons else f["after_input"]
                                   for f in fields}
        # ---- UI 保存 ----
        transaction["attempted"] = True
        saved = ctx.setting.save()
        ctx.run.log({"phase": "save_sent", "key": key, "status": saved["status"]})
        bounced = ctx.setting.bounced_to_login()
        result = {"key": key, "game": game_id, "account": ctx.account,
                  "save_status": saved["status"], "save_body": saved["body"],
                  "bounced_to_login": bounced, "fields": fields, "blocked": blocked,
                  "cap_rate": cap_rate, "cap_rate_independent": cap_rate_independent,
                  "ancestors_available": ancestors_available,
                  "step_ok": all(step_checks) if step_checks else None,
                  "checks": [], "restored": False}

        if saved["status"] not in (200, 204) or bounced:
            ctx.run.dump(f"save-failed-{key}.json", result)
            attach(f"{GAMES[game_id]}｜{ctx.account} 保存失敗",
                   f"HTTP {saved['status']}；是否跳回登入：{'是' if bounced else '否'}\n"
                   f"回應：{saved['body'][:800]}\n"
                   f"⚠️ 已知 Snotra-006（公司保存下級 403 並跳登入）；本輪判失敗，未改走其他路徑。")
            raise AssertionError(f"保存失敗 HTTP {saved['status']}，跳登入={bounced}；見 {ctx.run.dir}")

        # ---- 重載讀回 ----
        ctx.setting.reload_tab(game_id)
        after_api = ctx.api_rows(game_id)
        ctx.setting.wait_rows_match(after_api)
        # 列名先出現、數值後綁上：等數值與 API 一致再讀；逾時仍不符就照原值判定，不掩蓋顯示錯誤。
        ui_sync = ctx.setting.wait_values_match(after_api)
        after_ui = ui_sync["rows"]
        result["ui_value_sync"] = {k: v for k, v in ui_sync.items() if k != "rows"}
        after_map = {r["playTypeId"]: r for r in after_api}
        after_values = gap_values(after_api)

        written = {(f["play_id"], f["field"]): f["input"] for f in fields}
        untouched_bad = [{"field": list(k), "before": str(v), "after": str(after_values.get(k))}
                         for k, v in before.items()
                         if k not in written and after_values.get(k) != v]

        for item in fields:
            api_row = after_map[item["play_id"]]
            ui_row = after_ui[item["row"]]
            saved_api = dec(api_row[item["field"]])
            saved_ui = dec(ui_row["inputs"][item["col"]])
            api_remaining = dec(api_row[item["remaining_key"]])
            ui_remaining = dec(ui_row["remaining"][item["col"]])
            # 相對核對（不需祖先資料）：本層差分改了 Δ，剩餘就該同步變動 Δ
            expected_delta = item["input"] - item["old"]
            actual_delta = api_remaining - item["remaining_before"]
            check = {**item,
                     "saved_api": saved_api, "saved_ui": saved_ui,
                     "api_remaining": api_remaining, "ui_remaining": ui_remaining,
                     "expected_delta": expected_delta, "actual_delta": actual_delta,
                     "saved_ok": saved_api == item["input"] == saved_ui == item["after_input"],
                     "delta_ok": abs(actual_delta - expected_delta) <= API_TOLERANCE,
                     "remaining_api_ok": (abs(api_remaining - item["expected_remaining"]) <= API_TOLERANCE
                                          if formula_available else None),
                     "remaining_ui_observation": ui_remaining,
                     "remaining_ui_ok": None}
            result["checks"].append(check)

        result["untouched_changed"] = untouched_bad
        result["saved_all_ok"] = all(c["saved_ok"] for c in result["checks"])
        result["delta_all_ok"] = all(c["delta_ok"] for c in result["checks"])
        result["remaining_all_ok"] = (all(c["remaining_api_ok"]
                                          for c in result["checks"])
                                      if formula_available else None)

    result["restored"] = transaction["restored"]
    ctx.run.dump(f"result-{key}.json", result)

    _attach_save_flow(ctx, game_id, result, verify_remaining_formula)
    assert result["saved_all_ok"] and result["delta_all_ok"] and not result["untouched_changed"], "保存／剩餘變化／未操作欄位核對失敗，詳見附件"
    assert result["step_ok"] is not False, "加減步進與輸入值不符，詳見附件"
    if blocked:
        pytest.skip(f"BLOCKED（部分）：有 {len(blocked)} 欄額度或基準資料不足，詳見逐欄附件")
    return result


def _attach_save_flow(ctx: GapContext, game_id: str, result: dict,
                      with_formula: bool) -> None:
    """把逐格算式明細寫進 Allure（PASS／FAIL 用同一種可讀格式，不只附截圖）。"""
    checks = result["checks"]
    lines = [describe_scope(), "",
             f"目標：{ctx.account}（{ctx.level_name}）｜彩種：{GAMES[game_id]}",
             f"保存回應：HTTP {result['save_status']}；還原：{'已還原' if result['restored'] else '未完成'}",
             f"可測欄位 {len(checks)} 欄；受阻 {len(result['blocked'])} 欄；"
             f"加減按鈕核對：{'全部符合' if result['step_ok'] else result['step_ok']}",
             f"未操作欄位遭誤改：{result['untouched_changed'] or '無'}",
             f"上限比例：{result['cap_rate']}"
             f"（{'獨立取得' if result['cap_rate_independent'] else '⚠️ 取不到平台設定，依文件預設值假設'}）",
             ("祖先鏈與實際比例已取得，剩餘絕對值依完整公式核對"
              if result["ancestors_available"] and result["cap_rate_independent"]
              else "⚠️ 祖先鏈或平台實際上限比例未取得 → 剩餘的**絕對值**核對列 BLOCKED，"
                   "本輪只驗「改動量 ↔ 剩餘變化量」"),
             "",
             "逐欄明細（玩法｜欄位｜原值→輸入｜保存讀回 API/UI｜期望剩餘｜實際剩餘 API/UI｜Δ 期望/實際）："]
    for c in checks:
        verdicts = [] if c["saved_ok"] else ["保存不符"]
        if not c["delta_ok"]:
            verdicts.append("剩餘變化量不符")
        if c["remaining_api_ok"] is False:
            verdicts.append("剩餘絕對值不符")
        lines.append(f"{c['play']}｜{c['field']}｜{c['old']}→{c['input']}｜"
                     f"{c['saved_api']}/{c['saved_ui']}｜"
                     f"{c['expected_remaining'] if result['ancestors_available'] else '(BLOCKED)'}｜"
                     f"{c['api_remaining']}/{c['ui_remaining']}｜"
                     f"{c['expected_delta']}/{c['actual_delta']}｜"
                     f"{'／'.join(verdicts) if verdicts else 'OK'}")
    if with_formula and checks and result["ancestors_available"]:
        sample = checks[0]
        lines += ["", "剩餘差分算式（取第一欄示範，其餘同式）：",
                  f"上限 ＝ (基準 {sample['base_odds']} − 最低 {sample['min_odds']}) × 比例 {sample['cap_rate']}",
                  f"期望剩餘 ＝ 上限 ＋ 祖先合計 {sample['ancestor_sum']} ＋ 本層差分 {sample['input']}"
                  f" ＝ {sample['expected_remaining']}",
                  f"實際：API {sample['api_remaining']}、UI {sample['ui_remaining']}"
                  f"（UI 顯示精度依裁定不納入判定）"]
    if result["blocked"]:
        lines += ["", "受阻欄位（額度不足或缺基準值，未計入通過）："]
        lines += [f"{b['play']}｜{b['field']}｜{b['reason']}" for b in result["blocked"]]
    attach(f"{GAMES[game_id]}｜{ctx.account} 逐欄驗證明細", "\n".join(str(x) for x in lines))


# --------------------------------------------------------------------------
# B91：輸入邊界與異常
# --------------------------------------------------------------------------

#: 依規格可判定的合法輸入（有明確期望值）。
LEGAL_INPUTS = [("0", Decimal("0"), "允許 0"),
                ("-0.0001", Decimal("-0.0001"), "允許四位負小數")]
#: 規格未明訂處置方式的輸入——只記錄實際行為並列待確認，⛔ 不自行規定截斷／捨入／空值語意。
# Aaron最新指示：暫撤回截斷判準，超位小數只觀察並列BLOCKED，不能判PASS/FAIL。
UNDEFINED_INPUTS = ["abc", "", "1", "-0.00001", "-0.12346", "-0.00019"]
#: 超扣（輸入超過剩餘差分）：2026-09-29 新版文件明訂儲存時不檢查超扣、由投注時最低賠率擋住，
#: 預期保存成功且讀回等於畫面輸入值。超扣值取至四位小數（往負向取），不與待確認的超位小數混測。
OVERDRAW_EXPECTED = "entered"


def check_boundary_inputs(ctx: GapContext, game_id: str, manifest: dict) -> dict:
    """依full/sample選欄，每種條件同批保存並立即還原；不同條件不共用已改設定。"""
    rows = ctx.open(game_id)
    inventory, coverage = field_inventory(rows, boundary=True)
    targets = [(x['row'], x['col'], x['play_id'], x['field'], x['play']) for x in inventory if 'reason' not in x]
    result = {"legal": [], "undefined": [], "blocked": [x for x in inventory if 'reason' in x],
              "coverage": coverage, "batch_observations": [], "positive_persisted": False}
    ctx.run.dump(f"b91-{ctx.account}-{game_id}.json", result)
    attach('B91實際欄位範圍', json.dumps(coverage, ensure_ascii=False))
    if not targets:
        pytest.skip('BLOCKED：所選規格欄位皆缺失')
    conditions = [(raw, expected, note, "type") for raw, expected, note in LEGAL_INPUTS]
    conditions += [(raw, None, "未定義輸入處理", "type") for raw in UNDEFINED_INPUTS]
    conditions += [("abc", None, "貼上文字", "paste"), (None, OVERDRAW_EXPECTED, "超扣可保存", "overdraw")]
    input_scope = os.environ.get("XZH_GAP_BOUNDARY_INPUTS")
    if input_scope:
        selected_inputs = json.loads(input_scope)
        assert isinstance(selected_inputs, list) and selected_inputs and all(isinstance(v, str) for v in selected_inputs), "邊界輸入範圍需非空 JSON 字串陣列"
        assert set(selected_inputs) <= {c[0] for c in conditions if c[3] == "type"}, "指定了未知邊界輸入"
        conditions = [c for c in conditions if c[3] == "type" and c[0] in selected_inputs]
    rounds = []
    for condition in conditions:
        # 正數預期被拒絕，逐欄單獨提交，避免某一欄擋住整張表掩蓋其他欄漏洞。
        selections = [[target] for target in targets] if condition[0] == "1" else [targets]
        rounds.extend((*condition, selection) for selection in selections)
    key = f"b91-{ctx.account}-{game_id}.json"
    for raw, expected, note, mode, active_targets in rounds:
        rows = ctx.open(game_id)
        items = []
        with guarded_gaps(ctx, game_id, rows) as transaction:
            for i, col, play, field, name in active_targets:
                original = dec(rows[i][field])
                remaining_key = "remainingSubOddsGap" if col else "remainingOddsGap"
                value = (str((original - dec(rows[i][remaining_key]) - STEP).quantize(STEP, rounding=ROUND_FLOOR))
                         if mode == "overdraw" else raw)
                if mode == "paste":
                    after = ctx.setting.paste_raw(i, col, value)
                    if after is None:
                        result["blocked"].append({"play": play, "field": field, "condition": note,
                                                  "reason": "此 QAT 頁面無瀏覽器剪貼簿 API，未冒充實際貼上"})
                        continue
                else:
                    after = ctx.setting.fill_raw(i, col, value)
                item = {"play": name, "play_id": play, "field": field, "input": value,
                        "condition": note, "mode": mode, "after_focus": after, "original": original}
                item["validation_scope"] = "single_field" if len(active_targets) == 1 else "batch"
                if not after:
                    # 空字串不能自行推定會送成 0；保留行為並清除本批未保存輸入。
                    result["blocked"].append({**item, "reason": "失焦仍空白，無確定送出值；未猜測空值語意"})
                    break
                try:
                    written = dec(after)
                except Exception:
                    result["blocked"].append({**item, "reason": "失焦仍非數字，無確定送出值"})
                    break
                item["written"] = written
                transaction["expected"][(play, field)] = written
                items.append(item)
            else:
                if items:
                    assert gap_values(ctx.api_rows(game_id)) == gap_values(rows), "保存前發現他人异動"
                    transaction["attempted"] = True
                    saved = ctx.setting.save(allow_no_request=expected is None)
                    messages = ctx.setting.messages()
                    if expected is not None:
                        assert saved["status"] in (200, 204), f"合法輸入保存 HTTP {saved['status']}"
                    elif saved["status"] not in (None, 200, 204, 400, 422):
                        raise AssertionError(f"非法輸入出現非驗證拒絕回應 HTTP {saved['status']}")
                    ctx.setting.reload_tab(game_id)
                    actual = gap_values(ctx.api_rows(game_id))
                    isolated_retry = expected is None and len(items) > 1 and saved["status"] in (None, 400, 422)
                    if isolated_retry:
                        rounds.extend((raw, expected, note, mode, [target]) for target in active_targets)
                    for item in items:
                        value = actual[(item["play_id"], item["field"])]
                        item.update(save_status=saved["status"], read_back=value, messages=messages)
                        if expected is not None:
                            target = item["written"] if expected == OVERDRAW_EXPECTED else expected
                            result["legal"].append({**item, "expected": target, "ok": value == target})
                        else:
                            result["batch_observations" if isolated_retry else "undefined"].append(item)
                            if raw == "1" and value > 0:
                                result["positive_persisted"] = True
        ctx.run.dump(key, result)
        ctx.run.log({"phase": "boundary_condition", "game": game_id, "condition": note,
                     "input": raw, "fields": len(items), "write_attempted": transaction["attempted"],
                     "restored": transaction["restored"] if transaction["attempted"] else "未寫入"})
    attach(f"{GAMES[game_id]}｜{ctx.account} 邊界逐欄結果",
           json.dumps(result, ensure_ascii=False, default=str, indent=2))
    assert all(x["ok"] for x in result["legal"]), "合法輸入保存不符"
    assert not result["positive_persisted"], "正數被保存為有效正差分"
    if result["undefined"] or result["blocked"]:
        pytest.skip("BLOCKED（部分）：明確條件已檢查；未定義輸入處理及無法執行條件詳见逐欄附件")
    return result
