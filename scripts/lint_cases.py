# -*- coding: utf-8 -*-
"""檢查 UI 測試案例有沒有寫出「**步驟**」與「**判準**」。

用途：`ui-test` skill 階段 2 要求每條案例都要看得出「做了什麼」與「憑什麼判 PASS」——
      這一支就是那條規範的守門人。⛔ 靠自律的規範必然漂移（CLAUDE.md §6 已記過同型教訓：
      「規則已寫在 skill 裡，但那是格式說明、不是會被執行的檢查」）。

使用方式：
    python scripts/lint_cases.py                    # 全部產品
    python scripts/lint_cases.py --product CRUX     # 只看一個產品的目錄
    python scripts/lint_cases.py --all              # 連既有豁免的也列出來（想逐條補時用）
前置條件：無（純靜態剖析，不執行任何案例）。

檢查項目
    C1  這條案例沒有任何 `allure.step` —— allure 報告與測試助手的案例詳情
        都只看得到函式名，**看不出執行過程**。
    C2  這條案例有 `assert` 卻沒有任何 `allure.attach` —— 綠燈看不出驗了什麼、
        紅燈看不出是系統錯還是案例錯（CLAUDE.md §5「案例須留驗證過程與佐證」）。

    兩項都會往下追**同一個檔案裡的 helper**（一層）—— 把 attach 收在
    `_verify()` 這種輔助函式裡是正當寫法，不該被判成沒寫。

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
import sys

# ⚠️ Windows 主控台預設 cp950，summary 那行的 ⛔ 印下去會 UnicodeEncodeError 直接崩潰退出
#    （碼2，前面的掃描結果反而看不到）——跟 scripts/ 其餘腳本（next_todo_id.py 等）同一個
#    既有毛病，同一套修法：能轉 utf-8 就轉，轉不了（沒有 reconfigure）就算了不擋執行。
if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
BASELINE_NAME = "case_steps_baseline.json"
SKIP_PARTS = ("tooling", "perf", "__pycache__", ".pytest_cache")

CODES = {
    "C1": u"沒有 allure.step —— 看不出執行步驟",
    "C2": u"有 assert 卻沒有 allure.attach —— 看不出判準的實際值 vs 期望值",
}


def _rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


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


def case_files(base):
    """base 底下所有 UI 案例檔（`test_*.py`），跳過 perf／快取目錄。"""
    out = []
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP_PARTS]
        for f in sorted(files):
            if f.startswith("test_") and f.endswith(".py"):
                out.append(os.path.join(d, f))
    return out


def _calls(node):
    """這個函式呼叫了哪些**單純名字**的函式（`_verify(...)`，不含 `a.b()`）。"""
    got = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            got.add(n.func.id)
    return got


def analyze(path, src=None):
    """回傳 [(nodeid, code)]；nodeid 是 `相對路徑::函式名`。"""
    src = src if src is not None else io.open(path, encoding="utf-8").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    # helper ＝ 這個檔裡所有**不是案例**的函式（含類別裡的）；案例 ＝ `test_` 開頭的
    helpers, cases = {}, []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            (cases.append(n) if n.name.startswith("test_")
             else helpers.setdefault(n.name, n))

    def seg(n):
        # ⚠️ 要含**裝飾器** —— `ast.get_source_segment` 從 `def` 那一行開始，
        #    而 `@allure.step("登入")` 是 allure 的正規寫法之一，
        #    漏掉會把寫得很好的案例判成沒寫步驟。
        deco = "".join(ast.get_source_segment(src, d) or ""
                       for d in getattr(n, "decorator_list", []))
        return deco + (ast.get_source_segment(src, n) or "")

    def has(n, needle, depth=1):
        """本體有沒有，沒有就往同檔 helper 找一層（attach 收在 helper 裡是正當寫法）。"""
        body = seg(n)
        if needle in body:
            return True
        if depth <= 0:
            return False
        for name in _calls(n):
            h = helpers.get(name)
            if h is not None and has(h, needle, depth - 1):
                return True
        return False

    rel, out = _rel(path), []
    for n in cases:
        nodeid = "%s::%s" % (rel, n.name)
        if not has(n, "allure.step"):
            out.append((nodeid, "C1"))
        if "assert " in seg(n) and not has(n, "allure.attach"):
            out.append((nodeid, "C2"))
    return out


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


def scan(product=None):
    """回傳 (待修 findings, 已豁免 findings)。"""
    todo, waived = [], []
    for base in product_dirs():
        if product and os.path.basename(base).lower() not in (product.lower(),):
            continue
        exempt = load_baseline(base)
        for f in case_files(base):
            for nodeid, code in analyze(f):
                (waived if nodeid in exempt else todo).append((nodeid, code))
    return todo, waived


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", help=u"只檢查 tests/<目錄名>，如 crux")
    ap.add_argument("--all", action="store_true", help=u"連已豁免的也列出來")
    ap.add_argument("--init-baseline", action="store_true",
                    help=u"一次性：把現況寫成豁免名單（已存在則拒絕）")
    args = ap.parse_args()

    if args.init_baseline:
        for base in product_dirs():
            if args.product and os.path.basename(base).lower() != args.product.lower():
                continue
            _init_baseline(base)
        return 0

    todo, waived = scan(args.product)
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
    if todo:
        print(u"⛔ 新案例必須寫出步驟與判準 —— 做法見 `.claude/skills/ui-test/SKILL.md`"
              u"「步驟與判準」節。")
    return 1 if todo else 0


if __name__ == "__main__":
    sys.exit(main())
