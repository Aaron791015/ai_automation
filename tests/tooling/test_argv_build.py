# -*- coding: utf-8 -*-
"""`tools/test_platform/adapters/argv.py` 的 golden test。

用途：registry 的 `emit`（11 種）先前只被驗證合法性、沒有任何消費者；argv.py 是唯一消費點，
      而它**同時**餵三個地方（真的 subprocess、確認框預覽、run 參數卡）——
      組錯的後果是「畫面顯示的命令列」與「實際跑的命令列」不一致，那比不顯示更糟。
      故本檔直接拿五支真實 tool.json 的欄位做黃金比對，registry 改壞了這裡就會紅。
前置條件：
    · 不執行任何 subprocess，純組裝。
    · ⚠️ **匯入一律延後到 fixture 裡，不可寫在模組層**。
      `tools/test_platform/` 有一個頂層 `core` 套件，而 `tools/wbot_Performance/` 也有一個；
      模組層 import 會在**收集階段**就把 `sys.modules["core"]` 釘成前者，
      於是 `tests/wbot/perf/` 的 `from core.time_utils import …` 全部 ModuleNotFoundError
      —— 12 個檔收集失敗、整包索引（622 條）當場歸零。
      收集階段結束後才 import 就沒事，因為那時 wbot 的模組都已經匯入完畢。
      （2026-08-21 本檔第一版就踩到，`pytest tests/tooling` 單跑還是綠的，
        要跑整包 collect 才看得出來。）
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _platform():
    """延後匯入（理由見檔頭）。回 (build_invocation, preview, load_registry)。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from adapters.argv import build_invocation, preview
    from core.registry import load_registry
    return build_invocation, preview, load_registry


def build_invocation(*a, **kw):
    return _platform()[0](*a, **kw)


def preview(*a, **kw):
    return _platform()[1](*a, **kw)


GOLDEN_TOOLS = ["crux_bet_demo", "crux_perf", "qixing_perf", "wbot_perf", "ui_tests"]


def _registry_or_skip():
    """registry 空的就跳過整組黃金測試。

    ⚠️ 「registry 沒有註冊任何工具」是**範本的合法狀態**（`export_template.py`
      不會夾帶原型產品的 `.tool.json`），不是失敗 —— 同事剛匯出時這裡本來就沒東西。
      本檔驗的是「本 repo 的 registry 有沒有被改壞」，沒有 registry 就沒有可驗的對象。
    """
    r = _platform()[2](force=True)
    missing = [t for t in GOLDEN_TOOLS if t not in getattr(r, "tools", {})]
    if missing:
        # ⚠️ 判準是「**這幾支黃金工具在不在**」，不是「registry 空不空」——
        #    匯出的範本會帶 `ui_tests`（標準內建工具），registry 不是空的，
        #    但產品專屬的四支不在，這組黃金比對就沒有比對對象
        #    （2026-08-23：把 setup／ui_tests 納入匯出後，原本的空值判斷就失效了）。
        pytest.skip("缺少黃金工具 %s（匯出的範本不帶產品專屬 tool.json）" % missing)
    return r


@pytest.fixture(scope="module")
def reg():
    return _registry_or_skip()


def opts(inv):
    """去掉執行檔與 command.argv 這段固定前綴，只留欄位組出來的部分。"""
    return inv["argv"][1:]


# ---------------------------------------------------------------- 各種 emit
def test_opt與flag_when_true(reg):
    """emit=opt 出「旗標 值」兩個 token；flag_when_true 只在真值時出旗標本身"""
    spec = reg.tool("crux_bet_demo")
    cmd = spec.command("pb_decode")
    inv = build_invocation(spec, cmd, {"k": "abc", "short": True})
    assert opts(inv) == ["pb_codec.py", "--k", "abc", "--short"]
    inv = build_invocation(spec, cmd, {"k": "abc", "short": False})
    assert "--short" not in opts(inv)


def test_repeat把清單攤成重複旗標(reg):
    """emit=repeat：`--code a --code b`，不是 `--code a b`

    pb_codec.py 的 --code 是 action=extend，兩種寫法都吃得下；
    但平台一律出重複形式，因為值裡本來就可能含空白。
    """
    spec = reg.tool("crux_bet_demo")
    inv = build_invocation(spec, spec.command("pb_decode"), {"code": "A112 FSM123"})
    assert opts(inv) == ["pb_codec.py", "--code", "A112", "--code", "FSM123"]


def test_emit_none不進命令列但仍列在人話清單(reg):
    """generate_allure 是平台自己消化的旗標，不能傳給 pytest —— 但人要看得到它是開是關"""
    spec = reg.tool("ui_tests")
    cmd = spec.command("run_cases")
    inv = build_invocation(spec, cmd, {"selection": ["tests/a.py::test_x"], "generate_allure": True,
                                       "remark": "重驗 CRUX-934"})
    assert "--generate-allure" not in inv["argv"]
    not_emitted = {h["label"] for h in inv["human"] if h["emitted"] is False}
    assert "產生 Allure 報告" in not_emitted and "本次備註" in not_emitted


def test_emit_env進環境變數而非命令列(reg):
    spec = reg.tool("ui_tests")
    cmd = spec.command("run_cases")
    inv = build_invocation(spec, cmd, {"selection": ["tests/crux/a.py::t"], "crux_env": "qat",
                                       "crux_director": "director3"})
    assert inv["env"]["CRUX_QA_ENV"] == "qat"
    assert inv["env"]["CRUX_QA_DIRECTOR"] == "director3"
    assert "qat" not in inv["argv"] and "director3" not in inv["argv"]
    # registry 宣告的固定環境變數要一併帶上
    assert inv["env"]["PYTHONUTF8"] == "1"


def test_argsfile未給run_dir時不寫檔(reg):
    """預覽路徑不可以有副作用 —— 確認框只是要給人看，不該在硬碟上留東西"""
    spec = reg.tool("ui_tests")
    cmd = spec.command("run_cases")
    inv = build_invocation(spec, cmd, {"selection": ["tests/a.py::t1", "tests/a.py::t2"]})
    af = inv["argsfiles"][0]
    assert af["lines"] == ["tests/a.py::t1", "tests/a.py::t2"]
    assert not os.path.exists(af["path"])
    assert "2 行" in af["path"]


def test_argsfile給了run_dir就真的寫出來(reg, tmp_path):
    spec = reg.tool("ui_tests")
    cmd = spec.command("run_cases")
    inv = build_invocation(spec, cmd, {"selection": ["tests/a.py::t1"]}, run_dir=str(tmp_path))
    path = inv["argsfiles"][0]["path"]
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        assert f.read() == "tests/a.py::t1"


# ---------------------------------------------------------------- 人話與遮罩
def test_人話用中文label與選項label(reg):
    """看的人要讀到「總監3」而不是「director3」、「是」而不是 True"""
    spec = reg.tool("ui_tests")
    inv = build_invocation(spec, spec.command("run_cases"),
                           {"selection": ["a::t"], "crux_director": "director3", "headed": True})
    hm = {h["label"]: h["value"] for h in inv["human"]}
    assert hm["CRUX 總監站台"] == "總監3"
    assert hm["顯示瀏覽器視窗"] == "是"
    assert hm["要執行的案例"] == "已勾選 1 條"


def test_secret一律遮罩且不進命令列(reg):
    """schema 允許 secret 欄位（現有五支還沒有），一加上去就必須是遮罩的

    registry 已強制 secret 只能 emit=env，所以這裡驗的是「env 那份的遮罩」。
    """
    spec = reg.tool("crux_bet_demo")
    cmd = dict(spec.command("pb_decode"))
    cmd["params"] = {"fields": [
        {"key": "token", "type": "secret", "label": "登入 token", "emit": "env", "env": "QA_TOKEN"},
        {"key": "k", "type": "text", "label": "k", "arg": "--k"},
    ]}
    inv = build_invocation(spec, cmd, {"token": "s3cr3t", "k": "abc"})
    assert inv["env"]["QA_TOKEN"] == "s3cr3t"                    # 真的要傳給子行程
    assert inv["redacted"]["env"]["QA_TOKEN"] == "***"           # 給人看的那份不能有
    assert "s3cr3t" not in inv["redacted"]["cmdline"]


def test_preview不含平台自己的編碼環境變數(reg):
    """PYTHONUTF8 這種是平台一律加的，列在確認框只是雜訊"""
    spec = reg.tool("crux_bet_demo")
    pv = preview(spec, spec.command("parse_text"), {"text": "198组六4"})
    assert "PYTHONUTF8" not in pv["env"]
    assert pv["cwd"] == "tools/CRUX_bet_demo_all"


def test_空值不出現在命令列(reg):
    """`--out ''` 會被腳本當成「輸出到空檔名」，比不給還糟"""
    spec = reg.tool("crux_bet_demo")
    inv = build_invocation(spec, spec.command("parse_batch"), {"input_folder": "All", "out": ""})
    assert "--out" not in opts(inv)
    assert opts(inv) == ["parse.py", "--input-folder", "All"]


# ---------------------------------------------------------------- 與真實 spec 的一致性
@pytest.mark.parametrize("tool_id", GOLDEN_TOOLS)
def test_每支工具的每個命令都組得出argv(reg, tool_id):
    """欄位宣告了 emit 卻沒有對應規則時，argv.py 會放進 notes —— 這裡不允許有任何 notes"""
    spec = reg.tool(tool_id)
    for cmd in spec.commands:
        defaults = {f["key"]: f["default"] for f in (cmd.get("params") or {}).get("fields", [])
                    if f.get("default") not in (None, "")}
        inv = build_invocation(spec, cmd, defaults)
        assert inv["notes"] == [], f"{tool_id}.{cmd['id']}：{inv['notes']}"
        assert inv["argv"][1:len(cmd.get("argv") or []) + 1] == list(cmd.get("argv") or [])


def test_有arg沒宣告emit時的預設推定(reg):
    """布林 → flag_when_true；其餘 → opt。registry 大量欄位靠這個預設，改壞會全面錯位"""
    spec = reg.tool("crux_perf")
    cmd = dict(spec.command(spec.commands[0]["id"]))
    cmd["params"] = {"fields": [
        {"key": "b", "type": "boolean", "label": "布林", "arg": "--flag"},
        {"key": "n", "type": "number", "label": "數字", "arg": "--num"},
        {"key": "x", "type": "text", "label": "沒有 arg"},
    ]}
    inv = build_invocation(spec, cmd, {"b": True, "n": 5, "x": "忽略我"})
    tail = inv["argv"][1 + len(cmd.get("argv") or []):]
    assert tail == ["--flag", "--num", "5"]
