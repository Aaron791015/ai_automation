---
name: git-amend-race-shared-worktree
description: 共用 working tree 多 session 下 git commit --amend 的競態：HEAD 與「索引」是兩個獨立競態面，只改訊息時一律加 --only
metadata: 
  node_type: memory
  type: feedback
  modified: 2026-08-21T18:33:13.560Z
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

2026-08-03 實際事故：本 session 建立 commit 後欲 amend 修正內容，但另一 session 在其間已連續提交兩筆——amend 因此改寫了**他人的** HEAD commit（把自己的異動混進他人 commit 並換掉其 hash）。以 `git reflog` 找回原 commit、`git reset --soft <原hash>` 還原、再獨立提交自己的修正解決。

**Why**：git 的 HEAD 是共用 working tree 的屬性，多 session 併行時 HEAD 隨時可能被其他 session 推進；`--amend` 永遠作用於「當下的 HEAD」而非「自己剛建的那筆」。

**How to apply**：
- amend 前必做 `git log -1`，確認 HEAD hash＝自己要修的 commit；不是就改用新 commit。
- 誤 amend 到他人 commit 時：`git reflog` 找原 hash → `git reset --soft <原hash>`（保留暫存）→ 自己的異動另行 commit。切勿 `--hard`。
- **本則自己的建議**（非工作區規範）：寧開新 commit、少用 amend，小修正用獨立 fixup commit 更安全。
  （2026-08-22 更正：原文註了出處「（CLAUDE.md §8）」，但**該章節沒有這句話** —— 把自己的結論掛上不存在的出處，
  會讓讀者以為是硬規範。）

**反向也會發生（2026-08-14 實例）**：別人的 session 想 amend 修自己的訊息，
但那一刻 HEAD 已是**我的** commit → 他們的 amend 把我的 commit 換成「我的內容＋他們的訊息」，
我的 commit 從 log 消失。判別法：`git show --name-only HEAD` 的檔案是誰的、
訊息是誰的，兩者對不上就是這個坑。
**內容不會遺失**（amend 只換 commit 物件），對方隨後 `git reset`（非 `--hard`）退回時，
我的異動會原封不動回到工作區，直接重新 commit 即可。
⇒ 收工 commit 前先確認**索引是空的**。看到別人已暫存的內容時，
**現行規範要求停下來回報 —— 不要 commit（會把他們的東西送出去），也不要 reset（會清掉他們的暫存）**。
規則見 `CLAUDE.md` 的「版本控制（Git）」章節。

> （2026-08-22 更正：本則原本教「改用 `git commit -- <自己的路徑>` 的**局部提交**」來繞過。
> 局部提交雖然不會帶走他人的檔，但**現行規範要的是停下、不是繞過** —— 因為對方可能正處在
> 「已暫存、等使用者回覆」的狀態，你繞過去提交會讓他們的索引狀態更難釐清。）

**★ 真正的根因：HEAD 與「索引」是兩個獨立的競態面（2026-08-14，上一段的同一起事故，產品A 功能線視角）**

我 commit 完（6 個檔）想修訊息裡的一個錯字，**有先照上面的規則跑 `git log -1` 確認 HEAD 仍是自己的 commit**，
然後 `git commit --amend`。結果新 commit 的內容**完全變成壓測 session 的 4 個檔案**，我的 6 個檔全消失。
原因：commit 到 amend 之間的 **29 秒**內對方對索引下了 `git add`，
而 **`--amend` 提交的是「當下的索引」**，不是原 commit 的內容。
⇒ **只檢查 HEAD 擋不住這個坑**；症狀還很有欺騙性 —— commit 成功、訊息正確，只有檔案清單會露餡。

**How to apply（補充）**：
- **只想改訊息 → 一律 `git commit --amend --only -F -`**（不帶 pathspec）：
  完全忽略索引、只換訊息，是唯一 race-safe 的改訊息方式。
- 要改**內容**的 amend：`git log -1`（HEAD 是自己的？）**＋** `git diff --cached --stat`（索引是自己的？）
  兩項都確認才動手。
- **amend 後必跑 `git show --stat HEAD` 驗檔案清單**，別只看「commit 成功」。
- 救援用 **`git reset --mixed <原hash>`**：HEAD 與索引還原、**工作區不動**，
  對方的檔案退回 modified／untracked 且內容完好（實測 286+77 行原封不動）。⛔ 切勿 `--hard`。

**寫多行 commit 訊息（Bash 工具）**：用 heredoc `git commit -F - <<'EOF' … EOF`。
⚠️ 別把 PowerShell 的 here-string `@'…'@` 寫進 Bash —— `@` 會變成訊息的一部分。
（2026-08-14 正是為了修掉這個多餘的 `@` 才觸發上述 amend 事故 —— 起因只是個排版錯字。）

相關：[[uncommitted-files-ownership]]
