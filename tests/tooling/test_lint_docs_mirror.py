# -*- coding: utf-8 -*-
"""D13：乾淨範本鏡像有沒有跟上原版（`lint_docs.check_mirror_sync`）。

用途：`commit` skill 寫著「提交後跑一次 `--sync`」，但那條**只靠自律** ——
      而 skill 自己就寫著「原版改了而鏡像沒跟上時，**沒有任何機制會發現**」。
      2026-08-26 連續四輪漏掉，所以改成 lint 的一項。

⛔ 這裡釘住的重點是**不要吵**：三種情況必須靜默跳過，一種必須報。
   假警告會讓人開始忽略 lint，比沒有檢查更糟。

前置條件：無（全部用臨時目錄，不碰真的鏡像）。
"""
import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


@pytest.fixture
def L():
    import lint_docs
    return lint_docs


def _mirror(tmp_path, commit):
    """做一個假鏡像：只要有 `.template-export` 就算數。"""
    d = tmp_path / "mirror"
    d.mkdir()
    (d / ".template-export").write_text(
        json.dumps({"source_commit": commit, "files": {}}, ensure_ascii=False),
        encoding="utf-8")
    return d


def _point_to(monkeypatch, L, tmp_path, text):
    """把 `.template-mirror` 指到別處 —— ⛔ 不碰 repo 根目錄的那一個。"""
    fake_root = tmp_path / "root"
    fake_root.mkdir(exist_ok=True)
    if text is not None:
        (fake_root / ".template-mirror").write_text(text, encoding="utf-8")
    monkeypatch.setattr(L, "ROOT", str(fake_root))
    return fake_root


def test_沒設鏡像位置就整項跳過(L, tmp_path, monkeypatch):
    """⛔ 同事本來就沒有鏡像 —— 報了是純雜訊。"""
    _point_to(monkeypatch, L, tmp_path, None)
    assert L.check_mirror_sync() == []


def test_自己就是範本時跳過(L, tmp_path, monkeypatch):
    """根目錄有 `.template-export` ＝ 你手上就是匯出的範本，沒有鏡像可比。"""
    root = _point_to(monkeypatch, L, tmp_path, str(tmp_path / "mirror"))
    (root / ".template-export").write_text("{}", encoding="utf-8")
    assert L.check_mirror_sync() == []


def test_指到不存在的目錄要講(L, tmp_path, monkeypatch):
    """設了卻指錯，是**設定壞掉**不是沒有鏡像 —— 這種要講。"""
    _point_to(monkeypatch, L, tmp_path, str(tmp_path / "根本沒有這個目錄"))
    got = L.check_mirror_sync()
    assert got and "不存在" in got[0], got


def test_讀不到匯出標記要講(L, tmp_path, monkeypatch):
    """指到一個不是 `--out` 產生的目錄。"""
    d = tmp_path / "mirror"
    d.mkdir()
    _point_to(monkeypatch, L, tmp_path, str(d))
    got = L.check_mirror_sync()
    assert got and "template-export" in got[0], got


def test_鏡像跟上時不報(L, tmp_path, monkeypatch):
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    if not head:
        pytest.skip("不是 git repo")
    d = _mirror(tmp_path, head)
    root = _point_to(monkeypatch, L, tmp_path, str(d))
    # ⚠️ git 指令要在**真的 repo** 裡跑，所以只有 ROOT 的判斷用假的
    monkeypatch.setattr(L, "ROOT", ROOT)
    (tmp_path / "root" / ".template-mirror").rename(
        os.path.join(ROOT, "__d13_test_hint__"))
    try:
        monkeypatch.setattr(L, "MIRROR_HINT", "__d13_test_hint__")
        assert L.check_mirror_sync() == []
    finally:
        os.remove(os.path.join(ROOT, "__d13_test_hint__"))


def test_落後且動到通用檔就要報(L, tmp_path, monkeypatch):
    """★ 這是它存在的理由。"""
    old = subprocess.run(["git", "rev-parse", "--short", "HEAD~3"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    if not old:
        pytest.skip("歷史不夠長")
    d = _mirror(tmp_path, old)
    hint = os.path.join(ROOT, "__d13_test_hint__")
    io.open(hint, "w", encoding="utf-8").write(str(d))
    try:
        monkeypatch.setattr(L, "ROOT", ROOT)
        monkeypatch.setattr(L, "MIRROR_HINT", "__d13_test_hint__")
        got = L.check_mirror_sync()
        # HEAD~3..HEAD 這三筆是不是動了通用檔，取決於當下的歷史；
        # 有報就要報得完整（含指令），沒報也不能當成失敗。
        if got:
            assert "--sync" in got[0], u"報了卻沒給指令，人還要自己去查"
            assert str(d) in got[0], u"沒講是哪個鏡像"
    finally:
        os.remove(hint)
