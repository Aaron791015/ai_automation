---
name: env-credentials-policy
description: config/environments.md 可放 QAT 測試站帳密並版控，不視為外洩
metadata: 
  node_type: memory
  type: feedback
  modified: 2026-07-21T08:04:51.592Z
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

`config/environments.md` **刻意**存放 QAT/STG **測試站的站台 URL 與拋棄式測試帳密**，且**納入 git 版控**（此為內部 repo）。正式環境（prod）帳密/token/連線字串才放 `config/config.local.json`（不版控）。

**Why:** 使用者確認這是內部 repo + 純測試站拋棄式帳號，刻意為之。
**How to apply:** 不要把 `environments.md` 內的測試帳密當成敏感外洩來反覆示警；只有 prod 憑證誤入版控時才提醒。與 〈產品專屬 memory〉 的 config 慣例一致（該慣例的敏感分離仍適用於 prod）。
