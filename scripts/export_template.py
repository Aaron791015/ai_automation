# -*- coding: utf-8 -*-
"""把本工作區匯出成一份**乾淨的標準專案範本**，給同事直接拿去用。

用途
----
本工作區同時是「標準測試工程師 AI 助手的專案結構」的範本原型。
要給同事的時候，**不要直接複製這個資料夾** —— 資料夾複製會帶走所有
gitignored 的檔案，而祕密全在那裡（`config.local.json`、`docs/<產品>/bugs/` 的
測試站帳密、`reports/created_accounts/` 的數百組帳號、`_share/` 的交付副本、
138MB 綁死絕對路徑的 `.venv`）。**clone 至少有 `.gitignore` 擋，複製資料夾把那層保護拿掉了。**

所以改為**白名單匯出**：只有明確列在 `EXPORT` 的通用層會被複製，
其餘一律不存在。白名單 fail-safe（漏放 → 少東西，看得出來），
黑名單 fail-open（漏宣告 → 默默留下來）。

使用方式
--------
    python scripts\\export_template.py --out D:\\QA-Template            # 匯出並自動驗收
    python scripts\\export_template.py --out C:\\GitLab\\QA-Template --sync  # ★ 覆蓋版控中的鏡像（保留 .git）
    python scripts\\export_template.py --out D:\\QA-Template --dry-run  # 只列出會複製什麼
    python scripts\\export_template.py --verify D:\\QA-Template         # 只對既有匯出跑三條驗收
    python scripts\\export_template.py --compare D:\\QA-Template        # ★ 某份既有的匯出該不該更新
    python scripts\\export_template.py --audit                          # ★ 維護用：列出未分類的路徑

同事已經在用了，範本後來又改了怎麼辦
--------------------------------------
匯出是**一次性快照**，而同事那邊也會有自己的客製（`CLAUDE.md` §1、他的產品 skill…）。
光比「現在的範本 vs 他的目錄」**分不出「他改的」與「範本更新的」**。

所以匯出時會把每個檔的 sha1 記進 `.template-export` 當**基準線**，之後：

    python scripts\\export_template.py --compare <他的目錄>

做三方比較，把差異分成五類：**範本新增**／**只有範本改了（可直接覆蓋）**／
**兩邊都改了（要人合併）**／**只有他改了（別覆蓋）**／**判不出來（沒有基準線）**。

⛔ 這支只**報告**，不會自動覆蓋任何檔案 —— 合併是人的判斷。


維護（★ 讀這段）
----------------
白名單的敵人是**漏更新** —— 新增一支通用 skill 卻忘了加進 `EXPORT`，
匯出的範本就少一塊，而且沒有人會發現。

防治是 `--audit`：它把 repo 的每個路徑逐一對照四個清單
（`EXPORT`／`SKELETON`／`NEVER`／產品層），**任何一個都對不上就叫**。
`tests/tooling/test_export_template.py` 會跑同一份檢查 —— 所以
**新增檔案卻沒分類 = 測試紅燈**，不是靜默漏掉。

前置條件
--------
無。匯出目標必須是**空目錄**、**不存在**、或**上一次由本工具匯出的目錄**
（認得 `.template-export` 標記，會先清空再寫）。
⛔ 不認得的非空目錄一律拒絕，**沒有 `--force` 可以繞過** —— 本工具會 `rmtree` 目標，
   認錯目錄的代價太大。
"""
import argparse
import datetime
import fnmatch
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# INDEX 骨架與 reset_workspace 共用一份 —— 兩支腳本產出的骨架必須一致，
# 各留一份就會分岔（本工作區踩過太多次）。
from reset_workspace import INDEX_SKELETON      # noqa: E402

# ── ① 原樣匯出的通用層 ────────────────────────────────────────
#    路徑為 repo 相對；目錄會整個複製（但仍排除 NEVER 與產品層）。
EXPORT = [
    "CLAUDE.md", "README.md",
    ".gitignore", ".gitattributes", ".mcp.json", ".mcp",
    "pyproject.toml", "requirements.txt",
    ".claude/memory-seed",
    "config/README.md", "config/config.example.json",
    "data/README.md",
    "docs/README.md",
    "reports/README.md",
    "scripts",                    # 產品專屬的探索腳本由 extra_paths 排除
    "tests/README.md", "tests/tooling",
    "tools/README.md", "tools/qa_common", "tools/jira_qa", "tools/test_platform",
]

# 通用的流程 skill（產品 skill 由 products.json 決定，一律不匯出）
GENERIC_SKILLS = [
    "handoff", "testcase-design", "browser-ops", "ui-test",
    "bug-report", "jira-verify", "perf-test", "writeback", "commit",
]
EXPORT += [".claude/skills/%s" % s for s in GENERIC_SKILLS]

# ── ② 換成骨架（結構留著、內容清空）──────────────────────────
PLATFORM_CONFIG_SKELETON = u"""{
  "_comment": [
    "測試平台設定（版控）。敏感或個人覆寫請放 platform_config.local.json（不版控）。",
    "host 刻意預設 127.0.0.1：同事各自跑自己的實例、用自己的 Claude 帳號。",
    "",
    "平台一律真的執行 —— 沒有模擬模式（2026-08-23 移除）。"
  ],
  "host": "127.0.0.1",
  "port": 5300,
  "poll_seconds": 2,
  "recent_run_keep_minutes": 15,
  "jira_cache_minutes": 30,
  "claude": {
    "executable": null,
    "default_model": "sonnet",
    "fallback_model": "sonnet",
    "_compact_comment": [
      "compact_tokens：邊界壓縮門檻 —— 只在「回覆結束、交還給人」那一刻換一份較短的",
      "工作記憶（core/session_compact.py）。0 ＝ 關閉；個別任務可用 tasks/*.json 覆寫。",
      "autocompact_tokens：交給 claude CLI 的安全網，只擋「單段失控」（一則訊息內跑",
      "幾百輪、中間沒有邊界），刻意設得很高。⛔ 調低就退化成『途中壓縮』，會壓掉還沒",
      "寫成草稿的量測值。CLI 只收 100k~1M，超範圍會夾住。"
    ],
    "compact_tokens": 150000,
    "autocompact_tokens": 500000
  },
  "ui": {
    "motion": true
  }
}
"""


PRODUCTS_SKELETON = {
    "_comment": [
        u"★ 產品定義的單一來源。所有腳本都讀這裡，不要在別處再存一份。",
        u"",
        u"欄位說明：",
        u"  handovers      該產品的交接活文件（lint_docs D6 檢查它們有沒有跟上進度）",
        u"  handover_scope 每份交接檔「負責哪些路徑」。未列者退回 docs/<docs_dir>。",
        u"                 ⚠️ 功能線與壓測線要各自切開，否則兩份會互相誤報 D6。",
        u"  extra_paths    該產品擁有、但不在 docs/tests/tools/skills 標準四處的路徑",
        u"                 （壓測工具、探索腳本…）。reset_workspace 與 export_template 靠它判斷歸屬。",
        u"",
        u"新增產品請用：python scripts\\new_product.py --id <ID> --docs-dir <目錄名> --bug-prefix <前綴>",
    ],
    "products": [],
    "common_handovers": ["docs/共通_工作區維護交接.md"],
}

ENV_MD_SKELETON = u"""# 測試環境清單（依產品專案分區）

> 本檔僅放**測試站（QAT/STG）**的站台 URL 與測試帳密，供速查使用。
> 正式環境（prod）帳密/token/連線字串一律放 `config.local.json`，切勿寫入本檔。
> 未填欄位留空或以 `TBD` 標示。括號慣例：`(帳號, 密碼, 驗證說明)  # 用途`。
>
> **⛔ STG 環境需逐次取得使用者授權才可使用；預設一律走 QAT**（見 `CLAUDE.md` §5 第一條）。

---

## 專案：<產品名>

| 環境 | 用途 | 站台 | 帳號 |
| --- | --- | --- | --- |
| QAT | 日常測試 | `<url>` | `(帳號, 密碼)` |
| STG | ⛔ 需授權 | `<url>` | `(帳號, 密碼)` |

### 子帳號的分配

站台是「**同帳號他處登入即踢掉前者**」。併行時要分開帳號：
一組給 pytest、一組給 MCP 探索、一組給第二個 session。
"""

ENV_JSON_SKELETON = {
    "_comment": ("程式讀取用的結構化環境設定（僅 QAT/STG 測試站，依 config/README.md 政策可版控）；"
                 "人讀版見 environments.md。敏感/prod 設定放 config.local.json（同結構深度合併覆蓋）。"),
    # setup_test_env.ps1 會逐一戳這裡宣告的站台。留空＝略過連通性檢查。
    # ⛔ 網址不可寫回腳本裡 —— scripts/ 是通用層（2026-08-23 範本驗收）。
    "connectivity_check": [],
}

HANDOVER_SKELETON = u"""# 共通（工作區維護）— 交接說明（活文件）

> **最後更新：<日期>**（每次 session 收尾時更新，見文末「維護規則」）
>
> 給接手的 session：**先讀 §1 blocker 與 §2 待辦總覽**，其餘為背景。
> 這份只放**狀態**（現在卡在哪、還有什麼沒做完）；**知識**在 §4 指的那些檔裡，兩者不重複。

> ## ⚠️ 本檔與產品交接檔的分工（先看這段，免得放錯地方）
>
> | 這件事屬於 | 寫哪一份 |
> | --- | --- |
> | 某個**產品**的功能／需求／回歸／效能驗證 | `docs/<產品>/<產品>*驗證交接.md` |
> | **工作區本身**：規範、skill、治理腳本、測試框架、測試平台 | **本檔** |
>
> ★ 判準：**這件事換一個產品還會不會存在？** 會 → 本檔；不會 → 產品交接檔。

---

## 1. ⛔ 當前 blocker

（無）

## 2. ★ 待辦總覽

| # | 待辦 | 狀態 |
| --- | --- | --- |
| | | |

> ⚠️ 編號寫入前用 `python scripts\\next_todo_id.py --handover <本檔> --kind T` 取號。

## 3. 本檔負責的範圍（＝ `lint_docs` D6 的比對路徑）

`CLAUDE.md`、`.claude/skills/`、`scripts/`、`tools/qa_common/`、`tools/jira_qa/`、
`tools/test_platform/`、`tests/tooling/`、`docs/INDEX.md`、`pyproject.toml`、`requirements.txt`

## 4. 文件地圖（知識在哪）

| 我想知道 | 去哪 |
| --- | --- |
| 這個結構怎麼開始用 | 根目錄 `README.md` |
| 規範全文 | `CLAUDE.md` |
| 各文件裝了什麼 | `docs/INDEX.md` |

## 5. 工具與規範的現況（值得知道的）

（接手後逐步補）

## 6. 維護規則

- **開工**：讀 §1 blocker 與 §2 待辦。
- **收尾**：更新 §2 狀態、§5 現況，**最後**才改檔頭日期
  （只改日期＝把 `lint_docs` D6 的警告關掉，問題原封不動留給下一個人）。
"""

SKELETON = {
    "config/products.json":
        json.dumps(PRODUCTS_SKELETON, ensure_ascii=False, indent=2) + "\n",
    "config/environments.md": ENV_MD_SKELETON,
    "config/environments.json":
        json.dumps(ENV_JSON_SKELETON, ensure_ascii=False, indent=2) + "\n",
    "docs/INDEX.md": INDEX_SKELETON,
    "docs/共通_工作區維護交接.md": HANDOVER_SKELETON,
    "reports/created_accounts/.gitkeep": "",
    # 平台的產品清單清空 —— 接自己的工具時依 tools/test_platform/docs/CONTRIB_TOOL.md 補
    "tools/test_platform/registry/products.json": u'{\n  "products": []\n}\n',
    # 平台設定的骨架（埠、模型、UI 開關）——
    "tools/test_platform/config/platform_config.json": PLATFORM_CONFIG_SKELETON,
}

# ── ★ 匯出時的後處理：讓文字對「範本的讀者」成立 ──────────────
#    原型 repo 的 README 有幾段是講給維護者聽的（例如「若是 clone 原型 repo 就跑 reset」），
#    對拿到匯出範本的人是死路。
#    ⚠️ 用轉換而不是「維護兩份 README」—— 原文只有一份，轉換規則寫在這裡一處。
TRANSFORMS = {
    "README.md": [(
        u"""## 你是怎麼拿到這份東西的？

| 拿到的形式 | 要不要清產品 |
| --- | --- |
| **匯出的範本資料夾**（別人跑 `export_template.py` 給你的） | ❌ **不用**，已經是乾淨的 → **跳過 Step 2** |
| **clone 原型 repo** | ✅ 要 → **Step 2** |
""",
        u"""## 這份是匯出的乾淨範本

裡面**沒有任何別人的產品資料** —— `docs/<產品>/`、產品 skill、產品測試框架都已清空，
`config/products.json` 是空的。所以**下面的 Step 2 你可以直接跳過**。

匯出當下的來源版本記在 `.template-export`（含 commit SHA）——
回報問題時附上它，對方就知道你這份是哪一版。
"""),
    ],
}


# ── ③ 明確不匯出 ──────────────────────────────────────────────
#    每一條都要寫得出「為什麼」，寫不出來的表示還沒想清楚。
NEVER = {
    ".git": u"版控歷史（同事要開自己的）",
    ".venv": u"138MB，綁死絕對路徑，換台機器不能用",
    ".pytest_cache": u"執行殘渣",
    ".playwright-mcp": u"MCP 瀏覽器 profile",
    "_share": u"⛔ 對外交付副本，含測試站帳密",
    "config/config.local.json": u"⛔ 個人憑證",
    ".claude/settings.local.json": u"本機權限設定",
    ".claude/scheduled_tasks.lock": u"Claude Code 排程/背景任務的執行期鎖檔（含 session id/pid，機器與 session 相關）",
    ".claude/skills/frontend-design": u"與 QA 工作流無關（Claude 內建 skill）",
    ".claude/skills/theme-factory": u"與 QA 工作流無關（Claude 內建 skill）",
    "data/wbot_bet_texts.md": u"產品專屬的測試資料",
    "data/profitRate": u"產品專屬的試算資料（不版控）",
    ".template-export": u"匯出標記（本工具寫的，不再往下傳）",
    # ⭐ 鏡像位置**每台機器不同**，所以不版控也不匯出。
    #    lint 的 D13 靠它判斷「鏡像有沒有跟上」——沒設就整項靜默跳過
    #    （同事本來就沒有鏡像，報了是雜訊）。
    ".template-mirror": u"本機的鏡像位置（D13 用；每台機器不同）",
    "tools/test_platform/registry/profiles": u"原型產品的壓測 profile",
    # ★ 內建任務（tasks/*.json）是通用層要匯出；custom/ 是同事自己的，不同步 ——
    #   不分開的話，他加一個自己的任務按鈕，`--compare` 就會報一筆他看不懂的差異。
    "tools/test_platform/tasks/custom": u"同事自訂的任務模板（個人層，不隨範本同步）",
    "tools/test_platform/logs": u"run 產物與 session 紀錄",
    # ⚠️ 2026-08-23 補：`cache/` 沒有分類過 —— 它是**執行產物**
    #    （案例索引、POM 索引、lint 結果、**JIRA 單狀態**），
    #    實務上靠 .gitignore 擋住沒進範本，但白名單裡沒有結論＝哪天有人 commit 它就會外流。
    "tools/test_platform/cache": u"平台的快取產物（案例／POM 索引、lint 與 JIRA 狀態）",
    "reports/allure-report": u"run 產物",
    "reports/allure-results": u"run 產物",
    "reports/created_accounts": u"⛔ 含數百組帳號密碼（骨架只給 .gitkeep）",
    "reports/daycut_snapshots": u"產品專屬的 run 產物",
    "reports/BOT-799_測試報告.html": u"產品專屬的報告",
}

# ── ★ 共同語言層：**分岔了就無法互相理解對方的報告** ──────────
#    這不是「不能改」，是「改了要讓所有人一起改」——
#    每個人對 L3 的定義不一樣時，「這條驗到 L3」這句話就失去意義。
#    `--compare` 會把這一層的差異單獨標出來。
SHARED_LANGUAGE = {
    ".claude/skills/testcase-design/SKILL.md":
        u"深度分級 L0~L4、風險→目標深度、Oracle 分級 A/B/C/D、覆蓋矩陣與案例清單的標準欄位",
    ".claude/skills/bug-report/SKILL.md":
        u"Bug frontmatter 的 status 值、ID 命名規則",
    ".claude/skills/bug-report/references/測試報告規則.md":
        u"驗證結論五值（已修復／仍重現／部分修復／非缺陷／無法驗證）與各自的佐證下限",
    "scripts/coverage_matrix.py":
        u"覆蓋矩陣的欄位名與深度／風險常數（矩陣要能互相讀懂）",
    "scripts/bug_paths.py":
        u"Bug 單的目錄結構與狀態分層",
    "tools/test_platform/registry/_schema.json":
        u"tool.json 的欄位契約（field type／emit／scope）—— 分岔了，同事的工具就不能互相參考",
    # ── 八支內建任務模板 ──────────────────────────────────────
    #    ⚠️ 八支都要列。任務模板決定「大家按同一顆按鈕時，session 被交代了什麼」——
    #    分岔了，兩個人的「探索」或「開單」就不是同一回事，報告也對不起來。
    "tools/test_platform/tasks/explore.json":
        u"探索任務的提示模板 —— 它決定大家的探索流程長不長得一樣，"
        u"以及**站台可以動到什麼程度**（安全邊界條款）",
    "tools/test_platform/tasks/verify_requirement.json":
        u"需求驗證的提示模板 —— 綁著逐項 PASS／FAIL／BLOCKED 的判準，"
        u"以及「實測與規格不符時先問有沒有人說要改」這條護欄",
    "tools/test_platform/tasks/write_cases.json":
        u"撰寫案例的提示模板 —— 綁著覆蓋矩陣與案例命名的共同語言",
    "tools/test_platform/tasks/verify_jira.json":
        u"JIRA 重驗的提示模板 —— 綁著驗證結論五值與佐證下限",
    "tools/test_platform/tasks/file_bug.json":
        u"開單任務的提示模板 —— 它綁著「開單前三問」與「不自己配號」兩條紀律",
    "tools/test_platform/tasks/file_bug_from_run.json":
        u"從失敗 run 開單的提示模板 —— 綁著「測試失敗 ≠ 缺陷」與跨 run 去重",
    "tools/test_platform/tasks/perf.json":
        u"壓測任務的提示模板 —— 綁著前置檢查與「真金流下注」的警語",
    "tools/test_platform/tasks/handoff_check.json":
        u"收尾體檢的提示模板 —— 綁著 lint D6／D10 與交接檔的必寫項",
}


# ── ④ 容器：本身沒有結論，**每個子項都要各自分類** ────────────
#    ⚠️ 這幾個**絕對不能放進 NEVER**。放進去的話，任何新增的子項都會被
#      「在 NEVER 底下」這條規則掃進 never —— `--audit` 就永遠不會叫，
#      而白名單唯一的失效模式（新增通用檔卻忘了加）就靜默發生。
#      （2026-08-22 第一版正是這樣寫的，audit 當場全綠、毫無作用。）
PARTIAL = [".claude", ".claude/skills", "config", "data", "docs", "reports",
           "tests", "tools"]

# 用 glob 表示的不匯出（單一檔案列不完時用）
NEVER_GLOB = [
    # ⚠️ 這裡**不能**放 `registry/*.tool.json` —— 那會連通用工具一起擋掉。
    #    工具的歸屬依 `scope`／`products` 判定，見 `_tool_is_generic()`。
]


# 隨範本發送的通用工具（不屬於任何產品，或是標準內建工具）
GENERIC_TOOLS = {
    "setup": u"工作區設定 —— 接產品、裝 memory、體檢、匯出範本。scope=workspace",
    "ui_tests": u"UI 自動化測試 —— pytest＋playwright＋allure 是範本的標準配備，"
                u"且 products 為 \"*\"（跟著 config/products.json 走）",
    # ⭐ 2026-08-24 補：`setup` 瘦身時把 12 支治理腳本拆到這一支，
    #    **漏了同步加進白名單** —— 匯出的範本因此少了 lint／體檢／打包／歸檔
    #    等治理入口，而且 `test_platform_setup_tool.py` 在範本裡會**紅三條**
    #    （它期待那些命令找得到）。`--audit` 抓不到這種漏：它只檢查「有沒有
    #    未分類的路徑」，而這一支是**被明確分類成不匯出**的。
    "workspace_ops": u"工作區治理腳本（lint／體檢／打包／歸檔／trace）—— "
                     u"product=common，全部是跨產品的維護工具",
}


def _tool_is_generic(rel):
    """`registry/<id>.tool.json` 是不是通用工具（該隨範本發送）。

    ★ 判準是**工具的性質**，不是「一律排除」——
      `setup` 是 scope=workspace（同事要用它接產品），
      `ui_tests` 是標準內建工具（`roots: ["tests"]`，requires 就是範本的標準相依）。
      產品專屬的（`crux_perf`／`crux_bet_demo`…）不夾帶給別人。
    """
    base = rel.rsplit("/", 1)[-1]
    return base[:-len(".tool.json")] in GENERIC_TOOLS if base.endswith(".tool.json") else False


def product_paths(root):
    """products.json 定義的所有產品層路徑（含 extra_paths）。"""
    path = os.path.join(root, "config", "products.json")
    try:
        data = json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for p in data.get("products") or []:
        out.add("docs/%s" % (p.get("docs_dir") or ""))
        out.add("tests/%s" % (p.get("tests_dir") or p.get("skill") or ""))
        if p.get("qa_tools_dir"):
            out.add("tools/%s" % p["qa_tools_dir"])
        out.add(".claude/skills/%s" % p.get("skill", ""))
        out.update(p.get("extra_paths") or [])
    return set(x for x in out if x and not x.endswith("/"))


def _under(rel, parent):
    return rel == parent or rel.startswith(parent + "/")


def classify(rel, products):
    """一個 repo 相對路徑屬於哪一類：export／skeleton／never／product／None。

    ⚠️ 判定順序有意義：**產品層與 NEVER 優先於 EXPORT** ——
      `scripts` 整個在 EXPORT 裡，但 `scripts/explore_crux_ui.py` 是產品層，必須先被攔下。
    """
    if rel in SKELETON:
        return "skeleton"
    for p in products:
        if _under(rel, p):
            return "product"
    for n in NEVER:
        if _under(rel, n):
            return "never"
    for g in NEVER_GLOB:
        if fnmatch.fnmatch(rel, g):
            return "never"
    if fnmatch.fnmatch(rel, "tools/test_platform/registry/*.tool.json"):
        return "export" if _tool_is_generic(rel) else "never"
    for e in EXPORT:
        if _under(rel, e):
            return "export"
    if rel in PARTIAL:
        return "container"      # 目錄本身不匯出，子項各自判定
    return None


# `--audit` 掃描的深度：只到「決策會落在哪一層」為止，不必逐檔看
AUDIT_ROOTS = ["", ".claude", ".claude/skills", "config", "data", "docs",
               "reports", "scripts", "tests", "tools",
               # ⚠️ 平台這兩處**混著產品層與通用層** ——
               #    `tools/test_platform` 整個在 EXPORT 裡，底下新增的東西
               #    一律預設匯出，稽核看不到。對通用元件而言方向是安全的，
               #    但這兩個目錄必須逐項確認（2026-08-23 階段 H-3）。
               "tools/test_platform/registry",
               "tools/test_platform/tasks"]
AUDIT_SKIP = ["*.pyc", "__pycache__", ".DS_Store"]

# 匯出時由本工具寫出的標記檔（--force 靠它判斷「這是上次的匯出，可以覆蓋」）
MARKER = ".template-export"


# `suspicious()` 的例外：檔名帶產品字樣是**刻意**的那幾份。
# ⚠️ 比照 NEVER —— 每條都要寫得出理由，寫不出來的表示它其實不該被匯出。
SUSPICIOUS_OK = {
    ".claude/skills/perf-test/references/前置檢查_七星.md":
        u"perf-test 是三產品共用的通用 skill，各產品的前置清單本來就分檔放在它的 references/",
    ".claude/skills/perf-test/references/前置檢查_wbot.md":
        u"同上。匯出時保留，讓同事看得到一份 per-product 前置清單長什麼樣；"
        u"--out 的人工待辦已註明 perf-test 可整支刪掉",
}


def suspicious(root, plan=None):
    """★ 路徑裡帶產品字樣、卻被判成「通用」的檔案。

    ⚠️ 為什麼需要這一條：`scripts` 這種**整個目錄放進 EXPORT** 的條目是 fail-open ——
      新增 `scripts/explore_<產品>_ui.py` 卻忘了登記 `extra_paths` 時，
      classify 會回 "export"、`--audit` 全綠，**產品腳本就被靜默匯出**。
      （這正是白名單本來要避免的失效方式，只是換到容器內側發生。）

      用**路徑**判定而不是內容：檔名是命名，不是行文 —— 通用 skill 的內文
      會提到原型產品（那是教訓的場景），但**檔名不該有**。
    """
    words = leak_words(root)
    if not words:
        return []
    if plan is None:
        plan = export_plan(root)
    hits = []
    for rel in plan:
        if rel in SUSPICIOUS_OK:
            continue
        low = rel.lower()
        for w in sorted(words):
            if len(w) < 3:
                continue          # 太短的前綴（如 QX）會誤判，交給人看
            if w.lower() in low:
                hits.append((rel, w))
                break
    return hits


def stale_transforms(root):
    """TRANSFORMS 的來源段落已經不在原文裡了（原文改過卻沒同步轉換規則）。

    ⚠️ 不在 `do_export` 裡擋 —— 那會炸掉「README 本來就不含該段落」的情境
      （測試的假 repo、從範本再匯出一次）。
      這是 repo 的一致性問題，該由 `--audit` 與測試抓，不是執行期條件。
      漏掉的後果：範本裡留下一段**對讀者不成立**的敘述（例如叫他去跑一個空轉的步驟）。
    """
    # ⛔ **已匯出的範本本來就沒有那些段落**（它們就是被轉換掉的那幾段）——
    #    在那種 repo 上報「來源找不到」是誤報，而同事的工作區正是那種 repo，
    #    他跑 lint 會看到一條完全看不懂的錯（2026-08-23）。
    if os.path.isfile(os.path.join(root, MARKER)):
        return []
    out = []
    for rel, rules in TRANSFORMS.items():
        p = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            out.append((rel, u"檔案不存在"))
            continue
        text = io.open(p, encoding="utf-8").read()
        for i, (old, _) in enumerate(rules):
            if old not in text:
                out.append((rel, u"第 %d 條轉換規則的來源段落找不到了" % (i + 1)))
    return out


def missing_export_entries(root):
    """R3：EXPORT 列了、但 repo 裡已經不存在的路徑。

    通用 skill 改名後若沒同步 EXPORT，該檔會**無聲地不再匯出** ——
    範本少一塊，而且沒有人會發現。
    """
    return [e for e in EXPORT
            if not os.path.exists(os.path.join(root, e.replace("/", os.sep)))]


def unclassified(root, tracked_only=True):
    """★ 維護用：列出四個清單都對不上的路徑。

    這是白名單唯一的失效模式（新增了東西卻忘了分類）的防線，
    測試會跑同一份檢查 —— 所以漏分類是紅燈，不是靜默漏掉。

    `tracked_only=True`（預設）只回**已版控**的 —— 只有那些真的會影響匯出
    （匯出條件是「git 追蹤 ∩ 白名單」）。未版控的用 `unclassified_untracked()` 另外取，
    降為警告：可能是別的 session 留在根目錄的暫存物，
    也可能是你剛新增還沒 commit 的通用檔。
    ⚠️ 後者仍要提醒 —— **一 commit 就會變成錯誤**。
    （2026-08-23：另一個 session 在根目錄留下兩張 png，D11 當場全紅。）
    """
    products = product_paths(root)
    tracked = tracked_files(root) if tracked_only else None
    out = []
    for base in AUDIT_ROOTS:
        d = os.path.join(root, base.replace("/", os.sep)) if base else root
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if any(fnmatch.fnmatch(name, pat) for pat in AUDIT_SKIP):
                continue
            rel = "%s/%s" % (base, name) if base else name
            if classify(rel, products) is not None:
                continue
            if tracked is not None and not _has_tracked(tracked, rel):
                continue          # 未版控 → 交給 unclassified_untracked()
            out.append(rel)
    return out


def _export_but_untracked(root):
    """白名單判定要匯出、但 git 還沒追蹤的檔案。

    這類檔案**不會進範本**（匯出條件是「git 追蹤 ∩ 白名單」），
    而範本裡的測試若依賴它們就會紅燈 —— 講出來，不要讓人逐條去查。
    """
    tracked = tracked_files(root)
    if tracked is None:
        return []
    products = product_paths(root)
    out = []
    for base in AUDIT_ROOTS:
        d = os.path.join(root, base.replace("/", os.sep)) if base else root
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            rel = "%s/%s" % (base, name) if base else name
            if any(fnmatch.fnmatch(name, pat) for pat in AUDIT_SKIP):
                continue
            full = os.path.join(d, name)
            if os.path.isdir(full):
                # ⚠️ 要遞迴 —— 新測試多半躺在 `tests/tooling/` 這種第二層，
                #    只看第一層的話它們一個都抓不到（2026-08-23）。
                for dirpath, _dirs, files in os.walk(full):
                    for fn in files:
                        if any(fnmatch.fnmatch(fn, pat) for pat in AUDIT_SKIP):
                            continue
                        sub = os.path.relpath(os.path.join(dirpath, fn),
                                              root).replace(os.sep, "/")
                        if classify(sub, products) == "export" and sub not in tracked:
                            out.append(sub)
                continue
            if classify(rel, products) != "export":
                continue
            if rel not in tracked:
                out.append(rel)
    return sorted(set(out))


def _has_tracked(tracked, rel):
    """rel 本身或其底下有已版控的檔案。"""
    if rel in tracked:
        return True
    pre = rel + "/"
    return any(p.startswith(pre) for p in tracked)


def unclassified_untracked(root):
    """未分類**且未版控**的路徑（警告級，見 unclassified 的說明）。"""
    all_miss = unclassified(root, tracked_only=False)
    return [r for r in all_miss if r not in unclassified(root)]


def source_commit(root):
    """來源 repo 目前的 commit（短 SHA ＋ 是否有未提交異動）。取不到回 None。

    ★ 為什麼要記：時間戳只說得出「什麼時候匯的」，說不出「內容對應到哪個狀態」。
      同事回報問題時，一句 commit SHA 就能對得起來。
    """
    try:
        sha = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"]).decode().strip()
        dirty = subprocess.check_output(
            ["git", "-C", root, "status", "--porcelain"]).decode().strip()
    except Exception:
        return None
    return sha + ("+dirty" if dirty else "")


def tracked_files(root):
    """git 追蹤中的檔案（repo 相對、正斜線）。取不到時回 None＝不過濾。

    ★ 為什麼要這一層：`.gitignore` 已經宣告過所有 run 產物與敏感檔
      （`.venv`、`docs/**/bugs/`、`config.local.json`、平台的 `cache/`／`logs/`…）。
      在白名單再列一次就是第二份副本，遲早分岔。
      直接吃 git 的判定，是最省維護的一層防線。
    """
    try:
        out = subprocess.check_output(["git", "-C", root, "ls-files", "-z"])
    except Exception:
        return None
    return set(p for p in out.decode("utf-8").split("\0") if p)


def export_plan(root):
    """要複製的 (來源相對路徑) 清單。

    條件是**兩者皆滿足**：① git 追蹤中 ② 白名單分類為 export。
    """
    products = product_paths(root)
    tracked = tracked_files(root)
    plan = []
    for e in EXPORT:
        full = os.path.join(root, e.replace("/", os.sep))
        if not os.path.exists(full):
            continue
        if os.path.isfile(full):
            if tracked is None or e in tracked:
                plan.append(e)
            continue
        for dirpath, dirnames, filenames in os.walk(full):
            rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
            # 就地剪枝，避免走進不該複製的子樹
            dirnames[:] = [d for d in sorted(dirnames)
                           if classify("%s/%s" % (rel_dir, d), products) == "export"]
            for f in sorted(filenames):
                rel = "%s/%s" % (rel_dir, f)
                if any(fnmatch.fnmatch(f, pat) for pat in AUDIT_SKIP):
                    continue
                if classify(rel, products) != "export":
                    continue
                if tracked is not None and rel not in tracked:
                    continue          # 不版控＝run 產物或敏感檔，見 tracked_files
                plan.append(rel)
    return sorted(set(plan))


def file_digest(path):
    """檔案內容的 sha1（**忽略行尾差異**，避免 CRLF/LF 造成假警報）。"""
    try:
        data = io.open(path, "rb").read().replace(b"\r\n", b"\n")
    except OSError:
        return None
    return hashlib.sha1(data).hexdigest()


def read_baseline(out):
    """讀匯出時記下的基準線；沒有或格式不對時回 None。"""
    p = os.path.join(out, MARKER)
    if not os.path.isfile(p):
        return None
    try:
        return json.load(io.open(p, encoding="utf-8")).get("files") or None
    except Exception:
        return None          # 舊版是純文字標記，沒有 files


def compare(root, out):
    """三方比較。回傳 dict：各類別 → [路徑]。

    ⚠️ **沒有基準線時分不出「誰改的」** —— 這種情況一律歸到 `unknown`，
      並由 CLI 明講，不要讓人以為那些都是範本更新。
    """
    base = read_baseline(out)
    plan = export_plan(root)
    now = {}
    for rel in plan:
        now[rel] = file_digest(os.path.join(root, rel.replace("/", os.sep)))
    for rel, content in SKELETON.items():
        now[rel] = hashlib.sha1(content.replace("\r\n", "\n").encode("utf-8")).hexdigest()

    theirs = {}
    for rel in now:
        f = os.path.join(out, rel.replace("/", os.sep))
        theirs[rel] = file_digest(f) if os.path.isfile(f) else None

    out_map = {"new": [], "template_only": [], "yours_only": [],
               "both": [], "unknown": [], "removed": [], "same": [],
               "shared_language": []}      # ★ 上面幾類的交集，另外標出來
    for rel in sorted(now):
        t_now, t_them = now[rel], theirs[rel]
        if t_them is None:
            out_map["new"].append(rel)                  # 範本新增、他還沒有
            continue
        if base is None or rel not in base:
            (out_map["same"] if t_now == t_them else out_map["unknown"]).append(rel)
            continue
        b = base[rel]
        changed_template = (t_now != b)
        changed_theirs = (t_them != b)
        if changed_template and changed_theirs:
            out_map["both"].append(rel)                 # ⚠️ 兩邊都改 → 要人合併
        elif changed_template:
            out_map["template_only"].append(rel)        # ✅ 直接更新即可
        elif changed_theirs:
            out_map["yours_only"].append(rel)           # 他的客製，別蓋掉
        else:
            out_map["same"].append(rel)
    # ★ 共同語言層只要有任何差異就單獨標出 —— 那是團隊一致性真正的載體
    for key in ("template_only", "both", "yours_only", "unknown", "new"):
        for rel in out_map[key]:
            if rel in SHARED_LANGUAGE:
                out_map["shared_language"].append((rel, key, SHARED_LANGUAGE[rel]))
    # 基準線有、但現在的範本已經不提供了
    if base:
        for rel in sorted(base):
            if rel not in now:
                out_map["removed"].append(rel)
    return out_map, (base is not None)


def looks_like_export(out):
    """目標是不是「上次由本工具匯出的資料夾」。"""
    return os.path.isfile(os.path.join(out, MARKER))


def in_use_signs(out):
    """目標「已經有人在這裡工作」的跡象 —— 回傳人看得懂的理由清單。

    ⛔ 為什麼需要這個：MARKER 檔會**永久留在同事的 repo 裡**，所以
       `looks_like_export()` 對「已經用了三個月的工作區」照樣回 True，
       而 `do_export()` 下一步就是 `shutil.rmtree`。
       `bugs/` 與 `config.local.json` 都不版控 —— 刪掉沒有 git 可以救。
       （2026-08-23 範本端到端驗收發現。）
    """
    signs = []
    if os.path.isdir(os.path.join(out, ".git")):
        signs.append(u".git/（已經開始版控，rmtree 會連 commit 歷史一起刪）")
    if os.path.isdir(os.path.join(out, ".venv")):
        signs.append(u".venv/（已經建過環境）")
    try:
        import json as _json
        pj = os.path.join(out, "config", "products.json")
        if os.path.isfile(pj):
            if (_json.load(io.open(pj, encoding="utf-8")).get("products") or []):
                signs.append(u"config/products.json 已經接了產品")
    except Exception:
        pass
    for d in ("docs", "reports"):
        p = os.path.join(out, d)
        if os.path.isdir(p):
            for dirpath, dirnames, files in os.walk(p):
                if os.path.basename(dirpath) == "bugs" and files:
                    signs.append(u"%s（Bug 單不版控，刪掉救不回來）"
                                 % os.path.relpath(dirpath, out).replace("\\", "/"))
                    break
    return signs


def mirror_dirty(out):
    """版控中的鏡像有沒有未提交的東西。回 (髒不髒, 給人看的說明)。

    ⭐ `--sync` 的安全網就是這個：**working tree 乾淨 ＝ 覆蓋掉的每個位元都救得回來**
      （`git checkout .` 即可），所以才敢對一個有 `.git/` 的目錄動手。
    """
    try:
        # ⚠️ core.quotepath=false 不可省 —— 預設會把中文檔名轉成八進位跳脫（\350\210…），
        #    而這段字串是要給人看「哪個檔還沒提交」的（測試釘住）。
        txt = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "-C", out,
             "status", "--porcelain"]).decode("utf-8", "replace").strip()
    except Exception as e:
        return True, u"跑不動 git status（%s）—— 這個目錄不是可用的 git repo" % type(e).__name__
    # MARKER 每次同步都會被重寫（裡面是時間戳與來源 commit），本來就留不住 ——
    # 讓它擋住下一次同步，等於「看完差異決定先不提交」的人下週就卡住了。
    # ⚠️ 不可以用 L[3:] 取路徑 —— 上面的 .strip() 已經吃掉行首空白，欄位會錯開一格。
    lines = [L for L in txt.splitlines()
             if L.split()[-1].strip('"') != MARKER]
    return bool(lines), chr(10).join(lines)


def can_write(out, sync=False):
    """回傳 (可不可以寫, 理由)。空目錄或不存在 → 可；本工具的舊匯出 → 可（會先清空）。

    `sync=True` 時多一條路：目標是**版控中的鏡像**（有 MARKER ＋ `.git/` ＋ working tree 乾淨）
    也可以寫，且清空時**保留 `.git/` 與 `.venv/`**（見 `do_export` 的 `keep`）。
    """
    if not os.path.exists(out):
        return True, "new"
    if not os.path.isdir(out):
        return False, u"目標不是目錄"
    if not os.listdir(out):
        return True, "empty"
    if sync and looks_like_export(out) and os.path.isdir(os.path.join(out, ".git")):
        dirty, txt = mirror_dirty(out)
        if dirty:
            # ⛔ 髒的 working tree 一覆蓋就沒了，而那些改動不在任何 commit 裡。
            return False, (u"鏡像有未提交的變更，先處理掉再同步：\n%s\n"
                           u"   （這些改動一覆蓋就救不回來；`--sync` 的前提是「乾淨＝救得回來」）"
                           % "\n".join(u"     " + L for L in txt.splitlines()[:15]))
        # 這裡刻意**不**跑 in_use_signs()：鏡像本來就會有 config/products.json 之類的內容，
        # 而它們全都在 git 裡 —— 不版控的東西（bugs/、config.local.json）才是那條防線要保護的。
        for d in ("docs", "reports"):
            p = os.path.join(out, d)
            if not os.path.isdir(p):
                continue
            for dirpath, _dirnames, files in os.walk(p):
                if os.path.basename(dirpath) == "bugs" and files:
                    return False, (u"鏡像裡有 %s —— Bug 單不版控，覆蓋掉救不回來。\n"
                                   u"   鏡像是用來對外發送的，不該拿來做事；請自行搬走再同步。"
                                   % os.path.relpath(dirpath, out).replace("\\", "/"))
        return True, "sync"
    if looks_like_export(out):
        signs = in_use_signs(out)
        if signs:
            # ⛔ 同樣刻意沒有 --force：這一步會 rmtree，而下面列的東西多半沒有版控。
            return False, (u"目標雖然是本工具的舊匯出，但**已經有人在這裡工作**：\n"
                           u"%s\n"
                           u"   匯出會先 rmtree 整個目錄。確定要重來的話，"
                           u"請自己確認並刪除該目錄再跑。"
                           % "\n".join(u"     · " + s for s in signs))
        return True, "reexport"
    # ⛔ 不認得的非空目錄一律不碰 —— 這支腳本會 rmtree，認錯目標的代價太大
    return False, (u"目標非空、且不是本工具產出的匯出（找不到 %s）。\n"
                   u"   確定要用這個目錄的話請自行清空再跑 —— "
                   u"本工具不會刪除來路不明的資料夾。" % MARKER)


KEEP_ON_SYNC = (".git", ".venv")     # 版控歷史與虛擬環境不是「內容」，同步時不動它們


def do_export(root, out, dry_run=False, stamp=None, keep=()):
    """複製白名單 ＋ 寫骨架。回傳 (複製檔數, 骨架檔數)。

    ⚠️ 重覆匯出時**先清空**：不清的話，上一次匯出的殘留（甚至手動丟進去的
      `config.local.json`、`bugs/`）會留在資料夾裡跟著交出去。
      ③a 抓得到，但工具本身不該產生這種狀態。
    """
    if not dry_run and looks_like_export(out):
        if keep:
            # 逐項刪，跳過 keep —— 整份 rmtree 會連 .git/ 一起帶走（`--sync` 的重點就在這）
            for name in os.listdir(out):
                if name in keep:
                    continue
                p = os.path.join(out, name)
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
        else:
            shutil.rmtree(out, ignore_errors=True)
    plan = export_plan(root)
    for rel in plan:
        if dry_run:
            continue
        dst = os.path.join(out, rel.replace("/", os.sep))
        d = os.path.dirname(dst)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        src = os.path.join(root, rel.replace("/", os.sep))
        if rel in TRANSFORMS:
            text = io.open(src, encoding="utf-8").read()
            for old, new in TRANSFORMS[rel]:
                text = text.replace(old, new, 1)   # 找不到就原樣帶過，不中斷匯出
            io.open(dst, "w", encoding="utf-8", newline="\n").write(text)
        else:
            shutil.copyfile(src, dst)
    for rel, content in sorted(SKELETON.items()):
        if dry_run:
            continue
        dst = os.path.join(out, rel.replace("/", os.sep))
        d = os.path.dirname(dst)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        io.open(dst, "w", encoding="utf-8", newline="\n").write(content)
    if not dry_run:
        if not os.path.isdir(out):
            os.makedirs(out)
        # 標記檔同時是**基準線**：記下每個檔的 sha1，供日後 `--compare` 做三方比較
        # （分辨「同事改的」與「範本更新的」，見 compare()）
        manifest = {}          # note: TRANSFORM 過的檔案記的是**轉換後**的 sha1
        for rel in plan + sorted(SKELETON):
            f = os.path.join(out, rel.replace("/", os.sep))
            if os.path.isfile(f):
                manifest[rel] = file_digest(f)
        io.open(os.path.join(out, MARKER), "w", encoding="utf-8",
                newline="\n").write(json.dumps({
                    "_comment": [
                        u"由 scripts/export_template.py 匯出。",
                        u"這個檔案有兩個用途：",
                        u"  ① 「可安全覆蓋」的標記 —— 重覆匯出時本工具會先清空本目錄",
                        u"  ② **基準線** —— files 記著匯出當下每個檔的 sha1，",
                        u"     供 `--compare` 分辨「你改過的」與「範本更新的」。",
                        u"⛔ 不要手動編輯或刪除，刪了就沒辦法做三方比較。",
                    ],
                    "source": root,
                    "source_commit": source_commit(root) or "-",
                    "exported_at": stamp or "-",
                    "files": manifest,
                }, ensure_ascii=False, indent=2) + "\n")
    return len(plan), len(SKELETON)


# ── 三條自我驗收 ──────────────────────────────────────────────
# ③a 的禁列：這些字樣只要出現在**路徑**裡就是漏了，不必再看內容。
HARD_DENY = ["config.local.json", "settings.local.json",
             "/bugs/", "created_accounts/", "_share/", ".venv/",
             "allure-results/", "allure-report/"]


def leak_words(root):
    """殘留掃描要找的產品字樣：產品 id、docs 目錄、skill 名、bug 前綴。"""
    words = set()
    try:
        data = json.load(io.open(os.path.join(root, "config", "products.json"),
                                 encoding="utf-8"))
    except Exception:
        return words
    for p in data.get("products") or []:
        for k in ("id", "docs_dir", "skill", "bug_prefix"):
            if p.get(k):
                words.add(p[k])
        words.update(p.get("aliases") or [])
    return words


def _verify_python():
    """跑驗收用的直譯器：**優先工作區的 `.venv`**，沒有才退回目前這支。

    ⚠️ 不能直接用 `sys.executable`。同事很自然會用系統 Python 執行
    `python scripts\\export_template.py --out ...`，而**系統 Python 多半沒有
    `allure-pytest`** —— `pyproject.toml` 的 `addopts` 帶著 `--alluredir`，
    pytest 會以「unrecognized arguments」的**用法錯誤**退出（exit 4），
    於是驗收報「pytest 失敗」、印出「範本先不要交出去」，
    但**測試其實一條都沒跑、也一條都沒壞**。
    （2026-08-23 實際發生：範本裡手動跑是 405 passed，驗收卻說 ❌。）
    """
    venv = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv):
        return venv
    venv = os.path.join(ROOT, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


# pytest 的用法錯誤（`pytest.ExitCode.USAGE_ERROR`）—— 不是「測試失敗」
_PYTEST_USAGE_ERROR = 4


def _clean_run_artifacts(out):
    """把驗收自己跑 pytest 產生的東西清掉。

    ⛔ **驗收在匯出的資料夾裡跑 pytest**，而測試會摸到平台的 `logs/`／`cache/`
       （案例索引、POM 索引、設定檔備份…）。那些路徑本來就在 `NEVER` 裡 ——
       也就是說**不該出現在交付物裡**，卻由驗收自己製造出來，
       然後被第三條「殘留」檢查抓到（2026-08-24 匯出全新範本時實際發生）。

    這裡只刪 `NEVER` 名單裡、且確實是 run 產物的兩個目錄；
    刪錯了也沒有損失 —— 它們本來就不該被交出去。
    """
    for rel in ("tools/test_platform/logs", "tools/test_platform/cache"):
        shutil.rmtree(os.path.join(out, rel.replace("/", os.sep)), ignore_errors=True)


def verify(out, words):
    """三條驗收：① tests/tooling 全綠 ② lint_docs 無必修錯誤 ③ 無產品／敏感殘留。

    回傳 [(名稱, 通過?, 訊息)]。
    """
    results = []
    py = _verify_python()

    # ① 測試 —— 腳本不該依賴任何產品，所以匯出後照樣要全綠
    # ⚠️ `--alluredir` 指到拋棄目錄覆蓋 pyproject 的 addopts，否則 pytest 會在
    #    匯出的資料夾裡生出 `reports/allure-results/` —— 驗收自己製造殘留，
    #    然後被下面第三條抓到（2026-08-22 實際發生）。
    try:
        throwaway = tempfile.mkdtemp(prefix="tpl-allure-")
        p = subprocess.run([py, "-m", "pytest", "tests/tooling", "-q",
                            "-p", "no:cacheprovider", "--alluredir", throwaway],
                           cwd=out, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        shutil.rmtree(throwaway, ignore_errors=True)
        _clean_run_artifacts(out)
        text = p.stdout.decode("utf-8", "replace").strip()
        tail = text.splitlines()[-1:]
        if p.returncode == _PYTEST_USAGE_ERROR:
            # 用法錯誤 ＝ 環境缺套件，不是測試壞掉。講清楚差別，否則會被誤讀成範本有問題。
            msg = ("pytest **用法錯誤**（不是測試失敗）——多半是這支直譯器缺 "
                   "allure-pytest：%s　→ 用工作區 .venv 或先 pip install -r requirements.txt"
                   % (tail[0] if tail else ""))
            results.append(("pytest tests/tooling", False, msg))
        else:
            note = "%s　（直譯器 %s）" % (tail[0] if tail else "", os.path.basename(py))
            if p.returncode != 0:
                # ⚠️ 先講最常見的成因 —— 匯出條件是「git 追蹤 ∩ 白名單」，
                #    剛新增還沒 commit 的通用檔不會進範本，於是測到一半的東西紅燈。
                # ⛔ 這裡先前寫成 `_export_but_untracked(root)` —— **本 scope 沒有 `root`**，
                #    於是每次 pytest 一失敗就丟 NameError，被外層 except 接住，
                #    驗收只印「name 'root' is not defined」，**真正的 pytest 輸出整段被吃掉**。
                #    本該解釋失敗原因的那段程式碼，反而把失敗原因藏起來了
                #    （2026-08-24 匯出全新範本時撞到）。
                missing = _export_but_untracked(ROOT)
                if missing:
                    note += ("\n     ⚠️ 有 %d 個**該匯出但還沒版控**的檔 —— "
                             "它們不會進範本，多半就是紅燈的原因：\n       %s"
                             % (len(missing), "\n       ".join(missing[:8])
                                + ("\n       …另有 %d 個" % (len(missing) - 8)
                                   if len(missing) > 8 else "")))
            results.append(("pytest tests/tooling", p.returncode == 0, note))
    except Exception as e:
        results.append(("pytest tests/tooling", False, str(e)))

    # ①b ⭐ 該匯出但還沒版控 —— **不論 pytest 過不過都要報**。
    #    先前只在 pytest 紅燈時附帶提一句，於是最危險的那種情況剛好逃掉：
    #    新模組與它的新測試**一起**沒版控 → 兩者都沒進範本 → 範本的 pytest 是**綠的**，
    #    而那個功能在範本裡根本不存在（2026-08-25 加 Claude 用量統計時實際踩到：
    #    core/claude_usage.py 與它的測試都沒進去，驗收 616 passed 全綠）。
    try:
        missing_vc = _export_but_untracked(ROOT)
        if missing_vc:
            head = missing_vc[:8]
            more = ("\n       …另有 %d 個" % (len(missing_vc) - 8)) if len(missing_vc) > 8 else ""
            results.append(("未版控（不會進範本）", False,
                            "%d 個檔白名單判定要匯出、但 git 還沒追蹤：\n       %s\n     → 要進範本就先 commit"
                            % (len(missing_vc), "\n       ".join(head) + more)))
    except Exception as e:
        results.append(("未版控（不會進範本）", False, str(e)))

    # ② lint —— 沒有產品可檢查時也不該報錯
    try:
        p = subprocess.run([py, os.path.join("scripts", "lint_docs.py")],
                           cwd=out, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = p.stdout.decode("utf-8", "replace")
        bad = [l for l in text.splitlines() if l.startswith("❌")]
        results.append(("lint_docs", not bad,
                        bad[0] if bad else "無必修錯誤"))
    except Exception as e:
        results.append(("lint_docs", False, str(e)))

    # ③a 結構殘留（硬性）：匯出的每個檔案都必須落在白名單分類裡。
    #     產品目錄、bugs/、created_accounts/、*.local.json 只要出現就是白名單漏了。
    products = product_paths(ROOT)
    leaked = []
    for dirpath, dirnames, filenames in os.walk(out):
        # .git／.venv 是**環境與版控，不是內容** —— `--sync` 的鏡像必然帶著 .git/，
        # 不排除的話這條檢查會把它整包當成「白名單漏掉的檔案」（2026-08-25 加 --sync 時撞到）。
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",) + KEEP_ON_SYNC]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), out).replace(os.sep, "/")
            if rel in SKELETON or rel == MARKER:
                continue              # 骨架與標記檔是我們自己寫的，豁免
            if any(bad in rel for bad in HARD_DENY):
                leaked.append("%s（命中禁列 pattern）" % rel)
            elif classify(rel, products) not in ("export", "skeleton"):
                leaked.append("%s（不在白名單分類裡）" % rel)
    # 路徑帶產品字樣卻被判成通用 —— 見 suspicious() 的說明
    for rel, w in suspicious(ROOT):
        leaked.append("%s（檔名含產品字樣「%s」，應登記 extra_paths）" % (rel, w))
    results.append(("結構殘留", not leaked,
                    "；".join(sorted(set(leaked))[:5]) if leaked else "乾淨"))

    # ③b 原型舉例（軟性）：通用 skill 的教訓裡還提到原型產品的地方。
    #     **不擋交付** —— 那些是「有具體場景的教訓」，抹掉會連價值一起抹掉。
    #     報數是為了讓維護者知道還有多少可以再匿名化。
    examples = {}
    for dirpath, dirnames, filenames in os.walk(out):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",) + KEEP_ON_SYNC]
        for f in filenames:
            if not f.endswith((".md", ".py", ".json", ".txt", ".toml", ".ps1", ".js")):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, out).replace(os.sep, "/")
            try:
                text = io.open(full, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            n = sum(text.count(w) for w in words)
            if n:
                examples[rel] = n
    total = sum(examples.values())
    results.append(("原型舉例（不擋）", True,
                    "%d 處／%d 檔" % (total, len(examples)) if total else "無"))
    results.append(("_examples", True, examples))   # 詳表，供 CLI 印出
    return results


def tidy(out):
    """清掉驗收自己留下的東西（pytest 匯入 scripts 會生 __pycache__）。"""
    for dirpath, dirnames, _ in os.walk(out, topdown=False):
        for d in list(dirnames):
            if d in ("__pycache__", ".pytest_cache"):
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)


def print_results(results, show_examples=True):
    """印驗收結果；`_examples` 是詳表（dict），另外處理。"""
    examples = {}
    for name, ok, msg in results:
        if name == "_examples":
            examples = msg
            continue
        print("  %s %-22s %s" % ("✅" if ok else "❌", name, msg))
    if show_examples and examples:
        top = sorted(examples.items(), key=lambda kv: -kv[1])[:8]
        print("\n  原型舉例分佈（**不擋交付**，是可再匿名化的清單）：")
        for rel, n in top:
            print("     %3d 處  %s" % (n, rel))
        if len(examples) > len(top):
            print("     …另有 %d 個檔案" % (len(examples) - len(top)))
        print("     ↑ 這些是通用 skill 裡「帶著具體場景的教訓」。"
              "抹掉產品名會連場景一起抹掉，\n"
              "       所以只報數不阻擋 —— 要不要進一步匿名化由維護者決定。")


def main():
    ap = argparse.ArgumentParser(description="把工作區匯出成乾淨的標準專案範本")
    ap.add_argument("--out", help="匯出目標目錄（空目錄／不存在／上次的匯出）")
    ap.add_argument("--verify", help="只對既有的匯出跑三條驗收")
    ap.add_argument("--compare", metavar="DIR",
                    help="★ 比對某份既有的匯出與現在的範本差在哪（分辨誰改的）")
    ap.add_argument("--audit", action="store_true",
                    help="★ 維護用：未分類、疑似產品專屬、EXPORT 指到不存在的路徑")
    ap.add_argument("--sync", action="store_true",
                    help="★ 目標是版控中的乾淨範本鏡像：保留 .git/ 與 .venv/，其餘全部覆蓋")
    ap.add_argument("--dry-run", action="store_true", help="只列出會複製什麼")
    a = ap.parse_args()

    if a.audit:
        miss = unclassified(ROOT)
        loose = unclassified_untracked(ROOT)
        untracked_export = _export_but_untracked(ROOT)
        susp = suspicious(ROOT)
        gone = missing_export_entries(ROOT)
        stale = stale_transforms(ROOT)
        if untracked_export:
            print("⚠️ **該匯出但還沒版控**（%d 個）—— 這些檔**不會進範本**：" % len(untracked_export))
            for m in untracked_export[:15]:
                print("   " + m)
            if len(untracked_export) > 15:
                print("   …另有 %d 個" % (len(untracked_export) - 15))
            print("   → 要進範本就先 commit；只是暫存物就移到 scratchpad\n")
        if loose:
            print("⚠️ 未分類**且未版控**（不影響匯出，但 commit 之後就會變成錯誤）：")
            for m in loose:
                print("   " + m)
            print("   → 是暫存物就移到 scratchpad（CLAUDE.md §8.3「暫存物不落 repo」）；"
                  "\n     是要進範本的通用檔就先分類\n")
        if not miss and not susp and not gone and not stale:
            print("✅ 白名單完整：沒有未分類的路徑、沒有疑似產品專屬的檔案、"
                  "EXPORT 列的路徑都存在、TRANSFORMS 的來源段落都還在。")
            return 0
        if miss:
            print("❌ 未分類（四個清單都對不上）：")
            for m in miss:
                print("   " + m)
            print("   → 通用 → EXPORT；產品專屬 → products.json 的 extra_paths；"
                  "run 產物或敏感檔 → NEVER（要寫理由）")
        if susp:
            print("\n❌ 檔名帶產品字樣、卻會被當成通用匯出：")
            for rel, w in susp:
                print("   %s（含「%s」）" % (rel, w))
            print("   → 若確實是產品專屬，登記到 products.json 該產品的 extra_paths")
        if gone:
            print("\n⚠️ EXPORT 列了但 repo 裡不存在（改名後忘了同步？）：")
            for g in gone:
                print("   " + g)
        if stale:
            print("\n❌ TRANSFORMS 的來源段落已失效（原文改過，轉換規則沒跟上）：")
            for rel, why in stale:
                print("   %s —— %s" % (rel, why))
            print("   → 範本裡會留下對讀者不成立的敘述，去 export_template.py 的 "
                  "TRANSFORMS 更新那條規則")
        return 1

    if a.compare:
        target = os.path.abspath(a.compare)
        if not os.path.isdir(target):
            raise SystemExit("找不到目錄：%s" % target)
        m, has_base = compare(ROOT, target)
        try:
            meta = json.load(io.open(os.path.join(target, MARKER), encoding="utf-8"))
            theirs_ver = "%s（匯出於 %s）" % (meta.get("source_commit", "?"),
                                             meta.get("exported_at", "?"))
        except Exception:
            theirs_ver = "未知（沒有標記檔）"
        print("比對 %s\n   那份是：%s\n   現在的範本：%s（%s）\n"
              % (target, theirs_ver, source_commit(ROOT) or "?", ROOT))
        if not has_base:
            print("⚠️ 該目錄沒有基準線（`%s` 不存在或是舊格式）——" % MARKER)
            print("   **分不出「你改的」與「範本更新的」**，只能列出「內容不同」。")
            print("   下次用新版匯出就會有基準線。\n")

        def show(key, title, hint):
            rels = m[key]
            if not rels:
                return
            print("%s（%d）" % (title, len(rels)))
            for r in rels[:20]:
                print("   " + r)
            if len(rels) > 20:
                print("   …另有 %d 個" % (len(rels) - 20))
            print("   → %s\n" % hint)

        if m["shared_language"]:
            print("🔴 **共同語言層**有差異（%d）—— 這一層分岔了，"
                  "你和同事就看不懂彼此的報告" % len(m["shared_language"]))
            for rel, kind, why in m["shared_language"]:
                label = {"template_only": "只有範本改了", "both": "兩邊都改了",
                         "yours_only": "只有你改了", "unknown": "判不出誰改的",
                         "new": "範本新增"}[kind]
                print("   %-52s [%s]" % (rel, label))
                print("        承載：%s" % why)
            print("   → **這一層要和大家一起改，不要各走各的**。"
                  "\n     若是你有更好的做法，回饋給範本讓所有人一起換，"
                  "而不是只改自己這份。\n")

        show("new", "🆕 範本新增、你還沒有", "直接複製過去")
        show("template_only", "⬆️ 只有範本改了（你沒動過）", "**可以直接覆蓋**，不會弄丟你的東西")
        show("both", "⚠️ 兩邊都改了", "**要人合併** —— 先看你改了什麼，再決定怎麼併")
        show("yours_only", "🔧 只有你改了（範本沒動）", "這是你的客製，**別覆蓋**")
        show("unknown", "❓ 內容不同但判不出誰改的", "沒有基準線；逐檔看 diff")
        show("removed", "🗑️ 範本已不再提供", "確認是刻意移除後再決定要不要刪")

        total = sum(len(m[k]) for k in
                    ("new", "template_only", "both", "unknown", "removed"))
        if not total:
            print("✅ 沒有需要處理的差異（相同 %d 檔、你的客製 %d 檔）"
                  % (len(m["same"]), len(m["yours_only"])))
        else:
            print("相同 %d 檔、你的客製 %d 檔（都不必動）"
                  % (len(m["same"]), len(m["yours_only"])))
        return 0

    if a.verify:
        results = verify(a.verify, leak_words(ROOT))
        print_results(results)
        return 0 if all(ok for _, ok, _ in results) else 1

    if not a.out:
        ap.error("要 --out、--verify、--audit 或 --compare 其中之一")

    miss = unclassified(ROOT)
    if miss:
        print("⛔ 有 %d 個路徑未分類，先跑 `--audit` 處理完再匯出：" % len(miss))
        for m in miss:
            print("   " + m)
        return 1

    out = os.path.abspath(a.out)
    # R4：不得指向 repo 內部（--force 會 rmtree，指到 repo 自己就毀了）
    if out == ROOT or out.startswith(ROOT + os.sep):
        raise SystemExit("⛔ --out 不可指向工作區內部：%s\n"
                         "   （匯出前會清空目標目錄）" % out)

    ok, why = can_write(out, sync=a.sync)
    if not ok:
        # ⛔ 刻意沒有 --force：這支腳本會 rmtree 目標，認錯目錄的代價太大。
        #    要覆蓋來路不明的資料夾，請自己先確認並清空。
        raise SystemExit("⛔ %s" % why)
    if why == "reexport":
        print("（目標是上次的匯出，將先清空再寫入）")
    if why == "sync":
        print("（同步模式：保留 %s，其餘全部覆蓋；覆蓋前的 working tree 是乾淨的）"
              % "／".join(KEEP_ON_SYNC))

    gone = missing_export_entries(ROOT)
    if gone:
        print("⚠️ EXPORT 列了但 repo 裡不存在（改名後忘了同步？這些會無聲地不再匯出）：")
        for g in gone:
            print("   " + g)

    plan = export_plan(ROOT)
    print("匯出 %s → %s" % (ROOT, out))
    print("  白名單 %d 個檔案、骨架 %d 個檔案" % (len(plan), len(SKELETON)))
    if a.dry_run:
        for rel in plan:
            print("  [dry] " + rel)
        for rel in sorted(SKELETON):
            print("  [dry] %s（骨架）" % rel)
        print("\n（--dry-run，什麼都沒寫）")
        return 0

    do_export(ROOT, out, stamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
              keep=KEEP_ON_SYNC if why == "sync" else ())
    print("\n三條自我驗收（在匯出的資料夾裡跑）：")
    results = verify(out, leak_words(ROOT))
    tidy(out)
    print_results(results)

    if why == "sync":
        try:
            diff = subprocess.check_output(
                ["git", "-c", "core.quotepath=false", "-C", out,
                 "status", "--short"]).decode("utf-8", "replace").rstrip()
        except Exception:
            diff = None
        if diff is None:
            print("\n（同步完成，但讀不到 git status —— 請自行到鏡像目錄檢查差異）")
        elif diff:
            n = len(diff.splitlines())
            print("\n本次同步造成 %d 個檔案差異：" % n)
            print("\n".join(diff.splitlines()[:40]))
            if n > 40:
                print("   …另有 %d 個" % (n - 40))
            print("\n下一步：到 %s 檢查差異 → git add → git commit → git push" % out)
        else:
            print("\n✅ 鏡像已經是最新的（沒有任何差異）。")

    if all(ok for _, ok, _ in results):
        print("""
✅ 範本已就緒。交給同事之後，他要做的是：
   1. git init（或放進你們的 repo）
   2. scripts\\setup_test_env.ps1
   3. python scripts\\bootstrap_workspace.py     裝通用 memory
   4. python scripts\\new_product.py --id ...    接自己的產品
   詳見範本裡的 README.md。

⚠️ 仍需人工調整（判斷成分太高，腳本不碰）：
   · CLAUDE.md §1「專案定位」—— 仍是原型的領域敘述
   · .claude/skills/testcase-design §5 領域兩問 ＋ references/ 範例檔
   · .claude/skills/perf-test —— 原型產品專屬，沒有壓測需求可整支刪掉""")
        return 0
    print("\n❌ 驗收未過，範本先不要交出去。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
