# 測試工程師 AI 助手工作區（範本）

給**自動化測試工程師**與 Claude 一起工作的專案結構：規範、流程 skill、治理腳本、
測試框架與一套測試助手。接上自己的產品之後就能開始跑。

> 📖 這份是**給人看的入口**。`CLAUDE.md` 是**給 Claude 讀的規則書** —— 你不必先讀完它。
> 需要細節時，各章節都會指給你。
>
> ⭐ **要向別人介紹這套東西**（或自己想先看懂全貌）→
> **`tools/test_platform/web_ui/static/intro.html`（AI 自動化測試框架 · 總覽）** ——
> 四層架構、一件事從頭跑到尾的七站、人與 AI 的分界、不能破的四條。
> 一頁看完，不必先裝環境；起了平台之後在右上角的 **◇ 總覽** 也點得到。

---

## 這個結構在解決什麼

多個 QA 各自用 Claude、各自一個 repo，於是**產品知識、測試方法、涵蓋率口徑、流程**全都對不齊。
這裡把「對得齊的那一半」抽出來變成可複製的結構：

- **方法論寫成 skill** —— 該驗什麼、設幾條、驗多深、期望值哪裡來，不再靠各人手感
- **紀律寫成會執行的指令** —— 靠自律的規範必然漂移，所以做成 `lint_docs`／`gen_bug_index`／`new_bug_doc`
- **知識分三層落位** —— memory（要主動浮現的）／skill（導覽）／`docs/`（權威內容）

---

## 你拿到的東西分三層

| 層 | 是哪些 | 怎麼處理 |
| --- | --- | --- |
| **① 通用 QA 工作流** | `CLAUDE.md` 規範骨架、9 支流程 skill、`scripts/` 治理腳本、`tests/tooling/`、`tools/qa_common`｜`jira_qa`｜`test_platform`、`.mcp.json`、`pyproject.toml`、`requirements.txt` | **原樣保留**，這是整包的價值 |
| **② 領域特定** | `testcase-design` 的金流兩問與範例檔、`CLAUDE.md §1` 的領域敘述 | 方法留著，**例子換成自己的** |
| **③ 實例特定** | `docs/<產品>/`、產品 skill、`tools/<產品>_*`、`tests/<產品>/`、`config/environments.*` | **清空重建** |

範本原型接的是彩票系統（CRUX／七星／投注機器人）—— 那是③，你會把它清掉。

---

## ⭐ 哪些可以各走各的，哪些不行

上面那張表講的是「**哪些要換掉**」。這張表講的是「**哪些換掉之後，大家就對不上話了**」。

> **這個範本不是要你照著它工作。** 你一定會依自己的產品與習慣長出自己的流程 ——
> 那是預期中的，也是好的。範本只保證**起步一致**。
>
> 但有一小塊**必須保持共用**，否則團隊價值就沒了。

| 層 | 是什麼 | 分岔的後果 |
| --- | --- | --- |
| 🔴 **共同語言**<br>（約二十個名詞） | **深度分級 L0～L4**、**風險→目標深度**、**Oracle 分級 A/B/C/D**、**覆蓋矩陣與案例清單的標準欄位**、**Bug `status` 值**、**驗證結論五值** | ⛔ **看不懂彼此的報告** —— 你說「這條驗到 L3」，對方理解成別的意思；<br>他的覆蓋率 68% 和你的 68% 不是同一件事 |
| 🟠 **共同工具**<br>（建議同步） | 治理腳本、`lint_docs` 的 D／W 代號 | ⚠️ 「綠燈」的意思不一樣，交叉檢查失效 |
| 🟢 **個人工作流**<br>（歡迎分岔） | 開工先讀哪一節、報告章節順序、要不要用測試助手、自己加的 skill 與腳本 | ✅ **本來就該不一樣** |

**要改共同語言層？** 可以，但**跟大家一起改** —— 走下面的「回饋路徑」，
讓所有人一起換，而不是只改自己這份。

```powershell
python scripts\export_template.py --compare <你的目錄>
```

這支會把共同語言層的差異**單獨標紅**，其餘的只是列出來給你參考。

---

## 這份是匯出的乾淨範本

裡面**沒有任何別人的產品資料** —— `docs/<產品>/`、產品 skill、產品測試框架都已清空，
`config/products.json` 是空的。所以**下面的 Step 2 你可以直接跳過**。

匯出當下的來源版本記在 `.template-export`（含 commit SHA）——
回報問題時附上它，對方就知道你這份是哪一版。

> ⛔ **不要用「複製整個資料夾」的方式散佈** —— 資料夾複製會帶走所有 gitignored 的檔案，
> 而祕密全在那裡（`config.local.json`、`docs/*/bugs/` 的測試站帳密、
> `reports/created_accounts/` 的數百組帳號、`_share/` 的交付副本、138MB 的 `.venv`）。
> **要給人請用 `python scripts\export_template.py --out <目錄>`**（白名單匯出，附三條自我驗收）。

---

## 上手五步

### 0. 環境

**先裝這兩個**（都是必裝，不是選配）：

| 要裝什麼 | 為什麼 |
| --- | --- |
| **Python 3.11+** | 測試框架、所有治理腳本、測試助手 |
| **Node.js 18+** | ⛔ **Playwright MCP 靠 `npx @playwright/mcp` 起** —— 沒有它就沒有瀏覽器，而探索／需求驗證／JIRA 重驗／開單複現全都要瀏覽器。allure CLI 也走 npm。<br>⚠️ 缺它的症狀**很難查**：MCP server 起不來，session 只會安靜地少掉那幾個工具，然後交出一份只驗得到讀取面的報告 |

```powershell
git clone <repo> ; cd <repo>        # 若拿到的是匯出的範本，改成 git init
node -v ; python --version                                  # 先確認兩個都在
scripts\setup_test_env.ps1                                  # 冪等；建 .venv、裝 pytest/playwright/allure
copy config\config.example.json config\config.local.json     # 填自己的帳密／token（不版控）
```

`.mcp.json` 已接好 Playwright MCP（釘 0.0.77、`--isolated` 各 session 隔離）。
⚠️ **改 `.mcp.json` 要重啟 session 才生效。**

### 1. 裝通用 memory

```powershell
python scripts\bootstrap_workspace.py
```

memory 存在 repo **外面**（`~/.claude/projects/<路徑key>/memory/`），clone 不會帶過來。
這一步把 `.claude/memory-seed/` 的**通用 QA 教訓**裝進本機並補進索引。

> **重跑時的行為（重要）**：**已存在的一律跳過，不覆蓋。**
> 所以範本**新增**的 seed 重跑會裝到，但**修改過**的 seed **不會更新**
> —— 這是刻意的（你可能已經按自己的情況改過那則）。
> 真的要拿範本的版本蓋掉自己的，才加 `--force`。

### 2. 清掉範本原型的產品（只有 clone 原型 repo 才需要）

```powershell
python scripts\reset_workspace.py            # 預設 dry-run，先看會刪什麼
python scripts\reset_workspace.py --apply
```

⛔ **不可逆**：`docs/<產品>/bugs/` 整層不版控，刪掉沒有 git 可以救。
working tree 不乾淨時腳本會擋下來（多 session 共用同一份 working tree）。
執行完會列出**還需要人處理**的幾件事（`CLAUDE.md §1`、`config/environments.*`、範例檔…）。

### 3. 接自己的產品

```powershell
python scripts\new_product.py --id 樂透 --docs-dir Lotto --bug-prefix LOTTO --alias lotto
```

一次建好目錄、產品 skill 骨架、交接檔（檔名結尾符合 lint 檢查），並註冊到
**`config/products.json`（產品定義的單一來源）**，最後印出還要人做的事。

> ⛔ **不要手動建** —— 漏任何一步（例如交接檔沒用對檔名結尾）就不會被 lint 檢查到。
> 驗收：`python scripts\lint_docs.py --product 樂透` 應為綠。

### 4. 第一次探索

跟 Claude 說「載入 `/testcase-design`，我要探索 <某個功能區塊>」，然後照它走：

```
§10.1 先寫 Charter 再開瀏覽器（時間盒 60~90 分）
§1    五來源交叉盤點：選單樹／API 端點／對照產品／權限矩陣／規格文件
§3    標風險 → 推出目標深度（金流 L4／資料 L3／權限 L3／顯示 L2／邊角 L1）
§9    產出覆蓋矩陣（標準欄位，可被 coverage_matrix.py 讀）
§10.4 三條件判斷「探完了沒」
```

這一步的產物就是你的知識起點：覆蓋矩陣、機制文件、產品 skill 的不變量與意圖對照表。

---

## 之後的日常：13 個情境

開場先載入產品 skill（`/樂透`），它的 §4 會告訴你這次該再載哪一支：

| 你要做什麼 | 載入 |
| --- | --- |
| **開工接手 ／ 收尾交接** | `handoff` ★ 開工第一支 |
| 盤點功能點、設計案例、算覆蓋率 | `testcase-design` |
| 操作瀏覽器探索或重現 | `browser-ops` |
| 把案例寫成 pytest | `ui-test` |
| 開 Bug 單、寫報告 | `bug-report` |
| 驗 JIRA 修復 | `jira-verify` |
| 跑壓測與效能驗證 | `perf-test` |
| 學到新東西要落筆 | `writeback` |
| 要提交變更 | `commit` |

---

## 目錄地圖

```
CLAUDE.md            給 Claude 的規則書（規範的權威）
config/              products.json（產品定義單一來源）、environments.*（站台）、config.local.json（敏感，不版控）
.claude/skills/      9 支流程 skill ＋ 各產品 skill
.claude/memory-seed/ 隨 repo 發送的通用 memory 種子
scripts/             治理腳本（見下）
tools/               測試框架與工具；qa_common／jira_qa／test_platform 為共用基礎設施
tests/               測試案例；tests/tooling/ 是 scripts 自己的測試
docs/                文件；INDEX.md 是索引，docs/<產品>/bugs/ 整層不版控
reports/             allure 結果與報告（不版控）
```

## 乾淨範本鏡像：對外發送的那一份

原版工作區裡有產品資料，**不能直接推上去**。對外的那一份是一個獨立的
**鏡像 repo**（本機為 `C:\GitLab\QA-Template`），內容一律由匯出工具產生，
**不在鏡像裡直接改東西** —— 改了下次同步就會被蓋掉。

```powershell
# 原版改完之後（在原版工作區跑）
python scripts\export_template.py --out C:\GitLab\QA-Template --sync
# → 保留 .git/ 與 .venv/，其餘全部覆蓋，跑完直接列出差異
cd C:\GitLab\QA-Template
git status --short      # 檢查差異
git add -A ; git commit ; git push
```

⛔ `--sync` 的前提是**鏡像的 working tree 是乾淨的** —— 因為覆蓋是不可逆的，
乾淨才代表「蓋掉的每個位元都能用 `git checkout .` 救回來」。髒的話工具會拒絕並列出是哪些檔。
鏡像裡若出現 `docs/**/bugs/`（不版控、救不回來）同樣拒絕。

### ⭐ 讓「忘記同步」會被抓到：設一個 `.template-mirror`

「原版改了而鏡像沒跟上」**不會有任何人發現** —— 同事拿到的是舊的，
而你以為已經給出去了。所以在**原版**的根目錄放一行鏡像路徑：

```powershell
"C:\GitLab\QA-Template" | Out-File -Encoding utf8 .template-mirror
```

之後 `lint_docs`（收尾必跑）就會在鏡像落後時報 **D13** 並附上同步指令。

| | |
| --- | --- |
| 這個檔**不版控** | 鏡像位置每台機器不同 |
| **沒設就整項跳過** | 同事本來就沒有鏡像，報了是雜訊 |
| 只有動到**會被匯出**的路徑才報 | 只改 `docs/<產品>/` 不會吵你 |
| 你手上如果是**匯出的範本** | 整項不會出現（判準：根目錄有 `.template-export`） |

## 治理腳本

| 指令 | 做什麼 |
| --- | --- |
| `bootstrap_workspace.py` | 裝通用 memory（clone 後跑一次） |
| `export_template.py --out <目錄>` | **要把這套結構給別人時用這支**（白名單匯出＋四條自我驗收）；<br>`--audit` 維護入口｜`--verify <目錄>` 交出去前重驗｜**`--compare <目錄>` 某份既有的匯出該不該更新**｜<br>★ **`--out <鏡像> --sync` 覆蓋一份版控中的乾淨範本鏡像**（保留 `.git/`，見下） |
| `reset_workspace.py` | 清空範本原型的產品（已 clone 才需要） |
| `new_product.py` | 接一個新產品 |
| `lint_docs.py --product <產品>` | 文件與交接檔體檢（D1～D10）**收尾必跑** |
| `gen_bug_index.py <產品> [--next-id]` | Bug 索引與**配號**（⛔ 唯一取號途徑） |
| `new_bug_doc.py --product <產品> --kind report\|handover` | **報告／交接檔名防撞** |
| `next_todo_id.py --handover <檔> --kind T` | 交接檔待辦編號防撞 |
| `coverage_matrix.py --file <清單>` | 覆蓋率與缺口；`--lint`／`--orphans` |
| `analyze_run.py` | allure 結果分三類（真失敗／前置未備／環境問題）＋對應已知單 |
| `trace_value.py --value "<舊值>"` | **改任何規格值前後各跑一次**，找出全庫所有出現處 |
| `lint_bug_assets.py` | Bug 單格式與截圖檢查 |
| `run_ui_tests.ps1` | 跑 pytest 並產 allure（**人工發起**，結果落 `reports/`）|

> ### 跑測試有兩條入口，各有各的用途
>
> | | 產出落在 | 什麼時候用 |
> | --- | --- | --- |
> | `scripts/run_ui_tests.ps1` | `reports/allure-*`（**累積**） | 人工發起、要看完整的 allure 報告與歷史趨勢 |
> | **測試助手** `#/tool/ui_tests` | `tools/test_platform/logs/runs/<run_id>/allure-*`（**每個 run 獨立**） | 想留下「這一次跑了什麼、結果如何」的可追溯紀錄；或要從失敗直接開單 |
>
> ⭐ **兩者都餵給同一支 `analyze_run.py`**（真失敗／前置未備／環境問題三分類），
> 所以結論一致 —— 不會出現「終端機說是環境問題、平台說是真失敗」。
>
> ⚠️ **別同時跑** —— 站台是「同帳號他處登入即踢掉前者」，兩邊用同一組子帳號會互踢
> （症狀 `令牌过期，请重新登录`，很容易誤判成平台的 bug）。平台按下去之前會提醒你這件事。

---

## 三條先知道、否則會出錯的紀律

1. **commit 前一律先向使用者確認，且取得許可前不得 `git add`／`git stash`。**
   索引是**整個 working tree 共用的**，不是你這個 session 的 —— 你暫存著等回覆時，
   別的 session 一 commit 就把你的東西一起送出去了。細節見 `commit` skill。

2. **配號／取檔名一律「當下」用指令。**
   `bugs/` 不版控，撞名覆蓋**沒有 git 可以救**；ID 永不回收，自己推算必然撞號。

3. **實測與文件不符時，先問「有沒有人說要改」。**
   找得到人為的變更聲明（RD 留言／PM 修訂／使用者裁示）→ 更新文件；
   只有「我量到不一樣」→ **這是缺陷，去開單**，文件原句不動。
   分不清時一律當缺陷先立單 —— 把缺陷改寫成規格是測試工作最嚴重的失誤型態。

---

## 發現通用層的問題怎麼辦（回饋路徑）

範本是**單向發送**的 —— 你發現 `lint_docs` 的誤報、想到一條更好的判準、
或覺得某支 skill 寫得不清楚，**沒有任何機制會自動送回來**。

所以請主動回饋：

| 你發現的 | 怎麼做 |
| --- | --- |
| 🔴 **共同語言層**的問題（深度分級、Oracle、欄位、status 值） | **一定要回饋** —— 這一層各改各的等於團隊拆夥。先講，取得共識再一起換 |
| 治理腳本的 bug／誤報 | 直接改 ＋ 補一條 `tests/tooling/` 的測試，然後回饋（**測試就是最好的說明**） |
| skill 寫得不清楚、或缺一個情境 | 回饋你**實際卡住的那一刻**在想什麼 —— 那比「建議改成 XX」更有用 |
| 你長出來的新流程，別人可能也用得到 | 回饋。但不必等它完美，**先講一下你在幹嘛**就有價值 |
| 🔴 **測試助手的 `registry/_schema.json` 或內建 `tasks/`** | **一定要回饋** —— 前者是 tool.json 的欄位契約、後者是任務提示模板，分岔了同事的工具與流程就不能互相參考 |

⛔ **不要默默改完就算了** —— 你解掉的問題，別人明天會再踩一次。

---

## 測試助手（選用）

```powershell
tools\test_platform\run_server.bat        # http://127.0.0.1:5300
```

案例索引、Bug、待辦、知識雷達的聚合面板，並能宣告式接入測試工具；
按一個鈕就能起一個**帶好 skill 與上下文**的 Claude session，產出自動落回檔案。
**各自在自己 PC 跑自己的實例、綁自己的 Claude**，不是共用服務。

> ### 📖 使用手冊
> 平台跑起來後，點**頁首右上的「? 手冊」**，或直接開
> <http://127.0.0.1:5300/static/manual.html>
> （檔案在 `tools/test_platform/web_ui/static/manual.html`，離線雙擊也讀得到）。
> 涵蓋上手五分鐘、核心動線、九支任務按鈕、設定四分頁、**安全邊界**與排錯。

定位與路線的單一權威在 `tools/test_platform/docs/ROADMAP.md`；
維護平台本身看 `tools/test_platform/README.md`。
