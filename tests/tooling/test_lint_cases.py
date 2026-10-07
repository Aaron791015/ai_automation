# -*- coding: utf-8 -*-
"""`scripts/lint_cases.py` 的守門測試 —— 案例必須寫得出「步驟」與「判準」。

為什麼需要這一支（2026-08-28）
    `ui-test` skill 先前只規範了「佐證」，**從沒要求過「步驟」**，
    於是實查 `tests/crux/backend/` 17 支案例只有 3 支寫了 `allure.step`
    —— 測試助手的「案例詳情」對其餘的一個步驟都顯示不出來，
    人要覆核只能讀原始碼。

    ⛔ 光把規則寫進 skill 擋不住（CLAUDE.md §6 記過同型教訓：
       「規則已寫在 skill 裡，但那是**格式說明**、不是**會被執行的檢查**」），
       所以規範與檢查一起上路，而這一支釘住檢查本身。

使用方式：`pytest tests/tooling/test_lint_cases.py -q`
前置條件：無（合成檔在 tmp_path；只有兩條「現況」測試會讀真的 repo）。
"""
import io
import json
import os

import pytest

import lint_cases as L


def _write(tmp_path, name, body):
    p = tmp_path / name
    io.open(str(p), "w", encoding="utf-8", newline="\n").write(body)
    return str(p)


def _codes(path, src=None):
    return sorted(c for _n, c in L.analyze(path, src))


def test_沒有step要抓出來(tmp_path):
    src = ("import allure\n"
           "def test_a(page):\n"
           "    page.click('x')\n"
           "    allure.attach('實際=1 期望=1', name='判準')\n"
           "    assert 1 == 1\n")
    assert _codes(_write(tmp_path, "test_a.py", src), src) == ["C1"]


def test_有assert沒有attach要抓出來(tmp_path):
    src = ("import allure\n"
           "def test_a(page):\n"
           "    with allure.step('登入後應進首頁'):\n"
           "        assert page.url\n")
    assert _codes(_write(tmp_path, "test_b.py", src), src) == ["C2"]


def test_兩個都寫了就沒事(tmp_path):
    src = ("import allure\n"
           "def test_a(page):\n"
           "    with allure.step('月报表下限應等於後端下限'):\n"
           "        allure.attach('實際=2025-01-01 期望=2025-01-01', name='判準')\n"
           "        assert True\n")
    assert _codes(_write(tmp_path, "test_c.py", src), src) == []


def test_step寫成裝飾器也算(tmp_path):
    """⚠️ `ast.get_source_segment` 從 `def` 那一行開始 —— 不含裝飾器。
    而 `@allure.step("…")` 是 allure 的正規寫法，漏掉會把寫得很好的案例判成沒寫。"""
    src = ("import allure\n"
           "@allure.step('登入後台')\n"
           "def test_a():\n"
           "    allure.attach('實際=1 期望=1', name='判準')\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_deco.py", src), src) == []


def test_收在helper裡的attach不算漏(tmp_path):
    """★ 把佐證收進 `_verify()` 是正當寫法 —— 判成漏寫會逼人把程式碼攤平。"""
    src = ("import allure\n"
           "def _verify(actual, expect):\n"
           "    allure.attach('實際=%s 期望=%s' % (actual, expect), name='判準')\n"
           "    assert actual == expect\n"
           "def test_a(page):\n"
           "    with allure.step('比對貨量'):\n"
           "        _verify(1, 1)\n")
    assert _codes(_write(tmp_path, "test_d.py", src), src) == []


def test_helper只追一層(tmp_path):
    """⚠️ 不無限追下去 —— 追太深會把「隔了三層才 attach」也算成有寫，
    那時報告上早就看不出這條案例的判準了。"""
    src = ("import allure\n"
           "def _deep(x):\n"
           "    allure.attach(str(x), name='判準')\n"
           "def _mid(x):\n"
           "    _deep(x)\n"
           "def test_a():\n"
           "    with allure.step('走三層'):\n"
           "        _mid(1)\n"
           "        assert 1\n")
    assert _codes(_write(tmp_path, "test_e.py", src), src) == ["C2"]


def test_類別裡的案例也要檢查(tmp_path):
    src = ("import allure\n"
           "class Test某功能:\n"
           "    def test_a(self):\n"
           "        assert 1\n")
    assert _codes(_write(tmp_path, "test_f.py", src), src) == ["C1", "C2"]


def test_語法壞掉不可以拋(tmp_path):
    """⛔ 檢查工具自己炸掉，會讓整批案例靜默地不被檢查。"""
    assert L.analyze(_write(tmp_path, "test_g.py", "def test_a(:\n"), "def test_a(:\n") == []


def test_不檢查tooling與perf():
    """`tests/tooling/` 是腳本的單元測試、`**/perf/` 是壓測工具的 —— 都不是 UI 案例。"""
    dirs = [os.path.basename(d) for d in L.product_dirs()]
    assert "tooling" not in dirs
    for base in L.product_dirs():
        assert not [f for f in L.case_files(base) if "/perf/" in L._rel(f)]


# ── 現況：這兩條是**真的在守規範**的部分 ────────────────────────

def test_現有案例不可以有新的違規():
    """★ 這一條就是規範本身：既有的在豁免名單裡，**新寫的一律要合格**。"""
    files = [f for b in L.product_dirs() for f in L.case_files(b)]
    if not files:
        pytest.skip(u"這個工作區還沒有 UI 案例（剛匯出的範本就是這樣）")
    todo, waived = L.scan()
    # ⚠️ 先確認掃描器**真的把每個檔都看過** —— 少了這行，把 scan() 弄壞成「回空」
    #    也會讓這一條通過（實測突變：掃描器回空竟然是綠的）。
    #    ⛔ 不可以改成 `assert waived` —— 等 104 條全部補完，豁免名單本來就會是空的，
    #       那時這一條會**因為規範達成而變紅**（`rule-frozen-by-its-own-guard-test`）。
    assert len(todo) + len(waived) == sum(len(L.analyze(f)) for f in files),         u"掃描器漏看了案例"
    assert not todo, (
        u"有 %d 項沒寫步驟／判準 —— 做法見 .claude/skills/ui-test/SKILL.md：\n%s"
        % (len(todo), "\n".join("  [%s] %s" % (c, n) for n, c in sorted(todo)[:20])))


def test_豁免名單只減不增():
    """⛔ 名單變長 ＝ 有人把新案例塞進豁免，等於把規範關掉。

    ⚠️ 這裡刻意釘「**不超過上路當天的數量**」而不是釘等於 ——
       補好一條就該刪一條，名單只能變短（`rule-frozen-by-its-own-guard-test` 的教訓：
       守門測試要釘性質，不要釘字面）。
    """
    # ⚠️ 103 是**案例數**（nodeid），不是違規項數（104 —— 有一條同時缺 step 與 attach）。
    #    釘成 104 等於還留了一格成長空間，那正是這條要擋的事。
    上路當天 = 103          # 2026-08-28 規範上路時的既有豁免案例數
    #    （範本沒有產品案例 → 名單是 0，同樣通過，不需要特例）
    n = sum(len(L.load_baseline(b)) for b in L.product_dirs())
    assert n <= 上路當天, u"豁免名單變長了（%d > %d）—— 新案例不可以進名單" % (n, 上路當天)


def test_名單裡不可以留已經不存在的檔():
    """⚠️ 只擋「檔案不存在」；「已經合格了」是提醒不是錯 ——
    把「你改好了一條案例」變成紅燈，會讓人不想改。"""
    死的 = [x for x in L.stale_baseline() if x[2] == u"檔案不存在"]
    assert not 死的, u"名單指向不存在的檔，該刪了：%s" % 死的


def test_補好的案例要被提醒從名單刪掉(tmp_path, monkeypatch):
    """★ 沒有這一項，名單只會愈留愈舊 ——「只減不增」實際上變成「只是不增」。"""
    prod = tmp_path / "假產品"
    prod.mkdir()
    案例 = str(prod / "test_x.py")
    io.open(案例, "w", encoding="utf-8", newline="\n").write(
        "import allure\n"
        "def test_ok():\n"
        "    with allure.step('比對'):\n"
        "        allure.attach('實際=1 期望=1', name='判準')\n"
        "        assert True\n")
    io.open(str(prod / L.BASELINE_NAME), "w", encoding="utf-8", newline="\n").write(
        json.dumps({"exempt": ["%s::test_ok" % L._rel(案例)]}))
    monkeypatch.setattr(L, "TESTS", str(tmp_path))
    assert [x[2] for x in L.stale_baseline()] == ["已經合格了"]


def test_不提供把新案例加進名單的路():
    """⛔ 有 `--init-baseline` 是為了一次性建檔；**已存在就必須拒絕覆寫**，
    否則任何人都能一鍵把當下的違規全部洗成豁免。"""
    有名單 = [b for b in L.product_dirs() if os.path.exists(L.baseline_path(b))]
    if not 有名單:
        pytest.skip(u"這個工作區沒有豁免名單（剛匯出的範本就是這樣）")
    assert L._init_baseline(有名單[0]) is False, u"竟然覆寫了既有的豁免名單"


def test_豁免名單放在產品目錄裡才不會跟著範本走():
    """名單記的是**這個 repo 的舊帳**，同事的案例一條都不該豁免。

    放在 `tests/<產品>/` 底下，`export_template` 的產品路徑排除規則就會自然擋掉它；
    ⛔ 放進 `scripts/` 或 `config/` 就會被當成通用檔匯出去。
    """
    assert L.BASELINE_NAME not in os.listdir(os.path.join(L.ROOT, "scripts"))
    for base in L.product_dirs():
        p = L.baseline_path(base)
        if os.path.exists(p):
            assert L._rel(p).startswith("tests/"), L._rel(p)
            assert json.load(io.open(p, encoding="utf-8")).get("exempt") is not None


# ── T2（2026-10-07）：`--product` 解析不到不可以回「0 項」────────────────

def _workspace(tmp_path, monkeypatch, products=None, tests=("xzh",), cases=None):
    """在 tmp_path 造一個假工作區：tests/<目錄>、tools/、config/products.json，並把 lint_cases 指過去。

    products：products.json 的 `products` 清單（None＝登記「新綜合」，tests_dir 是 xzh）；
    cases：{目錄名: 案例檔原始碼}，沒給的目錄放一個合格的案例檔。
    """
    if products is None:
        products = [{"id": "新綜合", "label": "新綜合", "docs_dir": "新綜合", "aliases": ["xzh"],
                     "tests_dir": "xzh", "skill": "xzh"}]
    (tmp_path / "config").mkdir()
    io.open(str(tmp_path / "config" / "products.json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps({"products": products}, ensure_ascii=False))
    (tmp_path / "tools").mkdir()
    (tmp_path / "tests").mkdir(exist_ok=True)
    good = ("import allure\n"
            "def test_ok():\n"
            "    with allure.step('比對'):\n"
            "        allure.attach('實際=1 期望=1', name='判準')\n"
            "        assert True\n")
    for name in tests:
        d = tmp_path / "tests" / name
        d.mkdir(parents=True)
        io.open(str(d / "test_a.py"), "w", encoding="utf-8", newline="\n").write(
            (cases or {}).get(name, good))
    monkeypatch.setattr(L, "ROOT", str(tmp_path))
    monkeypatch.setattr(L, "TESTS", str(tmp_path / "tests"))
    monkeypatch.setattr(L, "TOOLS", str(tmp_path / "tools"))
    monkeypatch.setattr(L, "PRODUCTS_JSON", str(tmp_path / "config" / "products.json"))
    return tmp_path


def test_product不存在要報錯且非零不可以回0項(tmp_path, monkeypatch, capsys):
    """★ T2 本身：`--product 新綜合` 先前被當成 `tests/新綜合` 目錄名，目錄不存在就
    「待修 0 項」exit 0 —— 沒檢查跟檢查過沒問題，對看輸出的人是同一個畫面。"""
    _workspace(tmp_path, monkeypatch)
    code = L.main(["--product", "不存在的產品"])
    out, err = capsys.readouterr()
    assert code != 0, u"解析不到的產品竟然回 0（漏檢）"
    assert u"不存在的產品" in err
    assert u"待修 0 項" not in out, u"解析不到卻印出「待修 0 項」，等於告訴人檢查通過"


def test_product中文名與目錄名解析到同一目錄(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    want = str(tmp_path / "tests" / "xzh")
    for name in (u"新綜合", "xzh", "XZH", u" 新綜合 "):      # id／label／docs_dir、別名、tests_dir、大小寫、前後空白
        assert L.resolve_product(name) == want, name


def test_product各種稱呼都能解析(tmp_path, monkeypatch):
    """id／label／docs_dir／tests_dir／skill／別名都算 —— 同事不必記哪一個才是『對的名字』。"""
    _workspace(tmp_path, monkeypatch, tests=("quote",),
               products=[{"id": u"報價系統", "label": u"報價", "docs_dir": u"報價文件",
                          "aliases": ["qs"], "tests_dir": "quote", "skill": "quoteskill"}])
    want = str(tmp_path / "tests" / "quote")
    for name in (u"報價系統", u"報價", u"報價文件", "qs", "quote", "quoteskill"):
        assert L.resolve_product(name) == want, name


def test_product沒填tests_dir就退回skill(tmp_path, monkeypatch):
    """跟 `export_template` 同一個取法：`tests_dir` 沒有就用 `skill`。"""
    _workspace(tmp_path, monkeypatch, tests=("abc",),
               products=[{"id": u"某產品", "docs_dir": u"某產品", "skill": "abc"}])
    assert L.resolve_product(u"某產品") == str(tmp_path / "tests" / "abc")


def test_product兩種寫法掃出一樣的結果而且不是空的(tmp_path, monkeypatch):
    bad = ("import allure\n"
           "def test_bad():\n"
           "    assert 1\n")
    _workspace(tmp_path, monkeypatch, cases={"xzh": bad})
    by_name, _w1 = L.scan(u"新綜合")
    by_dir, _w2 = L.scan("xzh")
    assert sorted(by_name) == sorted(by_dir) != [], u"兩種寫法應該掃到同樣的違規，而且不是漏檢的空清單"
    assert sorted(c for _n, c in by_name) == ["C1", "C2"]


def test_product已登記但測試目錄不存在要報錯(tmp_path, monkeypatch, capsys):
    _workspace(tmp_path, monkeypatch, tests=("other",),
               products=[{"id": u"新產品", "docs_dir": u"新產品", "aliases": ["np"],
                          "tests_dir": "ghost", "skill": "ghost"}])
    with pytest.raises(L.ProductError) as e:
        L.resolve_product(u"新產品")
    assert u"tests/ghost" in str(e.value) and u"不存在" in str(e.value)
    assert L.main(["--product", "np"]) == 2
    assert u"待修 0 項" not in capsys.readouterr().out


def test_product沒登記但tests底下有同名目錄就照舊可用(tmp_path, monkeypatch):
    """舊行為：參數直接是 `tests/<目錄名>`（工作區的 products.json 空了或讀不到時也要能用）。"""
    _workspace(tmp_path, monkeypatch, products=[], tests=("legacy",))
    assert L.resolve_product("Legacy") == str(tmp_path / "tests" / "legacy")
    monkeypatch.setattr(L, "PRODUCTS_JSON", str(tmp_path / "不存在.json"))      # 讀不到登記檔
    assert L.resolve_product("legacy") == str(tmp_path / "tests" / "legacy")


def test_product_tooling與perf不是案例目錄(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch, tests=("xzh", "tooling"))
    for name in ("tooling", "perf"):
        with pytest.raises(L.ProductError) as e:
            L.resolve_product(name)
        assert u"不是案例目錄" in str(e.value)


def test_product空字串也要報錯(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    for name in ("", "   ", None):
        with pytest.raises(L.ProductError):
            L.resolve_product(name)


def test_product登記的目錄存在但沒有案例檔不可以假裝通過(tmp_path, monkeypatch, capsys):
    """目錄在、但裡面沒有 `test_*.py`（剛接進來的新產品）：不是錯誤，但摘要要說清楚「沒有東西可檢查」。"""
    _workspace(tmp_path, monkeypatch)
    os.remove(str(tmp_path / "tests" / "xzh" / "test_a.py"))
    assert L.main(["--product", "新綜合"]) == 0
    out = capsys.readouterr().out
    assert u"檢查範圍：0 個案例檔" in out and u"沒有東西可檢查" in out


def test_摘要要印出檢查範圍(tmp_path, monkeypatch, capsys):
    """★ 「待修 0 項」旁邊要有分母 —— 看到 `1 個案例檔、1 條案例` 才知道真的有檢查到東西。"""
    _workspace(tmp_path, monkeypatch)
    assert L.main(["--product", "xzh"]) == 0
    assert u"檢查範圍：1 個案例檔、1 條案例（xzh）" in capsys.readouterr().out


def test_init_baseline也走同一套產品解析(tmp_path, monkeypatch, capsys):
    """⛔ 打錯產品名不可以靜默地「什麼都沒建」還回 0。"""
    _workspace(tmp_path, monkeypatch)
    assert L.main(["--init-baseline", "--product", "不存在的產品"]) == 2
    assert not os.path.exists(L.baseline_path(str(tmp_path / "tests" / "xzh")))


def test_真實倉庫的新綜合與xzh解析到同一個目錄():
    """T2 驗收：`--product 新綜合` 與 `--product xzh` 必須是同一個目錄（先前前者漏檢）。"""
    if not any(u"新綜合" in L._product_names(p) for p in L._registered_products()):
        pytest.skip(u"這個工作區沒有登記「新綜合」（剛匯出的範本就是這樣）")
    assert L.resolve_product(u"新綜合") == L.resolve_product("xzh")
    assert os.path.isdir(L.resolve_product(u"新綜合"))


# ── T3（2026-10-07）：helper 追到 `tools/` 底下的專案模組 ────────────────

def _tools(tmp_path, monkeypatch, files):
    """在 tmp_path/tools 造模組：files＝{'mypkg/shared.py': 原始碼}；自動補 `__init__.py`。"""
    monkeypatch.setattr(L, "TOOLS", str(tmp_path / "tools"))
    for rel, body in files.items():
        p = tmp_path / "tools" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        io.open(str(p), "w", encoding="utf-8", newline="\n").write(body)
        init = p.parent / "__init__.py"
        if not init.exists():
            io.open(str(init), "w", encoding="utf-8", newline="\n").write("")


SHARED_OK = ("import allure\n"
             "def run(x):\n"
             "    with allure.step('共用模組：做一件事'):\n"
             "        allure.attach('實際=%s 期望=%s' % (x, x), name='判準')\n")


def test_共用模組裡的step與attach不算漏_各種import寫法(tmp_path, monkeypatch):
    """★ T3 本身：`allure.step`／`attach` 寫在 `tools/` 的共用模組裡是正當寫法（連肖賠率差案例就是），
    不可以判成沒寫 —— 實跑的 allure 報告看得到，只有這個靜態檢查看不到。"""
    _tools(tmp_path, monkeypatch, {"mypkg/shared.py": SHARED_OK})
    heads = {
        "from_import": ("from mypkg.shared import run\n", "run(1)"),
        "as": ("from mypkg.shared import run as go\n", "go(1)"),
        "import_dotted": ("import mypkg.shared\n", "mypkg.shared.run(1)"),
        "import_as": ("import mypkg.shared as sh\n", "sh.run(1)"),
        "from_pkg_import_module": ("from mypkg import shared\n", "shared.run(1)"),
    }
    for label, (imp, call) in heads.items():
        src = "import allure\n%sdef test_a():\n    %s\n    assert True\n" % (imp, call)
        assert _codes(_write(tmp_path, "test_%s.py" % label, src), src) == [], label


def test_函式內的import也算(tmp_path, monkeypatch):
    """連肖案例都是在函式裡才 `from xzh_qa.x import run_chain_winner`（登入前 skip 的需要）。"""
    _tools(tmp_path, monkeypatch, {"mypkg/shared.py": SHARED_OK})
    src = ("import allure\n"
           "def test_a():\n"
           "    from mypkg.shared import run\n"
           "    run(1)\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_local_import.py", src), src) == []


def test_案例先呼叫同檔helper再呼叫共用模組也算(tmp_path, monkeypatch):
    """★ 真實的連肖案例結構：案例 → `_run_chain_variant()`（同檔）→ `run_chain_winner()`（共用模組）。"""
    _tools(tmp_path, monkeypatch, {"mypkg/shared.py": SHARED_OK})
    src = ("import allure\n"
           "def _variant():\n"
           "    from mypkg.shared import run\n"
           "    run(1)\n"
           "def test_a():\n"
           "    _variant()\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_two_hop.py", src), src) == []


def test_共用模組裡沒寫step就仍然抓出來(tmp_path, monkeypatch):
    """⛔ 追進共用模組不是『只要有 import 就放行』—— 模組裡也沒有，一樣是 C1／C2。"""
    _tools(tmp_path, monkeypatch, {"mypkg/bare.py": "def run(x):\n    return x\n"})
    src = ("import allure\n"
           "from mypkg.bare import run\n"
           "def test_a():\n"
           "    run(1)\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_bare.py", src), src) == ["C1", "C2"]


def test_共用模組只有step沒有attach就只報C2(tmp_path, monkeypatch):
    _tools(tmp_path, monkeypatch, {"mypkg/steponly.py": (
        "import allure\n"
        "def run():\n"
        "    with allure.step('做事'):\n"
        "        pass\n")})
    src = ("from mypkg.steponly import run\n"
           "def test_a():\n"
           "    run()\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_steponly.py", src), src) == ["C2"]


def test_共用模組裡再收進同模組的helper追一層(tmp_path, monkeypatch):
    """進了共用模組之後，函式本體加上它在**同模組**呼叫的 helper 一層；再深就不追了。"""
    _tools(tmp_path, monkeypatch, {"mypkg/layers.py": (
        "import allure\n"
        "def _deep():\n"
        "    allure.attach('x', name='判準')\n"
        "def _mid():\n"
        "    _deep()\n"
        "def _one():\n"
        "    allure.attach('x', name='判準')\n"
        "def run_one():\n"
        "    with allure.step('一層'):\n"
        "        _one()\n"
        "def run_two():\n"
        "    with allure.step('兩層'):\n"
        "        _mid()\n")})
    one = ("from mypkg.layers import run_one\n"
           "def test_a():\n"
           "    run_one()\n"
           "    assert True\n")
    two = ("from mypkg.layers import run_two\n"
           "def test_b():\n"
           "    run_two()\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_one.py", one), one) == []
    assert _codes(_write(tmp_path, "test_two.py", two), two) == ["C2"], u"模組裡隔了兩層才 attach 不該算有寫"


def test_共用模組再import別的共用模組不再往下追(tmp_path, monkeypatch):
    """⚠️ 模組跳模組離案例太遠：報告上看不出這條案例的步驟，不算。"""
    _tools(tmp_path, monkeypatch, {
        "mypkg/inner.py": SHARED_OK,
        "mypkg/outer.py": ("from mypkg.inner import run as inner_run\n"
                           "def run(x):\n"
                           "    inner_run(x)\n")})
    src = ("from mypkg.outer import run\n"
           "def test_a():\n"
           "    run(1)\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_hop.py", src), src) == ["C1", "C2"]


def test_只追tools底下的本機模組(tmp_path, monkeypatch):
    """標準庫、第三方套件、`tools/` 以外的檔案一律不追（就算同名且裡面寫了 allure.step）。"""
    _tools(tmp_path, monkeypatch, {"mypkg/__init__.py": ""})
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    io.open(str(outside / "thirdparty.py"), "w", encoding="utf-8").write(SHARED_OK)
    src = ("import os.path\n"
           "from os.path import join\n"
           "from elsewhere.thirdparty import run\n"
           "from allure_pytest import plugin\n"
           "def test_a():\n"
           "    join('a', 'b')\n"
           "    run(1)\n"
           "    plugin.x()\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_outside.py", src), src) == ["C1", "C2"]


def test_模組互相呼叫或自呼叫不會無限追(tmp_path, monkeypatch):
    """額度只減不增 —— 遞迴、互相呼叫都要能停（卡住等於整批檢查靜默不跑）。"""
    _tools(tmp_path, monkeypatch, {"mypkg/loop.py": (
        "def a():\n"
        "    b()\n"
        "    a()\n"
        "def b():\n"
        "    a()\n")})
    src = ("def _h():\n"
           "    _h()\n"
           "from mypkg.loop import a\n"
           "def test_x():\n"
           "    _h()\n"
           "    a()\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_loop.py", src), src) == ["C1", "C2"]


def test_同檔helper遮蔽同名的import(tmp_path, monkeypatch):
    """案例檔自己定義了同名函式，呼叫的就是那一個，不可以轉頭去追模組裡的同名函式。"""
    _tools(tmp_path, monkeypatch, {"mypkg/shared.py": SHARED_OK})
    src = ("from mypkg.shared import run\n"
           "def run(x):\n"
           "    return x\n"
           "def test_a():\n"
           "    run(1)\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_shadow.py", src), src) == ["C1", "C2"]


def test_共用模組語法壞掉不可以拋(tmp_path, monkeypatch):
    """⛔ 共用模組寫壞（或編碼讀不出來）不可以讓整批案例檢查炸掉 —— 當成沒追到就好。"""
    _tools(tmp_path, monkeypatch, {"mypkg/broken.py": "def run(:\n"})
    src = ("from mypkg.broken import run\n"
           "def test_a():\n"
           "    run()\n"
           "    assert True\n")
    assert _codes(_write(tmp_path, "test_broken.py", src), src) == ["C1", "C2"]


def test_共用模組改了之後要重新剖析(tmp_path, monkeypatch):
    """模組剖析有快取；檔案一改（補上 step）就必須讀到新版，不可以沿用舊結果。"""
    _tools(tmp_path, monkeypatch, {"mypkg/live.py": "def run():\n    return 1\n"})
    src = ("from mypkg.live import run\n"
           "def test_a():\n"
           "    run()\n"
           "    assert True\n")
    path = _write(tmp_path, "test_live.py", src)
    assert _codes(path, src) == ["C1", "C2"]
    _tools(tmp_path, monkeypatch, {"mypkg/live.py": (
        "import allure\n"
        "def run():\n"
        "    with allure.step('補上步驟'):\n"
        "        allure.attach('實際=1 期望=1', name='判準')\n"
        "    return 1\n")})
    assert _codes(path, src) == []


def test_連肖賠率差案例的步驟寫在共用模組裡不算漏():
    """T3 驗收（真實檔案）：B106、B112～B121 的 `allure.step` 在 `tools/xzh_qa/` 的共用模組裡，
    實跑的 allure 看得到，不可以再判 C1。"""
    path = os.path.join(L.ROOT, "tests", "xzh", "test_odds_gap_betting_regression.py")
    if not os.path.exists(path):
        pytest.skip(u"這個工作區沒有新綜合的賠率差案例（剛匯出的範本就是這樣）")
    assert L.analyze(path) == [], u"連肖案例又被判成沒寫步驟了：%s" % L.analyze(path)


def test_掃描一個四百KB的案例檔不可以慢到無法使用(tmp_path):
    """⚠️ 先前每取一次節點原文就把整份原始碼逐字元重切（`ast.get_source_segment`），
    400KB 的案例檔要掃 100 秒、整個 xzh 要好幾分鐘，等於沒人會跑它。
    這裡釘的是性質（案例數增加時不會爆成平方），上限抓得很鬆，只擋退回舊寫法。"""
    import time
    body = "".join(
        "def test_case_%d():\n"
        "    with allure.step('步驟 %d：讀取頁面並比對一個比較長的說明文字讓檔案夠大'):\n"
        "        value = %d\n"
        "        allure.attach('實際=%%s 期望=%%s' %% (value, value), name='判準')\n"
        "        assert value == %d\n\n" % (i, i, i, i) for i in range(1800))
    src = "import allure\n\n" + body
    assert len(src.encode("utf-8")) > 380 * 1024
    t = time.time()
    assert _codes(_write(tmp_path, "test_big.py", src), src) == []
    assert time.time() - t < 15, u"掃一個大案例檔花了 %.1f 秒，疑似退回逐次重切原始碼的寫法" % (time.time() - t)
