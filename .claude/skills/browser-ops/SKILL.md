---
name: browser-ops
description: 用 Playwright MCP 操作瀏覽器的通用技能 — 探索頁面、重現 bug、驗證轉場、攔截 API payload。含 session 隔離紀律、語意定位、自訂元件輸入陷阱、探索安全邊界與備援方案。適用於任何產品（CRUX／七星／投注機器人），不論是否要寫測試案例。
---

# 瀏覽器操作（Playwright MCP）

> 本 skill 只管「**怎麼用瀏覽器**」，不管「怎麼寫測試案例」（那是 `ui-test`）、
> 也不管「怎麼驗 JIRA 單」（那是 `jira-verify`）。兩者都會引用本檔。

## 0. Session 紀律（每次必守）

> ### ★ 第一次登入前：先確認本 session 用哪一組子帳號
> 站台是「**同帳號他處登入即踢掉前者**」—— 撞號會把別的 session（或你自己的 pytest）踢下線，
> 症狀是 `令牌过期，请重新登录`／被踢回登入頁，**極易誤判為後端問題或 session 過期**。
> **分配慣例見 `config/environments.md`**；細節見下表「⚠️ 帳號不可與 pytest 共用」。
> （原列在 `handoff` 的開工清單，但互踢發生在**登入那一刻**而非 session 開場，2026-08-22 移到這裡。）

| 規則 | 說明 |
| --- | --- |
| **⭐ 瀏覽器一律用全螢幕** | 使用者 2026-08-20 裁示。MCP 的預設視窗只有 **929×925**，寬表格（報表／利潤率／攔貨）會被擠壓，**截出來的 bug 佐證圖讀不到要對照的欄位**。<br>**已設為預設**：`.mcp.json` 指向 `.mcp/playwright-fullscreen.json`（`launchOptions.args: ["--start-maximized"]` ＋ `contextOptions.viewport: null` —— viewport 跟著視窗走，截圖尺寸即實際視窗）。<br>⚠️ **該設定要重啟 session 才生效**。當前 session 若視窗還是小的，用下面這段把**真實視窗**最大化：<br>```<br>browser_run_code_unsafe  code=async (page) => {<br>  const cdp = await page.context().newCDPSession(page);<br>  const { windowId } = await cdp.send('Browser.getWindowForTarget');<br>  await cdp.send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'maximized' } });<br>}<br>```<br>⛔ **`browser_resize` 只改 viewport（`page.setViewportSize`），headed 模式下 OS 視窗完全不會動** —— 看畫面會發現視窗還是小的。要改真實視窗只能走上面的 CDP，或重啟讓 `.mcp.json` 生效。<br>⚠️ `--viewport-size` 的格式是 **`1920x1080`（用 x）**，寫成 `1920,1080` 會被忽略 |
| **用畢即關** | 探索／驗證告一段落後呼叫 `browser_close` 釋放資源，勿留掛整個 session |
| **各 session 隔離** | `.mcp.json` 已加 `--isolated`（profile 只存記憶體），多 session 併行不互搶。**代價：登入態不跨 session 保留，每個 session 需自行登入** |
| 版本 | 釘 `@playwright/mcp@0.0.77`（本機 Node 18 上限）。升級 Node 20+ 後才可改 `@latest` |
| **兩個瀏覽器可用** | `.mcp.json` 配了 `playwright` 與 `playwright2` 兩個 server，各自獨立瀏覽器與 localStorage。需要**同時以兩個帳號操作 UI** 時用它（詳見下方「兩個帳號同時操作 UI」） |
| 備援 | MCP 不可用時：`scripts\explore_crux_ui.py`／`scripts\explore_wbot_ui.py`（Playwright Inspector 人工模式），請使用者執行並回報 selector |
| **⚠️ 帳號不可與 pytest 共用** | 站台是**同帳號他處登入即踢掉前者**。MCP 開著探索時去跑 pytest（或反之），先登入者的 token 會立即失效，API 回 `令牌过期，请重新登录`、頁面被踢回登入頁 —— 極易誤判為「session 過期」或「後端拒絕」。**併行時分開帳號** —— 各站台的子帳號分配見 **`config/environments.md`**（CRUX 總監2 已備 3 組：`netsub1` pytest／`netsub2` MCP／`netsub4` 第二個 MCP 或第三個 session） |

> ### 📖 這次要同時用兩個帳號操作 UI？→ 讀 [`references/雙帳號操作.md`](references/雙帳號操作.md)
>
> ⛔ **一句話先擋住最常見的錯**：**不要開分頁登入不同帳號** ——
> token 同源共享，後登入的會覆蓋先登入的，但先登入分頁**已渲染的畫面不會變**，
> 形成「**畫面是 A、資料是 B**」的殘影，且**無任何警示**。照著記數據就會張冠李戴。
>
> 正確做法在那份裡：**要操作 UI** → 用第二個 MCP server（`playwright2`，各自獨立 localStorage）；
> **只要讀取比對** → 同一個瀏覽器收集多份 token 用 fetch 指定身份，不必重登。

## 1. 導航：走使用者的實際路徑

> ⛔ **不得用 `browser_navigate` 直接跳到目標頁／目標狀態來「省步驟」。**
> 教訓：2026-08-07 驗 JIRA CRUX-882 時直接導到 `/ledger/daily?level=2&parentId=2`，
> 跳過「在總監層點擊帳號下鑽」這段操作 —— 因而**完全沒看到**該轉場有嚴重缺陷：
> 點擊後表頭立刻變「大股东」、列表卻仍顯示總監資料達 **2.6 秒**且無 loading 遮罩
> （後來成為 CRUX-037／JIRA CRUX-936）。

- **導航要用點的**：點選單、點麵包屑、點表格內的連結／按鈕、用分頁器翻頁。
  `browser_navigate` 只用於**最初進入站台**與**登入**。
- 表單**逐欄填、逐步送出**，不可用 API 直接 POST 出結果再去看畫面。
- 唯一例外：確認某狀態**無法由 UI 到達**時（驗證深層連結、權限繞過），才可 URL 直達，
  且須在報告註明「此項以 URL 直達驗證，未經 UI 操作路徑」。
- ⚠️ 部分頁面**直接導航會被踢回登入**（如 CRUX `/hold/createSell`），必須經正常入口進入。

## 2. 定位：語意優先

- 以 accessibility tree／語意結構為主，記錄元素的 **label、role、可見文字**。
- 前端多為 Vue 3 + Element Plus，欄位 id 動態生成（`el-id-****`）→ **絕不依賴 id**。
- 公告等**彈窗會攔截點擊**：登入後與**每次路由切換後**都可能出現，
  關鍵操作前先迴圈關閉（可能多則輪播），失敗時重試。
- ⛔ **要斷言「前端沒有提示錯誤」之前，必須先查 `.el-overlay-message-box`／`.el-message`。**
  Element Plus 的 API 錯誤是**彈窗／浮動提示**，不是畫面內的 inline 文字 —— 只抓表格區塊會看不到，
  很容易誤報成「前端吞掉錯誤」。這類彈窗還會**攔截後續點擊**，下一步操作 timeout 時要先想到它。
  （教訓：2026-08-12 驗 CRUX-883 綜合報表，把「起始日超限」判成前端無提示並已標注截圖，
  下一次點擊 timeout 才發現錯誤彈窗一直都在，截圖與結論全部重做。）
- ⛔ **偵測彈窗時不要用 `offsetParent !== null` 當「可見」判準。**
  `.el-overlay-message-box` 這類元素在動畫期間 `offsetParent` 就是 `null`，
  於是「彈窗數 0」但它其實在畫面上、且**攔住所有後續點擊** ——
  你會得到「沒有確認彈窗」的錯誤結論，接著下一次 `click` timeout 才發現真相。
  **改用 `document.querySelectorAll('.el-overlay-message-box')` 直接數**（不加可見性過濾），
  或以 Playwright 的 `locator.count()`／`toBeVisible()` 判斷。
  （教訓：2026-08-14 驗 CRUX-962「刪除是否有二次確認」，先以 `offsetParent` 判為「無彈窗」，
  下一步點擊 timeout 的 error log 才顯示 `el-overlay-message-box … intercepts pointer events`。）

## 3. 輸入：自訂元件的三個陷阱

| 陷阱 | 說明 |
| --- | --- |
| **只認鍵盤逐字輸入** | `custom-input-number`（信用額度、分批賠率、出貨賠率）不吃 `fill`／JS setter／`insertText`，**必須 `press_sequentially`**。探索時就要找出可靠輸入法並記錄 |
| **假輸入框** | `.fake-input-container`（span 顯示值＋編輯 icon），**要先點編輯 icon** 才展開真控件 |
| **保存鈕依分頁呼叫不同 API** | 同一顆「保存」在不同分頁只存該分頁欄位（如 CRUX 基本设置存占成/信用額度、投注设置存福利）→ **需分別保存** |

另：下拉選項可能受**上級／繼承值動態限制**（占成盤口逐層遞減、福利受上級鏈限制），
看到選項比預期少時先懷疑這個，不要當成 bug。

## 4. 驗證真實寫入：攔 payload

**不要只記 selector，要確認操作真的寫進後端。**

- 對輸入框／下拉／自訂元件，於「保存」時攔截 API payload 比對送出值。
- 用 `browser_network_requests` 檢視請求；必要時 `browser_evaluate` 讀取
  `localStorage.jwtToken` 自行以 API 回讀後端值交叉驗證。
- ⚠️ **讀取驗證非被測行為**，可以走 API；但**被測行為本身一律走 UI**（CLAUDE.md §5）。

## 5. 轉場觀察（切頁／下鑽／切彩種／翻頁）

轉場本身就是受測範圍。每次切換都要留意：

1. 有沒有 loading 指示？
2. 新舊資料是否混雜？
3. 標題／表頭與內容是否同步？

懷疑有閃爍時，用 `browser_evaluate` 以 `requestAnimationFrame` 取樣記錄 DOM 狀態變化並附**時間軸佐證** ——
**截圖往往來不及**（工具往返常已超過不一致視窗）。

> ### 📖 要動手裝觀察工具時 → 讀 [`references/轉場觀察工具.md`](references/轉場觀察工具.md)
>
> 那裡有三件事：**取樣器的裝法**（一次裝好、之後只讀結果，不必反覆重裝）、
> **慢 API 要用 route 模擬**（別空等，等不到的多半不是慢而是根本沒發）、
> **`browser_evaluate` 傳不了自訂參數**（要把值內嵌進程式字串）。
>
> 上面 §5 的判斷夠你決定「這次要不要做轉場觀察」；真的要裝再讀那份。

## 6. 探索的安全邊界

| 情境 | 規則 |
| --- | --- |
| 唯讀探索 | **不投注、不建帳號、不改設定、不送出任何表單** —— 探索到送出按鈕即停在按下之前，只記錄元素 |
| 高頻彩種前台 | 任何點擊都要先確認**不會觸發真實投注** |
| 開關類設定 | 如「期数模板」的自动开盘／可下注 switch，**切了即生效**，唯讀探索勿碰 |
| 影響全盤 | 開獎「获取结果」「一键结账」「更新时间」、關盤、反結算 → **需個別確認** |
| ⛔ STG | 需逐次取得授權（CLAUDE.md §5），且以唯讀為原則 |
| **測試／驗證任務（非唯讀探索）** | QAT 的 **Web／UI 寫入已預先授權**，直接做不必逐次請示；**DB 一律唯讀**（唯一例外：重置期數改 `DrawTime`）。權威表在 **CLAUDE.md §5「QAT 的寫入授權」**；用完即還原 |

> ## 探索結果回寫 → **已移出到 `writeback` skill**
>
> 知識分流表（這則知識該寫哪一份檔）、產品交接檔骨架與四條紀律、回寫完成的四個必做、
> 更正他人條目的程序 —— **全部移到 `writeback`**。
>
> 📝 2026-08-22 抽出：該節自稱「全工作區的權威分流表」，卻與瀏覽器操作無關，
> 而且被 6 支 skill 引用 —— 想查「知識該寫哪」必須先載入一支 26 KB 的瀏覽器手冊。
>
> ⚠️ 原 §8／§9 因此改號為 **§7 增量驗證**、**§8 暫存物不落 repo**。

## 7. 增量驗證（省時關鍵）

未知 UI 的操作可靠性未知，**切勿寫完整流程後直接跑完整測試賭全對**。

1. 用 MCP 或最小 probe 腳本**逐一驗證每個關鍵操作**確實生效（含攔 payload），再組裝。
2. **由小到大**：單步 → 單帳戶完整流程 → 完整鏈。每階段綠燈才往上。
3. 完整跑失敗時，用 MCP／小 probe **重現失敗的那一步**診斷，不要反覆盲跑。

## 8. 暫存物不落 repo

page snapshot（`*.yml`）、probe 腳本、探索 log、截圖暫存 → **一律寫 scratchpad**（CLAUDE.md §8.3）。
只有正式的 bug 佐證截圖才進 `docs/<專案>/bugs/shots/`，探索截圖進 `docs/<專案>/探索截圖/`。

> ⛔ **要留作 bug 佐證的截圖，必須先標注再截。** 只有畫面的圖，讀者不知道要看哪個數字。
> 用 `tools/qa_common/shot.py` 的 `ANNOTATE_JS`（先裝成 `window.__annotate`，見 §5.3）疊上紅框＋編號，
> 截圖後注入 `CLEAR_JS` 清除。完整規範與 MCP 指令序列見 **`bug-report` skill 的「截圖規範」**。
>
> ⚠️ **MCP 截完還要蓋一次標記**：lint 的 W7 看的是 PNG 裡的 tEXt 標記，不是畫面上的紅框。
> pytest 的 `capture_annotated()` 會自動蓋，MCP 這條路不會 —— 用
> `python scripts\stamp_shots.py --product <產品> <來源>[=<目標檔名>]` 搬移並蓋章
> （會一併檢查檔名規範與覆蓋風險）。

> ⛔ **每張要留存的截圖，拍完就立刻 `stamp_shots.py` 搬走 —— 不要等一批拍完再一起搬。**
> `.playwright-mcp/` 的內容**會在 session 中途消失**：2026-08-20 實際踩到 ——
> 於總監2 拍了 3 張（963／999／1002），接著 `browser_navigate` 切到另一個站台（總監3）
> 再拍 2 張，最後要搬檔時**前 3 張已不存在**、後 2 張還在。
> 該目錄是 MCP 自己管理的暫存輸出（`--isolated` 下更是如此），**不保證跨導航／跨 context 保留**。
>
> ⛔ **而且它是「共用」的：整個 `rm -rf .playwright-mcp` 會清掉別人的佐證。**
> 那是 repo 根目錄下的**單一目錄**，同一台機器上所有 session（含平台起的任務 session）
> 都往那裡寫。要清只能清**自己那幾個檔名**。
> （2026-08-25：終端機 session 為了清自己的截圖暫存跑了 `rm -rf .playwright-mcp`，
> 而平台的 JIRA 重驗 session 正在同一個目錄累積 8 張佐證 —— 整批消失、無法復原，
> 三張 Bug 單與一份驗證報告從此引用著不存在的檔案。
> 平台端的落點已改到 `logs/sessions/<sid>/shots/`，但**終端機這一側仍走這個共用目錄**。）
> 代價是那 3 張要整段 UI 操作重做一次（含重新登入、重新觸發表單驗證）。
>
> **正確節奏**：`browser_take_screenshot` → 立刻 `python scripts\stamp_shots.py --product <產品> <來源>=<目標檔名>` → 再做下一步。

⚠️ **MCP 的 `filename` 參數寫不到 scratchpad**（`browser_take_screenshot`、`browser_evaluate`、
`browser_snapshot` 皆同）：allowed roots 只有 `<repo>` 與 `<repo>/.playwright-mcp`，
給 scratchpad 絕對路徑會回 `File access denied: … is outside allowed roots`。

- **一律加 `.playwright-mcp/` 前綴**（該目錄已列 `.gitignore`）：
  `filename: ".playwright-mcp/CRUX-045_01_xxx.png"`。
- **只給相對檔名會落到 repo 根目錄**（相對於 cwd，不是輸出目錄），污染工作區 ——
  發現時用 `mv` 移到 scratchpad 或 `.playwright-mcp/`。
- 要留存的正式佐證，再從 `.playwright-mcp/` 複製到 `docs/<專案>/bugs/shots/` 並依規範改名。

💡 **snapshot 太大時**：`browser_snapshot` 對長列表頁（如水賠對照表 200+ 列）會超出 token 上限。
用 `target` 縮到單一區塊（`tr:has-text("独胆")`、`.el-form`）＋ `depth` 限制層數；
真的需要全頁再用 `filename` 存檔後以 Read 分段看。
