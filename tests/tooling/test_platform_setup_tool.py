# -*- coding: utf-8 -*-
"""工作區設定工具 `registry/setup.tool.json` 與 `scope: workspace`（階段 B，2026-08-23）。

用途：初始化介面是**宣告式**的 —— 沒有專屬視圖，全靠一份 tool.json
      （CONTRIB_TOOL 三層擴充原則的第①層）。所以要釘住的是**宣告本身**：
      ① `scope: workspace` 真的豁免產品必填，且不會讓工具在 UI 上隱形
      ② 七個命令**都組得出 argv**，且組出來的就是我們要跑的那支腳本
      ③ 破壞性命令（reset／export）的 `danger` 宣告對
      ④ ⛔ **UI 只是觸發器** —— argv 一定要指向 `scripts/`，
         不可有人日後在平台裡重寫一份建目錄邏輯

前置條件：⚠️ 匯入延後到函式內（`tools/test_platform` 與 `tools/wbot_Performance`
          都有頂層 `core` 套件，模組層 import 會在收集階段釘死 sys.modules）。
使用方式：`pytest tests/tooling/test_platform_setup_tool.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")
SETUP_JSON = os.path.join(PLATFORM, "registry", "setup.tool.json")


def _p():
    """延後匯入（理由見檔頭）。回 (registry 模組, build_invocation)。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.registry as R
    from adapters.argv import build_invocation
    return R, build_invocation


@pytest.fixture(scope="module")
def setup_spec():
    R, _ = _p()
    reg = R.load_registry(force=True)
    if "setup" not in reg.tools:
        pytest.skip("registry 沒有 setup 工具")
    return reg.tools["setup"]


@pytest.fixture(scope="module")
def ops_spec():
    """治理腳本（2026-08-24 從 setup 拆出去）。

    使用者：「設定頁面的工作區分頁中，有很多非必要的設定操作，保留必要的即可」。
    判準是**這件事是「設定／初始化」還是「拿現有的工作區做一件事」**。
    """
    R, _ = _p()
    reg = R.load_registry(force=True)
    if "workspace_ops" not in reg.tools:
        pytest.skip("registry 沒有 workspace_ops 工具")
    return reg.tools["workspace_ops"]


@pytest.fixture(scope="module")
def both(setup_spec, ops_spec):
    """兩支合起來 —— 「命令一律指向 scripts/」這條保證涵蓋全部 16 個。"""
    return [setup_spec, ops_spec]


# ─────────────────────────────── scope 機制

def test_scope_workspace豁免產品必填():
    R, _ = _p()
    base = {"id": "t", "name": "T", "kind": "cli", "commands": [{"id": "c", "label": "C", "mode": "sync"}]}
    assert R.validate_spec(dict(base, scope="workspace"), "t.tool.json") == []
    errs = [e["error"] for e in R.validate_spec(base, "t.tool.json")]
    assert any("product" in e for e in errs), "product 型工具仍該要求 product"


def test_scope只認兩個值():
    R, _ = _p()
    errs = [e["error"] for e in R.validate_spec(
        {"id": "t", "name": "T", "kind": "cli", "scope": "亂寫",
         "commands": [{"id": "c", "label": "C", "mode": "sync"}]}, "t.tool.json")]
    assert any("scope" in e for e in errs)


def test_workspace工具的products為空且product不炸():
    R, _ = _p()
    s = R.ToolSpec(raw={"id": "x", "scope": "workspace"}, path="x.tool.json")
    assert s.products == [] and s.is_workspace
    assert s.product == "workspace"        # ⚠️ 不可 IndexError


def test_public要帶出scope與解析後的products():
    """★ 迴歸：`public()` 原本原樣送出 `products: "*"`，
    而前端做的是 `(t.products).includes(pid)` —— `["*"].includes("crux")` 是 false，
    該工具會**從所有產品欄消失**（2026-08-23 實際啟動平台才發現）。"""
    R, _ = _p()
    reg = R.load_registry(force=True)
    for spec in reg.tools.values():
        pub = spec.public()
        assert pub["products"] == spec.products
        assert "*" not in pub["products"], "%s 的 public 仍含未解析的萬用字元" % spec.id
        assert pub["scope"] in ("product", "workspace")


# ─────────────────────────────── setup.tool.json 本身

# 留在「設定 → 工作區」的：**改變工作區怎麼組成的**
SETUP_EXPECTED = {
    "new_product": "scripts/new_product.py",
    "bootstrap": "scripts/bootstrap_workspace.py",
    "reset": "scripts/reset_workspace.py",
    "export": "scripts/export_template.py",
}

# 移到 `#/tools` 共通欄的：**拿現有的工作區做一件事**
OPS_EXPECTED = {
    "health": "scripts/lint_docs.py",
    # ⭐ 收尾必跑的那一支（handoff §2④）—— 產品層的 D1／D5／**D6**／D7
    #    先前平台上跑不到，只有無參數的「工作區體檢」（跨檔一致性）
    "lint_product": "scripts/lint_docs.py",
    "template_audit": "scripts/export_template.py",
    "compare": "scripts/export_template.py",
    # ── 2026-08-23 補：一天工作的頭尾原本在平台上沒有入口 ────────
    #    22 支治理腳本只給了 8 個入口，缺的剛好都在「開工」與「交付」那兩端。
    "jira_match": "scripts/jira_match_bugs.py",
    "coverage": "scripts/coverage_matrix.py",
    "bug_assets": "scripts/lint_bug_assets.py",
    "pack_report": "scripts/pack_bug_report.py",
    "archive": "scripts/archive_bugs.py",
    # ── 第二輪盤點（同日）：22 支腳本剩下的三個缺口 ─────────────
    "report_html": "scripts/md_to_html_report.py",
    "trace_value": "scripts/trace_value.py",
    "verify_platform": "scripts/verify_platform.py",
}

EXPECTED = dict(SETUP_EXPECTED, **OPS_EXPECTED)


def test_設定分頁只留設定與初始化(setup_spec):
    """★ 2026-08-24 使用者裁示：設定頁只放「改變工作區怎麼組成的」那幾支。

    ⛔ 不要再把體檢／盤點／打包塞回來 —— 16 個頁籤的設定頁沒有人找得到東西。
    """
    assert {c["id"] for c in setup_spec.commands} == set(SETUP_EXPECTED)


def test_治理腳本一支都沒少(ops_spec):
    """⛔ 拆檔最容易出的錯是「搬一半」—— 搬丟的那幾支在 UI 上就消失了，
    而且不會有任何錯誤訊息（`#/tools` 只是少一張卡）。"""
    assert {c["id"] for c in ops_spec.commands} == set(OPS_EXPECTED)


def test_治理腳本在工具頁看得到(ops_spec):
    """它不是 `scope: workspace` —— 那個 scope 會把工具導去設定頁。"""
    assert not ops_spec.is_workspace
    assert ops_spec.product == "common"


def test_每個命令都指向對的腳本(both):
    for spec in both:
        for c in spec.commands:
            assert c["argv"][0] == EXPECTED[c["id"]], (spec.id, c["id"])


def test_每個命令都組得出argv且無未處理欄位(setup_spec):
    """`notes` 非空 ＝ 有欄位宣告了 emit 卻沒有對應規則。"""
    _, build = _p()
    demo = {
        "health": {}, "template_audit": {},
        "lint_product": {"product": "CRUX"},
        "new_product": {"id": "甲", "docs_dir": "A", "bug_prefix": "AA",
                        "alias": "aa", "dry_run": True},
        "bootstrap": {"dry_run": True},
        "export": {"out": "D:/T", "dry_run": True},
        "compare": {"compare": "D:/T"},
        "reset": {"apply": False},
        "jira_match": {"product": "CRUX", "recheck": True},
        "coverage": {"file": "docs/X/Y_驗證項目清單.md", "gaps": False, "lint": True},
        "bug_assets": {"product": "CRUX", "verbose": False},
        "pack_report": {"product": "CRUX", "name": "2026-08-23_某批",
                        "ids": "CRUX-019 CRUX-020"},
        "archive": {"product": "CRUX", "status": "fixed", "yes": False},
        "report_html": {"src": "docs/X/bugs/_reports/報告.md"},
        "trace_value": {"value": "2025-01-02", "quiet": False},
        "verify_platform": {"write": False},
    }
    R, _ = _p()
    reg = R.load_registry(force=True)
    seen = set()
    for tid in ("setup", "workspace_ops"):
        spec = reg.tools.get(tid)
        if not spec:
            continue
        for c in spec.commands:
            inv = build(spec, c, demo[c["id"]])
            assert not inv.get("notes"), (c["id"], inv["notes"])
            assert inv["argv"][1] == EXPECTED[c["id"]], c["id"]
            seen.add(c["id"])
    assert seen == set(EXPECTED), set(EXPECTED) - seen


def test_UI只是觸發器_argv一律指向scripts(both):
    """⛔ 平台不得自己重寫「建目錄、寫骨架、註冊」——
    `new_product.py` 存在的理由正是「不要手動建，漏一步就不會被 lint 檢查到」，
    平台自己做一遍就是最大規模的手動建。

    ⚠️ 拆檔之後這條要涵蓋**兩支**工具 —— 保證屬於「所有工作區命令」，不屬於某一支。"""
    for spec in both:
        for c in spec.commands:
            first = c["argv"][0]
            assert first.startswith("scripts/"), "%s.%s 沒有走 scripts/：%s" % (spec.id, c["id"], first)


def test_破壞性命令要有高危宣告與打字確認(setup_spec):
    for cid in ("reset", "export"):
        d = setup_spec.command(cid).get("danger") or {}
        assert d.get("level") == "high", cid
        assert d.get("require_typed_confirm") is True, cid
        assert d.get("confirm_text"), cid


def test_預設是安全的(setup_spec):
    """`reset --apply` 與 `export --dry-run` 的預設值決定「手滑會不會出事」。"""
    def default(cid, key):
        return next(f for f in setup_spec.command(cid)["params"]["fields"]
                    if f["key"] == key).get("default")
    assert default("reset", "apply") is False        # 預設 dry-run
    assert default("export", "out" if False else "dry_run") is True
    assert default("new_product", "dry_run") is True


def test_產品下拉要用權威id而非slug(setup_spec):
    """`lint_docs --product`／`gen_bug_index` 吃的是 `CRUX`／`七星`，不是 slug。"""
    f = next(f for f in setup_spec.command("reset")["params"]["fields"]
             if f["key"] == "product")
    assert f["options_from"]["source"] == "products"
    assert f["options_from"]["value"] == "product_id"


def test_低危_因為只碰本機(setup_spec):
    """純本機唯讀／寫本機檔案，不碰任何測試站。

    📝 `spec.live` 旗標已隨 Demo 模式一起移除（2026-08-23）——
       平台一律真的執行，沒有需要「覆蓋全域 demo」的東西了。
    """
    assert (setup_spec.danger or {}).get("level") == "low"


# ─────────────────────────────── 通用 options_from

def test_通用options來源_排除偽產品並可取權威id(monkeypatch):
    """★ 第②層擴充：`options_from: {source: products}` 所有工具共用，
    不必再逐工具寫特例。兩件事要對：**偽產品排除**、**value 可指定取權威 id**。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from web_ui.api import registry_api as RA
    import core.registry as R
    import flask

    def field(key, value=None):
        of = {"source": "products"}
        if value:
            of["value"] = value
        return {"key": key, "type": "select", "label": key, "options_from": of}

    fake = R.Registry(
        products=[{"id": "alpha", "product_id": "甲產品", "label": "甲"},
                  {"id": "common", "label": "共通", "virtual": True}],
        tools={"setup": R.ToolSpec(raw={
            "id": "setup", "scope": "workspace",
            "commands": [{"id": "c", "label": "C", "mode": "sync", "params": {
                "fields": [field("product", "product_id"), field("slug")]}}]},
            path="setup.tool.json")})
    monkeypatch.setattr(RA, "get_registry", lambda: fake)   # ⚠️ 用 monkeypatch，別直接改模組

    app = flask.Flask(__name__)
    app.register_blueprint(RA.bp)
    with app.test_client() as c:
        assert c.get("/api/tools/setup/options/product").get_json()["options"] ==             [{"value": "甲產品", "label": "甲"}]          # 權威 id，且偽產品被排除
        assert c.get("/api/tools/setup/options/slug").get_json()["options"] ==             [{"value": "alpha", "label": "甲"}]            # 預設取 slug


# ─────────────────────────────── 匯出歸屬

def test_setup要被匯出而產品工具不被匯出():
    """★ 範本化：`setup` 是通用的（每個同事都要用它接產品），
    產品專屬的 tool.json 則不該夾帶給別人。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import export_template as E
    products = E.product_paths(E.ROOT)
    assert E.classify("tools/test_platform/registry/setup.tool.json", products) == "export", \
        "setup.tool.json 沒被匯出 → 同事的平台沒有初始化介面"
    assert E.classify("tools/test_platform/registry/crux_perf.tool.json", products) == "never"


# ═══════════════ 本輪補齊的計畫缺口（2026-08-23）═══════════════

class TestSpecVersion:
    """H-4d／R2-2：registry 讀 `spec_version` 並給升級提示。

    ⚠️ 沒有這一層時的失效方式最難查：`validate_spec` 報一句「缺必要欄位 X」，
    而**那支工具直接從 `#/tools` 與儀表板消失** —— 錯誤只出現在 `#/registry`
    這個平常不會去看的頁面，於是同事的感覺是「我的工具不見了」。
    """

    def test_比平台新的spec要擋下來並說清楚(self):
        _p()
        from core.registry import spec_version_note, SPEC_VERSION
        n = spec_version_note({"spec_version": SPEC_VERSION + 1})
        assert n and n["level"] == "error"
        assert "更新平台" in n["message"] or "較新" in n["message"]

    def test_比平台舊的spec只警告不擋(self):
        _p()
        from core.registry import spec_version_note, SPEC_VERSION
        n = spec_version_note({"spec_version": max(0, SPEC_VERSION - 1)})
        if SPEC_VERSION > 0:
            assert n and n["level"] == "warn", "舊版不該直接擋掉（仍可用）"

    def test_同版本不吵(self):
        _p()
        from core.registry import spec_version_note, SPEC_VERSION
        assert spec_version_note({"spec_version": SPEC_VERSION}) is None
        assert spec_version_note({}) is None or SPEC_VERSION != 1

    def test_非整數要擋(self):
        from core.registry import spec_version_note
        n = spec_version_note({"spec_version": "abc"})
        assert n and n["level"] == "error"

    def test_現有工具全部相容(self):
        _p()
        from core.registry import load_registry
        r = load_registry(force=True)
        assert not r.errors, r.errors
        assert not r.notes, "現有工具不該有升級提示：%s" % r.notes

    def test_notes_有被端點送出去(self):
        """欄位加了卻沒有消費者 ＝ 白做（本專案反覆出現的模式）。"""
        _p()
        import inspect
        import web_ui.api.registry_api as m
        src = inspect.getsource(m.list_tools)
        assert "notes" in src


class TestGateNotice:
    """C-5／R2-4：站台佔用提示（只提示不硬擋）。"""

    def test_ui_tests_的run型命令有靜態提示(self):
        _p()
        from core.registry import load_registry
        from core.check_store import gate_status
        r = load_registry(force=True)
        s = r.tools["ui_tests"]
        run_cmds = [c for c in s.commands if (c.get("mode") or "run") == "run"]
        assert run_cmds, "ui_tests 沒有 run 型命令"
        for c in run_cmds:
            g = gate_status(s, c)
            assert g and g["state"] == "notice", "%s 沒有站台佔用提示" % c["id"]
            assert "踢" in g["message"], "提示沒講到互踢這件事"
            assert "netsub" in g["message"], "提示沒給子帳號分配慣例"

    def test_提示不含控制字元(self):
        """★ 迴歸：注入時用 heredoc，`scripts\run_...` 的 `\r` 被吃成 CR，
        顯示出來變成亂碼。JSON 裡的提示文字一律不該有控制字元。"""
        _p()
        from core.registry import load_registry
        r = load_registry(force=True)
        for s in r.tools.values():
            for c in s.commands:
                msg = (c.get("gate") or {}).get("notice") or ""
                bad = [ch for ch in msg if ord(ch) < 32]
                assert not bad, "%s/%s 的 notice 含控制字元 %r" % (s.id, c["id"], bad)

    def test_sync命令不需要這個提示(self):
        """sync 命令是秒級本機操作，不會佔站台。"""
        _p()
        from core.registry import load_registry
        r = load_registry(force=True)
        s = r.tools["ui_tests"]
        for c in s.commands:
            if c.get("mode") == "sync":
                assert "notice" not in (c.get("gate") or {})


class TestRunAnalysis:
    """C-3：run 收尾接上 `scripts/analyze_run.py` 的三分類。"""

    def test_不自己重寫分類規則(self):
        """⛔ 平台再寫一份的話兩邊遲早漂移，症狀是
        「終端機說環境問題、平台說真失敗」，沒有人知道該信哪個。"""
        _p()
        import inspect
        from core import run_analysis
        src = inspect.getsource(run_analysis)
        assert "import analyze_run" in src, "沒有 import 既有腳本"
        # 不該自己有 env/prereq 的判斷規則
        assert "ENV_RE" not in src and "PREREQ_RE" not in src, \
            "run_analysis 自己寫了分類規則 —— 規則只能有一份"

    def test_沒有allure結果時回None(self, tmp_path):
        _p()
        from core.run_analysis import classify_run
        assert classify_run(str(tmp_path)) is None

    def test_有結果但全過時回零(self, tmp_path):
        _p()
        from core.run_analysis import classify_run, summary_line
        d = tmp_path / "allure-results"
        d.mkdir()
        (d / "a-result.json").write_text(
            '{"name":"t","fullName":"m#t","status":"passed","start":1}', encoding="utf-8")
        r = classify_run(str(tmp_path))
        assert r["counts"] == {"real": 0, "prereq": 0, "env": 0}
        assert summary_line(r) == "沒有失敗"

    def test_失敗會被分類(self, tmp_path):
        import json as _json
        _p()
        from core.run_analysis import classify_run, summary_line
        d = tmp_path / "allure-results"
        d.mkdir()
        (d / "a-result.json").write_text(_json.dumps({
            "name": "壞掉的案例", "fullName": "m#t", "status": "failed", "start": 1,
            "statusDetails": {"message": "AssertionError: 1 != 2", "trace": ""}}),
            encoding="utf-8")
        r = classify_run(str(tmp_path))
        assert sum(r["counts"].values()) == 1
        assert r["items"][0]["kind_label"] in ("真失敗", "前置未備", "環境問題")
        assert summary_line(r)

    def test_PytestAdapter收尾會呼叫它(self):
        _p()
        import inspect
        from adapters.pytest_ import PytestAdapter
        src = inspect.getsource(PytestAdapter._finish)
        assert "classify_run" in src
        assert "analysis" in src

    def test_分類失敗不得讓run收尾爆掉(self):
        """分析是加值，不是必要 —— 它壞掉不該把整個 run 標成失敗。"""
        _p()
        import inspect
        from adapters.pytest_ import PytestAdapter
        src = inspect.getsource(PytestAdapter._finish)
        assert "except Exception" in src
