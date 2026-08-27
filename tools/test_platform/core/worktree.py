# -*- coding: utf-8 -*-
"""工作區檔案異動的前後快照 —— 「這一輪 session 動了哪些檔」。

用途：2026-08-25 起平台 session 有 shell 與寫檔（見 `claude_session.SAFE_TOOLS`）。
      給了寫入能力，就必須讓人**看得見它寫了什麼** ——
      否則「AI 做完 → 平台落檔 → 人看結果」那條動線會少掉中間那一段：
      session 用 `Bash` 直接改的檔，草稿模型完全不知道。

作法：跑一輪前後各取一次 `git status --porcelain`，比對出這一輪新出現／變動的路徑。

⚠️ 幾個刻意的取捨：
  · **只讀不寫** —— 不碰索引（`commit` skill §0 第 2 條），純粹是 `status`。
  · **會夾到別的 session 的異動** —— 同一台機器多個 session 共用一份 working tree，
    這裡分不出是誰改的。所以呈現時要講「這段期間工作區的異動」，不要說死是它改的。
  · 取不到 git（不是 repo、git 不在）就回 `None` —— **失效方向是「沒有這一段」**，
    不是讓整輪失敗。
"""
from __future__ import annotations

import subprocess

from core.paths import REPO_ROOT


def snapshot():
    """目前 working tree 的異動集合 `{路徑: 狀態碼}`。取不到回 None。"""
    try:
        out = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "-C", REPO_ROOT,
             "status", "--porcelain"],
            stderr=subprocess.DEVNULL).decode("utf-8", "replace")
    except Exception:                       # noqa: BLE001 不是 repo／沒有 git 都算「沒有這一段」
        return None
    snap = {}
    for line in out.splitlines():
        if len(line) < 4:
            continue
        snap[line[3:].strip().strip('"')] = line[:2]
    return snap


def changed_since(before, after=None):
    """這段期間**新出現或狀態變了**的路徑（排序後的 list）。任一邊取不到就回 []。"""
    if before is None:
        return []
    after = snapshot() if after is None else after
    if after is None:
        return []
    return sorted(p for p, st in after.items() if before.get(p) != st)
