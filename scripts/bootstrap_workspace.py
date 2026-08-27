# -*- coding: utf-8 -*-
"""把範本內建的通用 memory 裝進本機 —— **clone 之後跑一次**。

用途
----
memory 存在 `~/.claude/projects/<repo路徑key>/memory/`，**在 repo 外面、而且以路徑當 key**
—— 同事 clone 到自己的路徑之後，那個目錄是**空的**。
但其中十幾則是**通用 QA 教訓**（heredoc 反斜線坑、多 session 版控紀律、API vs UI 分工、
覆寫前查可還原性、驗證兩階段順序……），與產品無關，不該隨著本機一起消失。

本腳本把 `.claude/memory-seed/` 的種子複製進本機 memory 目錄，並把
`.claude/memory-seed/_index.md` 對應的索引行補進 `MEMORY.md`。

使用方式
--------
    python scripts\\bootstrap_workspace.py              # 直接安裝（已存在者跳過，不覆蓋）
    python scripts\\bootstrap_workspace.py --dry-run    # 只看會做什麼
    python scripts\\bootstrap_workspace.py --force      # 連已存在的也覆蓋（慎用）

前置條件
--------
無。可重複執行（冪等）：已安裝過的檔案預設跳過，`MEMORY.md` 的索引行不會重複加。

⚠️ 這支腳本**會寫到 repo 外面**（使用者家目錄下的 Claude memory），
所以每一步都會印出實際路徑，`--dry-run` 可先確認。
"""
import argparse
import io
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED_DIR = os.path.join(ROOT, ".claude", "memory-seed")
INDEX_SEED = os.path.join(SEED_DIR, "_index.md")

MEMORY_HEADER = u"# Memory Index\n\n"

# `_index.md` 裡真正要抄的行：`- [標題](檔名.md) — 鉤子`
INDEX_LINE_RE = re.compile(r"^- \[[^\]]+\]\(([^)]+\.md)\)")


def memory_dir():
    """由 repo 路徑推導 Claude 的 memory 目錄（`c:\\GitLab\\Automation` → `c--GitLab-Automation`）。

    ⚠️ 與 `scripts/trace_value.py` 的同名函式必須一致 —— 兩支都在找同一個目錄。
    """
    key = ROOT.replace(":", "-").replace("\\", "-").replace("/", "-")
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", key, "memory")


def seed_files():
    """種子檔清單（不含 `_` 開頭的內部檔）。"""
    if not os.path.isdir(SEED_DIR):
        return []
    return sorted(f for f in os.listdir(SEED_DIR)
                  if f.endswith(".md") and not f.startswith("_"))


def index_lines():
    """`_index.md` 中的索引行 → {檔名: 整行}。"""
    out = {}
    if not os.path.isfile(INDEX_SEED):
        return out
    for line in io.open(INDEX_SEED, encoding="utf-8"):
        m = INDEX_LINE_RE.match(line.rstrip("\n"))
        if m:
            out[m.group(1)] = line.rstrip("\n")
    return out


def install(mem_dir, dry_run=False, force=False):
    """複製種子並補索引。回傳 (已裝, 跳過, 新增的索引行數)。"""
    installed, skipped = [], []
    lines = index_lines()

    for name in seed_files():
        dst = os.path.join(mem_dir, name)
        if os.path.isfile(dst) and not force:
            skipped.append(name)
            continue
        if not dry_run:
            if not os.path.isdir(mem_dir):
                os.makedirs(mem_dir)
            shutil.copyfile(os.path.join(SEED_DIR, name), dst)
        installed.append(name)

    # ── MEMORY.md 索引 ─────────────────────────────────────
    index_path = os.path.join(mem_dir, "MEMORY.md")
    text = io.open(index_path, encoding="utf-8").read() \
        if os.path.isfile(index_path) else MEMORY_HEADER
    added = []
    for name in installed + skipped:          # 跳過的也要補索引（檔案在、索引可能缺）
        line = lines.get(name)
        # ⚠️ 判斷「已收錄」看的是**檔名**不是整行 —— 使用者可能改過標題或鉤子，
        #    比對整行會每次都重複加一條。
        if line and ("(%s)" % name) not in text:
            added.append(line)
    if added and not dry_run:
        if not text.endswith("\n"):
            text += "\n"
        io.open(index_path, "w", encoding="utf-8", newline="\n").write(
            text + "\n".join(added) + "\n")

    return installed, skipped, added


def next_steps() -> str:
    """接下來要做什麼 —— **依實際狀況給**，不是固定字串。

    ⚠️ 這份清單原本寫死，第 3 步叫人跑 `reset_workspace.py`「清掉範本原型的產品」
       —— 但**匯出的範本根本沒有原型產品**，同事照著跑只會看到「沒有可清的產品」。
       那一步只對「**clone 原型 repo**」的人成立。
       （2026-08-23 情境 A（剛拿到範本）走查發現。）
    """
    steps = [
        "1. scripts\\setup_test_env.ps1                     建 .venv 與測試相依",
        "2. copy config\\config.example.json config\\config.local.json   填自己的帳密（不版控）",
    ]
    n = 0
    try:
        import json
        cfg = os.path.join(ROOT, "config", "products.json")
        n = len(json.loads(io.open(cfg, encoding="utf-8").read()).get("products") or [])
    except Exception:                        # noqa: BLE001 —— 讀不到就當成乾淨範本
        pass
    if n:
        steps.append("3. python scripts\\reset_workspace.py              "
                     "先看這 %d 個產品要不要清掉（預設只列不刪）" % n)
    steps.append("%d. python scripts\\new_product.py --id <產品> ...   "
                 "接自己的第一個產品" % (len(steps) + 1))
    tail = "" if n else "\n\n   （這是一份乾淨的範本，沒有產品要清）"
    return ("\n接下來（詳見工作區根目錄的 README.md）：\n  "
            + "\n  ".join(steps) + tail + "\n")


def main():
    ap = argparse.ArgumentParser(description="把範本內建的通用 memory 裝進本機")
    ap.add_argument("--dry-run", action="store_true", help="只印出會做什麼，不寫檔")
    ap.add_argument("--force", action="store_true", help="連已存在的 memory 也覆蓋（慎用）")
    a = ap.parse_args()

    mem = memory_dir()
    seeds = seed_files()
    if not seeds:
        raise SystemExit("找不到任何種子：%s" % SEED_DIR)

    print("種子來源：%s（%d 則）" % (SEED_DIR, len(seeds)))
    print("安裝目標：%s" % mem)
    if a.dry_run:
        print("（--dry-run，不會寫任何檔案）")
    print("")

    installed, skipped, added = install(mem, dry_run=a.dry_run, force=a.force)
    for n in installed:
        print("  %s 安裝  %s" % ("[dry]" if a.dry_run else "  +  ", n))
    for n in skipped:
        print("  跳過（已存在） %s" % n)
    if added:
        print("\n  MEMORY.md 補 %d 條索引" % len(added))
    else:
        print("\n  MEMORY.md 索引無須變動")

    print(next_steps())


if __name__ == "__main__":
    main()
