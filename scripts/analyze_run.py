# -*- coding: utf-8 -*-
"""分析一次測試執行的 allure 結果，回答「這批能不能發」。

用途：發版前驗證跑完後，allure report 只告訴你「幾條紅」，但要判斷能不能發，
      需要的是**三分類**：真失敗／前置未備／環境問題 —— 前者要看，後兩者是雜訊。
      再加上「這條失敗是不是已知問題」，才知道是**新壞的**還是**一直壞著的**。
      （wbot 74 條發版驗證跑過一輪，回饋是「allure 主要是展示用，缺結果分析」。）

使用方式：
    python scripts\\analyze_run.py                                   # 讀 reports/allure-results
    python scripts\\analyze_run.py --results <目錄>
    python scripts\\analyze_run.py --product 投注機器人               # 一併比對該產品的 Bug 單
    python scripts\\analyze_run.py --since 2026-08-18                 # 只看該日期之後的結果
    python scripts\\analyze_run.py --verbose                          # 列出每一條的錯誤訊息

前置條件：無（讀本機 allure-results 的 *-result.json，不需連線）。

離開碼：有「真失敗」時回 1，其餘回 0。

⚠️ **只做分類與比對，不自動開單** —— 與「ID 永不回收、開單由人裁定」一致（見 `bug-report` skill）。

★ 分類判準刻意保守：分不出來的一律歸「真失敗」。
  把真失敗誤判成環境雜訊會讓缺陷溜過發版，反過來只是多看幾條。
"""
import argparse
import glob
import io
import json
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 分類判準 ────────────────────────────────────────────────
# 環境問題：站台或網路的狀況，不是產品缺陷。重跑該條多半就過了。
ENV_RE = re.compile(
    r"(令牌过期|令牌過期|请重新登录|請重新登入|登入頁|login"
    r"|Timeout\s+\d+ms\s+exceeded|TimeoutError|net::ERR_|ECONNREFUSED|ConnectionError"
    r"|502 Bad Gateway|503 Service|Connection aborted|Read timed out)", re.I)
# 前置未備：不是產品問題，是這次沒把前置跑起來（或刻意 skip）
PREREQ_RE = re.compile(
    r"(fixture .* not found|error in .* setup|未跑\s*Z0|wbot_target|尚未建立|前置未備"
    r"|需先執行|depends on|skipped)", re.I)


def load_results(results_dir, since=None):
    """讀 allure-results 的 *-result.json。回傳 [{name, full, status, msg, start}]。"""
    out = []
    for p in glob.glob(os.path.join(results_dir, "*-result.json")):
        try:
            d = json.loads(io.open(p, encoding="utf-8", errors="replace").read())
        except (ValueError, OSError):
            continue
        start = (d.get("start") or 0) // 1000          # allure 用毫秒
        if since and start and start < since:
            continue
        det = d.get("statusDetails") or {}
        out.append({
            "name": d.get("name") or "",
            "full": d.get("fullName") or "",
            "status": d.get("status") or "unknown",
            "msg": (det.get("message") or "").strip(),
            "trace": (det.get("trace") or "")[:400],
            "start": start,
        })
    return out


def classify(rec):
    """把一條非 passed 的結果分成 env／prereq／real。"""
    blob = rec["msg"] + "\n" + rec["trace"]
    if rec["status"] == "skipped":
        return "prereq"
    if ENV_RE.search(blob):
        return "env"
    if PREREQ_RE.search(blob) or rec["status"] == "broken" and "setup" in blob.lower():
        return "prereq"
    return "real"          # ★ 分不出來一律當真失敗


def known_bugs(product):
    """讀該產品的 Bug 單，回傳 [(bug_id, status, regression 欄, 模組)]。"""
    try:
        from bug_paths import PRODUCT_DIRS
        docs_dir = PRODUCT_DIRS.get(product)
    except ImportError:
        docs_dir = product
    if not docs_dir:
        return []
    bugs_dir = os.path.join(ROOT, "docs", docs_dir, "bugs")
    items = []
    for pat in (os.path.join(bugs_dir, "*.md"), os.path.join(bugs_dir, "old", "*.md")):
        for p in glob.glob(pat):
            if os.path.basename(p).startswith(("BUG清單", "_")):
                continue
            try:
                head = io.open(p, encoding="utf-8", errors="replace").read(2000)
            except OSError:
                continue
            def f(key):
                m = re.search(r"^%s:\s*(.*)$" % key, head, re.M)
                return (m.group(1).strip() if m else "")
            if f("id"):
                items.append((f("id"), f("status"), f("regression"), f("module")))
    return items


def match_known(rec, bugs):
    """三種比對（與 test_platform 的 bug_draft 同一套）：
    ① Bug 單的 `regression` 欄命中這條 nodeid ② 案例名含單號 ③ 模組名相符。
    回傳 (bug_id, status, 依據) 或 None。
    """
    # ⚠️ 兩個欄位都要看：allure 的 `fullName` 是模組路徑（tests.crux.backend#test_x），
    #    單號通常寫在 `name`（＝ @allure.title 的中文標題）裡。
    #    只看其中一個會漏掉全部比對（2026-08-22 實測踩到：9 條明明有單號卻全歸「新失敗」）。
    node = "%s %s" % (rec.get("full") or "", rec.get("name") or "")
    short = (rec.get("full") or "").split("::")[-1]
    for bug_id, status, regr, module in bugs:
        if regr and regr not in ("—", "-"):
            for token in re.split(r"[\s,；;]+", regr):
                t = token.strip().strip("`")
                if t and ("待補" not in t) and (t in node or (t.split("::")[-1] and t.split("::")[-1] == short)):
                    return bug_id, status, "regression 欄"
        if bug_id.lower() in node.lower():
            return bug_id, status, "案例名含單號"
    return None


def _rel(path):
    """結果目錄可能不在 repo 裡（`--results` 接任意路徑）。

    ⚠️ Windows 上 `relpath` 跨**磁碟機**會丟 `ValueError`，
    而這只是一行標題字串 —— 不值得為了好看而把整支分析弄挂。
    （2026-08-23 範本驗收實際發生：原型 repo 在 C:、範本在 D:）
    """
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="分析 allure 結果：真失敗／前置未備／環境問題")
    ap.add_argument("--results", default=os.path.join(ROOT, "reports", "allure-results"))
    ap.add_argument("--product", help="一併比對該產品的 Bug 單（CRUX／投注機器人／七星）")
    ap.add_argument("--since", help="只看該日期(YYYY-MM-DD)之後的結果")
    ap.add_argument("--verbose", action="store_true", help="列出每一條的錯誤訊息")
    a = ap.parse_args(argv)

    since = None
    if a.since:
        import calendar, time as _t
        since = calendar.timegm(_t.strptime(a.since, "%Y-%m-%d"))

    recs = load_results(a.results, since)
    if not recs:
        print("在 %s 找不到 allure 結果（*-result.json）" % a.results)
        return 0

    passed = [r for r in recs if r["status"] == "passed"]
    others = [r for r in recs if r["status"] != "passed"]
    buckets = {"real": [], "prereq": [], "env": []}
    for r in others:
        buckets[classify(r)].append(r)

    # 不指定 --product 時比對**全部**產品 —— 一批結果常橫跨多個產品，
    # 要人先猜對產品才比對得出來，等於沒有比對（2026-08-22 實測：指定錯產品時 9 條已知問題全被當新失敗）。
    if a.product:
        bugs = known_bugs(a.product)
    else:
        try:
            from bug_paths import PRODUCTS as ALL
        except ImportError:
            ALL = []
        bugs = [b for p in ALL for b in known_bugs(p)]
    new_fail, known_fail = [], []
    for r in buckets["real"]:
        hit = match_known(r, bugs) if bugs else None
        (known_fail if hit else new_fail).append((r, hit))

    print("執行結果分析 — %s" % _rel(a.results))
    print("  總計 %d 條：通過 %d／非通過 %d" % (len(recs), len(passed), len(others)))
    print()
    print("  ★ 新失敗      %3d 條   ← 這批要看的就是這些" % len(new_fail))
    print("  已知問題      %3d 條   %s" % (len(known_fail), "" if bugs else "（未指定 --product，未比對）"))
    print("  前置未備      %3d 條   ← 不是產品問題，補前置再跑" % len(buckets["prereq"]))
    print("  環境雜訊      %3d 條   ← 帳號互踢／站台不穩，重跑該條" % len(buckets["env"]))

    if new_fail:
        print("\n  ── 新失敗（逐條）──")
        for r, _ in new_fail[:30]:
            print("   ❌ %s" % (r["name"] or r["full"])[:78])
            if a.verbose and r["msg"]:
                print("      %s" % r["msg"].splitlines()[0][:100])
        if len(new_fail) > 30:
            print("   …另 %d 條" % (len(new_fail) - 30))

    if known_fail:
        print("\n  ── 已知問題（有對應 Bug 單）──")
        for r, hit in known_fail[:20]:
            print("   ⚠️ %-52s → %s（%s，%s）"
                  % ((r["name"] or r["full"])[:52], hit[0], hit[1] or "?", hit[2]))

    if buckets["env"] and a.verbose:
        print("\n  ── 環境雜訊 ──")
        for r in buckets["env"][:10]:
            print("   🔌 %-52s %s" % ((r["name"] or "")[:52], r["msg"].splitlines()[0][:60] if r["msg"] else ""))

    print("\n  發版判斷：%s" % (
        "⛔ 有 %d 條新失敗，逐條確認後再決定" % len(new_fail) if new_fail
        else "✅ 無新失敗" + ("（另有 %d 條已知問題）" % len(known_fail) if known_fail else "")))
    return 1 if new_fail else 0


if __name__ == "__main__":
    sys.exit(main())
