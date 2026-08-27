# -*- coding: utf-8 -*-
"""生成器這一層的兩個「宣告了沒人做」。

為什麼需要這一支
    平台的案例生成是**可替換供應者**的設計（`generators/base.py`）。
    介面留得很好，但 2026-08-23 用 CRUX 實跑範本時撞到兩個缺口，
    **兩個都不會有紅燈**：

      ① `generators/__init__.py` 一直寫著 `if name == "claude": from generators.claude
         import ClaudeGenerator  # M6` —— 而那個檔**不存在**。
         把 `platform_config.json` 的 `generator` 設成 `claude` 就是 ImportError。

      ② `PytestAdapter` 沒有覆寫 `list_cases()`，base 的預設回 `None`。
         呼叫端一律寫成 `(… or {}).get("flat") or []` → **既有案例永遠 0 條**，
         規則式生成器的核心機制（找結構範本）從此失效，產出全部退化成 low。

使用方式：`pytest tests/tooling/test_platform_generators.py -q`
"""
import os
import sys

import pytest

import conftest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _platform_path():
    """⚠️ 不可以在模組層插 sys.path（見 `test_platform_js_syntax` 的同名檢查）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)


# ─────────────────────────────── ① 兩個供應者都載得起來

def test_兩個供應者都載得起來():
    """★ 核心迴歸：`claude` 這個名字被宣告了三年，模組卻不存在。"""
    _platform_path()
    from generators import get_generator
    for name in ("rulebased", "claude"):
        g = get_generator(name)
        assert g.name == name
        assert g.disclaimer, u"%s 沒有 disclaimer —— UI 要靠它標示「請務必檢視」" % name


def test_未知的供應者要明確報錯():
    _platform_path()
    from generators import get_generator
    with pytest.raises(ValueError):
        get_generator("不存在的供應者")


# ─────────────────────────────── ② claude 供應者的解析與護欄

def test_從有前後文的回覆挖得出JSON():
    """模型幾乎一定會加說明文字 —— 只試 `json.loads(text)` 會整批失敗。"""
    _platform_path()
    from generators.claude import _first_json_array
    assert _first_json_array('說明\n```json\n[{"title":"x"}]\n```\n尾巴') == [{"title": "x"}]
    assert _first_json_array('前言 [{"title":"y"}] 後語') == [{"title": "y"}]
    assert _first_json_array("完全沒有陣列") is None


def test_索引裡沒有的POM方法一律丟掉():
    """⛔ 模型發明的方法名放行就是 `AttributeError`，而那要跑起來才看得到。"""
    _platform_path()
    from generators.claude import ClaudeGenerator
    pom = [{"cls": "BetLimitPage", "method": "goto", "args": [], "doc": "",
            "module": "pages.bet_limit", "path": "tools/crux_qa/pages/bet_limit.py"}]
    allowed = {"BetLimitPage.goto"}
    got = ClaudeGenerator._keep_real_pom(
        ["BetLimitPage.goto", "BetLimitPage.這個不存在", {"cls": "X", "method": "y"}],
        pom, allowed)
    assert [m["method"] for m in got] == ["goto"]


def test_產碼失敗時退回的骨架一定會skip():
    """⛔ 不可以留一條「必然通過」的假綠燈。"""
    _platform_path()
    from generators.claude import _fallback_code
    code = _fallback_code({"title": "某案例", "expected": "某期望"}, "backend_page", "CRUX")
    assert "pytest.skip" in code
    assert "assert" not in code


# ─────────────────────────────── ③ 既有案例真的交得出來

def test_pytest_adapter_交得出既有案例():
    """★ 核心迴歸：base 的預設回 None，呼叫端吞掉 → 既有案例永遠 0 條。"""
    _platform_path()
    from core.registry import get_registry
    from adapters import get_adapter
    spec = get_registry().tools.get("ui_tests")
    if not spec:
        pytest.skip("這個工作區沒有註冊 ui_tests")
    got = get_adapter(spec).list_cases()
    assert got is not None, u"PytestAdapter 沒有覆寫 list_cases —— 既有案例會永遠是 0 條"
    assert "flat" in got, u"回傳裡沒有 flat，drafts._context() 拿不到既有案例"


# ─────────────────────────────── ④ 產碼不重複跑

def test_產碼結果會被快取_案例改了才失效():
    """★ Claude 供應者一條案例一次 API 呼叫（實測 12 條 422 秒）。

    `commit()` 內部又呼叫 `preview()` —— 不快取就是同一份碼產兩次。
    規則式是毫秒級所以一直沒人發現。
    """
    _platform_path()
    from core import case_writer

    calls = {"n": 0}

    class _Fake:
        name = "fake"
        disclaimer = ""

        def write_code(self, case, ctx):
            calls["n"] += 1
            return "def test_x():\n    assert True\n"

        def module_header(self, draft):
            return '"""x"""\n'

    # ⛔ 這裡先前寫死 `crux` —— 匯出的範本沒有這個產品，`case_writer` 會丟
    #    「產品 crux 沒有登記」。它跟本測試要驗的「產碼有沒有被快取」毫無關係。
    slug, _ = conftest.need_product()
    draft = {"title": "快取測試", "product": slug,
             "cases": [{"id": "C01", "title": "a", "product": slug}]}
    gen = _Fake()
    case_writer.preview(draft, gen)
    first = calls["n"]
    assert first == 1
    case_writer.preview(draft, gen)
    assert calls["n"] == first, u"第二次應該走快取，卻又產了一次"

    draft["cases"].append({"id": "C02", "title": "b", "product": slug})
    case_writer.preview(draft, gen)
    assert calls["n"] > first, u"案例改了，快取應該失效"


def test_語言標籤要被剝掉():
    """★ 核心迴歸：```python 的「python」變成程式碼第一行 → NameError。"""
    _platform_path()
    from generators.claude import _strip_fence
    assert _strip_fence("說明\n```python\nimport pytest\n```") == "import pytest"
    assert _strip_fence("```\ndef f(): pass\n```") == "def f(): pass"
