"""把測試報告的 Markdown 轉成單檔 HTML（暗色主題，與壓測工具的 HTML 報告同風格）。

用途
    `docs/<專案>/bugs/_reports/` 下的測試報告是 Markdown，方便版本比對與檢索；
    但對外交付、或給不裝 Markdown 檢視器的人看時需要 HTML。
    本腳本產出**單一自足檔案**（CSS 內嵌、無外部資源），複製一個檔就能寄出。

    刻意不引入 `markdown` 套件：測試報告只用到固定的一小撮語法
    （標題、GFM 表格、清單、引言、水平線、粗體、行內程式碼、連結、程式區塊），
    自行處理可避免為了一支轉檔工具而在 `requirements.txt` 新增相依。

使用方式
    python scripts\\md_to_html_report.py <報告.md>
    python scripts\\md_to_html_report.py <報告.md> -o <輸出.html>
    python scripts\\md_to_html_report.py docs\\CRUX\\bugs\\_reports\\*.md   # 批次

前置條件
    無。純標準函式庫。

⚠️ 產出的 HTML 與來源同目錄（預設），故 `bugs/` 層下的報告轉出來一樣不版控。
"""
from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { background: #12151a; color: #e4e7eb; margin: 0; }
body {
  font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC", system-ui, sans-serif;
  line-height: 1.75; font-size: 15px;
}
.wrap { max-width: 1080px; margin: 0 auto; padding: 40px 24px 80px; }
h1, h2, h3, h4 { color: #f3f4f6; line-height: 1.35; }
h1 { font-size: 28px; border-bottom: 2px solid #2d3544; padding-bottom: 14px; margin-bottom: 8px; }
h2 { font-size: 22px; margin-top: 44px; border-bottom: 1px solid #2d3544; padding-bottom: 8px; }
h3 { font-size: 18px; margin-top: 32px; color: #cbd5e1; }
h4 { font-size: 16px; margin-top: 24px; color: #cbd5e1; }
p { color: #c9cdd4; }
strong { color: #f3f4f6; }
a { color: #60a5fa; }
hr { border: 0; border-top: 1px solid #2d3544; margin: 36px 0; }
ul, ol { color: #c9cdd4; padding-left: 26px; }
li { margin: 6px 0; }
blockquote {
  margin: 18px 0; padding: 12px 18px;
  border-left: 3px solid #3b82f6; background: #171c24; color: #b6bcc6;
}
blockquote p:first-child { margin-top: 0; }
blockquote p:last-child { margin-bottom: 0; }
code {
  background: #1f2630; color: #93c5fd; padding: 2px 6px;
  border-radius: 4px; font-size: 13px;
  font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
}
pre {
  background: #1a1f27; border: 1px solid #2d3544; border-radius: 6px;
  padding: 14px 16px; overflow-x: auto;
}
pre code { background: none; color: #d5dae1; padding: 0; }
.table-scroll { overflow-x: auto; margin: 18px 0; }
table { border-collapse: collapse; width: 100%; font-size: 14px; background: #1a1f27; }
th, td { border: 1px solid #2d3544; padding: 8px 11px; text-align: left; vertical-align: top; }
th { background: #232a35; color: #cbd5e1; white-space: nowrap; }
tbody tr:nth-child(even) { background: #161b22; }
tbody tr:hover { background: #252d3a; }
.footer-note { color: #8b949e; font-size: 12px; margin-top: 48px; border-top: 1px solid #2d3544; padding-top: 14px; }
"""

# 行內語法：程式碼要先抽走，才不會讓 `**` 之類的符號在程式碼裡被當成粗體
_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def render_inline(text: str) -> str:
    """行內語法 → HTML。順序：先保護程式碼 → 逸出 → 連結 → 粗體 → 還原程式碼。"""
    slots: list[str] = []

    def _stash(m: re.Match) -> str:
        slots.append(m.group(1))
        return f"\x00{len(slots) - 1}\x00"

    text = _CODE_RE.sub(_stash, text)
    text = html.escape(text, quote=False)
    text = _LINK_RE.sub(lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    for i, code in enumerate(slots):
        text = text.replace(f"\x00{i}\x00", f"<code>{html.escape(code, quote=False)}</code>")
    return text


def _split_row(line: str) -> list[str]:
    """切 GFM 表格列。首尾的 `|` 是裝飾，去掉後才不會多出空欄。"""
    cells = line.strip().split("|")
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?[\s:|-]+\|?", line.strip())) and "-" in line


def convert(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    list_stack: list[str] = []   # 目前開著的 <ul>/<ol>

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 程式區塊
        if stripped.startswith("```"):
            close_lists()
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(buf), quote=False) + "</code></pre>")
            continue

        # 表格：至少要有「表頭 + 分隔列」
        if stripped.startswith("|") and i + 1 < n and _is_separator(lines[i + 1]):
            close_lists()
            header = _split_row(stripped)
            i += 2
            body = []
            while i < n and lines[i].strip().startswith("|"):
                body.append(_split_row(lines[i]))
                i += 1
            out.append('<div class="table-scroll"><table><thead><tr>'
                       + "".join(f"<th>{render_inline(c)}</th>" for c in header)
                       + "</tr></thead><tbody>")
            for row in body:
                # 欄數不齊時補空白，避免表格塌掉
                row = (row + [""] * len(header))[:len(header)]
                out.append("<tr>" + "".join(f"<td>{render_inline(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table></div>")
            continue

        # 空行
        if not stripped:
            close_lists()
            i += 1
            continue

        # 水平線（要放在「清單」之前判斷，`---` 不是清單）
        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # 標題
        m = re.match(r"(#{1,6})\s+(.*)", stripped)
        if m:
            close_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{render_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # 引言（連續多行併成一個 blockquote）
        if stripped.startswith(">"):
            close_lists()
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + convert("\n".join(buf)) + "</blockquote>")
            continue

        # 原生 HTML 直通（如 <details>）
        if stripped.startswith("<"):
            close_lists()
            out.append(stripped)
            i += 1
            continue

        # 清單
        m = re.match(r"([-*])\s+(.*)", stripped) or re.match(r"(\d+)\.\s+(.*)", stripped)
        if m:
            tag = "ul" if m.group(1) in "-*" else "ol"
            if not list_stack or list_stack[-1] != tag:
                close_lists()
                out.append(f"<{tag}>")
                list_stack.append(tag)
            item = [m.group(2)]
            i += 1
            # 續行（縮排的接續文字併進同一個 <li>）
            while i < n and lines[i].startswith(("  ", "\t")) and lines[i].strip() \
                    and not re.match(r"\s*([-*]|\d+\.)\s+", lines[i]) \
                    and not lines[i].strip().startswith("|"):
                item.append(lines[i].strip())
                i += 1
            out.append(f"<li>{render_inline(' '.join(item))}</li>")
            continue

        # 段落（連續行併成一段）
        close_lists()
        buf = [stripped]
        i += 1
        while i < n and lines[i].strip() and not re.match(
                r"\s*(#{1,6}\s|[-*]\s|\d+\.\s|>|\||```|-{3,}$|<)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{render_inline(' '.join(buf))}</p>")

    close_lists()
    return "\n".join(out)


def build_document(title: str, body_html: str, source_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title, quote=False)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{body_html}
<div class="footer-note">由 scripts/md_to_html_report.py 自 {html.escape(source_name, quote=False)} 產生</div>
</div>
</body>
</html>
"""


def convert_file(src: str, out_path: str | None = None) -> str:
    with open(src, encoding="utf-8") as f:
        md = f.read()
    # 標題取第一個 H1，沒有就用檔名
    m = re.search(r"(?m)^#\s+(.*)$", md)
    title = m.group(1).strip() if m else os.path.splitext(os.path.basename(src))[0]
    dest = out_path or os.path.splitext(src)[0] + ".html"
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_document(title, convert(md), os.path.basename(src)))
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="測試報告 Markdown → 單檔 HTML")
    ap.add_argument("sources", nargs="+", help="來源 .md（可用萬用字元）")
    ap.add_argument("-o", "--out", help="輸出路徑（只在單一來源時有效）")
    args = ap.parse_args()

    paths: list[str] = []
    for pattern in args.sources:
        matched = glob.glob(pattern)
        if not matched:
            print(f"✖ 找不到：{pattern}", file=sys.stderr)
            return 1
        paths.extend(matched)

    if args.out and len(paths) > 1:
        print("✖ 多個來源時不可指定 --out", file=sys.stderr)
        return 1

    for p in paths:
        dest = convert_file(p, args.out)
        print(f"✅ {p}\n   → {dest}（{os.path.getsize(dest):,} bytes）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
