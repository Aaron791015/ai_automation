# -*- coding: utf-8 -*-
"""每個 session 一條**事件匯流排**：一份產出、多個畫面看得到，重整也接得回去。

用途：把「這一輪產出什麼」與「誰在看」拆開（`chat.py` 的 pump 只 publish）。
使用方式：`publish(sid, payload)` / `subscribe(sid, since)` / `unsubscribe` / `close`。
前置條件：純記憶體，行程重啟就空了（落檔的訊息才是權威來源）。

為什麼需要它（2026-08-28）
    先前是「**一個 POST 自帶一條串流**」—— 串流是那一次送出的私有物，於是：
      · 重整分頁 → 那一輪的過程再也看不到（只剩輪詢得到的工具 chip）
      · 兩個分頁看同一個 session → 各看各的，誰也看不到對方那一輪
      · 同一個 session 想連送兩則 → 只能擋掉（`claude_session_id` 會互相蓋）
    三個症狀同一個根因：**產出綁在連線上**。

    改成匯流排之後，pump 只管 `publish()`，畫面自己來 `subscribe()`。
    這也是「排隊」的前提 —— 排隊的那一則沒有自己的連線，只能靠訂閱看到。

設計上的三個取捨
    · **backlog 留最近 %d 個事件**：重整回來要能補上剛剛錯過的，但不能無限長。
      補不齊時前端會重新載入落檔的訊息（那份才是完整的權威來源）。
    · **訂閱者的佇列有上限**：讀太慢就把那個訂閱者丟掉，讓它重連 ——
      ⛔ 不可以反過來擋住 `publish()`，那等於讓一個卡住的分頁拖垮整輪任務。
    · **匯流排數量有上限**：沒有訂閱者、又最久沒動的先淘汰。
      它只是「還沒看到的畫面」的暫存，掉了不影響落檔。
""" % 400  # noqa: E501 —— docstring 裡的數字與 _MAX_BACKLOG 同步
import itertools
import queue
import threading

#: 每個 session 保留的事件數（重整後補播用）
_MAX_BACKLOG = 400
#: 最多同時保留幾條匯流排（沒有訂閱者的先淘汰）
_MAX_BUSES = 60
#: 單一訂閱者的佇列上限；塞爆就丟掉這個訂閱者（它會重連並補播）
_MAX_SUB = 2000

_reg_lock = threading.Lock()
_buses = {}                     # sid -> _Bus
_tick = itertools.count(1)      # 淘汰用的順序（不看時鐘，測試才好寫）


class _Bus(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.backlog = []       # [(seq, payload)]
        self.subs = set()       # {queue.Queue}
        self.touched = next(_tick)


def _get(sid, create=True):
    with _reg_lock:
        b = _buses.get(sid)
        if b is None and create:
            _evict_locked()
            b = _buses[sid] = _Bus()
        return b


def _evict_locked():
    """沒有訂閱者、又最久沒動的先淘汰。全都有人在看就不動。

    ⚠️ 已知邊界：一輪**沒有任何畫面在看**的任務，理論上可能被淘汰，
       之後重建時序號會從 1 重來 —— 那時中途加入的畫面補播不到東西
       （事件仍然照送，只是少了前面那段）。上限 60 條，實務上撞不到；
       真的要根治就得讓匯流排知道「這條有 pump 在跑」，成本大於收益。
    """
    while len(_buses) >= _MAX_BUSES:
        idle = [(b.touched, s) for s, b in _buses.items() if not b.subs]
        if not idle:
            return
        _buses.pop(min(idle)[1], None)


def publish(sid, payload):
    """送一個事件給所有訂閱者，並記進 backlog。回傳這個事件的序號。"""
    b = _get(sid)
    with b.lock:
        b.seq += 1
        seq = b.seq
        b.touched = next(_tick)
        b.backlog.append((seq, payload))
        if len(b.backlog) > _MAX_BACKLOG:
            del b.backlog[:-_MAX_BACKLOG]
        dead = []
        for q in b.subs:
            try:
                q.put_nowait((seq, payload))
            except queue.Full:
                dead.append(q)          # ⛔ 讀太慢的訂閱者丟掉，不可以擋住這裡
        for q in dead:
            b.subs.discard(q)
    return seq


def tip(sid):
    """目前的序號。⭐ 拿它當 `since` 就是「**不要補播**，從現在開始」。"""
    b = _get(sid, create=False)
    return b.seq if b is not None else 0


def subscribe(sid, since=None):
    """訂閱。回傳 (佇列, 要補播的 [(seq, payload)])。

    `since` 是前端上次收到的序號（SSE 的 `Last-Event-ID`）——
    ⚠️ 補播與加入訂閱**必須在同一個鎖裡**，否則兩者之間送出的事件會**整個消失**。
    """
    b = _get(sid)
    q = queue.Queue(maxsize=_MAX_SUB)
    with b.lock:
        replay = [x for x in b.backlog if since is None or x[0] > since]
        b.subs.add(q)
    return q, replay


def unsubscribe(sid, q):
    b = _get(sid, create=False)
    if b is not None:
        with b.lock:
            b.subs.discard(q)


def close(sid):
    """session 關掉了：叫醒所有訂閱者（收到 None ＝ 收工）並丟掉這條匯流排。"""
    with _reg_lock:
        b = _buses.pop(sid, None)
    if b is None:
        return
    with b.lock:
        for q in b.subs:
            try:
                q.put_nowait(None)
            except queue.Full:
                pass
        b.subs.clear()


def stats():
    """給測試與 `/api/settings` 看的現況。"""
    with _reg_lock:
        return {"buses": len(_buses),
                "subs": sum(len(b.subs) for b in _buses.values()),
                "backlog": sum(len(b.backlog) for b in _buses.values())}


def _reset_for_tests():
    with _reg_lock:
        _buses.clear()
