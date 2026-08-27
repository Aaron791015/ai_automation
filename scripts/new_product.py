# -*- coding: utf-8 -*-
"""把一個新產品接進這個工作區結構（目錄、產品 skill、交接檔、產品註冊）。

用途：本工作區預計成為「標準測試工程師 AI 助手的專案結構」，讓其他 QA 同事
      餵入自己產品的知識。而「新產品要怎麼接進來」原本散在各處、沒有一份文件講完 ——
      漏掉任何一步（例如交接檔沒用對檔名結尾）就不會被 lint 檢查到。
      本腳本把那些步驟變成一支會執行的指令。

使用方式：
    python scripts\\new_product.py --id 樂透 --docs-dir 樂透 --bug-prefix LOTTO
    python scripts\\new_product.py --id 樂透 --docs-dir 樂透 --bug-prefix LOTTO --dry-run
    python scripts\\new_product.py --list                       # 列出已註冊的產品

前置條件：無（純本機檔案建立）。

會建立：
    config/products.json 註冊一列
    docs/<docs_dir>/、docs/<docs_dir>/bugs/{shots,_reports,_handover}/
    docs/<docs_dir>/<id>_驗證交接.md      ← 檔名結尾必須是「驗證交接.md」才會被 lint D6 檢查到
    tests/<tests_dir>/、tools/<qa_tools_dir>/pages/
    .claude/skills/<skill>/SKILL.md       ← 意圖對照表骨架

⛔ 不會做（會印成待辦，因為需要人的判斷）：
    補 config/environments.{md,json} 的站台與帳密
    首次探索（依 `testcase-design` skill 產出覆蓋矩陣）
"""
import argparse
import io
import json
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = chr(10)
PRODUCTS_JSON = os.path.join(ROOT, "config", "products.json")
# 測試平台的**呈現層**（字樣／配色／環境徽章）。產品定義本身在上面那份，這裡不重複。
# ⚠️ 用函式而非模組層常數 —— 測試沙箱 monkeypatch 的是 `ROOT`，
#    模組層常數在 import 當下就固定成真實路徑，**測試會寫進真的 repo**
#    （2026-08-23 實際發生：測試把 gamma／lotto 寫進了平台的 products.json）。
# ⛔ **不可寫成模組層常數** —— `tests/tooling/test_new_product.py` 的 sandbox
#    只 monkeypatch `ROOT`，模組層常數在 import 當下就綁死了真實路徑，
#    於是跑一次 pytest 就會寫進真的 `config/environments.json`（2026-08-24 實際發生）。
#    同檔第 177 行對 `PLATFORM_PRODUCTS_JSON` 記過一模一樣的教訓。
def environments_json():
    return os.path.join(ROOT, "config", "environments.json")


def platform_products_json():
    return os.path.join(ROOT, "tools", "test_platform", "registry", "products.json")
# 平台的預設配色盤（與 core/registry.py 的 _FALLBACK_COLORS 同一組）
PLATFORM_COLORS = ["#4fa9ff", "#8f8cff", "#59d3a4", "#ffb454", "#ff7a9c", "#7ad9ff"]

SKILL_TEMPLATE = """---
name: {skill}
description: {label}產品的知識導覽與必記不變量 — <一句話列出主要主題>。開始任何{label}任務前先載入；也用於查「{label}的某項知識寫在哪裡」。
---

# {label} 產品知識導覽

> **本 skill 是地圖，不是知識本體。** 先用 §2 找位置，再去 Read 那一份。
> ⚠️ 一列最多兩行：只回答「去哪裡看」＋「一句話的坑」，**知識本體留在機制文件**。

## 1. 必記的不變量（不查文件也要知道的）

| # | 不變量 | 用途／後果 |
| --- | --- | --- |
| 1 | <填：不知道就會做錯的事實> | <後果> |

## 2. 我要做這件事 → 去讀這裡（★意圖對照表）

| 意圖 | 位置 |
| --- | --- |
| <使用者會怎麼問（不是檔名）> | docs/{docs_dir}/ 底下的某份機制文件 §N |

> ⚠️ 填進來時**檔名要用反引號括起來** —— `lint_docs` 的 D5 靠反引號裡的檔名
> 檢查指標有沒有斷掉。上面那一列刻意不加反引號，免得骨架本身就報紅。

## 3. 環境速記

| 項目 | 值 |
| --- | --- |
| 後台 | 見 `config/environments.md`「專案：{label}」 |

## 4. 配套 skill（依任務性質載入）

| 這次要做什麼 | 先載入 |
| --- | --- |
| 開工接手／收尾交接 | `handoff` |
| 盤點功能點、設計案例 | `testcase-design` |
| 操作瀏覽器 | `browser-ops` |
| 開 Bug 單、寫報告 | `bug-report` |
| 學到新東西要落筆 | `writeback` |

## 5. 學到新東西時

依 **`writeback` §1 的分流表**決定寫哪個檔，並在本檔 §2 補一列（以使用者會怎麼問為鍵），
最後登記 `docs/INDEX.md`。

## 6. 收尾時 ★ 與 §5 是兩件事

§5 處理**知識**，本節處理**狀態** —— 更新 `docs/{docs_dir}/{pid}_驗證交接.md`，見 `handoff` skill。
"""

HANDOVER_TEMPLATE = """# {label} 驗證交接（活文件）

> **最後更新：{today}**
> 本檔只放**狀態**（做完了／卡住了／動過了／還沒驗完），**不放知識** —— 知識在 §4 指路。
> 骨架與四條紀律見 `writeback` §4；開工與收尾流程見 `handoff` skill。

## 1. ⛔ 當前 blocker

目前無 blocker。

## 2. ★ 待辦總覽

> ⚠️ 編號寫入前用 `python scripts\\next_todo_id.py --handover <本檔> --kind T` 取號。

### 2.1 可立即動手

| # | 事項 | 說明 | 優先 |
| --- | --- | --- | --- |
| T1 | <首次探索：依 `testcase-design` 產出覆蓋矩陣> | 五來源交叉盤點功能點，標風險與目標深度 | 高 |

### 2.2 等外部裁定

目前無。

### 2.3 等他人處理

目前無。

### 2.4 被 blocker 擋住

目前無。

## 3. 批次交接索引

| 批次檔 | 殘留狀況 |
| --- | --- |
| （尚無） | — |

## 4. 文件地圖

| 要查什麼 | 去哪 |
| --- | --- |
| 意圖 → 位置 | `.claude/skills/{skill}/SKILL.md` §2 |
| 機制與公式 | `docs/{docs_dir}/` |
| 覆蓋矩陣（還有什麼沒驗） | `docs/{docs_dir}/<待建立>_驗證項目清單.md` |

## 5. 測試資料現況

| 動了什麼 | 屬哪張單 | 清掉會失去什麼 |
| --- | --- | --- |
| （尚無） | — | — |

## 6. 維護規則

- **開工**：載入 `handoff`，讀 §1 → §2 → §5
- **收尾**：知識回寫（`writeback`）→ 更新本檔 → 跑 `python scripts\\lint_docs.py --product {pid}`
"""


#: `docs/INDEX.md` 的產品分區骨架。
#:
#: ⚠️ **一定要有 `### ` 子節** —— 平台寫機制文件時會照子節登記索引，
#:    只有 `## ` 而沒有子節的話它挑不到節，就只能回一句「請自己補」。
INDEX_SECTION = """
## {pid} 專案

> 這一區由 `scripts/new_product.py` 建立。⚠️ **新增或大改文件時，
> 描述要同步更新且涵蓋該檔的實際內容** —— 索引描述失真等於別人搜尋不到。

### 規則與玩法
| 檔案 | 說明 |
| --- | --- |
| （待補） | 玩法規格、賠率表、判定規則 |

### 機制與設定
| 檔案 | 說明 |
| --- | --- |
| （待補） | 功能機制、API 契約、UI 元素對照 |

### 接手／狀態（活文件）
| 檔案 | 說明 |
| --- | --- |
| ⭐ `{handover_name}` | **交接活文件**：§1 blocker／§2 待辦總覽／§3 批次交接索引／§4 文件地圖／§5 測試資料現況／§6 維護規則 |
"""


def add_index_section(index_path, ctx, dry_run=False):
    """在 `docs/INDEX.md` 追加一個產品分區。回 (做了沒, 說明)。

    ⚠️ 交接檔名**不可以照樣板拼** —— 既有產品的檔名不一定是
       `<id>_驗證交接.md`（CRUX 的是 `CRUX_功能驗證交接.md`），
       拼錯就會被 lint 的 D1 判成斷連結（2026-08-23 實測）。
    """
    ctx = dict(ctx)
    ctx.setdefault("handover_name", "%s/%s_驗證交接.md"
                   % (ctx.get("docs_dir", ""), ctx.get("pid", "")))
    if not os.path.isfile(index_path):
        return False, "找不到 docs/INDEX.md"
    cur = io.open(index_path, encoding="utf-8").read()
    if ("## %s 專案" % ctx["pid"]) in cur:
        return False, "INDEX 已有 `%s` 的分區" % ctx["pid"]
    if not dry_run:
        io.open(index_path, "w", encoding="utf-8", newline="\n").write(
            cur.rstrip() + "\n" + INDEX_SECTION.format(**ctx))
    return True, "docs/INDEX.md（產品分區 ＋ 三個子節）"


def load():
    return json.loads(io.open(PRODUCTS_JSON, encoding="utf-8").read())


def _display_width(s: str) -> int:
    """字串在主視覺裡佔幾格 —— CJK 算 2 格，其餘算 1 格。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _default_wordmark(product_id: str, skill: str) -> str:
    """主視覺投影的字樣。

    ⭐ **產品名夠短就用產品名** —— 中文名通常比英文代號更有辨識度
       （樂透 > LOTTO）。太長的（投注機器人）撐不進基座間距，退回代號大寫。
       原型自己挑的是 CRUX／Seven／ChatBot／共通，最後一個就是中文。
    ⚠️ 這只是**預設值**：`registry/products.json` 的 `wordmark` 隨時可改，
       中文、英文、混排都支援（`--wordmark` 可在接入時直接指定）。
    """
    return product_id if _display_width(product_id) <= 6 else skill.upper()


def add_environment_stub(slug: str, label: str, dry: bool) -> tuple[bool, str]:
    """在 `config/environments.json` 放一段這個產品的骨架。

    ★ 為什麼是「骨架」而不是「提示去補」：打開檔案時該填的層級已經在那裡，
      人只要把 `<後台網址>` 換掉。給提示的話他得自己判斷巢狀怎麼分、slug 怎麼拼 ——
      而 slug 拼錯的話平台的網址與 tool.json 的鍵全部對不上。

    ⛔ **文字插入，不是 `json.dumps` 整份寫回。** 這份檔案刻意把小物件寫成一行
       （`{ "name": "…", "url": "…" }`），整份 dumps 會把它全部攤開 ——
       改一個產品、diff 卻是整份檔（2026-08-24 實測 118 增 21 刪）。
       平台的設定檔存回也守同一條（`core/config_files.py`，`test_存回不重排版`）。

    ⛔ 已經有這個鍵就**不動**（接第二次、或人已經填過了）。
    ⛔ 不寫任何帳密 —— 這份檔案可版控。要填帳密的人自己填（QAT 測試帳密可以）。
    """
    path = environments_json()
    if not os.path.isfile(path):
        return False, "config/environments.json 不存在，跳過"
    text = io.open(path, encoding="utf-8").read()
    try:
        data = json.loads(text)
    except ValueError as e:
        return False, "config/environments.json 不是合法 JSON（%s），跳過不動它" % e
    if slug in data:
        return False, "`%s` 已存在，不覆蓋" % slug

    stub = {
        "_comment": ("【%s】接產品時自動放的骨架 —— 把 <…> 換成真的網址即可。"
                     "巢狀層次自己決定：一個產品有多個彩種或多個站台時再往下分一層。"
                     "⛔ 正式環境與 token 一律不要寫在這裡。" % label),
        "qat": {
            "backend_url": "http://<後台網址>/",
            "frontend_url": "http://<前台網址>/",
            "admin": {"username": "<測試帳號>", "password": "<測試密碼>"},
        },
    }
    body = json.dumps({slug: stub}, ensure_ascii=False, indent=2)
    # 去掉外層大括號，並把每一行縮排對齊到檔案的第一層
    inner = NL.join(body.split(NL)[1:-1])

    close = text.rstrip()
    if not close.endswith("}"):
        return False, "config/environments.json 結尾不是 `}`，看不懂的格式，跳過不動它"
    head = close[:close.rfind("}")].rstrip()
    sep = "," if head.rstrip().endswith(("}", "]", '"')) or head.rstrip().endswith("e") else ""
    merged = head + sep + NL + inner + NL + "}" + NL

    try:
        json.loads(merged)                      # ⛔ 插壞了寧可不寫
    except ValueError as e:
        return False, "插入後不是合法 JSON（%s），已放棄不動原檔" % e
    if not dry:
        io.open(path, "w", encoding="utf-8", newline=NL).write(merged)
    return True, "已放好 `%s` 的 qat 骨架（到平台的 設定 → 設定檔 填網址）" % slug


def main(argv=None):
    ap = argparse.ArgumentParser(description="把一個新產品接進工作區結構")
    ap.add_argument("--id", help="產品正式名（會用在 --product 參數、Bug 單 product 欄）")
    ap.add_argument("--docs-dir", help="docs/ 下的目錄名（通常同 --id）")
    ap.add_argument("--bug-prefix", help="本地 Bug ID 前綴，如 LOTTO")
    ap.add_argument("--skill", help="產品 skill 名（小寫英數，預設由 --docs-dir 推導）")
    ap.add_argument("--tests-dir", help="tests/ 下的目錄名（預設同 --skill）")
    ap.add_argument("--alias", nargs="*", default=[], help="別名（如英文代號）")
    ap.add_argument("--wordmark", default=None,
                    help="主視覺投影的字樣（預設：產品名夠短就用產品名，否則用英文代號大寫）；中英皆可")
    ap.add_argument("--jira-key", help="JIRA project key（可留空）")
    ap.add_argument("--dry-run", action="store_true", help="只印出會做什麼，不動檔案")
    ap.add_argument("--list", action="store_true", help="列出已註冊產品")
    a = ap.parse_args(argv)

    data = load()
    if a.list:
        print("已註冊的產品（config/products.json）")
        for p in data["products"]:
            print("  %-10s docs/%-12s Bug 前綴 %-6s skill /%s"
                  % (p["id"], p["docs_dir"], p["bug_prefix"], p.get("skill") or "-"))
        return 0

    if not (a.id and a.docs_dir and a.bug_prefix):
        ap.error("需要 --id、--docs-dir、--bug-prefix（或用 --list）")
    if any(p["id"] == a.id for p in data["products"]):
        raise SystemExit("產品 `%s` 已註冊，請換一個 --id（或直接編輯 config/products.json）" % a.id)
    if any(p["bug_prefix"].upper() == a.bug_prefix.upper() for p in data["products"]):
        raise SystemExit("Bug 前綴 `%s` 已被使用 —— 前綴必須唯一，否則 Bug ID 會撞" % a.bug_prefix)

    # skill 名與目錄名一律用**小寫英文**（既有慣例 crux／wbot／qixing；`tools/<skill>_qa` 亦同）。
    # 產品 id 可以是中文，但推導不出英文名時要人明講 —— 否則會產生 `tools/樂透_qa` 這種目錄。
    # ⛔ 目錄名先擋掉會讓路徑變難處理的字元 —— 空白會讓 `handover_scope` 的
    #    git pathspec 與各處的 `--product` 引數都要額外引號，路徑分隔則直接建錯層
    #    （2026-08-23 情境 A 走查：`Big Lotto` 與 `a/b` 都照建）。
    if not re.fullmatch(r"[^\\/:*?\"<>|\s]+", a.docs_dir):
        raise SystemExit(
            "文件目錄名 `%s` 不合法 —— 不可含空白或 \\ / : * ? \" < > |。\n"
            "  它會變成 docs/<目錄名>/，也會出現在 handover_scope 的 git pathspec 裡。\n"
            "  建議用英文，例：Lotto" % a.docs_dir)

    skill = a.skill or (a.alias[0] if a.alias else None) or a.docs_dir.lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", skill):
        raise SystemExit(
            "skill 名必須是小寫英數（既有慣例：crux／wbot／qixing）。\n"
            "  產品 id 可以是中文，但 skill 與 tools/<skill>_qa 目錄要用英文。\n"
            "  請加 --skill <英文名>，或用 --alias <英文名> 讓它自動採用。")
    tests_dir = a.tests_dir or skill
    today = __import__("datetime").date.today().isoformat()
    ctx = dict(pid=a.id, label=a.id, docs_dir=a.docs_dir, skill=skill, today=today)

    dirs = [
        os.path.join(ROOT, "docs", a.docs_dir),
        os.path.join(ROOT, "docs", a.docs_dir, "bugs"),
        os.path.join(ROOT, "docs", a.docs_dir, "bugs", "shots"),
        os.path.join(ROOT, "docs", a.docs_dir, "bugs", "_reports"),
        os.path.join(ROOT, "docs", a.docs_dir, "bugs", "_handover"),
        os.path.join(ROOT, "tests", tests_dir),
        os.path.join(ROOT, "tools", "%s_qa" % skill, "pages"),
        os.path.join(ROOT, ".claude", "skills", skill),
    ]
    files = {
        os.path.join(ROOT, ".claude", "skills", skill, "SKILL.md"): SKILL_TEMPLATE.format(**ctx),
        os.path.join(ROOT, "docs", a.docs_dir, "%s_驗證交接.md" % a.id): HANDOVER_TEMPLATE.format(**ctx),
    }
    entry = {
        "id": a.id, "label": a.id, "docs_dir": a.docs_dir, "bug_prefix": a.bug_prefix.upper(),
        "aliases": a.alias, "tests_dir": tests_dir, "qa_tools_dir": "%s_qa" % skill,
        "skill": skill, "jira_key": a.jira_key,
        "handovers": ["docs/%s/%s_驗證交接.md" % (a.docs_dir, a.id)],
    }

    print("接入新產品：%s" % a.id)
    for d in dirs:
        print("  %s 目錄  %s" % ("[dry]" if a.dry_run else "建立", os.path.relpath(d, ROOT)))
        if not a.dry_run:
            os.makedirs(d, exist_ok=True)
    for f, body in files.items():
        exists = os.path.isfile(f)
        print("  %s 檔案  %s%s" % ("[dry]" if a.dry_run else ("跳過" if exists else "建立"),
                                 os.path.relpath(f, ROOT), "（已存在，不覆蓋）" if exists else ""))
        if not a.dry_run and not exists:
            io.open(f, "w", encoding="utf-8", newline="\n").write(body)
    print("  %s 註冊  config/products.json" % ("[dry]" if a.dry_run else "寫入"))
    if not a.dry_run:
        data["products"].append(entry)
        io.open(PRODUCTS_JSON, "w", encoding="utf-8", newline="\n").write(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    # ── config/environments.json 的骨架 ────────────────────────
    # ⛔ 不可以只在最後印一行「記得補環境設定」—— 同 INDEX 分區那條的理由：
    #    靠自律的規範必然漂移，而漏填的後果是所有腳本都連不上站台。
    ok_env, why_env = add_environment_stub(skill, a.id, a.dry_run)
    print("  %s 骨架  config/environments.json —— %s"
          % ("[dry]" if a.dry_run else ("寫入" if ok_env else "跳過"), why_env))

    # ── docs/INDEX.md 的產品分區 ────────────────────────────────
    # ⛔ 不可以只在最後的提示裡叫人「記得登記」—— 靠自律的規範必然漂移，
    #    而沒有分區的話**平台的自動登記也永遠不會生效**（2026-08-23 實跑）。
    ok_idx, why_idx = add_index_section(
        os.path.join(ROOT, "docs", "INDEX.md"), ctx, a.dry_run)
    print("  %s 分區  %s" % ("[dry]" if a.dry_run else ("寫入" if ok_idx else "跳過"),
                           why_idx))

    # ── 測試平台的呈現層（選配）──────────────────────────────
    # 平台本來就會從 config/products.json 自動看到新產品（含自動配色），
    # 這裡只是把字樣與配色寫定，讓同事有個可以改的落點。
    # ⚠️ 平台不存在時靜默跳過 —— 同事可能整個刪掉 tools/test_platform。
    _pp = platform_products_json()
    if os.path.isfile(_pp):
        print("  %s 註冊  tools/test_platform/registry/products.json（呈現層）"
              % ("[dry]" if a.dry_run else "寫入"))
        if not a.dry_run:
            pdata = json.loads(io.open(_pp, encoding="utf-8").read())
            items = pdata.setdefault("products", [])
            if not any(x.get("id") == skill for x in items):
                used = {x.get("color") for x in items}
                color = next((c for c in PLATFORM_COLORS if c not in used),
                             PLATFORM_COLORS[len(items) % len(PLATFORM_COLORS)])
                items.append({
                    "id": skill, "wordmark": a.wordmark or _default_wordmark(a.id, skill),
                    "hero_pillar": True,
                    "label": a.id, "short": a.id, "subtitle": "",
                    "color": color, "env_badge": "QAT",
                    "order": len(items) + 1,
                })
                io.open(_pp, "w", encoding="utf-8",
                        newline="\n").write(
                    json.dumps(pdata, ensure_ascii=False, indent=2) + "\n")

    print("""
接下來要人做的事（腳本不做，因為需要判斷）：
  1. 填站台網址 —— `config/environments.json` 的骨架已經放好了，
     到平台的 **設定 → 設定檔 → 測試環境（程式讀）** 直接改（那裡有範例格式可看），
     或用編輯器改。人讀版的說明另外補 `config/environments.md`
  2. 首次探索 —— 載入 `testcase-design`，寫 charter → 五來源交叉盤點 → 產出覆蓋矩陣
  3. 把探索到的機制寫成 `docs/{d}/` 的機制文件，並登記 `docs/INDEX.md`
  4. 填 `.claude/skills/{s}/SKILL.md` 的 §1 不變量與 §2 意圖對照表
  5. （選）若該產品要分「功能線／效能線」兩份交接檔，在 `config/products.json`
     的該產品 `handover_scope` 補一列指定各自負責的路徑
     （⚠️ 兩線要各自切開，否則兩份會互相誤報 D6）；只有一份的話不必動（預設就是 docs/{d}）
  6. （選）主視覺投影的字樣目前是「{w}」——
     要改的話動 `tools/test_platform/registry/products.json` 的 `wordmark`
     （中英皆可；太長會撐不進基座間距，原型是 CRUX／Seven／ChatBot／共通）

驗收：`python scripts\\lint_docs.py --product {p}` 應為綠。""".format(d=a.docs_dir, s=skill, p=a.id, w=(a.wordmark or _default_wordmark(a.id, skill))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
