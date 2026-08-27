# -*- coding: utf-8 -*-
"""平台啟動時的狀態調和 —— 收拾上一次沒有好好結束的東西（2026-08-24）。

## 為什麼需要

平台的「進行中」狀態有兩份，**都只活在程序記憶體裡**：

| | 記在哪 | 平台被 kill 之後 |
| --- | --- | --- |
| run | `manager._runs`（程序內字典） | 字典沒了 → `/api/runs/active` 回空 |
| session | meta 的 `activity`（**寫在磁碟**），收尾在 `finally` | `finally` 不會跑 → **永遠卡在 running** |

於是兩者壞掉的方式**剛好相反**，而且都是錯的：

· **run 從 UI 完全消失** —— 狀態檔卡在 `starting`，而 `run_index` 只收終態的 run，
  所以「執行紀錄」也找不到它。人按了執行、跑到一半平台掛掉，回來之後
  **不知道它跑過、跑到哪、結果是什麼**。
· **session 永遠顯示執行中** —— 總覽的「運行中」掛著一個早就不存在的東西，
  而且**沒有任何機制會清掉它**。

（2026-08-24 實測：跑一個 run 到 33% 時中止平台 → 重啟後總覽與執行紀錄都看不到它，
  只有直接打 URL 才看得到一個永遠停在 33% 的頁面。）

## 做法

啟動時掃一次磁碟，把「非終態但實際上沒有在跑」的標成中止，**並寫明原因**。

⭐ **原因要寫清楚是「平台重啟」而不是「失敗」** —— 那次執行可能跑得好好的，
   是平台被關掉了。標成 `failed` 會讓 `run_index` 的熱度圖把它算成基礎設施故障
   （與 `adapters/pytest_.py` 記過的「exit code 1 不是 run 失敗」同一條理由）。
   用 `stopped`。

⛔ **只在啟動時跑一次** —— 平台綁 127.0.0.1 且 port 衝突會直接啟動失敗，
   所以「啟動當下」保證只有這一個實例，掃磁碟不會誤傷別人正在跑的 run。
   ⚠️ 執行期**不可以**再呼叫：那時 `manager._runs` 裡有活著的 run，
   它們的狀態檔本來就是非終態的，掃了會把正在跑的東西標成中止。

使用方式（`web_ui/app.py` 啟動時）：
    from core import reconcile
    reconcile.on_startup()
"""
from __future__ import annotations

import json
import os

from core import run_store
from core.jsonio import write_json_atomic
from core.paths import LOGS_DIR

#: 標記用的欄位值 —— UI 靠它顯示「這是被平台重啟打斷的」而不是「失敗」
INTERRUPTED_NOTE = "平台重啟時中斷（不是執行失敗）—— 這一輪沒有跑完，結果不完整"


def on_startup() -> dict:
    """回 {"runs": n, "sessions": n}，供啟動訊息顯示。"""
    return {"runs": _sweep_runs(), "sessions": _sweep_sessions()}


def _sweep_runs() -> int:
    n = 0
    for run_id in run_store.list_run_dirs():
        st = run_store.read_status(run_id)
        if not st or st.get("phase") in run_store.TERMINAL:
            continue
        now = run_store.now_str()
        st["phase"] = "stopped"
        st["ended_at"] = st.get("ended_at") or now
        st["interrupted"] = True
        st["error"] = INTERRUPTED_NOTE
        # ⚠️ 進度**保留原樣** —— 「跑到 33% 被打斷」是人要知道的事，
        #    歸零或補成 100% 都會讓人誤判這一輪跑完了。
        try:
            write_json_atomic(run_store.status_path(run_id), st)
            run_store.append_console(run_id, "── %s ──" % INTERRUPTED_NOTE)
            n += 1
        except OSError:
            continue
    return n


def _sweep_sessions() -> int:
    """把卡在 `activity: running` 的 session 收掉。

    ⚠️ **不要動 `pending_review`** —— 那是「上一輪交了什麼」，與這一輪有沒有
       跑完無關；清掉等於把人還沒看的產出提示也一起丟了。
    """
    root = os.path.join(LOGS_DIR, "sessions")
    if not os.path.isdir(root):
        return 0
    n = 0
    for sid in os.listdir(root):
        p = os.path.join(root, sid, "meta.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("activity") != "running":
            continue
        m["activity"] = "idle"
        m["activity_ended_at"] = run_store.now_str()
        m["activity_interrupted"] = True
        try:
            write_json_atomic(p, m)
            n += 1
        except OSError:
            continue
    return n
