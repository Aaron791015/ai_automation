# -*- coding: utf-8 -*-
"""壓測控制台 ↔ 平台 tool.json 的欄位對照（階段 G-0，2026-08-23）。

用途：使用者要求「**平台的設定介面需要與舊控制台一致**」。
      實查落差是 97 個控制項對 56 個宣告 —— **差額近半**。
      直接吸收會讓那些設定從介面上消失，而且**沒有人會發現**
      （跑得起來、只是某個參數用了預設值）。

      這組測試釘住三件事：
      ① **未歸屬（gap）必須為零** —— 每個控制項都要有人看過並決定它的歸屬
      ② **豁免要寫得出理由** —— 寫不出理由的，表示它其實該對到一個 field
      ③ **憑證不得進 tool.json 的 fields** —— 密碼走 config.local.json（階段 F）

⚠️ 這組測試是**產品層**的（三支壓測工具是彩票專屬），不匯出給同事；
   但**做法**要寫進 `CONTRIB_TOOL.md`，因為同事吸收自己的工具時會遇到同一件事。

使用方式：`pytest tests/tooling/test_perf_field_parity.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import perf_field_parity as P  # noqa: E402


@pytest.fixture(scope="module")
def rep():
    return P.report()


def _has_consoles():
    return all(os.path.isdir(os.path.join(ROOT, rel))
               for _, rel in P.CONSOLES.values())


# ─────────────────────────────── ① 未歸屬必須為零

def test_每個控制項都有歸屬(rep):
    """★ `gap` ＝ **還沒有人看過它**。
    留著 gap 就代表吸收之後會有設定悄悄消失。"""
    if not _has_consoles():
        pytest.skip("找不到壓測控制台（範本不帶產品專屬工具）")
    gaps = {t: d["gaps"] for t, d in rep.items() if d["gaps"]}
    assert not gaps, "還有控制項沒歸屬：%s" % gaps


def test_待補清單應該已經清空(rep):
    """G-1 做完之後 `todo` 要歸零 —— 非零代表還有設定沒補進 tool.json。"""
    if not _has_consoles():
        pytest.skip("找不到壓測控制台")
    todo = {t: d["todo"] for t, d in rep.items() if d["todo"]}
    assert not todo, "還有真設定沒補進 tool.json：%s" % todo


# ─────────────────────────────── ② 豁免要寫得出理由

def test_每條豁免都有理由():
    for kind in ("display", "replaced"):
        for key, why in P.EXEMPT[kind].items():
            assert why and len(why) >= 6, "%s.%s 沒寫理由" % (kind, key)


def test_豁免不重疊():
    assert not (set(P.EXEMPT["display"]) & set(P.EXEMPT["replaced"]))


def test_豁免清單不得有已經對到的鍵(rep):
    """對到 field 的鍵還留在豁免清單裡 ＝ 清單過期，會遮掉真正的問題。"""
    if not _has_consoles():
        pytest.skip("找不到壓測控制台")
    exempt = set(P.EXEMPT["display"]) | set(P.EXEMPT["replaced"])
    for tool_id, d in rep.items():
        matched = {r["key"] for r in d["rows"] if r["kind"] == "field"}
        stale = exempt & matched
        assert not stale, "%s 的豁免清單有已經對到的鍵：%s" % (tool_id, stale)


def test_啟發式不得復辟():
    """★ 迴歸：第一版用子字串比對（key 含 'cancel' 就算顯示用），
    把 `cancel_after_bet_count`（退碼設定）判成顯示用 —— 那是真設定。
    豁免一律**逐鍵明列**。"""
    assert isinstance(P.EXEMPT["display"], dict)
    assert isinstance(P.EXEMPT["replaced"], dict)
    assert "cancel_after_bet_count" not in P.EXEMPT["display"]


# ─────────────────────────────── ③ 憑證不進 fields

def test_憑證欄位一律走config_local而非tool_json():
    """⛔ 密碼放進 tool.json ＝ 進版控。階段 F 已把憑證收到 config.local.json。"""
    for tool_id in P.CONSOLES:
        p = os.path.join(ROOT, "tools", "test_platform", "registry",
                         "%s.tool.json" % tool_id)
        if not os.path.isfile(p):
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        for c in d.get("commands", []):
            for f in ((c.get("params") or {}).get("fields") or []):
                k = f["key"].lower()
                if any(w in k for w in ("password", "pwd", "secret", "token", "cookie")):
                    assert f.get("type") == "secret", \
                        "%s 的 %s 看起來是憑證，卻不是 secret 型別" % (tool_id, f["key"])


def test_密碼類控制項都被歸到已由平台取代():
    """帳密應該走憑證設定頁，不該出現在壓測參數表單上。"""
    for key in ("modal-db-password", "modal-director-pwd", "chatroom_login_pwd"):
        assert key in P.EXEMPT["replaced"], "%s 沒被歸到 config.local.json" % key


# ─────────────────────────────── 帶入的欄位要誠實

def test_尚未接上引擎的欄位要明講():
    """★ `emit` 無法從 HTML 推導 —— 沒對應規則的欄位一律 `emit: none`
    並在 help 註明「尚未接上引擎參數」。
    寧可讓人看到「這欄還沒接」，也不要組出一個引擎不認得的旗標。"""
    n = 0
    for tool_id in P.CONSOLES:
        p = os.path.join(ROOT, "tools", "test_platform", "registry",
                         "%s.tool.json" % tool_id)
        if not os.path.isfile(p):
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        for c in d.get("commands", []):
            for f in ((c.get("params") or {}).get("fields") or []):
                if f.get("emit") == "none" and "尚未接上" in (f.get("help") or ""):
                    n += 1
                elif f.get("emit") == "none" and not f.get("help"):
                    pytest.fail("%s 的 %s 是 emit:none 卻沒說明原因" % (tool_id, f["key"]))
    assert n >= 0        # 只要沒有「emit:none 又不說明」就算通過


def test_三支壓測都是直跑引擎而非HTTP代理():
    """★ 依 2026-08-23 裁示**跳過 M4（HttpAdapter）直接吸收** ——
    決策 5「吸收控制台不吸收引擎」：引擎一行不動，只是不再需要那三個 Flask 控制台。"""
    for tool_id in P.CONSOLES:
        p = os.path.join(ROOT, "tools", "test_platform", "registry",
                         "%s.tool.json" % tool_id)
        if not os.path.isfile(p):
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        assert d.get("kind") == "cli", "%s 不是 cli（HTTP 代理已依裁示跳過）" % tool_id
        for c in d.get("commands", []):
            argv = " ".join(c.get("argv") or [])
            assert "http" not in argv.lower(), "%s 的 %s 看起來在打 HTTP" % (tool_id, c["id"])


# ─────────────────────────────── ④ 宣告的旗標，引擎一定要認得
#
# ★ 這是 G-1b 的核心機檢。tool.json 把 `arg` 打錯一個字（`--interval-start`
#   寫成 `--interval_start`），平台照樣組得出命令列、UI 也完全正常 ——
#   要等真的跑下去才會炸，而壓測跑下去是**真金流下注**。
#
# 用 AST 解析引擎的 argparse（多行 `add_argument(` 用 grep 會漏掉，
#   實際就漏過 `--cancel-after` 與 `--wallet-sync-mode` 兩個）。

# 每支工具的**根目錄**（命令的 argv 相對於它）
TOOL_ROOTS = {
    "crux_perf": "tools/CRUX_Performance",
    "qixing_perf": "tools/qixing_Performance",
    "wbot_perf": "tools/wbot_Performance",
}


def _script_of(tool_root, argv):
    """把命令的 argv 解析成它實際執行的 .py 檔。

    ⚠️ 一支 tool.json 有**多個命令、各指向不同腳本**
    （`bet_load` → runner.locust_main、`period_advance` → scripts.manage_period…）。
    第一版拿整支工具對單一引擎比，把 `--hours`／`--smoke-bet` 誤判成錯誤旗標
    —— 它們只是屬於別的命令。旗標必須**逐命令**比對。
    """
    argv = list(argv or [])
    for i, a in enumerate(argv):
        if a == "-m" and i + 1 < len(argv):                 # -m runner.locust_main
            return os.path.join(tool_root, *argv[i + 1].split(".")) + ".py"
        if a.endswith(".py"):                                # scripts/run_perf.py
            return os.path.join(tool_root, a)
    return None


def _script_flags(abs_path):
    """腳本的 argparse 接受的旗標集合（含短旗標）。

    用 AST —— 多行 `add_argument(` 用 grep 會漏，實際就漏過
    `--cancel-after` 與 `--wallet-sync-mode` 兩個。
    """
    import ast
    if not abs_path or not os.path.isfile(abs_path):
        return None
    tree = ast.parse(io.open(abs_path, encoding="utf-8").read())
    flags = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for a in node.args:
                try:
                    v = ast.literal_eval(a)
                except Exception:
                    continue
                if isinstance(v, str) and v.startswith("-"):
                    flags.add(v)
    return flags


def _commands(tool_id):
    """[(命令 id, 腳本絕對路徑, [(field_key, arg, emit)])]"""
    p = os.path.join(ROOT, "tools", "test_platform", "registry",
                     "%s.tool.json" % tool_id)
    if not os.path.isfile(p):
        return []
    d = json.load(io.open(p, encoding="utf-8"))
    root = os.path.join(ROOT, TOOL_ROOTS[tool_id])
    out = []
    for c in d.get("commands", []):
        fields = [(f["key"], f["arg"], f.get("emit"))
                  for f in ((c.get("params") or {}).get("fields") or [])
                  if f.get("arg")]
        out.append((c["id"], _script_of(root, c.get("argv")), fields))
    return out


# ─────────────────────────────── 4 宣告的旗標，腳本一定要認得
#
# ★ 這是 G-1b 的核心機檢。tool.json 把 `arg` 打錯一個字（`--interval-start`
#   寫成 `--interval_start`），平台照樣組得出命令列、UI 也完全正常 ——
#   要等真的跑下去才會炸，而壓測跑下去是**真金流下注**。

@pytest.mark.parametrize("tool_id", sorted(TOOL_ROOTS))
def test_宣告的旗標腳本都認得(tool_id):
    cmds = _commands(tool_id)
    if not cmds:
        pytest.skip("找不到 tool.json（範本不帶產品專屬工具）")
    checked = 0
    for cmd_id, script, fields in cmds:
        flags = _script_flags(script)
        if flags is None:
            continue
        checked += 1
        bad = [(k, a) for k, a, _ in fields if a not in flags]
        assert not bad, (
            "%s／%s 宣告了腳本不認得的旗標：%s；%s 實際接受：%s"
            % (tool_id, cmd_id, bad, os.path.basename(script), sorted(flags)))
    assert checked, "%s 的命令一個都沒解析到腳本" % tool_id


@pytest.mark.parametrize("tool_id", sorted(TOOL_ROOTS))
def test_布林欄位的旗標語義不得相反(tool_id):
    """`flag_when_false` 配的一定是腳本的 `--no-xxx`；`flag_when_true` 配的一定不是。

    配反了語義整個相反，而**兩種都跑得起來**（旗標存在、腳本收得到），
    只是行為相反 —— 壓測會照著相反的設定真的下注。"""
    cmds = _commands(tool_id)
    if not cmds:
        pytest.skip("找不到 tool.json")
    for cmd_id, _script, fields in cmds:
        for k, a, emit in fields:
            if emit == "flag_when_false":
                assert a.startswith("--no-"),                     "%s／%s 的 %s 用 flag_when_false 卻配了 %s（不是否定旗標）"                     % (tool_id, cmd_id, k, a)
            elif emit == "flag_when_true":
                assert not a.startswith("--no-"),                     "%s／%s 的 %s 用 flag_when_true 卻配了否定旗標 %s（語義相反）"                     % (tool_id, cmd_id, k, a)


@pytest.mark.parametrize("tool_id", sorted(TOOL_ROOTS))
def test_不得對到引擎的內部環境變數(tool_id):
    """⛔ `WBOT_RUN_PARAMS_JSON`／`API_RUN_PROFILE_JSON`／`CRUX_PROFILE_JSON`
    是各工具 `run_manager` **自己 spawn 子程序時設的內部變數**，不是對外開口。

    平台直接塞會**繞過 `resolve_params()`／`RunProfile` 的驗證** —— 組出來的
    參數組合未必是系統真的能產生的，跑出來的數據也就不能拿來當結論
    （與 CLAUDE.md §5 只留 `DrawTime` 一個 DB 寫入口是同一個道理）。"""
    p = os.path.join(ROOT, "tools", "test_platform", "registry",
                     "%s.tool.json" % tool_id)
    if not os.path.isfile(p):
        pytest.skip("找不到 tool.json")
    d = json.load(io.open(p, encoding="utf-8"))
    banned = {"WBOT_RUN_PARAMS_JSON", "API_RUN_PROFILE_JSON", "CRUX_PROFILE_JSON"}
    for c in d.get("commands", []):
        for f in ((c.get("params") or {}).get("fields") or []):
            assert f.get("env") not in banned,                 "%s 的 %s 對到了引擎的內部變數 %s" % (tool_id, f["key"], f.get("env"))


def test_沒接上的欄位要寫出確切原因():
    """★ `emit: none` 留著沒關係，但**不能只寫「尚未接上」** ——
    那句話讓人以為是 tool.json 還沒填，實際要動的是**引擎**（它沒開 CLI）。
    差別決定了下一個人該去改哪個檔。"""
    for tool_id in TOOL_ROOTS:
        p = os.path.join(ROOT, "tools", "test_platform", "registry",
                         "%s.tool.json" % tool_id)
        if not os.path.isfile(p):
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        for c in d.get("commands", []):
            for f in ((c.get("params") or {}).get("fields") or []):
                if f.get("emit") != "none":
                    continue
                h = f.get("help") or ""
                assert h, "%s 的 %s 是 emit:none 卻沒說明" % (tool_id, f["key"])
                if "尚未接上引擎參數" in h:
                    pytest.fail(
                        "%s 的 %s 只寫了含糊的「尚未接上引擎參數」——"
                        "要寫明是引擎沒開 CLI 還是 tool.json 沒填"
                        % (tool_id, f["key"]))


# ─────────────────────────────── 5 「命令未吸收」不可被當成待補欄位

def test_未吸收命令的控制項不得掛到別的命令():
    """★ 迴歸：G-1 用腳本把盤點出的欄位一律補到**主命令**，
    於是控制台「OpenAPI 壓測」頁的 8 個設定被塞進了 `bet_load`（會員下注壓測）。

    兩者是完全不同的進入點（`locust_main` vs `locust_openapi_harness`）——
    掛錯命令**比沒有更糟**：使用者會在表單上看到 8 個填了不會生效的欄位，
    而且沒有任何跡象顯示它沒生效。這正是欄位對照要防的事。
    """
    p = os.path.join(ROOT, "tools", "test_platform", "registry", "crux_perf.tool.json")
    if not os.path.isfile(p):
        pytest.skip("找不到 crux_perf.tool.json")
    d = json.load(io.open(p, encoding="utf-8"))
    for c in d.get("commands", []):
        stray = [f["key"] for f in ((c.get("params") or {}).get("fields") or [])
                 if f["key"] in P.EXEMPT.get("not_absorbed", {})]
        assert not stray, ("命令「%s」掛了屬於未吸收命令的欄位：%s" % (c["id"], stray))


def test_每條未吸收都寫得出理由():
    for key, why in P.EXEMPT.get("not_absorbed", {}).items():
        assert why and len(why) >= 20, "%s 的未吸收理由太短，看不出要去改哪裡" % key
        assert "進入點" in why or "命令" in why, "%s 的理由沒說明它屬於哪個命令" % key


def test_未吸收與其他歸屬不重疊():
    na = set(P.EXEMPT.get("not_absorbed", {}))
    assert not (na & set(P.EXEMPT["display"]))
    assert not (na & set(P.EXEMPT["replaced"]))
    for todo in P.TODO_FIELDS.values():
        assert not (na & set(todo)), "同一個鍵同時被列為未吸收與待補"


# ─────────────────────────────── 6 同一命令不得有重複／互斥的旗標

@pytest.mark.parametrize("tool_id", sorted(TOOL_ROOTS))
def test_同一命令不得有兩個欄位共用同一個旗標(tool_id):
    """★ 迴歸：G-1 用腳本補欄位時以 **key** 去重，但控制台的 id（`master_count`）
    與 tool.json 既有的 key（`masters`）**是同一個設定的兩種叫法** ——
    key 不同，去重完全沒攔到，結果三支工具共補出 **16 對重複**。

    後果一層比一層嚴重：
      ① 表單上兩個同義欄位，使用者不知道填哪個
      ② 兩個都填 → argv 拿到**兩次同一個旗標**，值可能互相矛盾
      ③ 最糟：`--wallet-check` 與 `--no-wallet-check` 兩個都送，
         引擎直接以「不可同時指定」退出（locust_main.py 有這個檢查）
    """
    import collections as _c
    p = os.path.join(ROOT, "tools", "test_platform", "registry", "%s.tool.json" % tool_id)
    if not os.path.isfile(p):
        pytest.skip("找不到 tool.json")
    d = json.load(io.open(p, encoding="utf-8"))
    for c in d.get("commands", []):
        by = _c.defaultdict(list)
        for f in ((c.get("params") or {}).get("fields") or []):
            k = f.get("arg") or f.get("env")
            if k:
                by[k].append(f["key"])
        dup = {k: v for k, v in by.items() if len(v) > 1}
        assert not dup, "%s／%s 有欄位共用同一個旗標：%s" % (tool_id, c["id"], dup)

        # ± 旗標對：--wallet-check 與 --no-wallet-check 同時出現
        for a in list(by):
            if a.startswith("--") and not a.startswith("--no-"):
                na = "--no-" + a[2:]
                assert na not in by, (
                    "%s／%s 同時宣告了 %s（%s）與 %s（%s）—— 那是同一個設定的正反面，"
                    "兩個都送出去引擎會拒絕執行"
                    % (tool_id, c["id"], a, by[a], na, by[na]))


def test_別名表不得指向不存在的欄位():
    """ALIAS 的右邊必須是 tool.json 裡**真的有**的 key，否則盤點會把控制項
    判成「已對到」而實際上沒有 —— 比沒有別名表更糟。"""
    for tool_id, alias in P.ALIAS.items():
        p = os.path.join(ROOT, "tools", "test_platform", "registry", "%s.tool.json" % tool_id)
        if not os.path.isfile(p):
            continue
        keys = set(P.tool_fields(tool_id))
        bad = {k: v for k, v in alias.items() if v not in keys}
        assert not bad, "%s 的別名指向不存在的欄位：%s" % (tool_id, bad)


# ─────────────────────────────── 7 「填了不生效」要盤得出來

def test_填了不生效的欄位有被獨立盤出來(rep):
    """★ 「欄位存在」不等於「設定會生效」。

    `emit: none` 的欄位在表單上看得到、填得下去，但**組不進命令列也不進環境變數**。
    這是「設定悄悄消失」的另一種形態，而且**更難發現** ——
    從「介面上不見了」變成「介面上有、按下去沒作用」。

    這條測試不要求 inert 為零（wbot 有 9 個是引擎 CLI 真的沒開口），
    只要求**盤得出來**，不會被「已對到」蓋掉。
    """
    if not _has_consoles():
        pytest.skip("找不到壓測控制台")
    for tool_id, d in rep.items():
        assert "inert" in d, "%s 的盤點沒有 inert 欄位" % tool_id
        for key in d["inert"]:
            assert key not in [r["key"] for r in d["rows"] if r["kind"] == "field"], \
                "%s 的 %s 同時被算成「已對到」與「填了不生效」" % (tool_id, key)


def test_已接真的工具不得有填了不生效的欄位(rep):
    """⭐ 判準：**一支工具移除 demo／設 live 之前，inert 必須為零**
    （或每個 inert 都在 `_接真前置` 裡寫明原因）。

    否則使用者在已接真的工具上填了設定卻不生效，而且沒有任何跡象。
    """
    if not _has_consoles():
        pytest.skip("找不到壓測控制台")
    for tool_id, d in rep.items():
        p = os.path.join(ROOT, "tools", "test_platform", "registry", "%s.tool.json" % tool_id)
        if not os.path.isfile(p):
            continue
        spec = json.load(io.open(p, encoding="utf-8"))
        if not spec.get("live"):
            continue                      # 還在 demo 的不受此限
        pre = " ".join(spec.get("_接真前置") or [])
        unexplained = [k for k in d["inert"] if k not in pre]
        assert not unexplained, (
            "%s 已接真（live=true）卻有填了不生效的欄位，且 _接真前置 沒說明：%s"
            % (tool_id, unexplained))


def test_命令列輸出不會因新增歸屬而崩(capsys):
    """★ 迴歸：新增 `inert` 歸屬時漏更新 `main()` 的圖示字典，
    `--json` 沒事、但預設輸出直接 `KeyError: 'inert'`。

    盤點工具自己崩掉 ＝ 沒有人會去跑它，而它是唯一擋住「設定悄悄消失」的東西。
    """
    rc = P.main([])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    # ⚠️ 第三種合法結局：**這個工作區沒有接壓測工具**（範本就是這樣）。
    #    先前只認前兩種，於是乾淨匯出的範本跑起來是紅的（2026-08-23）。
    assert ("全部有歸屬" in out or "沒有歸屬" in out
            or "沒有可盤點的壓測控制台" in out), out[-300:]
