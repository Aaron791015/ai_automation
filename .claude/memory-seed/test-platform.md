---
name: test-platform
description: 統一測試平台 tools/test_platform —— Flask :5300、registry 宣告式接工具、實作踩坑
metadata:
  node_type: memory
  type: project
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

`tools/test_platform/` 是隨範本附帶的**統一測試平台**（Flask，`run_server.bat` → http://127.0.0.1:5300）。
路線與定位的單一權威在 **`tools/test_platform/docs/ROADMAP.md`**。

**Why（設計要點，不看 code 看不出）**：
- **分發模式是「各自 PC 跑各自的實例、綁自己的 Claude」**，不是共用服務 ——
  所以不需要部署、多人併發、身份與權限系統。
- Dashboard 是**態勢感知**不是啟動器；工具清單在 `#/tools`。
- **接工具是宣告式的**：新增一個 `.tool.json` 就會出現在介面，參數表單由 `ui/form.js` 依 field type 動態渲染。
  需要更多能力時**優先擴充宣告能力**（新 field type／result kind，所有工具受益）
  最後才寫工具專屬視圖。見 `docs/CONTRIB_TOOL.md`。
- **Claude 只能 `propose_run`，UI 出確認卡、人按才跑。**
- **skill 是平台的大腦** —— 對話接真後 session 讀的仍是 `CLAUDE.md` 與 `.claude/skills/`。

**How to apply（實作踩坑）**：
1. 含反斜線或複雜引號的 JSON/JS **一律用 Write 工具，別用 bash heredoc** —— 見 bash-heredoc-backslash-trap。
2. CSS 註解裡不能寫 `.tip-*/` —— `*/` 提前結束註解，把整個 `:root {}` 吞掉（症狀：所有 CSS 變數為空）。
3. `el.js` 的 ``html`` `` 回 SafeString；內層的純字串 fallback 會被 esc，要包 `raw()`。
4. Flask 靜態檔已設 `Cache-Control: no-store`，改 JS 直接重載即可。
5. 多執行緒同寫 `run_status.json` 會互踩 tmp 檔：`jsonio` 的 tmp 名含 thread id ＋ per-path 鎖。
6. `pytest --collect-only` 匯出：plugin 自寫 UTF-8 JSON（繞 cp950）、命令列再給一次 `--alluredir`
   指向拋棄目錄（覆蓋 addopts）、**不要** `-p no:allure_pytest`。
