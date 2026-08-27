"""報告 HTML 共用骨架 —— 移植自 tools/qixing_Performance/reporting/report_html.py（page/cards/table/raw 四原語），
總監報告／跨期報告共用同一份樣式；色碼與平台 tokens.css 相容層一致（GitHub Dark）。"""
from __future__ import annotations

import html
import os

_CSS = """
:root{--bg:#0d1117;--bg-elevated:#161b22;--border:#30363d;--text:#e6edf3;--text-muted:#8b949e;
--primary:#58a6ff;--danger:#f85149;--success:#3fb950;--warn:#d29922;--code-bg:#21262d;}
*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--text);
font-family:"Segoe UI",system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.5}
h1{font-size:1.4rem;margin:0 0 4px}h2{font-size:1.05rem;margin:24px 0 8px;color:var(--text-muted);font-weight:600}
.sub{color:var(--text-muted);margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.card{background:var(--bg-elevated);border:1px solid var(--border);border-radius:8px;padding:12px 14px}
.card .k{color:var(--text-muted);font-size:.78rem}.card .v{font-size:1.15rem;font-weight:600;margin-top:2px;word-break:break-all}
table{border-collapse:collapse;width:100%;background:var(--bg-elevated);border:1px solid var(--border);border-radius:8px;overflow:hidden}
th,td{border-bottom:1px solid var(--border);padding:7px 10px;text-align:left;vertical-align:top;font-size:.85rem}
th{background:var(--code-bg);color:var(--text-muted);font-weight:600;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td{white-space:nowrap}td.wrap{white-space:normal}
.ok{color:var(--success)}.bad{color:var(--danger)}.warn{color:var(--warn)}.muted{color:var(--text-muted)}
code{background:var(--code-bg);padding:1px 5px;border-radius:4px;font-family:Consolas,"Cascadia Mono",monospace;font-size:.82rem}
.note{color:var(--text-muted);font-size:.8rem;margin-top:6px}
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def page(title: str, subtitle: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"/><title>{esc(title)}</title><style>{_CSS}</style></head>
<body><h1>{esc(title)}</h1><div class="sub">{esc(subtitle)}</div>{body}</body></html>"""


def cards(items: list[tuple[str, object]]) -> str:
    return '<div class="grid">' + "".join(
        f'<div class="card"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in items
    ) + "</div>"


def table(headers: list[str], rows: list[list], *, numeric_cols: set[int] | None = None,
          wrap_cols: set[int] | None = None, empty="無資料") -> str:
    """numeric_cols：靠右＋等寬數字（表頭同樣靠右，欄位才對得齊）；wrap_cols：允許換行的長文欄，其餘一律 nowrap。"""
    numeric_cols = numeric_cols or set()
    wrap_cols = wrap_cols or set()
    head = "".join(f'<th{" class=\"num\"" if i in numeric_cols else ""}>{esc(h)}</th>' for i, h in enumerate(headers))
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="muted">{esc(empty)}</td></tr>'
    else:
        body = ""
        for r in rows:
            cells = ""
            for i, c in enumerate(r):
                cls = ' class="num"' if i in numeric_cols else (' class="wrap"' if i in wrap_cols else "")
                # 允許呼叫端傳入已 escape 的 (html, raw) tuple
                if isinstance(c, tuple) and len(c) == 2 and c[0] == "__html__":
                    cells += f"<td{cls}>{c[1]}</td>"
                else:
                    cells += f"<td{cls}>{esc(c)}</td>"
            body += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def raw(h: str):
    return ("__html__", h)


# ---------------------------------------------------------------------------
# Locust 內建 HTML 報告改黑底
# ---------------------------------------------------------------------------
# Locust（2.4x）的報告是 MUI React 單頁：主題取 `window.theme || localStorage.theme || prefers-color-scheme`
# （bundle 內 `MR=co({palette:{mode:window.theme||TR,...}})`），所以在 <head> 最前面塞一行
# `window.theme="dark"` 就能讓整個 app（含表格與 echarts 圖）走原生 dark palette，
# 不必用 !important 硬蓋樣式。另補 color-scheme／body 背景，避免 bundle 載入前白閃一下。
LOCUST_DARK_MARKER = "qixing-locust-dark-theme"
_LOCUST_DARK_SNIPPET = (
    f'<meta name="color-scheme" content="dark"/>'
    f'<script id="{LOCUST_DARK_MARKER}">window.theme="dark";</script>'
    f'<style>html,body{{background:#0d1117 !important;color:#e6edf3}}</style>'
)


def inject_locust_dark_theme(content: str) -> str:
    """回傳已注入黑底設定的 HTML；已注入過（含 marker）則原樣回傳（冪等）。

    Locust 在檔尾 `<script>window.templateArgs=…; window.theme = "light"</script>` 寫死主題，
    而 bundle 是 `type="module"`（延後執行）—— 它讀到的是檔尾那行，所以光在 <head> 設值沒用，
    必須把檔尾那行一併改掉。
    """
    if LOCUST_DARK_MARKER in content:
        return content
    import re
    content = re.sub(r'window\.theme\s*=\s*"light"', 'window.theme = "dark"', content)
    if re.search(r"<head[^>]*>", content, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + _LOCUST_DARK_SNIPPET, content, count=1, flags=re.I)
    return _LOCUST_DARK_SNIPPET + content


def apply_dark_theme_to_locust_report(path: str) -> bool:
    """就地把 Locust 報告改黑底；成功（或本來就已套用）回 True，檔案不存在／IO 失敗回 False。"""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        themed = inject_locust_dark_theme(content)
        if themed != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(themed)
        return True
    except OSError:
        return False
