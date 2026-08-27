# -*- coding: utf-8 -*-
"""替交接活文件的待辦項配一個不撞號的編號（T／D／B／P…）。

用途：多 session 併行時，交接檔的待辦編號**沒有任何機制擋重複** ——
      不像 Bug ID 有 `gen_bug_index.py --next-id`。規範要求「寫入前當下 grep 重查」，
      但靠自律沒擋住：`CRUX_功能驗證交接.md` 的 **T34 與 T43 各被用了兩次**（2026-08-22 稽核發現）。
      本腳本把那條規範變成一支會執行的指令。

使用方式：
    python scripts\\next_todo_id.py --handover docs\\共通_工作區維護交接.md --kind T
    python scripts\\next_todo_id.py --handover <檔> --kind T --check      # 只檢查重複，不配號
    python scripts\\next_todo_id.py --scan                                # 掃所有交接檔的重複編號

前置條件：無（純本機檔案讀取）。

★ 認得三種寫法：`| T1 |`（一般）、`| **T21** |`（強調）、`| ~~T22~~ |`（已完成劃掉）——
  **劃掉的也算佔用**，編號不回收（比照 Bug ID 的紀律）。
"""
import argparse
import glob
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

# 交接活文件的檔名慣例（與 lint_docs 的 HANDOVER_SUFFIX 同一套）
HANDOVER_GLOBS = [
    os.path.join(ROOT, "docs", "*驗證交接.md"),
    os.path.join(ROOT, "docs", "*維護交接.md"),
    os.path.join(ROOT, "docs", "*", "*驗證交接.md"),
    os.path.join(ROOT, "docs", "*", "*維護交接.md"),
]

# 取「表格第一欄」開頭的編號。允許 ~~ 與 ** 任意組合的包裹。
# ⚠️ 不可要求編號後面緊接 `|` —— 實際格式有 `| ~~**T5**~~ ✅ **2026-08-21 完成** |`
#    （編號後還有完成註記才到欄位分隔）。漏認它就會把已用的號再配一次，
#    而那正是本腳本要防的事（2026-08-22 實測踩到）。
ID_RE = re.compile(r"^\s*~{0,2}\*{0,2}~{0,2}([A-Z]{1,2})(\d+)")


def collect(path):
    """回傳 {kind: {num: [行號…]}}。同一個號出現多行＝撞號。"""
    used = {}
    for i, line in enumerate(io.open(path, encoding="utf-8").read().splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        first = s.strip("|").split("|")[0]      # 表格第一欄
        m = ID_RE.match(first)
        if m:
            kind, num = m.group(1), int(m.group(2))
            used.setdefault(kind, {}).setdefault(num, []).append(i)
    return used


def report_dupes(path, used, prefix="  "):
    dupes = [(k, n, ls) for k, d in used.items() for n, ls in d.items() if len(ls) > 1]
    for kind, num, lines_ in sorted(dupes):
        print("%s⚠️ %s%d 被用了 %d 次（行 %s）—— 依規範改號的是**後寫入者**"
              % (prefix, kind, num, len(lines_), "、".join(map(str, lines_))))
    return len(dupes)


def main(argv=None):
    ap = argparse.ArgumentParser(description="交接檔待辦編號的防撞配號")
    ap.add_argument("--handover", help="交接檔路徑（相對 repo root 或絕對）")
    ap.add_argument("--kind", default="T", help="編號種類（預設 T）")
    ap.add_argument("--check", action="store_true", help="只檢查重複，不配號")
    ap.add_argument("--scan", action="store_true", help="掃所有交接檔的重複編號")
    a = ap.parse_args(argv)

    if a.scan:
        files = sorted(set(sum((glob.glob(g) for g in HANDOVER_GLOBS), [])))
        print("掃描 %d 份交接活文件" % len(files))
        total = 0
        for f in files:
            used = collect(f)
            n = report_dupes(f, used, prefix="  %s  " % os.path.relpath(f, ROOT))
            if n:
                total += n
        print("  —— %s" % ("✅ 無重複編號" if not total else "共 %d 組重複" % total))
        return 1 if total else 0

    if not a.handover:
        ap.error("需要 --handover <交接檔> 或 --scan")
    path = a.handover if os.path.isabs(a.handover) else os.path.join(ROOT, a.handover)
    if not os.path.isfile(path):
        raise SystemExit("找不到交接檔：%s" % path)

    used = collect(path)
    kind = a.kind.upper()
    nums = sorted(used.get(kind, {}))
    print("%s — %s 編號現況" % (os.path.basename(path), kind))
    if nums:
        print("  已用 %d 個：%s%s" % (len(nums), "、".join("%s%d" % (kind, n) for n in nums[:14]),
                                   "…" if len(nums) > 14 else ""))
    else:
        print("  尚未使用任何 %s 編號" % kind)
    dup = report_dupes(path, {kind: used.get(kind, {})})

    if not a.check:
        nxt = (max(nums) + 1) if nums else 1
        print("\n  下一個可用編號：**%s%d**" % (kind, nxt))
        print("  ⚠️ 編號不回收（劃掉的也算佔用）；寫入後若他人已先用，改號的是後寫入者。")
    return 1 if dup else 0


if __name__ == "__main__":
    sys.exit(main())
