# -*- coding: utf-8 -*-
"""讀 claude 那一側的 transcript（`~/.claude/projects/<key>/<cid>.jsonl`）。

用途：**這一輪沒有收到 `result` 事件時，把漏掉的結尾撿回來。**

    from core import transcript
    lost = transcript.texts_since(cid, "2026-08-27T09:14:00")

為什麼需要它（2026-08-27 實例，session `29bc6a46`）
    使用者回報「非任務對話沒有回應任何結果」。查證後：
      · claude **確實產出了完整的中文結論**（transcript 第 200 筆，09:21:40.967Z）
      · 平台落檔的訊息卻只有工具之間的四句英文旁白，`usage` 是 `null`
        —— `null` 代表 `meta` 是空的，也就是**整輪沒有收到 `done` 事件**
      · Flask 行程 17:10 起就沒重啟過，所以不是平台掛掉

    也就是說：**答案寫出來了，只是沒有走到平台這一側。**
    而在這之前平台對這件事**完全沒有反應** —— `claude_session.ask()` 只在
    「exit code 非 0 **且** stderr 有東西」時才報錯，乾淨退出卻沒有 result
    是一條靜默的路。使用者看到的就是最後一句旁白然後沒有下文。

紀律
  1. ⛔ **只讀檔尾** —— 本機最大的 transcript 有 300 MB（見 `session_compact` 紀律 2）。
     這裡的上限比它大（要撿的是一整段結論，不是一行 usage），但仍然有上限。
  2. ⚠️ 檔尾切下來的**第一行可能是半行**，一律丟掉。
  3. ⚠️ 一定要用時間過濾 —— 同一個 cid 累積了**這個 session 的每一輪**，
     不過濾就會把上一輪的結論當成這一輪的補回來。
"""
from __future__ import annotations

import io
import json
import os

from core.paths import REPO_ROOT

#: 撿結尾用的檔尾長度。⚠️ 比 `session_compact._TAIL_BYTES`（256 KB）大 ——
#   那邊只要找一行 usage，這邊要找的是一整段結論，而結論前面可能壓著大量工具回傳。
_TAIL_BYTES = 4 * 1024 * 1024


def path_for(cid: str):
    """claude 那側的 session id → transcript 檔路徑。找不到回 `None`。"""
    if not cid:
        return None
    try:
        from core.claude_usage import project_key, projects_dir
        p = os.path.join(projects_dir(), project_key(REPO_ROOT), "%s.jsonl" % cid)
        return p if os.path.exists(p) else None
    except Exception:                          # noqa: BLE001
        return None


def _tail_lines(path):
    size = os.path.getsize(path)
    with io.open(path, "rb") as f:
        if size > _TAIL_BYTES:
            f.seek(size - _TAIL_BYTES)
        raw = f.read()
    lines = raw.decode("utf-8", "replace").splitlines()
    if size > _TAIL_BYTES and lines:
        lines = lines[1:]                      # 紀律 2：半行
    return lines


def texts_since(cid: str, since_utc: str):
    """`since_utc`（UTC ISO，比到秒就夠）之後，助理寫出來的文字段落，依序回傳。

    ⛔ 讀不到一律回 `[]` —— 這是**補救**路徑，它自己壞掉不可以再把主流程弄倒。
    """
    path = path_for(cid)
    if not path:
        return []
    cut = (since_utc or "")[:19]
    out = []
    try:
        for line in _tail_lines(path):
            if '"assistant"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue                       # 半行或雜訊
            if row.get("type") != "assistant":
                continue
            if cut and str(row.get("timestamp") or "")[:19] < cut:
                continue
            for b in ((row.get("message") or {}).get("content") or []):
                # ⛔ 只撿 `text` —— `thinking` 是推論過程，不是給人的答覆
                if b.get("type") == "text" and b.get("text"):
                    out.append(b["text"])
    except Exception:                          # noqa: BLE001
        return []
    return out
