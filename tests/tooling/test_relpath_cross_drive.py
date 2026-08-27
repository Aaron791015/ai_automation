# -*- coding: utf-8 -*-
"""跨磁碟機的路徑不可以讓程式當掉（Windows 專屬的一類缺陷）。

為什麼這組測試值得寫
    `os.path.relpath()` 在 Windows 上遇到**不同磁碟機**會丟 `ValueError`，
    而它在本工作區的用途幾乎都只是「把路徑印得好看一點」——
    **為了好看而讓整支程式掛掉，代價完全不對等。**

    這個缺陷在原型 repo 裡**永遠踩不到**：repo 在 `C:`、`tempfile` 也在 `C:`。
    2026-08-23 的範本端到端驗收把範本匯到 `D:\\QA-Template`，當場炸掉 7 條測試
    —— 這正是「同事視角驗收」才看得見、分階段驗收看不到的東西。

    ⚠️ 真正的成因不是「有人忘了 try」，而是 **`core/paths.py` 早就有安全版
    `rel_to_repo()`，卻有四個檔各自手刻了一份不安全的**。所以這裡除了驗行為，
    也驗「沒有人再手刻一次」。

使用方式：`pytest tests/tooling/test_relpath_cross_drive.py -q`
"""
import io
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _p(*parts):
    return os.path.join(ROOT, *parts)


PLATFORM = _p("tools", "test_platform")


def _platform_path():
    """⚠️ **不可以在模組層插 sys.path。**

    收集整個 `tests/` 時所有測試模組都會被 import，模組層的 insert 會讓
    `core` 從此解析到平台的 `core` 套件 —— 而 `tests/wbot/perf/` 要的是
    `tools/wbot_Performance/core`。實測代價：12 條收集錯誤，
    而且 `case_index` 的 collect 失敗會讓**整個案例索引掉成 0 條**
    （2026-08-23）。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)


windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="只有 Windows 的 relpath 會因跨磁碟機丟 ValueError")

# 挑一個**必定與 repo 不同槽**的路徑（repo 在 C: 就用 D:，反之用 C:）
_OTHER = "D:" if ROOT.upper().startswith("C:") else "C:"
FOREIGN = os.path.join(_OTHER + os.sep, "somewhere", "else", "x.json")


@windows_only
def test_前提成立_跨磁碟機的relpath真的會炸():
    """先釘住前提 —— 否則下面幾條可能只是因為 ValueError 根本不會發生而『通過』。"""
    with pytest.raises(ValueError):
        os.path.relpath(FOREIGN, ROOT)


@windows_only
def test_rel_to_repo_跨磁碟機退回絕對路徑():
    _platform_path()
    from core.paths import rel_to_repo
    got = rel_to_repo(FOREIGN)
    assert got, "不該回空字串"
    assert got.replace("\\", "/") == FOREIGN.replace("\\", "/")


@windows_only
def test_credentials_status_跨磁碟機不炸(monkeypatch):
    """★ 這一條就是範本驗收當場炸掉的那 5 條的成因。"""
    _platform_path()
    from core import credentials
    monkeypatch.setattr(credentials, "LOCAL_PATH", FOREIGN)
    st = credentials.status()
    assert "groups" in st and st.get("path")


@windows_only
def test_analyze_run_的_rel_跨磁碟機不炸():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ar_probe", _p("scripts", "analyze_run.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m._rel(FOREIGN) == FOREIGN


# ─────────────────────────── 沒有人再手刻一份不安全的

# 安全版就在 `core/paths.rel_to_repo`。手刻 `os.path.relpath(x, REPO_ROOT)`
# 的地方一律要改用它 —— 除非那個路徑**必定**在 repo 內（例如 glob 的結果）。
_ALLOWED = {
    # glob 的結果必定在 REPO_ROOT 底下，且這是每次掃描都跑的熱路徑
    "tools/test_platform/collect/case_index.py",
    # 安全版自己的實作
    "tools/test_platform/core/paths.py",
}

_PAT = re.compile(r"os\.path\.relpath\([^)]*REPO_ROOT")


def test_平台裡沒有人手刻不安全的relpath():
    bad = []
    for dirpath, dirnames, files in os.walk(_p("tools", "test_platform")):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "logs", "node_modules")]
        for f in files:
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            if rel in _ALLOWED:
                continue
            if _PAT.search(io.open(full, encoding="utf-8").read()):
                bad.append(rel)
    assert not bad, (
        "這幾個檔手刻了 os.path.relpath(..., REPO_ROOT)，跨磁碟機會丟 ValueError；"
        "改用 core.paths.rel_to_repo()：%s" % "、".join(sorted(bad)))
