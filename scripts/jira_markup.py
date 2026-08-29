# -*- coding: utf-8 -*-
r"""markdown → JIRA wiki 標記 ＋ 節名寫法（Bug 單的下游是 JIRA）。

用途：Bug 單寫好之後要**轉貼進 JIRA**，所以正文的標記要對齊 JIRA 而不是 markdown。
使用方式：
    import sys, os
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    from jira_markup import to_jira, strip_headings
    body = strip_headings(to_jira(markdown_body))
前置條件：無（純字串處理，不碰檔案）。

## 為什麼放 scripts/（不是 tools/qa_common/）

⚠️ CLAUDE.md 把 `tools/qa_common/` 定為「跨產品共用元件」，第一版確實放在那裡 ——
但**平台的 sys.path 只有 `tools/test_platform`，沒有 `tools/`**，import 會直接失敗；
而把 `tools/` 加進去會讓 `tools/*_Performance/core` 有機會蓋掉平台自己的 `core`
（`tests/tooling/test_collect_all_roots.py` 專門在守這件事）。

⭐ 改放 `scripts/` 是**照既有慣例**：`scripts/bug_paths.py` 就是同一個形狀 ——
純函式庫住在 `scripts/`，平台用 `sys.path.insert(REPO_ROOT/scripts)` 借用
（見 `core/bug_index.py` 與 `web_ui/api/bugs_file.py`）。

## 為什麼要抽出來

2026-08-26 這套轉換只做在**平台落檔**那條路（`web_ui/api/bugs_file.py`），
`bug-report` skill 與 `scripts/pack_bug_report.py` 都沒跟上 ——
於是同一個工作區同時產出兩種格式的 Bug 單，**而 `lint_bug_assets` 的 W8
還刻意同時容忍兩種寫法**，沒有任何機制會發現在分岔（2026-08-28 使用者查出）。

⛔ 所以這份**不可以再被複製第三次**。要用就 import。

## 轉換規則（2026-08-26 使用者裁示）

| markdown | JIRA wiki |
| --- | --- |
| `**粗體**` | `*粗體*` |
| ` ``` ` 圍欄 | `{code}` … `{code}` |
| `\| --- \| --- \|` 表格分隔行 | 刪掉，上一行改成 `\|\|表頭\|\|表頭\|\|` |
| `## 節名` | 裸行 `節名`（不加 `##`、不加冒號，空一行才接內容） |

⚠️ 節名那條是**實抓 JIRA 真單**得到的（`CRUX-983`／`CRUX-969` 的 description
都是裸行）。本地人工單寫 `##`，是因為貼進 JIRA 之前有一道人工轉換把它拿掉了。
⚠️ 標題行不帶 `# ` —— 它對應的是 JIRA 的 **summary 欄**，不是內文。
⚠️ 反引號**不轉** —— 使用者沒點名，且它原樣顯示仍然可讀。
"""
from __future__ import annotations

import re

#: `bug-report` §4 的節序。⚠️ 這裡只列**節名**，順序的檢查在 `lint_bug_assets` W8。
SECTIONS = ("Reproduce Steps", "Actual result", "Expect result",
            "問題截圖", "【Test Environment】", "附註")

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
#: markdown 表格的分隔行。⚠️ JIRA 的 `|` 本來就是表格語法，這一行會被渲染成
#:  「一列全是破折號的儲存格」—— 留著就是一列垃圾。
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|[ \t]*$")

#: `## Reproduce Steps` / `### 附註` → 裸行。⚠️ 只認**規範的那幾個節名**：
#: 人自己加的分析節（`## 成因`）不在 JIRA 的格式裡，轉成裸行反而看不出是標題。
_HEADING = re.compile(
    r"^#{1,6}[ \t]*(%s)[ \t]*[:：]?[ \t]*$"
    % "|".join(re.escape(s).replace(r"\【", r"【?").replace(r"\】", r"】?")
               for s in SECTIONS), re.M)


def to_jira(text: str) -> str:
    """把正文的 markdown 轉成 JIRA wiki 標記。

    ⭐ 圍欄**先切出來**，內容原樣搬進 `{code}` —— 程式碼裡的 `**` 是次方運算，
       跟著轉會把它改壞。
    """
    out, last = [], 0
    for m in _FENCE.finditer(text):
        out.append(_plain(text[last:m.start()]))
        out.append("{code}\n%s{code}" % m.group(1))
        last = m.end()
    out.append(_plain(text[last:]))
    return "".join(out)


def strip_headings(text: str) -> str:
    """`## Reproduce Steps` → 裸行 `Reproduce Steps`（只作用於規範的節名）。

    ⛔ 不動 `#` 以外的東西，也不動非規範節名 —— 那些是人自己加的，
       拿掉井字號之後讀者就分不出它是標題還是內文。
    """
    return _HEADING.sub(lambda m: m.group(1), text)


def _plain(seg: str) -> str:
    seg = _BOLD.sub(r"*\1*", seg)
    lines, out = seg.split("\n"), []
    for ln in lines:
        if _TABLE_SEP.match(ln) and out and out[-1].lstrip().startswith("|"):
            # 上一行是表頭 → 改成 `||a||b||`，分隔行本身丟掉
            cells = [c.strip() for c in out[-1].strip().strip("|").split("|")]
            out[-1] = "||" + "||".join(cells) + "||"
            continue
        out.append(ln)
    return "\n".join(out)
