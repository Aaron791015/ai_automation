---
name: stg-requires-authorization
description: STG 環境已交客戶試用，需使用者逐次授權才可操作；預設一律走 QAT
metadata:
  node_type: memory
  type: feedback
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

**STG 環境已提供給客戶試用，不得任意使用。**
預設一律選 QAT；即使任務描述指定 STG，仍需**執行前向使用者確認授權**，且授權只適用該次任務、不延續。

**Why**：客戶正在試用，任何寫入（下注、結算／反結算、改設定、建帳號、出貨）
都可能干擾客戶或污染其資料。

**How to apply**：
- 規則的權威在 `CLAUDE.md` §5「QAT 的寫入授權」表與 `config/environments.md` 抬頭，動手前先看。
- 各站台的實際 URL 一律查 `config/environments.md`，**不要背在 memory 裡**（站台會換）。
- **既有於 STG 取得的結論若需重新佐證或補截圖，改在 QAT 複現**，不要回頭操作 STG。
- 正式環境（prod）一律不碰。

相關：env-credentials-policy
