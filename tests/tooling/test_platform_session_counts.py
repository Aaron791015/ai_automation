# -*- coding: utf-8 -*-
"""`/api/sessions` 的清單與計數要分開（2026-08-27 使用者回報）。

用途：釘住「**要顯示數量的地方不可以用清單長度**」。

★ 原本的 bug：`active=[... ][:10]`、`closed=[... ][:10]` 兩個清單被截斷，
  而前端拿它們的 `.length` 當計數 —— 於是：
    ① 總覽的對話入口顯示「10 條進行中」，實際 14
    ② 對話面板的下拉標籤也是 10，**而且第 11 條之後根本選不到**（更嚴重）
  ⚠️ 那個 `[:10]` 還**省不到任何頻寬** —— 完整的 `sessions` 本來就在同一個回應裡。

前置條件：無（session 目錄用臨時目錄假造）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _load(name):
    """⛔ 不在模組層動 `sys.path`（會污染整場 pytest）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import importlib
    return importlib.import_module(name)


@pytest.fixture
def api(tmp_path, monkeypatch):
    S = _load("web_ui.api.sessions")
    monkeypatch.setattr(S, "SESSIONS_DIR", str(tmp_path))
    return S


def _mk(tmp_path, n, state="active", prefix="s"):
    for i in range(n):
        d = tmp_path / ("%s%02d" % (prefix, i))
        d.mkdir()
        # ⚠️ `created_at` 不可省 —— `list_sessions()` 刻意跳過沒有它的紀錄
        #    （那是「跑測試留下的幽靈 session」的防線，見該函式的註解）。
        (d / "meta.json").write_text(json.dumps(
            {"id": "%s%02d" % (prefix, i), "title": "t%d" % i, "state": state,
             "created_at": "2026-08-27 09:00:00",
             "last_active": "2026-08-27 10:%02d:00" % i}, ensure_ascii=False),
            encoding="utf-8")


def _call(api):
    """直接跑 handler，取出它回給前端的 payload。"""
    app = _load("web_ui.app").create_app()
    with app.test_request_context("/api/sessions"):
        r = api.api_list()
    return json.loads(r.get_data(as_text=True)) if hasattr(r, "get_data") else r


def test_計數不可以跟著清單被截斷(api, tmp_path):
    """★ 使用者回報的那一顆：14 條卻顯示 10。"""
    _mk(tmp_path, 14)
    d = _call(api)
    assert d["active_count"] == 14, u"計數不對 —— 前端的「N 條進行中」就會是錯的"
    assert len(d["sessions"]) == 14


def test_清單本身也不可以被截斷否則選不到(api, tmp_path):
    """⛔ 比數字更嚴重：下拉只列得出前 N 條，**第 N+1 條之後根本選不到**。"""
    _mk(tmp_path, 14)
    d = _call(api)
    assert len(d["active"]) == 14, \
        u"清單被截斷 —— 對話面板的下拉會選不到後面那幾條 session"


def test_已關閉的也一樣(api, tmp_path):
    _mk(tmp_path, 12, state="closed", prefix="c")
    d = _call(api)
    assert d["closed_count"] == 12 and len(d["closed"]) == 12


def test_計數與清單長度一致時也要兩個都在(api, tmp_path):
    """⚠️ 少量時兩者相同，很容易讓人覺得 `*_count` 是多餘的而砍掉 ——

    留著它是為了「日後真的需要截斷時，計數不會跟著錯」。
    """
    _mk(tmp_path, 3)
    d = _call(api)
    for k in ("active", "closed", "active_count", "closed_count", "sessions"):
        assert k in d, u"回應少了 `%s`" % k


def test_前端顯示數量時不可以用清單長度():
    """⛔ 這條掃原始碼 —— 它才是這顆 bug 真正的成因（後端截斷只是誘因）。"""
    import io
    import re
    bad = []
    for rel in ("ui/chatportal.js", "ui/chatpanel.js"):
        p = os.path.join(PLATFORM, "web_ui", "static", "js", rel)
        src = io.open(p, encoding="utf-8").read()
        # ⚠️ 只抓「**顯示給人看的**數字」，不要抓條件判斷 ——
        #    `sessions.active.length ? …` 是「有沒有」，那是正當用法；
        #    `（${…length}）` 才是印在畫面上的數量。
        #    （第一版沒分這兩者，把條件判斷也報成缺陷。）
        for m in re.finditer(r"（\$\{[^}]*\.length[^}]*\}）", src):
            # ⭐ `X_count ?? …length` 是**降級備援**，合格 —— 主來源已經是計數，
            #    `.length` 只在「平台還沒重啟、API 還沒有這個鍵」時才會用到。
            #    要判的是「主來源是不是計數」，不是「有沒有出現 length」。
            if "_count" in m.group(0):
                continue
            bad.append("%s: %s" % (rel, m.group(0)[:70]))
        for m in re.finditer(r"n = \(d\.(active|closed) \|\| \[\]\)\.length", src):
            bad.append("%s: %s" % (rel, m.group(0)))
    assert not bad, (
        u"這幾處把清單長度當數量顯示 —— 清單一旦被截斷數字就錯：\n  "
        + "\n  ".join(bad))
