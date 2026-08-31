---
name: template-sync-snapshots-worktree-not-head
description: export_template --sync 快照的是「工作區」不是 HEAD —— 共用 working tree 下，任何人跑它都會把當下所有 session 未提交的檔複製進範本鏡像
metadata:
  type: feedback
---

**`python scripts\export_template.py --out <鏡像> --sync` 匯出的是「檔案現在長什麼樣」，
不是「HEAD 長什麼樣」。**

而這個工作區是**多 session 共用同一份 working tree**（見 [[uncommitted-files-ownership]]）——
所以任何人跑一次 `--sync`，就會把**當下所有 session 未提交的工作**一起複製進鏡像，
然後那些檔會以「未提交變更」的樣子留在鏡像裡，等著被下一個人 commit 掉。

2026-08-27 實例：另一個 session 提交完自己的東西後跑 `--sync`，
把我**改到一半**的六個平台檔帶了過去，只提交戳記檔。我下次要同步時被擋下來
（`⛔ 鏡像有未提交的變更`），才發現那不是我放的。

**Why**：這條擋不住的原因是它**看起來完全正常** —— 跑的人只看到自己的 commit 進去了，
鏡像的 `git status` 要有人主動去看才會發現多了別人的檔。
而鏡像是**要交給同事**的東西，夾帶半成品的代價由別人承擔。

**How to apply**：

1. **跑 `--sync` 之前先看 `git status --short`** —— 有別人的檔就先確認：
   那些檔在不在匯出白名單裡（產品 skill 與 `docs/<產品>/` **不在**，所以多數時候是安全的）。
2. **鏡像被擋下來時，先查那是誰的**（`diff -u 鏡像檔 原型檔 | grep '^-[^-]'`
   看有沒有「只存在於鏡像」的內容）—— 確認全是自己的舊版才可以 `git checkout -- .` 重來。
   ⛔ 看都不看就還原，等於幫別人把工作刪掉。
3. **戳記出現 `+dirty` 是誠實的訊號，不是要去消掉的東西** —— 它就是在說
   「同步當下來源工作區不乾淨」。要消掉只能等所有 session 都提交完，實務上等不到。

⭐ 判準與 CLAUDE.md 的版本控制章節同源：**索引與工作區都是 working tree 的屬性，
不是 session 的屬性**。`--sync` 只是第三個踩到這件事的東西。
