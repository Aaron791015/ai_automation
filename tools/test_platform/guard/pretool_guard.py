# -*- coding: utf-8 -*-
"""平台 session 的 shell 護欄（Claude Code 的 PreToolUse hook）。

用途：平台起的任務 session 是**無人看管**的。它需要 shell 才能照 skill 做事
      （`gen_bug_index --next-id` 配號、`stamp_shots.py` 搬截圖、`lint_docs` 收尾…），
      但有兩件事在沒有人的情況下不能做，這支就是那條線：

        ⛔ **碰 git 索引與提交**（add／commit／stash／push…）
           —— 不是因為危險，是因為 `CLAUDE.md` §8 要求**提交前一律先向使用者確認**，
              而它身邊沒有人可以確認。唯讀的 `status`／`diff`／`log` 一律放行（skill 需要）。
        ⛔ **遞迴刪除自己工作目錄以外的東西**
           —— 2026-08-25 的教訓：`rm -rf .playwright-mcp` 把另一個 session 正在累積的
              8 張佐證整批毀掉（不進資源回收筒、無法復原）。

使用方式：由 `core.claude_session` 產生的 settings 檔掛成 `PreToolUse` hook，
          **只套用在平台 session**（終端機 session 不受影響）。
          stdin 收 hook 事件 JSON，決定放行就 exit 0，要擋就 **exit 2 ＋ stderr 說明**
          （exit 2 是 Claude Code 的「擋下並把理由回給模型」約定）。

前置條件：只用標準函式庫 —— 它跑在 hook 程序裡，不保證有工作區的相依。

⚠️ **這支擋的是「誤觸與順手」，不是「刻意繞過」。**
   `python -c "import subprocess; subprocess.run(['git','add','.'])"` 這種包一層的寫法
   任何字串比對都攔不住。給了 shell 就是接受這個殘餘風險 ——
   真正降低它的是「session 沒有動機這麼做」＋「前後 `git status` 快照看得見它改了什麼」。
   ⛔ 所以**不要**因為有了這支就放寬其他地方；它是最後一道，不是唯一一道。
"""
from __future__ import annotations

import json
import os
import re
import sys

#: git 的唯讀子命令 —— 這些放行（`lint_docs` 的 D6、`writeback` 的 trace 都要用）
GIT_READONLY = {
    "status", "diff", "log", "show", "ls-files", "rev-parse", "blame",
    "describe", "check-ignore", "shortlog", "grep", "cat-file", "remote",
    "count-objects", "verify-pack", "whatchanged", "reflog",
}

#: 遞迴刪除的樣子（bash 與 PowerShell 兩套都要認 —— 2026-08-23 實測：擋掉 Bash 它會改用 PowerShell）
_RM_RECURSIVE = re.compile(
    r"""(?:^|[\s;&|(])(?:
          rm\s+(?:-\w*\s+)*-\w*[rR]\w*      |   # rm -r / -rf / -fr
          rmdir\s                            |
          Remove-Item\b[^\n]*?-Recurse       |
          rd\s+/s                            |
          del\s+/s
        )""",
    re.X | re.I)

#: 允許遞迴刪除的範圍 —— session 自己的工作目錄與系統暫存
_DELETABLE = ("logs/sessions/", "logs\\sessions\\", "/temp/", "\\temp\\", "/tmp/")


def _segments(cmd: str):
    """把 `a && b ; c | d` 拆成各段 —— 只看整串會漏掉 `cd x && git add .`。"""
    return [s.strip() for s in re.split(r"&&|\|\||[;\n|]", cmd or "") if s.strip()]


def _git_verdict(seg: str):
    """這一段是不是 git 的寫入操作。回 (要不要擋, 理由)。"""
    m = re.match(r"^git\b(.*)$", seg.strip(), re.S)
    if not m:
        return False, ""
    rest = m.group(1).strip()
    # 跳過 `-C <路徑>`／`-c k=v` 這類全域旗標，找出真正的子命令
    toks = rest.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        break
    sub = toks[i] if i < len(toks) else ""
    if not sub:
        return False, ""                       # 只有 `git`／`git --version`
    if sub in GIT_READONLY:
        return False, ""
    return True, (
        "⛔ 平台 session 不能碰 git 的寫入操作（`git %s`）。\n"
        "   理由不是危險，是 CLAUDE.md §8：**提交前一律先向使用者確認**，"
        "而你身邊沒有人可以確認 —— 索引又是整個工作目錄共用的，"
        "你一暫存就會把別的 session 正在改的東西一起帶走。\n"
        "   ✅ 唯讀的 `git status`／`diff`／`log`／`show` 可以用。\n"
        "   ✅ 你照常改檔就好，**平台會在這一輪結束時列出你動了哪些檔**，由人來提交。" % sub)


def _delete_verdict(seg: str):
    """這一段是不是「刪到自己家以外」。回 (要不要擋, 理由)。"""
    if not _RM_RECURSIVE.search(seg):
        return False, ""
    low = seg.replace("\\", "/").lower()
    if any(d.replace("\\", "/").lower() in low for d in _DELETABLE):
        return False, ""                       # 刪自己的工作目錄或系統暫存，放行
    return True, (
        "⛔ 平台 session 不能遞迴刪除自己工作目錄以外的東西。\n"
        "   2026-08-25 的教訓：`rm -rf .playwright-mcp` 把另一個 session 正在累積的"
        "8 張佐證整批毀掉 —— 那個目錄是**共用的**，而 `rm` 不進資源回收筒、救不回來。\n"
        "   ✅ 要清就指名檔案（`rm -f <路徑>/<檔名>`），或只清 "
        "`tools/test_platform/logs/sessions/<你的 sid>/` 底下的東西。")


def decide(tool_name: str, tool_input: dict):
    """(可不可以跑, 擋下來的理由)。⭐ 測試直接打這一支，不必真的起 hook。"""
    if tool_name not in ("Bash", "PowerShell", "BashOutput"):
        return True, ""
    cmd = (tool_input or {}).get("command") or ""
    for seg in _segments(cmd):
        for verdict in (_git_verdict(seg), _delete_verdict(seg)):
            if verdict[0]:
                return False, verdict[1]
    return True, ""


def main() -> int:
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0                               # 讀不到事件就不要擋 —— 護欄壞掉不該讓工作停擺
    ok, why = decide(ev.get("tool_name") or "", ev.get("tool_input") or {})
    if ok:
        return 0
    sys.stderr.write(why + "\n")
    return 2                                   # 2 ＝ 擋下並把 stderr 回給模型


if __name__ == "__main__":                      # pragma: no cover
    sys.exit(main())
