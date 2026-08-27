# -*- coding: utf-8 -*-
"""追蹤一個「規格值」散落在工作區的哪些地方（含 repo 外的 memory）。

用途：**改任何規格值之前先跑一次、改完再跑一次確認歸零。**
      2026-08-22 的一致性稽核找到四處互相矛盾的內容，成因**全都是「更新時只加不刪」**——
      CLAUDE.md 的 co-commit 範圍、利潤率檔的三種說法、INDEX 同一格前後矛盾、
      日誌類型 4 類 vs 5 類。規範早就寫著「索引型要直接取代」，
      但**沒有任何機制在執行時提醒**，這支腳本就是那個機制。

使用方式：
    python scripts\\trace_value.py --value "2025-01-02"
    python scripts\\trace_value.py --value "16.7" --ext .md .py      # 指定副檔名
    python scripts\\trace_value.py --value "中點" --no-memory        # 只掃 repo
    python scripts\\trace_value.py --value "舊公式" --quiet          # 只印統計（給收尾自檢用）

前置條件：無（純本機檔案讀取）。

★ 為什麼要連 memory 一起掃：memory 在 repo 外、沒有版控、沒有 lint —— 它是漂移最嚴重
  也最不可能被發現的一層，卻天天在 context 裡（稽核實證：漂移的全是裝了公式的那幾則）。

⚠️ 輸出會把**更正註記**（「原寫…」「已作廢」這類刻意保留的歷史說明）標成 `(註記)`。
   那些是**故意留著的**，不算殘留；只有沒標註記的才需要處理。
"""
import argparse
import io
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 掃描範圍：規格值可能落腳的地方（不含 bugs/ —— 那是快照，本來就該保留當時的值）
SCAN_DIRS = [
    "CLAUDE.md",
    os.path.join(".claude", "skills"),
    "docs",
    "scripts",
    os.path.join("tools", "test_platform", "docs"),
]
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "bugs", "allure-report",
              "allure-results", "cache", "logs", "demo"}
DEFAULT_EXT = (".md", ".py", ".json", ".ps1", ".txt")

# 疑似「更正註記」的行 —— 這類是刻意保留的歷史說明，不是殘留。
# ⚠️ 2026-08-22 擴充：原本只認「作廢／更正」等字樣，漏掉兩種很常見的寫法 ——
#    ① 對照表的左欄（`| 原本記的（❌） | 現行 |`），用 ❌／⛔ 標記而非文字
#    ② 變更說明（「由 X 放寬為 Y」「改採…口徑」），同一行同時含舊值與新值
#    實測時這兩種都被誤報成殘留，害人以為沒清乾淨。
NOTE_RE = re.compile(
    r"(原寫|原記|原註|原本寫|原本記|已作廢|作廢|更正|勿引用|勿再引用|歷史對照|先前寫|舊值|舊結論"
    r"|❌|⛔|~~"                                   # 對照表與刪除線的標記
    r"|放寬為|改採|已改為|已於\s*\d{4}-\d{2}-\d{2}|看似)")   # 變更說明的句型


def memory_dir():
    """由 repo 路徑推導 Claude 的 memory 目錄（`c:\\GitLab\\Automation` → `c--GitLab-Automation`）。"""
    key = ROOT.replace(":", "-").replace("\\", "-").replace("/", "-")
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", key, "memory")


def iter_files(exts, with_memory=True, mem_dir=None):
    for rel in SCAN_DIRS:
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            yield p, rel
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
            for fn in filenames:
                if fn.endswith(tuple(exts)):
                    full = os.path.join(dirpath, fn)
                    yield full, os.path.relpath(full, ROOT).replace("\\", "/")
    if with_memory:
        md = mem_dir or memory_dir()
        if os.path.isdir(md):
            for fn in sorted(os.listdir(md)):
                if fn.endswith(".md"):
                    yield os.path.join(md, fn), "memory/" + fn


def trace(value, exts, with_memory=True, mem_dir=None, quiet=False):
    hits, notes = [], []
    for full, rel in iter_files(exts, with_memory, mem_dir):
        try:
            lines = io.open(full, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if value in line:
                is_note = bool(NOTE_RE.search(line)) or line.lstrip().startswith(">")
                (notes if is_note else hits).append((rel, i, line.strip()))

    print('trace: "%s"' % value)
    if not hits and not notes:
        print("  ✅ 全庫零命中")
        return 0
    if hits:
        print("  ── 實際使用（%d 處，改值時這些都要處理）──" % len(hits))
        for rel, i, line in hits:
            print("  %-52s %s" % ("%s:%d" % (rel, i), line[:90] if not quiet else ""))
    if notes:
        print("  ── (註記) 疑似刻意保留的歷史說明（%d 處，通常不用動）──" % len(notes))
        if not quiet:
            for rel, i, line in notes[:12]:
                print("  %-52s %s" % ("%s:%d" % (rel, i), line[:90]))
            if len(notes) > 12:
                print("  …另 %d 處" % (len(notes) - 12))
    print("  —— 實際使用 %d 處｜註記 %d 處" % (len(hits), len(notes)))
    return 1 if hits else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="追蹤規格值散落在工作區（含 memory）的哪些地方")
    ap.add_argument("--value", required=True, help="要追蹤的值或字串")
    ap.add_argument("--ext", nargs="*", default=list(DEFAULT_EXT), help="副檔名（預設 .md .py .json .ps1 .txt）")
    ap.add_argument("--no-memory", action="store_true", help="不掃 repo 外的 memory")
    ap.add_argument("--memory-dir", help="自訂 memory 目錄（預設由 repo 路徑推導）")
    ap.add_argument("--quiet", action="store_true", help="只印統計，不印每一行內容")
    a = ap.parse_args(argv)
    return trace(a.value, a.ext, not a.no_memory, a.memory_dir, a.quiet)


if __name__ == "__main__":
    sys.exit(main())
