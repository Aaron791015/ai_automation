# -*- coding: utf-8 -*-
"""本地 Bug 單 ↔ JIRA 單配對工具。

用途：把 `docs/<專案>/bugs/` 的本地 Bug 單與 JIRA 上的單子配對，找出對應關係，
      並可回填本地 Bug 單 frontmatter 的 `reported` 欄位（開立日期＋JIRA 單號），
      免去人工逐張回填。**對 JIRA 唯讀**；只寫入本地 Bug 單。

使用方式：
    python scripts\\jira_match_bugs.py --product CRUX                     # 產生配對報告（不改檔）
    python scripts\\jira_match_bugs.py --product CRUX --since 2026-07-20
    python scripts\\jira_match_bugs.py --product CRUX --apply             # 回填「高信心」配對
    python scripts\\jira_match_bugs.py --product CRUX --apply \\
        --pair CRUX-019=CRUX-905 --pair CRUX-015=CRUX-903                 # 人工指定配對（優先於自動）
    python scripts\\jira_match_bugs.py --product CRUX --apply --force     # 連已填的 reported 一併覆寫

前置條件：
  1. `config/config.local.json` 已設定 JIRA 帳密（見 config/README.md）。
  2. 需在公司內網。

注意：
  - **自動配對只是建議**，`--apply` 前務必人工檢視報告；標題相近但實為不同問題的情況存在。
  - 回填後請重跑 `python scripts\\gen_bug_index.py` 更新 BUG清單.md。
"""

import argparse
import difflib
import glob
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from jira_qa.jira_api import JiraClient, JiraError  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 產品 → (本地 bugs 目錄, 本地 ID 前綴, JIRA project key)
# ⛔ 不在此硬編 —— 以 `config/products.json` 為單一來源（經 scripts/bug_paths）。
#    沒填 `jira_key` 的產品自動略過比對（範本與七星都是這個情況）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bug_paths                                    # noqa: E402


def _products() -> dict:
    out = {}
    for pid in bug_paths.PRODUCTS:
        key = (bug_paths.JIRA_KEYS or {}).get(pid)
        if not key:
            continue                                # 沒有 JIRA project key 就不比對
        out[pid] = (bug_paths.bugs_dir(pid),
                    "%s-" % bug_paths.ID_PREFIX.get(pid, pid), key)
    return out


PRODUCTS = _products()

HIGH = 0.72   # 高信心門檻（--apply 只動這一級）
MAYBE = 0.45  # 候選門檻（列出供人工判斷）

# 標題正規化：去除 [產品][前後台][模組] 標籤與標點空白，只留可比對的語意字元
_TAG = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+")
_NOISE = re.compile(r"[\s　「」『』（）()\[\]【】<>《》、，,。．.：:；;／/\\|~～\-—_＋+*#!！?？'\"]+")

# 繁簡對照：本地文件寫繁體、系統 UI 與部分 JIRA 單寫簡體，不統一會讓字串比對失效。
# （實例：本地「万分之」↔ JIRA「萬分之」導致 CRUX-012 ↔ CRUX-871 完全配不上。）
_SIMP = "万复单双号显后报帐类结载长张场时实现应处变设计记录员额货币转换输赢亏数码开关页项询击选组试验证确认删编辑详细总监级层图态状库赔盘龙价"
_TRAD = "萬複單雙號顯後報帳類結載長張場時實現應處變設計記錄員額貨幣轉換輸贏虧數碼開關頁項詢擊選組試驗證確認刪編輯詳細總監級層圖態狀庫賠盤龍價"
_S2T = str.maketrans(_SIMP, _TRAD)


def normalize(text):
    """去標籤、去標點空白，並統一為繁體，供字串比對使用。"""
    return _NOISE.sub("", _TAG.sub("", text or "")).translate(_S2T)


def similarity(a, b):
    """本地標題 vs JIRA 標題的相似度。取『整體比對』與『本地標題是否為 JIRA 標題子片段』的較大值。

    本地標題常帶括號補述（如「…（對涵蓋號碼恆定正值）」），JIRA 標題則帶模組標籤，
    兩者長度差異大時單純 ratio 會偏低，故併用子字串比對補償。
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    # 最長共同子串佔較短字串的比例
    match = difflib.SequenceMatcher(None, na, nb).find_longest_match(0, len(na), 0, len(nb))
    contain = match.size / min(len(na), len(nb))
    return max(ratio, contain)


def parse_frontmatter(path):
    """讀出檔頭 --- 之間的 key: value（與 gen_bug_index.py 同慣例）"""
    text = io.open(path, encoding="utf-8").read()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def load_local_bugs(bugs_dir, prefix):
    """載入本地 Bug 單（略過索引與建議單以外的非 Bug 檔）。"""
    bugs = []
    for path in sorted(glob.glob(os.path.join(bugs_dir, prefix + "*.md"))):
        meta = parse_frontmatter(path)
        if not meta or not meta.get("id"):
            continue
        bugs.append(
            {
                "path": path,
                "id": meta["id"],
                "title": meta.get("title", ""),
                "status": meta.get("status", ""),
                "found": meta.get("found", ""),
                "reported": meta.get("reported", ""),
            }
        )
    return bugs


def set_reported(path, value):
    """改寫 frontmatter 的 reported 欄位（只動這一行，其餘內容不變）。"""
    text = io.open(path, encoding="utf-8").read()
    new, n = re.subn(r"(?m)^reported:.*$", "reported: " + value, text, count=1)
    if n == 0:
        return False
    io.open(path, "w", encoding="utf-8", newline="").write(new)
    return True


# JIRA 已結案的狀態（本站台用 Done；保留其他常見值以防流程調整）
_CLOSED = {"done", "resolved", "closed"}
_KEY_RE = re.compile(r"\b([A-Z]+-\d+)\b")


def recheck(local, product):
    """比對已配對單的「本地狀態 vs JIRA 狀態」，找出待重驗與該撤單的矛盾。

    此清單為**即時導出**（每次查 JIRA 現況），不是人工維護的待辦，不會過期失準。
    """
    targets = []
    for b in local:
        m = _KEY_RE.search(b["reported"] or "")
        if m:
            targets.append((b, m.group(1)))
    if not targets:
        print(f"{product}：沒有任何已回填 JIRA 單號的本地 Bug 單。")
        return 0

    keys = sorted({k for _, k in targets})
    try:
        client = JiraClient.from_config()
        issues = {i.key: i for i in client.search(f"key in ({', '.join(keys)})", len(keys))}
    except JiraError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    print(f"# {product} 本地狀態 vs JIRA 狀態（已配對 {len(targets)} 張）\n")
    recheck_list, withdraw_list, unclosed, rows = [], [], [], []
    for b, key in targets:
        issue = issues.get(key)
        js = issue.status if issue else "（查無）"
        closed = js.lower() in _CLOSED
        if b["status"] == "open" and closed:
            verdict = "⚠️ 待重驗（RD 已修，我方未驗）"
            recheck_list.append(f"{b['id']} / {key}")
        elif b["status"] == "rejected" and not closed:
            verdict = "⚠️ 建議撤單（我方判非缺陷，JIRA 仍開）"
            withdraw_list.append(f"{b['id']} / {key}")
        elif b["status"] == "fixed" and not closed:
            verdict = "⚠️ JIRA 未關（我方已重驗通過）"
            unclosed.append(f"{b['id']} / {key}")
        else:
            verdict = "✓ 一致"
        rows.append((b, key, js, verdict))

    print("| 本地 ID | 本地狀態 | JIRA | JIRA 狀態 | 判定 |")
    print("| --- | --- | --- | --- | --- |")
    for b, key, js, verdict in rows:
        print(f"| {b['id']} | {b['status']} | {key} | {js} | {verdict} |")

    for title, items in (
        ("🔁 待重驗", recheck_list),
        ("↩️ 建議至 JIRA 撤單", withdraw_list),
        ("📌 可請 RD 關單", unclosed),
    ):
        if items:
            print(f"\n## {title}（{len(items)}）\n")
            for it in items:
                print(f"- {it}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="本地 Bug 單 ↔ JIRA 單配對")
    p.add_argument("--product", required=True, choices=sorted(PRODUCTS), help="產品")
    p.add_argument("--since", default="2026-07-01", help="只比對此日期後建立的 JIRA 單（預設 2026-07-01）")
    p.add_argument("--mine", action="store_true",
                   help="只比對自己回報的單。⚠️ 預設不加：實測有本地單對應到同事開立的 JIRA 單（如本地 CRUX-011 ↔ CRUX-835），加了會漏配")
    p.add_argument("--jql", help="自訂 JQL（覆寫預設的 project+created 條件）")
    p.add_argument("--max", type=int, default=400, help="JIRA 取單上限（預設 400）")
    p.add_argument("--apply", action="store_true", help="回填高信心配對到本地 reported 欄位")
    p.add_argument("--force", action="store_true", help="連已填的 reported 一併覆寫")
    p.add_argument("--pair", action="append", default=[], help="人工指定配對，格式 本地ID=JIRA單號（可重複）")
    p.add_argument("--recheck", action="store_true",
                   help="不做配對，改為比對已配對單的本地狀態 vs JIRA 狀態，列出待重驗／該撤單的矛盾")
    p.add_argument("--only-pairs", action="store_true",
                   help="--apply 時只回填 --pair 指定的配對，不動自動判定的高信心結果（推薦：自動比對會漏會錯）")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    bugs_dir, prefix, project = PRODUCTS[args.product]
    local = load_local_bugs(bugs_dir, prefix)
    if not local:
        print(f"❌ {bugs_dir} 找不到任何 {prefix}*.md")
        return 1

    manual = {}
    for pair in args.pair:
        if "=" not in pair:
            p.error(f"--pair 格式應為 本地ID=JIRA單號，收到：{pair}")
        k, v = pair.split("=", 1)
        manual[k.strip().upper()] = v.strip().upper()

    if args.recheck:
        return recheck(local, args.product)

    mine = " AND reporter = currentUser()" if args.mine else ""
    jql = args.jql or (
        f'project = {project}{mine} AND created >= "{args.since}" ORDER BY created ASC'
    )
    try:
        client = JiraClient.from_config()
        issues = client.search(jql, args.max)
    except JiraError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    print(f"# {args.product} 本地 Bug 單 ↔ JIRA 配對")
    print(f"\nJQL：`{jql}`")
    print(f"本地單 {len(local)} 張、JIRA 單 {len(issues)} 張\n")

    by_key = {i.key: i for i in issues}
    used = {}       # JIRA key -> 本地 id（偵測一對多）
    rows, applied = [], []

    for b in local:
        if b["id"] in manual:
            key = manual[b["id"]]
            issue = by_key.get(key)
            if not issue:  # 人工指定的單可能不在 JQL 範圍內，單獨取
                try:
                    issue = client.get_issue(key)
                    by_key[key] = issue
                except JiraError:
                    issue = None
            score, level = (1.0, "人工指定") if issue else (0.0, "指定單取不到")
        else:
            ranked = sorted(
                ((similarity(b["title"], i.summary), i) for i in issues),
                key=lambda x: x[0],
                reverse=True,
            )[:3]
            b["candidates"] = ranked
            score, best = ranked[0] if ranked else (0.0, None)
            issue = best if score >= MAYBE else None
            level = "高信心" if score >= HIGH else ("候選" if issue else "無對應")

        key = issue.key if issue else ""
        if key:
            used.setdefault(key, []).append(b["id"])
        rows.append(
            {
                "local": b,
                "key": key,
                "summary": issue.summary if issue else "",
                "created": (issue.created or "")[:10] if issue else "",
                "status": issue.status if issue else "",
                "score": score,
                "level": level,
            }
        )

    # 回填
    if args.apply:
        allowed = ("人工指定",) if args.only_pairs else ("高信心", "人工指定")
        for r in rows:
            if r["level"] not in allowed or not r["key"]:
                continue
            cur = r["local"]["reported"]
            if cur and not args.force:
                continue
            value = f"{r['created']}（{r['key']}）"
            if set_reported(r["local"]["path"], value):
                applied.append(f"{r['local']['id']} → {value}")

    # 報告
    print("| 本地 ID | 狀態 | 本地標題 | JIRA | JIRA 狀態 | 相似度 | 判定 | 現有 reported |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        b = r["local"]
        warn = " ⚠️重複" if r["key"] and len(used.get(r["key"], [])) > 1 else ""
        print(
            f"| {b['id']} | {b['status']} | {b['title'][:40]} | {r['key'] or '—'} | "
            f"{r['status'] or '—'} | {r['score']:.2f} | {r['level']}{warn} | {b['reported'] or '（空）'} |"
        )

    # 非高信心者列出前 3 名候選：字串比對常因繁簡、改寫、同義詞失準，
    # 單看最佳解會漏配（實例：CRUX-010 ↔ CRUX-872「上繳貨量會虛增」措辭全異）。
    weak = [r for r in rows if r["level"] not in ("高信心", "人工指定") and r["local"].get("candidates")]
    if weak:
        print(f"\n## 未達高信心者的候選（前 3 名，供人工判讀）\n")
        for r in weak:
            print(f"- **{r['local']['id']}** {r['local']['title'][:45]}")
            for s, i in r["local"]["candidates"]:
                print(f"    - {s:.2f} {i.key} [{i.status}] {i.summary[:65]}")

    matched_keys = {r["key"] for r in rows if r["key"]}
    orphan = [i for i in issues if i.key not in matched_keys]
    if orphan:
        print(f"\n## JIRA 有、本地無對應（{len(orphan)} 張）\n")
        for i in orphan:
            print(f"- {i.key} [{i.status}] {i.summary[:70]}")

    dup = {k: v for k, v in used.items() if len(v) > 1}
    if dup:
        print("\n## ⚠️ 一張 JIRA 單被多張本地單指到（需人工裁定）\n")
        for k, ids in dup.items():
            print(f"- {k} ← {'、'.join(ids)}")

    if args.apply:
        print(f"\n## 已回填 {len(applied)} 張\n")
        for a in applied:
            print(f"- {a}")
        if applied:
            print("\n請重跑：`python scripts\\gen_bug_index.py`")
    else:
        print("\n> 本次未改檔。確認無誤後加 `--apply` 回填（只動「高信心」與「人工指定」）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
