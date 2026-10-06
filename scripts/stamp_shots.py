# -*- coding: utf-8 -*-
"""把 Playwright MCP 拍的截圖搬進 `docs/<專案>/bugs/shots/` 並蓋上「已標注」標記。

用途：補上 MCP 路徑缺的那一步。pytest 走 `qa_common.shot.capture_annotated()` 會自動
      `stamp_png`，但 **MCP 的 `browser_take_screenshot` 不會** —— 圖看起來有紅框，
      `lint_bug_assets` 的 W7 卻判定「沒有標注標記」，因為標記是寫在 PNG 的 tEXt 區塊裡、
      不是看畫面判斷的。以前只能每次手寫一段 Python 補蓋，本腳本把它固定下來。

使用方式（在 repo 根目錄執行）：
    # 單張：來源 → 目標檔名（副檔名可省略，會補 .png）
    python scripts\\stamp_shots.py --product CRUX \\
        .playwright-mcp/CRUX-060_01_直属会员彈窗盈亏空白.png

    # 改名搬移：`來源=目標檔名`
    python scripts\\stamp_shots.py --product CRUX \\
        ".playwright-mcp/probe.png=CRUX-060_02_日報表未結算日盈亏欄空白.png"

    # 一次多張
    python scripts\\stamp_shots.py --product CRUX .playwright-mcp/CRUX-06*.png

    # 只檢查不搬（看看檔名合不合規、目標會不會覆蓋）
    python scripts\\stamp_shots.py --product CRUX --dry-run .playwright-mcp/*.png

前置條件：截圖**必須已經在瀏覽器裡標注過**（`ANNOTATE_JS` 疊紅框＋圖例）才搬。
          本腳本只蓋「已標注」的標記，**不會幫你畫框** —— 蓋在未標注的圖上等於騙過 lint。

回傳碼：0 成功／1 輸入有問題（**整批不執行**，不會出現搬一半的狀態）／2 環境問題（找不到 shots 目錄）。
測試：`tests/tooling/test_stamp_shots.py`
"""
import argparse
import glob
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from qa_common.shot import read_png_mark, stamp_png  # noqa: E402

from bug_paths import PRODUCT_DIRS, ROOT, SHOTS_DIR  # noqa: E402

# 檔名規範（見 `bug-report` skill「截圖的檔案規範」）
#   本地單：<ID>_<序2碼>_<說明>.png ／ 修復驗證圖 <ID>_fixed_<序2碼>_<說明>.png
#   改善建議：ID 走 `-S01` 序列（CRUX-S01），不佔 bug 流水號 → 數字前可有 `S`
#   純他人單（無本地 ID）：JIRA-<KEY>_… ，避免與本地 ID 撞命名空間
# ⚠️ `S` 那一段是實測補的：初版寫成 `-\d+` 會擋掉既有的 CRUX-S01／CRUX-S02 截圖。
# ⚠️ 前綴寫成 `[A-Z][A-Za-z]*`（首字母大寫、其後可小寫），不是 `[A-Z]+`：
#    新綜合的前綴是混合大小寫的 `Snotra`，只吃全大寫會整批擋掉
#    （2026-09-18 實測 Snotra-013 截圖被擋，只能手動蓋章而繞過本檢查）。
#    首字母仍要求大寫，才擋得住 `crux-060` 這種全小寫的筆誤。
NAME_RE = re.compile(r"^(JIRA-)?[A-Z][A-Za-z]*-S?\d+(_fixed)?_\d{2}_.+\.png$")


def _resolve(spec: str) -> tuple[str, str]:
    """`來源` 或 `來源=目標檔名` → (來源路徑, 目標檔名)。"""
    if "=" in spec:
        src, dst = spec.split("=", 1)
    else:
        src, dst = spec, os.path.basename(spec)
    if not dst.lower().endswith(".png"):
        dst += ".png"
    return src, dst


def main() -> int:
    ap = argparse.ArgumentParser(description="搬移 MCP 截圖到 bugs/shots/ 並蓋上已標注標記")
    ap.add_argument("--product", required=True, choices=sorted(PRODUCT_DIRS),
                    help="產品別名（CRUX／投注機器人／wbot／七星…）")
    ap.add_argument("--dry-run", action="store_true", help="只檢查，不搬也不蓋")
    ap.add_argument("--mark", default="mcp",
                    help="蓋進 PNG 的**來源**標記（預設 mcp；平台代搬用 auto）")
    ap.add_argument("--force", action="store_true", help="允許覆蓋既有的目標檔")
    ap.add_argument("specs", nargs="+", metavar="來源[=目標檔名]")
    args = ap.parse_args()

    shots_dir = os.path.join(ROOT, "docs", PRODUCT_DIRS[args.product], "bugs", SHOTS_DIR)
    if not os.path.isdir(shots_dir):
        print(f"❌ 找不到 {shots_dir}", file=sys.stderr)
        return 2

    # 回傳碼：0 成功／1 輸入有問題（整批未執行）／2 環境問題
    pairs: list[tuple[str, str]] = []
    problems: list[str] = []
    for spec in args.specs:
        src, dst = _resolve(spec)
        is_glob = any(c in src for c in "*?[")
        matches = glob.glob(src) if is_glob else [src]
        if not matches:
            problems.append(f"樣式沒有比對到任何檔案：{src}")
            continue
        for m in matches:
            pairs.append((m, dst if len(matches) == 1 and not is_glob else os.path.basename(m)))

    planned = []
    for src, dst in pairs:
        if not os.path.isfile(src):
            problems.append(f"來源不存在：{src}")
            continue
        if not NAME_RE.match(dst):
            problems.append(f"檔名不合規：{dst}\n"
                            f"    應為 <ID>_<序2碼>_<說明>.png、<ID>_fixed_<序2碼>_<說明>.png，"
                            f"或純他人單的 JIRA-<KEY>_…（見 bug-report skill）")
            continue
        target = os.path.join(shots_dir, dst)
        if os.path.exists(target) and not args.force:
            problems.append(f"目標已存在（要覆蓋請加 --force）：{dst}")
            continue
        planned.append((src, target, dst))

    if problems:
        print("⚠️ 有問題，未執行任何搬移：")
        for p in problems:
            print("  -", p)
        return 1

    for src, target, dst in planned:
        if args.dry_run:
            print(f"[dry-run] {src}  →  {os.path.relpath(target, ROOT)}")
            continue
        shutil.copyfile(src, target)
        if not stamp_png(target, "marks=%s" % args.mark):
            print(f"⚠️ {dst} 不是 PNG，已搬移但未蓋標記")
            continue
        # ⭐ 在**來源**旁邊留記號：本腳本是複製不是搬移，原檔會留在原地，
        #    呼叫端（平台的「待搬」提醒）需要一個方式知道「這張已經歸位了」。
        #    ⛔ 少了它，已經搬完的圖會一直被報成待辦（2026-08-25 實跑）。
        try:
            with open(src + ".filed", "w", encoding="utf-8", newline="\n") as f:
                f.write(dst)
        except OSError:
            pass                      # 記號寫不了不影響搬移本身
        print(f"✅ {dst}  （標記：{read_png_mark(target)}）")

    if not args.dry_run and planned:
        print(f"\n共 {len(planned)} 張 → docs/{PRODUCT_DIRS[args.product]}/bugs/{SHOTS_DIR}/")
        print("接著跑：python scripts\\gen_bug_index.py   （會順帶檢查截圖資產）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
