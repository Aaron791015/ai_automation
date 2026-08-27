# -*- coding: utf-8 -*-
"""草稿區塊的圍欄容錯（`core/draft_parse._blocks`）。

用途：2026-08-25 實跑撞到 —— session 交出三筆**格式完全正確**的草稿，
      平台一筆都沒接住，而且畫面上一個字都沒有。

      成因不是草稿寫錯，是它把**上一個**區塊的收尾圍欄與後文寫在同一行
      （`` ```登入成功。直接導到… ``）。那一行不算 CommonMark 的收尾，
      外層圍欄就一路吃下去，把後面的草稿區塊當成收尾用掉。

⛔ 這裡釘住的是**兩件事**，第二件比第一件重要：
   ① 圍欄壞掉時，仍然靠 `kind` 錨點把草稿撿回來
   ② **撿不回來就要報數**（`missed`）—— 產出可以解析失敗，不可以無聲消失

前置條件：無。
"""
import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def DP(monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(ROOT, "tools", "test_platform"))
    spec = importlib.util.spec_from_file_location(
        "draft_parse_ut", os.path.join(ROOT, "tools", "test_platform", "core", "draft_parse.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


F4 = "`" * 4
F3 = "`" * 3

GOOD = F4 + """
kind     handover
product  CRUX
section  data
title    刻意保留的測試資料
why      它就是那張單的重現環境
cells    賠率變動設置一筆 | 總監2 | 保留 | 本次
""" + F4


def test_圍欄正常時照常解析(DP):
    got = DP.parse(GOOD, "CRUX")
    assert len(got["docs"]) == 1 and got["missed"] == 0


def test_前面的圍欄壞掉也撿得回來(DP):
    """★ 事故重現：上一個區塊的收尾圍欄後面**接了文字**，配對整個錯位。"""
    broken = (F3 + "\n目標：補拍佐證\n" + F3 + "登入成功。直接導到設定頁。\n\n" + GOOD)
    got = DP.parse(broken, "CRUX")
    assert len(got["docs"]) == 1, "草稿被吃掉了 —— 這正是 2026-08-25 掉三筆的形狀"
    assert got["docs"][0]["section"] == "data"
    assert got["missed"] == 0


def test_連續三筆都撿得回來(DP):
    broken = F3 + "\nx\n" + F3 + "接在同一行的文字\n\n" + GOOD + "\n\n" + GOOD.replace(
        "刻意保留的測試資料", "第二筆").replace("section  data", "section  todo") + "\n\n" + GOOD.replace(
        "刻意保留的測試資料", "第三筆")
    got = DP.parse(broken, "CRUX")
    assert len(got["docs"]) == 3, [d.get("title") for d in got["docs"]]


def test_撿不回來時要報數(DP):
    """⛔ 最重要的一條：接不住可以，**不吭聲不行**。"""
    junk = "kind     handover\n（後面全是散文，沒有任何必要欄位）\n"
    got = DP.parse(junk, "CRUX")
    assert got["docs"] == [] and got["missed"] == 1


def test_空圍欄不會被當成草稿(DP):
    """圍欄配對錯位時會產生一堆 body 為空的區塊，那些不是草稿。"""
    got = DP.parse(F4 + "\n" + F4 + "\n" + F4 + "\n" + F4 + "\n", "CRUX")
    assert got["docs"] == [] and got["bugs"] == []


def test_散文裡提到kind不會誤判(DP):
    """⚠️ 誤抓比漏抓難查：正文寫「kind 這個欄位」不該被當成草稿的開頭。"""
    got = DP.parse("草稿的第一個鍵是 kind，例如 kind handover 這樣寫。\n", "CRUX")
    assert got["missed"] == 0 and got["docs"] == []


# ── 案例草稿的兩個靜默失真（2026-08-26）─────────────────────
CASE = F4 + """
kind          case
product       CRUX
title          玩法篩選選三码定位_列表應只回該玩法
surface       backend
preconditions 已登入總監後台，彩種切至排列三
steps         1. 進入 设置 > 赔率变动设置
              2. 點開篩選列「玩法」下拉
expected      只回 playTypeId=300 的資料
markers       smoke
pom_hints     OddsChangePage.filter_by_play_type
verified      yes
""" + F4


def _case(DP):
    got = DP.parse(CASE, "CRUX")
    assert len(got["cases"]) == 1, got
    return got["cases"][0]


def test_步驟要一行一列而不是逐字元(DP):
    """⛔ `generators/rulebased` 對 steps `enumerate()` —— 交字串進去會逐字元展開。

    2026-08-25 實跑產出 3285 行、80 KB，幾乎整檔都是
    「# 步驟 1：1／# 步驟 2：.／# 步驟 3：　」這種一個字一列的註解。
    """
    c = _case(DP)
    assert isinstance(c["steps"], list), u"還是字串 —— 產碼會逐字元展開"
    assert len(c["steps"]) == 2, c["steps"]
    assert c["steps"][0].startswith("進入"), u"自帶的編號沒拿掉"
    assert isinstance(c["preconditions"], list)


def test_pom提示不會被產品id擋掉(DP):
    """★ POM 索引的鍵是 slug（`crux`），草稿的 product 是權威 id（`CRUX`）。

    ⛔ 不轉的話 `flat_methods('CRUX')` 回 0 筆 → **每一個提示都被當成模型編的**濾掉
       → 產碼只能走 `pytest.skip("找不到對應的 Page Object 方法")`。
    ⚠️ 本工作區沒有 CRUX 這個產品時跳過（範本情境）。
    """
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "pom_ut", os.path.join(ROOT, "tools", "test_platform", "core", "pom_index.py"))
    m = _u.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
        has = any(x.get("cls") == "OddsChangePage" for x in (m.flat_methods("crux") or []))
    except Exception:                       # noqa: BLE001
        has = False
    if not has:
        pytest.skip("本工作區沒有 crux 的 OddsChangePage")
    c = _case(DP)
    assert c["pom_hints"], u"提示被濾光了 —— 產碼會退回 pytest.skip 骨架"
    assert c["pom_hints"][0]["method"] == "filter_by_play_type"


# ── session 自己交程式碼（2026-08-26）─────────────────────
CODE_CASE = F4 + """
kind          case
product       CRUX
title          玩法篩選只回該玩法
surface       backend
steps         1. 進入賠率變動設置
expected      只回 playTypeId=300
markers       smoke
verified      yes
code
      import pytest

      @pytest.mark.smoke
      def test_玩法篩選只回該玩法(backend_page):
          expected = 300
          actual = 300
          assert actual == expected
""" + F4


def test_鍵名獨佔一行的多行欄位收得到(DP):
    """⛔ `_KV` 要求鍵名後至少一個空白 —— `code` 單獨一行完全不匹配，
    整段程式碼會被當成**上一個欄位的續行**，而且不會報錯（2026-08-26 實測）。
    """
    c = DP.parse(CODE_CASE, "CRUX")["cases"][0]
    assert c["code"], u"code 沒收到 —— 整段碼會併進上一個欄位"
    assert c["code"].startswith("import pytest")
    assert "def test_玩法篩選只回該玩法(backend_page):" in c["code"]
    assert c["expected"].startswith("只回"), u"expected 被 code 汙染了"


def test_縮排六格以上的程式碼不會被當成欄位(DP):
    """★ 這是為什麼提示要求 code 內容縮排 ≥6：
    `    actual = po.rows()` 縮 4 格時 `actual` 落在 `_KNOWN_KEYS` 裡，
    會被當成新欄位而把整段碼從那裡切斷。
    """
    c = DP.parse(CODE_CASE, "CRUX")["cases"][0]
    assert "actual = 300" in c["code"] and "expected = 300" in c["code"]
    # dedent 後回到正常的四格縮排，不是原始的十格
    assert "\n    expected = 300" in c["code"], repr(c["code"])


def test_沒有def_test的code會退回產碼器(DP):
    """交了 code 但不是一段案例碼時**不可以直接寫進去** —— 那會產出收不到的檔。"""
    bad = CODE_CASE.replace("def test_玩法篩選只回該玩法(backend_page):", "x = 1  # 忘了寫 def")
    c = DP.parse(bad, "CRUX")["cases"][0]
    assert c["code"], u"還是要留著，好讓 preview 報「交了 code 卻沒有 def test_」"


# ── 案例落點：三種產品寫法都要認（2026-08-26 code review）───
#
# ⛔ `tests_out_dir("CRUX")` 原本會炸（只認 slug `crux`）。
#    而**同一個 draft 裡兩種寫法並存**：頂層 `product` 是 slug，
#    每條 case 的 `product` 被 `_norm_product` 正規化成權威 id。
#    當時沒炸只是因為 `preview()` 剛好讀頂層那個。

def test_案例落點三種產品寫法都認():
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "cw_ut", os.path.join(ROOT, "tools", "test_platform", "core", "case_writer.py"))
    m = _u.module_from_spec(spec)
    sys_path_added = os.path.join(ROOT, "tools", "test_platform")
    import sys
    if sys_path_added not in sys.path:
        sys.path.insert(0, sys_path_added)
    spec.loader.exec_module(m)
    try:
        by_slug = m.tests_out_dir("crux")
    except ValueError:
        pytest.skip("本工作區沒有 crux")
    assert m.tests_out_dir("CRUX") == by_slug, u"權威 id 算出來的落點不一樣"


def test_沒登記的產品要明講而不是預設一個():
    """⛔ 猜一個落點比報錯更糟 —— 案例會靜靜地寫到別的產品底下。"""
    import importlib.util as _u
    import sys
    p = os.path.join(ROOT, "tools", "test_platform")
    if p not in sys.path:
        sys.path.insert(0, p)
    spec = _u.spec_from_file_location("cw_ut2", os.path.join(p, "core", "case_writer.py"))
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    with pytest.raises(ValueError):
        m.tests_out_dir("這個產品不存在")
