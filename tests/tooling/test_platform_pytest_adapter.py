# -*- coding: utf-8 -*-
"""`adapters/pytest_.py` 與進度 plugin（階段 C，2026-08-23）。

用途：這支 adapter 讓平台**真的把 pytest 跑起來**。三個陷阱全部會**靜默失真**
      （跑得起來、只是數字或狀態是錯的），所以要靠測試釘住：

      ① **子程序不可寫 `run_status.json`** —— `core/jsonio.py` 的鎖是 `threading.Lock`
         （程序內），跨程序無效。plugin 只 append `progress.jsonl`。
      ② **pytest exit code 1 ＝「有案例失敗」，不是「run 失敗」** ——
         映射錯的話 `run_index` 的 `hourly_heat` 會把每次紅燈算成基礎設施故障。
      ③ **`--alluredir` 必須覆蓋** —— `pyproject.toml` 的 addopts 無條件帶
         `reports/allure-results`，不覆蓋則所有 run 互相污染、還弄髒正式報告。

前置條件：⚠️ 匯入延後到函式內（`tools/test_platform` 與 `tools/wbot_Performance`
          都有頂層 `core` 套件）。本檔**不真的起子程序**，全部在暫存目錄上驗邏輯。
使用方式：`pytest tests/tooling/test_platform_pytest_adapter.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import adapters.pytest_ as P
    return P


# ─────────────────────────────── ② 退出碼映射

@pytest.mark.parametrize("code,expect", [
    (0, "completed"),          # 全過
    (1, "completed"),          # ★ 有案例失敗 —— run 本身跑完了
    (5, "completed"),          # 沒收集到案例：不是基礎設施故障
    (2, "failed"),             # 被中斷
    (3, "failed"),             # pytest 內部錯誤
    (4, "failed"),             # 命令列用法錯誤
])
def test_退出碼映射(tmp_path, monkeypatch, code, expect):
    P = _mod()
    seen = {}
    monkeypatch.setattr(P.rs, "read_status", lambda rid: {"phase": "running"})
    monkeypatch.setattr(P.rs, "run_dir", lambda rid: str(tmp_path))
    monkeypatch.setattr(P.rs, "update_status",
                        lambda rid, **kw: seen.update(kw) or {})

    class Spec:
        def phase_meta(self, v):
            return {"label": v, "tone": "info"}

    ad = P.PytestAdapter.__new__(P.PytestAdapter)
    ad.spec = Spec()
    ad._procs = {}
    ad._finish("r1", code, {"counts": {"passed": 1, "failed": 1}, "failed_cases": []},
               str(tmp_path))
    assert seen["phase"] == expect, "exit %s 應為 %s" % (code, expect)


def test_真失敗要說明原因(tmp_path, monkeypatch):
    """`failed` 時要講得出「為什麼不是測試紅燈」，否則看的人會去查錯方向。"""
    P = _mod()
    seen = {}
    monkeypatch.setattr(P.rs, "read_status", lambda rid: {"phase": "running"})
    monkeypatch.setattr(P.rs, "run_dir", lambda rid: str(tmp_path))
    monkeypatch.setattr(P.rs, "update_status", lambda rid, **kw: seen.update(kw) or {})

    class Spec:
        def phase_meta(self, v):
            return {}
    ad = P.PytestAdapter.__new__(P.PytestAdapter)
    ad.spec, ad._procs = Spec(), {}
    ad._finish("r1", 3, {"counts": {}, "failed_cases": []}, str(tmp_path))
    assert "內部錯誤" in seen["summary"]["note"]


def test_stop_flag_在時判為stopped(tmp_path, monkeypatch):
    P = _mod()
    seen = {}
    io.open(os.path.join(str(tmp_path), "stop.flag"), "w").write("x")
    monkeypatch.setattr(P.rs, "read_status", lambda rid: {"phase": "running"})
    monkeypatch.setattr(P.rs, "run_dir", lambda rid: str(tmp_path))
    monkeypatch.setattr(P.rs, "update_status", lambda rid, **kw: seen.update(kw) or {})

    class Spec:
        def phase_meta(self, v):
            return {}
    ad = P.PytestAdapter.__new__(P.PytestAdapter)
    ad.spec, ad._procs = Spec(), {}
    ad._finish("r1", 1, {"counts": {}, "failed_cases": []}, str(tmp_path))
    assert seen["phase"] == "stopped", "使用者按了停止，就算 exit 1 也不是 completed"


# ─────────────────────────────── ① 進度只讀完整行

def test_只讀完整行_殘行留到下一輪(tmp_path):
    """子程序可能正寫到一半 —— 讀進半行會 JSON 解析失敗或漏事件。"""
    P = _mod()
    f = os.path.join(str(tmp_path), "p.jsonl")
    io.open(f, "w", encoding="utf-8").write(
        '{"event":"collected","total":3}\n{"event":"test","done":1')   # 第二行不完整
    off, evs = P._read_new(f, 0)
    assert [e["event"] for e in evs] == ["collected"]

    with io.open(f, "a", encoding="utf-8") as fh:      # 補完第二行
        fh.write(',"total":3,"counts":{}}\n')
    off2, evs2 = P._read_new(f, off)
    assert [e["event"] for e in evs2] == ["test"] and off2 > off


def test_壞掉的行不影響其他事件(tmp_path):
    P = _mod()
    f = os.path.join(str(tmp_path), "p.jsonl")
    io.open(f, "w", encoding="utf-8").write(
        '{"event":"a"}\n這不是 JSON\n{"event":"b"}\n')
    _, evs = P._read_new(f, 0)
    assert [e["event"] for e in evs] == ["a", "b"]


def test_檔案還不存在時不炸(tmp_path):
    P = _mod()
    assert P._read_new(os.path.join(str(tmp_path), "無"), 0) == (0, [])


# ─────────────────────────────── plugin 本身

def _plugin_src():
    return io.open(os.path.join(PLATFORM, "collect", "pytest_progress.py"),
                   encoding="utf-8").read()


def test_plugin只用stdlib且不碰run_store():
    """★ 陷阱①：plugin 在**另一個程序**，碰 `run_store` 就會與父程序互相蓋掉。

    ⚠️ 用 AST 檢查**實際的 import**，不要用字串搜尋 ——
      檔頭的說明本來就會提到 `run_store` 與 `core/jsonio.py`
      （2026-08-23：第一版就是這樣誤報的）。
    """
    import ast
    tree = ast.parse(_plugin_src())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    assert mods <= {"json", "os", "time", "__future__"},         "plugin 匯入了非 stdlib 或平台模組：%s" % (mods - {"json", "os", "time", "__future__"})


def test_plugin只做append不做讀改寫():
    """append 的單行寫入是原子的；read-modify-write 不是。

    同樣用 AST：找所有 `open(...)` 呼叫，mode 一律只能是 'a'。
    """
    import ast
    modes = []
    for node in ast.walk(ast.parse(_plugin_src())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
            m = node.args[1].value if len(node.args) > 1 else None
            m = m or next((k.value.value for k in node.keywords if k.arg == "mode"), "r")
            modes.append(m)
    assert modes and set(modes) == {"a"}, "plugin 有非 append 的檔案開啟：%s" % modes


# ─────────────────────────────── ③ allure 隔離

def test_argv一定覆蓋alluredir與掛進度plugin():
    """★ 陷阱③：`pyproject.toml` 的 addopts 無條件帶 `reports/allure-results`。"""
    src = io.open(os.path.join(PLATFORM, "adapters", "pytest_.py"),
                  encoding="utf-8").read()
    assert '"--alluredir", os.path.join(run_dir, "allure-results")' in src
    assert "collect.pytest_progress" in src
    assert '"--progress-out"' in src


def test_selection走argsfile不重複附加():
    """★ `selection` 的 emit 是 `argsfile`（`@檔案`）——
    adapter 再 append 一次 nodeid 會讓同一批案例跑兩遍。
    而且 `build_invocation` 沒給 `run_dir` 的話只會拿到預覽用佔位字串。"""
    src = io.open(os.path.join(PLATFORM, "adapters", "pytest_.py"),
                  encoding="utf-8").read()
    assert "run_dir=run_dir" in src, "build_invocation 沒給 run_dir → argsfile 寫不出來"
    assert "argv += list(req.selection)" not in src, "重複附加 selection"


# ─────────────────────────────── registry 接真

def test_ui_tests沒有真假切換旗標():
    """★ 這是**迴歸防線**，不是還在用的機制。

    `demo: true` 原本會強制走 `FakeAdapter`。2026-08-23 連同 demo 模式一起移除之後，
    這個鍵已經沒有任何作用 —— 留著這條測試是為了擋「有人照舊文件再加回來」，
    那會是一個**寫了卻不生效**的宣告（比沒寫更難查）。
    """
    d = json.load(io.open(os.path.join(PLATFORM, "registry", "ui_tests.tool.json"),
                          encoding="utf-8"))
    assert d.get("demo") is not True, "tool.json 又出現 demo 旗標 —— 那個機制已經不存在了"


def test_工廠會選到PytestAdapter():
    """⚠️ 工廠已無 demo 分支（2026-08-23 移除）—— 只依 `spec.kind` 挑實作。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import adapters as A

    class Spec:
        kind, live, demo = "pytest", False, False
    assert A.get_adapter(Spec()).kind == "pytest"

# ─────────────────────────────── 平台 phase 要從 starting 推進到 running

@pytest.mark.parametrize("adapter_name", ["CliAdapter", "PytestAdapter"])
def test_看到工具階段就把平台phase推到running(adapter_name, monkeypatch):
    """★ 迴歸：`manager.start()` 只設到 `starting`，先前**沒有人負責推到 `running`**。

    症狀：一輪跑 30 分鐘的壓測從頭到尾顯示「啟動中」，而儀表板的
    「執行中 N」是用 `phase` 算的（`ui/hero.js` 濾掉 completed/failed/stopped），
    所以連帶算不對。2026-08-23 實跑七星壓測、40 秒後 phase 仍是 starting 才看出來。

    ⚠️ 這裡驗**行為**不驗原始碼字串 —— 字串比對會中 docstring
    （本專案已經因此誤判過兩次）。
    """
    import adapters.cli as cli_mod
    import adapters.pytest_ as pt_mod
    cls = {"CliAdapter": cli_mod.CliAdapter, "PytestAdapter": pt_mod.PytestAdapter}[adapter_name]
    mod = cli_mod if adapter_name == "CliAdapter" else pt_mod

    state = {"phase": "starting"}
    monkeypatch.setattr(mod.rs, "read_status", lambda rid: dict(state))
    monkeypatch.setattr(mod.rs, "update_status", lambda rid, **kw: state.update(kw))

    class _Spec:
        raw = {}
        run = {}
        runtime = {}
        stop = {}
        def phase_meta(self, v):
            return {"value": v, "label": v, "tone": "info"}

    ad = cls.__new__(cls)
    ad.spec = _Spec()
    ad.ctx = {}
    ad._phase("r1", "betting")
    assert state["phase"] == "running", "第一次看到工具階段時沒有把 phase 推到 running"

    # 已經在 stopping 的不可被推回 running —— 那會蓋掉停止意圖
    state.update({"phase": "stopping"})
    ad._phase("r1", "draining")
    assert state["phase"] == "stopping"


# ─────────────────────────────── adapter 必須完整實作契約

@pytest.mark.parametrize("mod_name,cls_name", [
    ("adapters.cli", "CliAdapter"),
    ("adapters.pytest_", "PytestAdapter"),
])
def test_adapter必須自己實作契約的每個方法(mod_name, cls_name):
    """★ 迴歸：2026-08-23 改 `reports()` 時用「從這裡切到那裡」的字串取代，
    一併把 `run_command`／`health`／`_exe_of`／`_cwd_of`／`_parse_stdout`
    **五樣一起刪掉了**，而全套 423 條測試**照樣全綠** ——
    CliAdapter 的同步路徑當時零覆蓋。

    症狀要等真的按下「期數回收」才會出現：
    `ValueError: crux_perf 不支援同步命令` —— 那是 `ToolAdapter` 基底的錯誤訊息，
    表示子類根本沒有覆寫。

    這條測試檢查**方法確實定義在子類上**，而不是掉回基底的 raise。
    """
    import importlib
    from adapters.base import ToolAdapter
    cls = getattr(importlib.import_module(mod_name), cls_name)

    # ⛔ `run_command` 不列入 —— pytest 型工具本來就沒有 sync 命令，
    #    掉回基底那句明確的 ValueError 是正確行為。
    must_own = ["start", "stop", "status", "logs", "reports"]
    missing = [m for m in must_own
               if getattr(cls, m, None) is getattr(ToolAdapter, m, None)]
    assert not missing, (
        "%s 沒有自己實作：%s —— 會掉回 ToolAdapter 基底"
        "（基底不是 raise NotImplementedError 就是 raise ValueError，"
        "而那要等真的按下去才會發現）" % (cls_name, missing))


def test_健康檢查是基底提供的通用能力():
    """★ `health()` 原本只長在 `CliAdapter` 上，基底是 `{"ok": True, "checks": []}`
    —— pytest 型工具（`ui_tests`）的健康檢查頁**永遠綠燈、一項都不檢查**，
    同事 fresh clone 少裝 playwright 也看不出來。

    現在改由基底依 `runtime.requires` 統一實作，所以檢查「基底有沒有真的在檢查」。
    """
    import inspect
    from adapters.base import ToolAdapter
    src = inspect.getsource(ToolAdapter.health)
    body = src[src.index('"""', src.index('"""') + 3) + 3:]     # 去掉 docstring 再看
    assert "python_modules" in body, "基底的 health 沒有檢查 requires.python_modules"
    assert "external" in body, "基底的 health 沒有檢查 requires.external"
    assert "checks" in body


def test_cli同步命令走得通(tmp_path, monkeypatch):
    """CliAdapter 的 sync 路徑要真的組得出 argv 並跑得起來（用一支必定成功的假腳本）。"""
    import adapters.cli as cli_mod

    script = tmp_path / "echo_json.py"
    script.write_text('import json; print(json.dumps({"kind": "text", "text": "ok"}))',
                      encoding="utf-8")

    class _Spec:
        id = "t"
        raw = {}
        run = {}
        stop = {}
        runtime = {"executable": sys.executable, "cwd": "."}
        def phase_meta(self, v):
            return {"value": v, "label": v, "tone": "info"}

    cmd = {"id": "c", "mode": "sync", "argv": [str(script)],
           "result": {"kind": "text"}, "params": {"fields": []}}
    ad = cli_mod.CliAdapter(_Spec())
    r = ad.run_command(cmd, {})
    assert r["exit_code"] == 0, r
    assert (r.get("result") or {}).get("text") == "ok"


# ─────────────────────────────── stop 的兩種策略

def _fake_spec(stop_spec, run_dir_tpl):
    class _S:
        id = "t"
        raw = {"artifacts": {"run_dir": run_dir_tpl}}
        run = {}
        runtime = {}
        stop = stop_spec
        def phase_meta(self, v):
            return {"value": v, "label": v, "tone": "info"}
    return _S()


def test_flag策略要先寫stop_flag再等寬限(tmp_path, monkeypatch):
    """★ wbot 的 `stop.strategy = "flag"`：**先寫 `stop.flag` 讓 worker 優雅收尾**，
    逾時才強制終止。

    為什麼不能直接殺：wbot 的**孫程序握著 WebSocket** ——
    只 terminate 父程序，它們會留下來**繼續下注**（真金流）。
    而且優雅收尾才產得出報告。

    ⚠️ `stop.flag` 要寫進**引擎的** run 目錄（`core/run_status.py:stop_flag_path`
    就是這樣找的），不是平台的 run 目錄。
    """
    import adapters.cli as cli_mod

    engine_dir = tmp_path / "logs" / "runs" / "R1"
    engine_dir.mkdir(parents=True)
    spec = _fake_spec({"strategy": "flag", "flag_file": "stop.flag", "grace_seconds": 1},
                      str(tmp_path / "logs" / "runs" / "{run_id}").replace("\\", "/"))

    state = {"phase": "running"}
    monkeypatch.setattr(cli_mod.rs, "read_status", lambda rid: dict(state))
    monkeypatch.setattr(cli_mod.rs, "update_status", lambda rid, **kw: state.update(kw))
    monkeypatch.setattr(cli_mod.rs, "append_console", lambda rid, line: None)
    monkeypatch.setattr(cli_mod, "REPO_ROOT", "")

    killed = []
    monkeypatch.setattr(cli_mod, "_kill_tree", lambda pid, force=False: killed.append(pid))

    class _Proc:
        pid = 4242
        def __init__(self): self._n = 0
        def poll(self):
            self._n += 1
            return 0 if self._n > 1 else None      # 第二次輪詢時已自行結束

    ad = cli_mod.CliAdapter(spec)
    ad._procs["R1"] = _Proc()
    ad._engine_dirs["R1"] = str(engine_dir)
    ad.stop("R1", reason="測試")

    assert (engine_dir / "stop.flag").is_file(), "flag 策略沒有寫出 stop.flag"
    assert not killed, "worker 在寬限內自行結束了，不該再強制終止"
    assert state["phase"] == "stopping"


def test_flag策略逾時後仍要強制終止(tmp_path, monkeypatch):
    """寬限過了還沒收尾就一定要殺 —— 否則壓測會一直跑下去（真金流）。"""
    import adapters.cli as cli_mod

    engine_dir = tmp_path / "logs" / "runs" / "R2"
    engine_dir.mkdir(parents=True)
    spec = _fake_spec({"strategy": "flag", "flag_file": "stop.flag", "grace_seconds": 1},
                      str(tmp_path / "logs" / "runs" / "{run_id}").replace("\\", "/"))
    monkeypatch.setattr(cli_mod.rs, "read_status", lambda rid: {"phase": "running"})
    monkeypatch.setattr(cli_mod.rs, "update_status", lambda rid, **kw: None)
    monkeypatch.setattr(cli_mod.rs, "append_console", lambda rid, line: None)
    monkeypatch.setattr(cli_mod, "REPO_ROOT", "")
    killed = []
    monkeypatch.setattr(cli_mod, "_kill_tree", lambda pid, force=False: killed.append((pid, force)))

    class _Proc:
        pid = 777
        def poll(self): return None                # 永遠不結束

    ad = cli_mod.CliAdapter(spec)
    ad._procs["R2"] = _Proc()
    ad._engine_dirs["R2"] = str(engine_dir)
    ad.stop("R2", reason="測試")
    assert killed == [(777, True)], "寬限逾時後沒有強制殺整棵程序樹：%s" % killed


def test_tree策略直接殺不寫flag(tmp_path, monkeypatch):
    """CRUX／七星是 `tree` —— 不寫 flag，直接殺整棵樹。"""
    import adapters.cli as cli_mod

    engine_dir = tmp_path / "logs" / "runs" / "R3"
    engine_dir.mkdir(parents=True)
    spec = _fake_spec({"strategy": "tree", "grace_seconds": 15},
                      str(tmp_path / "logs" / "runs" / "{run_id}").replace("\\", "/"))
    monkeypatch.setattr(cli_mod.rs, "read_status", lambda rid: {"phase": "running"})
    monkeypatch.setattr(cli_mod.rs, "update_status", lambda rid, **kw: None)
    monkeypatch.setattr(cli_mod.rs, "append_console", lambda rid, line: None)
    monkeypatch.setattr(cli_mod, "REPO_ROOT", "")
    killed = []
    monkeypatch.setattr(cli_mod, "_kill_tree", lambda pid, force=False: killed.append(pid))

    class _Proc:
        pid = 55
        def poll(self): return None

    ad = cli_mod.CliAdapter(spec)
    ad._procs["R3"] = _Proc()
    ad._engine_dirs["R3"] = str(engine_dir)
    ad.stop("R3", reason="測試")
    assert killed == [55]
    assert not (engine_dir / "stop.flag").exists(), "tree 策略不該寫 stop.flag"


def test_找不到引擎run目錄時flag策略要退回強制終止(tmp_path, monkeypatch):
    """⚠️ wbot 沒有 `--run-id`，引擎 run 目錄靠**探測**——探測失敗時
    `stop.flag` 無處可寫。這時**必須退回強制終止**，
    不能因為寫不出 flag 就放著讓它繼續下注。"""
    import adapters.cli as cli_mod
    spec = _fake_spec({"strategy": "flag", "flag_file": "stop.flag", "grace_seconds": 1},
                      str(tmp_path / "logs" / "runs" / "{run_id}").replace("\\", "/"))
    monkeypatch.setattr(cli_mod.rs, "read_status", lambda rid: {"phase": "running"})
    monkeypatch.setattr(cli_mod.rs, "update_status", lambda rid, **kw: None)
    monkeypatch.setattr(cli_mod.rs, "append_console", lambda rid, line: None)
    monkeypatch.setattr(cli_mod, "REPO_ROOT", "")
    killed = []
    monkeypatch.setattr(cli_mod, "_kill_tree", lambda pid, force=False: killed.append(pid))

    class _Proc:
        pid = 99
        def poll(self): return None

    ad = cli_mod.CliAdapter(spec)
    ad._procs["R4"] = _Proc()
    ad._engine_dirs["R4"] = None            # 探測失敗
    ad.stop("R4", reason="測試")
    assert killed == [99], "探測不到引擎目錄時沒有退回強制終止 —— 壓測會繼續下注"


# ─────────────────────────────── 併發佔位一定要釋放

def test_每個adapter收尾都要呼叫on_finished():
    """★ 核心迴歸：`manager._acquire_slot()` 用 `ended_ts is None` 判斷「還在跑」，
    而 `ended_ts` **只在 `manager.on_finished()` 裡設**。

    先前全工作區只有 `adapters/fake.py` 呼叫它 —— 於是接真之後，
    **第一次跑完那支工具就再也啟動不了**（訊息還說「已有進行中的 run」），
    直到重啟平台。（當時只有已移除的 FakeAdapter 會呼叫，所以接真之前看不出來。）
    （2026-08-23 情境 B（用了一個月的同事）走查發現。）
    """
    import io as _io
    import os as _os
    adapters_dir = _os.path.join(ROOT, "tools", "test_platform", "adapters")
    bad = []
    for name in sorted(_os.listdir(adapters_dir)):
        if not name.endswith(".py") or name in ("__init__.py", "base.py", "argv.py"):
            continue
        src = _io.open(_os.path.join(adapters_dir, name), encoding="utf-8").read()
        # 只有「會開 run」的 adapter 需要釋放佔位
        if "def start(" not in src:
            continue
        if "on_finished" not in src:
            bad.append(name)
    assert not bad, (
        u"這些 adapter 開了 run 卻不釋放併發佔位 —— 跑完一次就再也啟動不了："
        u"%s" % "、".join(bad))


def test_on_finished真的會清掉佔位():
    """驗行為本身，不只驗有沒有呼叫。"""
    import sys as _sys
    PLATFORM = os.path.join(ROOT, "tools", "test_platform")
    if PLATFORM not in _sys.path:
        _sys.path.insert(0, PLATFORM)
    from runner import manager as M

    class _Rec:
        run_id = "probe_run"
        tool_id = "probe_tool"
        ended_ts = None
        adapter = None

    rec = _Rec()
    M._runs[rec.run_id] = rec
    try:
        assert rec.ended_ts is None
        M.on_finished(rec.run_id)
        assert rec.ended_ts is not None, u"on_finished 沒有設 ended_ts，佔位永遠不會釋放"
    finally:
        M._runs.pop(rec.run_id, None)
