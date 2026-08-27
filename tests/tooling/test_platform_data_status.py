# -*- coding: utf-8 -*-
"""交接檔 §5「測試資料現況」的解析（開工必讀的那一節）。

為什麼這一節值得單獨釘住
    `handoff` skill §1.A 是**開場無條件必做**的兩節：§1 blocker 與 §5 測試資料現況。
    而 §5 是那兩節裡**唯一「不先讀會造成不可逆傷害」**的 ——
    標明「刻意保留、屬哪一張單」的資料清掉之後，那張單就不可重現了
    （RD 照 Reproduce Steps 走會看不到現象，要重新建資料才拍得到佐證）。

    handoff 自己解釋過為什麼它必須前置：這一節的觸發時機是「我看到一批看起來
    像殘留的資料」，而那一刻的判斷是「這是垃圾，清掉」——
    **不會有任何訊號提醒你先去查交接檔**。平台是同事一天的起點，要替他推到眼前。

⚠️ 誤判的方向很重要：**把已刪除的東西標成「不要動」**比漏標更糟 ——
   人一旦發現警示不準就會整塊略過，連真正該看的那一筆也一起略過。

使用方式：`pytest tests/tooling/test_platform_data_status.py -q`
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import todo_index
    return todo_index


HEADER = ["動過什麼", "還原了嗎", "備註"]


def test_刻意保留判得出來():
    T = _mod()
    assert T._is_kept(HEADER, ["帳號 x", "⛔ **刻意保留**", "屬 A-001 的重現環境"])
    assert T._is_kept(HEADER, ["帳號 x", "尚未還原", "等 RD 確認"])


def test_已還原的不可以被標成保留():
    """★ 核心迴歸：備註裡的「資料**無保留**價值」曾讓整列命中「保留」。"""
    T = _mod()
    assert not T._is_kept(HEADER, ["歷史開獎 200 筆", "✅ 已刪除", "A-003 已撤銷，資料無保留價值"])
    assert not T._is_kept(HEADER, ["注單", "✅ 已退碼", "量完就還原"])


def test_沒有還原欄時退回整列():
    T = _mod()
    assert T._is_kept(["項目", "說明"], ["帳號 x", "刻意保留給 A-001"])


def test_兩張表不會互相污染():
    """§5 常有兩張表（骨架自帶一張、後來又加一張）——
    空行沒有結束表格的話，第二張的**表頭**會被當成資料列。"""
    T = _mod()
    lines = [
        "## 5. 測試資料現況",
        "",
        "| 動過什麼 | 還原了嗎 | 備註 |",
        "| --- | --- | --- |",
        "| 帳號 A | ⛔ 刻意保留 | 屬 X-001 |",
        "",
        "| 動了什麼 | 屬哪張單 | 清掉會失去什麼 |",
        "| --- | --- | --- |",
        "| （尚無） | — | — |",
        "",
        "## 6. 維護規則",
    ]
    rows = T._data_rows(lines)
    whats = [r["what"] for r in rows]
    assert "帳號 A" in whats
    assert "動了什麼" not in whats, u"第二張表的表頭被當成資料列：%s" % whats
    assert "（尚無）" not in whats, u"佔位列沒有被濾掉：%s" % whats


def test_刻意保留的排在前面():
    T = _mod()
    lines = [
        "## 5. 測試資料現況",
        "",
        "| 動過什麼 | 還原了嗎 | 備註 |",
        "| --- | --- | --- |",
        "| 已刪的 | ✅ 已刪除 | — |",
        "| 要留的 | ⛔ 刻意保留 | 屬 X-001 |",
    ]
    rows = T._data_rows(lines)
    assert rows[0]["what"] == "要留的", u"刻意保留的沒有排在最前面"


def test_真實交接檔解析得出東西():
    """跑真的 repo —— 只驗「解析得出結構」，不驗內容（內容會變）。"""
    T = _mod()
    idx = T.build_todo_index()
    for pid, p in (idx.get("products") or {}).items():
        for r in p.get("data_status") or []:
            assert isinstance(r.get("kept"), bool)
            assert isinstance(r.get("what"), str)
            assert r.get("doc"), u"每一列都要知道它來自哪一份交接檔"
