# -*- coding: utf-8 -*-
"""平台 session 的 shell 護欄（`tools/test_platform/guard/pretool_guard.py`）。

用途：這支是「給平台 session 開 shell」的唯一前提 —— **護欄沒被釘住，就等於沒有護欄**。
      兩件事要擋（git 寫入、刪到自己家以外），其餘一律放行。

⚠️ 誤擋比漏擋更容易毀掉這個設計：擋錯一次，session 就照不了 skill 做事，
   而它不會停下來問人。所以放行面的案例比擋下面的還多。

前置條件：無。
使用方式：`pytest tests/tooling/test_platform_session_guard.py -q`
"""
import importlib.util
import os

import pytest

# ⛔ **不可以在模組層把平台目錄插進 `sys.path`** —— 那會讓 `core` 在收集期被綁到平台的
#    `core` 套件，`tests/wbot/perf` 的 `core.reconnect` 當場找不到
#    （`test_collect_all_roots.py` 就是在守這件事，2026-08-25 我自己踩了一次）。
#    直接依檔案路徑載入：這支只用標準函式庫，沒有相對匯入。
_GUARD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools", "test_platform", "guard", "pretool_guard.py")
_spec = importlib.util.spec_from_file_location("pretool_guard", _GUARD)
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)
decide = G.decide


def run(cmd, tool="Bash"):
    return decide(tool, {"command": cmd})


# ─────────────────────────────── ① git：寫入要擋，唯讀要放

@pytest.mark.parametrize("cmd", [
    "git add -A",
    "git add --renormalize scripts/",
    "git commit -m 'x'",
    "git stash",
    "git push origin main",
    "git reset --hard",
    "git checkout -- .",
    "git clean -fd",
    "git -C C:/GitLab/Automation add .",          # 帶全域旗標也要認得出子命令
    "cd docs && git add .",                       # ★ 只看整串會漏掉這種
    "ls && git commit -am x",
])
def test_git寫入一律擋(cmd):
    ok, why = run(cmd)
    assert not ok, cmd
    assert "CLAUDE.md" in why


@pytest.mark.parametrize("cmd", [
    "git status --short",
    "git diff --stat",
    "git log --oneline -5",
    "git show HEAD:CLAUDE.md",
    "git ls-files",
    "git -c core.quotepath=false status --porcelain",
    "git rev-parse --short HEAD",
    "git --version",
])
def test_git唯讀要放行(cmd):
    """⛔ 擋掉唯讀 git 會讓 lint 的 D6 與 writeback 的 trace 都做不了。"""
    ok, why = run(cmd)
    assert ok, (cmd, why)


# ─────────────────────────────── ② 刪除：只准刪自己家

@pytest.mark.parametrize("cmd", [
    "rm -rf .playwright-mcp",                     # ★ 2026-08-25 的事故本體
    "rm -rf docs/CRUX/bugs",
    "rm -r reports",
    "rmdir /s /q reports",
    "Remove-Item -Recurse -Force C:/GitLab/Automation/reports",
])
def test_刪到自己家以外要擋(cmd):
    ok, why = run(cmd)
    assert not ok, cmd
    assert "2026-08-25" in why


@pytest.mark.parametrize("cmd", [
    "rm -rf tools/test_platform/logs/sessions/abc123/work",
    "rm -rf /tmp/probe",
    "rm -f .playwright-mcp/我拍的.png",            # 指名檔案：允許（不是遞迴）
    "rm docs/CRUX/bugs/_reports/草稿.md",
])
def test_刪自己家或指名檔案要放行(cmd):
    ok, why = run(cmd)
    assert ok, (cmd, why)


# ─────────────────────────────── ③ 其餘一律放行（這才是給 shell 的目的）

@pytest.mark.parametrize("cmd", [
    "python scripts/gen_bug_index.py CRUX --next-id",
    "python scripts/stamp_shots.py --product CRUX '.playwright-mcp/a.png=CRUX-001_01_x.png'",
    "python scripts/lint_docs.py --product CRUX",
    "python scripts/new_bug_doc.py --product CRUX --kind report",
    "python -c \"print(1+1)\"",
    "ls -la docs/CRUX",
    "grep -rn 'ProfitRate' docs/CRUX | head",
    ".venv/Scripts/python.exe -m pytest tests/crux -q",
])
def test_照skill做事的指令全部放行(cmd):
    ok, why = run(cmd)
    assert ok, (cmd, why)


def test_非shell工具不受影響():
    ok, _ = decide("Read", {"file_path": "CLAUDE.md"})
    assert ok


def test_PowerShell走同一套規則():
    """2026-08-23 實測：擋掉 Bash 之後 session 會**改用 PowerShell** 跑同一個指令。"""
    ok, _ = run("git add .", tool="PowerShell")
    assert not ok


def test_事件讀不到時不擋(monkeypatch, capsys):
    """⛔ 護欄自己壞掉，不該讓所有工作停擺 —— 失效方向要是「放行」。"""
    import io as _io

    monkeypatch.setattr(G.sys, "stdin", _io.StringIO("這不是 JSON"))
    assert G.main() == 0
