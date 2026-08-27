# -*- coding: utf-8 -*-
"""解析「覆蓋矩陣」文件，算出覆蓋率、缺口與剩餘工作量。

用途：覆蓋矩陣（`docs/<產品>/*_驗證項目清單.md` 這類）記錄每個功能點「驗到多深」，
      但人工看表算不出「還剩多少」。本腳本把它變成可查的數字，並用 `--lint` 擋掉半成品。
      方法論見 `.claude/skills/testcase-design/SKILL.md`。

使用方式：
    python scripts\\coverage_matrix.py --file docs\\CRUX\\CRUX_排列五與七星彩_驗證項目清單.md
    python scripts\\coverage_matrix.py --file <矩陣> --gaps        # 只列差距最大的
    python scripts\\coverage_matrix.py --file <矩陣> --lint        # 格式完整性檢查（缺欄位／缺標記）
    python scripts\\coverage_matrix.py --file <矩陣> --cases <案例清單> --orphans
                                                                  # 盤到了卻沒推成案例的功能點

前置條件：無（純本機檔案讀取，不需連線測試站）。

★ 為什麼「目標深度」可以留空：目標由**風險類別**決定（金流→L4、資料/權限→L3、顯示→L2、邊角→L1），
  逐列手填會不一致也會漏。本腳本從 `風險` 欄推導，只有需要覆寫時才填 `目標` 欄。

⚠️ 深度／風險／來源三組常數**刻意先放本檔**。若日後 `lint_docs` 也要讀矩陣，
   再比照 `bug_paths.py` 收斂成共用模組 —— 不要一開始就各複製一份
   （`bug_paths.py` 的 docstring 記著 2026-08-11 那次「靜默分裂」的教訓）。
"""
import argparse
import io
import os
import re
import sys

# Windows 終端預設 cp950，直接 print 中文會 UnicodeEncodeError（平台其他工具踩過同一個坑）
if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:      # Python < 3.7 沒有 reconfigure，退回原編碼
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 深度分級（見 SKILL.md §2）────────────────────────────────
DEPTHS = ["L0", "L1", "L2", "L3", "L4"]
DEPTH_LABEL = {
    "L0": "未觸及", "L1": "已瀏覽", "L2": "已比對", "L3": "已驗算", "L4": "已端到端",
}

# ── 風險類別 → 目標深度（見 SKILL.md §3）─────────────────────
RISK_TARGET = {
    "金流": "L4", "資料": "L3", "權限": "L3", "顯示": "L2", "邊角": "L1",
}

# ── 功能點來源（見 SKILL.md §1）；僅供 --lint 檢查用字是否在集合內 ──
SOURCES = ["選單", "API", "對照", "權限", "規格"]

# ── 欄位別名：既有矩陣用「本次深度」，新標準用「本次」，兩者都要認 ──
COLUMN_ALIASES = {
    "#": "id", "編號": "id",
    "功能點": "name", "功能": "name",
    "來源": "source",
    "風險": "risk", "風險類別": "risk",
    "目標": "target", "目標深度": "target",
    "本次": "current", "本次深度": "current",
    "已知缺陷": "defect",
    "後續詳驗要點": "note",
    "對應矩陣項": "matrix_ref",       # 案例清單用
    "案例": "case",                   # 案例清單用
}

# 阻塞的判斷：要點欄提到「等」某張單、或明寫阻塞
BLOCKED_RE = re.compile(r"(等\s*(RD|PM|SA)|等[^\s，。]*修|阻塞|待\s*(RD|PM|SA)\s*裁定)")


def _split_row(line):
    """切 markdown 表格列。先還原被跳脫的 `\\|`，避免把儲存格內的 | 當成欄位分隔。"""
    line = line.strip()
    if not line.startswith("|"):
        return None
    placeholder = "\x00"
    line = line.replace(r"\|", placeholder)
    cells = [c.strip().replace(placeholder, "|") for c in line.strip("|").split("|")]
    return cells


def _clean(text):
    """去掉 markdown 修飾，只留內容：**粗體**、~~刪除線~~、`code`、[連結](url)。"""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("~~", "").replace("`", "")
    return text.strip()


def _is_separator(cells):
    """表頭下方的 |---|---| 分隔列。"""
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells if c.strip())


def parse_tables(path):
    """掃出檔案裡所有 markdown 表格，回傳 [{header: [...], rows: [{欄位鍵: 值}]}]。

    ★ 不假設整份檔只有一張表 —— 覆蓋矩陣通常依區塊分成多張（2.1 定盤、2.2 設置…）。
    """
    if not os.path.isfile(path):
        raise SystemExit("找不到檔案：%s" % path)
    lines = io.open(path, encoding="utf-8").read().splitlines()
    tables, i = [], 0
    while i < len(lines):
        cells = _split_row(lines[i])
        if cells and i + 1 < len(lines) and _is_separator(_split_row(lines[i + 1]) or []):
            header = [_clean(c) for c in cells]
            keys = [COLUMN_ALIASES.get(h, h) for h in header]
            rows, j = [], i + 2
            while j < len(lines):
                rc = _split_row(lines[j])
                if not rc:
                    break
                row = {}
                for k, v in zip(keys, rc):
                    row[k] = _clean(v)
                row["_line"] = j + 1          # 1-based，供報錯指路
                rows.append(row)
                j += 1
            tables.append({"header": header, "keys": keys, "rows": rows})
            i = j
        else:
            i += 1
    return tables


def collect_items(path):
    """把所有「看起來是覆蓋矩陣」的表格的列收成一份清單。

    判準：表頭同時有 `功能點` 與 `本次(深度)` —— 只有覆蓋矩陣長這樣，
    藉此跳過同一份檔裡的說明表（如深度分級表、前置環境表）。
    """
    items = []
    for t in parse_tables(path):
        if "name" in t["keys"] and "current" in t["keys"]:
            items.extend(t["rows"])
    return items


def _depth(value):
    """從儲存格取出 L0~L4；取不到回 None（--lint 會報）。"""
    if not value:
        return None
    m = re.search(r"L([0-4])", value)
    return ("L%s" % m.group(1)) if m else None


def _risk(value):
    """風險欄可能寫「金流正確性」「金流」等，取關鍵字。"""
    if not value:
        return None
    for k in RISK_TARGET:
        if k in value:
            return k
    return None


def analyse(items):
    """算出每列的目標／現況／差距，以及整體統計。"""
    dist = dict((d, 0) for d in DEPTHS)
    rows, blocked, no_risk, no_depth = [], [], [], []
    for it in items:
        cur = _depth(it.get("current"))
        risk = _risk(it.get("risk"))
        tgt = _depth(it.get("target")) or (RISK_TARGET.get(risk) if risk else None)
        if cur:
            dist[cur] += 1
        else:
            no_depth.append(it)
        if not risk and not _depth(it.get("target")):
            no_risk.append(it)
        gap = (DEPTHS.index(tgt) - DEPTHS.index(cur)) if (tgt and cur) else None
        if BLOCKED_RE.search(it.get("note", "") or ""):
            blocked.append(it)
        rows.append({"item": it, "current": cur, "target": tgt, "risk": risk, "gap": gap})
    met = [r for r in rows if r["gap"] is not None and r["gap"] <= 0]
    unmet = [r for r in rows if r["gap"] is not None and r["gap"] > 0]
    return {
        "rows": rows, "dist": dist, "met": met, "unmet": unmet,
        "blocked": blocked, "no_risk": no_risk, "no_depth": no_depth,
        "total": len(rows),
    }


def report(path, res, gaps_only=False):
    name = os.path.basename(path)
    print("覆蓋矩陣分析 — %s" % name)
    if not res["total"]:
        print("  ⚠️ 沒有解析到任何功能點列。")
        print("     矩陣表頭需同時含「功能點」與「本次」(或「本次深度」)。")
        return
    if not gaps_only:
        dist = "  ".join("%s×%d" % (d, res["dist"][d]) for d in DEPTHS if res["dist"][d])
        print("  功能點  %d    深度分布  %s" % (res["total"], dist or "（皆未標記）"))
        gradable = len(res["met"]) + len(res["unmet"])
        if gradable:
            pct = round(len(res["met"]) * 100.0 / gradable)
            print("  已達目標 %d/%d (%d%%)      未達 %d"
                  % (len(res["met"]), gradable, pct, len(res["unmet"])))
        else:
            print("  ⚠️ 無法計算達標率：沒有任何一列同時有「風險(或目標)」與「本次」")
    worst = sorted(res["unmet"], key=lambda r: -r["gap"])[:8]
    if worst:
        print("  缺口最大：")
        for r in worst:
            it = r["item"]
            print("    %-5s %s（%s → %s，差 %d 級）"
                  % (it.get("id", "?"), it.get("name", "")[:34],
                     r["current"], r["target"], r["gap"]))
    if res["blocked"]:
        ids = "、".join(b.get("id", "?") for b in res["blocked"][:10])
        print("  阻塞中  %d 項：%s" % (len(res["blocked"]), ids))


def lint(path, res):
    """格式完整性檢查。回傳 0=通過、1=有問題（供 CI／人工判讀）。"""
    problems = []
    if not res["total"]:
        problems.append("沒有解析到任何功能點列（表頭需含「功能點」與「本次」）")

    # ★ 整欄缺 vs 個別列缺要分開報。
    #   整欄缺時逐列報等於同一件事講 61 次，會把真正該逐列修的問題淹掉（實測過）。
    def _has_col(key):
        return any(key in r["item"] for r in res["rows"])

    has_risk_col = _has_col("risk") or _has_col("target")
    if res["total"] and not has_risk_col:
        problems.append("整張矩陣沒有「風險」欄（也沒有「目標」欄）→ 算不出還要驗到多深。"
                        "補一欄「風險」填 金流／資料／權限／顯示／邊角，目標深度會自動推導（SKILL.md §3）")
    else:
        for it in res["no_risk"]:
            problems.append("第 %d 行 %s 未標「風險」也未標「目標」→ 算不出還要驗到多深"
                            % (it["_line"], it.get("id") or it.get("name", "")[:20]))

    if res["total"] and not _has_col("current"):
        problems.append("整張矩陣沒有「本次」欄")
    else:
        for it in res["no_depth"]:
            problems.append("第 %d 行 %s 未標「本次深度」（L0～L4）"
                            % (it["_line"], it.get("id") or it.get("name", "")[:20]))

    if res["total"] and not _has_col("source"):
        problems.append("整張矩陣沒有「來源」欄 → 無法追溯「為什麼有這一列」（見 SKILL.md §1 五來源交叉）")
    print("coverage_matrix --lint：%s" % os.path.basename(path))
    if not problems:
        print("  ✅ 通過")
        return 0
    for p in problems:
        print("  ⚠️ %s" % p)
    print("  —— 共 %d 項。未標記的列算不進覆蓋率，等於盤了一半。" % len(problems))
    return 1


def orphans(matrix_path, cases_path):
    """找出「矩陣有、案例清單沒有」的功能點 —— 盤到了卻沒推成案例。"""
    items = collect_items(matrix_path)
    refs = set()
    for t in parse_tables(cases_path):
        if "matrix_ref" in t["keys"]:
            for r in t["rows"]:
                for one in re.split(r"[、,／/\s]+", r.get("matrix_ref", "")):
                    if one.strip():
                        refs.add(one.strip())
    print("孤兒功能點（矩陣有、案例清單未涵蓋） — %s" % os.path.basename(matrix_path))
    if not refs:
        print("  ⚠️ 案例清單沒有「對應矩陣項」欄，無法比對。")
        print("     請依 SKILL.md §9 的產物二標準欄位補上，才能建立雙向追溯。")
        return 1
    miss = [it for it in items if (it.get("id") or "").strip() and it.get("id").strip() not in refs]
    if not miss:
        print("  ✅ 每個功能點都有對應案例")
        return 0
    for it in miss:
        print("    %-5s %s" % (it.get("id"), it.get("name", "")[:40]))
    print("  —— 共 %d 項尚未推成案例（占 %d 項功能點的 %d%%）"
          % (len(miss), len(items), round(len(miss) * 100.0 / max(len(items), 1))))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="解析覆蓋矩陣，算出覆蓋率、缺口與剩餘工作量")
    ap.add_argument("--file", required=True, help="覆蓋矩陣 markdown 檔路徑")
    ap.add_argument("--cases", help="案例清單 markdown 檔路徑（配合 --orphans）")
    ap.add_argument("--gaps", action="store_true", help="只列差距最大的功能點")
    ap.add_argument("--lint", action="store_true", help="格式完整性檢查")
    ap.add_argument("--orphans", action="store_true", help="列出矩陣有、案例清單沒有的功能點")
    args = ap.parse_args(argv)

    path = args.file if os.path.isabs(args.file) else os.path.join(ROOT, args.file)
    if args.orphans:
        if not args.cases:
            raise SystemExit("--orphans 需要同時提供 --cases <案例清單>")
        cases = args.cases if os.path.isabs(args.cases) else os.path.join(ROOT, args.cases)
        return orphans(path, cases)

    res = analyse(collect_items(path))
    if args.lint:
        return lint(path, res)
    report(path, res, gaps_only=args.gaps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
