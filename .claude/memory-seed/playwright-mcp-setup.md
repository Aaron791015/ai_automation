---
name: playwright-mcp-setup
description: 工作區已接 Playwright MCP（.mcp.json 釘 0.0.77，因 Node 18 上限；--isolated 各 session 隔離）
metadata:
  node_type: memory
  type: project
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

工作區根目錄的 `.mcp.json` 已接入 Playwright MCP，供 Claude 直接操作瀏覽器做 UI 探索
（取代人工 Inspector 抄 selector 的流程）。

- 版本**釘在 `@playwright/mcp@0.0.77`**：0.0.78 起相依 playwright 1.62-alpha 要求 **Node >= 20**
  Node 18 會啟動失敗。**升級 Node 20+ 後才可改 `@latest`**。
- Windows 原生環境下 npx 需以 `cmd /c` 包裝（`.mcp.json` 已如此設定）。
- **`--isolated`**（profile 僅存記憶體）：各 session 的 MCP 瀏覽器彼此隔離
  解決多 session 互搶 profile。代價：**登入態不跨 session 保留，每 session 需重新登入**。
- 配了 **兩個 server**（`playwright`／`playwright2`），需要同時以兩個帳號操作 UI 時用第二個。
- **用畢呼叫 `browser_close`**，勿留掛整個 session。
- ⚠️ 改 `.mcp.json` 後**需重啟 session 才生效**。

完整操作規則見 skill `browser-ops`；寫測試案例的流程見 `ui-test`；API 使用限制見 api-vs-ui-rule。
