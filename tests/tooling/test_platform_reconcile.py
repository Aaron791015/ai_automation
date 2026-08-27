# -*- coding: utf-8 -*-
"""平台啟動時的狀態調和（2026-08-24 走查發現的盲點 ③④）。

## 為什麼要有這一支

平台的「進行中」狀態壞掉的方式**剛好相反**，而且兩個都是錯的：

| | 平台被 kill 之後 | 人看到什麼 |
| --- | --- | --- |
| run | `manager._runs` 是程序內字典，沒了 | **從 UI 完全消失** —— 總覽沒有、執行紀錄也沒有（`run_index` 只收終態） |
| session | 收尾在 `finally`，不會執行 | **永遠顯示執行中**，且沒有任何機制會清 |

實測（2026-08-24）：跑一個 run 到 33% 時中止平台 → 重啟後只有直接打 URL
才看得到一個永遠停在 33% 的頁面。而**第一次接上調和時，磁碟上已經累積了
4 個這樣的孤兒** —— 沒有人發現，因為它們在 UI 上不存在。

使用方式：`pytest tests/tooling/test_platform_reconcile.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod(tmp_path, monkeypatch):
    """把 run 與 session 的根目錄都導到 tmp。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import reconcile, run_store
    runs = tmp_path / "runs"
    runs.mkdir()
    (tmp_path / "sessions").mkdir()
    monkeypatch.setattr(run_store, "RUNS_DIR", str(runs))
    monkeypatch.setattr(reconcile, "LOGS_DIR", str(tmp_path))
    return reconcile, run_store


def _run(runs_dir, run_id, phase, **extra):
    d = os.path.join(runs_dir, run_id)
    os.makedirs(d, exist_ok=True)
    st = {"run_id": run_id, "phase": phase, "tool_id": "ui_tests",
          "started_at": "2026-08-24 16:32:22", **extra}
    io.open(os.path.join(d, "run_status.json"), "w", encoding="utf-8").write(
        json.dumps(st, ensure_ascii=False))
    return d


def _read(runs_dir, run_id):
    return json.load(io.open(os.path.join(runs_dir, run_id, "run_status.json"),
                             encoding="utf-8"))


# ── run ───────────────────────────────────────────────────
def test_非終態的run會被標成中止而不是失敗(tmp_path, monkeypatch):
    """⛔ 標 `failed` 會讓熱度圖把它算成基礎設施故障 ——
    而那一輪可能跑得好好的，只是平台被關掉了。"""
    rec, rs = _mod(tmp_path, monkeypatch)
    _run(rs.RUNS_DIR, "r1", "starting", progress={"percent": 33.3, "current": 20, "total": 60})
    assert rec.on_startup()["runs"] == 1
    st = _read(rs.RUNS_DIR, "r1")
    assert st["phase"] == "stopped", "不可以標成 failed"
    assert st["interrupted"] is True, "要標得出來這是中斷、不是正常停止"
    assert st["ended_at"], "沒有結束時間的話 run_index 排序會出問題"
    assert "重啟" in st["error"]


def test_中斷時進度要保留原樣(tmp_path, monkeypatch):
    """⚠️ 歸零或補成 100% 都會讓人誤判這一輪跑完了。"""
    rec, rs = _mod(tmp_path, monkeypatch)
    _run(rs.RUNS_DIR, "r1", "running", progress={"percent": 33.3, "current": 20, "total": 60})
    rec.on_startup()
    assert _read(rs.RUNS_DIR, "r1")["progress"]["percent"] == 33.3


@pytest.mark.parametrize("phase", ["completed", "failed", "stopped"])
def test_已經結束的run一個都不動(tmp_path, monkeypatch, phase):
    rec, rs = _mod(tmp_path, monkeypatch)
    _run(rs.RUNS_DIR, "r1", phase, ended_at="2026-08-24 10:00:00")
    assert rec.on_startup()["runs"] == 0
    st = _read(rs.RUNS_DIR, "r1")
    assert st["phase"] == phase
    assert "interrupted" not in st


def test_調和之後run才進得了執行紀錄(tmp_path, monkeypatch):
    """★ 這是**盲點的核心**：`run_index` 只收終態的 run，
    所以卡在 `starting` 的孤兒在「執行紀錄」裡也找不到 —— 從 UI 完全消失。"""
    rec, rs = _mod(tmp_path, monkeypatch)
    _run(rs.RUNS_DIR, "r1", "starting")
    assert _read(rs.RUNS_DIR, "r1")["phase"] not in rs.TERMINAL
    rec.on_startup()
    assert _read(rs.RUNS_DIR, "r1")["phase"] in rs.TERMINAL


# ── session ───────────────────────────────────────────────
def _sess(tmp_path, sid, meta):
    d = tmp_path / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    io.open(str(d / "meta.json"), "w", encoding="utf-8").write(
        json.dumps({"id": sid, **meta}, ensure_ascii=False))
    return d / "meta.json"


def test_卡在running的session會被收掉(tmp_path, monkeypatch):
    rec, _ = _mod(tmp_path, monkeypatch)
    p = _sess(tmp_path, "s1", {"activity": "running", "activity_started_at": "2026-08-24 16:30:00"})
    assert rec.on_startup()["sessions"] == 1
    m = json.load(io.open(str(p), encoding="utf-8"))
    assert m["activity"] == "idle"
    assert m["activity_interrupted"] is True


def test_不可以清掉待確認的產出(tmp_path, monkeypatch):
    """⚠️ `pending_review` 是「上一輪交了什麼」，與這一輪有沒有跑完無關 ——
    清掉等於把人還沒看的產出提示一起丟了。"""
    rec, _ = _mod(tmp_path, monkeypatch)
    review = {"at": "2026-08-24 15:00", "items": [{"kind": "bug", "text": "已開單 X-001"}]}
    p = _sess(tmp_path, "s1", {"activity": "running", "pending_review": review})
    rec.on_startup()
    m = json.load(io.open(str(p), encoding="utf-8"))
    assert m["pending_review"] == review


def test_閒置的session不動(tmp_path, monkeypatch):
    rec, _ = _mod(tmp_path, monkeypatch)
    p = _sess(tmp_path, "s1", {"activity": "idle"})
    assert rec.on_startup()["sessions"] == 0
    assert "activity_interrupted" not in json.load(io.open(str(p), encoding="utf-8"))


def test_壞掉的meta不會拖垮整輪調和(tmp_path, monkeypatch):
    """一個壞檔不該讓其他 session 收不了尾。"""
    rec, _ = _mod(tmp_path, monkeypatch)
    bad = tmp_path / "sessions" / "broken"
    bad.mkdir(parents=True)
    io.open(str(bad / "meta.json"), "w", encoding="utf-8").write("{ 不是 json")
    _sess(tmp_path, "s1", {"activity": "running"})
    assert rec.on_startup()["sessions"] == 1
