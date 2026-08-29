# -*- coding: utf-8 -*-
"""欄位「宣告了卻不會出現在畫面上」的三個洞（2026-08-24 使用者回報第 5 項）。

## 為什麼要獨立一支

使用者的回報是「舊控制台的設定，有部分沒有在平台出現」。
而 `test_perf_field_parity.py` 那 30 條**全綠** —— 因為它只比對
「tool.json 有沒有宣告」，不管「表單畫不畫得出來」。

實查成因：`form.js` 的渲染是

    for (g of groups) fields.filter(f => (f.group || '_') === g.id)

宣告了 `groups` 之後，**沒填 `group` 的欄位落在 `_`、不屬於任何一組 → 一格都不畫**。
三支壓測工具合計 **19 個欄位**這樣消失，而表單看起來完全正常。

★ 這一類缺陷的共同形狀是「**宣告存在、效果不存在**」，而且**不會有任何錯誤訊息**。
  本檔就是釘住這一類：

  ① 有 groups 就每個欄位都要有 group（不然靜默不渲染）
  ② select 類一定要有 options 或 options_from（不然是個空下拉）
  ③ 同一個命令不可以有兩個欄位指向同一個引擎旗標（後者靜默蓋掉前者）
  ④ secret 欄位不可以出現在給人看的 `human` 清單裡（確認卡會印明碼）

使用方式：`pytest tests/tooling/test_platform_form_fields.py -q`
"""
import glob
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")
TOOLS = sorted(glob.glob(os.path.join(PLATFORM, "registry", "*.tool.json")))


def _cmds():
    """(檔名, 命令 id, params) 逐一展開。"""
    for p in TOOLS:
        d = json.load(io.open(p, encoding="utf-8"))
        for c in d.get("commands", []):
            yield os.path.basename(p), c.get("id", "?"), (c.get("params") or {})


# ── ① 有 groups 就每個欄位都要有 group ────────────────────
def test_宣告了分組就不可以有欄位沒分組():
    """⛔ 沒填 group 的欄位**不會被渲染**，而且表單看起來完全正常。

    2026-08-24 實查：crux 5、七星 4、wbot 10，共 19 個欄位這樣消失。
    """
    bad = []
    for name, cid, params in _cmds():
        if not params.get("groups"):
            continue
        bad += ["%s.%s.%s" % (name, cid, f.get("key"))
                for f in params.get("fields") or [] if not f.get("group")]
    assert not bad, "這些欄位不會出現在畫面上：%s" % bad


def test_group_必須在groups裡():
    ids = {}
    bad = []
    for name, cid, params in _cmds():
        gs = {g.get("id") for g in params.get("groups") or []}
        if not gs:
            continue
        ids[(name, cid)] = gs
        bad += ["%s.%s.%s → %s" % (name, cid, f.get("key"), f.get("group"))
                for f in params.get("fields") or []
                if f.get("group") and f["group"] not in gs]
    assert not bad, "group 打錯，欄位會靜默不顯示：%s" % bad


def test_registry驗證會擋下沒分組的欄位():
    """★ 光靠上面的靜態掃描不夠 —— 同事自己接工具時也要當場被擋下來。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import validate_spec
    errs = validate_spec({
        "id": "x", "name": "X", "kind": "cli", "product": "crux",
        "commands": [{"id": "c", "mode": "run", "argv": ["-m", "x"], "params": {
            "groups": [{"id": "a", "label": "A"}],
            "fields": [{"key": "k", "type": "text", "label": "K"}],
        }}],
    }, "x.tool.json")
    assert any("沒有 group" in e["error"] for e in errs), errs


# ── ② 選單不可以是空的 ────────────────────────────────────
def test_下拉選單一定要有選項來源():
    """空下拉在畫面上是一個**打不開的控件** —— 比缺欄位更難懂。"""
    bad = []
    for name, cid, params in _cmds():
        for f in params.get("fields") or []:
            if f.get("type") not in ("select", "multiselect", "file_select"):
                continue
            if not f.get("options") and not f.get("options_from"):
                bad.append("%s.%s.%s" % (name, cid, f.get("key")))
    assert not bad, "這些下拉沒有選項：%s" % bad


def test_files來源不得逃出工具目錄():
    """`options_from: {source:"files"}` 是 GET 端點，任何人都打得到。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from web_ui.api.registry_api import _file_options

    class _Spec:
        runtime = {"cwd": "tools/CRUX_Performance"}

    # ⭐ 逃逸檢查**無條件跑** —— 那是這條測試存在的理由，與工作區裡有什麼無關
    assert _file_options(_Spec(), {"dir": "../..", "glob": "*"}) == []
    assert _file_options(_Spec(), {"dir": "config/../..", "glob": "*"}) == []
    assert _file_options(_Spec(), {"dir": "config", "glob": "../*"}) == []

    # 正向斷言要有真的檔案可取 —— 而 `tools/CRUX_Performance` 是**產品專屬**路徑
    # （不隨範本匯出）。範本裡沒有它時跳過這一段，不是缺陷。
    if not os.path.isdir(os.path.join(ROOT, "tools", "CRUX_Performance", "config", "api_profiles")):
        pytest.skip("這個工作區沒有 CRUX 壓測工具（範本的正常狀態）")
    got = _file_options(_Spec(), {"dir": "config/api_profiles", "glob": "*.json", "strip_ext": True})
    assert got and all(not o["value"].endswith(".json") for o in got)


# ── ③ 不可以有兩個欄位搶同一個旗標 ────────────────────────
def test_同一個命令不可有兩個欄位指向同一個旗標():
    """⛔ 兩個都填就組出 `-d 10 --delay 15`，argparse 取後者 ——
    畫面上兩個控件給不同的值，而使用者無從得知哪個算數。

    2026-08-24 實際抓到一組：七星的 `director_delay_mins`（`--delay`）
    與 `delay`（`-d`）是同一個 argparse dest。
    """
    bad = []
    for name, cid, params in _cmds():
        seen = {}
        for f in params.get("fields") or []:
            for slot in (f.get("arg"), f.get("env")):
                if not slot:
                    continue
                if slot in seen:
                    bad.append("%s.%s：%s 與 %s 都送 %s" % (name, cid, seen[slot], f["key"], slot))
                seen[slot] = f["key"]
    assert not bad, bad


# ── ④ secret 不可以出現在給人看的清單 ─────────────────────
def test_確認卡不可印出密碼():
    """★ `preview()` 的 `human` 是確認卡直接顯示的東西。

    先前只遮 `redacted` —— 因為當時沒有任何 run 命令宣告 secret 欄位。
    2026-08-24 加上 `crux_perf.api_load` 的登入密碼，確認框就會印明碼。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import load_registry
    from adapters.argv import preview
    reg = load_registry(force=True)
    spec = reg.tools.get("crux_perf")
    if not spec or not spec.command("api_load"):
        pytest.skip("範本不帶產品專屬的壓測工具")
    pv = preview(spec, spec.command("api_load"),
                 {"api_profile": "x", "api_password": "hunter2"})
    blob = json.dumps(pv, ensure_ascii=False)
    assert "hunter2" not in blob, "密碼漏進了確認卡：%s" % blob


# ── ⑤ 宣告了動態選項，就要真的回得出選項 ───────────────
def test_每個動態選項來源都回得出東西():
    """★ 2026-08-24 走查發現：`form.js` 的 `reloadDynamic` 原本要求
    `options_from.kind === 'api'`，而 tool.json **一支都沒有這樣寫**
    （寫的都是宣告式的 `{source: "products"|"files"}`）——
    於是所有動態下拉在畫面上都是空的，`#/tool/setup` 的「接一個產品」
    「收尾體檢」因為 required 過不了而**整個命令按不下去**。

    後端端點一直是好的，只是前端從來沒去問。這條測試釘的是後端那半
    （來源 key 打錯、dir/glob 寫錯會被抓到）；前端那半由
    `test_前端會去問選項端點` 釘住。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import load_registry
    from web_ui.api.registry_api import _file_options
    reg = load_registry(force=True)
    has_products = bool([p for p in reg.products if not p.get("virtual")])
    empty = []
    for tid, spec in reg.tools.items():
        for c in spec.commands:
            for f in ((c.get("params") or {}).get("fields") or []):
                src = f.get("options_from") or {}
                if src.get("source") == "files":
                    if not _file_options(spec, src):
                        empty.append("%s.%s.%s（dir=%s glob=%s）"
                                     % (tid, c["id"], f["key"], src.get("dir"), src.get("glob")))
                elif src.get("source") == "products":
                    # ⚠️ 一個產品都沒接時，這種下拉**本來就該是空的** ——
                    #    那是範本的初始狀態（同事拿到手的第一個畫面），不是缺陷。
                    #    這條測試要抓的是「來源 key 打錯、dir/glob 寫錯」。
                    if not has_products:
                        continue
                elif src and not src.get("url"):
                    empty.append("%s.%s.%s：不認得的 source「%s」"
                                 % (tid, c["id"], f["key"], src.get("source")))
    assert not empty, "這些動態下拉會是空的：%s" % empty


def test_前端會去問選項端點():
    """⛔ 迴歸：不可以再回到「只有 `kind: 'api'` 才去問」。

    這條測試看的是**原始碼**而不是行為 —— 前端沒有測試框架，
    而這個缺陷的形狀正好是「一行 if 就整批失效、畫面看起來完全正常」。
    """
    p = os.path.join(PLATFORM, "web_ui", "static", "js", "ui", "form.js")
    src = io.open(p, encoding="utf-8").read()
    i = src.index("async function reloadDynamic")
    # ⚠️ 視窗長度需 > 函式實際長度，否則函式尾端的檢查點會被切掉而誤判成「不見了」
    #    （2026-08-27 `appendInto`／`opt-reason` 兩段邏輯插進函式中段，
    #    把 `if (touched) recalc()` 推到第 1955 字元，1800 切太短漏踩過一次）。
    body = src[i:i + 2400]
    # ⚠️ 比對「真的會執行的那個形狀」，不是這串字 ——
    #    上面的註解本身就引用了舊寫法（那是刻意留的說明），單純 grep 會誤判。
    assert "!== 'api') continue" not in body, "又把動態選項鎖回 kind==='api' 了"
    assert "/options/" in body, "reloadDynamic 沒有組出工具的選項端點"
    assert "if (touched) recalc()" in body, "填完選項要重算，否則 required 的紅字不會消"


# ── ⑥ 文件端點的白名單邊界 ────────────────────────────
def test_文件端點放行README但不放行整個根目錄():
    """★ 2026-08-24：總覽空狀態的「看 README 的完整上手五步」指向
    `#/doc?path=README.md`，而該路由當時**不存在**、端點也**不放行根目錄的檔案**
    —— 新同事第一個畫面上第一顆按鈕就是壞的。

    ⛔ 修法是**逐檔明列**，不是把根目錄當白名單根 —— 後者等於放行整個 repo
       （含 `config/config.local.json` 的鄰居們）。
    """
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from web_ui.api.docs_api import resolve_doc
    assert resolve_doc("README.md"), "README.md 應該讀得到"
    # ⚠️ **只放行真的被連到的那一份**。`CLAUDE.md` 刻意不放行 ——
    #    `test_platform_flows.py` 拿它當「白名單外」的代表，連同兩個 `../` 逃逸變體
    #    一起釘住這個口的安全底線；放進來那三條斷言就失去意義了。
    assert resolve_doc("CLAUDE.md") is None
    assert resolve_doc("requirements.txt") is None      # 非 .md
    assert resolve_doc("../README.md") is None          # 逃逸
    assert resolve_doc("config/README.md") is None      # 根目錄不是白名單根
