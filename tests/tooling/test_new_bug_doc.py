# -*- coding: utf-8 -*-
"""`scripts/new_bug_doc.py`（報告／交接檔的防撞名配號）的回歸測試。

用途：這支腳本存在的唯一理由，就是擋掉「同日同類檔名互相覆蓋」——
      `docs/**/bugs/` 不版控，覆蓋即永久遺失（2026-08-14 實際發生過一次）。
      因此它的**遞增邏輯與原子佔位**必須真的擋得住，否則等於沒做。
前置條件：無（全部在 tmp_path 上操作，不碰真實 docs/）。
使用方式：`pytest tests/tooling/test_new_bug_doc.py -q`
"""
import io
import os

import pytest

import new_bug_doc

import bug_paths as _bp
# ⚠️ 這個檔的測試都需要**一個已登記的產品**當樣本（腳本的 `--product` 有 choices 驗證）。
#    全新範本「一個產品都還沒接」是正常狀態 —— 那時候沒有東西可測，明講跳過。
#    ⛔ 不要靠 `bug_paths` 的 fallback 變出產品來：那個 fallback 只給「設定檔壞掉」用，
#       拿它來餵測試會讓「空工作區」這個狀態永遠測不到（2026-08-23）。
_REGISTERED = _bp.PRODUCTS
pytestmark = pytest.mark.skipif(
    not _REGISTERED,
    reason="這個工作區還沒接任何產品 —— 這幾條測的是「對某個產品」的腳本行為")
_SAMPLE = _REGISTERED[0] if _REGISTERED else ""



@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把腳本的 ROOT 指到 tmp_path，建出 docs/CRUX/bugs/{_reports,_handover}/。"""
    bugs = tmp_path / "docs" / "CRUX" / "bugs"
    (bugs / "_reports").mkdir(parents=True)
    (bugs / "_handover").mkdir(parents=True)
    monkeypatch.setattr(new_bug_doc, "ROOT", str(tmp_path))
    monkeypatch.setattr(new_bug_doc, "bugs_dir", lambda product: str(bugs))
    return tmp_path, bugs


def _run(capsys, *argv):
    """執行 main() 並回傳 (回傳碼, 最後一行輸出)。最後一行依約定就是路徑。"""
    import sys
    monkey = sys.argv
    sys.argv = ["new_bug_doc.py", *argv]
    try:
        code = new_bug_doc.main()
    finally:
        sys.argv = monkey
    out = capsys.readouterr().out.strip().splitlines()
    return code, (out[-1] if out else "")


def _touch(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8").write(text)


# ── 配號邏輯 ────────────────────────────────────────────────────

def test_無同名檔時給原始檔名(sandbox, capsys):
    code, path = _run(capsys, "--product", "CRUX", "--kind", "report", "--date", "2026-08-14")
    assert code == 0
    assert path.endswith("_reports/JIRA_Bug驗證報告_2026-08-14.md")


def test_已有原始檔時遞增為第2批(sandbox, capsys):
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14.md"))
    code, path = _run(capsys, "--product", "CRUX", "--kind", "report", "--date", "2026-08-14")
    assert code == 0
    assert path.endswith("JIRA_Bug驗證報告_2026-08-14_第2批.md")


def test_已有第2批時遞增為第3批(sandbox, capsys):
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14.md"))
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14_第2批.md"))
    code, path = _run(capsys, "--product", "CRUX", "--kind", "report", "--date", "2026-08-14")
    assert path.endswith("_第3批.md")


def test_只有第2批存在時仍會補回原始檔名(sandbox, capsys):
    """序號有洞就填洞 —— 否則刪過檔的目錄會一路往上跳號。"""
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14_第2批.md"))
    code, path = _run(capsys, "--product", "CRUX", "--kind", "report", "--date", "2026-08-14")
    assert path.endswith("JIRA_Bug驗證報告_2026-08-14.md")


def test_不同日期互不影響(sandbox, capsys):
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14.md"))
    code, path = _run(capsys, "--product", "CRUX", "--kind", "report", "--date", "2026-08-15")
    assert path.endswith("JIRA_Bug驗證報告_2026-08-15.md")


def test_交接檔走另一個目錄與樣板(sandbox, capsys):
    _, bugs = sandbox
    _touch(str(bugs / "_handover" / "交接_SideEffect待驗_2026-08-14.md"))
    code, path = _run(capsys, "--product", "CRUX", "--kind", "handover", "--date", "2026-08-14")
    assert path.endswith("_handover/交接_SideEffect待驗_2026-08-14_第2批.md")


def test_報告與交接檔的序號互不干擾(sandbox, capsys):
    """兩者在不同目錄；報告已到第2批，不該讓交接檔也跳號。"""
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14.md"))
    _, path = _run(capsys, "--product", "CRUX", "--kind", "handover", "--date", "2026-08-14")
    assert path.endswith("交接_SideEffect待驗_2026-08-14.md")


def test_需求報告帶主題(sandbox, capsys):
    code, path = _run(capsys, "--product", "CRUX", "--kind", "requirement",
                      "--topic", "CRUX-883綜合報表", "--date", "2026-08-14")
    assert code == 0
    assert path.endswith("需求驗證報告_CRUX-883綜合報表_2026-08-14.md")


def test_不同主題不互相佔號(sandbox, capsys):
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "效能測試報告_A-7_2026-08-14.md"))
    _, path = _run(capsys, "--product", "CRUX", "--kind", "perf",
                   "--topic", "A-8", "--date", "2026-08-14")
    assert path.endswith("效能測試報告_A-8_2026-08-14.md")


def test_requirement缺topic時報錯(sandbox, capsys):
    with pytest.raises(SystemExit) as e:
        _run(capsys, "--product", "CRUX", "--kind", "requirement", "--date", "2026-08-14")
    assert e.value.code == 2          # argparse 的 error() 用 2


def test_日期格式錯誤時報錯(sandbox, capsys):
    with pytest.raises(SystemExit) as e:
        _run(capsys, "--product", "CRUX", "--kind", "report", "--date", "2026/08/14")
    assert e.value.code == 2


# ── 佔位（原子建檔）────────────────────────────────────────────

def test_reserve會真的建檔而且不覆蓋既有檔(sandbox, capsys):
    _, bugs = sandbox
    victim = bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14.md"
    _touch(str(victim), "別人的報告內容")
    code, path = _run(capsys, "--product", "CRUX", "--kind", "report",
                      "--date", "2026-08-14", "--reserve")
    assert code == 0
    assert path.endswith("_第2批.md")
    # 佔位檔已建立，且**既有檔完好無損**（這就是整支腳本的重點）
    assert os.path.exists(os.path.join(str(bugs.parent.parent.parent), path))
    assert io.open(str(victim), encoding="utf-8").read() == "別人的報告內容"


def test_連續reserve會拿到不同檔名(sandbox, capsys):
    """模擬兩個 session 先後佔位 —— 不可拿到同一個名字。"""
    _, first = _run(capsys, "--product", "CRUX", "--kind", "report",
                    "--date", "2026-08-14", "--reserve")
    _, second = _run(capsys, "--product", "CRUX", "--kind", "report",
                     "--date", "2026-08-14", "--reserve")
    assert first != second
    assert second.endswith("_第2批.md")


def test_reserve會自動建目錄(sandbox, capsys):
    _, bugs = sandbox
    os.rmdir(str(bugs / "_handover"))
    code, path = _run(capsys, "--product", "CRUX", "--kind", "handover",
                      "--date", "2026-08-14", "--reserve")
    assert code == 0
    assert os.path.isdir(str(bugs / "_handover"))


# ── 反向檢查 ────────────────────────────────────────────────────

def test_check_已佔用回傳1(sandbox, capsys):
    _, bugs = sandbox
    _touch(str(bugs / "_reports" / "JIRA_Bug驗證報告_2026-08-14.md"))
    code, _ = _run(capsys, "--check", "docs/CRUX/bugs/_reports/JIRA_Bug驗證報告_2026-08-14.md")
    assert code == 1


def test_check_未佔用回傳0(sandbox, capsys):
    code, path = _run(capsys, "--check", "docs/CRUX/bugs/_reports/JIRA_Bug驗證報告_2026-08-14.md")
    assert code == 0
    assert path.endswith("JIRA_Bug驗證報告_2026-08-14.md")
