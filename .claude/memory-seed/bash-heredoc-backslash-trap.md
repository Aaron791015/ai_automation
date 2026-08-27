---
name: bash-heredoc-backslash-trap
description: 用 Bash heredoc 直接跑 Python 改檔時，Windows 路徑的反斜線會被吃掉（`scripts\new_x.py` 的 \n 變成換行）—— 一律改成先寫 .py 檔再執行
metadata: 
  node_type: memory
  type: feedback
  modified: 2026-08-22T00:38:16.241Z
---

> 📌 **範本內建的通用教訓。** 文中的「產品A／產品B／產品C」是範本原型留下的匿名實例，
> 只是為了讓教訓有具體場景 —— **教訓照用，例子換成你自己的產品**。

**⛔ 不要用 `python - <<'EOF'` 的 heredoc 去寫含 Windows 路徑的內容。**
即使用 quoted heredoc（`<<'EOF'`，理應完全不展開），**實測 `\\` 仍會被縮成 `\`** ——
於是 Python 再解析一次，`\n`／`\t`／`\a`／`\r` 就變成了控制字元。

## 實際踩到的樣子（2026-08-22）

想寫進文件的是：
```
python scripts\new_product.py --id <產品名> ...
```
實際寫進去的是**兩行**：
```
python scripts
ew_product.py --id <產品名> ...
```
`\n` 被當成換行吃掉了。**而且腳本不會報錯** —— `assert` 通過、`print` 顯示成功、
檔案 mtime 也更新了，只有內容是壞的。是後來用 `grep -c "new_product"` 回 0 才發現。

## 哪些名字會中招

首字母是有效跳脫字元的都會：

| 序列 | 受害的檔名 | 變成 |
| --- | --- | --- |
| `\n` | `next_todo_id`、`new_bug_doc`、`new_product` | 換行 |
| `\t` | `trace_value` | tab |
| `\a` | `analyze_run` | BEL |
| `\r` | `run_ui_tests` | CR |
| `\b` | `bug_paths` | BS |

（`\l`／`\g`／`\s`／`\j` 不是有效跳脫，那些名字反而安全 —— 更難察覺規律。）

**Why**：這類破損**靜默發生**，而工作區的文件大量寫著 `python scripts\xxx.py` 這種指令。
壞掉的指令複製貼上會直接失敗，但沒人會回頭看是哪一步寫壞的。

**How to apply**：

- **改檔一律先用 Write 寫成 `.py` 到 scratchpad，再 `python <檔>` 執行** —— 本 session
  用這個方式做的十幾次編輯全部正常，只有改用 heredoc 的那兩次壞掉。
- 非寫不可時，用 `chr(92)` 組出反斜線，或全程用正斜線。
- **改完一定要 grep 驗證關鍵字串真的在檔案裡** —— 不要相信腳本印的「成功」。
- 事後掃描：搜 `\next_`／`\trace_`／`\analyze_` 這類殘骸（首字母被吃掉後會黏在上一行尾）。

相關：[[uncommitted-files-ownership]]（同樣是「工具行為與直覺不符」的類型）
