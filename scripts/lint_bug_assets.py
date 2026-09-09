# -*- coding: utf-8 -*-
"""檢查 `docs/<專案>/bugs/` 的 Bug 單與截圖是否一致、命名是否合規。

用途：Bug 單與截圖持續增長，靠人記規範必然漂移；本腳本把規範變成可執行的檢查。
      預設**只報告不動檔案**；清理走 --quarantine（隔離而非刪除，可還原）。

使用方式：
    python scripts\\lint_bug_assets.py                    # 檢查全部專案
    python scripts\\lint_bug_assets.py --product CRUX     # 只檢查 CRUX
    python scripts\\lint_bug_assets.py --verbose          # 連「已豁免」的項目也列出
    python scripts\\lint_bug_assets.py --product CRUX --quarantine        # 預演隔離
    python scripts\\lint_bug_assets.py --product CRUX --quarantine --yes  # 真的搬

前置條件：無（純本機檔案讀寫，不需連線測試站）。

離開碼：有 ❌ 錯誤時回 1，只有 ⚠️ 警告或全過回 0（供 CI／hook 使用）。

檢查項目
--------
❌ E1 斷圖    文件引用了 shots/ 下不存在的檔案（圖被刪或改名，單子沒跟著改）
❌ E2 撞號    同一個 ID 有多份 Bug 單
⚠️ W1 死圖    shots/ 的圖沒有被任何文件引用
              —— `_fixed_` 驗證圖依 jira-verify 規範是上傳 JIRA、本地不回貼，
                 故自動豁免；frontmatter `shots_external: true` 亦可整單豁免
⚠️ W2 命名    不符 `<ID>_<序>_<說明>.png` / `<ID>_fixed_<序>_<說明>.png`
⚠️ W3 外部ID  圖的 ID 前綴在本地無對應 Bug 單（多半是 JIRA 單號，應加 `JIRA-` 前綴）
⚠️ W4 無佐證  Bug 單缺 Actual／Expect 具體數值（截圖不版控，圖丟了就讀不懂）
⚠️ W5 未引用  Bug 單有同名截圖存在，但單子內文完全沒引用任何圖
⚠️ W6 索引過期  BUG清單.md／_view/ 早於 Bug 單 —— 過期的分組檢視會說謊
⚠️ W7 截圖未標注  圖沒有框選標記，或 markdown 引用沒寫說明（alt text）
⚠️ W8 單格式    Reproduce Steps 超過 5 步／正文有成因推導／缺【Test Environment】
⚠️ W9 斷引用    單／報告引用的截圖**檔案不存在**（多半是還沒 stamp_shots 搬進 shots/ 就被清掉）
              —— 規範見 `bug-report` skill §4「讀者要在 10 秒內知道哪裡錯、應該是多少」
⚠️ W10 缺截圖   Bug 單沒有任何佐證截圖 —— 圖能讓讀者在 10 秒內看懂問題點
                 （只查生效日之後開的單；真的沒畫面就在 frontmatter 寫 `no_shot: 理由`）
"""
import argparse
import glob
import io
import os
import re
import shutil
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bug_paths import ARCHIVE_DIR, product_base   # noqa: E402  單一事實來源，勿在此重新定義
from bug_paths import PRODUCTS as _PRODUCT_IDS    # noqa: E402
from bug_paths import ID_PREFIX                   # noqa: E402

# ⚠️ 產品表**必須**從 `config/products.json` 導出（`bug_paths` 是唯一來源）。
#    這裡原本寫死 CRUX／投注機器人／七星 —— 在原型永遠正確，
#    但同事接了自己的產品之後，這支會完全掃不到它，而且**不會有任何訊息**。
#    （2026-08-23 在只接了一個產品的範本裡才踩到。）
PRODUCTS = {pid: product_base(pid) for pid in _PRODUCT_IDS}

# ⚠️ ID_RE／SHOT_NAME_RE 的前綴**必須包含** `ID_PREFIX` 目前登記的值，不可只寫死 CRUX／WBOT／QX ——
#    2026-08-26 接「新綜合」（前綴 Snotra）時踩到：上面的 PRODUCTS 已經改成動態讀取，
#    但這裡兩個 regex 沒有跟著改，導致新產品的 Bug 單與截圖被 W2「命名不合規」誤報。
#    是同一份 docstring 警告過的「同一份資訊散在多處，改一處漏一處」，只是換了地方犯。
#    ⚠️ 但也不能**只**用 `ID_PREFIX`：CRUX／WBOT／QX 是三個原型產品的固定樣板前綴，
#    `tests/tooling/` 的通用測資（`bugs_tree` fixture）直接寫死用它們造假 Bug 單，
#    不管這個 clone 實際接了哪個產品都該認得——故與即時設定**取聯集**，兩邊都不會誤判。
_PREFIXES = "|".join(re.escape(p) for p in
                      sorted(set(ID_PREFIX.values()) | {"CRUX", "WBOT", "QX"}))
# ⚠️ JIRA 單號已破千（如 JIRA-CRUX-1001），故 `JIRA-` 前綴允許 3~4 碼；
#    本地 ID 仍固定 3 碼（`gen_bug_index.py --next-id` 只配 3 碼）。
ID_RE = re.compile(r"^(?:JIRA-(?:%s)-(?:\d{3,4}|S\d{2})|(?:%s)-(?:\d{3}|S\d{2}))"
                    % (_PREFIXES, _PREFIXES))
# 文字裡「看起來是圖檔」的字串。⚠️ 與 collect() 的 `shots/…` 不同：
# 那個只認已經搬進 shots/ 的，而 W9 要抓的正好是**還沒搬進去**的那些。
IMG_TOKEN_RE = re.compile(
    r"""[^\s`"'（）()\[\]｜|，、。；;：:]+\.(?:png|jpg|jpeg|gif)""", re.I)

# <ID>_<序2碼>_<說明>.png 或 <ID>_fixed_<序2碼>_<說明>.png
SHOT_NAME_RE = re.compile(
    r"^(?:JIRA-(?:%s)-(?:\d{3,4}|S\d{2})|(?:%s)-(?:\d{3}|S\d{2}))"
    r"_(?:fixed_)?\d{2}_.+\.(?:png|jpg|jpeg|gif)$" % (_PREFIXES, _PREFIXES))


def parse_frontmatter(path):
    text = io.open(path, encoding="utf-8", errors="replace").read()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text


def id_prefix(filename):
    """由截圖檔名取出 ID 前綴（含可能的 JIRA- 前綴）"""
    m = re.match(r"^(JIRA-(?:%s)-(?:\d{3,4}|S\d{2})"
                 r"|(?:%s)-(?:\d{3}|S\d{2}))" % (_PREFIXES, _PREFIXES), filename)
    return m.group(1) if m else None


NUL = bytes([0])     # PNG tEXt 的 keyword/text 分隔符；避免在原始碼裡寫入真的 NUL 位元組
# 截圖標注規範的生效日：早於此日的舊圖不追溯（比照「已寄出的不追改」）
ANNOTATION_POLICY_DATE = "2026-08-12"


def _shot_mark(path):
    """讀 PNG 的標注標記；未標注／非 PNG 回 None。

    與 `tools/qa_common/shot.py` 的 `read_png_mark` 同一份邏輯——
    lint 不應相依 tools/（那是測試框架，scripts/ 是工作區工具），故在此保留輕量實作。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return None
    key = b"qa-annotated" + NUL
    i = head.find(key)
    if i < 8:
        return None
    # 用 chunk 長度欄位界定文字：tEXt 的 text 後面沒有終止符，
    # 緊接著是 4 bytes CRC，若用 split(NUL) 會把 CRC 位元組一起讀進來。
    length = struct.unpack(">I", head[i - 8:i - 4])[0]
    return head[i:i + length][len(key):].decode("utf-8", "replace")


def collect(bugs_dir):
    """回傳 (bug 單 dict, 所有引用到的圖檔名 set, 所有文字檔內容)

    Bug 單只會存在於**主目錄**或 **old/（歸檔層）**，兩層都要掃。
    """
    bugs, referenced, texts = {}, set(), []

    for pattern in (os.path.join(bugs_dir, "*.md"),
                    os.path.join(bugs_dir, ARCHIVE_DIR, "*.md")):
        for path in sorted(glob.glob(pattern)):
            if os.path.basename(path) == "BUG清單.md":
                continue
            meta, text = parse_frontmatter(path)
            texts.append((path, text))
            if meta and "id" in meta:
                bugs.setdefault(meta["id"], []).append((path, meta, text))

    # 報告與交接會引用截圖，納入「有被引用」的判定。
    # ⚠️ `_deliver/` **刻意排除** —— 交付包自帶 `shots/`，是自足的凍結快照，
    #    拿它的引用去比對主 shots/ 會產生假斷圖（CLAUDE.md §6：已寄出的不追改）。
    for sub in ("_reports", "_handover"):
        for path in glob.glob(os.path.join(bugs_dir, sub, "**", "*.md"), recursive=True):
            texts.append((path, io.open(path, encoding="utf-8", errors="replace").read()))

    # 只認 `shots/<檔名>` 形式的引用（markdown 圖語法或反引號路徑皆可）。
    # ⚠️ 不可只抓「像檔名的字串」—— 截圖檔名常含小數點（回水0.54.png、-46.02.png），
    #    從中間斷開會產生大量假斷圖；且會誤抓 docs/ 下的其他圖（如 虛盤平均貨量_賠率.png）。
    for _path, text in texts:
        for name in re.findall(r"shots/([^\s\)\`\"'）]+\.(?:png|jpg|jpeg|gif))", text):
            referenced.add(name)
    return bugs, referenced, texts


#: W10 生效日 —— 之前開的單不追溯（同 W7 的取捨：訊號不能被雜訊淹沒）
SHOT_POLICY_DATE = "2026-08-26"

#: ⚠️ 這幾類**非截圖不可** —— 錯誤訊息、提示文案、版面問題用文字描述
#:    永遠不如一張圖。命中就在警告裡額外標出來，讓人知道這張特別該補。
_VISUAL_WORDS = ("訊息", "提示", "顯示", "版面", "畫面", "欄位名", "標籤",
                 "文案", "排版", "按鈕", "彈窗", "对话框", "对话方块")


def _visual_hint(meta, text):
    """視覺性缺陷 → 回一句額外提醒；否則空字串。"""
    if str(meta.get("surface") or "") in ("前台", "frontend"):
        return "（`surface: 前台`，**這一類非截圖不可**）"
    title = str(meta.get("title") or "")
    hit = [w for w in _VISUAL_WORDS if w in title]
    if hit:
        return "（標題含「%s」，**這一類非截圖不可**）" % hit[0]
    return ""


# ── 節名 → 規範節序（bug-report §4）──────────────────────
# ⚠️ 別名是實況：61 張單用 `## 【Test Environment】`、平台舊格式用裸行 `Test Environment：`，
#    佐證那一格有人寫「問題截圖」有人寫「佐證」——**同一格的不同叫法不該報成順序錯**。
_SECTION_ORDER = ["Reproduce Steps", "Actual result", "Expect result",
                  "問題截圖", "【Test Environment】", "附註"]
_SECTION_ALIAS = [
    (re.compile(r"^(Reproduce\s*Steps|重現步驟)", re.I), 0),
    (re.compile(r"^Actual(\s*result)?|^實際(值|結果)", re.I), 1),
    (re.compile(r"^Expect(ed|\s*result)?|^(預期|期望)(值|結果)", re.I), 2),
    (re.compile(r"^(問題截圖|佐證)"), 3),
    (re.compile(r"^【?\s*Test\s*Environment|^測試環境", re.I), 4),
    (re.compile(r"^附註"), 5),
]


# 裸行寫法要嚴格認：**整行剛好是節名**（JIRA 的寫法，實抓 CRUX-983／CRUX-969），
# 或**節名緊接冒號**再接內文（平台舊格式）。
# ⛔ 放寬到「開頭是節名就算」的話，`佐證 run：\`logs/…\`` 這種
#    【Test Environment】表格裡的一列會被當成「佐證」節
#    → 誤報一票（2026-08-26 第一版實跑，14 則裡 9 則是誤報）。
_SEC_WORDS = (r"Reproduce\s*Steps|Actual(\s*result)?|Expect(ed|\s*result)?|"
              r"【?\s*Test\s*Environment\s*】?|問題截圖|佐證|附註|重現步驟|測試環境")
_BARE_HEAD = re.compile(r"^(?:%s)\s*(?:[：:]|$)" % _SEC_WORDS, re.I)


def _canon_section(text, heading):
    """一行 → 它是規範的第幾節；認不得回 None（人自己加的分析節，跳過不管）。

    `heading` 為真代表它是 markdown 標題（`## Actual result`），可直接比對；
    否則要先過 `_BARE_HEAD`（關鍵詞直接接冒號）才當作節標題。
    """
    t = (text or "").strip().lstrip("#").strip()
    if not heading and not _BARE_HEAD.match(t):
        return None
    for rx, idx in _SECTION_ALIAS:
        if rx.match(t):
            return idx
    return None


def lint(product, base, verbose=False):
    """回傳 (errors, warnings, dead_shots, stat)；前三者各為可列印的字串清單。

    ⚠️ 四個值 —— 早退路徑原本只回三個（呼叫端解四個 → ValueError）。
       剛接進來、還沒開過任何單的產品就是走這條路。
    """
    bugs_dir = os.path.join(base, "bugs")
    shots_dir = os.path.join(bugs_dir, "shots")
    if not os.path.isdir(bugs_dir):
        return [], [], [], u"📊 %s：還沒有 bugs/ 目錄（尚未開過單）" % product

    bugs, referenced, texts = collect(bugs_dir)
    # 截圖同樣分佈在主 shots/ 與 old/shots/ 兩層；以檔名為鍵（全域唯一）
    shot_path = {}
    for d in (shots_dir, os.path.join(bugs_dir, ARCHIVE_DIR, "shots")):
        for p in glob.glob(os.path.join(d, "*")):
            if os.path.isfile(p):
                shot_path[os.path.basename(p)] = p
    shots = sorted(shot_path)
    shot_set = set(shots)

    errors, warnings, dead, exempted = [], [], [], []

    # ── E2 撞號 ────────────────────────────────────────────────
    for bug_id, entries in sorted(bugs.items()):
        if len(entries) > 1:
            errors.append("E2 撞號 %s → %s" % (
                bug_id, "、".join(os.path.basename(p) for p, _, _ in entries)))

    # ── E1 斷圖：被引用但檔案不存在 ─────────────────────────────
    for name in sorted(referenced):
        if name not in shot_set:
            where = [os.path.relpath(p, bugs_dir) for p, t in texts if name in t]
            errors.append("E1 斷圖 %s ← 被 %s 引用" % (name, "、".join(where[:3])))

    # ── W1 死圖／W2 命名／W3 外部 ID ───────────────────────────
    # 整單豁免：frontmatter `shots_external: true`
    external_ids = {bid for bid, entries in bugs.items()
                    if any((m.get("shots_external", "").lower() == "true") for _, m, _ in entries)}

    for name in shots:
        prefix = id_prefix(name)
        if not SHOT_NAME_RE.match(name):
            warnings.append("W2 命名 %s（應為 <ID>_<序2碼>_<說明>.png）" % name)
        if prefix and not prefix.startswith("JIRA-") and prefix not in bugs:
            warnings.append("W3 外部ID %s → 本地無 %s，若為 JIRA 單號請改前綴 JIRA-%s_…"
                            % (name, prefix, prefix))
        if name not in referenced:
            if "_fixed_" in name or (prefix in external_ids):
                exempted.append(name)
            else:
                dead.append(name)

    for name in dead:
        warnings.append("W1 死圖 %s（無任何文件引用）" % name)

    # ── W4 無佐證數值／W5 有圖未引用 ───────────────────────────
    for bug_id, entries in sorted(bugs.items()):
        for path, meta, text in entries:
            fname = os.path.basename(path)
            body = text.split("---", 2)[-1]
            # 改善建議（S 序列）、已撤銷、已接續（轉址樁）本就沒有 Actual／Expect
            if meta.get("status") not in ("suggestion", "rejected", "superseded") and (
                    not re.search(r"Actual|實際值|實際結果", body) or
                    not re.search(r"Expect|期望值|預期結果", body)):
                warnings.append("W4 無佐證 %s（缺 Actual／Expect 段落，截圖不版控、圖丟了就讀不懂）"
                                % fname)
            own = [s for s in shots if id_prefix(s) == bug_id and "_fixed_" not in s]
            if own and not re.search(r"shots/[^\s]+\.(?:png|jpg|jpeg|gif)", body):
                warnings.append("W5 未引用 %s 有 %d 張截圖，但單子內文未引用任何圖"
                                % (fname, len(own)))

    # ── W8 Bug 單格式（bug-report §4：讀者要在 10 秒內知道「哪裡錯、應該是多少」）──
    # 規範訂了「順序固定、Reproduce Steps 5 步以內、⛔ 不要寫成因推導」，
    # 但先前只有截圖資產被機檢 —— 格式仍靠自律，而自律必然漂移。
    for bug_id, entries in sorted(bugs.items()):
        for path, meta, text in entries:
            fname = os.path.basename(path)
            if meta.get("status") in ("suggestion", "rejected", "superseded"):
                continue                      # 這幾類本就不套 Bug 回報模板
            body = text.split("---", 2)[-1]

            # ① Reproduce Steps 步數：規範是 5 步以內
            m = re.search(r"(?:Reproduce\s*Steps|重現步驟)[：:]?\s*\n(.*?)(?=\n\s*\n|\Z)",
                          body, re.S | re.I)
            if m:
                steps = re.findall(r"^\s*(\d+)[.、)]", m.group(1), re.M)
                if len(steps) > 5:
                    warnings.append("W8 格式 %s 的 Reproduce Steps 有 %d 步（規範 5 步以內）"
                                    % (fname, len(steps)))

            # ② 成因推導：屬我方內部知識，寫進單裡等於要讀者多確認一件事
            #    只掃正文，**排除折疊的附註區**（規範允許把追溯與更正紀錄壓在附註）
            main = re.split(r"<details|##\s*附註|###\s*附註", body)[0]
            hits = sorted(set(re.findall(
                r"(推測|猜測|應該是因為|原因可能|可能是因為|研判為|懷疑是)", main)))
            if hits:
                warnings.append("W8 格式 %s 正文有成因推導（%s）—— 機制與推導進機制文件，不進 Bug 單"
                                % (fname, "、".join(hits)))

            # ③ 必要段落：Test Environment 是 RD 重現的前提
            if not re.search(r"(Test\s*Environment|測試環境)", body, re.I):
                warnings.append("W8 格式 %s 缺【Test Environment】—— RD 沒有站台與帳號就重現不了" % fname)

            # ④ 節次順序：規範第一句就是「順序固定、不得增節、不得調序」
            #    ⚠️ 只擋**相對順序倒過來**，不擋缺節、不擋人自己加的分析節 ——
            #       人工單常有「## 成因（資料自證）」「## 影響」，那些是允許的。
            #    ⛔ 這一項先前沒有機檢，平台連開 5 張順序錯的單而 lint 全綠
            #       （2026-08-26）：Test Environment 跑到最前面、Actual/Expect 對調。
            #       規範的理由是「讀者要在 10 秒內知道哪裡錯、應該是多少」，
            #       先讀到站台帳號就是把那 10 秒花掉了。
            # ⚠️ 歸檔單（`old/`）跳過 —— 它們已結案凍結、沒有人會再編輯，
            #    而排版依共用檔紀律**不是可改的項目**，報了就是純雜訊。
            if (os.sep + ARCHIVE_DIR + os.sep) in path or ("/" + ARCHIVE_DIR + "/") in path:
                continue
            prev = None                       # 當前這一段裡上一個規範節
            for line in body.splitlines():
                if re.match(r"\s*(#{1,4}\s*附註|<details)", line):
                    break                     # 附註是規範允許的雜物間，之後不看
                m = re.match(r"\s*#{1,4}\s*(.+?)\s*$", line)
                key = _canon_section(m.group(1) if m else line, bool(m))
                if key is None:
                    # ⚠️ 認不得的**章節標題**（`## 症狀 B`）代表另起一段 → 節序重新起算。
                    #    CRUX-034 就是兩症狀各一組 Reproduce／Expect，那不是調序。
                    if m:
                        prev = None
                    continue
                name = (m.group(1) if m else line.strip())[:40]
                if prev and key < prev[0]:
                    warnings.append("W8 順序 %s 的「%s」排在「%s」後面 —— "
                                    "規範是 %s（bug-report §4，不得調序）"
                                    % (fname, name, prev[1], " → ".join(_SECTION_ORDER)))
                    break
                if not prev or prev[0] != key:
                    prev = (key, name)

    # ── W10 缺佐證截圖 ─────────────────────────────────────────
    # ⭐ 使用者 2026-08-26 裁示：「佐證截圖可以更快速的讓看的人了解問題點」——
    #    與 `bug-report` §4 第一句「讀者要在 10 秒內知道哪裡錯」是同一件事。
    # ⛔ 只查**生效日之後**開的單（同 W7 的取捨）：全部追溯會一次噴四十幾則，
    #    訊號被雜訊淹沒 → 大家學會忽略 lint，比沒有檢查更糟。
    # ⭐ 真的沒畫面的缺陷是有的（API 回應、DB 對帳、壓測數據）——
    #    frontmatter 寫 `no_shot: <理由>` 豁免。重點是讓「不放圖」變成
    #    一個**要寫下理由的決定**，而不是默默省略。
    for bug_id, entries in sorted(bugs.items()):
        for path, meta, text in entries:
            fname = os.path.basename(path)
            if meta.get("status") in ("suggestion", "rejected", "superseded"):
                continue
            if str(meta.get("no_shot") or "").strip():
                continue                      # 明示豁免（理由寫在 frontmatter）
            if str(meta.get("found") or "") < SHOT_POLICY_DATE:
                continue                      # 生效日之前的舊單不追溯
            if IMG_TOKEN_RE.search(text.split("---", 2)[-1]):
                continue                      # 有引用到圖
            warnings.append("W10 缺截圖 %s 沒有任何佐證截圖%s —— "
                            "圖能讓讀者 10 秒內看懂問題點（`bug-report` §4）。"
                            "真的沒畫面就在 frontmatter 寫 `no_shot: <理由>`"
                            % (fname, _visual_hint(meta, text)))

    # ── W7 截圖未標注／引用無說明 ───────────────────────────────
    # 只有畫面的截圖，讀者得自己找問題在哪。規範見 bug-report skill「截圖規範」：
    # 每張圖要有①框選問題點②實際值vs應為值的說明③一句話標題。
    # 「有沒有框」靠 PNG 標記判定（`qa_common.shot` 產圖時會蓋章）；
    # 「有沒有說明」靠 markdown 的 alt text 判定。
    for path, text in texts:
        for alt, name in re.findall(
                r"!\[([^\]]*)\]\(\s*(?:\.\./|%s/)*shots/([^\s\)]+)\)" % ARCHIVE_DIR, text):
            if len(alt.strip()) < 2:
                warnings.append("W7 引用無說明 %s 於 %s 的 alt 是空的／過短 —— "
                                "寫成 `![實際X應為Y](shots/…)`"
                                % (name, os.path.basename(path)))
    # ⚠️ 只查規範生效日之後產生的圖。全部追溯會一次噴出上百則警告，
    #    訊號被雜訊淹沒 → 大家學會忽略 lint，比沒有檢查更糟。
    cutoff = time.mktime(time.strptime(ANNOTATION_POLICY_DATE, "%Y-%m-%d"))
    unmarked_old = 0
    for name in shots:
        if name not in referenced or "_fixed_" in name:
            continue                      # 未引用者已由 W1 處理；驗證圖以 JIRA 為準
        if _shot_mark(shot_path[name]) is not None:
            continue
        if os.path.getmtime(shot_path[name]) < cutoff:
            unmarked_old += 1
            continue
        warnings.append("W7 截圖未標注 %s 沒有標注標記 —— "
                        "請用 `qa_common.shot.capture_annotated` 產圖（框選＋說明）" % name)
    if unmarked_old and verbose:
        warnings.append("— %d 張舊圖未標注（早於規範生效日 %s，不追溯）"
                        % (unmarked_old, ANNOTATION_POLICY_DATE))

    # ── W6 索引過期 ─────────────────────────────────────────────
    # 過期的 BUG清單.md／_view/ 比沒有更危險：它看起來很權威，卻可能少一張新單、
    # 或把已修復的單還列在「待開立」。這是唯一會讓分組檢視說謊的情況。
    index_path = os.path.join(bugs_dir, "BUG清單.md")
    if os.path.isfile(index_path) and bugs:
        idx_mtime = os.path.getmtime(index_path)
        newer = [(os.path.basename(p), os.path.getmtime(p))
                 for entries in bugs.values() for p, _, _ in entries
                 if os.path.getmtime(p) > idx_mtime + 1]      # 1 秒容差，避開同批寫入
        view_dir = os.path.join(bugs_dir, "_view")
        stale_view = (os.path.isdir(view_dir) and
                      min([os.path.getmtime(os.path.join(view_dir, f))
                           for f in os.listdir(view_dir)] or [0]) < idx_mtime - 1)
        if newer:
            lag = (max(m for _, m in newer) - idx_mtime) / 60.0
            warnings.append(
                "W6 索引過期 BUG清單.md 早於 %d 張 Bug 單（最多 %.0f 分鐘），"
                "_view/ 分組可能失準 → python scripts\\gen_bug_index.py %s"
                % (len(newer), lag, product))
            for n, _ in sorted(newer, key=lambda x: -x[1])[:3]:
                warnings.append("       較新：%s" % n)
        elif stale_view:
            warnings.append("W6 索引過期 _view/ 早於 BUG清單.md → 重跑 gen_bug_index.py")

    # ── W9 斷引用：引用了圖，但那個檔案不存在 ───────────────────
    # ⛔ 判準是「**這個檔名在產品文件樹底下找不到**」，不是「路徑對不對」——
    #    單子裡常用相對於別處的寫法，硬解路徑會製造一堆假警告。
    #    ⚠️ 已經在 shots/ 的引用不歸這裡管（W1／W5／W7 各有分工）。
    known = set(shots)
    for dirpath, _dirnames, files in os.walk(base):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                known.add(f)
    seen_dangling = set()
    for path, text in texts:
        fname = os.path.basename(path)
        for tok in IMG_TOKEN_RE.findall(text):
            norm = tok.replace("\\", "/")
            if "shots/" in norm:
                continue
            leaf = norm.rsplit("/", 1)[-1]
            # ⚠️ 只認兩種**明確是引用**的形態，否則含空白的舊檔名
            #    （「截圖 2026-08-11 下午3.45.17.png」）會被從中間切開，變成假警告：
            #      ① 帶路徑分隔（`.playwright-mcp/xxx.png`）
            #      ② 檔名以本地或 JIRA 單號開頭（就是我們自己的命名規範）
            if "/" not in norm and not ID_RE.match(leaf):
                continue
            if leaf in known or os.path.exists(os.path.join(ROOT, norm)):
                continue
            key = (fname, leaf)
            if key in seen_dangling:
                continue
            seen_dangling.add(key)
            warnings.append(
                "W9 斷引用 %s 引用的截圖不存在：%s —— "
                "拍完沒搬就會這樣（`.playwright-mcp/` 是共用暫存，會被清掉）。"
                "找得回就 `stamp_shots.py` 搬進 shots/，找不回就把該行改成文字佐證或重拍"
                % (fname, leaf))

    if verbose and exempted:
        warnings.append("— 已豁免死圖檢查（%d 張，_fixed_ 驗證圖或 shots_external）：%s"
                        % (len(exempted), "、".join(exempted)))

    total_mb = sum(os.path.getsize(shot_path[s]) for s in shots) / 1048576.0
    stat = "📊 %s：%d 單 / %d 圖 / %.1f MB（豁免 %d、待清 %d）" % (
        product, len(bugs), len(shots), total_mb, len(exempted), len(dead))
    return errors, warnings, dead, stat


def quarantine(base, dead, do_it, older_than):
    """把死圖搬到 shots/_quarantine/，並留一份還原清單。不刪檔。

    ⚠️ 寬限期（older_than 天）：剛截好、還沒寫進 Bug 單的圖天生「無人引用」，
       若不設寬限期會把工作中的素材當垃圾清掉。預設只處理 14 天前的檔案。
    """
    shots_dir = os.path.join(base, "bugs", "shots")
    qdir = os.path.join(shots_dir, "_quarantine")
    cutoff = time.time() - older_than * 86400
    paths = {}
    for d in (shots_dir, os.path.join(base, "bugs", ARCHIVE_DIR, "shots")):
        for n in dead:
            if os.path.isfile(os.path.join(d, n)):
                paths[n] = os.path.join(d, n)
    fresh = [n for n in dead if os.path.getmtime(paths[n]) > cutoff]
    dead = [n for n in dead if n not in fresh]
    if fresh:
        print("  ⏳ %d 張在寬限期內（%d 天）暫不處理：%s"
              % (len(fresh), older_than, "、".join(fresh[:5]) + ("…" if len(fresh) > 5 else "")))
    if not dead:
        print("  無待隔離的死圖。")
        return
    print("  %s %d 張死圖 → %s" % ("搬移" if do_it else "[預演] 將搬移", len(dead),
                                   os.path.relpath(qdir, ROOT)))
    for name in dead:
        print("    %s %s" % ("→" if do_it else " ·", name))
    if not do_it:
        print("  （預演，未動任何檔案；確定要搬請加 --yes）")
        return
    os.makedirs(qdir, exist_ok=True)
    for name in dead:
        shutil.move(paths[name], os.path.join(qdir, name))
    with io.open(os.path.join(qdir, "README.md"), "a", encoding="utf-8", newline="\n") as f:
        f.write("\n## 隔離批次\n\n本批 %d 張圖在隔離時無任何文件引用。\n"
                "**未刪除** —— 確認不需要後可手動刪除本目錄；若發現仍需要，"
                "直接搬回上層 `shots/` 即可。\n\n" % len(dead))
        for name in dead:
            f.write("- %s\n" % name)
    print("  完成。還原方式：把檔案從 _quarantine/ 搬回 shots/。")


def main():
    ap = argparse.ArgumentParser(description="檢查 Bug 單與截圖的一致性與命名規範")
    ap.add_argument("--product", choices=list(PRODUCTS), help="只檢查指定專案")
    ap.add_argument("--verbose", action="store_true", help="連已豁免的項目也列出")
    ap.add_argument("--quarantine", action="store_true", help="把死圖搬到 shots/_quarantine/")
    ap.add_argument("--yes", action="store_true", help="配合 --quarantine，實際執行搬移")
    ap.add_argument("--older-than", type=int, default=14, metavar="N",
                    help="只隔離 N 天前的死圖，避免清掉剛截好還沒寫進單子的圖（預設 14）")
    args = ap.parse_args()

    targets = [args.product] if args.product else list(PRODUCTS)
    total_err = 0
    for product in targets:
        base = PRODUCTS[product]
        errors, warnings, dead, stat = lint(product, base, args.verbose)
        print("\n" + "=" * 60)
        print(stat)
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
        if args.quarantine:
            print()
            quarantine(base, dead, args.yes, args.older_than)
        total_err += len(errors)

    print()
    sys.exit(1 if total_err else 0)


if __name__ == "__main__":
    main()
