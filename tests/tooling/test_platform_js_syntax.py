# -*- coding: utf-8 -*-
"""前端 JS 的語法把關（沒有 build step，壞了只在瀏覽器 console 才看得到）。

為什麼需要這一支
    平台的前端是**原生 ES module，沒有打包也沒有 lint** —— 語法錯誤不會有任何
    紅燈，只會讓那一頁**整片空白**，而唯一的線索躺在瀏覽器 console 裡。

    這個 codebase 已經踩過三次同一類「跳脫」問題：
      · CSS 檔裡的 `*/` 提前結束註解
      · `html` 樣板巢狀時的二次跳脫
      · 2026-08-23：在樣板裡照 markdown 習慣寫了一對反引號包住字 ——
        **那對反引號直接把樣板收掉**，`#/sessions` 整頁空白，
        console 只說「Unexpected identifier」

做法
    用 **Node 自己的 parser**（`node --check`）—— 手寫的括號／反引號計數會被
    樣板裡的 HTML、正則、字串常值誤傷（實測誤報 10 支以上），不值得維護。
    ⚠️ 檔案要以 `.mjs` 餵給它：這些是 ES module，用預設的 CommonJS 解析會
    在 `import` 那行就掛掉。

前置條件：本機要有 Node。沒有就 skip —— 這是**加分的防線**，不是必要條件。
使用方式：`pytest tests/tooling/test_platform_js_syntax.py -q`
"""
import os
import shutil
import subprocess
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS_DIR = os.path.join(ROOT, "tools", "test_platform", "web_ui", "static", "js")

_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="本機沒有 Node —— 這道防線是加分的，不是必要的")


def _js_files():
    out = []
    for dirpath, dirnames, files in os.walk(JS_DIR):
        dirnames[:] = [d for d in dirnames if d != "node_modules"]
        for f in sorted(files):
            if f.endswith(".js"):
                out.append(os.path.join(dirpath, f))
    return out


@needs_node
def test_有js檔可檢查():
    """先釘住前提 —— 路徑改了而測試靜靜地什麼都沒檢查，比沒有測試更糟。"""
    assert len(_js_files()) >= 10, u"只找到 %d 支 JS，路徑可能變了" % len(_js_files())


@needs_node
def test_每支js都通過node的語法檢查():
    """★ 語法錯 ＝ 那一頁整片空白，而且沒有任何紅燈會告訴你。"""
    bad = []
    tmp = tempfile.mkdtemp(prefix="jscheck-")
    try:
        for path in _js_files():
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            # ⚠️ 必須是 .mjs —— 預設的 CommonJS 解析會在 import 那行就掛
            dst = os.path.join(tmp, os.path.basename(path)[:-3] + ".mjs")
            shutil.copyfile(path, dst)
            p = subprocess.run([_NODE, "--check", dst],
                               capture_output=True, text=True, timeout=30)
            if p.returncode != 0:
                first = next((ln for ln in (p.stderr or "").splitlines()
                              if "Error" in ln or "error" in ln), (p.stderr or "").strip()[:160])
                bad.append("%s → %s" % (rel, first))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert not bad, "\n  ".join([u"這幾支 JS 語法有問題（該頁會整片空白）："] + bad)


# ─────────────────────────────── sys.path 的紀律

def test_不得在模組層動sys_path():
    """★ 核心迴歸：模組層的 `sys.path.insert` 會污染整場 pytest。

    收集整個 `tests/` 時所有測試模組都會被 import，模組層的 insert 會讓
    `core` 解析到平台的 `core` 套件 —— 而 `tests/<產品>/perf/` 要的是
    `tools/<產品>_Performance/core`。

    ⚠️ 代價不只是收集錯誤：`case_index` 的 collect 一失敗，
       **整個案例索引就掉成 0 條**，案例瀏覽器整片空白
       （2026-08-23 實測，12 個 ERROR）。

    既有測試的檔頭早就寫著「⚠️ 匯入延後到函式內」—— 這條測試把它變成紅燈。
    """
    import io as _io
    import re as _re
    d = os.path.join(ROOT, "tests", "tooling")
    bad = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py"):
            continue
        for i, ln in enumerate(_io.open(os.path.join(d, f), encoding="utf-8"), 1):
            if not _re.match(r"^sys\.path\.(insert|append)", ln):
                continue
            # ⭐ 判準是**插了什麼**，不是「有沒有插」：
            #    `scripts/` 沒有與別的工具重名的套件，模組層插它是安全的
            #    （conftest 本來就這樣做）。危險的是 `tools/` 底下的目錄 ——
            #    那裡的 `core`／`runner`／`collect` 在多個工具之間重複。
            if '"tools"' in ln or "'tools'" in ln or "tools/" in ln or "tools\\" in ln:
                bad.append("%s:%d %s" % (f, i, ln.strip()[:70]))
    assert not bad, (
        u"這幾行在**模組層**把 `tools/` 底下的目錄插進 sys.path —— "
        u"會污染整場 pytest，把別的產品同名的套件蓋掉。移進函式裡：\n  "
        + "\n  ".join(bad))
