# -*- coding: utf-8 -*-
"""替 `bugs/_reports/` 與 `bugs/_handover/` 配一個**不會撞到別人**的檔名。

用途：這兩個目錄的檔名是「類型＋日期」的固定組合（`JIRA_Bug驗證報告_<日期>.md`、
      `交接_SideEffect待驗_<日期>.md`），**同一天有兩個 session 各驗一批就必然撞名**。
      而 `docs/**/bugs/` 不納入版控 —— **覆蓋掉就沒有 git 可以救**。

      skill 早就寫了「同日多批加 `_第N批`」（`jira-verify` §6／§9），但那是**格式說明**，
      不是**會被執行的檢查**；只要有人沒先 `ls` 就直接寫檔，規則等於不存在。
      本腳本把那句話變成一道指令：**問它要路徑，而不是自己拼檔名。**

      （事故：2026-08-14 一個 session 以固定檔名寫入驗證報告與交接檔，覆蓋了同日
        另一批「賠率變動設置五單重驗」的兩份產物。當次靠原作者 session 還在線、
        依 context 重打一次才救回來 —— 那是運氣，不是機制。）

使用方式（在 repo 根目錄執行）：
    # 要寫 JIRA 重驗報告 → 先問路徑
    python scripts\\new_bug_doc.py --product CRUX --kind report
    # 要寫 side effect 交接檔
    python scripts\\new_bug_doc.py --product CRUX --kind handover
    # 需求驗證報告／效能測試報告（要帶主題）
    python scripts\\new_bug_doc.py --product CRUX --kind requirement --topic CRUX-883綜合報表
    python scripts\\new_bug_doc.py --product CRUX --kind perf --topic A-7文本重複度

    # 長任務可先「佔位」：原子建檔（O_EXCL），確保寫檔前不會被別的 session 插隊
    python scripts\\new_bug_doc.py --product CRUX --kind report --reserve

    # 反向檢查：某個路徑現在能不能寫
    python scripts\\new_bug_doc.py --check "docs/CRUX/bugs/_reports/JIRA_Bug驗證報告_2026-08-14.md"

輸出：**最後一行就是可以直接寫入的相對路徑**（其餘為說明，皆帶前綴符號），
      方便 `... | Select-Object -Last 1` 或人眼直接取用。

回傳碼：0 正常／1 `--check` 判定該路徑已被佔用，或輸入有誤／2 環境問題（產品目錄不存在）。
測試：`tests/tooling/test_new_bug_doc.py`
"""
import argparse
import datetime
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bug_paths import PRODUCT_DIRS, ROOT, bugs_dir  # noqa: E402

# kind → (子目錄, 檔名樣板, 是否需要 --topic)
# 樣板中的 {topic} 與 {date} 會被替換；`_第N批` 一律加在**最後面**（副檔名之前）。
KINDS = {
    "report":      ("_reports",  "JIRA_Bug驗證報告_{date}",        False),
    "handover":    ("_handover", "交接_SideEffect待驗_{date}",     False),
    "requirement": ("_reports",  "需求驗證報告_{topic}_{date}",     True),
    "perf":        ("_reports",  "效能測試報告_{topic}_{date}",     True),
}

EXT = ".md"
# 佔位檔的內容 —— 不留空檔，免得被誤認為「寫壞的殘骸」而遭人刪除
RESERVE_STUB = (
    "<!-- 本檔由 scripts/new_bug_doc.py --reserve 佔位，內容待補。\n"
    "     若你不是佔位者且此檔長期為空，請先確認無人在寫再處理。 -->\n"
)


def allocate(dir_path, stem, ext=EXT):
    """在 `dir_path` 裡替 `stem` 找出下一個未被佔用的檔名。

    佔用判定同時涵蓋 `<stem>.md` 與 `<stem>_第N批.md` —— 只看其中一種會漏。
    回傳 `(建議檔名, 已存在的同系列檔名清單)`。
    """
    pattern = re.compile(r"^" + re.escape(stem) + r"(?:_第(\d+)批)?" + re.escape(ext) + r"$")
    taken, existing = set(), []
    if os.path.isdir(dir_path):
        for name in sorted(os.listdir(dir_path)):
            m = pattern.match(name)
            if m:
                existing.append(name)
                taken.add(int(m.group(1)) if m.group(1) else 1)
    n = 1
    while n in taken:
        n += 1
    return (stem + ext if n == 1 else "%s_第%d批%s" % (stem, n, ext)), existing


def _rel(path):
    """轉成 repo 相對路徑並統一用 `/`（Windows 的 `\\` 貼進 markdown 會被吃掉）。"""
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def _reserve(dir_path, stem, ext=EXT, limit=50):
    """原子佔位：以 O_EXCL 建檔，撞到就換下一個序號重試。

    ⚠️ 不能用「先 allocate 再 open」—— 兩個 session 同時 allocate 會拿到同一個名字。
       真正的互斥要靠 O_EXCL 本身。
    """
    os.makedirs(dir_path, exist_ok=True)
    for _ in range(limit):
        name, existing = allocate(dir_path, stem, ext)
        path = os.path.join(dir_path, name)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue          # 被插隊，重算
        with io.open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(RESERVE_STUB)
        return path, existing
    raise RuntimeError("連續 %d 次都被插隊，請人工確認 %s" % (limit, dir_path))


def main():
    ap = argparse.ArgumentParser(
        description="替 bugs/_reports/ 與 bugs/_handover/ 配一個不會撞到別人的檔名")
    ap.add_argument("--product", choices=sorted(PRODUCT_DIRS),
                    help="產品別名（CRUX／投注機器人／wbot／七星…）")
    ap.add_argument("--kind", choices=sorted(KINDS),
                    help="文件種類：report=JIRA 重驗報告／handover=side effect 交接／"
                         "requirement=需求驗證報告／perf=效能測試報告")
    ap.add_argument("--topic", help="主題（requirement／perf 必填），如 CRUX-883綜合報表")
    ap.add_argument("--date", help="日期 YYYY-MM-DD（預設今天）")
    ap.add_argument("--reserve", action="store_true",
                    help="立刻原子建檔佔位，避免長任務中途被別的 session 插隊")
    ap.add_argument("--check", metavar="路徑",
                    help="反向檢查：該路徑是否已被佔用（佔用回傳碼 1）")
    args = ap.parse_args()

    # ── 反向檢查模式 ──────────────────────────────────────────
    if args.check:
        path = args.check if os.path.isabs(args.check) else os.path.join(ROOT, args.check)
        if os.path.exists(path):
            print("✗ 已被佔用，**不可直接寫入**：%s" % _rel(path))
            print("  → 改用 `--product <產品> --kind <種類>` 取得可用檔名")
            return 1
        print("✓ 尚未被佔用，可寫入")
        print(_rel(path))
        return 0

    if not args.product or not args.kind:
        ap.error("未使用 --check 時，--product 與 --kind 皆為必填")
    subdir, template, need_topic = KINDS[args.kind]
    if need_topic and not args.topic:
        ap.error("--kind %s 需要 --topic（會成為檔名的一部分）" % args.kind)

    if args.date:
        try:
            datetime.date.fromisoformat(args.date)
        except ValueError:
            ap.error("--date 需為 YYYY-MM-DD，收到：%s" % args.date)
        date = args.date
    else:
        date = datetime.date.today().isoformat()

    base = bugs_dir(args.product)
    if not os.path.isdir(base):
        print("✗ 找不到 %s —— 產品目錄不存在？" % _rel(base))
        return 2
    dir_path = os.path.join(base, subdir)
    stem = template.format(date=date, topic=args.topic or "")

    if args.reserve:
        path, existing = _reserve(dir_path, stem)
        name = os.path.basename(path)
    else:
        name, existing = allocate(dir_path, stem)
        path = os.path.join(dir_path, name)

    if existing:
        print("⚠️ 同日已有 %d 份同類文件（**別覆蓋它們**）：" % len(existing))
        for e in existing:
            print("     %s" % e)
        print("   → 本次請用下列檔名（已自動遞增 _第N批）")
    else:
        print("✓ 同日尚無同類文件，可用原始檔名")
    if args.reserve:
        print("📌 已原子建檔佔位（內容為待補註解，直接覆寫即可）")
    if not os.path.isdir(dir_path):
        print("ℹ️ 目錄尚不存在，寫檔時會一併建立：%s/" % _rel(dir_path))
    print(_rel(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
