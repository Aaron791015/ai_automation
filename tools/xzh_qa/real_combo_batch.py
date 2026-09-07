"""真實飛單批次控制：三彩種前台全部完成後才登入後台，設定刻意保留。

JSONL 紀錄在下注前落盤。中斷或狀態不明的項目需先核對注單，不自動重送。
此模組不操作站台，UI 行為由呼叫端提供，方便以離線測試驗證順序與續跑。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class BatchJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.rows = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)  # 損壞時停止，不能忽略後重新下注。
                self.rows[row["key"]] = row

    @staticmethod
    def key(target, scope=None):
        """紀錄鍵；`scope` 供多層級後台驗證區分同一筆注單在各代理層級的結果。

        不帶 `scope` 時與舊版完全相同，既有紀錄檔可原樣續讀。
        """
        parts = [target["game_id"], target["play_type_id"], target["relation_mode"]]
        if scope:
            parts.append(scope)
        return "/".join(parts)

    def record(self, target, status, scope=None, **details):
        key = self.key(target, scope)
        row = {**self.rows.get(key, {}), **target, **details,
               "key": key, "status": status, "scope": scope,
               "updated_at": datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.rows[key] = row
        error = f"：{details['error']}" if details.get("error") else ""
        where = f"{scope}／" if scope else ""
        message = f"[{row['updated_at']}] {status} {where}{target['game']}／{target['label']}{error}"
        try:
            print(message, flush=True)
        except UnicodeEncodeError:
            # Windows 控制台可能仍是 cp950；落盤紀錄已是 UTF-8，輸出降級不能中止批次。
            print(message.encode("ascii", "backslashreplace").decode("ascii"), flush=True)
        return row


class MarketClosed(Exception):
    """尚未送出注單，彩種未開盤。"""


def _front_stage(targets, journal, place_bet, resume_closed, resume_backend_failed=False):
    """前台下注階段；注單九層共用，紀錄一律不帶層級，換層級不得重下。"""
    pending, issues = [], []
    for target in targets:
        previous = journal.rows.get(journal.key(target))
        if previous and previous["status"] == "verified":
            continue
        if previous and previous["status"] == "bet_confirmed":
            pending.append(previous)
            continue
        if previous and previous["status"] == "backend_failed" and resume_backend_failed:
            # 只在呼叫端明確要求「後台補驗」時接續；不會重新下注。
            pending.append(previous)
            continue
        if previous and previous["status"] == "closed" and resume_closed:
            # 只有人工確認市場重新開盤且明確解鎖才可重試；預設禁止重下。
            journal.record(target, "bet_retry_authorized", prior_status="closed")
            previous = journal.rows[journal.key(target)]
        elif previous:
            # closed 也代表這次前台階段已嘗試過；不能把它當成可安全重試。
            issues.append(f"{target['game']}／{target['label']}：{previous['status']}，需核對既有注單")
            continue
        journal.record(target, "betting")
        try:
            details = place_bet(target)
            pending.append(journal.record(target, "bet_confirmed", **details))
        except MarketClosed as exc:
            journal.record(target, "closed", error=str(exc))
            issues.append(f"{target['game']}／{target['label']}：未開盤")
        except Exception as exc:
            journal.record(target, "bet_unknown", error=f"{type(exc).__name__}: {exc}")
            issues.append(f"{target['game']}／{target['label']}：下注未確認，禁止自動重送")
    return pending, issues


def run_batch(targets, journal, place_bet, login_backend, check_backend,
              resume_backend_failed=False, resume_closed=False):
    """先遍歷全部前台目標，再登入一次後台；不提供任何還原 callback。"""
    pending, issues = _front_stage(targets, journal, place_bet, resume_closed,
                                   resume_backend_failed)

    if pending:
        print(f"前台階段結束；已確認下注 {len(pending)} 項、待處理 {len(issues)} 項，現在登入後台一次", flush=True)
        login_backend()
        for target in pending:
            journal.record(target, "checking")
            try:
                details = check_backend(target)
                journal.record(target, "verified", **details, settings_retained=True)
            except Exception as exc:
                journal.record(target, "backend_failed", error=f"{type(exc).__name__}: {exc}",
                               settings_retained=True)
                issues.append(f"{target['game']}／{target['label']}：後台驗證失敗 {exc}")
    return issues


def run_multi_level_batch(targets, journal, place_bet, levels, login_backend, check_backend,
                          resume_backend_failed=False, resume_closed=False):
    """前台只下注一次，後台再依序登入各代理層級，每層對同一批注單各驗一輪。

    ⚠️ 後台結果一律以 `scope=<代理帳號>` 獨立記錄。少了這個維度，九個層級會共用同一個
    key —— 第一層驗完之後其餘八層會被 `status == "verified"` 判成已完成而**靜默跳過**，
    批次還是回報成功。下注紀錄則刻意維持不帶層級：注單是九層共用的，換層級不可重下。
    """
    # 後台補驗旗標只作用在「逐層」的後台紀錄，前台階段不因此重下注單。
    pending, issues = _front_stage(targets, journal, place_bet, resume_closed)
    if not pending:
        return issues
    print(f"前台階段結束；已確認下注 {len(pending)} 項、待處理 {len(issues)} 項，"
          f"接著依序驗證 {len(levels)} 個代理層級", flush=True)
    for level in levels:
        todo = []
        for target in pending:
            previous = journal.rows.get(journal.key(target, level))
            if previous and previous["status"] == "verified":
                continue
            if previous and previous["status"] == "backend_failed" and not resume_backend_failed:
                issues.append(f"{level}／{target['game']}／{target['label']}：前次後台驗證失敗，需人工核對")
                continue
            todo.append({**target, "agent_level": level})
        if not todo:
            continue
        print(f"=== 代理層級 {level}：{len(todo)} 個目標待驗 ===", flush=True)
        login_backend(level)
        for target in todo:
            journal.record(target, "checking", scope=level)
            try:
                details = check_backend(target, level)
                journal.record(target, "verified", scope=level, **details, settings_retained=True)
            except Exception as exc:
                journal.record(target, "backend_failed", scope=level,
                               error=f"{type(exc).__name__}: {exc}", settings_retained=True)
                issues.append(f"{level}／{target['game']}／{target['label']}：後台驗證失敗 {exc}")
    return issues
