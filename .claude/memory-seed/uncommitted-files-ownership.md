---
name: uncommitted-files-ownership
description: 多 session 共用 working tree「為什麼」需要版控紀律——三個實際踩過的坑；規則本體一律以 CLAUDE.md 的版本控制章節為準
metadata: 
  node_type: memory
  type: feedback
  modified: 2026-08-21T18:32:37.550Z
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

> ⛔ **本則只記「為什麼」，不記任何 git 指令。**
> **操作規則的唯一權威是 `CLAUDE.md` 的「版本控制（Git）」章節**（兩段式流程、路徑歸屬、共用檔紀律、
> co-commit 配套）。動手前去讀那裡，不要照本則行動。
>
> 📝 **2026-08-22 全面改寫**：本則原本寫著具體指令，而那些指令**已被現行規範明令禁止**——
> 教過「commit 前跑 `git add --renormalize .`」（現規範：取得許可前不得碰索引，且加 `.` 會暫存他人檔案）、
> 教過誤帶時用 `git reset` 救援（現規範：發現他人暫存時**停下回報**，不要 reset）、
> 寫過「共用檔只增不減」（2026-08-13 已改為「只動自己的條目」，可增可改可刪）。
> **一則會過期的操作指令留在 memory 裡，比沒有還糟**——memory 沒有 lint、沒有版控、沒人會發現它過期。

## 核心事實

本工作區**多個 session 併行、共用同一份 working tree**。而 git 的「當前分支」與「索引」都是
**working tree 的屬性、不是 session 的屬性** —— 一個 session 切分支或暫存，其他 session 會當場受影響。

這推導出三件事（規則細節見 CLAUDE.md）：**所有 session 直接在 `main` 上提交**、
**取得許可前不碰索引**、**只提交自己路徑的檔案**。

## Why：三個實際踩過的坑

1. **任務分支長期未併回** —— `某任務分支` 期間別的 session 在 main 上提交了 6 個 產品A commit，
   `git status` 冒出 25 個檔，被誤判成「我的未 commit」而向使用者回報錯誤。
   ⭐ **`git status` 顯示的內容 ≠ 你的未 commit 工作。**
2. **CRLF 差異**使約 100 個 `tools/產品A_Performance/` 檔顯示為 modified，實際零差異。
3. **先讀後寫的競態** —— `docs/INDEX.md` 我手上的版本較舊，寫回去會刪掉 main 上其他 session 新加的行。
   共用檔的風險是這個，**不是 merge 衝突**。

## 第四個坑（2026-08-12 實踩，最貴的一個）

另一個 session 可能已經把它的檔案暫存進**共用的索引**——此時你的 commit 會把
**整個索引**（含對方的檔案）一起送出，即使你只 add 了自己的路徑。

> 這正是現行規範要求「**取得 commit 許可之前完全不碰索引**」的由來：
> 「已暫存、正在等使用者回覆」是整個流程中**停留時間最長**的狀態，也是最危險的。

## How to apply

- **動手前先讀 CLAUDE.md 的版本控制章節**，照那裡的流程走
- 併行干擾若成常態（如 [[playwright-mcp-setup]] 的 profile 互搶），再考慮 `git worktree` 每 session 一目錄
- 相關：[[git-amend-race-shared-worktree]]
