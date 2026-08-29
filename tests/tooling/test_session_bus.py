# -*- coding: utf-8 -*-
"""`core/session_bus.py` —— 一條 session、一份產出、多個畫面看得到。

為什麼需要這一支（2026-08-28）
    先前是「一個 POST 自帶一條串流」，三個症狀同一個根因（產出綁在連線上）：
      · 重整分頁 → 那一輪的過程再也看不到
      · 兩個分頁看同一個 session → 各看各的
      · 同一個 session 想連送兩則 → 只能擋掉
    匯流排是這三件事的共同前提，所以它的**邊界行為**要釘死：
    補播不可以漏、慢的訂閱者不可以擋住產出、記憶體要有上限。

使用方式：`pytest tests/tooling/test_session_bus.py -q`
前置條件：無（純記憶體）。
"""
import os
import queue
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _bus():
    """⛔ 不可以在模組層插 sys.path（`test_collect_all_roots` 專門守它）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import session_bus
    return session_bus


@pytest.fixture
def B():
    b = _bus()
    b._reset_for_tests()
    yield b
    b._reset_for_tests()


def test_訂閱之後收得到(B):
    q, replay = B.subscribe("s")
    assert replay == []
    B.publish("s", "a")
    assert q.get_nowait() == (1, "a")


def test_補播只補指定序號之後的(B):
    for x in "abc":
        B.publish("s", x)
    _q, replay = B.subscribe("s", since=2)
    assert replay == [(3, "c")], replay


def test_沒給序號就補整段backlog(B):
    """重整回來的畫面要看得到剛剛錯過的過程 —— 這就是那條路。"""
    for x in "abc":
        B.publish("s", x)
    _q, replay = B.subscribe("s")
    assert [p for _s, p in replay] == ["a", "b", "c"]


def test_補播與加入訂閱不可以有空隙(B):
    """⛔ 若「讀 backlog」與「加入訂閱者」不在同一個鎖裡，
    兩者之間送出的事件會**整個消失**（補播沒有、推播也沒有）。

    這裡從外部驗結果：訂閱前後各送一個，兩個都要拿得到、且不重複。
    """
    B.publish("s", "before")
    q, replay = B.subscribe("s")
    B.publish("s", "after")
    got = [p for _s, p in replay] + [q.get_nowait()[1]]
    assert got == ["before", "after"], got


def test_慢的訂閱者被丟掉而不是擋住產出(B, monkeypatch):
    """⛔ 一個卡住的分頁**不可以拖垮整輪任務** —— 塞爆就丟掉它，讓它重連補播。"""
    monkeypatch.setattr(B, "_MAX_SUB", 3)
    q, _r = B.subscribe("s")
    for i in range(10):
        B.publish("s", i)               # 不可以在這裡卡住
    assert B.stats()["subs"] == 0, u"讀太慢的訂閱者沒有被丟掉"
    assert q.qsize() == 3


def test_backlog有上限(B, monkeypatch):
    """沒有人在看的時候也不可以無限長 —— 它只是「還沒看到的畫面」的暫存。"""
    monkeypatch.setattr(B, "_MAX_BACKLOG", 5)
    for i in range(50):
        B.publish("s", i)
    assert B.stats()["backlog"] == 5
    _q, replay = B.subscribe("s")
    assert [p for _s, p in replay] == [45, 46, 47, 48, 49], replay


def test_序號不會因為backlog被截而重來(B, monkeypatch):
    """⚠️ 序號是 `Last-Event-ID` 的依據 —— 重來的話重連會補到錯的位置。"""
    monkeypatch.setattr(B, "_MAX_BACKLOG", 3)
    for i in range(10):
        B.publish("s", i)
    _q, replay = B.subscribe("s")
    assert [s for s, _p in replay] == [8, 9, 10], replay


def test_關掉session要叫醒訂閱者(B):
    """⛔ 不叫醒的話，那條 SSE 會一直掛著（每 20 秒 ping 一次）永遠不收線。"""
    q, _r = B.subscribe("s")
    B.close("s")
    assert q.get_nowait() is None
    assert B.stats()["buses"] == 0


def test_匯流排數量有上限且先淘汰沒人看的(B, monkeypatch):
    monkeypatch.setattr(B, "_MAX_BUSES", 3)
    for i in range(3):
        B.publish("s%d" % i, "x")
    B.subscribe("s0")                   # s0 有人在看
    B.publish("s3", "x")                # 觸發淘汰
    assert B.stats()["buses"] <= 3
    got = [p for _s, p in B.subscribe("s0")[1]]
    assert got == ["x"], u"有訂閱者的那一條被淘汰了"


def test_全部都有人在看就不淘汰(B, monkeypatch):
    """⚠️ 寧可超過上限，也不可以把有人正在看的那一條丟掉 ——
    丟掉等於那個畫面從此收不到任何東西，而它自己不會知道。"""
    monkeypatch.setattr(B, "_MAX_BUSES", 2)
    for i in range(4):
        B.subscribe("s%d" % i)
    assert B.stats()["buses"] == 4


def test_取消訂閱之後不再收到(B):
    q, _r = B.subscribe("s")
    B.unsubscribe("s", q)
    B.publish("s", "a")
    with pytest.raises(queue.Empty):
        q.get_nowait()
