# -*- coding: utf-8 -*-
"""賠率差測試的**執行狀態管理**：執行 ID、帳號鏈互斥鎖、原值快照、逐項日誌、受控還原。

用途：滿足規劃 §13「執行、資料與失敗管理」——同鏈循序、中斷可續、只還原本次修改、
      衝突時停手留證。

使用方式：
    state = OddsGapRunState.start("B90-level1-markSix")
    with state.chain_lock("aaa111"):
        state.snapshot("aaa111/markSix", rows)
        state.log({"phase": "input", ...})
        ...
        state.restore_guard("aaa111/markSix", current_rows, written_values)

前置條件：`reports/odds_gap_runs/` 可寫（run 產物、不版控）。

⚠️ 鎖只擋得住**本框架自己**的併行；擋不住人工或其他系統。因此還原前一律重新讀值，
   確認欄位仍是本次寫入的值才還原（見 `restore_guard`）。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNS_DIR = os.path.join(ROOT, "reports", "odds_gap_runs")
LOCKS_DIR = os.path.join(RUNS_DIR, "_locks")


class ChainBusy(RuntimeError):
    """同一條帳號鏈已被本框架的其他執行占用。呼叫端應等待或改判 BLOCKED，⛔ 不可強行寫入。"""


class RestoreConflict(AssertionError):
    """還原前重讀發現欄位已不是本次寫入的值——代表期間有他人異動。

    依 CLAUDE.md §5：停止該筆還原、保留差異、輸出明確清單，⛔ 不得覆蓋他人的修改。
    """


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"不支援的型別：{type(value)}")


class OddsGapRunState:
    """一次執行的狀態根目錄；所有快照／日誌／證據都落在 `reports/odds_gap_runs/<run_id>/`。"""

    def __init__(self, run_id: str, directory: str):
        self.run_id = run_id
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)

    @classmethod
    def start(cls, label: str) -> "OddsGapRunState":
        run_id = f"{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        return cls(run_id, os.path.join(RUNS_DIR, run_id))

    # ---------------- 日誌與快照 ----------------

    def log(self, event: dict) -> dict:
        """逐項日誌（jsonl）。`phase` 建議用：prepare／input／save_sent／persisted／verified／restored。"""
        event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        with open(os.path.join(self.dir, "journal.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")
        return event

    def dump(self, name: str, payload) -> str:
        """把任意結構存成檔案（證據附件用），回傳路徑。"""
        path = os.path.join(self.dir, name.replace("/", "_"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)
        return path

    def snapshot(self, key: str, rows) -> str:
        """保存原值快照（授權、主副差分、基準／最低與比例、時間）。只存一次，重跑時沿用。

        中斷續跑靠這份快照判斷「原值是什麼」，所以**不覆寫**既有快照。
        """
        path = os.path.join(self.dir, "snapshots", key.replace("/", "_") + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"key": key, "taken_at": datetime.now().isoformat(timespec="seconds"),
                           "rows": rows}, f, ensure_ascii=False, indent=2, default=_json_default)
        return path

    def load_snapshot(self, key: str):
        path = os.path.join(self.dir, "snapshots", key.replace("/", "_") + ".json")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ---------------- 帳號鏈互斥 ----------------

    @contextmanager
    def chain_lock(self, chain_key: str, timeout: float = 0.0):
        """同鏈／同帳號循序執行：以檔案鎖阻止**本框架**的併行寫入。

        `timeout` 為等待秒數；逾時丟 `ChainBusy`，由案例判 BLOCKED 而不是硬闖。
        """
        os.makedirs(LOCKS_DIR, exist_ok=True)
        path = os.path.join(LOCKS_DIR, chain_key.replace("/", "_") + ".lock")
        deadline = time.time() + timeout
        handle = None
        while True:
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.time() >= deadline:
                    with open(path, encoding="utf-8") as f:
                        holder = f.read()
                    raise ChainBusy(f"帳號鏈 {chain_key} 已被占用：{holder}")
                time.sleep(1.0)
        try:
            os.write(handle, json.dumps({"run_id": self.run_id, "pid": os.getpid()},
                                        ensure_ascii=False).encode("utf-8"))
            os.close(handle)
            yield
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    # ---------------- 受控還原 ----------------

    def restore_guard(self, key: str, current: dict, written: dict) -> dict:
        """還原前的衝突檢查：回傳「可安全還原」的欄位對照 `{欄位: 原值}`。

        - `current`：**剛剛重讀**的線上值（`gap_values()` 格式）。
        - `written`：本次寫入的值 `{欄位: 寫入值}`。

        規則：只有「線上值 == 本次寫入值」的欄位才還原（表示期間沒人動過）。
        任一欄不符即丟 `RestoreConflict` 並把清單寫進日誌——停手、留證、不覆蓋他人修改。
        """
        snapshot = self.load_snapshot(key)
        assert snapshot, f"找不到 {key} 的原值快照，無法還原"
        original = {(r["playTypeId"], field): r[field]
                    for r in snapshot["rows"] for field in ("oddsGap", "subOddsGap")}
        conflicts = [{"field": list(field), "expected_written": str(value),
                      "actual_online": str(current.get(field))}
                     for field, value in written.items()
                     if current.get(field) != value]
        if conflicts:
            self.log({"phase": "restore_conflict", "key": key, "conflicts": conflicts})
            self.dump(f"restore-conflict-{key}.json", conflicts)
            raise RestoreConflict(
                f"{key} 有 {len(conflicts)} 欄已非本次寫入值，停止還原並保留差異；詳見 {self.dir}")
        return {field: original[field] for field in written}
