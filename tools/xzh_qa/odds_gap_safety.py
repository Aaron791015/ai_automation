"""賠率差 UI 寫入的異常收尾；唯讀重查、衝突停手、只還原本次欄位。"""
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
import os
import json
import time
from pathlib import Path

from xzh_qa.odds_gap_client import gap_values, ReadOnlyApiError
from xzh_qa.odds_gap_oracle import dec
from xzh_qa.odds_gap_run_state import RestoreConflict

# 副欄「NULL→0」登記檔（2026-10-06 Aaron 同意方案 B）：UI 保存一列會把該列從未設過的副欄（NULL）
# 一併送成 0，且 UI 寫不回 NULL；規格「副差分未設＝0」，兩者計算等價。只有登記在這裡的格，
# 還原核對與全表基準比對才視 NULL→0 為相符；其他任何差異（含未登記的 NULL→0、0→NULL）照舊報。
NULL_TO_ZERO_REGISTRY = (Path(__file__).resolve().parents[2]
                         / "reports" / "odds_gap_regression" / "_baselines" / "null-to-zero-registry.json")
# 兩條帳號鏈會同時登記（2026-10-07 16:24 一方讀到另一方寫到一半的空檔，觸發停止標記）：
# 登記時以鎖檔排隊，寫暫存檔後整檔換上；讀遇到空檔或 Windows 換檔瞬間的共用違規時短暫重試。
REGISTRY_LOCK_TIMEOUT = 30.0
_IO_RETRIES = 20
_IO_WAIT = 0.1


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


def is_null_to_zero(field, before, after):
    """副欄由 NULL 變成 0（UI 保存副作用的唯一形態）；主欄、0→NULL、NULL→非 0 都不算。"""
    return field == "subOddsGap" and before is None and after is not None and dec(after) == 0


def _read_registry(registry: Path) -> dict:
    """讀登記檔；空檔（舊版寫到一半）或共用違規時重試，重試完仍失敗就照原錯誤拋出，不當成沒有登記。"""
    for attempt in range(_IO_RETRIES):
        try:
            if not registry.exists():
                return {"cells": []}
            return json.loads(registry.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            if attempt == _IO_RETRIES - 1:
                raise
            time.sleep(_IO_WAIT)


def _write_registry(registry: Path, data: dict) -> None:
    """寫同目錄暫存檔再整檔換上，讀的一方只會看到換檔前或換檔後的完整內容。"""
    temp = registry.with_name(f".{registry.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        for attempt in range(_IO_RETRIES):
            try:
                os.replace(temp, registry)
                return
            except PermissionError:      # Windows：另一方正好開著舊檔
                if attempt == _IO_RETRIES - 1:
                    raise
                time.sleep(_IO_WAIT)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _registry_lock(registry: Path):
    """以 O_EXCL 建鎖檔排隊；逾時不搶鎖、不刪別人的鎖，直接報錯並附鎖檔內容供人判斷。"""
    lock = registry.with_name(registry.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + REGISTRY_LOCK_TIMEOUT
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                try:
                    holder = lock.read_text(encoding="utf-8")
                except OSError:
                    holder = "（讀不到）"
                raise TimeoutError(f"NULL→0 登記檔被鎖住超過 {REGISTRY_LOCK_TIMEOUT:g} 秒：{lock}（{holder}）；"
                                   "確認沒有批次正在登記後再手動刪除鎖檔") from None
            time.sleep(_IO_WAIT)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "at": datetime.now().astimezone().isoformat(timespec="seconds")}))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def registered_null_to_zero(path=None) -> set:
    """已登記的 (account, game, play, field)。"""
    registry = Path(path or NULL_TO_ZERO_REGISTRY)
    cells = _read_registry(registry)["cells"]
    return {(c["account"], c["game"], c["play"], c["field"]) for c in cells}


def register_null_to_zero(account, game_id, keys, source, path=None):
    """登記本批保存造成的 NULL→0；已登記的不重寫。keys 為 strict_gap_values 的 (play, field)。

    讀、加、寫整段持鎖，兩條鏈同時登記不會互相蓋掉。
    """
    registry = Path(path or NULL_TO_ZERO_REGISTRY)
    with _registry_lock(registry):
        data = _read_registry(registry)
        known = {(c["account"], c["game"], c["play"], c["field"]) for c in data["cells"]}
        at = datetime.now().astimezone().isoformat(timespec="seconds")
        added = [{"account": account, "game": game_id, "play": play, "field": field, "at": at, "source": source}
                 for play, field in sorted(keys) if (account, game_id, play, field) not in known]
        if added:
            data["cells"].extend(added)
            _write_registry(registry, data)
    return added


def gap_differences(strict_before, strict_after, allow_null_to_zero=lambda play: False):
    """逐格比對兩份 strict_gap_values；回傳（差異清單, 容許的 NULL→0 格）。
    只有 allow_null_to_zero(play) 為真的列，其副欄 NULL→0 才容許。"""
    differences, tolerated = [], []
    for k in sorted(set(strict_before) | set(strict_after)):
        if k in strict_before and k in strict_after:
            before, after = strict_before[k], strict_after[k]
            if before == after:
                continue
            if is_null_to_zero(k[1], before, after) and allow_null_to_zero(k[0]):
                tolerated.append(k)
                continue
        differences.append({"play": k[0], "field": k[1], "before": strict_before.get(k), "after": strict_after.get(k)})
    return differences, tolerated


def restore_equal(account, game_id, before_rows, after_rows, path=None):
    """還原後與快照是否相同；只容許已登記的副欄 NULL→0。"""
    allowed = registered_null_to_zero(path)
    differences, _ = gap_differences(strict_gap_values(before_rows), strict_gap_values(after_rows),
                                     lambda play: (account, game_id, play, "subOddsGap") in allowed)
    return not differences


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
                # 只容許本批保存過的列（UI 整列送出）或已登記格的副欄 NULL→0；其他列的 NULL→0 代表有人動過
                saved = {play for play, _ in state["expected"]}
                allowed = registered_null_to_zero()
                differences, tolerated = gap_differences(
                    strict_before, strict_gap_values(ctx.api_rows(game_id)),
                    lambda play: play in saved or (ctx.account, game_id, play, "subOddsGap") in allowed)
                if differences:
                    ctx.run.dump(f"restore-diff-{key}.json", differences)
                    raise RestoreConflict("最終全欄與本輪快照不一致；保留差異，不覆蓋其他欄位")
                register_null_to_zero(ctx.account, game_id, tolerated, str(ctx.run.dir))
                state["restored"] = True
                ctx.run.log({"phase": "restored", "key": key, "equal": True,
                             "null_to_zero": [list(k) for k in tolerated]})
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
