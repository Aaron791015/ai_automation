# -*- coding: utf-8 -*-
"""`scripts/next_todo_id.py`（交接檔待辦編號防撞）的回歸測試。

用途：這支腳本存在的唯一理由是「擋掉編號重複」——多 session 併行時沒有任何機制擋它，
      而 `CRUX_功能驗證交接.md` 已實際撞號三組（T27／T34／T43）。
      **若它漏認任何一種既有寫法，就會把已用的號再配一次，等於製造它要防的問題。**
      ★ 最重要的回歸：`| ~~**T5**~~ ✅ 2026-08-21 完成 |` 這種
      「編號後面還有完成註記才到欄位分隔」的寫法（2026-08-22 實測漏認過）。
前置條件：無（全部在 tmp_path 上操作，不碰真實 docs/）。
使用方式：`pytest tests/tooling/test_next_todo_id.py -q`
"""
import pytest

import next_todo_id as nt


def _doc(tmp_path, body, name="x_驗證交接.md"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_三種基本寫法都認得(tmp_path):
    body = """| # | 事項 |
| --- | --- |
| T1 | 一般寫法 |
| **T2** | 粗體 |
| ~~T3~~ | 已完成劃掉 |
"""
    used = nt.collect(_doc(tmp_path, body))
    assert sorted(used["T"]) == [1, 2, 3]


def test_編號後有完成註記也要認得(tmp_path):
    """★ 回歸保障：漏認這種寫法會把已用的號再配一次。"""
    body = """| # | 事項 |
| --- | --- |
| ~~**T5**~~ ✅ **2026-08-21 完成** | 測試平台四條動線 |
| T4 | 另一件事 |
"""
    used = nt.collect(_doc(tmp_path, body))
    assert sorted(used["T"]) == [4, 5], "T5 沒被認出 → 下一個會配到 T5 而撞號"


def test_劃掉的編號仍佔用不回收(tmp_path):
    body = "| # | 事項 |\n| --- | --- |\n| ~~T1~~ | 做完了 |\n| ~~T2~~ | 也做完了 |\n"
    used = nt.collect(_doc(tmp_path, body))
    assert sorted(used["T"]) == [1, 2]


def test_表頭與分隔列不誤判(tmp_path):
    body = "| # | 功能點 | A1 說明 |\n| --- | --- | --- |\n| T1 | 甲 | 乙 |\n"
    used = nt.collect(_doc(tmp_path, body))
    assert sorted(used["T"]) == [1] and "A" not in used


def test_不同種類分開計數(tmp_path):
    body = "| # | x |\n| --- | --- |\n| T1 | a |\n| D1 | b |\n| B2 | c |\n"
    used = nt.collect(_doc(tmp_path, body))
    assert sorted(used["T"]) == [1] and sorted(used["D"]) == [1] and sorted(used["B"]) == [2]


def test_偵測撞號(tmp_path, capsys):
    body = "| # | x |\n| --- | --- |\n| T7 | 甲 |\n| **T7** | 乙（不同 session 寫的）|\n"
    used = nt.collect(_doc(tmp_path, body))
    assert nt.report_dupes("x", used) == 1
    assert "T7 被用了 2 次" in capsys.readouterr().out


def test_配號為最大值加一(tmp_path, capsys):
    body = "| # | x |\n| --- | --- |\n| T1 | a |\n| ~~T9~~ | b |\n"
    nt.main(["--handover", _doc(tmp_path, body), "--kind", "T"])
    assert "**T10**" in capsys.readouterr().out


def test_全新檔案從1開始(tmp_path, capsys):
    nt.main(["--handover", _doc(tmp_path, "| # | x |\n| --- | --- |\n"), "--kind", "T"])
    assert "**T1**" in capsys.readouterr().out


def test_check模式有撞號時回傳非零(tmp_path):
    body = "| # | x |\n| --- | --- |\n| T3 | a |\n| T3 | b |\n"
    assert nt.main(["--handover", _doc(tmp_path, body), "--kind", "T", "--check"]) == 1


def test_找不到檔案時明確報錯(tmp_path):
    with pytest.raises(SystemExit):
        nt.main(["--handover", str(tmp_path / "不存在.md"), "--kind", "T"])
