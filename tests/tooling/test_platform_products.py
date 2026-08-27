# -*- coding: utf-8 -*-
"""測試平台的產品定義接通 `config/products.json`（階段 A，2026-08-23）。

用途：平台原本**完全不知道 `config/products.json` 的存在**（grep 零命中），
      自己存一份 `registry/products.json`，其中 `docs_dir`／`bug_product`／
      `tests_prefix`／`skill`／`handover` 五個欄位與 config 那份完全重複 ——
      同事跑 `new_product.py` 之後**平台看不到那個產品**。

      三件事要釘住：
      ① 產品來自 config（單一來源），呈現層只覆寫顏色字樣
      ② **id ↔ slug 的映射**（config 是 `CRUX`／中文，平台是 `crux`／slug）
      ③ **缺呈現層條目時仍要顯示**（給預設配色）—— 那正是同事會遇到的狀態

前置條件：⚠️ 匯入延後到函式內（比照 `test_argv_build.py` 的檔頭說明）——
          `tools/test_platform/` 有頂層 `core` 套件，`tools/wbot_Performance/` 也有，
          模組層 import 會在收集階段把 `sys.modules["core"]` 釘死。
使用方式：`pytest tests/tooling/test_platform_products.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _registry():
    """延後匯入（理由見檔頭）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.registry as R
    return R


def _merge(monkeypatch, workspace, display):
    R = _registry()
    monkeypatch.setattr(R, "load_workspace_products", lambda: workspace)
    return R._merge_products(display)


WS_ONE = [{"id": "甲產品", "label": "甲", "docs_dir": "Alpha", "bug_prefix": "ALPHA",
           "aliases": ["alpha"], "tests_dir": "alpha", "skill": "alpha",
           "jira_key": "AL", "handovers": ["docs/Alpha/甲_驗證交接.md"]}]


def test_產品來自config而非平台自己那份(monkeypatch):
    got = _merge(monkeypatch, WS_ONE, [])
    # ⚠️ `common` 一定在（見下一條）—— 真產品只有 alpha
    assert [p["id"] for p in got if not p.get("virtual")] == ["alpha"]
    assert got[0]["product_id"] == "甲產品"
    assert got[0]["bug_prefix"] == "ALPHA"


def test_common偽產品一定存在即使呈現層是空的(monkeypatch):
    """★ 2026-08-24：`common` 是**平台內建的概念**（跨產品工具的歸屬），
    先前它只從 `registry/products.json` 來 —— 而範本的骨架是
    `{"products": []}`，於是**同事的平台一開起來就是**

        workspace_ops 引用了不存在的產品：['common']

    ⛔ 不可以改成「在骨架裡寫死 common」—— 那份檔案同事會改、
       `reset_workspace` 會清。內建概念要由**程式碼**保證。
    """
    for ws in (WS_ONE, []):                      # 有產品／一個都沒有，兩種都要有
        got = _merge(monkeypatch, ws, [])
        c = next((p for p in got if p["id"] == "common"), None)
        assert c, "common 不見了（workspace_ops 會對不到產品）"
        assert c["virtual"] is True, "common 必須標 virtual —— 它不參與知識雷達與交接檔檢查"
        assert c.get("hero_pillar") is False, "common 不該出現在主視覺的柱子上"


def test_id與slug的映射(monkeypatch):
    """config 用中文／大寫 id（Bug 前綴、lint --product），平台用小寫 slug（URL、tool.json 的鍵）。"""
    got = _merge(monkeypatch, WS_ONE, [])[0]
    assert got["id"] == "alpha"            # slug：給 #/product/<id> 與 tool.json
    assert got["product_id"] == "甲產品"    # 權威 id：給 gen_bug_index／lint_docs


def test_沒有aliases時退回skill當slug(monkeypatch):
    ws = [dict(WS_ONE[0], aliases=[])]
    assert _merge(monkeypatch, ws, [])[0]["id"] == "alpha"


def test_缺呈現層條目仍要顯示並給預設配色(monkeypatch):
    """★ 這正是同事會遇到的狀態 —— 不可因為沒設定就不顯示他的產品。"""
    got = _merge(monkeypatch, WS_ONE, [])[0]
    assert got["color"].startswith("#") and len(got["color"]) == 7
    assert got["hero_pillar"] is True
    assert got["wordmark"] == "ALPHA"


def test_呈現層只覆寫外觀不覆寫權威欄位(monkeypatch):
    display = [{"id": "alpha", "label": "我改的標籤", "color": "#123456",
                "wordmark": "ALPHA2", "env_badge": "QAT ⛔", "order": 9,
                # 就算呈現層亂寫這些，也不該蓋掉 config 的權威值
                "knowledge": {"docs_dir": "docs/亂寫"}}]
    got = _merge(monkeypatch, WS_ONE, display)[0]
    assert got["color"] == "#123456" and got["label"] == "我改的標籤"
    assert got["knowledge"]["docs_dir"] == "docs/Alpha"      # 權威值不被覆寫
    assert got["knowledge"]["bug_product"] == "甲產品"


def test_knowledge欄位對應正確(monkeypatch):
    k = _merge(monkeypatch, WS_ONE, [])[0]["knowledge"]
    assert k["docs_dir"] == "docs/Alpha"
    assert k["tests_prefix"] == "tests/alpha/"
    assert k["handover"] == ["docs/Alpha/甲_驗證交接.md"]


def test_平台獨有的偽產品要保留並標virtual(monkeypatch):
    """`common`（共通）在 config 那份不存在，但 tool.json 會引用它 —— 不可弄丟。"""
    got = _merge(monkeypatch, WS_ONE, [{"id": "common", "label": "共通", "order": 99}])
    common = next(p for p in got if p["id"] == "common")
    assert common["virtual"] is True
    assert next(p for p in got if p["id"] == "alpha")["virtual"] is False


def test_config讀不到時不整個掛掉(monkeypatch):
    """剛匯出的範本 products 是空的 —— 平台仍要靠偽產品運作。"""
    got = _merge(monkeypatch, [], [{"id": "common", "label": "共通"}])
    assert [p["id"] for p in got] == ["common"]


# ─────────────────────────────── products: "*"

def test_萬用字元跟著config展開且不含偽產品(monkeypatch):
    """★ 標準內建工具（`ui_tests`）不該硬編碼產品清單 ——
    同事接了自己的產品，UI Test 要自動涵蓋。"""
    R = _registry()
    fake = R.Registry(products=[{"id": "alpha", "virtual": False},
                                {"id": "beta", "virtual": False},
                                {"id": "common", "virtual": True}])
    monkeypatch.setattr(R, "load_registry", lambda force=False: fake)
    spec = R.ToolSpec(raw={"id": "t", "products": "*"}, path="t.tool.json")
    assert spec.products == ["alpha", "beta"]


def test_明列的產品清單不受影響(monkeypatch):
    R = _registry()
    spec = R.ToolSpec(raw={"id": "t", "products": ["alpha"]}, path="t.tool.json")
    assert spec.products == ["alpha"]
    spec2 = R.ToolSpec(raw={"id": "t", "product": "alpha"}, path="t.tool.json")
    assert spec2.products == ["alpha"]


def test_validate接受萬用字元也擋掉亂寫():
    R = _registry()
    base = {"id": "t", "name": "T", "kind": "cli", "commands": []}
    assert not [e for e in R.validate_spec(dict(base, products="*"), "t.tool.json")
                if "products" in e["error"]]
    assert [e for e in R.validate_spec(dict(base, products="all"), "t.tool.json")
            if "products" in e["error"]]


# ─────────────────────────────── 真實 repo

def test_真實registry載入無誤且工具都對得到產品():
    """★ A 的迴歸：既有五支 tool.json 引用的是 slug（`crux`／`common`…）——
    映射沒做好會讓所有工具找不到產品。"""
    R = _registry()
    reg = R.load_registry(force=True)
    assert reg.errors == [], reg.errors
    slugs = {p["id"] for p in reg.products}
    for tid, spec in reg.tools.items():
        assert set(spec.products) <= slugs, "%s 引用了不存在的產品：%s" % (tid, spec.products)


def test_真實產品的權威欄位來自config():
    R = _registry()
    reg = R.load_registry(force=True)
    cfg = json.load(io.open(os.path.join(ROOT, "config", "products.json"),
                            encoding="utf-8"))["products"]
    by_slug = {(p.get("aliases") or [p["id"]])[0]: p for p in cfg}
    for p in reg.products:
        if p.get("virtual"):
            continue
        src = by_slug[p["id"]]
        assert p["product_id"] == src["id"]
        assert p["knowledge"]["docs_dir"] == "docs/%s" % src["docs_dir"]
