# -*- coding: utf-8 -*-
"""治理腳本不得自己寫死一份產品表。

為什麼需要這一支
    產品定義的單一來源是 `config/products.json`，由 `scripts/bug_paths.py` 讀出來。
    但**寫死一份**在原型裡永遠是對的 —— CRUX／投注機器人／七星三個都在，
    測試綠、lint 綠、什麼都不會響。

    它只在**同事的工作區**才會現形，而且症狀分兩種，兩種都很難查：
      · 好一點的：`ValueError` traceback（`lint_bug_assets` 2026-08-23 就是這樣）
      · 壞一點的：**靜默跳過**同事自己的產品，畫面上什麼都不少

    這正是本工作區反覆踩到的那一類（`gen_bug_index`／`jira_match_bugs`／
    `pack_bug_report` 都各自被抓出來改過一輪）。這條測試把它變成紅燈。

使用方式：`pytest tests/tooling/test_scripts_product_source.py -q`
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "scripts")

# 原型的三個產品名。出現在**字串常值**裡就是可疑
_PROTOTYPE = ("投注機器人", "七星")

# 這些檔可以提到原型產品名，理由各自不同
_ALLOWED = {
    # 單一來源自己的退路：設定檔壞掉時不讓所有腳本停擺（該檔 docstring 已說明）
    "bug_paths.py",
    # 接新產品的腳本，說明文字裡拿原型當例子
    "new_product.py",
    # 清空原型產品用的，本來就要指名它們
    "reset_workspace.py",
    # 匯出範本：白名單分類要指名產品專屬路徑
    "export_template.py",
    # 壓測欄位對照 —— 三支壓測工具是彩票專屬的，這支**本來就不進範本**
    "perf_field_parity.py",
}

# ⭐ `_FALLBACK*` 是**正當的**：設定檔讀不到時的安全網，讓 lint 不會整支停擺。
#    `bug_paths.py` 與 `lint_docs.py` 都用這個模式，且兩者都是「先讀 json、失敗才退」。
#    判準是**變數名**，不是檔案 —— 整檔豁免會讓日後新加的硬編碼跟著溜進去。
_FALLBACK_NAME = re.compile(r"^\s*_?FALLBACK|^\s*_FALLBACK")

_PAT = re.compile("['\"](%s)['\"]" % "|".join(_PROTOTYPE))


def _scripts():
    for f in sorted(os.listdir(SCRIPTS)):
        if f.endswith(".py") and f not in _ALLOWED:
            yield f, os.path.join(SCRIPTS, f)


def test_前提成立_掃得到腳本():
    """路徑改了而測試靜靜地什麼都沒檢查，比沒有測試更糟。"""
    got = list(_scripts())
    assert len(got) >= 8, u"只掃到 %d 支腳本，路徑可能變了" % len(got)


def test_治理腳本不得寫死原型產品名():
    bad = []
    for name, path in _scripts():
        for i, ln in enumerate(io.open(path, encoding="utf-8"), 1):
            if ln.lstrip().startswith("#"):
                continue          # 註解裡舉例可以
            if "_FALLBACK" in ln.split("=")[0]:
                continue          # 設定檔壞掉時的安全網，見上方說明
            m = _PAT.search(ln)
            if m:
                bad.append("%s:%d %s" % (name, i, ln.strip()[:70]))
    assert not bad, (
        u"這幾行把原型的產品名寫進程式 —— 同事的工作區沒有這些產品，"
        u"輕則 traceback、重則**靜默跳過他自己的產品**。\n"
        u"改從 `bug_paths` 取（`PRODUCTS`／`product_base()`／`PRODUCT_DIRS`）：\n  "
        + "\n  ".join(bad))


def test_lint_bug_assets的產品表來自單一來源():
    """★ 核心迴歸：2026-08-23 在只接了一個產品的範本裡踩到的那一支。"""
    t = io.open(os.path.join(SCRIPTS, "lint_bug_assets.py"), encoding="utf-8").read()
    assert "from bug_paths import" in t and "_PRODUCT_IDS" in t, \
        u"lint_bug_assets 的 PRODUCTS 必須由 bug_paths 導出"


def test_lint_bug_assets的早退回傳四個值():
    """★ 核心迴歸：剛接進來、還沒開過單的產品會走這條路，原本回三個值 → ValueError。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_lba_probe", os.path.join(SCRIPTS, "lint_bug_assets.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    got = m.lint("不存在的產品", os.path.join(ROOT, "docs", "__no_such_dir__"))
    assert len(got) == 4, u"早退回傳 %d 個值，呼叫端解 4 個 → ValueError" % len(got)
