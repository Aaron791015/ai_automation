# -*- coding: utf-8 -*-
"""live 模式的產出必須落在**真實位置**，不是 Demo 沙箱。

為什麼要一支專門的測試
    平台有兩組「產出落點」常數，它們的註解都寫著「M1 之後要切成真實落點時，
    只需要改這兩個常數」—— 而那一步都沒做：

      · `BUG_OUT_DIR`   → 開單永遠寫進 `demo/output/bugs/`
      · `TESTS_OUT_DIR` → 寫案例永遠寫進 `demo/generated_tests/`

    ⚠️ 兩者的症狀都是**功能斷掉，而不是顯示問題**：
       案例寫出去了，但 `collect_roots()` 只在 demo 模式才把沙箱加進掃描範圍，
       於是 live 模式下寫的案例**索引掃不到、跑不了**，也不在 `tests/` 裡不會被版控。
       而確認框當時還寫著「⛔ 不碰 tests/」，讓人以為那是刻意的設計。

    Demo 模式必須維持原樣 —— 那是原型 repo，`tests/` 是版控目錄且別的 session 正在用。

使用方式：`pytest tests/tooling/test_platform_live_outputs.py -q`
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mods():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import case_writer
    from web_ui.api import bugs_file
    return case_writer, bugs_file


def _a_product():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import get_registry
    real = [p for p in get_registry().products if not p.get("virtual")]
    if not real:
        pytest.skip("這個工作區還沒接任何產品（乾淨範本的正常狀態）")
    return real[0]


DEMO_MARK = os.path.join("demo", "")


def test_寫案例要進真實的tests目錄():
    """★ 核心迴歸：進沙箱的話**索引掃不到**，寫出去的案例跑不了、也不會被版控。

    這正是移除 Demo 模式的直接理由之一 —— 落點常數恆指向沙箱，
    而「只有 demo 才掃沙箱」，兩者合起來就是「寫了等於沒寫」。
    """
    cw, _ = _mods()
    p = _a_product()
    out = cw.tests_out_dir(p["id"])
    assert DEMO_MARK not in out.replace("/", os.sep) + os.sep, (
        u"live 模式的案例落點還在 Demo 沙箱：%s" % out)
    assert os.path.join("tests", "") in out.replace("/", os.sep) + os.sep, (
        u"live 模式應該寫進 tests/<產品>/：%s" % out)


def test_開單要進產品的bugs目錄():
    _, bf = _mods()
    p = _a_product()
    out = bf.bug_out_dir(p.get("product_id") or p["id"])
    assert DEMO_MARK not in out.replace("/", os.sep) + os.sep, (
        u"live 模式的開單落點還在 Demo 沙箱：%s" % out)
    assert os.path.join("bugs", "") in out.replace("/", os.sep) + os.sep, out


def test_不得再出現指向沙箱的落點常數():
    """★ 通則：`*_OUT_DIR` 這類「恆指向沙箱」的常數不可以再回來。

    它們是這一輪兩個缺陷的共同成因（落單與寫案例都寫進了沙箱），
    而註解都寫著「M1 之後只需要改這兩個常數」—— 那一步從來沒做。
    """
    import io
    bad = []
    for dirpath, dirnames, files in os.walk(PLATFORM):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "logs", "cache")]
        for f in files:
            if not f.endswith(".py"):
                continue
            src = io.open(os.path.join(dirpath, f), encoding="utf-8").read()
            for const in ("TESTS_OUT_DIR", "BUG_OUT_DIR", "DEMO_OUT_DIR", "DEMO_DIR"):
                if const in src:
                    bad.append("%s → %s" % (os.path.relpath(os.path.join(dirpath, f), ROOT)
                                            .replace('\\', "/"), const))
    assert not bad, '\n  '.join([u"沙箱落點常數又回來了："] + bad)
