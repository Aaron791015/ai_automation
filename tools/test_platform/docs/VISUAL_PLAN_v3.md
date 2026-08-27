# 第三次視覺改版 —— 計畫原文與執行結果對照

> **狀態：已完成並提交**（`ced5228` 主體、`449b6c5` 收尾）。本檔是**歷史紀錄**，不是現況規格。
>
> ⛔ **要查「現在長什麼樣、為什麼這樣設計」一律看 [`VISUAL.md`](VISUAL.md)**，不要看本檔。
> 計畫是動工前寫的，執行中經使用者多輪指正而改了方向（見下表），
> 照本檔的敘述去改程式會改錯。留著它是為了保存**決策脈絡**：
> 為什麼要裝兩支官方 skill、為什麼先產主題規格再動 CSS、為什麼要拆掉軍事 HUD 語彙。
>
> 原檔為本機的 `~/.claude/plans/sequential-meandering-peacock.md`（不版控），
> 2026-08-20 依使用者要求複製進 repo。以下第二節起為**逐字保留的原文**。

## 計畫 vs 實際（執行中被推翻的部分）

| 計畫怎麼寫（§） | 實際做出來的 | 為什麼改 |
| --- | --- | --- |
| §4.1 物件用 **2D 剪影 path**，靠 `getTotalLength()`／`isPointInFill()` 沿輪廓與內部灑點 | **真 3D 低多邊形模型＋表面取樣**（`ui/model3d.js`＋`ui/models.js`）；`ui/pointcloud.js` 縮到 26 行只剩 tooltip 說明與 bloom | 2D 沒有面的前後關係，再怎麼加細節都不夠寫實 —— 使用者連續三輪指出「不夠寫實／過於可愛」 |
| §4.2 七星＝**北斗七星星圖** | **渾天儀**（赤道環／子午環／黃道環＋中心球＋地平環＋支柱） | 使用者要求更寫實、更像實物 |
| §4.2 投注機器人＝**機械手臂點觸投注面板** | **聊天室**（懸浮對話視窗＋浮泡） | 使用者裁示「wbot 使用聊天室如何?」，對應前台聊天室 |
| §4.2 共通＝**伺服器機櫃**（第四座基座） | **不設基座**，知識量散成全景星塵 | 共通貫穿所有產品，不該與產品並列成第四座 |
| §4.3 中央＝**線框地球**（沿用第二版並點陣化） | **螺旋星系 ＋ 知識雷達軌道融進主視覺** | 使用者要求移除地球、並把側欄的知識雷達融入主視覺 |
| §5 右欄四卡＝系統概況／運行中／待辦與 Bug／助手提示＋熱度 | 系統概況／運行中／**最近報告**／待辦與 Bug | 版面實作時調整 |
| （計畫未涵蓋） | **hover 擺動**：游標停在某座基座 → 該全息體擺 ±16° | 3D 化之後補的收尾，見 `VISUAL.md` §動態紀律 |
| （計畫未涵蓋） | **基座改半透明玻璃台座**（柱身 .42／底盤 .3／外沿 .24） | 不透明會在地板與星空上壓出三塊近黑量體 |

計畫中**照原樣做到**的部分：兩支官方 skill 的安裝與使用、先產主題規格再動 CSS 的流程（§1）、
拆掉切角／L 型角標／掃描線（§2）、自帶字型與型階（§3）、總覽兩欄版面（§5）、驗收項目（§9）。

---

## 原始計畫（2026-08-19 核准版，以下逐字保留）

## Context

平台功能已完成並 commit（`858326a` Demo 本體、`5cccb3c` 第二次視覺改版）。**本計畫純前端改樣式，API／core／adapters／runner／registry 一律不動。**

前兩次改版都沒打中：第一次太暗太平，第二次雖已依參考圖取樣色票，使用者仍表示「不是理想中的畫面」。這次先找出**為什麼還是不像**，再動手：

### 為什麼還是不像（本次盤點出的根因）

| # | 現況 | 參考圖 | 影響 |
| --- | --- | --- | --- |
| 1 | **切角＋L 角標＋掃描線**的軍事 HUD 語彙（9 處 `clip-path`、4 處角標、`sweep` 掃描動畫） | **圓角矩形、無角標、無掃描線**的乾淨金融儀表板 | ★ 最大落差。整體氣質完全不同 |
| 2 | 主視覺物件是**線稿 wireframe** | **深色剪影＋內部星點場＋亮點描邊輪廓＋少量連線** | ★ 使用者明確指出「類似星光點陣投影」 |
| 3 | 大數字用等寬字（`--mono`） | 幾何無襯線**細體大字**，僅數字對齊用 tabular figures | 質感偏「終端機」而非「儀表板」 |
| 4 | 卡片密、padding 小 | 留白大、字級大 | 顯得侷促 |
| 5 | 產品圖示是抽象小圖騰 | **該領域的真實物件**（牛／大樓／水晶／鈔票） | 使用者：「需要更符合產品的圖示」 |

色票已於上一版逐點取樣自參考圖，**本次沿用不再重調**（`--bg #020d19`／面板 `#0e1721`／正文 `#d0e7f5`／主青 `#7fd5f0`／次藍 `#29a8e0`／金 `#f0b429`／綠 `#4ade80`／標題 `#adcddc`）。

### 使用者裁示（2026-08-19，本輪）

| 議題 | 裁示 |
| --- | --- |
| skill | 下載官方 `frontend-design` **與 `theme-factory`**，兩者併用 |
| 字體 | **字型檔放進 repo**（離線也一致） |
| 物件題材 | **改用彩票世界的真實物件**；並補充「主視覺的產品圖示需重新設計、要更符合產品」 |
| 版面 | **維持單屏不捲**，但**下方卡片改到側邊垂直排列**，讓主視覺有完整空間 |

### 兩支官方 skill 各自負責什麼（已查證內容，非臆測）

| skill | 是什麼 | 在本計畫的角色 |
| --- | --- | --- |
| **`frontend-design`** v1.1.0（`anthropics/claude-code`） | 單一 `SKILL.md`（8,260 bytes）的**設計方法論**，不產程式碼 | 決定**怎麼設計**：見下方五條 |
| **`theme-factory`**（`anthropics/skills`） | `SKILL.md`＋10 個預設主題＋`theme-showcase.pdf`＋`LICENSE.txt`。主題檔格式：**4 色帶名稱的 hex ＋ 標題／正文字體配對 ＋ 適用場景** | 決定**主題怎麼被審核**：產出一份可讀的主題規格，**先給使用者確認再套用** |

`frontend-design` 的五條，本計畫據以執行：

- 「**brief 的原話永遠優先**」→ 參考圖就是 brief，逐項比照，不自由發揮。
- 「**扎根於題材本身**」→ 圖示改用彩票／測試世界的真實物件（見 §4）。
- 「**把大膽用在一個地方**」→ signature ＝ **星光點陣投影的產品基座**；其餘一律安靜（正是拿掉切角／角標／掃描線的理由）。
- 「**排版承載個性**」→ 顯示字與正文字分工（見 §3.2）。
- 「**邊做邊自我批評、截圖看**」→ 驗收照 §9。

> ★ **theme-factory 帶來的關鍵改變**：它規定「產出主題 → **展示給使用者審核** → 確認後才套用」。
> 前兩次改版失敗的正是這一環 —— 我都是直接改完 CSS，使用者看到成品才說「不是理想中的畫面」。
> 本次**在動任何 CSS 之前先交出主題規格**（§1），確認了才往下做。

---

## 0. 安裝兩支 skill

| 目的地 | 來源 |
| --- | --- |
| `.claude/skills/frontend-design/SKILL.md` | `raw.githubusercontent.com/anthropics/claude-code/main/plugins/frontend-design/skills/frontend-design/SKILL.md` |
| `.claude/skills/theme-factory/SKILL.md`＋`themes/*.md`（10 支）＋`theme-showcase.pdf`＋`LICENSE.txt` | `raw.githubusercontent.com/anthropics/skills/main/skills/theme-factory/…` |

檔頭各記一行來源與取得日期。`.claude/skills/` 是共用檔 —— 依 CLAUDE.md §8.4**只新增自己的目錄，不動他人條目**。

---

## 1. 【先做且需你確認】以 theme-factory 產出主題規格

**10 個預設主題全部不適用**（已逐項查證）：Ocean Depths／Sunset Boulevard／Forest Canopy／Modern Minimalist／Golden Hour／Arctic Frost／Desert Rose／Tech Innovation／Botanical Garden／Midnight Galaxy —— 全是**簡報用的通用主題**，字體是 FreeSans／DejaVu Sans，配色多為淺底 4 色，沒有一個是深色資料儀表板。最接近的 Tech Innovation（`#0066ff`／`#00ffff`／`#1e1e1e`／`#fff`）霓虹感過強，與參考圖的**低飽和鋼青**相反。

故走 skill 的「**Create your Own Theme**」分支：

1. 依 skill 指示**先展示 `theme-showcase.pdf`** 給使用者過目 10 個預設。
2. 產出自訂主題 **`.claude/skills/theme-factory/themes/starlight-telemetry.md`**（沿用該 skill 的檔案格式：命名色票／字體配對／適用場景），內容＝上一版已逐點取樣自參考圖的色票 ＋ §3 的字體配對 ＋ signature 說明。
3. **交給使用者審核確認**（skill 明訂「show it for review and verification」）。
4. 確認後才進 §2 之後的實作；`tokens.css` 的值一律由這份主題檔推導，不另外憑感覺調色。

> 主題檔放在 skill 的 `themes/` 下是遵循該 skill 的慣例（它會去那裡讀），並在 `docs/VISUAL.md` 留指標。

---

## 2. 拆掉軍事 HUD 語彙（`components.css`／`base.css`）

這是最大單筆改動，也是「比照參考圖」的主體。

- **全面移除** `clip-path` 切角（9 處：`.card`／`.btn`／`.pill`／`.modal .box`／`.cmdbar .box`／`.dock-panel`／`.env-badge` 等）→ 改 `border-radius`：卡片 10px、按鈕 6px、輸入框 6px、pill 999px、modal 12px。
- **全面移除** `.card::before/::after`、`.modal .box::before/::after` 的 L 型角標（4 處）。
- **移除** `.scanline` 掃描線動畫（改以卡片邊框轉青＋左緣光棒表示「執行中」）。
- 卡片背景改**上淺下深的微漸層**（`linear-gradient(180deg, #131e2a, #0e1721)`），邊框 1px `--border`，hover 才升為 `--border-strong`。
- **留白放大**：卡片 padding 9→14px、標題與內容間距 8→12px、卡片間 gap 10→14px。
- 區塊標題右側補參考圖的 `···` 次要動作點（僅視覺占位，無行為）。
- 分段控制（如報告頁的篩選）改參考圖的**圓角膠囊 active**樣式。

> ⚠️ 依 skill 的提醒：改 CSS 特異度時小心互相抵銷。本檔已有前科（`.hero .globe.state-idle .globe-edge` 0-4-0 壓過 `html[data-motion="0"] …` 0-3-1 使開關失效），**每個 `data-motion="0"` 關閉規則都要重新核對特異度**。

## 3. 字體（自帶字型檔）

### 3.1 檔案

`web_ui/static/fonts/`（新目錄，OFL 授權，需一併放 `OFL.txt`）：

| 角色 | 字體 | 用途 |
| --- | --- | --- |
| 顯示 | **Sora**（600/700） | 品牌、卡片標題、主視覺柱面產品名 |
| 正文／數字 | **Inter**（400/500/600，`tnum` tabular figures） | 全站正文、標籤、**所有大數字**（取代等寬） |
| 等寬 | **JetBrains Mono**（400） | console／log／nodeid／run_id 等真正的代碼 |

- 只取 latin 子集，`font-display: swap`，`@font-face` 寫在 `tokens.css` 前段。
- **中文不自帶**（完整繁中字型 5MB＋，不划算）→ fallback 維持 `"Noto Sans TC", "Microsoft JhengHei"`。字型堆疊需驗證中英混排的基線與字重不打架。
- 若實作時無法取得字型檔（網路受限），**退回系統字並在計畫回報中說明**，不得靜默略過。

### 3.2 型階

`--font-display: Sora`／`--font: Inter`／`--mono: JetBrains Mono`。
大數字 34px/300–400（非等寬、開 `tnum`）；卡片標題 11px/600/`.16em` 大寫；標籤 11px muted；正文 13.5px。

## 4. 主視覺：星光點陣投影（`ui/hero.js` 重寫 ＋ 新 `ui/pointcloud.js`）

### 4.1 點陣渲染法（技術核心）

參考圖的物件＝**深色剪影 ＋ 內部星點場 ＋ 亮點描邊輪廓 ＋ 少量星座連線**。用瀏覽器原生 API 從既有 path 產生，不需手工排點：

1. 每個物件仍以**若干條 SVG path 定義剪影**（我畫）。
2. `SVGGeometryElement.getTotalLength()` ＋ `getPointAtLength()` **沿輪廓等距取樣** → 亮點（r 1.0–1.6、opacity .7–1）。
3. `SVGGeometryElement.isPointInFill()` 對**確定性亂數**灑出的候選點做內部測試 → 星點場（r 0.5–1.3、opacity .15–.7）。
4. 每點連到最近的 1–2 個鄰點，取前 N 條 → 極淡星座連線（opacity ≤ .18）。
5. 剪影本身保留一層極淡填色（opacity .06–.10）撐出體積。

**三個必須遵守的實作紀律**：

- **確定性亂數**（mulberry32＋固定 seed）—— 否則每次重畫星點就跳動一次。
- **快取產生結果**（key＝`pid`）—— `drawHero()` 會被 `subscribe(active)` 與 60s 輪詢反覆呼叫，**每次重算點陣會嚴重掉效能**。
- **點數上限**：每物件 ≤ 320 點（輪廓 180 ＋ 內部 140），四物件合計 ≤ 1,300 個 `<circle>`；閃爍只給其中約 30 點（CSS staggered delay），不要每點都動。

### 4.2 四個新物件（彩票世界的真實物件）

| 產品 | 物件 | 為什麼是這個 |
| --- | --- | --- |
| **CRUX**（排列三 P3、福彩 3D） | **開獎搖球機** —— 透明球艙＋艙內編號球＋底座與出球管 | 直接對應「開獎」這件事；球體與球最適合點陣 |
| **七星**（幸運五星彩／七星彩／排列五） | **七星座星圖** —— 七顆亮星＋星座連線＋淡星塵 | 「七星」的字面義；且**天生就是點陣**，與 signature 完全同語彙 |
| **投注機器人** | **機械手臂點觸投注面板** —— 三節手臂＋夾具＋面板上的號碼格 | 講清楚「自動投注外掛」；取代原本偏可愛的機器人頭 |
| **共通** | **伺服器機櫃** —— 層板＋指示燈＋側面透視 | 已是真實物件、與參考圖的大樓同語彙，沿用並改點陣 |

`glyphSvg(pid, size)` 供 `#/tools` 欄首與產品頁頁首重用時，**小尺寸改用剪影＋少量點**（點陣在 22px 下看不出來）。

### 4.3 場景

沿用第二版已驗證的骨架（圓柱基座、柱面刻字、光錐、掃描帶、發射環、中央線框地球、地板透視環），**只換物件畫法並重算 viewBox**：側欄化之後主視覺變高（見 §5），viewBox 由現在的 `14 8 1172 442`（比例 2.65）改為約 **`0 0 1200 820`（比例 1.46）**，基座列上移、地球放大並下移到前景，垂直空間留給高聳的點陣物件。地球本身也改點陣化（經緯線＋節點）以統一語彙。

## 5. 總覽版面：主視覺獨占，卡片移到右側欄

依裁示改為**左右兩欄**（rail 在左，故卡片放右較平衡）：

```
┌──────┬──────────────────────────────────┬──────────────┐
│ rail │ header 44px                                     │
│ 64px ├──────────────────────────────────┼──────────────┤
│      │                                  │ 系統概況      │
│      │        HERO 點陣投影主視覺        │ 運行中        │
│      │        （佔滿剩餘寬高）           │ 待辦與 Bug    │
│      │                                  │ 助手提示＋熱度 │
│      ├──────────────────────────────────┴──────────────┤
│      │ 播報 ticker 30px                                 │
└──────┴─────────────────────────────────────────────────┘
```

- 右欄固定 **380px**，內部 4 張卡垂直排列（總高約 930px，1080p 下剛好；矮螢幕時**整欄內捲**，主視覺高度不受影響）。
- **原本的三張狀態卡（系統狀態／執行狀態／環境健康）合併為一張「系統概況」**——它們都只有幾個數字與燈號，合併後省下兩組卡片框與標題列，正是騰出空間的關鍵。內部分三段：關鍵數字列／執行狀態列／環境燈列。
- 其餘三卡（運行中、待辦與 Bug、助手提示＋24h 熱度）沿用現有內容與 API。
- 斷點：`max-width: 1279px` 或 `max-height: 759px` 時右欄改為主視覺下方的橫列並解鎖頁捲（現有降級規則沿用）。

資料來源不變：`/api/knowledge｜cases｜bugs｜todos｜health｜runs/*｜hints｜narration`。

## 6. 其他頁

§2 的元件改動一次生效，各頁只需頁級微調：

- `#/tools` 看板欄首換小圖示；`#/product/<id>` 頁首同。
- `#/reports` 篩選改膠囊分段控制；趨勢圖改平滑曲線＋柔和面積漸層（現為折線）。
- `#/cases`／`#/run`／`#/registry`／`#/sessions`／`#/settings` 僅隨元件連動，版面不動。
- 產品頁的線框極座標雷達**維持上一版的細線樣式**（已對齊參考圖 RISK METRICS 那格），只跟著圓角化。

## 7. 檔案清單

| 檔案 | 動作 |
| --- | --- |
| `.claude/skills/frontend-design/SKILL.md` | **新增**（官方 skill） |
| `.claude/skills/theme-factory/`（`SKILL.md`／`themes/`／showcase／LICENSE） | **新增**（官方 skill） |
| `.claude/skills/theme-factory/themes/starlight-telemetry.md` | **新增**：本平台的自訂主題規格（§1，需你確認） |
| `web_ui/static/fonts/*.woff2`＋`OFL.txt` | **新增**（Sora／Inter／JetBrains Mono，latin 子集） |
| `css/tokens.css` | `@font-face`、字體 token、型階；色票不動 |
| `css/components.css` | **最大改動**：去切角／去角標／去掃描線、圓角化、留白放大、卡片漸層 |
| `css/base.css` | 殼與 rail 圓角化、兩欄 grid |
| `css/hud.css` | 總覽兩欄版面、點陣物件樣式、側欄卡 |
| `js/ui/pointcloud.js` | **新增**：path → 輪廓取樣／內部星點／星座連線／確定性亂數／快取 |
| `js/ui/hero.js` | 重寫：四個新題材的剪影 path、新 viewBox、改用 pointcloud |
| `js/views/overview.js` | 兩欄版面、三卡合併為「系統概況」 |
| `js/views/reports.js` | 膠囊分段控制、平滑曲線 |
| `js/ui/hud.js` | sparkline 改平滑曲線 |
| `docs/VISUAL.md`／`README.md` | 設計語言改寫（去 HUD 語彙、點陣規格、字體、兩欄版面） |

**不動**：`web_ui/api/`、`core/`、`adapters/`、`runner/`、`collect/`、`registry/`。

## 8. 實作順序

1. 裝兩支 skill
2. **展示 showcase ＋ 產出主題規格 → 停下來等你確認**（§1）
3. 字型檔與型階
4. 去 HUD 語彙＋圓角化（全站質感先到位）
5. `pointcloud.js` ＋ **先只做七星星座**一個物件 → **截圖給你看**，點陣手法確認可行再往下
6. 其餘三物件（搖球機／機械手臂／機櫃）
7. 總覽兩欄版面
8. 其他頁微調
9. 文件（`VISUAL.md`／`README.md`）
10. 驗收（§9）

> 第 2、5 步是刻意設的**兩個停等點** —— 前兩次都是一路做到底才給看，錯了就整批重來。

## 9. 驗證

```powershell
tools\test_platform\run_server.bat   # http://127.0.0.1:5300
```

Playwright 於 **1920×1080（主要）** 與 **1366×768（降級）**：

0. **主題規格**：`tokens.css` 的每個色票值都能在 `starlight-telemetry.md` 找到對應（不得有憑感覺加的顏色）。
1. **逐頁截圖過目**（總覽／tools／tool/crux_perf／cases／run／product/crux／reports／sessions／registry／settings）—— 與參考圖並排比對；確認**無殘留切角／角標／掃描線**（`grep clip-path` 應只剩必要處）。
2. 總覽：`scrollHeight <= clientHeight`；主視覺高度 ≥ 視窗 70%；右欄 4 卡齊全；1366×768 降級正常。
3. 點陣：四物件皆生成，`.pc-dot` 總數在預算內；**連續觸發 10 次 `drawHero()` 後點座標不變**（確定性＋快取都成立）。
4. 字體：`document.fonts.check()` 三支皆載入；中英混排無基線跳動；離線（斷網）仍正常。
5. fake run：基座轉 hot、地球推進弧、右欄執行狀態同步、停止生效。
6. 互動：點基座 → 產品頁；dock 各頁可開；`Ctrl K` 命令列；「降低動態」→ **零動畫殘留**（含新的點陣閃爍）。
7. `console` 零錯誤；`tests/tooling` 129 綠；5 支 registry spec 通過；全部 JS 語法檢查通過。
8. 收工前刪除暫存截圖與 `.playwright-mcp/`（§8.5）。

完成後依 CLAUDE.md §8.2 五步驟整理 commit（`[共通]`）供使用者確認，**不自行 commit**。

## 10. 風險與退路

| 風險 | 退路 |
| --- | --- |
| 字型檔下載不到（網路受限） | 退回系統字堆疊，**在回報中明說**，型階照樣調 |
| 1,300 個 `<circle>` ＋ 柔光濾鏡造成掉幀 | 先降點數與閃爍點數；仍不足則物件改 `<canvas>` 分層（互動留在 SVG 層）。**headless 下 rAF 被鎖 1fps 量不到真實幀率，需在真實瀏覽器目視確認** |
| `isPointInFill` 在舊瀏覽器不支援 | 內部星點改用 path bounding box ＋ 手工遮罩多邊形；輪廓取樣不受影響（`getPointAtLength` 支援度無虞） |
| 四張側欄卡在 1080p 塞不下 | 「助手提示」改為卡內捲；再不夠則熱度條併入 ticker 列 |
