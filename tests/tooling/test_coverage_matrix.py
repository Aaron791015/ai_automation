# -*- coding: utf-8 -*-
"""`scripts/coverage_matrix.py`（覆蓋矩陣解析）的回歸測試。

用途：這支腳本的價值在於「把人工看不出來的剩餘工作量算成數字」，因此
      **解析錯一欄就會給出錯誤的覆蓋率**，比不做更糟。
      特別要守住三件事：① 欄位別名（既有矩陣用「本次深度」，新標準用「本次」）
      ② 風險→目標深度的推導 ③ lint 的「整欄缺只報一次」——
      實測過整欄缺時逐列報會刷出 61 行，把真正該逐列修的問題淹掉。
前置條件：無（全部在 tmp_path 上操作，不碰真實 docs/）。
使用方式：`pytest tests/tooling/test_coverage_matrix.py -q`
"""
import os

import pytest

import coverage_matrix as cm


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# ── 標準矩陣（新欄位）─────────────────────────────────────────
STD = """# 測試矩陣

## 2.1 定盤

| # | 功能點 | 來源 | 風險 | 目標 | 本次 | 已知缺陷 | 後續詳驗要點 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | 玩法表結構 | API | 顯示 |  | L2 | — | 逐列比對 |
| A2 | 賠率上下限 | 對照 | 金流 |  | **L3** | CRUX-077 | 等 RD 修完再全驗 |
| A3 | 四字现玩法 | 選單 | 金流 |  | L0 | CRUX-078 | 完全沒測 |

## 2.2 報表

| # | 功能點 | 來源 | 風險 | 目標 | 本次 | 已知缺陷 | 後續詳驗要點 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 | 日報表 | 選單 | 金流 | L3 | L3 | — | 已達標 |
"""


def test_解析多張表格並統計深度分布(tmp_path):
    """覆蓋矩陣通常依區塊分成多張表，不能只讀第一張。"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "m.md", STD)))
    assert res["total"] == 4
    assert res["dist"]["L0"] == 1 and res["dist"]["L2"] == 1 and res["dist"]["L3"] == 2


def test_風險推導目標深度(tmp_path):
    """目標欄留空時由風險推導：金流→L4、顯示→L2。"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "m.md", STD)))
    by = dict((r["item"]["id"], r) for r in res["rows"])
    assert by["A1"]["target"] == "L2"      # 顯示
    assert by["A2"]["target"] == "L4"      # 金流
    assert by["A1"]["gap"] == 0            # L2 已達 L2
    assert by["A3"]["gap"] == 4            # L0 → L4


def test_目標欄可覆寫推導值(tmp_path):
    """D1 明寫目標 L3（金流本會推 L4）——手填優先。"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "m.md", STD)))
    d1 = [r for r in res["rows"] if r["item"]["id"] == "D1"][0]
    assert d1["target"] == "L3" and d1["gap"] == 0


def test_達標與未達的分組(tmp_path):
    res = cm.analyse(cm.collect_items(_write(tmp_path, "m.md", STD)))
    assert len(res["met"]) == 2            # A1、D1
    assert len(res["unmet"]) == 2          # A2、A3


def test_阻塞偵測(tmp_path):
    """要點欄提到「等 RD」的列要被標成阻塞，否則排批次時會先做白工。"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "m.md", STD)))
    assert [b["id"] for b in res["blocked"]] == ["A2"]


# ── 欄位別名與 markdown 清理 ──────────────────────────────────
def test_相容既有矩陣的本次深度欄名(tmp_path):
    """既有矩陣用「本次深度」，不能因為改標準就讀不到舊檔。"""
    old = """| # | 功能點 | 本次深度 | 已知缺陷 | 後續詳驗要點 |
| --- | --- | --- | --- | --- |
| A1 | 玩法表 | L2 | — | 待比對 |
"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "old.md", old)))
    assert res["total"] == 1 and res["dist"]["L2"] == 1


def test_儲存格內跳脫的直線不會切錯欄(tmp_path):
    r"""要點欄常寫 `A \| B`；若把它當欄位分隔，整列會錯位。"""
    md = r"""| # | 功能點 | 風險 | 本次 | 後續詳驗要點 |
| --- | --- | --- | --- | --- |
| A1 | 玩法表 | 金流 | L1 | 比對 A \| B 兩種寫法 |
"""
    items = cm.collect_items(_write(tmp_path, "esc.md", md))
    assert items[0]["note"] == "比對 A | B 兩種寫法"


def test_清掉粗體與刪除線(tmp_path):
    md = """| # | 功能點 | 風險 | 本次 |
| --- | --- | --- | --- |
| ~~A1~~ | **玩法表** | 金流 | **L3** |
"""
    items = cm.collect_items(_write(tmp_path, "fmt.md", md))
    assert items[0]["id"] == "A1" and items[0]["name"] == "玩法表"
    assert cm._depth(items[0]["current"]) == "L3"


def test_跳過非矩陣的說明表(tmp_path):
    """同一份檔常有「深度分級」說明表，表頭沒有『功能點』就不該被當成資料。"""
    md = """| 級別 | 意義 | 判準 |
| --- | --- | --- |
| L0 | 未觸及 | 沒開過 |

| # | 功能點 | 風險 | 本次 |
| --- | --- | --- | --- |
| A1 | 玩法表 | 金流 | L1 |
"""
    assert len(cm.collect_items(_write(tmp_path, "mix.md", md))) == 1


# ── lint ────────────────────────────────────────────────────
def test_lint_整欄缺只報一次(tmp_path, capsys):
    """★ 回歸保障：整張矩陣沒有風險欄時，不可逐列報 N 次。

    實測既有的 61 列矩陣會刷出 61 行同樣的話，把真正該逐列修的問題淹掉。
    """
    md = """| # | 功能點 | 本次深度 |
| --- | --- | --- |
| A1 | 甲 | L1 |
| A2 | 乙 | L2 |
| A3 | 丙 | L0 |
"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "n.md", md)))
    assert cm.lint("n.md", res) == 1
    out = capsys.readouterr().out
    assert out.count("未標「風險」") == 0          # 不逐列報
    assert "整張矩陣沒有「風險」欄" in out          # 只報一次
    assert "整張矩陣沒有「來源」欄" in out


def test_lint_有欄位時逐列報缺項(tmp_path, capsys):
    """有風險欄、只有個別列沒填 —— 這時就該指名道姓到行號。"""
    md = """| # | 功能點 | 來源 | 風險 | 本次 |
| --- | --- | --- | --- | --- |
| A1 | 甲 | 選單 | 金流 | L1 |
| A2 | 乙 | 選單 |  | L2 |
"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "p.md", md)))
    assert cm.lint("p.md", res) == 1
    out = capsys.readouterr().out
    assert "A2" in out and "未標「風險」" in out
    assert "A1" not in out.split("未標「風險」")[1] if "未標「風險」" in out else True


def test_lint_完整矩陣通過(tmp_path, capsys):
    res = cm.analyse(cm.collect_items(_write(tmp_path, "m.md", STD)))
    assert cm.lint("m.md", res) == 0
    assert "✅ 通過" in capsys.readouterr().out


def test_解析不到功能點時明確報錯(tmp_path, capsys):
    """空檔或表頭不對時要說清楚原因，不能靜靜地回報 0 個功能點。"""
    res = cm.analyse(cm.collect_items(_write(tmp_path, "e.md", "# 沒有表格\n")))
    assert cm.lint("e.md", res) == 1
    assert "沒有解析到任何功能點列" in capsys.readouterr().out


# ── orphans ─────────────────────────────────────────────────
CASES = """| # | 案例 | 被測行為 | 預期（oracle） | 對應矩陣項 |
| --- | --- | --- | --- | --- |
| C1 | 驗玩法表 | 讀取 | 21 種（A） | A1 |
| C2 | 驗賠率 | 讀取 | 9400~9996（A） | A2 |
"""


def test_orphans_找出沒推成案例的功能點(tmp_path, capsys):
    m = _write(tmp_path, "m.md", STD)
    c = _write(tmp_path, "c.md", CASES)
    assert cm.orphans(m, c) == 1
    out = capsys.readouterr().out
    assert "A3" in out and "D1" in out      # 未被案例涵蓋
    assert "共 2 項" in out


def test_orphans_全涵蓋時通過(tmp_path, capsys):
    m = _write(tmp_path, "m.md", STD)
    c = _write(tmp_path, "c.md", CASES + "| C3 | 驗四字现 | 下注 | 可下注（A） | A3 |\n"
                                         "| C4 | 驗日報表 | 讀取 | 對帳一致（B） | D1 |\n")
    assert cm.orphans(m, c) == 0
    assert "每個功能點都有對應案例" in capsys.readouterr().out


def test_orphans_案例清單缺對應欄時給明確指引(tmp_path, capsys):
    """沒有『對應矩陣項』欄就建立不了雙向追溯，要講清楚怎麼補。"""
    m = _write(tmp_path, "m.md", STD)
    c = _write(tmp_path, "c.md", "| # | 案例 |\n| --- | --- |\n| C1 | 驗玩法表 |\n")
    assert cm.orphans(m, c) == 1
    assert "沒有「對應矩陣項」欄" in capsys.readouterr().out


def test_orphans_一列可對應多個矩陣項(tmp_path, capsys):
    """一條案例常同時覆蓋多個功能點，分隔符要都吃得下。"""
    m = _write(tmp_path, "m.md", STD)
    c = _write(tmp_path, "c.md",
               "| # | 案例 | 對應矩陣項 |\n| --- | --- | --- |\n"
               "| C1 | 綜合驗 | A1、A2 / A3　D1 |\n")
    assert cm.orphans(m, c) == 0
