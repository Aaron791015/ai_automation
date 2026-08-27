# 如何接入你的工具（同事自助）

1. 在 `tools/test_platform/registry/` 新增 `<tool_id>.tool.json`（`tool_id` 小寫英數底線，與檔名一致）。**一工具一檔** —— 各產品線只改自己那支，結構上不可能撞檔。
2. 最小可用：
   ```json
   {"id":"my_tool","product":"crux","name":"我的工具","kind":"cli",
    "runtime":{"cwd":"tools/my_tool"},
    "commands":[{"id":"run","label":"執行","mode":"run","primary":true,"argv":["-m","my_tool.main"],
      "params":{"fields":[{"key":"n","type":"number","label":"次數","default":10,"arg":"-n"}]}}]}
   ```
   平台會以 `.venv\Scripts\python.exe <argv...> -n 10` 執行（`cwd` 相對 repo root）。
3. 長時執行用 `mode:"run"`；秒級用 `mode:"sync"`（結果依 `result.kind` 就地渲染）；有函式沒 CLI 用 `mode:"python_call"` ＋ `call:"module:function"`。
4. 若你的工具會寫自己的 `run_status.json`，在 `run.status_source` 指過去並用 `run.phases[]` 宣告狀態機；否則平台只看 exit code。
5. 會寫測試站的設 `danger.level:"high"`；會與別的工具搶同一站台的設 `run.exclusive_group`。
6. 需要的套件寫進 `runtime.requires.python_modules`，缺件會在 Dashboard 亮紅並給修復指令（統一 .venv：`pip install -r requirements.txt`）。
7. 存檔 → `#/registry` 按「重新載入」→ 通過驗證即出現在 `#/tools`。可先用 `python -m core.registry --validate` 檢查。
   ⭐ 也可以直接用 `#/registry` 的「**＋ 接一支新工具**」建骨架（即時驗證 spec，收不下就不寫檔）。
8. 📝 2026-08-23：`"demo": true` 與 `FakeAdapter` 已移除 —— 平台一律真的執行。要先看畫面就先接一個**唯讀、不碰站台**的命令（`danger.level: low`），按下去跑真的，比模擬更早發現接錯。
9. **需要工具專屬的操作頁面時 → 先別急著寫。** 依三層原則**依序往下、不要跳級**（完整說明見 [`ROADMAP.md`](ROADMAP.md) §6）：
   - **① 用現有宣告能力**：12 種 field type／`run.phases`／`metrics`／`artifacts`／
     `options_from`（`products`／`tools`／`files`）。
     **多數工具到這裡就夠了** —— `views/` 底下目前**沒有任何工具專屬視圖**，`tool.js` 是所有工具共用的。
   - **② 擴充宣告能力** ⭐：需要新互動時，優先**新增一個 field type 或 result kind**，讓所有工具都能用。
     `case_picker` 就是這樣來的 —— 它服務 pytest，但任何需要挑選清單的工具都能用。
     **前者讓後續每個工具受益，後者只服務一個工具卻要長期維護。**
   - **③ 真的無法通用化，才寫 `views/tools/<tool_id>.js`**，且必須滿足四條：
     - **(a) 介面契約**：export 固定簽名（接 run status／spec，回傳 DOM 節點），平台自動掛載
     - **(b) fallback**：載入失敗或不存在時**退回通用 `tool.js`** —— 專屬視圖壞掉不能讓整個工具不能用
     - **(c) 驗收資料**：在 registry 宣告一份範例資料，生成後必須能渲染它（這是「對不對」的唯一自動判準）
     - **(d) 先回答「能不能用 ①②」** —— 擋掉「懶得想就直接生一頁」，那是會累積無聲維護債的路徑


---

## 9. 工作區級工具：`scope: "workspace"`（2026-08-23 新增）

不屬於任何產品的工具（初始化、體檢、覆蓋率盤點）宣告 `"scope": "workspace"`：

- 豁免「`product`／`products` 必填」
- ⚠️ **不在 `#/tools`** —— 2026-08-24 使用者裁示「設定相關的操作應放在設定頁面」，
  `scope: workspace` 的工具改列在 **設定 → 工作區**（`#/settings/workspace`）；
  `#/tool/<id>` 會自動轉址過去，舊連結不會斷

範例見 `registry/setup.tool.json`。

## 10. 標準內建工具：`"products": "*"`

跟著 `config/products.json` **動態展開**（不含偽產品）。
標準內建工具（如 `ui_tests`）不該硬編碼產品清單 ——
否則同事接了自己的產品，還要回頭改 tool.json。

## 11. 通用 `options_from`

```json
{"key": "product", "type": "select", "label": "產品",
 "options_from": {"source": "products", "value": "product_id"}}
```

- `source`: `products`（排除偽產品）／`tools`
- `value`: 省略取 slug（`crux`）；給 `product_id` 取**權威 id**（`CRUX`）——
  `lint_docs --product`／`gen_bug_index` 吃的是權威 id

⭐ **優先擴充這裡，不要新增逐工具的特例。** 舊版是
`if field_key == "member_list" and tool_id == "qixing_perf"` 這種硬編碼。

## 12. 吸收既有工具時：先做**欄位對照盤點**

把一支既有的控制台吸收進平台時，最容易出的錯是**設定悄悄消失** ——
跑得起來、只是某個參數用了預設值，**沒有人會發現**。

做法（`scripts/perf_field_parity.py` 是可照抄的實例）：

1. 掃控制台 HTML 的 `id=`／`name=`，那是它送參數的鍵
2. 每個鍵**逐項歸屬**：對到 tool.json 的 field ／ 顯示用 ／ 已由平台取代 ／ 待補
3. ⚠️ **逐鍵明列，不要用子字串啟發式** ——
   第一版把 `cancel_after_bet_count` 因為含 "cancel" 判成顯示用，那是真設定
4. 寫一支測試釘住「**未歸屬必須為零**」，讓漏掉變成紅燈而不是靠目測
5. ⛔ **憑證不進 tool.json 的 fields** —— 走 `config/config.local.json`（憑證設定頁）

## 13. 任務模板（`tasks/*.json`）

一顆按鈕 ＝ 一組提示 ＋ 要載入的 skill ＋ 一個 Claude session。
格式與**紀律**見 `tasks/_schema.md`。兩條重點：

- `tasks/` 內建（隨範本匯出）／`tasks/custom/` 個人的（不匯出）
- **`writes: draft` 指的是「需要人判斷的那一刻由平台落檔」**（配號也在那一刻）——
  ⭐ **不是**「session 不能寫檔」。2026-08-25 起 session 有 shell 與寫檔，
  否則它照不了 skill 的規範（跑不了 `stamp_shots.py`／`lint_docs.py`）。
  邊界見 `guard/pretool_guard.py`：⛔ git 寫入、⛔ 刪到自己家以外


## 14. ⭐ 接工具前，先把 tool.json 整份讀過

2026-08-23 吸收三支壓測時，**同一個錯誤犯了三次**：平台已經宣告好的機制，
我又在旁邊發明一套。

| 我發明的 | 早就宣告好的 | 差別 |
| --- | --- | --- |
| `runtime.progress`（比對 console 字串推進度） | **`run.status_source`** —— 引擎自己寫的 `run_status.json` 路徑＋欄位名 | 字串會隨日誌措辭漂移；欄位不會 |
| 頂層 `phases` | **`run.phases`** —— 八個階段，中文 label 與 tone 齊全 | 我那份是重複品 |
| `spec.reports`（**根本不存在**） | **`artifacts`** —— `run_dir` 樣板、`whitelist`、`primary[]` | 猜屬性名會在執行時才炸 |

三次都是同一個成因：**憑印象寫，沒把 tool.json 整份看完**。
成本不對稱 —— 讀一遍 tool.json 兩分鐘，事後對照與回退花了一小時。

## 15. 吸收既有工具的五個必檢項

`scripts/perf_field_parity.py` ＋ `tests/tooling/test_perf_field_parity.py`
是可照抄的實例。五條機檢，每一條都對應一個「跑得起來但結果是錯的」失效：

| # | 檢查 | 不檢查會怎樣 |
| --- | --- | --- |
| 1 | **未歸屬（gap）為零** | 吸收後設定悄悄消失，沒有人會發現 |
| 2 | **宣告的旗標，腳本真的認得**（AST 解析 argparse，**逐命令**比對） | `arg` 打錯一個字，UI 完全正常，要等真的跑下去才炸 |
| 3 | **同一命令不得有兩個欄位共用同一個旗標**，也不得有 `--x` 與 `--no-x` 並存 | 表單出現同義欄位；argv 拿到兩次旗標；± 對會讓引擎直接拒絕執行 |
| 4 | **`emit: none` 要盤得出來**（「填了不生效」） | 「欄位存在」≠「設定會生效」—— 這比「介面上不見了」**更難發現** |
| 5 | **adapter 必須自己實作契約的每個方法** | 掉回基底的 `raise`，要等真的按下去才知道 |

⚠️ 第 2 條要**逐命令**：一支 tool.json 有多個命令、各指向不同腳本。
第一版拿整支工具對單一引擎比，把別的命令的旗標誤判成錯誤。

⚠️ 第 5 條是實際發生過的：改 `reports()` 時用「從這裡切到那裡」的字串取代，
一併刪掉了 `run_command`／`health` 等五樣，而**全套測試照樣全綠**
（那條路徑當時零覆蓋）。

## 16. ⛔ 不要對到引擎的「內部變數」

`WBOT_RUN_PARAMS_JSON`／`API_RUN_PROFILE_JSON`／`CRUX_PROFILE_JSON`
看起來是現成的萬能入口 —— 它們**不是對外開口**，是各工具的 `run_manager`
自己 spawn 子程序時設的。

平台直接塞會**繞過 `resolve_params()`／`RunProfile` 的驗證**：
組出來的參數組合未必是系統真的能產生的，**跑出來的數據也就不能拿來當結論**。
（與 `CLAUDE.md` §5 只留 `DrawTime` 一個 DB 寫入口是同一個道理。）

引擎沒開 CLI 就**如實標成 `emit: none` 並寫明「要去改引擎」** ——
別為了讓盤點好看而走後門。
