# -*- coding: utf-8 -*-
"""檢查 `docs/` 的文件索引是否失真、是否有名不副實的大檔。

用途：2026-08-11 拆檔的根因是「知識寫了但找不到」——`UI元素對照_總監後台.md` 長成 609 行、
      涵蓋六類主題，而 `docs/INDEX.md` 的描述只提到約四成，其他 session 依意圖搜尋撲空。
      本腳本把「索引描述要涵蓋實際內容」這條規範變成可執行的檢查。

使用方式：
    python scripts\\lint_docs.py                    # 檢查全部產品
    python scripts\\lint_docs.py --product CRUX     # 只檢查指定產品
    python scripts\\lint_docs.py --verbose          # 列出每個未涵蓋的章節

前置條件：無（純本機檔案讀寫）。
離開碼：有 ❌ 錯誤時回 1，其餘回 0。

⚠️ 本腳本只能指出「這裡不對勁」，**不能替你決定內容該搬去哪** ——
   那是語義判斷，仍需人＋Claude 依 `browser-ops` §7 的分流表處理。

檢查項目
--------
❌ D1 斷連結    INDEX.md 列了某檔，但檔案不存在
⚠️ D2 未登記    docs/<產品>/ 下的文件不在 INDEX.md 中
⚠️ D3 描述失真  INDEX 描述未涵蓋該檔的多數章節（本次拆檔的根因）
⚠️ D4 檔案偏大  行數或章節數超標，可能混了多類主題該拆
⚠️ D5 skill 斷連結  產品 skill 意圖對照表指向的檔案不存在
⚠️ D6 交接檔過期  交接活文件的「最後更新」落後該產品最新 commit 超過 1 天
⚠️ D7 規格被改動  相對 HEAD 刪改到帶裁定來源（「…裁定」「as-designed」）的規格行 ——
                  實測與規格不符時那是**缺陷**，要開單而不是改文件
❌ D8 指標失效    skill 之間（與對 CLAUDE.md）的 `§N.M` 章節指標指不到 ——
                  章節重編號後會**靜默失效**，是跨檔漂移的頭號來源。
                  **含子項**：`§2④` 的 ④、`§1 A` 的 A 也會驗（該章節有子項標題時才驗）
⚠️ D9 編號重複    交接活文件的待辦編號（T／D／B…）被用了兩次
⚠️ D10 積壓       待補回歸案例／未開立／side effect 未復查 —— 這三類平常完全看不見
❌ D11 範本白名單  `export_template.py` 的白名單沒涵蓋到某個路徑 ——
                  漏分類的通用檔會**無聲地不再匯出**，漏分類的產品檔會**被夾帶出去**
❌ D13 鏡像落後    原版動了會匯出的路徑，乾淨範本鏡像卻沒跟上（要跑 `--sync`）——
                  只在原版工作區、且設過 `.template-mirror` 時才查
❌ D12 產品沒進索引  `config/products.json` 有這個產品，`docs/INDEX.md` 卻沒有它的分區 ——
                  沒有分區就沒有地方登記文件（`writeback` 四個必做的第一條），
                  **測試平台寫機制文件時的自動登記也永遠不會生效**
"""
import argparse
import glob
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
SKILLS = os.path.join(ROOT, ".claude", "skills")

# ── 產品定義：以 config/products.json 為單一來源（比照 bug_paths.py）────
#   讀不到時退回硬編碼，確保設定檔壞掉不會讓整支 lint 停擺。
_FALLBACK_PRODUCTS = ["CRUX", "七星", "投注機器人"]
_FALLBACK_SKILL = {"CRUX": "crux", "七星": "qixing", "投注機器人": "wbot"}


def _load_products():
    """回傳 (PRODUCTS, PRODUCT_SKILL, 各產品的 handover_scope 合併結果)。"""
    path = os.path.join(ROOT, "config", "products.json")
    try:
        import json
        data = json.load(io.open(path, encoding="utf-8"))
        items = data["products"]
    except Exception:
        return list(_FALLBACK_PRODUCTS), dict(_FALLBACK_SKILL), {}
    names, skills, scope = [], {}, {}
    for p in items:
        names.append(p["id"])
        skills[p["id"]] = p.get("skill") or (p.get("aliases") or [p["id"]])[0]
        scope.update(p.get("handover_scope") or {})
    return names, skills, scope


PRODUCTS, PRODUCT_SKILL, _PRODUCT_SCOPE = _load_products()

# 這些目錄不納入索引檢查
SKIP_DIRS = ("bugs", "需求驗證", "探索截圖", "CRUX_bet_demo", "七星彩計算")
SKIP_FILES = ("INDEX.md", "README.md")

BIG_LINES = 500      # 行數門檻
BIG_SECTIONS = 10    # `##` 章節數門檻
COVERAGE_MIN = 0.5   # 描述涵蓋率門檻（低於此值才報，避免把「可以更好」當成「錯」）

# 章節標題的裝飾：emoji、★、編號、日期、括號註記、全形空白後的補充
DECOR = re.compile(r"^[\s#]*(?:[←-⯿\U0001F000-\U0001FAFF]️?\s*)*"
                   r"(?:\d+(?:\.\d+)*[\.、]?\s*)*")
TAIL = re.compile(r"[（(　※].*$")


def clean_heading(h):
    """`### ⚠️ 手動關盤與「關盤不可逆」（2026-08-10 實測）` → `手動關盤與「關盤不可逆」`"""
    h = DECOR.sub("", h)
    h = TAIL.sub("", h)
    return h.strip(" 　*_`★⭐⚠️⛔📌💡→")


# 純結構性標題：每份文件都會有，不帶主題資訊，列入覆蓋率只會稀釋訊號
BOILERPLATE = re.compile(
    r"^(快速索引|相關文件|相關|附錄|總覽|目錄|摘要|結論|結論摘要|前提與但書|產出物|待辦|"
    r"參考|註記|備註|環境與前置|測試環境|回歸測試|文件地圖|使用方式|前置條件)")

# 檔內可用此標記豁免 D4（確認過主題單一、只是內容深）
ALLOW_BIG = re.compile(r"<!--\s*lint-docs:\s*allow-big\s*-->")

# ── D6 交接活文件 ───────────────────────────────────────────────
# 交接檔一律以 `驗證交接.md` 結尾（見 `browser-ops` §7.1）。
# 這條命名規則同時是本檢查的偵測依據 —— 取別的名字就不會被檢查到。
# 刻意**不**比對 `交接清單_*.md`／`交接_SideEffect待驗_*.md`：那些是一次性快照，
# 任務結束就凍結，本來就該停在當時的日期。
# 交接活文件的檔名後綴。產品線用「…驗證交接.md」；跨產品的工作區維護用「…維護交接.md」
# （2026-08-14 新增 `docs/共通_工作區維護交接.md` 時擴充 —— 只認前者的話新檔完全不會被檢查到）。
HANDOVER_SUFFIX = ("驗證交接.md", "維護交接.md")
STALE_DAYS = 1

# 跨產品的交接檔放在 `docs/` 底下（不屬於任何 `docs/<產品>/`），
# 故不會被 `listed_files(product_dir)` 掃到，要另外指名。
COMMON_HANDOVERS = ["共通_工作區維護交接.md"]

# 每份交接檔「負責哪些路徑」——拿這些路徑的最新 commit 日期跟它的更新日期比。
# 為什麼不用全 repo 最新 commit：七星沒人動的期間，它的交接檔本來就該保持不動，
# 拿 CRUX 的 commit 去逼它更新只會製造雜訊，久了整條檢查就被忽略。
# 鍵為檔名；值為 git pathspec（可用 `:(exclude)` 排除）。未列者退回 `docs/<產品>`。
HANDOVER_SCOPE = {
    # 跨產品的工作區維護：只涵蓋**共用基礎設施**（CLAUDE.md §8.3），
    # 不含任何 docs/<產品>/ —— 那些各自有自己的交接檔，重複涵蓋只會製造雜訊。
    # ⚠️ 這一條**刻意留在程式碼裡**：它與任何產品無關，清空產品時不該跟著消失。
    "共通_工作區維護交接.md": [
        "CLAUDE.md", ".claude/skills", "scripts", "tools/qa_common", "tools/jira_qa",
        "tools/test_platform",   # 2026-08-19 統一測試平台（本體屬共用基礎設施）
        "tests/tooling", "docs/INDEX.md", "pyproject.toml", "requirements.txt"],
}
# 各產品的 scope 來自 config/products.json 的 `handover_scope`（2026-08-22 移出）
HANDOVER_SCOPE.update(_PRODUCT_SCOPE)

# 「最後更新：2026-08-13」或 H1 的「（2026-08-06 更新）」都認
UPDATED_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _days_between(a, b):
    """a、b 皆為 (y, m, d) tuple，回傳 b − a 的天數。"""
    import datetime
    return (datetime.date(*b) - datetime.date(*a)).days


def handover_updated_date(path):
    """從交接檔前 15 行找出「最後更新」日期，回傳 (y, m, d)；找不到回 None。

    只掃前 15 行是刻意的 —— 內文到處都是日期（實測日、佈版日、教訓日期），
    整份掃會抓到不相干的值，比不檢查更糟。
    """
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            head = [next(f, "") for _ in range(15)]
    except OSError:
        return None
    for line in head:
        if "更新" not in line:
            continue
        m = UPDATED_RE.search(line)
        if m:
            return tuple(int(x) for x in m.groups())
    return None


def git_last_commit_date(pathspec):
    """該組路徑最新一筆 commit 的日期 (y, m, d)；git 不可用或無 commit 回 None。"""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--date=short", "--format=%cd", "--"] + list(pathspec),
            cwd=ROOT, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None                      # 沒有 git／不是 repo → 靜默跳過本檢查
    if out.returncode != 0:
        return None
    m = UPDATED_RE.search(out.stdout.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def check_handovers(product, by_name):
    """D6：交接活文件是否跟上該產品的最新 commit。"""
    warnings = []
    for name, path in sorted(by_name.items()):
        if not name.endswith(HANDOVER_SUFFIX):
            continue
        scope = HANDOVER_SCOPE.get(name, ["docs/%s" % product])
        commit = git_last_commit_date(scope)
        if commit is None:
            continue                     # 該範圍還沒有任何 commit，或無 git
        doc = handover_updated_date(path)
        if doc is None:
            warnings.append(
                "D6 交接檔無日期 %s 前 15 行找不到「最後更新」日期 —— "
                "請在檔頭加一行 `> **最後更新：YYYY-MM-DD**`，否則無法檢查是否跟上進度" % name)
            continue
        lag = _days_between(doc, commit)
        if lag > STALE_DAYS:
            warnings.append(
                "D6 交接檔過期 %s 標示 %04d-%02d-%02d，但其負責範圍最新 commit 是 "
                "%04d-%02d-%02d（落後 %d 天）—— 有人做了事卻沒更新交接檔？"
                "收尾紀律見 `browser-ops` §7.1" % ((name,) + doc + commit + (lag,)))
    return warnings


# ── D7：帶裁定來源的「規格」行被刪改 ────────────────────────────
# 這些字樣代表該行陳述的是**經人裁定的規格**，而不是「上次量到的值」。
# 兩者被實測推翻時的處置完全相反（見 CLAUDE.md §6「實測與文件不符時」）：
#   規格 → 系統不符＝**缺陷**，要開單；觀測 → 更新紀錄即可。
# ⚠️ 本檢查存在的理由：2026-08-14 有 session 把一段開頭就寫著
#   「這是規格，不是缺陷 —— 使用者 2026-08-12 裁定」的文字整段改寫成新行為
#   （JIRA CRUX-983），等於把缺陷合法化。**來源就寫在眼前仍然改了**，
#   所以光靠文件內的標注擋不住，必須有一道在 commit 前會絆到腳的機檢。
# ⚠️「裁定」與「裁示」工作區都在用（實際盤點：裁示 20 處、裁定 18 處），兩個都要收 ——
#    只收其中一個等於漏掉一半（2026-08-14 由測試抓出）。
SPEC_MARKERS = ("裁定", "裁示", "as-designed", "as designed", "規格，不是缺陷", "📌 規格")
SPEC_MAX_SHOWN = 8

# ⛔ 交接活文件排除在 D7 之外（2026-08-14 上線當天就被自己的誤報打臉）：
#    它是**狀態型**文件，「劃掉他人列出的待辦」是它的正常運作（CLAUDE.md §8.3 配套②(a)），
#    而 T／D／B 列又常引用「使用者×× 裁示」。若不排除，**每劃掉一條待辦就叫一次** ——
#    誤報率高的檢查幾天內就會被所有人忽略，比沒有更糟。
#    規格不住在交接檔（§8.4 分流③：狀態型 vs 索引型），住在機制文件與 skill，那些仍受保護。
SPEC_SKIP_SUFFIX = HANDOVER_SUFFIX


def git_diff_vs_head(paths):
    """工作區（含已暫存）相對 HEAD 的 diff 文字；git 不可用或失敗回 None。

    抽成獨立函式是為了讓測試能注入固定 diff —— 否則結果會隨今天有沒有人改檔而變動。
    """
    # ⚠️ `-c core.quotepath=false` 不可省 —— 預設 git 會把非 ASCII 路徑寫成
    #    `+++ "b/docs/CRUX/CRUX_\\347\\266\\234…"`（**引號在 b/ 之前**、內容為八進位跳脫），
    #    本專案的文件檔名全是中文，不關掉就每一筆都解析不出檔名（實測顯示成 `?`）。
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "diff", "-U0", "HEAD", "--"] + list(paths),
            cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def check_spec_edits(product):
    """D7：工作區相對 HEAD，有沒有刪改到帶裁定來源的規格行。

    掃描範圍是 `docs/<產品>/` 與該產品的 skill —— `bugs/` 不版控故本來就不在 diff 裡。
    只看被刪除（`-`）的行：整行原封不動時不會出現在 diff，故不會誤報。
    git 不可用時靜默跳過（同 D6）。
    """
    paths = [os.path.join("docs", product)]
    # ⚠️ 用 .get()：產品未註冊於 products.json 時不該讓整支 lint 爆掉
    #    （範本匯出後 products 是空的，測試曾因此 KeyError）
    skill = PRODUCT_SKILL.get(product)
    skill_rel = os.path.join(".claude", "skills", skill or "", "SKILL.md")
    if skill and os.path.isfile(os.path.join(ROOT, skill_rel)):
        paths.append(skill_rel)
    diff = git_diff_vs_head(paths)
    if diff is None:
        return []

    hits, seen, current = [], set(), "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            # 正常：`+++ b/docs/…`；舊 git／未關 quotepath 時：`+++ "b/docs/…"`
            path = line[4:].strip().strip('"')
            current = os.path.basename(path[2:] if path.startswith("b/") else path)
        elif line.startswith("-") and not line.startswith("---"):
            if current.endswith(SPEC_SKIP_SUFFIX):
                continue                 # 交接活文件屬狀態型，劃掉待辦是正常運作
            body = line[1:].strip()
            if not any(m in body for m in SPEC_MARKERS):
                continue
            key = (current, body)
            if key in seen:
                continue
            seen.add(key)
            hits.append((current, body))
    if not hits:
        return []

    warnings = ["D7 規格被改動 共 %d 行帶裁定來源的敘述被刪除或改寫 —— "
                "**實測與規格不符時那是缺陷，要開單，不是改文件**；"
                "除非你有新的變更聲明（RD 留言／PM 修訂／使用者裁示）。"
                "判準與實例見 CLAUDE.md §6「實測與文件不符時」" % len(hits)]
    for name, body in hits[:SPEC_MAX_SHOWN]:
        warnings.append("       %s：%s" % (name, body[:90] + ("…" if len(body) > 90 else "")))
    if len(hits) > SPEC_MAX_SHOWN:
        warnings.append("       …另有 %d 行（`git diff HEAD -- docs/%s` 可看全部）"
                        % (len(hits) - SPEC_MAX_SHOWN, product))
    return warnings


def sections_of(path):
    """只取 `##` 一級章節 —— H1 是檔名重述、H3 是細節，兩者都不該影響索引描述的判定。"""
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return [], 0, False
    heads = [clean_heading(m) for m in re.findall(r"^##\s+(.+)$", text, re.M)]
    heads = [h for h in heads if len(h) >= 2 and not BOILERPLATE.match(h)]
    return heads, text.count("\n") + 1, bool(ALLOW_BIG.search(text))


CHAR_COVER = 0.75    # 章節標題有多少比例的字出現在描述中，才算「有涵蓋」


def covered(heading, desc):
    """判斷索引描述是否涵蓋某章節。

    ⚠️ 不可用整串比對 —— 描述本來就會換句話說（「操作↔留痕對應**實測**」
       vs 章節「操作 ↔ 留痕對應」、「頁面元素與工具箱」vs「頁面與元素」），
       整串比對會把已涵蓋的判成失真，訊號全被雜訊淹沒（2026-08-11 校準）。
       改看字元覆蓋率：對中文而言，同一主題的不同措辭用字高度重疊。
    """
    chars = set(re.sub(r"[\s\W_]", "", heading))
    if not chars:
        return True
    hit = sum(1 for c in chars if c in desc)
    return hit / float(len(chars)) >= CHAR_COVER


def parse_index(index_path):
    """回傳 {檔名: 描述}；只認 `| … \\`檔名\\` | 描述 |` 這種表格列"""
    entries = {}
    if not os.path.isfile(index_path):
        return entries
    for line in io.open(index_path, encoding="utf-8").read().splitlines():
        m = re.match(r"^\|\s*[^|]*?`([^`]+)`\s*\|(.*)\|\s*$", line)
        if m:
            entries[os.path.basename(m.group(1).rstrip("/"))] = m.group(2)
    return entries


def listed_files(product_dir):
    """該產品目錄下應被索引的文件"""
    out = []
    for p in sorted(glob.glob(os.path.join(product_dir, "*"))):
        name = os.path.basename(p)
        if os.path.isdir(p) or name in SKIP_FILES or name.startswith("_"):
            continue
        if os.path.splitext(name)[1].lower() in (".md", ".pdf", ".docx", ".xlsx", ".txt", ".pptx"):
            out.append(p)
    return out


def check_product(product, entries, verbose):
    errors, warnings = [], []
    product_dir = os.path.join(DOCS, product)
    files = listed_files(product_dir)
    by_name = {os.path.basename(p): p for p in files}

    # ── D1 斷連結：索引列了但檔案不存在 ─────────────────────────
    for name in sorted(entries):
        if name in by_name:
            continue
        # 可能在子目錄（如 七星彩計算/xxx.docx）或屬其他產品
        if glob.glob(os.path.join(product_dir, "**", name), recursive=True):
            continue
        if glob.glob(os.path.join(DOCS, "**", name), recursive=True):
            continue
        errors.append("D1 斷連結 INDEX 列了 `%s`，但 docs/ 下找不到" % name)

    # ── D2 未登記 ───────────────────────────────────────────────
    for name in sorted(by_name):
        if name not in entries:
            warnings.append("D2 未登記 %s/%s 不在 INDEX.md 中" % (product, name))

    # ── D3 描述失真／D4 檔案偏大 ────────────────────────────────
    for name, path in sorted(by_name.items()):
        if not name.endswith(".md"):
            continue                      # 非文字檔無法抽章節
        heads, nlines, allow_big = sections_of(path)
        if not heads:
            continue
        if nlines >= BIG_LINES and len(heads) >= BIG_SECTIONS and not allow_big:
            warnings.append("D4 檔案偏大 %s：%d 行 / %d 個 `##` 章節 —— 確認是否混了多類主題"
                            "（確認單一主題可加 `<!-- lint-docs: allow-big -->` 豁免）"
                            % (name, nlines, len(heads)))
        desc = entries.get(name)
        if desc is None:
            continue                      # 已由 D2 報告
        missing = [h for h in heads if h and not covered(h, desc)]
        cover = 1.0 - len(missing) / float(len(heads))
        if cover < COVERAGE_MIN and len(heads) >= 4:
            warnings.append(
                "D3 描述失真 %s：%d 章節，描述只涵蓋 %d（%.0f%%）"
                % (name, len(heads), len(heads) - len(missing), cover * 100))
            shown = missing if verbose else missing[:6]
            warnings.append("       未提及：%s%s" % (
                "／".join(shown), "…" if len(missing) > len(shown) else ""))

    # ── D5 產品 skill 的意圖對照表指向不存在的檔 ────────────────
    # ⚠️ 2026-08-22：意圖對照表拆到 `references/` 之後，**要連 references 一起掃** ——
    #    否則拆層等於把這個檢查關掉（那 110 列的檔案指標才是最需要被檢查的）。
    skill_dir = os.path.join(SKILLS, PRODUCT_SKILL.get(product, ""))
    skill_files = [os.path.join(skill_dir, "SKILL.md")]
    skill_files += sorted(glob.glob(os.path.join(skill_dir, "references", "*.md")))
    for skill in skill_files:
        if not os.path.isfile(skill):
            continue
        text = io.open(skill, encoding="utf-8").read()
        for ref in sorted(set(re.findall(r"`([^`]+\.md)`", text))):
            # skill 內部的相對路徑（references/…）不是 docs/ 下的檔，改在 skill 目錄裡找
            if ref.startswith("references/"):
                if not os.path.isfile(os.path.join(skill_dir, ref)):
                    errors.append("D5 skill 斷連結 %s skill 指向 `%s`，檔案不存在"
                                  % (PRODUCT_SKILL.get(product, product), ref))
                continue
            # ⚠️ 先當「repo 相對路徑」試一次 —— 下面的 glob **走不進 `.` 開頭的目錄**，
            #    指向 `.claude/skills/<別的 skill>/references/*.md` 的引用會被誤判成斷連結。
            if os.path.isfile(os.path.join(ROOT, ref.replace("/", os.sep))):
                continue
            base = os.path.basename(ref)
            if base in by_name or glob.glob(os.path.join(DOCS, "**", base), recursive=True):
                continue
            if glob.glob(os.path.join(ROOT, "**", base), recursive=True):
                continue
            errors.append("D5 skill 斷連結 %s skill 指向 `%s`（在 %s），檔案不存在"
                          % (PRODUCT_SKILL.get(product, product), ref, os.path.basename(skill)))

    # ── D6 交接活文件是否跟上進度 ───────────────────────────────
    warnings.extend(check_handovers(product, by_name))

    # ── D7 帶裁定來源的規格行被刪改 ─────────────────────────────
    warnings.extend(check_spec_edits(product))

    return errors, warnings


# ── D8：skill 交叉引用的章節指標 ────────────────────────────
# 形如 `writeback` §1 、`commit` skill §8.3 、CLAUDE.md §5
# 尾端可再帶一個**子項標記**：`handoff` §2④ 、`handoff` §1 A
SUB = r"\s*([\u2460-\u2473]|[A-Z](?![A-Za-z0-9]))?"
SKILL_REF_RE = re.compile(r"`([a-z][a-z0-9-]{2,})`\s*(?:skill\s*)?§(\d+(?:\.\d+)?)" + SUB)
CLAUDE_REF_RE = re.compile(r"CLAUDE\.md\s*(?:的\s*)?§(\d+(?:\.\d+)?)" + SUB)
HEADING_NUM_RE = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)?)[\.、\s]")
# 子項標題：`### ① 這批有跑測試` / `### A. 開場必做`
SUB_HEADING_RE = re.compile(r"^#{3,4}\s+([\u2460-\u2473]|[A-Z])[\.、\s]")


def heading_numbers(path):
    """該檔所有 `## N.` / `### N.M` 的編號集合。"""
    nums = set()
    try:
        for line in io.open(path, encoding="utf-8"):
            m = HEADING_NUM_RE.match(line)
            if m:
                nums.add(m.group(1))
    except OSError:
        pass
    return nums


def section_submarkers(path):
    """`## N.` 章節 → 其底下的子項標記集合（①②… 或 A/B/C）。

    ★ 為什麼：D8 原本只驗到章節層，**子項改動不會被發現**。
      2026-08-22 實際踩到：`writeback` §6 指向 `handoff` §2③，
      但 lint 那段在 §2④（③ 是狀態交接）—— D8 當時全綠。

    ⚠️ 只收**標題型**子項。子項若寫成粗體條列（如 `commit` §8.2 的「**A. 許可前**」）
      這裡收不到，該章節就會被跳過不驗 —— 寧可漏報，不要誤報。
    """
    out, cur = {}, None
    try:
        for line in io.open(path, encoding="utf-8"):
            if line.startswith("## ") and not line.startswith("### "):
                m = HEADING_NUM_RE.match(line)
                cur = m.group(1) if m else None
            elif cur is not None:
                m = SUB_HEADING_RE.match(line)
                if m:
                    out.setdefault(cur, set()).add(m.group(1))
    except OSError:
        pass
    return out


def check_skill_refs():
    """D8：skill 之間（與對 CLAUDE.md）的章節指標是否還指得到。

    ★ 為什麼需要：章節重編號後這些指標會**靜默失效**，沒有任何機制會發現。
      2026-08-22 把 browser-ops §7 抽成 writeback、CLAUDE.md §8.2~8.4 抽成 commit skill 時，
      一次就製造了 16 處需要改寫的引用 —— 漏改一處就是一個死指標。
    """
    errors = []
    claude_md = os.path.join(ROOT, "CLAUDE.md")
    cache = {"CLAUDE.md": heading_numbers(claude_md)}
    subs = {"CLAUDE.md": section_submarkers(claude_md)}

    def check_sub(owner, target, path, sec, mark):
        """子項存在性。該章節沒有標題型子項時直接跳過（見 section_submarkers）。"""
        if not mark:
            return
        if target not in subs:
            subs[target] = section_submarkers(path)
        have = subs[target].get(sec)
        if have and mark not in have:
            errors.append("D8 指標失效 %s 指向 %s §%s%s，該章節沒有這個子項（有的是 %s）"
                          % (owner, target, sec, mark, "".join(sorted(have))))

    targets = [("CLAUDE.md", claude_md)]
    for d in sorted(glob.glob(os.path.join(SKILLS, "*", "SKILL.md"))):
        targets.append((os.path.basename(os.path.dirname(d)), d))
    # references/ 也會寫章節指標（例：前置檢查_七星.md 指向 perf-test §6）
    for d in sorted(glob.glob(os.path.join(SKILLS, "*", "references", "*.md"))):
        targets.append(("%s/%s" % (os.path.basename(os.path.dirname(os.path.dirname(d))),
                                   os.path.basename(d)), d))

    for owner, path in targets:
        try:
            text = io.open(path, encoding="utf-8").read()
        except OSError:
            continue
        for m in SKILL_REF_RE.finditer(text):
            name, sec, mark = m.group(1), m.group(2), m.group(3)
            skill_path = os.path.join(SKILLS, name, "SKILL.md")
            if not os.path.isfile(skill_path):
                continue          # 不是 skill 名（可能是工具名／檔名），交給 D1／D5
            if name not in cache:
                cache[name] = heading_numbers(skill_path)
            if cache[name] and sec not in cache[name]:
                errors.append("D8 指標失效 %s 指向 `%s` §%s，該 skill 沒有這一節"
                              % (owner, name, sec))
                continue
            check_sub(owner, "`%s`" % name, skill_path, sec, mark)
        for m in CLAUDE_REF_RE.finditer(text):
            sec, mark = m.group(1), m.group(2)
            if cache["CLAUDE.md"] and sec not in cache["CLAUDE.md"]:
                errors.append("D8 指標失效 %s 指向 CLAUDE.md §%s，該章節不存在" % (owner, sec))
                continue
            check_sub(owner, "CLAUDE.md", claude_md, sec, mark)
    return sorted(set(errors))


def check_template_manifest():
    """D11：範本匯出的白名單是否仍涵蓋整個 repo。

    ★ 為什麼接在 lint_docs：白名單唯一的失效模式是「**新增了東西卻忘了分類**」，
      而它**隨變更發生、不隨時間發生** —— 排程檢查的觸發條件是錯的。
      收尾必跑 lint_docs 是既有紀律（`handoff` §2④），接在這裡不必有人新記得一件事。

    三種問題：未分類、檔名帶產品字樣卻被判成通用、EXPORT 指到已不存在的路徑。
    `export_template.py` 不在時（例如被裁掉）靜默跳過，不讓 lint 整支停擺。
    """
    try:
        import export_template as X
    except Exception:
        return []
    errors = []
    for m in X.unclassified(ROOT):
        errors.append("D11 範本白名單 `%s` 未分類 —— "
                      "通用 → EXPORT／產品專屬 → products.json 的 extra_paths／"
                      "run 產物或敏感檔 → NEVER" % m)
    try:
        for rel, w in X.suspicious(ROOT):
            errors.append("D11 範本白名單 `%s` 檔名含產品字樣「%s」卻會被當通用匯出 —— "
                          "登記到該產品的 extra_paths" % (rel, w))
    except Exception:
        pass          # suspicious 需要跑 git，取不到就算了
    for g in X.missing_export_entries(ROOT):
        errors.append("D11 範本白名單 EXPORT 列了 `%s`，但 repo 裡不存在（改名後沒同步？）" % g)
    return errors


MIRROR_HINT = ".template-mirror"


def check_mirror_sync():
    """D13：乾淨範本鏡像有沒有跟上原版。

    ★ 為什麼接在 lint_docs：`commit` skill 寫著「提交後跑一次 `--sync`」，
      但那條**只靠自律** —— 而 skill 自己就寫著「原版改了而鏡像沒跟上時，
      **沒有任何機制會發現**」。2026-08-26 連續四輪漏掉，每次只是口頭提醒。

    ⛔ 三種情況**靜默跳過**，不是報錯：
      · 根目錄有 `.template-export` → 你手上就是匯出的範本，沒有鏡像可比
      · 沒有 `.template-mirror` → 這台機器沒有鏡像（同事的常態）
      · 鏡像讀不到／`source_commit` 對不上 git 歷史 → 講不出「落後幾個」就別亂報

    ⭐ **只有動到「會被匯出」的路徑才報** —— 只改 `docs/<產品>/` 的話鏡像不必更新，
      報了就是雜訊，而雜訊會讓人開始忽略 lint（同 W7 的取捨）。
    """
    if os.path.exists(os.path.join(ROOT, ".template-export")):
        return []                       # 這裡就是範本，沒有鏡像
    hint = os.path.join(ROOT, MIRROR_HINT)
    if not os.path.exists(hint):
        return []                       # 這台機器沒有鏡像
    try:
        mirror = io.open(hint, encoding="utf-8").read().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return []
    if not mirror or not os.path.isdir(mirror):
        return ["D13 鏡像落後 `%s` 指到 `%s`，但那個目錄不存在 —— "
                "改掉它或刪掉那個檔（沒有鏡像就不必設）" % (MIRROR_HINT, mirror)]
    try:
        import json as _json
        stamp = _json.load(io.open(os.path.join(mirror, ".template-export"), encoding="utf-8"))
        base = str(stamp.get("source_commit") or "").split("+")[0]
    except Exception:                   # noqa: BLE001
        return ["D13 鏡像落後 `%s` 讀不到 `.template-export` —— "
                "那不像是 `export_template.py --out` 產生的鏡像" % mirror]
    if not base:
        return []
    try:
        out = subprocess.run(["git", "log", "--format=%h", "--name-only", "%s..HEAD" % base],
                             cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=30)
        if out.returncode:
            return []                   # commit 不在歷史裡（被 gc／換過 repo）—— 不亂報
        lines = [l.strip() for l in (out.stdout or "").splitlines() if l.strip()]
    except Exception:                   # noqa: BLE001
        return []
    commits = [l for l in lines if len(l) <= 12 and " " not in l and "/" not in l]
    paths = sorted({l for l in lines if "/" in l or "." in l} - set(commits))
    if not paths:
        return []
    # ⭐ 只留「會被匯出」的路徑 —— 產品專屬的改動不需要同步鏡像
    try:
        import export_template as X
        # ⚠️ `classify` 要吃 `product_paths()` 的結果 —— 少了它，產品專屬的路徑
        #    會被判成通用，於是只改 `docs/<產品>/` 也報「鏡像落後」（純雜訊）。
        products = X.product_paths(ROOT)
        hit = [p for p in paths
               if X.classify(p, products) in ("export", "skeleton")]
    except Exception:                   # noqa: BLE001
        hit = paths                     # 分類不出來就全報，寧可吵一點也別漏掉
    if not hit:
        return []
    return ["D13 鏡像落後 `%s` 有 %d 個通用檔改過而鏡像停在 `%s`（%d 個 commit 前）：%s%s\n"
            "   → python scripts\\export_template.py --out %s --sync"
            % (mirror, len(hit), base, len(commits), "、".join(hit[:4]),
               "…" if len(hit) > 4 else "", mirror)]


def check_workspace_residue():
    """W：repo 根目錄（與各稽核層）**未版控又沒分類**的檔案。

    ★ 2026-08-23 實跑抓到：任務 session 用 MCP 截圖時只帶檔名，
      檔案就落在 **repo 根目錄**（工具的預設是 cwd）；page snapshot 的
      `.yml` 也一樣。而 `CLAUDE.md` §8.3 明訂「暫存與 page snapshot
      一律寫 scratchpad，不得留在 repo 根目錄」——
      **在此之前沒有任何機制會報**（D11 只看已版控的檔案）。

    ⚠️ 是警告不是必修：它有兩種可能，處置相反 ——
      ① session／探索留下的殘留 → 刪掉
      ② 你剛新增、還沒 commit 的通用檔 → 去白名單分類（**一 commit 就會變成 D11 錯誤**）
    """
    try:
        import export_template as X
    except Exception:                       # noqa: BLE001
        return []
    try:
        residue = X.unclassified_untracked(ROOT)
    except Exception:                       # noqa: BLE001
        return []
    if not residue:
        return []
    shown = "、".join("`%s`" % x for x in residue[:6])
    more = "（另有 %d 個）" % (len(residue) - 6) if len(residue) > 6 else ""
    return ["W 工作區殘留 有 %d 個未版控又沒分類的檔案：%s%s —— "
            "是 session／探索留下的暫存就刪掉（CLAUDE.md §8.3：不得留在 repo 根目錄）；"
            "是你新增的通用檔就去 export_template 的白名單分類（一 commit 就會變成 D11 錯誤）"
            % (len(residue), shown, more)]


def check_index_sections():
    """D12：每個已註冊的產品在 `docs/INDEX.md` 都要有分區（含子節）。

    ⚠️ 判準要**兩件都有**：`## <產品> 專案` 這一節，以及底下至少一個 `### ` 子節 ——
       只有大節而沒有子節時，平台挑不到要登記到哪一格，等於還是沒有落點。

    `new_product.py` 現在會自動建；這條是給「**用搬資產的方式接產品**」
    那種情況的絆線（2026-08-23 實跑就是這樣接的，而 lint 全綠）。
    """
    index_path = os.path.join(ROOT, "docs", "INDEX.md")
    if not os.path.isfile(index_path):
        return []
    import json
    try:
        cfg = json.loads(io.open(os.path.join(ROOT, "config", "products.json"),
                                 encoding="utf-8").read())
    except Exception:                       # noqa: BLE001
        return []
    text = io.open(index_path, encoding="utf-8").read()
    lines = text.split("\n")
    errors = []
    for prod in cfg.get("products") or []:
        pid = prod.get("id")
        docs_dir = (prod.get("docs_dir") or "").split("/")[-1]
        start = None
        for i, ln in enumerate(lines):
            if ln.startswith("## ") and ((pid and pid in ln) or
                                         (docs_dir and docs_dir in ln)):
                start = i
                break
        if start is None:
            errors.append(
                "D12 產品沒進索引 `%s` 在 docs/INDEX.md 沒有分區 —— "
                "沒有分區就沒有地方登記文件，平台的自動登記也不會生效。"
                "跑 `python scripts/new_product.py` 接的產品會自動建；"
                "手動接的請補一節 `## %s 專案` ＋ 至少一個 `### ` 子節" % (pid, pid))
            continue
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        if not any(lines[i].startswith("### ") for i in range(start, end)):
            errors.append(
                "D12 產品沒進索引 `%s` 的分區底下沒有任何 `### ` 子節 —— "
                "平台挑不到要把文件登記到哪一格" % pid)
    return errors


def check_todo_ids():
    """D9：交接活文件的待辦編號重複。

    ★ 多 session 併行時沒有任何機制擋它（不像 Bug ID 有 `--next-id`），
      而 `CRUX_功能驗證交接.md` 已實際撞號三組（2026-08-22 發現 T27／T34／T43）。
    """
    warnings = []
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import next_todo_id as nti
    except ImportError:
        return ["D9 未執行 找不到 scripts/next_todo_id.py"]
    files = sorted(set(sum((glob.glob(g) for g in nti.HANDOVER_GLOBS), [])))
    for f in files:
        used = nti.collect(f)
        for kind, d in sorted(used.items()):
            for num, lines_ in sorted(d.items()):
                if len(lines_) > 1:
                    warnings.append("D9 編號重複 %s 的 %s%d 用了 %d 次（行 %s）—— 改號的是後寫入者"
                                    % (os.path.relpath(f, ROOT), kind, num, len(lines_),
                                       "、".join(map(str, lines_))))
    return warnings


def check_backlog(product):
    """D10：把三類看不見的積壓變成數字。

    ★ 這三類都不在交接檔的待辦表裡，也不在 BUG清單 的狀態統計裡 ——
      它們只有在「有人特地去數」時才會出現，於是永遠不會有人數。
    """
    bugs = os.path.join(DOCS, product, "bugs")
    if not os.path.isdir(bugs):
        return []
    paths = glob.glob(os.path.join(bugs, "*.md")) + glob.glob(os.path.join(bugs, "old", "*.md"))
    no_regr, unfiled = [], []
    for p in paths:
        name = os.path.basename(p)
        if name.startswith(("BUG清單", "_")):
            continue
        try:
            head = io.open(p, encoding="utf-8").read(1800)
        except OSError:
            continue
        bug_id = (re.search(r"^id:\s*(\S+)", head, re.M) or [None, name[:12]])[1]
        status = (re.search(r"^status:\s*(\S+)", head, re.M) or [None, ""])[1]
        regr = (re.search(r"^regression:\s*(.*)$", head, re.M) or [None, ""])[1].strip()
        rep = (re.search(r"^reported:\s*(.*)$", head, re.M) or [None, ""])[1].strip()
        if status in ("open", "fixed") and (not regr or "待補" in regr):
            no_regr.append("%s%s" % (bug_id, "（已修復卻無回歸案例）" if status == "fixed" else ""))
        if status == "open" and not rep:
            unfiled.append(bug_id)
    pend = []
    hand = os.path.join(bugs, "_handover")
    if os.path.isdir(hand):
        for p in sorted(glob.glob(os.path.join(hand, "*.md"))):
            try:
                n = io.open(p, encoding="utf-8").read().count("未檢查")
            except OSError:
                n = 0
            if n:
                pend.append("%s(%d)" % (os.path.basename(p)[:22], n))
    out = []
    if no_regr:
        out.append("D10 積壓 待補回歸案例 %d 張：%s%s"
                   % (len(no_regr), "、".join(no_regr[:8]), "…" if len(no_regr) > 8 else ""))
    if unfiled:
        out.append("D10 積壓 未開立（open 但 reported 空）%d 張：%s" % (len(unfiled), "、".join(unfiled[:8])))
    if pend:
        out.append("D10 積壓 side effect 未復查 %d 份：%s%s"
                   % (len(pend), "、".join(pend[:5]), "…" if len(pend) > 5 else ""))
    return out


def check_common(entries):
    """跨產品的交接檔（`docs/` 直下，不屬任何產品目錄）—— D1 已由 check_product 涵蓋，
    這裡只補 D6：它負責的是共用基礎設施，那些路徑動了它就該更新。
    """
    by_name = {}
    for name in COMMON_HANDOVERS:
        path = os.path.join(DOCS, name)
        if os.path.isfile(path):
            by_name[name] = path
    if not by_name:
        return []
    missing = [n for n in by_name if n not in entries]
    warnings = ["D2 未登記 %s 不在 INDEX.md 中" % n for n in sorted(missing)]
    return warnings + check_handovers("共通", by_name)


def main():
    ap = argparse.ArgumentParser(description="檢查 docs/ 索引是否失真、是否有該拆的大檔")
    ap.add_argument("--product", choices=PRODUCTS)
    ap.add_argument("--verbose", action="store_true", help="列出全部未涵蓋章節")
    args = ap.parse_args()

    entries = parse_index(os.path.join(DOCS, "INDEX.md"))
    total_err = 0
    for product in ([args.product] if args.product else PRODUCTS):
        errors, warnings = check_product(product, entries, args.verbose)
        print("\n" + "=" * 60)
        print("📚 %s：%d 份文件已登記索引" % (product, len(listed_files(os.path.join(DOCS, product)))))
        if errors:
            print("\n❌ 錯誤（%d）" % len(errors))
            for e in errors:
                print("   " + e)
        if warnings:
            print("\n⚠️ 警告（%d）" % len(warnings))
            for w in warnings:
                print("   " + w)
        if not errors and not warnings:
            print("   ✅ 全部通過")
        if any(w.startswith(("D3", "D4")) for w in warnings):
            print("\n   ↑ D3/D4 是**技術債清單**（描述可補、大檔可拆），非阻塞；"
                  "D1/D5 斷連結才是必修")
        if any(w.startswith("D6") for w in warnings):
            print("\n   ↑ D6 是**收尾漏做**的訊號：改交接檔的 §2 待辦與檔頭日期即可，"
                  "不要只改日期（那只是把警告關掉）")
        if any(w.startswith("D7") for w in warnings):
            print("\n   ↑ D7 **不是叫你回退**，是要你停下來回答一個問題："
                  "\n     『這次有沒有人（RD／PM／SA／使用者）說要改？』"
                  "\n     有 → 在 commit 訊息或報告寫明依據，這個警告可以忽略；"
                  "\n     沒有 → 你正在把缺陷改寫成規格，**應該去開單**。")
        backlog = check_backlog(product)
        if backlog:
            print("\n📦 積壓（D10，不阻塞但別讓它一直長）")
            for b in backlog:
                print("   " + b)
        total_err += len(errors)

    # ── D8／D9：跨產品，只跑一次 ──────────────────────────
    ref_errors = check_skill_refs()
    ref_errors += check_template_manifest()
    ref_errors += check_index_sections()
    ref_errors += check_mirror_sync()
    id_warnings = check_todo_ids()
    id_warnings += check_workspace_residue()
    print("\n" + "=" * 60)
    print("🔗 跨檔一致性")
    if ref_errors:
        print("\n❌ 錯誤（%d）" % len(ref_errors))
        for e in ref_errors:
            print("   " + e)
        print("\n   ↑ D8 是**章節重編號後的靜默失效**：改章節號時，"
              "用 `python scripts\\trace_value.py --value \"<skill> §<舊號>\"` 找出所有引用一起改")
        total_err += len(ref_errors)
    if id_warnings:
        print("\n⚠️ 警告（%d）" % len(id_warnings))
        for w in id_warnings:
            print("   " + w)
        print("\n   ↑ D9：寫入前用 `python scripts\\next_todo_id.py --handover <檔> --kind T` 取號")
    if not ref_errors and not id_warnings:
        print("   ✅ 全部通過")

    # 跨產品的工作區維護交接檔 —— 不屬任何產品，只在未指定 --product 時檢查
    if not args.product:
        common = check_common(entries)
        print("\n" + "=" * 60)
        print("🧰 共通（工作區維護）")
        if common:
            print("\n⚠️ 警告（%d）" % len(common))
            for w in common:
                print("   " + w)
        else:
            print("   ✅ 全部通過")

    print()
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
