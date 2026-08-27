# -*- coding: utf-8 -*-
"""`scripts/trace_value.py`（規格值追蹤）的回歸測試。

用途：這支腳本是「改值前後各跑一次、確認舊值歸零」的機制。
      **它必須把「實際使用」與「刻意保留的更正註記」分開** ——
      否則每次改完值都會看到一堆命中而無從判斷是否清乾淨（2026-08-22 手動 grep 時實際踩到）。
前置條件：無（在 tmp_path 上偽造 repo 結構，不掃真實工作區）。
使用方式：`pytest tests/tooling/test_trace_value.py -q`
"""
import os

import trace_value as tv


def _repo(tmp_path, monkeypatch, files):
    """在 tmp_path 造一個假 repo，並把腳本的 ROOT 指過去。"""
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    monkeypatch.setattr(tv, "ROOT", str(tmp_path))
    return str(tmp_path)


def test_找到實際使用處(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch, {
        "CLAUDE.md": "起始日須 ≥ 2025-01-02\n",
        "docs/a.md": "另一處也寫 2025-01-02\n",
    })
    assert tv.trace("2025-01-02", [".md"], with_memory=False) == 1
    out = capsys.readouterr().out
    assert "實際使用（2 處" in out and "CLAUDE.md:1" in out


def test_更正註記與實際使用分開(tmp_path, monkeypatch, capsys):
    """★ 核心行為：`> （原寫 X…）` 這類刻意保留的說明不該算成殘留。"""
    _repo(tmp_path, monkeypatch, {
        "CLAUDE.md": "現行值 ≥ 2025-01-01\n> （2026-08-22 更正：原寫 2025-01-02）\n",
    })
    assert tv.trace("2025-01-02", [".md"], with_memory=False) == 0   # 只剩註記 → 視為已清乾淨
    out = capsys.readouterr().out
    assert "實際使用 0 處" in out and "註記 1 處" in out


def test_對照表與變更說明也算註記(tmp_path, monkeypatch, capsys):
    """★ 回歸保障：這兩種寫法原本被誤報成殘留（2026-08-22 實測踩到）。

    ① 對照表左欄用 ❌ 標記而非「作廢」二字
    ② 變更說明「由 X 放寬為 Y」同一行同時含舊值與新值
    """
    _repo(tmp_path, monkeypatch, {
        "a.md": "| 原本記的（❌） | 現行 |\n| 中點 (下注賠率+總監賠率)/2 | 回水口徑 |\n",
        "b.md": "起始日下限由 2025-01-02 放寬為 2025-01-01\n",
    })
    assert tv.trace("下注賠率+總監賠率", [".md"], with_memory=False) == 0
    assert tv.trace("2025-01-02", [".md"], with_memory=False) == 0


def test_全庫零命中(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch, {"CLAUDE.md": "沒有那個值\n"})
    assert tv.trace("不存在的值", [".md"], with_memory=False) == 0
    assert "✅ 全庫零命中" in capsys.readouterr().out


def test_會掃到_repo_外的_memory(tmp_path, monkeypatch, capsys):
    """memory 沒有版控也沒有 lint，是漂移重災區 —— 一定要掃到。"""
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "old.md").write_text("公式＝中點口徑\n", encoding="utf-8")
    _repo(tmp_path, monkeypatch, {"CLAUDE.md": "無關內容\n"})
    assert tv.trace("中點口徑", [".md"], with_memory=True, mem_dir=str(mem)) == 1
    assert "memory/old.md:1" in capsys.readouterr().out


def test_no_memory_時不掃(tmp_path, monkeypatch, capsys):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "old.md").write_text("中點口徑\n", encoding="utf-8")
    _repo(tmp_path, monkeypatch, {"CLAUDE.md": "無關\n"})
    assert tv.trace("中點口徑", [".md"], with_memory=False, mem_dir=str(mem)) == 0


def test_跳過不該掃的目錄(tmp_path, monkeypatch, capsys):
    """bugs/ 是當時的快照，本來就該保留當時的值，不算殘留。"""
    _repo(tmp_path, monkeypatch, {
        "docs/CRUX/bugs/CRUX-001_x.md": "舊值 2025-01-02\n",
        "docs/CRUX/機制.md": "無關\n",
    })
    assert tv.trace("2025-01-02", [".md"], with_memory=False) == 0


def test_memory_目錄由_repo_路徑推導(monkeypatch):
    monkeypatch.setattr(tv, "ROOT", r"c:\GitLab\Automation")
    assert tv.memory_dir().endswith(os.path.join("projects", "c--GitLab-Automation", "memory"))
