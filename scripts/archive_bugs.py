# -*- coding: utf-8 -*-
"""把已結案的 Bug 單與其截圖搬到 `docs/<專案>/bugs/old/`，並改寫所有引用路徑。

用途：Bug 單持續增長，已結案的單留在主目錄會稀釋活躍單。本腳本把結案單移入歸檔層，
      **Bug 單只會存在於兩個位置：主目錄 或 old/**。

使用方式：
    python scripts\\archive_bugs.py --product CRUX                # 預演（預設，不動檔案）
    python scripts\\archive_bugs.py --product CRUX --yes          # 實際執行
    python scripts\\archive_bugs.py --product CRUX --status fixed # 只歸檔特定狀態
    python scripts\\archive_bugs.py --product CRUX --restore CRUX-019   # 從 old/ 取回

前置條件：無（純本機檔案讀寫）。執行後會自動重跑 gen_bug_index.py。

歸檔判準：**看狀態，不看日期。**
    可歸檔：fixed（已修復重驗通過）／rejected（查證非缺陷）／superseded（由後續單接續）
    不歸檔：open（未修復，無論多久）／suggestion（改善建議隨時可能被採納）
    ⚠️ 用「N 天前」當判準是錯的 —— 90 天前仍未修復的 open 單，
       比 10 天前的 fixed 單更需要留在手邊。

搬移規則
--------
1. **圖跟著擁有者走**：檔名前綴為歸檔單 ID 的截圖一併搬到 `old/shots/`。
   共用圖（被多張單引用）不特別處理 —— 引用路徑會被改寫成正確的相對路徑。
2. **JIRA-* 圖不搬**：那些屬於純他人單，本地沒有對應的歸檔對象。
3. **引用全面改寫**：主目錄單、old/ 單、`_reports/`、`_handover/` 內所有指向
   被搬動檔案的路徑都會重算相對路徑。
4. **`_deliver/` 不動**：已寄出的交付快照，依 CLAUDE.md §6 不追改。
"""
import argparse
import glob
import io
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_bug_index import PRODUCTS, ARCHIVE_DIR, load_bugs  # noqa: E402
from bug_paths import ID_PREFIX  # noqa: E402

ARCHIVABLE = ("fixed", "rejected", "superseded")
# 掃描這些位置的 .md 來改寫引用（_deliver 刻意排除）
REF_DIRS = ("", ARCHIVE_DIR, "_reports", "_handover")

# ⚠️ 前綴**必須包含** `ID_PREFIX` 目前登記的值，不可只寫死 CRUX／WBOT／QX ——
#    2026-08-26 接「新綜合」（前綴 XINZONGHE）時發現 `lint_bug_assets.py` 犯過同一種寫死，
#    順手一併檢查修掉這裡，否則歸檔新產品的單時 DOC_RE／圖片配對會完全掃不到。
#    ⚠️ 但也與 CRUX／WBOT／QX 取聯集（理由同 `lint_bug_assets.py` 的 `_PREFIXES` 註解）：
#    這三個是 `tests/tooling/` 通用測資固定寫死的樣板前綴，不論這個 clone 接了哪個產品都要認得。
_PREFIXES = "|".join(re.escape(p) for p in
                      sorted(set(ID_PREFIX.values()) | {"CRUX", "WBOT", "QX"}))

# ⚠️ 各 pattern 前置 `(?<!\\)`：Markdown 連結**文字**常有跳脫（如 `[../\_reports/x.md](…)`），
#    若不排除，改寫會插在跳脫字元後產生 `../\../_reports/` 這種壞路徑（2026-08-11 沙箱實測踩到）。
IMG_RE = re.compile(r"(?<!\\)((?:\.\./)*(?:%s/)?shots/)([^\s\)\`\"'）]+\.(?:png|jpg|jpeg|gif))"
                    % ARCHIVE_DIR)
DOC_RE = re.compile(
    r"(?<!\\)((?:\.\./)*(?:%s/)?)((?:%s)-(?:\d{3}|S\d{2})_[^\s\)\`\"'）]+\.md)"
    % (ARCHIVE_DIR, _PREFIXES))
# 指向 bugs/ 底下其他子目錄的引用（報告、交接、交付、分組檢視）。
# 只在「引用者自己被搬走」時才需要改寫；雙方都不動時碰它只會製造風險。
SUB_RE = re.compile(
    r"(?<!\\)((?:\.\./)*)((?:_reports|_handover|_deliver|_view)/[^\s\)\`\"'）]+\.md)")


def rel(target, from_dir):
    """target/from_dir 皆相對 bugs_dir（空字串＝bugs_dir 本身）；回傳 posix 風格相對路徑"""
    p = os.path.relpath(target or ".", from_dir or ".")
    return p.replace("\\", "/")


def ref_files(bugs_dir):
    """所有需要改寫引用的檔案 → [(絕對路徑, 相對 bugs_dir 的所在目錄)]"""
    out = []
    for d in REF_DIRS:
        pattern = os.path.join(bugs_dir, d, "*.md") if d else os.path.join(bugs_dir, "*.md")
        for p in sorted(glob.glob(pattern)):
            if os.path.basename(p) == "BUG清單.md":
                continue
            out.append((p, d))
    return out


def build_plan(product, bugs_dir, statuses):
    """算出要搬哪些單、哪些圖。回傳 (docs, imgs)：{來源相對路徑: 目標相對路徑}"""
    bugs = load_bugs(bugs_dir, quiet=True)
    targets = [b for b in bugs if not b.get("_archived") and b.get("status") in statuses]
    ids = {b["id"] for b in targets}

    docs = {}
    for b in targets:
        docs[b["_file"]] = "%s/%s" % (ARCHIVE_DIR, b["_file"])

    imgs = {}
    shots_dir = os.path.join(bugs_dir, "shots")
    for f in sorted(os.listdir(shots_dir)) if os.path.isdir(shots_dir) else []:
        if not os.path.isfile(os.path.join(shots_dir, f)):
            continue
        if f.startswith("JIRA-"):
            continue                     # 他人單的圖，本地無歸檔對象
        m = re.match(r"^((?:%s)-(?:\d{3}|S\d{2}))_" % _PREFIXES, f)
        if m and m.group(1) in ids:
            imgs["shots/%s" % f] = "%s/shots/%s" % (ARCHIVE_DIR, f)
    return targets, docs, imgs


def rewrite(bugs_dir, docs, imgs, do_it):
    """改寫所有引用路徑；回傳被改動的檔案數"""
    moved_img = {os.path.basename(k): v for k, v in imgs.items()}
    moved_doc = {os.path.basename(k): v for k, v in docs.items()}
    # 未搬動者的最終位置（供已在 old/ 的檔案回指主目錄）
    def img_target(name):
        return moved_img.get(name, "shots/%s" % name)

    def doc_target(name):
        return moved_doc.get(name, name)

    changed = 0
    for path, loc in ref_files(bugs_dir):
        # 檔案自己若要被搬走，改寫後的相對基準是新位置
        rel_self = os.path.relpath(path, bugs_dir).replace("\\", "/")
        new_loc = os.path.dirname(docs.get(rel_self, rel_self))
        text = io.open(path, encoding="utf-8").read()

        def fix_img(m):
            name = m.group(2)
            return "%s%s" % (rel(os.path.dirname(img_target(name)), new_loc) + "/", name)

        def fix_doc(m):
            name = m.group(2)
            tgt = doc_target(name)
            d = os.path.dirname(tgt)
            prefix = (rel(d, new_loc) + "/") if d or new_loc else ""
            if prefix == "./":
                prefix = ""
            return "%s%s" % (prefix, name)

        def fix_sub(m):
            tgt = m.group(2)                       # 相對 bugs_dir 的固定位置
            prefix = rel(os.path.dirname(tgt), new_loc)
            return "%s/%s" % (prefix, os.path.basename(tgt)) if prefix != "." else tgt

        new = IMG_RE.sub(fix_img, text)
        new = DOC_RE.sub(fix_doc, new)
        if new_loc != os.path.dirname(rel_self):      # 只有自己被搬走才需要調整
            new = SUB_RE.sub(fix_sub, new)
        if new != text:
            changed += 1
            if do_it:
                io.open(path, "w", encoding="utf-8", newline="\n").write(new)
    return changed


def move_all(bugs_dir, docs, imgs, do_it):
    if not do_it:
        return
    os.makedirs(os.path.join(bugs_dir, ARCHIVE_DIR, "shots"), exist_ok=True)
    for src, dst in list(docs.items()) + list(imgs.items()):
        shutil.move(os.path.join(bugs_dir, src), os.path.join(bugs_dir, dst))


def restore(bugs_dir, bug_id, do_it):
    """把某張單與其圖從 old/ 取回主目錄（誤歸檔或需重新追蹤時）"""
    docs, imgs = {}, {}
    for p in glob.glob(os.path.join(bugs_dir, ARCHIVE_DIR, "%s_*.md" % bug_id)):
        n = os.path.basename(p)
        docs["%s/%s" % (ARCHIVE_DIR, n)] = n
    for p in glob.glob(os.path.join(bugs_dir, ARCHIVE_DIR, "shots", "%s_*" % bug_id)):
        n = os.path.basename(p)
        imgs["%s/shots/%s" % (ARCHIVE_DIR, n)] = "shots/%s" % n
    if not docs:
        print("  old/ 內找不到 %s" % bug_id)
        return None, None
    print("  %s %s：1 單 + %d 圖 → 主目錄" % ("取回" if do_it else "[預演] 將取回", bug_id, len(imgs)))
    return docs, imgs


def main():
    ap = argparse.ArgumentParser(description="把已結案 Bug 單與截圖歸檔到 old/")
    ap.add_argument("--product", required=True, choices=list(PRODUCTS))
    ap.add_argument("--status", default=",".join(ARCHIVABLE),
                    help="要歸檔的狀態，逗號分隔（預設 fixed,rejected,superseded）")
    ap.add_argument("--restore", metavar="ID", help="反向操作：把指定 ID 從 old/ 取回")
    ap.add_argument("--yes", action="store_true", help="實際執行（未加則只預演）")
    args = ap.parse_args()

    bugs_dir = os.path.join(PRODUCTS[args.product], "bugs")
    do_it = args.yes

    if args.restore:
        docs, imgs = restore(bugs_dir, args.restore, do_it)
        if not docs:
            return
    else:
        statuses = tuple(s.strip() for s in args.status.split(","))
        bad = [s for s in statuses if s == "open"]
        if bad:
            print("⛔ 拒絕歸檔 open 單 —— 未修復的缺陷必須留在主目錄。")
            sys.exit(1)
        targets, docs, imgs = build_plan(args.product, bugs_dir, statuses)
        if not docs:
            print("沒有符合條件（%s）的單可歸檔。" % ",".join(statuses))
            return
        print("%s %d 單 + %d 圖 → %s/" % (
            "歸檔" if do_it else "[預演] 將歸檔", len(docs), len(imgs), ARCHIVE_DIR))
        by_status = {}
        for b in targets:
            by_status.setdefault(b["status"], []).append(b["id"])
        for st, ids in sorted(by_status.items()):
            print("  %-11s %d：%s" % (st, len(ids), "、".join(ids)))

    changed = rewrite(bugs_dir, docs, imgs, do_it)
    print("  引用改寫：%d 個檔案%s" % (changed, "" if do_it else "（預演）"))
    move_all(bugs_dir, docs, imgs, do_it)

    if not do_it:
        print("\n（預演，未動任何檔案；確定要執行請加 --yes）")
        return

    print("\n重跑索引…")
    subprocess.call([sys.executable, os.path.join(ROOT, "scripts", "gen_bug_index.py"),
                     args.product])


if __name__ == "__main__":
    main()
