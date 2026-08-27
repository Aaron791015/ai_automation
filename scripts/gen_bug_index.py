# -*- coding: utf-8 -*-
"""由各 Bug 單的 frontmatter 生成 `docs/<專案>/bugs/BUG清單.md`。

用途：Bug 狀態的單一事實來源是各 Bug 單檔頭的 frontmatter；本腳本把它彙總成索引。
使用方式：
    python scripts\\gen_bug_index.py            # 生成全部專案索引 ＋ _view/ 分組檢視
    python scripts\\gen_bug_index.py CRUX       # 只生成指定專案
    python scripts\\gen_bug_index.py CRUX --next-id   # ★配號：算出下一個可用 Bug ID
前置條件：無（純本機檔案讀寫，不需連線測試站）。

Bug 單只會存在於兩個位置：**主目錄** 與 **`old/`（歸檔層，由 archive_bugs.py 搬移）**；
索引與配號一律同時掃描兩層。

⚠️ `BUG清單.md` 為自動生成，勿手改；要改內容請改對應 Bug 單的 frontmatter 後重跑本腳本。
"""
import datetime
import glob
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bug_paths import ARCHIVE_DIR, VIEW_DIR   # noqa: E402  單一事實來源，勿在此重新定義
from bug_paths import PRODUCTS as _PRODUCT_IDS, product_base  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⛔ **不要在這裡重新定義產品清單。**（上一行的註解本來就這樣寫，
#    但底下曾經硬編了三個原型產品 —— 於是同事接了自己的產品之後，
#    `gen_bug_index.py <新產品> --next-id` 直接 KeyError，
#    而 `CLAUDE.md` §6 規定配號**必須**用這支指令。
#    2026-08-23 範本端到端驗收發現。）
PRODUCTS = {p: product_base(p) for p in _PRODUCT_IDS}

STATUS_LABEL = {
    "open": "🔴 未修復",
    "fixed": "✅ 已修復",
    "rejected": "⛔ 已撤銷",
    "superseded": "🔁 已接續",
    "suggestion": "💡 建議",
}
STATUS_ORDER = ["open", "superseded", "fixed", "rejected", "suggestion"]


def parse_frontmatter(path):
    """讀出檔頭 --- 之間的 key: value（本專案只用平坦字串欄位）"""
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


def short_date(d):
    """2026-07-28 -> 07-28（同年省略年份，跨年才顯示全日期）"""
    if not d or not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d or "—"
    return d[5:] if d[:4] == str(datetime.date.today().year) else d


def is_reported(b) -> bool:
    """這張單提交 RD 了沒。

    ⚠️ 空字串與「未開立」**都算沒開** —— `BUG清單.md` 的開立欄顯示的就是
       「❌ 未開立」，照著抄回 frontmatter 是很自然的事，而
       `core/bug_index.py` 早就這樣認了。兩邊判準不同的話，
       一張沒人開的單會被歸到「已開立待修復」，從此沒有人會去開它
       （2026-08-23 情境 B 走查）。
    """
    r = (b.get("reported") or "").strip()
    return bool(r) and "未開立" not in r


def short_reported(b):
    """開立欄顯示：已開立→開立日期（含附註）；未填→未結案者明示「未開立」、已結案（fixed/rejected）顯 —"""
    r = (b.get("reported") or "").strip()
    if r and r not in ("—", "-"):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})(.*)$", r)
        return (short_date(m.group(1)) + m.group(2)) if m else r
    return "—" if b.get("status") in ("fixed", "rejected") else "❌ 未開立"


def short_reg(r):
    if not r or r in ("—", "-"):
        return "—"
    if r.startswith("⚠️"):
        return r
    # tests/crux/hold/test_x.py（附註） -> test_x.py（附註）
    m = re.match(r"^(tests/[^\s（(]*/)?([^\s（(]+)(.*)$", r)
    return (m.group(2) + m.group(3)).strip() if m else r


def render(product, bugs):
    today = datetime.date.today().isoformat()
    counts = {s: sum(1 for b in bugs if b.get("status") == s) for s in STATUS_ORDER}
    defects = [b for b in bugs if b.get("status") != "suggestion"]
    sugs = [b for b in bugs if b.get("status") == "suggestion"]

    out = ["# %s Bug 清單" % product, "",
           "> 由 `scripts/gen_bug_index.py` 依各 Bug 單 frontmatter 自動生成，**請勿手改**；",
           "> 要更新狀態請改對應 Bug 單檔頭的 `status`／`reported`／`verified`／`regression` 後重跑腳本。",
           "> 最後更新：%s" % today, "",
           "## 統計", "",
           "| 狀態 | 件數 |", "| --- | --- |"]
    for s in STATUS_ORDER:
        if counts[s]:
            out.append("| %s | %d |" % (STATUS_LABEL[s], counts[s]))
    out += ["| **合計** | **%d** |" % len(bugs), ""]

    if defects:
        out += ["## 缺陷", "",
                "| ID | 標題 | 面 | 模組 | 嚴重度 | 狀態 | 發現 | 開立 | 重驗 | 回歸案例 | 位置 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for b in defects:
            out.append("| [%s](%s) | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                b["id"], b["_file"], b.get("title", ""), b.get("surface", "—"),
                b.get("module", "—"), b.get("severity", "—"),
                STATUS_LABEL.get(b.get("status"), b.get("status", "?")),
                short_date(b.get("found")), short_reported(b),
                short_date(b.get("verified")), short_reg(b.get("regression")),
                "📦" if b.get("_archived") else "—"))
        out.append("")
    if sugs:
        out += ["## 改善建議（非缺陷，S 序列）", "",
                "| ID | 標題 | 模組 | 發現 | 開立 |", "| --- | --- | --- | --- | --- |"]
        for b in sugs:
            out.append("| [%s](%s) | %s | %s | %s | %s |" % (
                b["id"], b["_file"], b.get("title", ""), b.get("module", "—"),
                short_date(b.get("found")), short_reported(b)))
        out.append("")

    # ⚠️ 只算 open。`superseded`（已接續）由後續單接手追蹤，本身不會再開立，
    #    列進來會讓「待開立」永遠清不完（實例：CRUX-005、CRUX-044）。
    unreported = [b["id"] for b in defects
                  if b.get("status") == "open" and not is_reported(b)]
    if unreported:
        out += ["## ❌ 待開立", "",
                "以下未修復缺陷**尚未開立提交 RD**（frontmatter `reported` 為空）；",
                "重新驗證前請先確認是否已提交，未開立者重驗 FAIL 屬預期：**%s**" % "、".join(unreported), ""]

    # 同上：superseded 的回歸案例由後續單負責，不列入待補
    missing = [b["id"] for b in defects
               if b.get("status") == "open"
               and (not b.get("regression") or b["regression"].startswith("⚠️"))]
    if missing:
        out += ["## ⚠️ 待補回歸案例", "",
                "依 CLAUDE.md §6，已確認的 bug 須建立以正確行為為斷言的回歸案例。",
                "以下未修復缺陷尚無對應案例：**%s**" % "、".join(missing), ""]

    out += ["---", "",
            "**欄位說明**：狀態 `open` 未修復／`fixed` 已修復重驗通過／`rejected` 查證後非缺陷／",
            "`superseded` 由後續單接續／`suggestion` 改善建議。",
            "開立＝是否已提交 RD 修正（frontmatter `reported`，值為開立日期、可附外部單號；未開立留空）。",
            "截圖統一置於 `shots/`，",
            "檔名前綴為首位擁有者 ID（共用圖由多單引用同一路徑）。對外打包副本見 `_deliver/`。", ""]
    return "\n".join(out)


VIEWS = [
    ("01_待開立", lambda b: b.get("status") == "open" and not is_reported(b),
     "未修復且**尚未提交 RD**。重驗前先看這裡——未開立者重驗仍 FAIL 屬預期。"),
    ("02_已開立待修復", lambda b: b.get("status") == "open" and is_reported(b),
     "已提交 RD、等待修復或重驗。"),
    ("03_已修復", lambda b: b.get("status") == "fixed",
     "已重驗通過，可建議關單。"),
    ("04_已撤銷與接續", lambda b: b.get("status") in ("rejected", "superseded"),
     "查證後非缺陷（rejected）或由後續單接手（superseded）。"),
    ("05_改善建議", lambda b: b.get("status") == "suggestion",
     "非缺陷的改善建議（S 序列，不佔 bug 流水號）。"),
]


def load_bugs(bugs_dir, quiet=False):
    """讀取主目錄與 old/ 兩層的 Bug 單；`_archived` 標示是否已歸檔。"""
    bugs = []
    for archived, pattern in ((False, os.path.join(bugs_dir, "*.md")),
                              (True, os.path.join(bugs_dir, ARCHIVE_DIR, "*.md"))):
        for path in sorted(glob.glob(pattern)):
            if os.path.basename(path) == "BUG清單.md":
                continue
            meta = parse_frontmatter(path)
            if not meta or "id" not in meta:
                if not quiet:
                    print("  [warn] 缺 frontmatter，略過:", os.path.basename(path))
                continue
            meta["_file"] = (ARCHIVE_DIR + "/" if archived else "") + os.path.basename(path)
            meta["_archived"] = archived
            bugs.append(meta)
    bugs.sort(key=lambda b: b["id"])
    return bugs


def next_id(product, bugs_dir):
    """算出下一個可用的 Bug ID。

    ⚠️ 這是配號的**唯一正確方式** —— 不可用 `ls bugs/`：
       ① 看不到 old/ 的已歸檔單 → 撞號（ID 永不回收）
       ② 多 session 併行共用 working tree，別人隨時可能剛用掉一個號
    仍需在**寫檔的當下**執行，不得沿用先前步驟記下的號碼。
    """
    # ⛔ 前綴一律從 `config/products.json` 取（經 bug_paths）——
    #    硬編的話新接的產品直接 KeyError，而這支正是配號的唯一正確方式
    #    （2026-08-23 範本端到端驗收）。
    from bug_paths import ID_PREFIX
    prefix = ID_PREFIX.get(product)
    if not prefix:
        raise SystemExit(
            "產品 %s 沒有登記 bug_prefix —— 請確認 config/products.json，"
            "或用 scripts/new_product.py 重新接入" % product)
    used = set()
    for b in load_bugs(bugs_dir, quiet=True):
        m = re.match(r"^%s-(\d{3})$" % prefix, b["id"])
        if m:
            used.add(int(m.group(1)))
    # 檔名也掃一次：frontmatter 壞掉的檔仍佔號
    for path in glob.glob(os.path.join(bugs_dir, "**", "*.md"), recursive=True):
        m = re.match(r"^%s-(\d{3})_" % prefix, os.path.basename(path))
        if m:
            used.add(int(m.group(1)))
    nxt = max(used) + 1 if used else 1
    return "%s-%03d" % (prefix, nxt), sorted(used)[-5:]


def render_views(product, bugs, view_dir):
    """輸出按狀態分組的檢視檔（純衍生，勿手改）。"""
    os.makedirs(view_dir, exist_ok=True)
    today = datetime.date.today().isoformat()
    written = []
    for name, pred, desc in VIEWS:
        rows = [b for b in bugs if pred(b)]
        out = ["# %s — %s（%d）" % (product, name.split("_", 1)[1], len(rows)), "",
               "> %s" % desc,
               "> 由 `scripts/gen_bug_index.py` 自動生成，**勿手改**；最後更新：%s" % today, ""]
        if rows:
            out += ["| ID | 標題 | 模組 | 嚴重度 | 開立 | 回歸案例 | 位置 |",
                    "| --- | --- | --- | --- | --- | --- | --- |"]
            for b in rows:
                loc = "📦 old" if b.get("_archived") else "—"
                out.append("| [%s](../%s) | %s | %s | %s | %s | %s | %s |" % (
                    b["id"], b["_file"], b.get("title", ""), b.get("module", "—"),
                    b.get("severity", "—"), short_reported(b),
                    short_reg(b.get("regression")), loc))
        else:
            out.append("_（目前沒有符合的項目）_")
        out.append("")
        path = os.path.join(view_dir, name + ".md")
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out))
        written.append("%s(%d)" % (name.split("_", 1)[1], len(rows)))
    return written


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--next-id" in flags:
        # ⚠️ 預設值不可寫死某個產品 —— 沒給參數時用**唯一的那個產品**，
        #    有多個就全部列出來讓人自己看（配錯號的代價是永久的）。
        for product in (args or list(PRODUCTS)):
            bugs_dir = os.path.join(PRODUCTS[product], "bugs")
            nid, recent = next_id(product, bugs_dir)
            print("%s 下一個可用 ID：%s（已用最大 5 個：%s）" % (
                product, nid, "、".join("%03d" % n for n in recent)))
        return

    targets = args or list(PRODUCTS)
    for product in targets:
        base = PRODUCTS.get(product)
        if not base:
            print("未知專案:", product)
            continue
        bugs_dir = os.path.join(base, "bugs")
        os.makedirs(bugs_dir, exist_ok=True)
        bugs = load_bugs(bugs_dir)
        index = os.path.join(bugs_dir, "BUG清單.md")
        with io.open(index, "w", encoding="utf-8", newline="\n") as f:
            f.write(render(product, bugs))
        n_arch = sum(1 for b in bugs if b.get("_archived"))
        print("生成 %s（%d 筆%s）" % (os.path.relpath(index, ROOT), len(bugs),
                                     "，其中 %d 筆已歸檔" % n_arch if n_arch else ""))
        views = render_views(product, bugs, os.path.join(bugs_dir, VIEW_DIR))
        print("  分組檢視 %s/：%s" % (VIEW_DIR, "、".join(views)))

    _run_lint(targets)


def _run_lint(targets):
    """順便檢查截圖與 Bug 單的一致性。

    改完 Bug 單就要重跑索引（CLAUDE.md §6），那正是檢查資產的自然時機——
    分成兩個要記得跑的指令，第二個一定會被忘記。詳細報告請跑 lint_bug_assets.py。
    """
    try:
        import lint_bug_assets as L
    except ImportError:
        return
    issues = 0
    for product in targets:
        base = L.PRODUCTS.get(product)
        if not base:
            continue
        errors, warnings, _dead, stat = L.lint(product, base)
        if errors or warnings:
            issues += len(errors) + len(warnings)
            print("  %s：❌%d ⚠️%d" % (product, len(errors), len(warnings)))
    if issues:
        print("\n⚠️ 截圖資產有 %d 項待處理 → python scripts\\lint_bug_assets.py --verbose" % issues)
    else:
        print("✅ 截圖資產檢查通過")


if __name__ == "__main__":
    main()
