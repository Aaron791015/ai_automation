# 測試助手（Test Assistant）

> 統一的測試助手：一個 Jarvis 風格的 Dashboard，開著就知道「現在如何」（知識雷達／待辦與 Bug／運行中的 run），
> 要動手時展開工具、選產品、填參數、跑、看報告；並且是一個**框架**，同事的工具與新產品可宣告式接入。

> ### ⭐ 定位：平台 ＝ **帶狀態的 Claude Code**
> 不是 Claude Code 的簡化版，也不是把對話包成表單 —— 它提供**對話給不了的東西**：
> 持久索引、跨 session 視野、非線性瀏覽、`propose_run` 確認閘門。
> **完整定位、分工原則與路線見 → [`docs/ROADMAP.md`](docs/ROADMAP.md)（單一權威）。**
>
> ⚠️ **skill 是平台的大腦**：對話接真後 session 讀的是 `CLAUDE.md` 與 `.claude/skills/`，
> **skill 品質決定平台回答的品質**。規範與 skill 沒成形前，先不要擴張平台功能。

## 啟動

```powershell
tools\test_platform\run_server.bat        # 用工作區 .venv → http://127.0.0.1:5300
```

- 統一使用工作區 `.venv`（flask／psutil／requests 已有，零安裝）。
- host 刻意預設 `127.0.0.1` —— **同事各自跑自己的實例、用自己的 Claude 帳號**；改 0.0.0.0 別人連進來會用你的額度與 OS 身分執行 run。

## 這裡沒有模擬模式

**平台一律真的執行。** 2026-08-23 移除 `mode: demo` 與 `adapters/fake.py`
—— 「看起來會動但其實是假的」對範本是負資產：同事分不出哪些是真的，
出問題時第一個念頭是「這是不是 demo？」而不是去查。

| 面向 | 來源 |
| --- | --- |
| 案例索引 | `pytest --collect-only`（`collect/pytest_case_export.py`，唯讀零風險） |
| 知識雷達 | 掃 `docs/`、`tests/`、`bugs/`、`lint_docs` |
| 本地 Bug 與待辦 | Bug frontmatter（重用 `scripts/bug_paths.py`）與交接檔表格 |
| JIRA 現況 | `tools/jira_qa` 唯讀串接（憑證在設定頁填，快取 30 分鐘） |
| run 執行 | `adapters/pytest_.py`／`cli.py` 真的起子程序、真的可停、真的產 allure |
| Claude 對話 | `claude -p --output-format stream-json` ＋ 平台 MCP；`propose_run` 一律要人按 |

⚠️ **`propose_run` 只能提議** —— UI 出確認卡、人按下去才會真的跑。這條閘門在任何模式下都不繞過。

## 使用手冊（給人看的）

`web_ui/static/manual.html` —— 平台跑起來時從**頁首右上的「? 手冊」**開啟，
或直接 <http://127.0.0.1:5300/static/manual.html>。內容涵蓋上手、核心動線、
任務按鈕、設定四分頁、安全邊界與排錯。**同事拿到範本先看那一份，不是這一份。**
（本檔是給維護平台的人看的。）

## 目錄

```
config/      platform_config.json（版控）／platform_config.local.json（不版控覆寫）
registry/    _schema.json、products.json、<tool_id>.tool.json ×6、profiles/   ← ★ 接新工具改這裡
tasks/       任務按鈕的提示模板 ×9（與 registry 同構）；tasks/custom/ 是自己加的，不隨範本匯出
core/        paths jsonio config registry run_store run_index 三個知識索引（knowledge／todo／bug）
             claude_probe＋claude_session（起 headless session）、tasks（提示渲染）
             draft_parse＋bug_draft＋doc_draft＋spec_draft＋case_writer（草稿 → 落檔）
             credentials（只寫不讀）、config_files（設定檔開檔編輯存回）、pom_index、run_analysis
adapters/    base（唯一契約）／cli／pytest_／argv（http **刻意不做**，見 ARCHITECTURE 決策 6）
runner/      manager（多 run dict ＋ 三層併發鎖 ＋ 佔位在啟動前）
collect/     pytest_case_export（pytest plugin）、pytest_progress（進度 jsonl）、case_index（快取＋樹狀化）
generators/  需求 → 案例清單：rulebased（不耗額度）／claude（讀得懂需求），共用 base 契約
mcp/         server.py —— 給 Claude 的唯讀索引 ＋ propose_run；同一支也註冊在 .mcp.json 給終端機用
reporting/   report_html（移植七星版四原語）
web_ui/      app.py ＋ api/*.py ×15 ＋ static/{index.html, manual.html, css/, js/, fonts/}（ES modules，零建置）
             js/ui/hero.js（主視覺場景）、model3d.js＋models.js（3D 全息體）、radar.js（產品頁雷達）、
             dock.js＋chatportal.js（對話入口）、tasklauncher.js（任務按鈕）；fonts/ 自帶三套字型
cache/ logs/ 不版控
docs/        ROADMAP（★單一權威）／ARCHITECTURE／REGISTRY／CONTRIB_TOOL／FLOWS／VISUAL
             ＋ VISUAL_PLAN_v3、DEMO_流程與UI分析_2026-08-21（兩份是歷史紀錄，不是現況）
```

## 版面（2026-08-19 第三次視覺改版：Starlight Telemetry）

殼＝**左側 icon rail**（底部 Claude 連線燈）＋44px 細 header（右上有「? 手冊」）
＋**全域對話入口**：右下角的通訊埠按鈕 ＋ 左下角的 rail 燈，**總覽另有一個主視覺腳下的大入口**
（那一頁的右下角會自動隱藏）。點下去開的是**畫面置中的大視窗**（2026-08-24 改版）。

- **總覽 `#/` 嚴格單屏、三塊**：**頂部狀態列**（數字・執行摘要・環境燈，橫貫全寬）／
  左為 **HERO 主視覺**佔滿高度／右為 380px 側欄（運行中・待辦與 Bug・助手提示・最近報告）。
  側欄**整欄不捲**，四張卡分掉欄高、各自內捲 —— 這樣「有幾張卡」是版面保證的，
  不是要捲到底才會發現（2026-08-24 重排）。
- **HERO** ＝ 深空 → 地板電路 → 三座產品基座（上方是**真 3D 全息體**：搖球機／渾天儀／聊天室）
  → 中央螺旋星系＋知識雷達軌道。**亮點數就是該產品的知識量**（案例＋規格＋紀錄＋Bug，Bug 為紅點）；
  共通不設基座，其知識散成全景星塵。hover 某座時該全息體會小幅擺動。
- **其他頁**：頁框架固定、內容區單區捲動（操作列與選取列永遠可見）。
- 低於 1280×760 時解鎖頁捲動（優雅降級）。

設計語言（圓角不切角／自帶字型／動態紀律／效能三招）見 `docs/VISUAL.md`；
色票的權威來源是 `.claude/skills/theme-factory/themes/starlight-telemetry.md`。

`#/tools` 四欄產品看板 · `#/tool/<id>` 工具操作（動態表單，執行鈕固定底部）· `#/product/<id>` 產品頁 ·
`#/cases` 案例瀏覽器 · `#/require` 需求→案例 · `#/run/<id>` 執行監控 · `#/reports` 報告中心 ·
`#/sessions` 對話 · `#/registry` 註冊表 · **`#/settings/<tab>` 設定四分頁**（`claude`／`credentials`／`workspace`／`files`）· `Ctrl+K` 指令列

## 接入新工具

### 賠率差案例入口

在「案例瀏覽器 → 新綜合 → test_user_management.py → 各層級 → 赔率差分」查看各層設定、授權、抽驗與分批驗收。層級依測試的目標索引分類；父子授權對歸於操作的上級層級。
每層再分「主要案例（三彩種）／授權檢查／分批驗收／快速抽驗／已知缺陷回歸」。同一函式的彩種、公司與直屬上級路徑收在一個情境下，展開後以中文標示差異。主要 B89／B90／B91 是整層入口；分批 B90＋B92 另含剩餘公式核對，分批 B91 供單彩種續跑，與主要案例部分重疊，不應當成新增覆蓋；快速抽驗僅涵蓋代表欄，回歸則針對既有缺陷。執行時依目的選一套入口，避免把所有分類全選當成去重後的測試計畫。
一次涵蓋多層的設定核對、跨層公式、報表與回歸案例，集中在同檔案節點下的「賠率差跨層與共用」。來源檔、執行 nodeid、步驟與歷史紀錄維持原樣；分類數字含參數展開，不代表已通過數。

分類由 `registry/ui_tests.tool.json` 的 `cases.topics` 維護，依來源檔與 Allure 標籤選取，第一個符合的分類優先；`target_file` 指定顯示位置，`level_labels` 對應零起算的 `level_index`，固定目標案例另由 `fixed_levels` 指定。未符合的案例保留原有檔案分組。新增賠率差測試檔時，須補入對應分類並重建索引。

在 `registry/` 新增 `<tool_id>.tool.json`（依 `_schema.json`），存檔 → `#/registry` 重新載入。**不改平台程式**。詳見 `docs/CONTRIB_TOOL.md`。

## 驗證

```powershell
cd tools\test_platform
..\..\.venv\Scripts\python.exe -m core.registry --validate                     # 6 spec 通過
..\..\.venv\Scripts\python.exe -m collect.case_index --rebuild                  # 案例數以實際掃到的為準
..\..\.venv\Scripts\python.exe -m core.knowledge_index --dump
..\..\.venv\Scripts\python.exe -m core.bug_index --dump --no-jira
..\..\.venv\Scripts\python.exe -m core.todo_index --dump
..\..\.venv\Scripts\python.exe -m core.claude_probe
```

## 路線圖 → 見 [`docs/ROADMAP.md`](docs/ROADMAP.md)（★ 單一權威）

**階段 0／A～H 已全部完成**（2026-08-23）；之後三輪在做「把它變成別人用得下去的東西」
（移除 demo 模式 → 角色重新定義為「檢視產出」→ 更名測試助手＋介面調整＋使用手冊）。

> 📝 2026-08-24 刪掉本節原本複製的那份 P1/P2/P3 表。
> **同一份路線在兩個地方各有一份，正是 `ROADMAP.md` 檔頭寫著要消滅的漂移成因**
> —— 而那份副本已經過期（它列的 P2 對話接真、P3 PytestAdapter 都做完了）。
> 要看下一步做什麼，一律去 `ROADMAP.md`。
