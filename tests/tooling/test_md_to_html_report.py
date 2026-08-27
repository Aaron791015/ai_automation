# -*- coding: utf-8 -*-
"""`scripts/md_to_html_report.py` 的回歸測試。

用途：測試報告要對外交付，轉檔**默默漏掉一段**比整支壞掉更危險
      —— 壞掉看得出來，漏一列表格看不出來。本檔鎖住轉換的完整性
      （表格列數、清單項數）與三個容易寫錯的細節（見各案例 docstring）。
前置條件：無（純字串處理，不碰檔案系統）。
"""
import io

import md_to_html_report as M


def test_表格列數與欄數完整保留():
    """漏一列或漏一欄都不會報錯，只能靠數量比對抓出來。"""
    md = "\n".join([
        "| 指標 | A | B |",
        "| --- | --- | --- |",
        "| RPS | 64.45 | 64.52 |",
        "| 節流率 | 86.84% | 87.37% |",
    ])
    out = M.convert(md)
    assert out.count("<table>") == 1
    assert out.count("<th>") == 3
    assert out.count("<tr>") == 3          # 表頭 1 ＋ 資料 2
    assert out.count("<td>") == 6
    assert "64.52" in out and "87.37%" in out


def test_表格欄數不齊時補空欄而非塌掉():
    """手寫報告偶爾少打一個 `|`；補空欄可讓其餘欄位仍對齊，不要整表錯位。"""
    md = "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |"
    out = M.convert(md)
    assert out.count("<td>") == 3


def test_水平線不可被當成清單():
    """`---` 與 `- x` 都以 `-` 開頭；判斷順序寫反會把每條分隔線變成清單項。"""
    out = M.convert("段落一\n\n---\n\n- 項目")
    assert "<hr>" in out
    assert out.count("<li>") == 1


def test_行內程式碼裡的星號不被當成粗體():
    """`band:35-*` 這種寫法在報告裡很常見，先抽出程式碼才不會被 `**` 規則吃掉。

    注意：程式碼區塊內的 `**` **應該**原樣保留（那是內容），
    要驗的是「區塊外的 `**` 有轉成粗體、區塊內的沒有被吃掉」。
    """
    out = M.convert("使用 `a ** b` 與 **真粗體**")
    assert out == "<p>使用 <code>a ** b</code> 與 <strong>真粗體</strong></p>"


def test_html_逸出避免內容被當標籤():
    """報告裡會出現 `<details>` 以外的角括號（如泛型、比較符號），必須逸出。"""
    out = M.convert("門檻 5 < x > 3 且 a & b")
    assert "&lt;" in out and "&gt;" in out and "&amp;" in out


def test_清單項數完整():
    md = "- 一\n- 二\n- 三\n\n1. 甲\n2. 乙"
    out = M.convert(md)
    assert out.count("<li>") == 5
    assert out.count("<ul>") == 1 and out.count("<ol>") == 1


def test_產出為單檔且無外部資源(tmp_path):
    """對外交付要能只寄一個檔，任何外部 URL 都會在對方那邊破圖／破版。"""
    src = tmp_path / "報告.md"
    io.open(src, "w", encoding="utf-8").write(
        "# CRUX 效能測試報告\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    dest = M.convert_file(str(src))
    html = io.open(dest, encoding="utf-8").read()
    assert dest.endswith(".html")
    assert "<style>" in html                      # CSS 內嵌
    assert 'href="http' not in html and 'src="http' not in html
    assert "<title>CRUX 效能測試報告</title>" in html   # 標題取自第一個 H1
