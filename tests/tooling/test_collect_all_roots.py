# -*- coding: utf-8 -*-
"""⛔ `pytest --collect-only tests` 必須零錯誤（2026-08-24 走查）。

## 為什麼需要一支專門的測試

平台的**案例索引**是唯一會「一次收集整個 `tests/`」的地方
（`collect/case_index.run_collect()`）。而 2026-08-24 走查發現它**一直在失敗**：

    {"ok": true, "count": 1059, "stale": true,
     "collect_error": "ModuleNotFoundError: No module named 'core.redact' …"}

`ok: true` 但 `stale: true` —— `rebuild()` 在 collect 失敗時刻意「沿用上一次的
快取並標 stale」（那個設計是對的：索引壞掉不該讓整頁空白），
於是**案例數從來不變、按幾次「重建索引」都一樣**，而且沒有人注意到。
修好之後從 935 條 ＋ 12 個錯誤變成 **1,198 條、零錯誤**。

## 成因：收集期的 `core` 命名衝突

`tests/tooling` 的三個檔在**模組層**寫 `pytestmark = skipif(_a_product() is None)`，
而 `_a_product()` 會 `from core.registry import …` → `sys.modules['core']`
在收集期被綁成**平台的 core**。接著收集 `tests/wbot/perf/`（字母序在後）時，
它想讓 `core` 指向 `tools/wbot_Performance/core`，但位子已經被佔住了。

## ★ 為什麼日常指令抓不到

單獨跑 `pytest tests/tooling` 或 `pytest tests/wbot/perf` **都是綠的** ——
只有**一起收集**才會炸。而沒有人會手動跑 `pytest tests`（太慢），
所以它躲過了所有人的日常指令。這支測試就是補上那個缺口。

使用方式：`pytest tests/tooling/test_collect_all_roots.py -q`
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _collect(*targets):
    """跑一個**獨立的**收集程序 —— 必須獨立，因為問題就出在 `sys.modules` 的狀態。"""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *targets],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return r


def test_整包收集零錯誤():
    """⛔ 這是平台案例索引能不能重建的**必要條件**。"""
    r = _collect("tests")
    tail = (r.stdout or "")[-2500:] + (r.stderr or "")[-1500:]
    assert "errors during collection" not in tail, tail
    assert "ERROR " not in (r.stdout or ""), tail
    assert r.returncode in (0, 5), "collect 退出碼 %s%s%s" % (r.returncode, os.linesep, tail)


def test_兩個有core同名套件的目錄可以一起收集():
    """★ 這一組就是當年炸掉的組合 —— 字母序 `tooling` 在 `wbot` 之前。

    ⛔ 別把這條併進上一條：分開列的用意是**指名道姓**，
       日後再炸時錯誤訊息就直接說得出是哪兩邊在搶 `core`。

    ⚠️ 這一條**只斷言 `core` 沒被搶走**，不斷言「零錯誤」——
       因為這兩個目錄底下**還有第二個同名衝突**：兩邊都有 `conftest.py`，
       而 `tests/tooling` 的幾支測試寫了 `import conftest`（沿用已久）。
       只指定這兩個目錄時，誰先佔住 `sys.modules['conftest']` 會隨參數順序改變。
       ⭐ 那個衝突**不影響平台**（它跑的是 `pytest --collect-only tests`，
          由上一條測試守著）；列在這裡是為了不讓它被無聲吞掉。
    """
    r = _collect("tests/tooling", "tests/wbot/perf")
    tail = (r.stdout or "")[-3000:]
    assert "No module named 'core." not in tail, (
        "`core` 又被誰在收集期綁死了 —— 模組層不可以 import 平台的 core。"
        + os.linesep + tail)


def test_模組層守衛不得載入平台():
    """靜態防線：`pytestmark` 那一行不可以呼叫會 import 平台的函式。

    ⚠️ 光靠上面兩條「跑跑看」不夠 —— 它們慢（每條要起一個 pytest），
       日後有人加新檔時不會先想到跑它。這一條掃原始碼，秒級。
    """
    import glob
    import io
    bad = []
    for p in sorted(glob.glob(os.path.join(ROOT, "tests", "tooling", "*.py"))):
        src = io.open(p, encoding="utf-8").read()
        for line in src.split("\n"):
            if line.startswith("pytestmark") and "_a_product" in line:
                bad.append("%s：%s" % (os.path.basename(p), line.strip()))
    assert not bad, (
        "模組層守衛呼叫了會 import 平台 core 的函式，會在收集期綁死 `core`："
        + os.linesep + os.linesep.join(bad))
