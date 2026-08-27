# 四條工作動線（2026-08-21 改造）

> 走查結論是「**能跑測試，還不能做測試工作**」——挑案例 → 跑 → 看失敗清單這條已經好用，
> 但開單、驗修復、比較歷次結果、寫案例四條都要離開平台。這一輪把它們補起來。
> 走查原始發現（45 項）見 `DEMO_流程與UI分析_2026-08-21.md`。

> ### ⭐ 前提：skill 是這四條動線的大腦（2026-08-22 補）
>
> 四條動線裡凡屬**創作或判斷**的部分（D 的案例設計、C 的開單內容、A 的「今天該做什麼」），
> 最終都要交給 Claude session 執行 —— 而 session 讀的是 **`CLAUDE.md` 與 `.claude/skills/`**
> （cwd=repo root，自動載入）。**對話與九支任務按鈕都是。**
>
> ⇒ **skill 品質決定這些動線的產出品質。**
> 動線 D 目前只能產「規則式骨架」，**不是 UI 不夠，是當時還沒有 `testcase-design` skill**。
> **規範與 skill 沒成形前擴張動線功能，只會做出更多空殼。** 定位與路線見 [`ROADMAP.md`](ROADMAP.md)。

| | 動線 | 入口 | 產出 |
| --- | --- | --- | --- |
| **A** | 今天做什麼 → 待辦／Bug → 讀到來源 | `#/`、`#/product/<id>` | 跳到來源檔那一行、可複製的開單資訊 |
| **B** | 跑一批測試 → 對的環境 → 有把關 | `#/tool/<id>` | 依勾選案例自動切環境欄位、前置檢查未過會提醒 |
| **C** | 結果回到哪裡 → 開單、比較、驗回歸 | `#/run/<id>`、`#/reports` | Bug 單、同 kind 對比、三組回歸差異 |
| **D** | 需求 → 案例清單 → 人工調整 → 自動化實作 | `#/require` | 可被案例索引收到、可勾選執行的測試檔 |

---

## A：待辦與 Bug 走得到底

`core/todo_index.py` 逐行編號，每筆帶 `doc`（來源檔）＋ `line`（1-based）。
`GET /api/doc?path=<repo 相對路徑>` 唯讀讀 markdown，`ui/docview.js` 渲染並捲到指定行高亮。

**安全邊界**：白名單根只有 `docs/` 與平台自己的 `docs/`；只允許 `.md`；`os.path.realpath` 前綴比對擋 `..` 與 symlink。

## B：產品脈絡與前置把關

**產品脈絡**靠虛擬欄位 `_products`（陣列）——由選取案例推導，注入表單值後，
`visible_when: {"_products": ["crux"]}` 就能依產品切環境欄位。
條件式的比較語意在**前後端雙實作**（`ui/form.js evalCond` 與 `adapters/base.py _cond`），
待測值是陣列時判「交集非空」；⚠️ 改一邊沒改另一邊，會出現「前端顯示、後端丟棄」的鬼欄位。

**前置把關**：命令宣告 `gate: {"requires_check": "preflight", "max_age_minutes": 30}`，
`core/check_store.py` 記住上次 sync 命令的結論，未跑過／過期／未通過時在執行鈕上方提示。
⛔ **只提示不硬擋** —— 有時就是要在環境不全的情況下跑。

## C：失敗變成單、歷次可比

### Bug：誰自動開單、誰留草稿（2026-08-23 角色重新定義後改寫）

> ⚠️ 本節原本寫「**人勾選並確認內容才配號開單**」，那**只對一半** ——
> 2026-08-23 使用者裁示「使用 AI 輔助工作，不是增加自己的工作量，來審核確認未完成任務」之後，
> **session 判定的缺陷會自動開單**。照舊文件去「待開單清單」找，會找不到那些單。

判準是「**這個判定是誰做的**」：

| 來源 | 處置 | 為什麼 |
| --- | --- | --- |
| **session 判定**（探索／需求驗證／JIRA 重驗／手動開單任務） | ✅ **自動開單** | 它已走過 `bug-report` 的**開單前三問**，是有判斷的。配號一樣走 `gen_bug_index --next-id` |
| **run 失敗** | ⛔ **留草稿**（不佔 ID、不寫檔） | 走查實測三筆 run 的失敗集合完全相同（同樣那 14 條），自動開 ＝ 42 張，而 Bug ID 永不回收。更根本的是**測試失敗 ≠ 缺陷** |

實作在 `core/bug_draft.is_auto_fileable()`：`source.kind == "session"` 且**開單前三問至少答了兩題**才自動。
三問沒答完的一律留草稿 —— 三問的答案是「為什麼判定該開」的唯一佐證，沒答就沒有判斷可言。

留草稿這一段還多換到兩件手動開單做不到的事：**跨 run 去重**與**比對既有單**。

比對規則由強到弱：① 該單的 `regression` 欄就是這條 nodeid ② 案例名稱含單號 ③ 模組名相符（弱提示）。
**比對池含已結案的單** —— 命中一張 `fixed` 的單代表**回歸**，比新缺陷更緊急，會標紅並預設勾選。

配號**真的呼叫** `scripts/gen_bug_index.py --next-id`（唯讀），且是**寫檔那一刻**才取 —— 這正是 `CLAUDE.md` 要求的「配號前當下取號」（多 session 併行時，別的 session 隨時可能已經用掉你以為還空著的號）。

### 對比：判準是 `summary.kind`，不是 tool_id

`crux_perf` 與 `qixing_perf` 同為 perf（都在講注數／失敗率／期數），**跨工具本來就該能比**；
pytest 比 perf 沒有共同指標，直接擋掉。pytest 之間另回**三組回歸差異**：

| 組 | 意義 |
| --- | --- |
| 🔴 新壞的 | 前一次過、這次壞 ＝ **回歸**，最該先看 |
| 🟢 修好的 | 前一次壞、這次過 ＝ 修復生效的佐證 |
| ⚪ 一直壞的 | 兩次都壞 ＝ 本次沒有變化 |

## D：需求 → 案例 → 可執行實作

```
需求 ──①生成──▶ 案例清單 ──②檢視/調整/新增──▶ ③產碼 ──▶ ④寫檔・重建索引・語法驗證
      ★可替換              純 UI              ★可替換     純程式
```

①③ 是**可替換的供應者**（`generators/base.py`）：規則式與 Claude 兩條路共用同一組 ②④，換供應者時 **②④ 一行都不用改**。

**規則式的天花板（UI 上也標示）**：只處理**有先例**的需求 —— 從既有案例找結構最近的一條當範本，
沿用它的 fixture／marker／斷言樣式，產出是「既有已驗證程式碼的重組」。**全新玩法或新頁面它生不出來**。

兩道護欄讓產出跑得起來：

1. **`core/pom_index.py`**（`ast` 靜態掃描，約 400 個公開方法）—— 產碼**只能呼叫索引裡存在的方法**，不自由發明 API。
2. **寫檔後真的跑 `pytest --collect-only`** —— 語法錯、import 錯、fixture 名打錯都在這關現形，**收不到就自動還原**
   （一個壞掉的檔會讓整包案例索引 collect 失敗，連帶讓別人的案例瀏覽器空掉）。

⛔ **生成出來的骨架不可以再當範本**（`kind == "generated"`）：它們會被索引收進來，
不排除就形成回饋迴路，抄到的是「待補判準」而不是驗證過的結構。

---

## 產出落點：一律寫真的

📝 2026-08-23 移除 Demo 沙箱。先前所有寫入都落 `tools/test_platform/demo/`，
而那**不是假裝寫檔，是真的寫、只是換個地方** —— 設計本意是「模擬到位」。

問題出在**它從來沒有切回來**：`BUG_OUT_DIR` 與 `TESTS_OUT_DIR` 兩個常數的註解都寫著
「M1 之後要切成真實落點時，只需要改這兩個常數」，而那一步沒做。於是接真之後：

| 產出 | 症狀 |
| --- | --- |
| Bug 單 | 寫進沙箱 → `gen_bug_index`／`lint_docs`／`bugs/_view/` 全都看不到 |
| 測試案例 | 寫進沙箱 → 而索引**只在 demo 模式**才掃沙箱 → **索引掃不到、跑不了** |

現在的落點：

| 產出 | 落點 | 由誰決定 |
| --- | --- | --- |
| Bug 單 | `docs/<產品>/bugs/` | `scripts/bug_paths.py`（Bug 目錄結構的單一事實來源） |
| 測試案例 | `tests/<產品>/` | `config/products.json` 的 `tests_prefix` |
| 機制文件 | `docs/<產品>/` | 同上的 `docs_dir` |
| 交接檔的列 | 產品的 `*驗證交接.md` | 同上的 `handover` |

⛔ 平台**不自己拼路徑** —— 否則它與 `gen_bug_index`／`lint_docs` 會各走各的。

## 接真骨架

| 元件 | 說明 |
| --- | --- |
| `adapters/argv.py` | registry 的 `emit`（11 種）唯一的消費點。同時餵三處：真的 subprocess、確認框預覽、run 參數卡 —— **顯示的命令列與實際跑的是同一份**。golden test 見 `tests/tooling/test_argv_build.py` |
| `adapters/cli.py` | `crux_bet_demo`（競品快譯解析）**真的跑起來**：四個命令全是 `sync`，純本機唯讀、不碰任何站台。`health()` 真的檢查 `loguru` 與 Node 18 |
| ~~`spec.live`~~ | **已無作用**（2026-08-23 移除 demo 模式後失去意義）。先前它是「覆蓋全域 demo」的宣告。三支壓測的 tool.json 還留著這個鍵 —— 沒有害處，但也不做任何事，見共通交接檔 T26 |
| `runtime.json_flag` | 腳本吐單一 JSON 物件的旗標（`crux_bet_demo` 是 `--json-out`）。沒宣告就退回純文字結果 |

> ⚠️ **信封的 `ok` ≠ 工具的結論**：`verify` 有失敗筆數時退出碼是 1，但那張對帳表正是要看的東西。
> 工具自己的成敗放 `tool_ok`／`exit_code`，混用會讓前端把結果當錯誤丟掉、整張表不渲染。

## 相關檔案

| 主題 | 檔案 |
| --- | --- |
| 動線 A | `core/todo_index.py`、`web_ui/api/docs_api.py`、`web_ui/static/js/ui/docview.js` |
| 動線 B | `core/check_store.py`、`web_ui/static/js/store.js`（`syncSelectionProducts`）、`ui/form.js`、`adapters/base.py` |
| 動線 C | `core/bug_draft.py`、`web_ui/api/bugs_file.py`、`web_ui/api/runs.py`（`/api/runs/compare`）、`views/reports.js` |
| 動線 D | `core/pom_index.py`、`core/spec_draft.py`、`core/case_writer.py`、`generators/`、`web_ui/api/drafts.py`、`views/require.js` |
| 接真 | `adapters/argv.py`、`adapters/cli.py`、`tools/CRUX_bet_demo_all/`（四支腳本補了 argparse 與 `--json-out`，**不給旗標時行為完全不變**） |
| 回歸測試 | `tests/tooling/test_argv_build.py`、`tests/tooling/test_platform_flows.py` |


---

## E. 任務啟動器（2026-08-23 新增）

前四條動線是「平台自己做的事」。這一條是**平台與 session 的接點**：

```
儀表板／產品頁／run 結果頁 的任務按鈕
   → 填幾個欄位（重用 ui/form.js）
   → POST /api/tasks/<id>/launch  建 session（帶 context、skills、allowed_tools）
   → SSE 送第一則提示
   → session 載入對應 skill 開始工作
   → 寫入型任務**產草稿**，人在平台按開單才寫檔（配號在那一刻）
```

⭐ **skill 是平台的大腦** —— session 的 cwd 是 repo root，
會自動載入 `CLAUDE.md` 與 `.claude/skills/`。
**skill 品質決定平台回答的品質**，所以 `testcase-design` 等 skill 是平台的前置條件，
不是它的附屬品。

### ★ 兩種「寫入」是不同的東西（2026-08-23 實跑後補）

| | session 能不能做 | 為什麼 |
| --- | --- | --- |
| **站台寫入**（下注／建帳號／改設定／送出表單） | ✅ **可以，而且預設就開** | QAT 的 Web／UI 寫入本來就**已預先授權**（`CLAUDE.md` §5）。<br>⭐ **不能寫入就驗不了正確性** —— 讀得到的東西最多到 L2，會改狀態的規則一條都驗不了 |
| **寫 repo 裡的檔案**（Bug 單、機制文件、報告、交接檔） | ⛔ **不行，一律走草稿** | 平台起的 session **無人看管**，而 Bug ID 永不回收。寫檔與配號都由平台在人按下確認的那一刻執行 |

任務的 `boundary` 欄位控制第一種（可寫入／唯讀二選一，預設可寫入），
展開成整段條款的是 `core/tasks.py` 的 `{boundary_rules}`。

> **踩過的坑**：探索任務原本只給 session 一個標籤（「安全邊界：可寫入 QAT」），
> 又在同一段寫「⛔ 你不能寫檔」—— session 把兩者一起解讀成「什麼都不要改」，
> **全程唯讀**。45 分鐘只驗到「欄位有沒有 `pattern` 屬性」這種讀得出來的事。

### 動線 E 的兩支主力任務

| 任務 | 什麼時候用 | 產出草稿 |
| --- | --- | --- |
| 🔭 **探索新功能** | **沒有規格**，或還不知道這裡有什麼 | 覆蓋矩陣／機制文件（`doc`）＋ Bug ＋ 測試資料（`handover/data`） |
| 📐 **需求驗證** | **有權威規格**（JIRA 需求單／PRD／裁定），要逐項判定做了沒 | **驗證報告**（`report`，檔名走 `new_bug_doc.py`）＋ Bug ＋ 測試資料 ＋ 等裁定（`handover/todo_ext`） |

兩者刻意**不合併**：探索的產物是「這裡有什麼、風險在哪」，
需求驗證的產物是「照規格做了沒」——
判準不同（一個沒有對照組、一個有），落檔也不同（`docs/<產品>/` vs `bugs/_reports/`）。

⛔ 需求驗證特有的一條護欄：**實測與規格不符時要先問「這次有沒有人說要改」** ——
沒有變更聲明就是缺陷，判 FAIL 並開單，**不得改文件**。
把缺陷改寫成規格是 `CLAUDE.md` 列為最嚴重的失誤型態，而平台的 session 無人看管，
所以這一條直接寫進提示裡。
