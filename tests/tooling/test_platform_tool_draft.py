# -*- coding: utf-8 -*-
"""接新工具的介面（階段 B-3）：`core/tool_draft.py` 的四段式。

為什麼這組測試值得寫
    使用者明確要求「**接新工具需要有介面可以進行**」，而在此之前
    `registry_api.py` 對 tool.json 是**唯讀的**。

    這裡釘住三件事：
    ① **驗證失敗一定要還原** —— 留下一支壞掉的 tool.json 會讓它自己從
       `#/tools` 消失，錯誤只出現在 `#/registry` 那個平常不看的頁面，
       使用者的感受是「建好了但不見了」。
    ② **不替人猜欄位** —— `params.fields` 一律留空。猜出來的欄位會變成
       「填了不生效」，那正是階段 G 花最多力氣在防的事。
    ③ **表單層與契約層兩道檢查都要在** —— 骨架是程式組的，只驗人的輸入
       會漏掉組裝本身的錯。

使用方式：`pytest tests/tooling/test_platform_tool_draft.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mods():
    """⚠️ **不可以在模組層插 sys.path**（見 `test_platform_js_syntax` 的同名檢查）。

    收集整個 `tests/` 時所有測試模組都會被 import，模組層的 insert 會讓
    `core` 解析到平台的 `core` 套件 —— 而 `tests/<產品>/perf/` 要的是
    `tools/<產品>_Performance/core`。實測代價：12 條收集錯誤，
    而且 `case_index` 的 collect 失敗會讓**整個案例索引掉成 0 條**（2026-08-23）。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import tool_draft
    from core.registry import load_registry
    return tool_draft, load_registry

REGISTRY = os.path.join(ROOT, "tools", "test_platform", "registry")


def _draft(**kw):
    d = {"id": "zz_probe_tmp", "name": "測試探針", "kind": "cli", "scope": "workspace",
         "command_id": "run", "command_label": "執行", "argv": "-m scripts.lint_docs",
         "mode": "sync", "cwd": "."}
    d.update(kw)
    return d


@pytest.fixture
def cleanup():
    """確保測試產生的 tool.json 一定被清掉 —— 它會進真的 registry 目錄。"""
    made = []
    yield made
    for tool_id in made:
        p = os.path.join(REGISTRY, "%s.tool.json" % tool_id)
        if os.path.exists(p):
            os.remove(p)
    _mods()[1](force=True)


# ─────────────────────────────── ① 表單層檢查

def test_id_格式錯誤要擋下來():
    for bad in ("Bad-Id", "9start", "有中文", "", "with space"):
        errs = _mods()[0].check_input(_draft(id=bad))
        assert errs, "id=%r 應該被擋" % bad


def test_撞名要擋下來():
    """已存在的 id 不可覆蓋 —— 那會靜默蓋掉別人的工具。"""
    errs = _mods()[0].check_input(_draft(id="ui_tests"))
    assert any("已經有一支" in e for e in errs), errs


def test_產品層工具必須選產品():
    errs = _mods()[0].check_input(_draft(scope="product", product=None))
    assert any("產品" in e for e in errs), errs


def test_不存在的產品要擋下來():
    errs = _mods()[0].check_input(_draft(scope="product", product="不存在的產品"))
    assert any("config/products.json" in e for e in errs), errs


def test_工作區級工具豁免產品必填():
    assert _mods()[0].check_input(_draft(scope="workspace", product=None)) == []


def test_argv_必填():
    assert any("argv" in e for e in _mods()[0].check_input(_draft(argv="")))


# ─────────────────────────────── ② 組出來的骨架

def test_骨架的必要欄位齊全():
    spec = _mods()[0].build_spec(_draft())
    for k in ("$schema", "spec_version", "id", "name", "kind", "commands"):
        assert k in spec, "骨架缺 %s" % k
    assert spec["commands"][0]["primary"] is True


def test_不替人猜欄位():
    """★ `params.fields` 一律留空。

    平台猜出來的欄位會變成「填了不生效」—— 使用者在表單上填了，
    但那個值組不進命令列，而且**沒有任何跡象顯示它沒生效**。
    """
    spec = _mods()[0].build_spec(_draft())
    assert spec["commands"][0]["params"]["fields"] == []


def test_骨架帶著接入待辦():
    """建好 ≠ 接好。骨架要自己說清楚還差什麼，否則使用者會以為完成了。"""
    spec = _mods()[0].build_spec(_draft())
    todo = " ".join(spec.get("_接入待辦") or [])
    assert "params.fields" in todo
    assert "憑證" in todo, "沒提醒憑證不要放進 fields"


def test_骨架的spec_version跟著平台走():
    _mods()
    from core.registry import SPEC_VERSION
    assert _mods()[0].build_spec(_draft())["spec_version"] == SPEC_VERSION


def test_preview_不寫檔():
    before = set(os.listdir(REGISTRY))
    pv = _mods()[0].preview(_draft())
    assert pv["ok"] and pv["text"]
    assert set(os.listdir(REGISTRY)) == before, "preview 不該寫任何檔"


# ─────────────────────────────── ③ 寫檔與還原

def test_寫檔後registry真的收得到(cleanup):
    d = _draft()
    res = _mods()[0].commit(d)
    assert res["ok"], res
    cleanup.append(d["id"])
    reg = _mods()[1](force=True)
    assert d["id"] in reg.tools
    assert os.path.isfile(os.path.join(REGISTRY, "%s.tool.json" % d["id"]))


def test_registry收不下就要把檔刪掉(monkeypatch, cleanup):
    """★ 核心迴歸：驗證失敗**一定要還原**。

    留著一支壞掉的 tool.json 的話，它會佔住 id、在 `#/registry` 掛一條錯誤，
    而使用者看到的是「工具建好了但不見了」—— 那比當場失敗難查得多。
    """
    d = _draft(id="zz_probe_bad")
    tool_draft = _mods()[0]
    real = tool_draft.load_registry

    def fake(force=False):
        reg = real(force=force)
        reg.tools.pop(d["id"], None)          # 模擬 registry 拒收
        reg.errors.append({"file": "%s.tool.json" % d["id"], "error": "模擬的驗證失敗"})
        return reg

    monkeypatch.setattr(tool_draft, "load_registry", fake)
    res = _mods()[0].commit(d)
    cleanup.append(d["id"])
    assert not res["ok"]
    assert res.get("restored") is True
    assert not os.path.exists(os.path.join(REGISTRY, "%s.tool.json" % d["id"])), \
        "registry 收不下卻把檔留著了"


def test_既有工具不會被覆蓋():
    res = _mods()[0].commit(_draft(id="ui_tests"))
    assert not res["ok"]
    # 確認原檔沒被動過
    p = os.path.join(REGISTRY, "ui_tests.tool.json")
    d = json.load(io.open(p, encoding="utf-8"))
    assert d["id"] == "ui_tests" and d.get("products") == "*"


# ─────────────────────────────── ④ 端點存在

def test_寫入端點有註冊():
    """`registry_api` 先前對 tool.json 完全唯讀（只有 profiles 可寫）。"""
    import web_ui.api.registry_api as m
    assert hasattr(m, "create_tool")
    assert hasattr(m, "preview_tool")
