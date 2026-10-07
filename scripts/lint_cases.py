# -*- coding: utf-8 -*-
"""檢查 UI 測試案例有沒有寫出「**步驟**」與「**判準**」。

用途：`ui-test` skill 階段 2 要求每條案例都要看得出「做了什麼」與「憑什麼判 PASS」——
      這一支就是那條規範的守門人。⛔ 靠自律的規範必然漂移（CLAUDE.md §6 已記過同型教訓：
      「規則已寫在 skill 裡，但那是格式說明、不是會被執行的檢查」）。

使用方式：
    python scripts/lint_cases.py                    # 全部產品
    python scripts/lint_cases.py --product xzh      # 只看一個產品（見下方「--product 怎麼解析」）
    python scripts/lint_cases.py --all              # 連既有豁免的也列出來（想逐條補時用）
前置條件：無（純靜態剖析，不執行任何案例）。

--product 怎麼解析（2026-10-07，修 T2「給不存在的目錄回 0 項」的漏檢）
    參數可以是 `config/products.json` 裡該產品的 **id／label／docs_dir／tests_dir／skill／別名**
    （不分大小寫，例：`新綜合`、`xzh` 都指向 `tests/xzh`），或 `tests/` 底下實際的目錄名。
    ⛔ **解析不到、或解析到的測試目錄不存在 → 印錯誤訊息並回傳 exit code 2**，不可以回「待修 0 項」：
       0 項代表「檢查過、沒問題」，而這種情況其實是「什麼都沒檢查」，兩者對人看起來一模一樣。
    摘要最後一行另外印出「檢查範圍：N 個案例檔、M 條案例」—— 看到 0 個檔就知道不是真的通過。

檢查項目
    C1  這條案例沒有任何 `allure.step` —— allure 報告與測試助手的案例詳情
        都只看得到函式名，**看不出執行過程**。
    C2  這條案例有 `assert` 卻沒有任何 `allure.attach` —— 綠燈看不出驗了什麼、
        紅燈看不出是系統錯還是案例錯（CLAUDE.md §5「案例須留驗證過程與佐證」）。

    兩項都會往下追 helper —— 把 step／attach 收在 `_verify()` 這種輔助函式裡是正當寫法，
    不該被判成沒寫。追法（深度固定，不會無限追下去）：

      案例本體
        └ 同檔 helper（一層）
            └ `tools/` 底下專案模組的函式（一層；本體＋它在同模組呼叫的 helper 一層）

    · **同檔 helper**：案例（或它呼叫的同檔 helper）呼叫的、同一個檔案裡的函式，追一層。
    · **共用模組（2026-10-07 起，修 T3「共用模組裡的步驟被判成沒寫」的誤報）**：案例檔 import 了
      `tools/` 底下的專案模組（`from xzh_qa.x import y`、`import xzh_qa.x`、`import xzh_qa.x as m`、
      `from xzh_qa import x`；pythonpath 是 `tools`，見 `pyproject.toml`；函式內的 import 也算），
      就往該模組的函式追：函式本體，加上它在**同一個模組**裡呼叫的 helper 再追一層。
      例：案例 → `_run_chain_variant()`（同檔 helper）→ `xzh_qa.odds_gap_chain_winner.run_chain_winner()`
      （函式本體寫 `allure.step`）→ 判定「有寫」。
    · ⚠️ 只追 **`tools/` 內的本機模組** —— 標準庫、第三方套件、`tools/` 以外的檔案一律不追；
      共用模組再 import 別的共用模組也**不再往下追**（那已經離案例太遠，報告上看不出這條案例的步驟了）；
      相對匯入（`from .x import y`）、`from x import *`、類別方法（`obj.method()`）、
      `xzh_qa/__init__.py` 轉出口的名字都不解析。
    · 判定來源是**原始碼字面**，不是執行結果 —— 模組函式裡的 `allure.step` 在實跑的 allure 報告看得到，
      但 test_platform 的靜態案例瀏覽器（`pytest_case_export.py`）只追同檔 helper，
      看不到共用模組裡的步驟；要讓平台案例詳情也顯示，仍要把步驟寫進案例的「平台案例：…步驟」說明。

★ 既有案例不追溯（2026-08-28 使用者裁示）
    每個產品的測試目錄放一份 `case_steps_baseline.json`，列出**規範上路前**就存在、
    暫時豁免的案例。名單**只減不增**：
      · 補好一條就從名單刪掉一條（`tests/tooling/test_lint_cases.py` 釘住它不會變長）
      · ⛔ 沒有「把新案例加進名單」的指令 —— 那等於把規範關掉
    名單放在產品的測試目錄裡（而不是 `scripts/`），這樣**匯出範本時不會跟著走** ——
    同事的案例一條都不豁免，本來就該如此。

⚠️ 檢查範圍刻意排除 `tests/tooling/` 與 `**/perf/`：
   前者是腳本自己的單元測試、後者是壓測工具的單元測試，都不是 UI 案例。
"""
import argparse
import ast
import io
import json
import os
import re
import sys

# ⚠️ Windows 主控台預設 cp950，summary 那行的 ⛔ 印下去會 UnicodeEncodeError 直接崩潰退出
#    （碼2，前面的掃描結果反而看不到）——跟 scripts/ 其餘腳本（next_todo_id.py 等）同一個
#    既有毛病，同一套修法：能轉 utf-8 就轉，轉不了（沒有 reconfigure）就算了不擋執行。
#    stderr 也一起轉：產品解析失敗的錯誤訊息走 stderr，一樣有中文。
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and _stream.encoding and _stream.encoding.lower().replace("-", "") != "utf8":
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
TOOLS = os.path.join(ROOT, "tools")          # pythonpath 的 `tools`；共用模組只在這底下找
PRODUCTS_JSON = os.path.join(ROOT, "config", "products.json")
BASELINE_NAME = "case_steps_baseline.json"
SKIP_PARTS = ("tooling", "perf", "__pycache__", ".pytest_cache")

# 追 helper 的深度（固定常數，不可變成「追到底」）：
LOCAL_HOPS = 1         # 同檔 helper：案例 → helper
MODULE_HOPS = 1        # 共用模組：→ `tools/` 模組的函式（整條追蹤最多一次）
MODULE_LOCAL_HOPS = 1  # 進了共用模組之後，函式在**同模組**再追的 helper 層數

CODES = {
    "C1": u"沒有 allure.step —— 看不出執行步驟",
    "C2": u"有 assert 卻沒有 allure.attach —— 看不出判準的實際值 vs 期望值",
}


def _rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


class ProductError(Exception):
    """`--product` 的參數解析不到／目錄不存在 —— 呼叫端要印訊息並回非零，不可當成「0 項」。"""


def product_dirs():
    """`tests/` 下的產品目錄（排除 tooling 等非案例目錄）。"""
    if not os.path.isdir(TESTS):
        return []
    out = []
    for name in sorted(os.listdir(TESTS)):
        p = os.path.join(TESTS, name)
        if os.path.isdir(p) and name not in SKIP_PARTS:
            out.append(p)
    return out


def _registered_products():
    """`config/products.json` 的產品清單；讀不到就回空（退回「只認實際目錄名」）。"""
    try:
        data = json.load(io.open(PRODUCTS_JSON, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("products") if isinstance(data, dict) else None
    return [p for p in (items or []) if isinstance(p, dict)]


def _product_names(p):
    """這個產品的所有稱呼（小寫）：id／label／docs_dir／tests_dir／skill／aliases。"""
    names = [p.get(k) for k in ("id", "label", "docs_dir", "tests_dir", "skill")]
    names += list(p.get("aliases") or [])
    return {str(x).strip().lower() for x in names if x}


def _product_tests_dir(p):
    """該產品登記的測試目錄名（跟 `export_template` 同一個取法：tests_dir，沒有就用 skill）。"""
    return p.get("tests_dir") or p.get("skill")


def resolve_product(name):
    """把 `--product` 的參數解析成 `tests/<目錄>` 的絕對路徑；解析不到就拋 `ProductError`。

    ⛔ 不可以回 None／空清單讓呼叫端當成「沒有案例」—— 那就是 T2 的漏檢。
    """
    key = (name or u"").strip().lower()
    if not key:
        raise ProductError(u"--product 不可以是空字串")
    dirs = {os.path.basename(d).lower(): d for d in product_dirs()}
    registered_missing = []
    for p in _registered_products():
        if key not in _product_names(p):
            continue
        td = _product_tests_dir(p)
        if td and td.lower() in dirs:
            return dirs[td.lower()]
        registered_missing.append((p.get("id") or p.get("label") or key, td))
    if key in dirs:                       # 沒登記、但 tests/ 底下真的有這個目錄（舊行為）
        return dirs[key]
    if key in SKIP_PARTS:
        raise ProductError(
            u"「%s」不是案例目錄：tests/tooling 是腳本自己的單元測試、**/perf 是壓測工具的單元測試，"
            u"本工具刻意不檢查它們" % name)
    if registered_missing:
        pid, td = registered_missing[0]
        raise ProductError(
            u"產品「%s」已登記在 config/products.json，但它的測試目錄 %s 不存在"
            u"（還沒有任何案例，或 tests_dir 欄位與實際目錄名不符）；tests/ 底下實際有：%s"
            % (pid, u"tests/%s" % td if td else u"（沒填 tests_dir／skill）",
               u"、".join(sorted(dirs)) or u"（無）"))
    known = []
    for p in _registered_products():
        alias = u"／".join(a for a in (p.get("aliases") or []) if a)
        known.append(u"%s%s" % (p.get("id") or p.get("label"), u"（%s）" % alias if alias else u""))
    raise ProductError(
        u"找不到產品「%s」。已登記的產品：%s；tests/ 底下實際的目錄：%s"
        % (name, u"、".join(known) or u"（無）", u"、".join(sorted(dirs)) or u"（無）"))


def case_files(base):
    """base 底下所有 UI 案例檔（`test_*.py`），跳過 perf／快取目錄。"""
    out = []
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP_PARTS]
        for f in sorted(files):
            if f.startswith("test_") and f.endswith(".py"):
                out.append(os.path.join(d, f))
    return out


# ── 剖析：一份原始碼 → 函式表、匯入表、取原文 ─────────────────────

_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


def _dotted(func):
    """呼叫的對象寫成名字鏈：`f(...)`→('f',)、`a.b.c(...)`→('a','b','c')；其他寫法（`x()()`、`obj[0]()`）回 None。"""
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return tuple(reversed(parts))
    return None


class _Info(object):
    """一份 Python 原始碼的剖析結果（案例檔或 `tools/` 模組都用這個）。

    ⚠️ 取節點原文**不用** `ast.get_source_segment`：它每呼叫一次就把**整份原始碼逐字元重切一遍**
       （純 Python 迴圈）—— 實測 400KB 的 `test_system_setting.py` 光掃這一個檔就 100 秒，
       一條案例要呼叫十幾次。這裡改成只切一次、節點原文與 call 清單各算一次就快取。
    """

    def __init__(self, src, all_helpers=False):
        self.tree = ast.parse(src)                 # SyntaxError 由呼叫端處理
        self.lines = _LINE_RE.findall(src)
        self.helpers, self.cases, self.aliases = {}, [], {}
        self._seg, self._calls = {}, {}
        # helper ＝ 這個檔裡所有**不是案例**的函式（含類別裡的）；案例 ＝ `test_` 開頭的。
        # （`ast.walk` 是廣度優先，頂層函式一定排在巢狀／類別內的同名函式前面，setdefault 取到頂層那個。）
        for n in ast.walk(self.tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if n.name.startswith("test_") and not all_helpers:
                    self.cases.append(n)
                else:
                    self.helpers.setdefault(n.name, n)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname:
                        self.aliases[a.asname] = a.name            # import a.b.c as m → m = a.b.c
                    else:
                        head = a.name.split(".")[0]                # import a.b.c → 綁的是 a
                        self.aliases[head] = head
            elif isinstance(n, ast.ImportFrom):
                if n.level or not n.module:                        # 相對匯入不解析
                    continue
                for a in n.names:
                    if a.name != "*":                              # from a.b import c as d → d = a.b.c
                        self.aliases[a.asname or a.name] = n.module + "." + a.name

    def _text(self, n):
        """對應 `ast.get_source_segment(src, n)`（不含裝飾器）。"""
        if n.end_lineno is None or n.end_col_offset is None:
            return ""
        first, last = n.lineno - 1, n.end_lineno - 1
        if first == last:
            return self.lines[first].encode()[n.col_offset:n.end_col_offset].decode()
        mid = self.lines[first + 1:last]
        head = self.lines[first].encode()[n.col_offset:].decode()
        tail = self.lines[last].encode()[:n.end_col_offset].decode()
        return "".join([head] + mid + [tail])

    def seg(self, n):
        # ⚠️ 要含**裝飾器** —— `ast.get_source_segment` 從 `def` 那一行開始，
        #    而 `@allure.step("登入")` 是 allure 的正規寫法之一，
        #    漏掉會把寫得很好的案例判成沒寫步驟。
        got = self._seg.get(id(n))
        if got is None:
            deco = "".join(self._text(d) for d in getattr(n, "decorator_list", []))
            got = self._seg[id(n)] = deco + self._text(n)
        return got

    def calls(self, n):
        """這個函式呼叫了哪些名字鏈（`_verify(...)`→('_verify',)、`m.run(...)`→('m','run')），依出現順序、去重。"""
        got = self._calls.get(id(n))
        if got is None:
            got = []
            for c in ast.walk(n):
                if isinstance(c, ast.Call):
                    d = _dotted(c.func)
                    if d is not None and d not in got:
                        got.append(d)
            self._calls[id(n)] = got
        return got


# `tools/` 模組的剖析快取：key＝絕對路徑，值＝((mtime_ns, size), _Info 或 None)；檔案一改就重剖。
_MODULES = {}


def _module_file(parts):
    """`['xzh_qa','odds_gap_chain_winner']` → `tools/xzh_qa/odds_gap_chain_winner.py`（沒有就 None）。

    只在 `TOOLS` 底下找 —— 標準庫與第三方套件不在這裡，自然不會被追。
    """
    if not parts or not all(p.isidentifier() for p in parts):
        return None
    base = os.path.join(TOOLS, *parts)
    for cand in (base + ".py", os.path.join(base, "__init__.py")):
        if os.path.isfile(cand):
            return cand
    return None


def _load_module(path):
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
        hit = _MODULES.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            info = _Info(io.open(path, encoding="utf-8-sig").read(), all_helpers=True)
        except (SyntaxError, ValueError, UnicodeDecodeError):
            info = None                    # ⛔ 共用模組寫壞不可以讓整批檢查炸掉
        _MODULES[path] = (stamp, info)
        return info
    except OSError:
        return None


def _resolve_module_call(call, info):
    """案例檔裡的 `call`（名字鏈）若指向 `tools/` 模組的函式，回 (模組 _Info, 函式節點)；否則 None。"""
    base = info.aliases.get(call[0])
    if base is None:
        return None
    full = base.split(".") + list(call[1:])        # 還原成完整的點分名稱
    if len(full) < 2:
        return None
    path = _module_file(full[:-1])                 # 最後一段是函式名，前面才是模組
    mod = _load_module(path) if path else None
    fn = mod.helpers.get(full[-1]) if mod else None
    return (mod, fn) if fn is not None else None


def _has(fn, info, needle, local_left, module_left):
    """`fn` 的本體有沒有 needle；沒有就依剩餘額度往 helper／共用模組函式找。

    額度只減不增（進共用模組時 `local_left` 重設為 `MODULE_LOCAL_HOPS`，但 `module_left` 會歸零），
    所以遞迴一定停：函式互相呼叫、自己呼叫自己都不會無限追下去。
    """
    if needle in info.seg(fn):
        return True
    for call in info.calls(fn):
        if len(call) == 1 and call[0] in info.helpers:      # 同檔 helper（遮蔽同名的 import）
            h = info.helpers[call[0]]
            if local_left > 0 and _has(h, info, needle, local_left - 1, module_left):
                return True
            continue
        if module_left > 0:
            hit = _resolve_module_call(call, info)
            if hit and _has(hit[1], hit[0], needle, MODULE_LOCAL_HOPS, module_left - 1):
                return True
    return False


def _analyze(path, src=None):
    """回傳 ([(nodeid, code)], 案例數)；nodeid 是 `相對路徑::函式名`。"""
    src = src if src is not None else io.open(path, encoding="utf-8").read()
    try:
        info = _Info(src)
    except SyntaxError:
        return [], 0
    rel, out = _rel(path), []
    for n in info.cases:
        nodeid = "%s::%s" % (rel, n.name)
        if not _has(n, info, "allure.step", LOCAL_HOPS, MODULE_HOPS):
            out.append((nodeid, "C1"))
        if "assert " in info.seg(n) and not _has(n, info, "allure.attach", LOCAL_HOPS, MODULE_HOPS):
            out.append((nodeid, "C2"))
    return out, len(info.cases)


def analyze(path, src=None):
    """回傳 [(nodeid, code)]；nodeid 是 `相對路徑::函式名`。"""
    return _analyze(path, src)[0]


def baseline_path(base):
    return os.path.join(base, BASELINE_NAME)


def load_baseline(base):
    """回傳豁免的 nodeid 集合（檔案不存在＝一條都不豁免）。"""
    p = baseline_path(base)
    if not os.path.exists(p):
        return set()
    try:
        got = json.load(io.open(p, encoding="utf-8"))
    except ValueError:
        return set()
    return set(got.get("exempt") or [])


def scan_with_stats(product=None):
    """回傳 (待修 findings, 已豁免 findings, 檢查了幾個檔, 檢查了幾條案例)。

    `product` 給了就先 `resolve_product`（解析不到拋 `ProductError`）；沒給＝全部產品。
    """
    bases = [resolve_product(product)] if product else product_dirs()
    todo, waived, n_files, n_cases = [], [], 0, 0
    for base in bases:
        exempt = load_baseline(base)
        for f in case_files(base):
            found, count = _analyze(f)
            n_files += 1
            n_cases += count
            for nodeid, code in found:
                (waived if nodeid in exempt else todo).append((nodeid, code))
    return todo, waived, n_files, n_cases


def scan(product=None):
    """回傳 (待修 findings, 已豁免 findings)。"""
    return scan_with_stats(product)[:2]


def stale_baseline():
    """名單裡**該刪掉**的條目，回傳 (名單路徑, nodeid, 理由)。

    兩種：
      · `檔案不存在` —— 案例被刪或改名了
      · `已經合格了` —— 有人把它補好了，⭐ **名單就該跟著變短**
        （沒有這一項的話，名單只會愈留愈舊，「只減不增」變成「只是不增」）

    ⚠️ 兩者都**只提醒、不讓 lint 變紅** —— 把「你改好了一條案例」變成紅燈
       會讓人不想改。真正要擋的是「名單變長」，那由
       `tests/tooling/test_lint_cases.py` 的上限守著。
    """
    out = []
    for base in product_dirs():
        exempt = load_baseline(base)
        if not exempt:
            continue
        found = set()
        for f in case_files(base):
            found.update(nodeid for nodeid, _c in analyze(f))
        for nodeid in sorted(exempt):
            rel = nodeid.split("::")[0]
            if not os.path.exists(os.path.join(ROOT, rel)):
                out.append((_rel(baseline_path(base)), nodeid, u"檔案不存在"))
            elif nodeid not in found:
                out.append((_rel(baseline_path(base)), nodeid, u"已經合格了"))
    return out


def _init_baseline(base):
    """一次性：把**現況**寫成豁免名單。⛔ 已存在就拒絕覆寫。"""
    p = baseline_path(base)
    if os.path.exists(p):
        print(u"  已存在，拒絕覆寫（名單只減不增）：%s" % _rel(p))
        return False
    ids = sorted({nodeid for f in case_files(base) for nodeid, _ in analyze(f)})
    io.open(p, "w", encoding="utf-8", newline="\n").write(json.dumps({
        "_comment": (u"規範上路前就存在、暫時豁免的案例（見 scripts/lint_cases.py 檔頭）。"
                     u"只減不增：補好一條就刪一條。"),
        "since": "2026-08-28",
        "exempt": ids,
    }, ensure_ascii=False, indent=2) + "\n")
    print(u"  已建立 %s（%d 條）" % (_rel(p), len(ids)))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--product",
                    help=u"只檢查一個產品：產品 id／中文名／別名／tests 目錄名都可以，如 新綜合、xzh"
                         u"（對照 config/products.json）；解析不到會報錯並回傳非零")
    ap.add_argument("--all", action="store_true", help=u"連已豁免的也列出來")
    ap.add_argument("--init-baseline", action="store_true",
                    help=u"一次性：把現況寫成豁免名單（已存在則拒絕）")
    args = ap.parse_args(argv)

    try:
        if args.init_baseline:
            bases = [resolve_product(args.product)] if args.product else product_dirs()
            for base in bases:
                _init_baseline(base)
            return 0
        todo, waived, n_files, n_cases = scan_with_stats(args.product)
    except ProductError as e:
        # ⛔ 不可以退回「待修 0 項、exit 0」—— 沒檢查跟檢查過沒問題，對看輸出的人是同一個畫面。
        sys.stderr.write(u"⛔ %s\n" % e)
        return 2

    for nodeid, code in sorted(todo):
        print(u"[%s] %s —— %s" % (code, nodeid, CODES[code]))
    if args.all:
        for nodeid, code in sorted(waived):
            print(u"[%s] %s （已豁免）" % (code, nodeid))
    for path, nodeid, why in stale_baseline():
        print(u"[C0] %s 裡的 %s：%s —— 請從名單刪掉" % (path, nodeid, why))

    print(u"")
    # ⚠️ 項數與案例數要分開講 —— 一條案例可能同時缺 step 與 attach，
    #    只印項數會讓人以為名單有 104 條（實際是 103 條案例）。
    print(u"待修 %d 項（%d 條案例）；既有豁免 %d 項（%d 條案例，只減不增）"
          % (len(todo), len({n for n, _c in todo}),
             len(waived), len({n for n, _c in waived})))
    print(u"檢查範圍：%d 個案例檔、%d 條案例（%s）"
          % (n_files, n_cases, args.product or u"全部產品"))
    if not n_files:
        print(u"⚠️ 沒有找到任何 test_*.py 案例檔 —— 這不代表通過，而是沒有東西可檢查。")
    if todo:
        print(u"⛔ 新案例必須寫出步驟與判準 —— 做法見 `.claude/skills/ui-test/SKILL.md`"
              u"「步驟與判準」節。")
    return 1 if todo else 0


if __name__ == "__main__":
    sys.exit(main())
