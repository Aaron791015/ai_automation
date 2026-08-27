# -*- coding: utf-8 -*-
"""平台 MCP server 與對話接真（階段 D，2026-08-23）。

用途：這一階段讓平台起的 Claude session 能查真實索引、並且**只能提議不能執行**。
      三件事必須釘住，而且其中兩件是**實測才發現的**：

      ① ⛔ **工具封鎖**：`--allowedTools` 白名單**擋不住** ——
         實測時 session 照樣跑了 `Bash: git status`；擋掉 Bash 之後它**改用
         `PowerShell`**。要兩者都下，且拒絕清單要涵蓋所有 shell 與副作用型工具。
      ② ⛔ **`propose_run` 只提議不執行**（ARCHITECTURE 決策 8 的閘門）——
         它一旦真的呼叫 `runner.manager`，「人按確認卡才跑」就形同虛設。
      ③ **MCP server 只准 stdlib** —— 不裝 `mcp` SDK。
         範本的原則是「`setup_test_env.ps1` 跑完就能用」，每多一個相依就多一個
         「在同事機器上裝不起來」的機會（階段 0 的 flask 就是這樣漏掉的）。

前置條件：⚠️ 匯入延後到函式內。本檔**不啟動 claude.exe**，只驗協定與參數組裝。
使用方式：`pytest tests/tooling/test_platform_mcp_and_chat.py -q`
"""
import ast
import io
import json
import os
import sys

import pytest

import conftest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")
SERVER_PY = os.path.join(PLATFORM, "mcp", "server.py")


def _mcp():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import mcp.server as S
    return S


def _cs():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.claude_session as C
    return C


# ─────────────────────────────── ③ MCP server 只准 stdlib

def test_server只用stdlib():
    """★ 不裝 `mcp` SDK —— 範本要「裝完就能跑」。
    MCP 是 JSON-RPC over stdio，工具型 server 只需三個方法。"""
    tree = ast.parse(io.open(SERVER_PY, encoding="utf-8").read())
    top = set()
    for node in tree.body:                       # 只看**模組層**的 import
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            top.add(node.module.split(".")[0])
    assert top <= {"json", "os", "sys", "traceback", "__future__"}, \
        "模組層匯入了非 stdlib：%s" % top


def test_stdout只准放JSON_RPC():
    """任何 print 到 stdout 都會污染協定，Claude 那端會判定 server 壞掉。"""
    src = io.open(SERVER_PY, encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            kw = {k.arg for k in node.keywords}
            assert "file" in kw, "第 %d 行的 print 沒有指定 file=stderr" % node.lineno


# ─────────────────────────────── JSON-RPC 協定

def test_initialize回協定版本與能力():
    S = _mcp()
    r = S.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r["result"]["protocolVersion"] == S.PROTOCOL_VERSION
    assert "tools" in r["result"]["capabilities"]


def test_通知不回應():
    """有 `id` 才要回；通知沒有 id，回了會讓對方解析失敗。"""
    S = _mcp()
    assert S.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert S.handle({"jsonrpc": "2.0", "method": "不認得的通知"}) is None


def test_未支援的方法回錯誤碼():
    S = _mcp()
    r = S.handle({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
    assert r["error"]["code"] == -32601


def test_每個工具都有描述與schema():
    """Claude 是靠 description 決定要不要呼叫的 —— 空描述等於這個工具不存在。"""
    S = _mcp()
    for t in S._tools():
        assert t["name"] and len(t["description"]) >= 20, t["name"]
        assert t["inputSchema"]["type"] == "object"


def test_工具錯誤要標isError(monkeypatch):
    S = _mcp()
    r = S.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "不存在的工具", "arguments": {}}})
    assert r["result"]["isError"] is True


def test_工具丟例外時不會讓server掛掉(monkeypatch):
    S = _mcp()
    monkeypatch.setattr(S, "_call", lambda n, a: (_ for _ in ()).throw(RuntimeError("炸了")))
    r = S.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                  "params": {"name": "get_runs", "arguments": {}}})
    assert r["result"]["isError"] is True
    assert "炸了" in r["result"]["content"][0]["text"]


def test_serve主迴圈能處理多則訊息():
    S = _mcp()
    import io as _io

    class Out:
        def __init__(self):
            self.lines = []

        def write(self, s):
            self.lines.append(s)

        def flush(self):
            pass

    src = _io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + "這不是 JSON\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
    out = Out()
    S.serve(stdin=src, stdout=out)
    ids = [json.loads(l)["id"] for l in out.lines]
    assert ids == [1, 2], "壞掉的行與通知都不該產生回應"


# ─────────────────────────────── ② propose_run 只提議

def test_propose_run絕不執行():
    """★ 決策 8 的閘門。它一旦呼叫 `runner.manager`，
    「人按確認卡才跑」就形同虛設。

    ⚠️ 用 AST 檢查**實際的 import**，不要用字串搜尋 ——
      檔頭的說明本來就會提到 `runner.manager`。
      （階段 C 已經踩過一次同樣的錯，寫新測試時又寫回字串搜尋。）
    """
    mods = set()
    for node in ast.walk(ast.parse(io.open(SERVER_PY, encoding="utf-8").read())):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    bad = [m for m in mods if m.startswith("runner")]
    assert not bad, "MCP server 匯入了執行器：%s —— propose_run 可能會真的跑" % bad


def test_propose_run回提議且帶危險等級():
    S = _mcp()
    r = S._call("propose_run", {"tool_id": "ui_tests", "command_id": "run_cases",
                                "reason": "測試"})
    assert "proposal" in r and "note" in r
    assert r["proposal"]["danger"] in ("low", "medium", "high")
    assert "不會" in r["note"] or "確認卡" in r["note"]


def test_propose_run對未知工具給可行的提示():
    S = _mcp()
    r = S._call("propose_run", {"tool_id": "不存在", "command_id": "x"})
    assert "list_tools" in r["error"], "錯誤訊息要告訴它怎麼查對的 id"


# ─────────────────────────────── ① 工具封鎖（實測發現的兩層）

def test_兩個shell都放行():
    """⭐ 2026-08-25 政策改變：**shell 要給**（使用者裁示「做得到與終端機幾乎相同的事」）。

    先前一律不給，擋掉的不只是風險，**也擋掉了規範本身** ——
    `stamp_shots.py` 搬截圖、`gen_bug_index --next-id` 配號、`lint_docs` 收尾全跑不了，
    實際後果是 8 張佐證整批遺失、知識回寫做不完（T44）。

    ⚠️ 兩個 shell 都要給：skill 裡寫的是 PowerShell 語法（`python scripts\\lint_docs.py`），
       在 bash 底下反斜線會被吃掉。
    """
    C = _cs()
    for shell in ("Bash", "PowerShell", "BashOutput", "KillShell"):
        assert shell in C.SAFE_TOOLS, "%s 應該放行" % shell
        assert shell not in C.DENIED_TOOLS, "%s 不該再被擋" % shell


def test_寫檔放行但派生仍然擋():
    """寫檔給了（明著給，比讓它用 `python -c` 偷寫更看得見）；
    會**放大權限**的（派生 agent、排程、對外發布）仍然一律擋。"""
    C = _cs()
    for t in ("Write", "Edit"):
        assert t in C.SAFE_TOOLS, "%s 應該放行" % t
    for t in ("NotebookEdit", "Task", "Workflow", "CronCreate", "SendMessage",
              "Artifact", "ScheduleWakeup"):
        assert t in C.DENIED_TOOLS, "%s 沒被擋" % t


def test_護欄一定要掛上去(monkeypatch, tmp_path):
    """⛔ **這條是放寬 shell 的唯一前提** —— 護欄沒掛上，等於直接把 git 索引交出去。

    釘三件事：settings 檔真的產得出來、hook 是 PreToolUse、指向的是護欄那支。
    """
    C = _cs()
    p = C.write_settings(str(tmp_path / "s.json"))
    import json
    cfg = json.load(open(p, encoding="utf-8"))
    hooks = cfg["hooks"]["PreToolUse"]
    assert hooks and "Bash" in hooks[0]["matcher"] and "PowerShell" in hooks[0]["matcher"]
    cmd = hooks[0]["hooks"][0]["command"]
    assert "pretool_guard.py" in cmd
    assert C.GUARD_SCRIPT.replace("\\", "/").endswith(
        "tools/test_platform/guard/pretool_guard.py")


def test_安全清單與拒絕清單不重疊():
    C = _cs()
    assert not (C.SAFE_TOOLS & set(C.DENIED_TOOLS))


def test_Skill要留著():
    """⭐「skill 是平台的大腦」靠它落實（ROADMAP §2）——
    擋掉 Skill 等於平台的 session 讀不到方法論。"""
    C = _cs()
    assert "Skill" in C.SAFE_TOOLS


def test_argv三樣都要下(monkeypatch):
    """★ 只下白名單擋不住（2026-08-23 實測），所以白名單、拒絕清單、**護欄**三樣都要。"""
    C = _cs()
    monkeypatch.setattr(C, "find_executable", lambda: ("claude.exe", "test"))
    argv = C.build_argv("hi", model="sonnet")
    assert "--allowedTools" in argv and "--disallowedTools" in argv
    assert "--settings" in argv, "⛔ 護欄沒掛上 —— shell 開放之後這是唯一的邊界"
    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    assert "Task" in denied and "Bash" not in denied
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert C.MCP_PREFIX in allowed and "Bash" in allowed


def test_cwd是repo_root才載得到skill():
    """cwd 不是 repo root 的話，session 不會自動載入 CLAUDE.md 與 .claude/skills/。"""
    src = io.open(os.path.join(PLATFORM, "core", "claude_session.py"),
                  encoding="utf-8").read()
    assert "cwd=REPO_ROOT" in src


# ─────────────────────────────── 事件翻譯與降級

def test_翻譯只吐前端認得的四種():
    C = _cs()
    raw = [
        {"type": "system", "subtype": "init", "session_id": "s1", "tools": ["Read"]},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "嗨"},
            {"type": "tool_use", "name": "mcp__test-platform__get_runs", "input": {}}]}},
        {"type": "result", "session_id": "s1", "usage": {"output_tokens": 3},
         "total_cost_usd": 0.01, "is_error": False},
        {"type": "不認得的事件"},
    ]
    got = [e for ev in raw for e in C._translate(ev)]
    assert [e["type"] for e in got] == ["tool", "text", "tool", "done"]
    assert got[-1]["session_id"] == "s1"


def test_init帶出未分類工具供自檢():
    """Claude Code 日後新增工具時，拒絕清單會**靜默過期** —— 要有東西提醒。"""
    C = _cs()
    ev = next(iter(C._translate({"type": "system", "subtype": "init",
                                 "tools": ["Read", "某個新工具"]})))
    assert ev["input"]["unexpected_tools"] == ["某個新工具"]


def test_claude不可用時優雅停用(monkeypatch):
    """同事可能只想用索引與執行，不接對話 —— 不可讓整個平台掛掉。"""
    C = _cs()
    monkeypatch.setattr(C, "probe_claude", lambda: {"executable": None})
    okay, why = C.available()
    assert okay is False and "claude.exe" in why
    evs = list(C.ask("hi"))
    assert evs == [{"type": "error", "message": why}]


def test_未登入時也停用(monkeypatch):
    C = _cs()
    monkeypatch.setattr(C, "probe_claude",
                        lambda: {"executable": "x", "auth": {"loggedIn": False}})
    okay, why = C.available()
    assert okay is False and "登入" in why


# ─────────────────────────────── .mcp.json 註冊

def test_mcp已註冊且用相對路徑():
    """★ `.mcp.json` 隨範本發給同事 —— 寫絕對路徑到別人機器上就壞了。"""
    d = json.load(io.open(os.path.join(ROOT, ".mcp.json"), encoding="utf-8"))
    e = d["mcpServers"]["test-platform"]
    for p in [e["command"]] + list(e["args"]):
        assert not os.path.isabs(p) and ":" not in p, "用了絕對路徑：%s" % p
    assert os.path.isfile(os.path.join(ROOT, e["args"][0])), "註冊的檔案不存在"


# ── 草稿要查得到（收尾體檢實跑時自己點出的缺口）────────────────
#
# 2026-08-23：平台的收尾體檢說「📦 有 2 筆 Bug 草稿還沒開單」，
# 而 session 回覆「可用的 MCP 工具沒有一個能查草稿，這一段我做不了判斷」。
# ⛔ 平台把發現丟給 session，卻不給它查下去的工具 —— 動線在這裡斷掉。

def test_有查草稿的工具():
    names = {t["name"] for t in _mcp()._tools()}
    assert "get_drafts" in names, u"收尾體檢查不到草稿內容，發現就只能停在數字"


def test_查草稿要分得出bug與文件兩種():
    got = _mcp()._call("get_drafts", {})
    assert "bugs" in got and "docs" in got, got
    assert "不佔 Bug ID" in (got.get("note") or ""), u"沒講清楚草稿不佔號"


def test_查草稿可以只要一種():
    got = _mcp()._call("get_drafts", {"kind": "doc"})
    assert "docs" in got and "bugs" not in got


def test_bug草稿要帶開單前三問():
    """★ 三問的**答案**是「為什麼判定該開」的唯一佐證，查不到等於沒有。"""
    got = _mcp()._call("get_drafts", {"kind": "bug"})
    for b in got["bugs"]:
        assert "prechecks" in b, b


# ── 逾時之後要接得回前文 ────────────────────────────────────
#
# 2026-08-23 實跑 90 秒上限：1501 字保住了、錯誤訊息也有，
# 但續接用的 `claude_session_id` **只在 done 事件裡記** ——
# 被殺的程序沒有 done 事件，於是下一則訊息是全新對話，脈絡全丟。

def test_逾時訊息要講對時間():
    C = _cs()
    assert C._human_duration(90) == "90 秒" or "秒" in C._human_duration(90)
    assert C._human_duration(1800) == "30 分鐘"
    assert C._human_duration(3960) == "66 分鐘"
    # ⛔ 先前 `timeout // 60` 讓 90 秒顯示成「1 分鐘」——講錯了上限
    assert C._human_duration(90) != "1 分鐘"


def test_逾時訊息要講清楚怎麼接下去():
    """⚠️ 先前寫「用『續接』」—— 那是 UI 上關閉後重開的動作，不是這裡要做的事。"""
    C = _cs()

    class _P:
        stdout = iter(())
        stderr = None

        def wait(self):
            return -1

        def kill(self):
            pass

    evs = list(C.ask("x", timeout=0.01, _popen=lambda *a, **k: _P()))
    errs = [e for e in evs if e["type"] == "error"]
    if errs and "時間上限" in errs[0]["message"]:
        assert "再送一則訊息" in errs[0]["message"]


def test_init事件就記住claude的session_id():
    """★ 這是「逾時之後接得回去」的根本 —— 不能等 done。"""
    import inspect
    src = inspect.getsource(_chat())
    i = src.index("_init")
    # `_init` 附近要有記住 session id 的動作
    assert "_remember_claude_session" in src[max(0, i - 400):i + 600], \
        u"`_init` 事件沒有記住 claude 的 session id，逾時後就接不回前文"


def _chat():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.api.chat as C
    return C


# ── 新寫入的案例要真的跑一次（2026-08-26）──────────────────
#
# ⛔ 在這之前只跑 `--collect-only` —— 那只證明「語法對、import 得到、收得到」，
#    證明不了**跑起來會過**。於是 `verified: yes` 一直是 session 自己說的、
#    沒有任何一步查證（使用者問「案例生成過程中，沒有去做測試嗎？」）。

def test_落檔後會發動一次真的執行(monkeypatch):
    C = _chat()
    seen = {}

    class _Spec:
        id = "ui_tests"
        commands = [{"id": "run_cases", "label": "執行案例"}]

    def fake_start(spec, cmd, params, **kw):
        seen.update(spec=spec.id, cmd=cmd["id"], selection=kw.get("selection"))
        return {"run_id": "r-123"}

    # ⚠️ `from runner import manager` 取的是**真模組的屬性** ——
    #    塞 `sys.modules["runner.manager"]` 攔不到，要 import 真模組再 setattr。
    from runner import manager as M
    monkeypatch.setattr(M, "start", fake_start)
    import core.registry as R
    monkeypatch.setattr(R, "get_registry",
                        lambda: type("Reg", (), {"tools": {"ui_tests": _Spec()}})())

    got = C._verify_run(["tests/crux/test_a.py::test_x", "tests/crux/test_a.py::test_y"])
    assert got.get("run_id") == "r-123", got
    assert seen["selection"] == ["tests/crux/test_a.py::test_x",
                                 "tests/crux/test_a.py::test_y"]
    assert seen["cmd"] == "run_cases"


def test_跑不成要講原因而不是靜靜地略過(monkeypatch):
    """⛔ 沒跑成卻不說，人會以為跑過了 —— 那比不跑更糟。"""
    C = _chat()

    def boom(*a, **k):
        raise RuntimeError("另一個 run 正在跑")
    from runner import manager as M
    monkeypatch.setattr(M, "start", boom)
    import core.registry as R
    _S = type("S", (), {"id": "ui_tests", "commands": [{"id": "run_cases"}]})
    monkeypatch.setattr(R, "get_registry",
                        lambda: type("Reg", (), {"tools": {"ui_tests": _S()}})())
    got = C._verify_run(["tests/x.py::test_a"])
    assert "run_id" not in got
    assert "另一個 run 正在跑" in got.get("skipped", ""), got


def test_沒有nodeid就不跑():
    assert "skipped" in _chat()._verify_run([])


def test_摘要要區分寫入了與跑得過():
    """⛔ 只寫「寫入 22 條案例」會讓人以為案例好了。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.api.sessions as S
    ok = S._output_summary({"cases": 2, "cases_written": {
        "ok": True, "collected": 2, "path": "tests/crux/test_a.py",
        "verify_run": {"run_id": "r-9", "count": 2}}}, "sid")
    assert any(x["kind"] == "run" and "r-9" in x["href"] for x in ok), ok
    bad = S._output_summary({"cases": 2, "cases_written": {
        "ok": True, "collected": 2, "path": "tests/crux/test_a.py",
        "verify_run": {"skipped": "併發被擋"}}}, "sid")
    # ⚠️ 用 any 不用 warn[0] —— 2026-08-26 起「沒交整檔執行結果」也是一則 warn，
    #    順序不該被測試釘死。
    assert any(x["kind"] == "warn" and "沒有實際執行過" in x["text"] for x in bad), bad


def _summary(cases_written):
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.api.sessions as S
    return S._output_summary({"cases": 2, "cases_written": cases_written}, "sid")


_OK = {"ok": True, "collected": 2, "path": "tests/crux/test_a.py",
       "verify_run": {"run_id": "r-1", "count": 2}}


def test_沒交整檔執行結果要講出來():
    """⛔ 逐條跑抓不到互相影響（共用 fixture、前一條沒還原站台狀態）。"""
    got = _summary(dict(_OK, runs=[]))
    assert any("沒有交整檔執行結果" in x["text"] for x in got), got


def test_只跑一次要講出來():
    """★ 第二次才看得出「不可反覆執行」—— 資料殘留、名稱撞號、狀態沒收。"""
    got = _summary(dict(_OK, runs=[{"full_run": "22 passed", "rerun": "",
                                    "known_fail": ""}]))
    assert any("只跑了一次" in x["text"] for x in got), got


def test_兩次不一致要講出來():
    got = _summary(dict(_OK, runs=[{"full_run": "22 passed",
                                    "rerun": "20 passed，與第一次不一致",
                                    "known_fail": ""}]))
    assert any("兩次執行結果不一致" in x["text"] for x in got), got


def test_known_fail要浮出來讓人核對():
    """⛔⛔ 「這條本來就該紅」是最容易被濫用的宣告 —— 一條其實是自己寫錯的紅燈，
    宣告成「抓到缺陷」就沒有人會再去看它。平台不判定對不對，但一定要讓人看見。
    """
    got = _summary(dict(_OK, runs=[{"full_run": "21 passed, 1 failed",
                                    "rerun": "一致",
                                    "known_fail": "test_c19=CRUX-115"}]))
    hit = [x for x in got if x["kind"] == "known_fail"]
    assert hit and "CRUX-115" in hit[0]["text"], got
    assert "別讓它把判準改到綠" in hit[0]["text"]


def test_known_fail會寫進run備註(monkeypatch):
    """人看 run 結果時要對照得到「它說會紅的是這幾條」。"""
    C = _chat()
    seen = {}

    def fake_start(spec, cmd, params, **kw):
        seen["remark"] = kw.get("remark")
        return {"run_id": "r-1"}
    from runner import manager as M
    monkeypatch.setattr(M, "start", fake_start)
    import core.registry as R
    _S = type("S", (), {"id": "ui_tests", "commands": [{"id": "run_cases"}]})
    monkeypatch.setattr(R, "get_registry",
                        lambda: type("Reg", (), {"tools": {"ui_tests": _S()}})())
    C._verify_run(["tests/x.py::test_a"], [{"known_fail": "test_c19=CRUX-115"}])
    assert "CRUX-115" in seen["remark"], seen


# ── SSE：兩個疊在一起的缺陷，讓串流**從來沒有成功過** ──────────────
#
# 2026-08-23 UI 走查（按下任務的「開始」）才挖出來：
#   ① 前端用 GET 把兩千多字的提示塞進 query → URL 破四千字元 → 500
#   ② 後端 `gen()` 閉包內對 `text` 賦值 → 讀外層 `text` 時 UnboundLocalError → 500
# 前端每次都靜默退回非串流，所以畫面「按了沒反應、突然跳頁」，而且沒有人發現串流是壞的。

def test_stream端點收POST():
    """任務的提示有兩千多字 —— 塞進 query string 一定會爆。"""
    import inspect
    src = inspect.getsource(_chat().chat_stream)
    assert "get_json" in src, u"沒有從 body 取 text，長提示會被塞進 URL"


def test_stream的閉包不會遮蔽外層的text():
    """★ 這一條就是那個 500 的迴歸：閉包內一旦對 `text` 賦值，
    迴圈開頭讀它就會 `UnboundLocalError`。"""
    import inspect
    src = inspect.getsource(_chat().chat_stream)
    body = src[src.index("def gen("):]
    # 閉包內不得再出現 `text = `（賦值）
    for ln in body.split("\n"):
        st = ln.strip()
        assert not st.startswith("text ="), u"閉包內又對 text 賦值了：%s" % st


def test_stream真的串得出事件(monkeypatch):
    """不接真 claude —— 只驗這條路走得完、事件送得出去。"""
    C = _chat()
    monkeypatch.setattr(C, "claude_available", lambda: (True, ""))
    monkeypatch.setattr(C, "claude_ask",
                        lambda *a, **k: iter([{"type": "text", "text": "嗨"},
                                              {"type": "done", "session_id": "x",
                                               "usage": {}}]))
    monkeypatch.setattr(C, "get_meta", lambda sid: {"id": sid, "state": "active"})
    monkeypatch.setattr(C, "append_message", lambda *a, **k: {"role": "assistant"})
    # ⛔ 這一行不補的話，測試會在**真的** `logs/sessions/xyz/` 留下一筆 meta ——
    #    `_remember_claude_session()` 會拿 done 事件的 session_id 去 save_meta。
    #    症狀是對話清單多出一列「沒有標題、0 則、最後活動 —」的幽靈
    #    （2026-08-24 走查才發現，而它已經躺在那裡好幾天）。
    #    ⚠️ 測試污染正式資料這件事本身比那一列還嚴重：同事跑一次測試就會多一筆。
    saved = []
    monkeypatch.setattr(C, "save_meta", lambda m: saved.append(m))
    app = _flask_app()
    got = app.test_client().post("/api/chat/xyz/stream", json={"text": "問一句"})
    assert got.status_code == 200, got.data[:200]
    assert b"data:" in got.data


def _flask_app():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.app as A
    return A.app


def test_斷線時已產出的內容仍然落檔(monkeypatch):
    """★ 2026-08-23 實測：任務跑到一半平台被重啟 —— 連線斷掉，那一輪整段消失。

    SSE 的 `gen()` 是跑完迴圈才 `append_message`，而 client 斷線會讓
    generator 收到 `GeneratorExit`，**後面那幾行永遠不會執行**。
    與逾時是同一類：跑了幾十分鐘的東西，不能因為收尾那一步沒跑到就全丟。
    """
    C = _chat()
    saved = []
    monkeypatch.setattr(C, "claude_available", lambda: (True, ""))
    monkeypatch.setattr(C, "claude_ask",
                        lambda *a, **k: iter([{"type": "text", "text": "第一段"},
                                              {"type": "text", "text": "第二段"},
                                              {"type": "text", "text": "第三段"}]))
    monkeypatch.setattr(C, "get_meta", lambda sid: {"id": sid, "state": "active"})
    monkeypatch.setattr(C, "append_message",
                        lambda sid, role, text, **k:
                        (saved.append(text) if role == "assistant" else None)
                        or {"role": role})
    app = _flask_app()
    with app.test_request_context("/api/chat/x/stream", json={"text": "問"}):
        resp = C.chat_stream("x")
        it = resp.response
        next(it)                    # 只讀第一段就「斷線」
        it.close()                  # 觸發 GeneratorExit
    assert saved, u"斷線之後一個字都沒留"
    assert "第一段" in saved[0]


def test_正常結束不會重複落檔(monkeypatch):
    C = _chat()
    saved = []
    monkeypatch.setattr(C, "claude_available", lambda: (True, ""))
    monkeypatch.setattr(C, "claude_ask",
                        lambda *a, **k: iter([{"type": "text", "text": "全部"}]))
    monkeypatch.setattr(C, "get_meta", lambda sid: {"id": sid, "state": "active"})
    monkeypatch.setattr(C, "append_message",
                        lambda sid, role, text, **k:
                        (saved.append(text) if role == "assistant" else None)
                        or {"role": role})
    app = _flask_app()
    with app.test_request_context("/api/chat/x/stream", json={"text": "問"}):
        resp = C.chat_stream("x")
        list(resp.response)
    assert len(saved) == 1, u"落了兩次檔：%s" % saved


# ── ⛔ 產品名的兩套 id：不轉會靜默回 0 ────────────────────────
#
# 2026-08-24 實測（對話視窗，真的問了一句）：
#   「用平台的 MCP 查一下：CRUX 現在有幾張活躍 Bug？」
#   → session 拿**權威 id** `CRUX` 呼叫 `get_bugs` → 回 **0 張**，
#     而同一時間畫面上寫著 60 張。
#
# 成因：這個工作區有兩套 id —— `config/products.json` 的權威 id（`CRUX`）
# 與平台內部的 slug（`crux`）。`by_prod.get("CRUX")` 拿到 `None`，
# 而程式把 `None` 當成「這個產品沒有 Bug」。
#
# ⚠️ 這一類最貴：**不報錯、答案看起來完全合理**。

def test_mcp的產品名兩種寫法都查得到():
    # ⛔ 不可以寫死 `CRUX` —— 匯出的範本一個產品都沒有（2026-08-24 匯出時實際紅了）
    slug, authoritative = conftest.need_product()
    m = _mcp()
    a = m._call("get_bugs", {"product": authoritative, "limit": 1})
    b = m._call("get_bugs", {"product": slug, "limit": 1})
    assert a.get("total") == b.get("total"), "權威 id 與 slug 查到的數量不一樣"
    assert not a.get("error"), "用權威 id 查竟然查不到產品：%s" % a.get("error")


def test_mcp查不到的產品要說出來不要回0():
    """⛔ 回 0 會被讀成「沒有 Bug」；要回 error 才不會被當成答案。"""
    got = _mcp()._call("get_bugs", {"product": "並不存在的產品"})
    assert got.get("error"), "查不到的產品竟然靜默回了一個數字"
    assert "沒有這個產品" in got["error"]


def test_to_slug認得權威id與label():
    import sys
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import to_slug
    assert to_slug("") == ""
    assert to_slug("並不存在的產品") == "並不存在的產品", "認不得的原樣回傳，不要吞掉"
    slug, authoritative = conftest.need_product()
    assert to_slug(authoritative) == slug, "權威 id 沒有轉成 slug"
    assert to_slug(slug) == slug, "已經是 slug 的不該被改掉"
    assert to_slug(authoritative.upper()) == slug, "大小寫不同也要認得"


# ── 記下「載了哪支 skill」（2026-08-26）─────────────────────
#
# 使用者問「呼叫了 Skill 3 次 → 同一個 skill 嗎？」而平台答不出來 ——
# `tools` 欄只存工具名稱。要翻 claude 的原生 transcript 才查得到
# （結果是 crux／ui-test／testcase-design 三支不同的）。
# ⭐「skill 是平台的大腦」，那它載了哪一支就是最該留的紀錄之一。

def test_skill要記下載了哪一支():
    C = _chat()
    assert C._tool_label({"name": "Skill", "input": {"skill": "ui-test"}}) == "Skill:ui-test"
    assert C._tool_label({"name": "Skill", "input": {}}) == "Skill", u"沒帶名稱就原樣"


def test_其他工具不展開參數():
    """⛔ `Bash` 的指令、`Write` 的內容可能含帳密 —— 記進 messages.jsonl 就是外洩面。"""
    C = _chat()
    assert C._tool_label({"name": "Bash",
                          "input": {"command": "mysql -u root -pSECRET"}}) == "Bash"
    assert C._tool_label({"name": "Write", "input": {"content": "x" * 9999}}) == "Write"
