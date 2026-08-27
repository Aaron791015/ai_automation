# 測試助手架構

> **定位與路線見 [`ROADMAP.md`](ROADMAP.md)（★ 單一權威）。**
> 本檔只記「**怎麼實作**」，不記「**往哪走**」——先前路線散在 README 最後一行與本檔五處零散引用，是漂移的成因。

## 決策
1. Flask :5300 ＋ 原生 JS ES modules，零建置（與三個壓測控制台同技術棧）。
2. **工具靠 `registry/*.tool.json` 宣告式接入**，平台核心對任何工具的參數一無所知。
3. **Dashboard 是態勢感知不是啟動器**：工具清單在 `#/tools`；閒置態的內容是知識雷達＋待辦與 Bug。
4. **統一 `.venv`**（兩邊都是 Python 3.12.10）。平台相依（flask／psutil／requests）已併入根 `requirements.txt` —— 分成兩份會讓範本裝完卻開不起來。
5. **吸收控制台不吸收引擎**：`CliAdapter` 直接跑 `python -m runner.locust_main`，`tools/*_Performance/{runner,core,reporting}` 一行不動。
6. ~~**代理先行、吸收在後**（M4 `HttpAdapter` → M5 逐一改 cli）。~~
   → **2026-08-23 使用者裁示：跳過 M4，直接吸收。**
   兩者都要做時，先做代理等於做一層之後會丟掉的東西。
   三支壓測本來就是 `kind: cli` 直跑引擎，`adapters/http.py` **不再需要**。
   （決策 5「吸收控制台不吸收引擎」不變：引擎一行不動。）
7. ~~**假在 adapter 不在前端**：`FakeAdapter` 與真 adapter 同介面。~~
   → **2026-08-23 移除 `mode: demo` 與 `adapters/fake.py`，平台一律真的執行。**
   「看起來會動但其實是假的」對範本是負資產：同事分不出哪些是真的，
   出問題時第一個念頭是「這是不是 demo？」而不是去查。
   保留下來的是那條紀律的另一半：**前端永遠只打真 REST**，不在前端造假資料。
8. **Claude 走 MCP server**：平台暴露 `list_cases／get_run_status／get_bugs／propose_run…`，同一個 MCP 也給終端機用；只能提議、人按才執行。

## 分層
- `core/`：路徑、原子 JSON、設定、registry、run 狀態、跨工具索引、三個知識索引（knowledge／todo／bug）、Claude 探測。
- `adapters/base.py`：唯一契約 `validate／start／stop／status／logs／reports／list_cases／run_command`。
- `runner/manager.py`：多 run dict；三層併發（不同工具可並行／同工具 `concurrency`／跨工具 `exclusive_group`）；**佔位在 start 之前**；剛結束的 run 保留 15 分鐘。
- `collect/`：pytest plugin 自寫 UTF-8 JSON（繞 cp950）；`case_index` mtime 簽章快取＋背景重建＋樹狀化（wbot 走 allure 三層、crux 塌陷到檔案層、tooling 收合成非產品）；前置依賴由 fixture 反推。
- `web_ui/api/` ×15：bootstrap／registry_api／runs／cases／reports／knowledge（含 health／hints）／search／settings（含**憑證**與**設定檔編輯**）／sessions／chat／**tasks_api**（任務啟動器）／**drafts**＋**bugs_file**（草稿與落單）／**docs_api**／**verif_reports**。
- `mcp/server.py`：給 Claude 的唯讀索引 ＋ 一個 `propose_run`（只提議）。**同一支也註冊在 `.mcp.json` 給終端機的 session 用。**
- `generators/`：需求 → 案例清單的兩種生成器（`rulebased` 不耗額度、`claude` 讀得懂需求），共用 `base` 契約。
- `tasks/*.json` ×9：任務按鈕的提示模板（與 registry 同構，可自行增刪；`tasks/custom/` 不隨範本匯出）。
- 前端 `js/`：`api`（統一 {ok,error}、409）、`store`（observable）、`router`（hash ＋ keepAlive）、`poll`（單一輪詢器 ＋ SSE）、`ui/` ×19（el／form 動態表單引擎／tree／radar／cmdbar／hud／modal／toast／todopanel／**chatpanel**／**dock**＋**chatportal**（對話入口）／**tasklauncher**／**bugfiler**／docview／hero＋model3d＋models（主視覺））、`views/` ×15。

## run 生命週期
`logs/runs/<YYYYMMDD_HHMMSS_<tool_id>>/{run_meta.json, run_status.json, console.log, stop.flag, allure-*}`；`logs/runs_index.jsonl` append-only ＋ 自癒重建。
`run_status.json`：平台 phase（7 值）與工具 phase 分開；`summary.kind` 為前端渲染分派鍵。所有 JSON 一律 `write_json_atomic`（tmp＋replace，per-path 鎖，Windows PermissionError 重試）。

## 已知限制（2026-08-24 實查）

> ⚠️ 本節 2026-08-24 重寫。**先前列的三項「限制」（對話是規則式／run 執行是假的／JIRA 用快照）
> 全部已經不成立** —— 階段 0～H 完成後它們都接真了，而表格沒有跟著改。
> 文件說「這是假的」而實際是真的，比反過來更糟：人不會去用那個功能。

| 限制 | 現況 | 處置 |
| --- | --- | --- |
| **覆蓋矩陣沒有聚合視圖** | 覆蓋矩陣仍只在 `docs/<產品>/` 的 markdown 裡，平台沒有把它彙整成一頁。`docs_api` ＋ `ui/docview.js` 可重用 | 尚未做 |
| `adapters/http.py` 未實作 | **刻意不做**（決策 6：直接吸收，不做代理）。三支壓測本來就是 `kind: cli` 直跑引擎 | 不做 |
| `lint_docs` 無 `--json` | 平台先解析 stdout。要換成結構化輸出隨手可補 | 隨手可補 |
| 主視覺擺動的真實幀率 | headless 量不到，需在真瀏覽器目視確認（`hero.js` 的 `FRAME_MS`／`models.js` 的 `SWAY` 各是一行常數） | 見共通交接檔 T4 |

### ✅ 已接真的（曾經是限制，別再照舊文件推論）

| 面向 | 實作 |
| --- | --- |
| 對話 | `core/claude_session.py` 起 `claude -p --output-format stream-json`；SSE 串流；斷線／逾時都會把已產出的內容落檔（在 `finally` 裡） |
| run 執行 | `adapters/pytest_.py`（allure 獨立目錄、exit code 1 → `completed`、進度 plugin 只 append）與 `adapters/cli.py`（`stop` 殺整棵程序樹） |
| JIRA | `tools/jira_qa` 唯讀串接，憑證走設定頁，30 分鐘快取 |
| 壓測 | 三支 `kind: cli` 直跑引擎，前置檢查移植成 `gate` |

⛔ **`propose_run` 一律只能提議** —— UI 出確認卡、人按下去才會真的跑。這條閘門在任何情況下都不繞過。
