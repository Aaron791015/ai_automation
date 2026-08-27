---
name: api-vs-ui-rule
description: API 加速僅限「非被測行為」的前置資料準備；被測行為本身一律走 UI
metadata: 
  node_type: memory
  type: feedback
  modified: 2026-07-22T02:02:43.230Z
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

使用者明確規定：測試中以 API 取代 UI 操作**須分情境**——API 只能用於「非被測行為」的前置資料準備；案例的被測行為本身一律走 UI，不得以 API 取代。例：測「建立帳號」的案例，建帳號動作必須走 UI；其他案例僅需帳號作為前置條件時才可用 API 建立。

**Why:** 被測行為若走 API 就等於沒測到 UI 流程本身，測試失去意義；API 只是縮短「準備測試資料」的時間。

**How to apply:** 撰寫測試前先辨識案例的「被測行為」是什麼；只有被測行為以外的資料準備可呼叫 API（如 〈產品專屬 memory〉 的 bet_limit_api 模式），且 API 寫入後仍以 UI 重讀驗證。規則已寫入 CLAUDE.md 第 5 節與 `.claude/skills/ui-test/SKILL.md`。
