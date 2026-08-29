# -*- coding: utf-8 -*-
"""把指定的 Bug 單打包成對外提交副本至 `docs/<專案>/bugs/_deliver/<名稱>/`。

用途：交付給需求方／開發時，從工作區單一事實來源（`bugs/*.md`）生成副本，
      避免手動複製造成兩份漂移（教訓：舊 `bug回報_0728/` 與本體重複維護）。
使用方式：
    python scripts\\pack_bug_report.py --product CRUX --name 2026-08-04_虛盤最大損失 ^
        --ids CRUX-019 CRUX-020
前置條件：無（純本機檔案讀寫）。

行為：
  - 複製各 Bug 單，**移除 frontmatter 與遷移註記**（對外不需要），保留狀態列與全部內容。
  - ★ **正文轉成 JIRA wiki 標記**（`jira_markup`）—— 交付的下游就是 JIRA，
    貼過去之前不該還要人手動轉一次（2026-08-28 使用者裁示）。
    `--no-jira` 可關掉（要交的是 markdown 而不是 JIRA 時）。
  - 只複製該批 Bug 單實際引用到的截圖，路徑維持 `shots/`。
  - 目標資料夾已有手寫 `README.md`（缺陷彙總）時保留不覆蓋；沒有才生成基本彙總表。
"""
import argparse
import io
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bug_paths import ARCHIVE_DIR   # noqa: E402  單一事實來源，勿在此重新定義
from bug_paths import PRODUCT_DIRS as PRODUCTS   # noqa: E402
# ⛔ 轉換規則只有這一份 —— 勿在本檔再寫一份（見該檔檔頭）
from jira_markup import strip_headings, to_jira   # noqa: E402

# ⛔ 上一行就是「單一事實來源」的意思 —— 這裡曾經又硬編一份原型三產品，
#    於是同事接的產品打包不出來（2026-08-23 範本端到端驗收）。

# 對外副本不需要的工作區內部註記
DROP_NOTE = re.compile(r"^> （\d{4}-\d{2}-\d{2} 由 .*(拆出／改名|改名).*$|^> 遷移補註[:：]")


def load(path):
    return io.open(path, encoding="utf-8").read()


def strip_internal(text, jira=True):
    u"""去掉工作區內部的東西；`jira=True` 時順便轉成 JIRA wiki 標記。

    ⭐ 交付的下游就是 JIRA —— 貼過去之前不該還要人手動轉一次（2026-08-28 使用者裁示）。
    ⛔ 轉換的實作在 `jira_markup`，**不要在這裡再寫一份**：
       2026-08-26 那套規則只做在平台落檔那條路，這支與 `bug-report` skill 都沒跟上，
       於是同一個工作區同時產出兩種格式，而沒有任何機制會發現（2026-08-28 查出）。
    """
    text = re.sub(r"\A---\n.*?\n---\n+", "", text, flags=re.S)   # 去 frontmatter
    text = "\n".join(l for l in text.splitlines() if not DROP_NOTE.match(l)) + "\n"
    return strip_headings(to_jira(text)) if jira else text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, choices=sorted(PRODUCTS))
    ap.add_argument("--name", required=True, help="打包資料夾名，如 2026-08-04_虛盤最大損失")
    ap.add_argument("--ids", required=True, nargs="+", help="要打包的 Bug ID")
    # ⭐ 預設**轉成 JIRA wiki 標記** —— 交付的下游就是 JIRA。
    #    要交 markdown（例如貼進 wiki 或寄信）才關掉。
    ap.add_argument("--no-jira", action="store_true",
                    help="不要轉成 JIRA wiki 標記，維持 markdown")
    args = ap.parse_args()

    bugs_dir = os.path.join(ROOT, "docs", PRODUCTS[args.product], "bugs")
    dst = os.path.join(bugs_dir, "_deliver", args.name)
    os.makedirs(os.path.join(dst, "shots"), exist_ok=True)

    # ⚠️ Bug 單與截圖分佈在**主目錄**與 **old/（歸檔層）**兩處，兩層都要找 ——
    #    已結案的單常常正是要交付的對象（2026-08-11 導入歸檔後，只掃主目錄會直接報「找不到」）。
    layers = [bugs_dir, os.path.join(bugs_dir, ARCHIVE_DIR)]

    picked, shots = [], set()
    for bug_id in args.ids:
        src = None
        for layer in layers:
            if not os.path.isdir(layer):
                continue
            matches = [f for f in os.listdir(layer) if f.startswith(bug_id + "_")
                       and f.endswith(".md")]
            if matches:
                src, fname = os.path.join(layer, matches[0]), matches[0]
                break
        if not src:
            raise SystemExit("找不到 Bug 單（主目錄與 %s/ 皆無）: %s" % (ARCHIVE_DIR, bug_id))
        text = load(src)
        title = re.search(r"^title:\s*(.+)$", text, re.M)
        picked.append((bug_id, fname, title.group(1) if title else ""))
        io.open(os.path.join(dst, fname), "w", encoding="utf-8", newline="\n").write(
            strip_internal(text, jira=not args.no_jira))
        # 引用可能寫成 `shots/x.png` 或 `old/shots/x.png`、`../shots/x.png`，一律只取檔名
        shots.update(re.findall(r"shots/([^\s)`）]+\.png)", text))

    for s in sorted(shots):
        srcp = next((p for p in (os.path.join(l, "shots", s) for l in layers)
                     if os.path.exists(p)), None)
        if srcp:
            shutil.copy2(srcp, os.path.join(dst, "shots", s))
        else:
            print("  [warn] 截圖不存在:", s)

    print("  格式：%s" % ("markdown（--no-jira）" if args.no_jira
                          else "JIRA wiki 標記（可直接貼進 JIRA description）"))

    readme = os.path.join(dst, "README.md")
    if not os.path.exists(readme):
        lines = ["# %s Bug 回報 — %s" % (args.product, args.name), "",
                 "> 本資料夾為**對外提交用副本**，由 `scripts/pack_bug_report.py` 生成。",
                 "> 工作區單一事實來源：`docs/%s/bugs/`。" % PRODUCTS[args.product], "",
                 "| # | Bug 單 | 標題 |", "| --- | --- | --- |"]
        for i, (bug_id, fname, title) in enumerate(picked, 1):
            lines.append("| %d | [%s](%s) | %s |" % (i, bug_id, fname, title))
        lines.append("")
        io.open(readme, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    else:
        print("  README.md 已存在，保留不覆蓋")

    print("打包完成：%s（%d 份 Bug 單、%d 張截圖）"
          % (os.path.relpath(dst, ROOT), len(picked), len(shots)))


if __name__ == "__main__":
    main()
