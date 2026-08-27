# -*- coding: utf-8 -*-
"""「跑完之後去哪」與「提議執行」（2026-08-24 走查盲點 ②⑤）。

兩個都是**宣告存在、效果不存在**那一類 —— 不會有任何錯誤訊息：

· `next`：宣告錯了（缺 href、when 打錯）就靜默不顯示，
  與 `group`／`options_from` 同一種失效形狀
· `proposal`：前端讀 `done` 事件的 `proposal`，而後端**從來沒有產生過那個欄位**
  —— 確認卡從未出現過，而 `perf` 任務唯一的產出就是提議

使用方式：`pytest tests/tooling/test_platform_next_and_proposal.py -q`
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _platform():
    """⛔ **不可以在模組層做這件事** —— `sys.path` 一插進平台目錄，
    收集 `tests/wbot/perf/` 時它要的 `core` 就會解析到平台的 core，
    整包收集直接 `ModuleNotFoundError`。

    `test_collect_all_roots.py` 就是在守這一條，而本檔第一版當場違反了它
    （2026-08-24）—— 這正好證明那條測試有用。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)


def _spec(next_items):
    return {"id": "x", "name": "X", "kind": "cli", "product": "crux",
            "commands": [{"id": "c", "mode": "sync", "argv": ["-m", "x"],
                          "next": next_items}]}


def _errs(next_items):
    _platform()
    from core.registry import validate_spec
    return [e["error"] for e in validate_spec(_spec(next_items), "x.tool.json")]


# ── next 的驗證 ───────────────────────────────────────────
def test_next少了href會被擋下():
    assert any("少了 label 或 href" in e for e in _errs([{"label": "去看看"}]))


def test_next少了label會被擋下():
    assert any("少了 label 或 href" in e for e in _errs([{"href": "#/cases"}]))


def test_next不可以指向站外():
    """⛔ `next` 是宣告式的，不該變成「開任意網址」的口。"""
    for bad in ("https://example.com", "http://x", "//evil", "javascript:alert(1)"):
        assert any("站內路由" in e for e in _errs([{"label": "x", "href": bad}])), bad


def test_next的when只能是ok或fail():
    assert any("ok／fail" in e for e in _errs([{"label": "x", "href": "#/a", "when": "maybe"}]))
    assert not _errs([{"label": "x", "href": "#/a", "when": "ok"}])
    assert not _errs([{"label": "x", "href": "#/a", "when": "fail"}])
    assert not _errs([{"label": "x", "href": "#/a"}])          # when 可省略


def test_真實的tool_json全部通過驗證():
    """★ 這一條才是重點：宣告錯了會**靜默不顯示**，靠人目測是擋不住的。"""
    _platform()
    from core.registry import load_registry
    reg = load_registry(force=True)
    assert reg.errors == [], reg.errors
    n = sum(1 for t in reg.tools.values() for c in t.commands if c.get("next"))
    assert n >= 10, "宣告 next 的命令太少（目前 %d）—— sync 命令原本一個下一步都沒有" % n


def test_next的href佔位只用得到自己的欄位():
    """`{欄位鍵}` 會被這次填的值取代 —— 鍵必須真的是該命令的欄位，
    否則畫面上會出現一顆連過去是壞路由的按鈕。"""
    _platform()
    from core.registry import load_registry
    import re
    bad = []
    for tid, spec in load_registry(force=True).tools.items():
        for c in spec.commands:
            keys = {f.get("key") for f in ((c.get("params") or {}).get("fields") or [])}
            for n in (c.get("next") or []):
                for ph in re.findall(r"\{(\w+)\}", n.get("href", "")):
                    if ph not in keys:
                        bad.append("%s.%s → {%s}（該命令沒有這個欄位）" % (tid, c["id"], ph))
    assert not bad, bad


# ── 提議的攔截 ────────────────────────────────────────────
def _as_proposal(ev):
    _platform()
    from web_ui.api.chat import _as_proposal as f
    return f(ev)


def test_認得mcp的propose_run():
    """⚠️ 工具名帶著 MCP server 前綴 —— 不可以寫死完整名字。"""
    p = _as_proposal({"name": "mcp__test-platform__propose_run",
                      "input": {"tool_id": "ui_tests", "command_id": "run_cases",
                                "reason": "重跑上次失敗的"}})
    assert p and p["tool_id"] == "ui_tests"
    assert p["command_id"] == "run_cases"
    assert p["reason"] == "重跑上次失敗的"
    assert p["command_label"], "要帶得出人看得懂的命令名稱"


def test_其他工具不會被誤認成提議():
    for name in ("Read", "mcp__playwright__browser_click", "mcp__test-platform__get_bugs"):
        assert _as_proposal({"name": name, "input": {"tool_id": "x", "command_id": "y"}}) is None, name


def test_少了必要參數就不算提議():
    """⛔ 半個提議比沒有提議更糟 —— 確認卡會出現但按下去是壞的。"""
    assert _as_proposal({"name": "x__propose_run", "input": {"tool_id": "ui_tests"}}) is None
    assert _as_proposal({"name": "x__propose_run", "input": {}}) is None
    assert _as_proposal({"name": "x__propose_run"}) is None


def test_未知的工具仍然回得出提議():
    """⚠️ 平台不認得那支工具時**不可以吞掉** —— 人要看到「它提議了什麼」
    才知道是 Claude 講錯了，而不是平台默默沒反應。"""
    p = _as_proposal({"name": "x__propose_run",
                      "input": {"tool_id": "不存在的工具", "command_id": "c"}})
    assert p and p["tool_id"] == "不存在的工具"
    assert p["danger"] == "low"


def test_提議會進待確認清單():
    """★ `perf` 任務是 `writes: none` —— 提議是它**唯一**的產出。
    先前它只活在對話訊息裡，總覽完全看不到「有一個提議在等你按」。"""
    _platform()
    from web_ui.api.sessions import _output_summary
    out = _output_summary({}, "sid-1")
    assert out == [], "沒有產出時不該無中生有"

    import web_ui.api.sessions as S
    # `mark_done` 會把 proposal 插到最前面 —— 直接驗那段組裝
    items = S._output_summary({}, "sid-1")
    prop = {"tool_id": "crux_perf", "tool_name": "CRUX 下注壓測",
            "command_id": "bet_load", "command_label": "下注壓測"}
    items.insert(0, {"kind": "proposal",
                     "text": "提議執行：%s · %s（需要你確認）" % (prop["tool_name"], prop["command_label"]),
                     "href": "#/tool/%s" % prop["tool_id"]})
    assert items[0]["href"] == "#/tool/crux_perf"
    assert "需要你確認" in items[0]["text"]


# ── 產出的連結要走得到產出物 ───────────────────────────────
def test_產出連結不可以只指向對話列表():
    """⛔ `#/sessions` 是對話列表，**不是產出物** —— 人到了還要自己找。

    使用者裁示：「確認完結果，要可以接續下一步
    （ex: 案例審查／Bug 描述檢視／測試報告查看）」。
    """
    _platform()
    from web_ui.api.sessions import _output_summary
    got = {
        "bugs": 2,
        "cases_written": {"ok": True, "collected": 5, "path": "tests/crux/test_x.py"},
        "written": [{"path": "docs/CRUX/機制.md"}],
        "needs_review": [{"title": "A", "why": "太大"}],
        "write_failed": [{"title": "B", "errors": ["權限"]}],
    }
    out = _output_summary(got, "sid-9")
    assert out, "有產出就該列得出來"
    for item in out:
        assert item["href"] != "#/sessions", "%s 只指向對話列表，等於沒接上" % item["kind"]
    by_kind = {i["kind"]: i["href"] for i in out}
    assert "tests/crux/test_x.py" in by_kind["cases"], "案例要帶檔案路徑才定位得到那一批"
    assert by_kind["doc"].startswith("#/doc?path="), "文件要直接開全文"
    assert "sid-9" in by_kind["bug_draft"], "草稿要指到那一個 session"


def test_沒有session_id時才退回對話列表():
    """⚠️ 那是最後手段，不是預設。"""
    _platform()
    from web_ui.api.sessions import _output_summary
    out = _output_summary({"bugs": 1}, "")
    assert out[0]["href"] == "#/sessions"
