"""賠率差 UI 寫入的異常收尾；唯讀重查、衝突停手、只還原本次欄位。"""
from contextlib import contextmanager
from uuid import uuid4
import os
import json
from pathlib import Path

from xzh_qa.odds_gap_client import gap_values, ReadOnlyApiError
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_run_state import RestoreConflict


def ensure_writes_clear(ctx):
    marker = os.environ.get("XZH_GAP_STOP_FILE")
    if getattr(ctx.run, "restore_pending", False) or (marker and Path(marker).exists()):
        raise RestoreConflict("本批已有未解決還原異常，停止後續寫入；先核對 restore-pending 紀錄")


def block_following_writes(ctx, key, error):
    ctx.run.restore_pending = True
    marker = os.environ.get("XZH_GAP_STOP_FILE")
    if marker:
        path = Path(marker)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"run": ctx.run.dir, "key": key, "error": str(error)},
                                   ensure_ascii=False, indent=2), encoding="utf-8")


def strict_gap_values(rows):
    """還原核對保留 NULL 與零的差別；計算端的零正規化不能掩蓋資料變更。"""
    return {(r["playTypeId"], field): None if r[field] is None else dec(r[field])
            for r in rows for field in ("oddsGap", "subOddsGap")}


@contextmanager
def guarded_gaps(ctx, game_id, before_rows):
    """呼叫端在送出前登記 expected；回應遺失仍會讀回判定，不重送測試寫入。"""
    ensure_writes_clear(ctx)
    key = f"{ctx.account}-{game_id}-{uuid4().hex[:10]}"
    ctx.run.snapshot(key, before_rows)
    before = gap_values(before_rows)
    strict_before = strict_gap_values(before_rows)
    assert strict_gap_values(ctx.api_rows(game_id)) == strict_before, "進入寫入前原始值已異動，停止保存"
    state = {"expected": {}, "attempted": False, "restored": False, "key": key}
    try:
        yield state
    finally:
        if state["attempted"]:
            try:
                try:
                    current = gap_values(ctx.api_rows(game_id))
                except ReadOnlyApiError as exc:
                    if exc.status not in (401, 403) or not ctx.recover:
                        raise
                    ctx.recover()
                    current = gap_values(ctx.api_rows(game_id))
                pending = {k: v for k, v in state["expected"].items()
                           if k not in current or current[k] != before[k]}
                if pending:
                    ctx.run.restore_guard(key, current, pending)
                    # 重新從 UI 開啟，清除未保存輸入並按玩法 ID 重新定位。
                    rows = ctx.open(game_id)
                    fresh = gap_values(rows)
                    targets = ctx.run.restore_guard(key, fresh, pending)
                    indexes = {r["playTypeId"]: i for i, r in enumerate(rows)}
                    for (play, field), value in targets.items():
                        ctx.setting.set_value(indexes[play], int(field == "subOddsGap"), dec(value))
                    latest = gap_values(ctx.api_rows(game_id))
                    if latest != fresh:
                        raise RestoreConflict("還原輸入期間資料已變更，停止保存")
                    response = ctx.setting.save()
                    assert response["status"] in (200, 204), f"還原保存失敗：{response['status']}"
                final = strict_gap_values(ctx.api_rows(game_id))
                if final != strict_before:
                    differences = [{"play": k[0], "field": k[1], "before": strict_before.get(k),
                                    "after": final.get(k)} for k in set(strict_before) | set(final)
                                   if k not in final or k not in strict_before or final[k] != strict_before[k]]
                    ctx.run.dump(f"restore-diff-{key}.json", differences)
                    raise RestoreConflict("最終全欄與本輪快照不一致；保留差異，不覆蓋其他欄位")
                state["restored"] = True
                ctx.run.log({"phase": "restored", "key": key, "equal": True})
            except BaseException as exc:
                block_following_writes(ctx, key, exc)
                ctx.run.dump(f"restore-pending-{key}.json", {
                    "account": ctx.account, "game": game_id, "snapshot": key,
                    "error": str(exc), "fields": [
                        {"play": k[0], "field": k[1], "written": str(v)}
                        for k, v in state["expected"].items()]})
                ctx.run.log({"phase": "restore_pending", "key": key, "error": str(exc)})
                raise


@contextmanager
def guarded_authorization(ctx):
    """授權切換也在 finally 中檢查與還原；讀回失敗時不盲目保存。"""
    ensure_writes_clear(ctx)
    ctx.setting.open_target(ctx.level_name, ctx.account, require_gap=False)
    original = ctx.setting.is_earn_odds_gap_checked()
    key = f"authorization-{ctx.account}-{uuid4().hex[:10]}"
    ctx.run.dump(f"{key}.json", {"original": original})
    state = {"original": original, "expected": original, "last_verified": original, "attempted": False}
    try:
        yield state
    finally:
        if state["attempted"]:
            try:
                ctx.setting.open_target(ctx.level_name, ctx.account, require_gap=False)
                current = ctx.setting.is_earn_odds_gap_checked()
                if current != original:
                    # 多次切換時，請求未生效可能仍停在上一個已讀回的本次寫入值。
                    if current not in (state["expected"], state["last_verified"]):
                        raise RestoreConflict("授權已非本次寫入值，停止還原")
                    result = ctx.setting.set_earn_odds_gap(original)
                    assert result["status"] in (200, 204), "授權還原保存失敗"
                ctx.setting.open_target(ctx.level_name, ctx.account, require_gap=False)
                assert ctx.setting.is_earn_odds_gap_checked() == original, "授權還原讀回不符"
                ctx.run.log({"phase": "authorization_restored", "key": key, "equal": True})
            except BaseException as exc:
                block_following_writes(ctx, key, exc)
                ctx.run.dump(f"restore-pending-{key}.json", {**state, "error": str(exc)})
                raise
