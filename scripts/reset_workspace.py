# -*- coding: utf-8 -*-
"""把範本原型的**產品實例**清乾淨，留下通用的 QA 工作流骨架。

用途
----
本工作區同時是「**標準測試工程師 AI 助手的專案結構**」的範本。
同事 clone 下來之後，要先把原型的產品（彩票三支）清掉，才能接自己的產品。

三層分離（`CLAUDE.md` 與 `README.md` 都有這張表）：
  ① 通用 QA 工作流   skill／scripts／tests/tooling／qa_common／jira_qa／test_platform  → **保留**
  ② 領域特定         testcase-design 的金流兩問與範例檔                              → **人工替換**
  ③ 實例特定         docs/<產品>／產品 skill／tools/<產品>_*／tests/<產品>            → **本腳本清除**

使用方式
--------
    python scripts\\reset_workspace.py                  # 預設只列出會刪什麼，不動檔案
    python scripts\\reset_workspace.py --product CRUX   # 只清一個產品
    python scripts\\reset_workspace.py --apply          # 真的執行
    python scripts\\reset_workspace.py --apply --force  # working tree 不乾淨時仍執行

前置條件
--------
⛔ **這是破壞性操作**，預設 dry-run。真的要跑之前：
   1. 確認 working tree 乾淨（本腳本會擋，除非 `--force`）—— 多 session 共用同一份 working tree 時，
      別人未提交的工作會被一起刪掉。
   2. 這是**不可逆**的：`docs/<產品>/bugs/` 整層不版控，刪掉沒有 git 可以救。

清完之後
--------
    python scripts\\new_product.py --id <產品> --docs-dir <目錄> --bug-prefix <前綴>
"""
import argparse
import collections
import io
import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 清空所有產品後，docs/INDEX.md 重設成這份骨架。
# ⚠️ 抬頭那幾段**刻意保留** —— 它們是通用的索引維護紀律，不是彩票專屬的。
INDEX_SKELETON = u"""# docs 文件索引

依產品專案分區。
> 說明：⭐ = 測試核心參考文件；🖼️ = 圖片；📊 = 試算表（需轉檔擷取）；📄 = Word（需轉檔擷取）。

> 💡 **本索引以「檔案」為鍵**（這個檔裡有什麼）。若你的問題是「**我要做 X，該讀哪一份**」，
> 先載入該產品的 skill —— 它們有**以意圖為鍵**的對照表。
>
> ⚠️ **新增或大改文件時，務必同步更新本索引的描述，且描述要涵蓋該檔的實際內容。**
> 教訓（範本原型踩過的）：某份 UI 對照檔曾長成 609 行、涵蓋六類主題，
> 但索引描述只提到約四成 —— 其他 session 即使讀了索引也找不到那些知識，等於沒寫。

---

## 共通（工作區維護，跨產品）

| 檔案 | 內容 |
| --- | --- |
| ⭐ `共通_工作區維護交接.md` | **工作區本身**（非任何產品）的交接活文件：§1 blocker／§2 待辦總覽／§3 本檔負責的路徑（＝`lint_docs` D6 的比對範圍）／§4 文件地圖／§5 工具與規範的現況／§6 維護規則。<br>★ **分工判準：這件事換一個產品還會不會存在？** 會 → 本檔；不會 → 產品交接檔 |

---

<!-- 接了產品之後，在這裡依 `## <產品名>` 分區列出該產品的文件。
     每一列：檔名 ＋ **涵蓋該檔實際內容**的描述。 -->
"""

# 腳本不碰、但清完之後需要人處理的東西。判斷成分太高，自動改只會改壞。
MANUAL = [
    (u"CLAUDE.md §1「專案定位」",
     u"產品對照表與領域敘述仍是範本原型的（彩票）。改成你自己的產品線"),
    (u"config/environments.md ／ environments.json",
     u"站台 URL 與測試帳密。整份換掉（敏感的放 config.local.json，不版控）"),
    (u".claude/skills/testcase-design/SKILL.md §5",
     u"「領域兩問」⑤不變量／⑥鑑別力是金流專屬的舉例，換成你的領域"),
    (u".claude/skills/testcase-design/references/",
     u"範例檔是彩票實例，**整份替換**成自己領域的例子"),
    (u".claude/skills/perf-test/",
     u"§0.1／§1／§2／§3／§5 是原型產品專屬；沒有壓測需求可整支刪掉"),
    (u"docs/共通_工作區維護交接.md",
     u"§1 blocker 與 §2 待辦是原型的狀態，清空重寫；§3／§4／§6 是結構，留著"),
    (u"tools/test_platform/registry/",
     u"平台的工具註冊檔仍指向原型工具，接自己的工具時一併換掉"),
]


def load_products(root):
    """讀 config/products.json，回傳 (整份 dict, products list)。"""
    path = os.path.join(root, "config", "products.json")
    data = json.load(io.open(path, encoding="utf-8"),
                     object_pairs_hook=collections.OrderedDict)
    return data, data.get("products") or []


def product_paths(p):
    """一個產品擁有的所有 repo 相對路徑。

    ⚠️ `extra_paths` 是必要的 —— 壓測工具（`tools/<x>_Performance`）與探索腳本
      不在標準四目錄裡，只靠推導會漏掉，留下孤兒目錄。
    """
    out = ["docs/%s" % p["docs_dir"],
           "tests/%s" % (p.get("tests_dir") or p["skill"]),
           "tools/%s" % (p.get("qa_tools_dir") or ""),
           ".claude/skills/%s" % p["skill"]]
    out += list(p.get("extra_paths") or [])
    return [x for x in out if x and not x.endswith("/")]


def plan(root, only=None):
    """回傳 (要刪的路徑清單, 要移除的產品清單)。只列存在的路徑。"""
    _, products = load_products(root)
    targets, removed = [], []
    for p in products:
        if only and p["id"] != only:
            continue
        removed.append(p)
        for rel in product_paths(p):
            if os.path.exists(os.path.join(root, rel.replace("/", os.sep))):
                targets.append(rel)
    # 同一個路徑可能被兩個產品宣告（不該發生，但宣告是人寫的）
    return sorted(set(targets)), removed


def apply_plan(root, targets, removed, reset_index=True):
    """真的刪除，並把產品自 products.json 移除。回傳剩下幾個產品。"""
    for rel in targets:
        full = os.path.join(root, rel.replace("/", os.sep))
        if os.path.isdir(full):
            shutil.rmtree(full)
        elif os.path.isfile(full):
            os.remove(full)

    data, products = load_products(root)
    ids = set(p["id"] for p in removed)
    data["products"] = [p for p in products if p["id"] not in ids]
    io.open(os.path.join(root, "config", "products.json"), "w",
            encoding="utf-8", newline="\n").write(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    # 全清空才重設索引；只清一個產品時保留（其他產品的條目還在裡面）
    if reset_index and not data["products"]:
        io.open(os.path.join(root, "docs", "INDEX.md"), "w",
                encoding="utf-8", newline="\n").write(INDEX_SKELETON)
    return len(data["products"])


def worktree_dirty(root):
    """working tree 有未提交異動時回傳那份清單，乾淨則回傳 []。"""
    try:
        out = subprocess.check_output(
            ["git", "-C", root, "status", "--porcelain"],
            stderr=subprocess.STDOUT).decode("utf-8", "replace")
    except Exception:
        return []                       # 不是 git repo 就不擋
    return [l for l in out.splitlines() if l.strip()]


def main():
    ap = argparse.ArgumentParser(description="清空範本原型的產品實例")
    ap.add_argument("--product", help="只清這一個產品（預設全部）")
    ap.add_argument("--apply", action="store_true", help="真的執行（預設只列出）")
    ap.add_argument("--force", action="store_true",
                    help="working tree 不乾淨時仍執行")
    a = ap.parse_args()

    targets, removed = plan(ROOT, only=a.product)
    if not removed:
        raise SystemExit("products.json 裡沒有%s可清的產品。"
                         % (("「%s」這個" % a.product) if a.product else ""))

    print("將移除 %d 個產品：%s" % (len(removed), "、".join(p["id"] for p in removed)))
    print("")
    for rel in targets:
        print("  %s %s" % ("[dry]" if not a.apply else "  -  ", rel))
    print("\n  config/products.json 移除上述產品定義")
    if a.apply is False:
        print("  （全清空時另會把 docs/INDEX.md 重設為骨架）")

    if not a.apply:
        print("\n⛔ 這是 dry-run，什麼都沒動。確認無誤後加 --apply。")
        print("   注意：`docs/<產品>/bugs/` 整層不版控，**刪掉沒有 git 可以救**。")
        return

    dirty = worktree_dirty(ROOT)
    if dirty and not a.force:
        print("\n⛔ working tree 有 %d 項未提交的異動，已中止。" % len(dirty))
        print("   多 session 共用同一份 working tree 時，別人未提交的工作會被一起刪掉。")
        print("   先處理乾淨，或確認風險後加 --force。")
        raise SystemExit(1)

    left = apply_plan(ROOT, targets, removed)
    print("\n✅ 已清除。products.json 剩 %d 個產品。" % left)

    print("\n腳本不動、需要人處理的（判斷成分太高，自動改只會改壞）：")
    for what, why in MANUAL:
        print("  · %-46s %s" % (what, why))

    print("""
接下來：
  python scripts\\new_product.py --id <產品> --docs-dir <目錄> --bug-prefix <前綴> --alias <英文名>
  python scripts\\lint_docs.py --product <產品>      驗收應為綠""")


if __name__ == "__main__":
    main()
