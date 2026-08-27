# -*- coding: utf-8 -*-
"""落單時自動搬佐證截圖（`tools/test_platform/core/shot_filing.py`）。

用途：截圖先前是整條動線上**唯一要人手動接的環節**，而兩批都因此掉了
      （一批放共用暫存被清光、一批拍完沒人搬）。自動化之後要釘住三件事：

  ① **只搬被這張單引用的** —— 全搬會在 `shots/` 堆出死圖（W1）
  ② 目標檔名照規範 `<ID>_<序2碼>_<描述>.png`，且**過長要截、怪字元要換掉**
  ③ ⛔ **任何失敗都不可以讓落單失敗** —— 單子已經寫好了

前置條件：無（不真的呼叫 `stamp_shots.py`，subprocess 換掉）。
"""
import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MOD = os.path.join(ROOT, "tools", "test_platform", "core", "shot_filing.py")


@pytest.fixture
def SF(monkeypatch, tmp_path):
    """依檔案路徑載入。⛔ 不可在模組層改 `sys.path`（會綁死 `core`，見 test_collect_all_roots）。"""
    monkeypatch.syspath_prepend(os.path.join(ROOT, "tools", "test_platform"))
    spec = importlib.util.spec_from_file_location("shot_filing_ut", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "SESSIONS_DIR", str(tmp_path))
    return m


def make_shots(tmp_path, sid, names):
    d = tmp_path / sid / "shots"
    os.makedirs(str(d), exist_ok=True)
    for n in names:
        (d / n).write_bytes(b"\x89PNG\r\n\x1a\n")
    return d


def fake_run(rc=0, out=""):
    class R:
        returncode, stdout, stderr = rc, out, ""
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return R()
    return run, calls


# ─────────────────────────────── ① 只搬被引用的

def test_只搬evidence提到的那幾張(SF, tmp_path, monkeypatch):
    make_shots(tmp_path, "s1", ["甲_現象.png", "乙_過程.png", "丙_對照.png"])
    run, calls = fake_run()
    monkeypatch.setattr(SF.subprocess, "run", run)
    r = SF.file_for_bug("s1", "CRUX-114", "CRUX",
                        "佐證：截圖 `甲_現象.png`、`丙_對照.png`；API …")
    assert len(r["moved"]) == 2
    assert r["skipped"] == ["乙_過程.png"], "沒被引用的不該搬"
    pairs = [a for a in calls[0] if "=" in a]
    assert pairs[0].endswith("=CRUX-114_01_甲_現象.png")
    assert pairs[1].endswith("=CRUX-114_02_丙_對照.png")


def test_沒有引用任何圖就一張都不搬(SF, tmp_path, monkeypatch):
    make_shots(tmp_path, "s2", ["過程.png"])
    run, calls = fake_run()
    monkeypatch.setattr(SF.subprocess, "run", run)
    r = SF.file_for_bug("s2", "CRUX-114", "CRUX", "佐證：API 回應與算式明細。")
    assert r["moved"] == [] and calls == []
    assert r["skipped"] == ["過程.png"]


def test_沒有shots目錄不算錯(SF, tmp_path):
    """這一輪沒拍照是常態（唯讀驗證、純 API 比對），不該報錯。"""
    r = SF.file_for_bug("不存在", "CRUX-114", "CRUX", "佐證：截圖 `x.png`")
    assert r == {"moved": [], "skipped": [], "error": None}


# ─────────────────────────────── ② 檔名規範

@pytest.mark.parametrize("src,want", [
    ("切換彩種後篩選殘留.png", "CRUX-114_01_切換彩種後篩選殘留.png"),
    ("有 空白 與/斜線:冒號.png", "CRUX-114_01_有_空白_與_斜線_冒號.png"),
    ("大寫.PNG", "CRUX-114_01_大寫.png"),
])
def test_目標檔名照規範(SF, src, want):
    assert SF.target_name("CRUX-114", 1, src) == want


def test_過長的描述會截斷(SF):
    n = SF.target_name("CRUX-114", 2, "描" * 200 + ".png")
    assert n.startswith("CRUX-114_02_") and n.endswith(".png")
    assert len(n) < 90, "檔名過長在 Windows 上會踩到路徑上限"


def test_改善建議的S序列也認得(SF):
    assert SF.target_name("CRUX-S06", 1, "x.png") == "CRUX-S06_01_x.png"


# ─────────────────────────────── ③ 失敗不可以讓落單失敗

def test_stamp失敗只回錯誤不丟例外(SF, tmp_path, monkeypatch):
    make_shots(tmp_path, "s3", ["甲.png"])
    run, _ = fake_run(rc=1, out="⚠️ 目標已存在（要覆蓋請加 --force）")
    monkeypatch.setattr(SF.subprocess, "run", run)
    r = SF.file_for_bug("s3", "CRUX-114", "CRUX", "截圖 `甲.png`")
    assert r["moved"] == [] and "目標已存在" in r["error"]


def test_subprocess爆炸也只回錯誤(SF, tmp_path, monkeypatch):
    make_shots(tmp_path, "s4", ["甲.png"])

    def boom(*a, **k):
        raise OSError("找不到直譯器")
    monkeypatch.setattr(SF.subprocess, "run", boom)
    r = SF.file_for_bug("s4", "CRUX-114", "CRUX", "截圖 `甲.png`")
    assert r["moved"] == [] and "OSError" in r["error"]


def test_來源標記是auto不是mcp(SF, tmp_path, monkeypatch):
    """⛔ 不可冒用 `mcp` —— 那是「session 自己搬」的來源值。
    平台代搬要留得下線索：標注是拍攝當下做的，平台沒有驗證過。"""
    make_shots(tmp_path, "s5", ["甲.png"])
    run, calls = fake_run()
    monkeypatch.setattr(SF.subprocess, "run", run)
    SF.file_for_bug("s5", "CRUX-114", "CRUX", "截圖 `甲.png`")
    argv = calls[0]
    assert "--mark" in argv and argv[argv.index("--mark") + 1] == "auto"
