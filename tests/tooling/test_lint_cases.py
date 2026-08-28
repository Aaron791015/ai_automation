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
