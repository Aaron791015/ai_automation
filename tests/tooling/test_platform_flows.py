# -*- coding: utf-8 -*-
"""測試平台四條動線的回歸測試（`tools/test_platform/`）。

用途：鎖住 2026-08-21 這批動線改造裡「改壞了不會當場報錯、但會安靜失效」的那幾處：
    · 終態的 progress 標籤（改壞 → 畫面顯示「完成」卻寫著「產生 Allure 報告」）
    · Demo 的參數縮放（改壞 → 填什麼參數都跑出同一組數字，Demo 一眼穿幫）
    · Bug 草稿的去重與既有單比對（改壞 → 重複開單，而 ID 永不回收）
    · 生成器不得拿「生成出來的骨架」當範本（改壞 → 回饋迴路，產出一代不如一代）
    · `/api/doc` 的路徑白名單（改壞 → 讀得到 repo 任意檔案）
前置條件：
    · ⚠️ **匯入一律延後到函式裡**，理由與 `test_argv_build.py` 檔頭同 ——
      `tools/test_platform/` 的頂層 `core` 套件會在收集階段蓋掉
      `tools/wbot_Performance/core`，害 `tests/wbot/perf/` 全部收集失敗。
    · 全部在 tmp_path 或純函式上跑，不啟動伺服器、不寫任何真實產物。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod(name):
    """延後匯入平台模組（理由見檔頭）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import importlib
    return importlib.import_module(name)


# ---------------------------------------------------------------- 終態標籤
def test_進終態時自動補上完成標籤(tmp_path, monkeypatch):
    """三條終止路徑都沒帶 progress，而 progress 走淺合併 —— 舊 label 會原封不動留著"""
    rs = _mod("core.run_store")
    monkeypatch.setattr(rs, "RUNS_DIR", str(tmp_path))
    rid = "20260821_000000_x"
    rs.init_run(rid, {"tool_id": "x"})
    rs.update_status(rid, phase="running", progress={"percent": 62, "label": "產生 Allure 報告"})
    rs.update_status(rid, phase="completed")          # ← 刻意不帶 progress
    st = rs.read_status(rid)
    assert st["progress"] == {"percent": 100, "label": "完成"}


def test_本次有帶progress時不覆蓋(tmp_path, monkeypatch):
    """補寫只在「首次進終態且本次沒帶 progress」這個窄條件作用，正常回報不受影響"""
    rs = _mod("core.run_store")
    monkeypatch.setattr(rs, "RUNS_DIR", str(tmp_path))
    rid = "20260821_000001_x"
    rs.init_run(rid, {"tool_id": "x"})
    rs.update_status(rid, phase="stopped", progress={"percent": 41, "label": "中途停止於第 3 期"})
    assert rs.read_status(rid)["progress"]["label"] == "中途停止於第 3 期"


@pytest.mark.parametrize("phase,label", [("completed", "完成"), ("stopped", "已停止"), ("failed", "失敗")])
def test_三種終態各自的標籤(tmp_path, monkeypatch, phase, label):
    rs = _mod("core.run_store")
    monkeypatch.setattr(rs, "RUNS_DIR", str(tmp_path))
    rid = f"20260821_0000_{phase}"
    rs.init_run(rid, {"tool_id": "x"})
    rs.update_status(rid, phase="running", progress={"percent": 5, "label": "下注中"})
    rs.update_status(rid, phase=phase)
    assert rs.read_status(rid)["progress"]["label"] == label


def test_去重鍵會抹掉期號與時間戳():
    """同一個缺陷每次跑訊息都帶不同期號，不抹掉就會被當成新問題、重複開單"""
    bd = _mod("core.bug_draft")
    a = bd.signature("t.py::x", "AssertionError: 期號 2026082199 對不上（2026-08-21 10:00:00）")
    b = bd.signature("t.py::x", "AssertionError: 期號 2026082201 對不上（2026-08-21 11:30:00）")
    assert a == b
    assert a != bd.signature("t.py::y", "AssertionError: 期號 2026082199 對不上")


def test_nodeid比對必須精確不可用子字串():
    """`::test_a` 是 `::test_abc` 的前綴 —— 子字串比對會比中不相干的單"""
    bd = _mod("core.bug_draft")
    ids = bd._regression_nodeids("tests/crux/backend/test_x.py::test_abc[chromium]")
    assert "tests/crux/backend/test_x.py::test_abc" in ids
    assert "tests/crux/backend/test_x.py::test_a" not in ids


def test_命中已結案的單要標成回歸():
    """一條標成 fixed 的缺陷又失敗 ＝ 回歸，比新缺陷更緊急，不能被「已結案」濾掉"""
    bd = _mod("core.bug_draft")
    bugs = [{"id": "CRUX-040", "title": "占成合计", "product_label": "CRUX",
             "status": "fixed", "status_label": "✅ 已修復", "regression": "", "jira_keys": []}]
    hit = bd._match_existing("tests/crux/backend/test_x.py::t", "…（本地 CRUX-040）", "CRUX", bugs)
    assert hit["id"] == "CRUX-040" and hit["regressed"] is True


def test_命中仍開著的單不標回歸():
    bd = _mod("core.bug_draft")
    bugs = [{"id": "CRUX-031", "title": "x", "product_label": "CRUX",
             "status": "open", "status_label": "開啟", "regression": "", "jira_keys": []}]
    hit = bd._match_existing("t.py::t", "…（CRUX-031）", "CRUX", bugs)
    assert hit["id"] == "CRUX-031" and hit["regressed"] is False


def test_產品由nodeid前綴推導():
    """★ 依**實際的產品定義**驗，不寫死原型的產品名。

    ⚠️ 這條原本寫死 crux／wbot／qixing —— 而乾淨匯出的範本
    `config/products.json` 是空的，同事還沒接產品就跑 pytest 會看到紅燈，
    **範本的第一印象就是「這東西是壞的」**（2026-08-23 範本端到端驗收）。
    """
    bd = _mod("core.bug_draft")
    reg = _mod("core.registry")
    products = [p for p in reg.get_registry().products if not p.get("virtual")]
    if not products:
        import pytest as _pt
        _pt.skip("這個工作區還沒接任何產品（乾淨範本的正常狀態）")
    for p in products:
        prefix = ((p.get("knowledge") or {}).get("tests_prefix")
                  or "tests/%s/" % p["id"]).rstrip("/") + "/"
        want = p.get("product_id") or p["id"]
        assert bd.bug_product(prefix + "test_x.py::t") == want
    # 對不到任何前綴時**不可以隨便挑一個產品** —— 那個值會決定燒掉誰的 Bug 號
    got = bd.bug_product("tools/somewhere/test_x.py::t")
    assert got == "" or len(products) == 1


def test_嚴重度用中文與既有單一致():
    """gen_bug_index.py 依 severity 分組，寫成 medium 會多出一個假分類"""
    bd = _mod("core.bug_draft")
    assert bd._guess_severity("AssertionError: 期望 1，實際 2") == "中"
    assert bd._guess_severity("TimeoutError: connection refused") == "高"


# ---------------------------------------------------------------- 生成器
def test_生成的骨架不可以再當範本():
    """否則第二次抄第一次、第三次抄第二次 —— 抄到的是「待補判準」而不是驗證過的結構"""
    gen = _mod("generators.rulebased").RuleBasedGenerator()
    existing = [
        {"nodeid": "tools/test_platform/demo/generated_tests/crux/test_a.py::t_占成合计",
         "product": "crux", "kind": "generated", "title": "占成合计 欄位"},
        {"nodeid": "tests/crux/backend/test_b.py::t_占成合计", "product": "crux",
         "kind": "e2e", "title": "占成合计 欄位"},
    ]
    cases = gen.propose_cases("- 分类账會員層不應顯示占成合计欄位", {"product": "crux", "existing_cases": existing, "pom": []})
    assert cases[0]["template_from"]["nodeid"].startswith("tests/")


def test_標題行不會變成一條案例():
    gen = _mod("generators.rulebased").RuleBasedGenerator()
    req = "賠率變動設置需求\n- 起始日期不應早於 2025-01-01\n- 批量新增應可設為否"
    cases = gen.propose_cases(req, {"product": "crux", "existing_cases": [], "pom": []})
    assert len(cases) == 2
    assert all("需求" not in c["title"] for c in cases)


def test_中文以n_gram比對才找得到POM方法():
    """POM 的 docstring 寫「批量新增」，需求寫「批量新增時」—— 不切 n-gram 就比不中"""
    gen = _mod("generators.rulebased").RuleBasedGenerator()
    pom = [{"cls": "OddsChangePage", "method": "batch_create", "args": [], "doc": "批量新增一個套餐。",
            "module": "crux_qa.pages.backend.odds_change_page", "path": "x.py"}]
    cases = gen.propose_cases("- 批量新增時應可設為否", {"product": "crux", "existing_cases": [], "pom": pom})
    assert cases[0]["pom_hints"] and cases[0]["pom_hints"][0]["method"] == "batch_create"


def test_寫入型動作標write_action():
    gen = _mod("generators.rulebased").RuleBasedGenerator()
    cases = gen.propose_cases("- 新增一筆賠率變動設定\n- 查詢賠率變動列表",
                              {"product": "crux", "existing_cases": [], "pom": []})
    assert cases[0]["markers"] == ["write_action"]
    assert cases[1]["markers"] == ["smoke"]


def test_沒有POM方法時產出skip骨架而非壞掉的碼():
    gen = _mod("generators.rulebased").RuleBasedGenerator()
    c = gen.propose_cases("- 全新玩法的某某規則應成立", {"product": "crux", "existing_cases": [], "pom": []})[0]
    code = gen.write_code(c, {"product": "crux"})
    assert "pytest.skip" in code and c["confidence"] == "low"


def test_產碼的參數是佔位常數不是未定義變數():
    """直接寫變數名會是 NameError，那要跑起來才炸；佔位字串一眼看得到"""
    gen = _mod("generators.rulebased").RuleBasedGenerator()
    pom = [{"cls": "P", "method": "m", "args": ["account", "kind"], "doc": "占成合计",
            "module": "crux_qa.pages.p", "path": "x.py"}]
    c = gen.propose_cases("- 占成合计欄位不應顯示", {"product": "crux", "existing_cases": [], "pom": pom})[0]
    code = gen.write_code(c, {"product": "crux"})
    assert 'po.m("⚠️account", "⚠️kind")' in code


# ---------------------------------------------------------------- POM 索引
def test_pom的import路徑不含tools前綴():
    """pyproject 的 pythonpath = ["tools", "."]，多一層 tools. 會 ImportError"""
    pi = _mod("core.pom_index")
    idx = pi.build_pom_index()
    for rows in (pi.flat_methods("crux", idx), pi.flat_methods("wbot", idx)):
        for r in rows[:20]:
            assert not r["module"].startswith("tools."), r["module"]


def test_pom只收公開方法():
    pi = _mod("core.pom_index")
    for r in pi.flat_methods("crux"):
        assert not r["method"].startswith("_")


# ---------------------------------------------------------------- /api/doc 白名單
@pytest.mark.parametrize("bad", [
    "../../../etc/passwd", "CLAUDE.md", "docs/../CLAUDE.md",
    "docs/INDEX.md/../../CLAUDE.md", "/etc/passwd", "docs/INDEX.txt",
])
def test_文件端點擋掉白名單外的路徑(bad):
    """這支端點開了讀檔的口，白名單破了就等於能讀 repo 任意檔案"""
    api = _mod("web_ui.api.docs_api")
    assert api.resolve_doc(bad) is None


def test_文件端點放行docs底下的md():
    api = _mod("web_ui.api.docs_api")
    assert api.resolve_doc("docs/INDEX.md") is not None


# ─────────────────────────────── 執行對比：指標只能是純量

def test_對比的指標不收巢狀結構():
    """★ 迴歸：`summary` 裡的 dict／list（`analysis`、`allure`）若原樣進指標表，
    前端會印出一行「[object Object]」—— 而**畫面上真的就長那樣**，沒有任何錯誤。
    （2026-08-23 情境 B（用了一個月的同事）走查發現。）
    """
    import sys as _sys
    if PLATFORM not in _sys.path:
        _sys.path.insert(0, PLATFORM)
    from web_ui.api.runs import _metric_diff

    def side(summary):
        return {"status": {"summary": summary}}

    a = side({"passed": 2, "failed": 1, "analysis": {"real": 1},
              "allure": {"generated": True, "detail": "x"}, "analysis_line": "真失敗 1"})
    b = side({"passed": 0, "failed": 1, "analysis": {"real": 1},
              "allure": {"generated": True, "detail": "y"}, "analysis_line": "真失敗 1"})
    keys = [m["key"] for m in _metric_diff([a, b])]
    assert "analysis" not in keys and "allure" not in keys, (
        u"巢狀結構進了指標表，前端會顯示 [object Object]：%s" % keys)
    assert "passed" in keys and "analysis_line" in keys, (
        u"純量欄位不該被一起濾掉：%s" % keys)


def test_對比的指標值都是可直接顯示的():
    """把上一條推廣：任何一格都不可以是 dict／list。"""
    import sys as _sys
    if PLATFORM not in _sys.path:
        _sys.path.insert(0, PLATFORM)
    from web_ui.api.runs import _metric_diff
    rows = _metric_diff([
        {"status": {"summary": {"n": 1, "d": {"x": 1}, "l": [1, 2], "s": "ok"}}},
        {"status": {"summary": {"n": 2, "d": {"x": 2}, "l": [3], "s": "ok"}}},
    ])
    for m in rows:
        for side in ("a", "b"):
            assert not isinstance(m[side], (dict, list)), m


# ─────────────────────── 設定檔壞掉不可以靜默

def test_設定檔語法錯誤要出聲(tmp_path, monkeypatch, capsys):
    """★ 核心迴歸：`read_json(path, {})` 把「人打錯字」與「正在被寫入」混為一談。

    後者重試就好；前者重試三次仍失敗，然後**靜靜地當成檔案不存在**，
    平台用預設值照常啟動。`platform_config.local.json` 正是同事會手改的檔
    —— 改壞了他只會看到「我的設定沒作用」，查不到原因（2026-08-23 實際踩到）。
    """
    import importlib
    import io as _io
    import os as _os
    import sys as _sys
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    p = _os.path.join(root, "tools", "test_platform")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    from core import config as cfgmod

    d = tmp_path / "cfg"
    d.mkdir()
    _io.open(str(d / "platform_config.json"), "w", encoding="utf-8").write('{"port": 5300}')
    _io.open(str(d / "platform_config.local.json"), "w", encoding="utf-8").write('{"port": 9999,,}')
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", str(d))
    cfgmod.load_config.cache_clear()
    try:
        got = cfgmod.load_config()
        out = capsys.readouterr().out
        assert "platform_config.local.json" in out, u"設定檔壞掉卻沒有任何訊息"
        assert got.get("port") == 5300, u"壞掉那層應該被忽略，不該讓整份設定失效"
    finally:
        cfgmod.load_config.cache_clear()


# ── 草稿要有出口：捨棄（2026-08-23 UI 走查）────────────────────
#
# 先前只能「落單」或「寫檔」——判定不該開的草稿永遠躺在清單裡，
# 清單愈長愈髒，久了沒有人願意看。而那才是真正的損失。

def test_bug草稿可以捨棄而且不是真的刪掉(tmp_path, monkeypatch):
    import sys
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import bug_draft
    monkeypatch.setattr(bug_draft.paths, "SESSIONS_DIR", str(tmp_path))
    src = {"kind": "session", "id": "s1"}
    bug_draft.save(src, {"drafts": [{"signature": "abc", "title": "某現象"}]})
    assert len(bug_draft.read(src)["drafts"]) == 1

    assert bug_draft.discard(src, "abc", "這是探針檔，不是缺陷")
    kept = bug_draft.read(src)["drafts"][0]
    assert kept["dropped"] is True
    assert "探針" in kept["dropped_why"], u"理由沒留下 —— 下次同一個現象又要重走一遍判斷"
    # 不再出現在待辦清單，但檔案裡還在
    assert all(d.get("signature") != "abc"
               for d in bug_draft.read_all())


def test_捨棄不存在的草稿要回false(tmp_path, monkeypatch):
    import sys
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import bug_draft
    monkeypatch.setattr(bug_draft.paths, "SESSIONS_DIR", str(tmp_path))
    bug_draft.save({"kind": "session", "id": "s2"}, {"drafts": []})
    assert not bug_draft.discard({"kind": "session", "id": "s2"}, "nope", "x")
