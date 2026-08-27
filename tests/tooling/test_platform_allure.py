# -*- coding: utf-8 -*-
"""allure 的解析與產生（2026-08-23 範本端到端驗收第 ⑦ 步）。

要釘住的兩件事：

① **解析只能有一處。** 先前 `web_ui/api/knowledge.py`（npm 全域優先）與
   `adapters/base.py`（裸 `shutil.which`）各有一套 —— 同一個畫面上，
   儀表板健康列報 2.43.0、工具頁健康檢查報 2.7.0。
   而 **2.7.0 讀不動現代的 allure-results**，同事照著它產報告會拿到壞結果。
   `scripts/setup_test_env.ps1` 早就寫著要 npm 全域優先，平台這側漏了。

② ⛔ **`generate_allure` 不可以是 inert 欄位。**
   它宣告了、預設開、表單上看得到，`adapters/pytest_.py` 還有一個叫
   `generating_reports` 的階段 —— 但先前**沒有任何程式讀它**。
   使用者按下「產生 Allure 報告」什麼也不會發生，而且看不出來。
   這正是階段 G 花最多力氣防的那件事。

使用方式：`pytest tests/tooling/test_platform_allure.py -q`
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _p(*parts):
    return os.path.join(ROOT, *parts)


def _mod():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import allure_cli
    return allure_cli


# ─────────────────────────────── ① 解析只有一處

def test_解析器存在且可呼叫():
    A = _mod()
    exe = A.find_allure()
    assert exe is None or os.path.isfile(exe) or exe.endswith(".cmd")


def test_沒有人再自己寫一套allure解析():
    """★ 迴歸：兩套解析＝同一個畫面報出兩個版本。"""
    bad = []
    for rel in ("tools/test_platform/web_ui/api/knowledge.py",
                "tools/test_platform/adapters/base.py"):
        src = io.open(_p(*rel.split("/")), encoding="utf-8").read()
        if 'shutil.which("allure")' in src or "shutil.which('allure')" in src:
            bad.append(rel)
    assert not bad, (
        u"這些檔又自己找 allure 了 —— PATH 上的舊版（2.7.0）讀不動現代結果，"
        u"一律走 core.allure_cli.find_allure()：%s" % "、".join(bad))


def test_結果目錄不存在時給得出原因(tmp_path):
    A = _mod()
    ok, why = A.generate(str(tmp_path / "nope"), str(tmp_path / "out"))
    assert not ok and why, u"失敗時必須回一句人看得懂的原因"


def test_空的結果目錄不當成成功(tmp_path):
    A = _mod()
    res = tmp_path / "allure-results"
    res.mkdir()
    ok, why = A.generate(str(res), str(tmp_path / "out"))
    assert not ok and "一條都沒跑" in why


# ─────────────────────────────── ② 宣告的欄位要有人讀

def _fields(tool_id):
    spec = json.load(io.open(
        _p("tools", "test_platform", "registry", "%s.tool.json" % tool_id), encoding="utf-8"))
    for c in spec["commands"]:
        for f in (c.get("params") or {}).get("fields") or []:
            yield c["id"], f


def test_generate_allure欄位真的有人讀():
    """★ 核心迴歸：`emit: none` 的欄位**不會進命令列**，
    所以它唯一的意義就是「平台自己讀」。沒有人讀＝填了不生效。
    """
    keys = [f["key"] for _, f in _fields("ui_tests") if f["key"] == "generate_allure"]
    assert keys, u"ui_tests 不再宣告 generate_allure —— 若是刻意移除，請一併刪掉本測試"
    src = io.open(_p("tools", "test_platform", "adapters", "pytest_.py"),
                  encoding="utf-8").read()
    assert "generate_allure" in src, (
        u"generate_allure 宣告了卻沒有人讀 —— 使用者按下去什麼也不會發生")
    assert "allure_cli" in src, u"應該透過 core.allure_cli 產生報告"


def test_emit_none的欄位一律要有人讀():
    """把上一條推廣到所有工具：`emit: none` ＝ 平台自己處理，沒人處理就是假欄位。"""
    platform_src = ""
    for dirpath, dirnames, files in os.walk(PLATFORM):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "logs", "cache", "demo", "node_modules")]
        for f in files:
            if f.endswith((".py", ".js")):
                platform_src += io.open(os.path.join(dirpath, f), encoding="utf-8").read()

    orphan = []
    reg = _p("tools", "test_platform", "registry")
    for name in sorted(os.listdir(reg)):
        if not name.endswith(".tool.json"):
            continue
        spec = json.load(io.open(os.path.join(reg, name), encoding="utf-8"))
        for c in spec.get("commands") or []:
            for f in (c.get("params") or {}).get("fields") or []:
                if f.get("emit") != "none":
                    continue
                if f["key"] not in platform_src:
                    orphan.append("%s / %s / %s" % (name, c["id"], f["key"]))
    assert not orphan, (
        u"這些欄位宣告 emit:none（不進命令列），卻沒有任何平台程式讀它們 —— "
        u"表單上填得到、按下去不生效，而且看不出來：\n  " + "\n  ".join(orphan))


# ─────────────────────────────── ③ 宣告的 sync 命令要真的實作得出來

def test_每個sync命令的adapter都實作得出來():
    """★ 迴歸：`ui_tests` 宣告了 `rebuild_index`（mode: sync），
    但 `PytestAdapter` 沒有覆寫 `run_command()` —— 基底類別直接丟
    「不支援同步命令」。按鈕看得到、按下去必定失敗
    （2026-08-23 範本端到端驗收第 ⑧ 步）。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import load_registry
    from adapters.base import ToolAdapter
    from adapters import get_adapter

    reg = load_registry(force=True)
    bad = []
    for spec in reg.tools.values():
        syncs = [c for c in (spec.raw.get("commands") or [])
                 if c.get("mode") == "sync"]
        if not syncs:
            continue
        try:
            ad = get_adapter(spec)
        except Exception as e:                      # noqa: BLE001
            bad.append("%s：取不到 adapter（%s）" % (spec.id, e))
            continue
        if type(ad).run_command is ToolAdapter.run_command:
            bad.append("%s 宣告了 %d 個 sync 命令（%s），但 %s 沒有實作 run_command()"
                       % (spec.id, len(syncs), "、".join(c["id"] for c in syncs),
                          type(ad).__name__))
    assert not bad, "\n  ".join([u"這些按鈕按下去必定失敗："] + bad)
