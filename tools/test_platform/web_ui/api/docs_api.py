"""/api/doc —— 唯讀讀取工作區的 markdown 檔（給前端 docview 顯示全文並定位到行）。

用途：待辦「看全文」跳到交接檔的那一行、Bug 單「看全文」讀 docs/<產品>/bugs/*.md。
使用方式：GET /api/doc?path=docs/CRUX/CRUX_功能驗證交接.md
前置條件：
    · ⛔ 唯讀。平台不寫回工作區任何既有檔案（產出一律落 demo/ 沙箱）。
    · 三道防護：白名單根目錄 ＋ 只允許 .md ＋ realpath 前綴檢查（同時擋 `..` 與 symlink 逃逸）。
      用 realpath 而非 abspath 是因為 abspath 不解析 symlink —— 指向根外的連結會通過前綴檢查。
    · 平台本來就只綁 127.0.0.1（config/platform_config.json），這個口不對外。
"""
from __future__ import annotations

import os

from flask import Blueprint, request

from core.paths import BASE_DIR, DOCS_DIR, REPO_ROOT, rel_to_repo
from web_ui.api import fail, ok

bp = Blueprint("docs_api", __name__)

# 允許讀的根：工作區 docs/（含各產品的 bugs/）、平台自己的 docs/、
# 以及 **`.claude/skills/`**（產品 skill）。
#
# ⭐ 為什麼把 skills 也放進來（2026-08-24）：平台現在會自動往產品 skill 的
#    意圖對照表補列（`kind: skill` 的草稿），而產品頁的「文件」分頁也把它列出來了。
#    **列得出來卻打不開**就是白列 —— 點下去只會拿到 400。
# ⛔ 仍然只放行 `.md`，且路徑要在這三個根底下（`resolve_doc` 用 realpath 比對，
#    擋掉 `../` 逃逸）。skill 是可版控、不含帳密的檔案，唯讀開放沒有風險。
_ROOTS = (os.path.realpath(DOCS_DIR),
          os.path.realpath(os.path.join(BASE_DIR, "docs")),
          os.path.realpath(os.path.join(REPO_ROOT, ".claude", "skills")))

# ⭐ 根目錄的 **`README.md` 逐檔放行**（2026-08-24）——「根目錄」不能整個當白名單根，
#    那等於放行整個 repo。放行它的理由很具體：總覽空狀態的
#    「看 README 的完整上手五步」指向 `#/doc?path=README.md`，
#    而那是**新同事看到的第一個畫面**（一個產品都還沒接的時候）。
#
# ⚠️ **只加真的被連到的檔** —— `CLAUDE.md` 刻意不放行：
#    `tests/tooling/test_platform_flows.py` 拿它當「白名單外」的代表，
#    連同 `docs/../CLAUDE.md`、`docs/INDEX.md/../../CLAUDE.md` 兩個逃逸變體一起釘。
#    把它放進來，那三條斷言就失去意義了 —— 而它們正是這個口的安全底線。
_ALLOW_FILES = (os.path.realpath(os.path.join(REPO_ROOT, "README.md")),)
_MAX_BYTES = 2 * 1024 * 1024


def resolve_doc(rel: str) -> str | None:
    """把 repo 相對路徑解析成絕對路徑；不合法回 None。對外只暴露 .md。"""
    if not rel or os.path.isabs(rel) or rel.startswith("\\"):
        return None
    if os.path.splitext(rel)[1].lower() != ".md":
        return None
    path = os.path.realpath(os.path.join(REPO_ROOT, rel))
    if path in _ALLOW_FILES:
        return path
    for root in _ROOTS:
        if path == root or path.startswith(root + os.sep):
            return path
    return None


@bp.get("/api/doc")
def get_doc():
    rel = (request.args.get("path") or "").replace("\\", "/").strip()
    path = resolve_doc(rel)
    if not path:
        return fail("非法路徑（只放行 docs/、.claude/skills/ 底下的 .md，以及根目錄的 README.md）", 400)
    if not os.path.isfile(path):
        return fail(f"找不到檔案：{rel}", 404)
    size = os.path.getsize(path)
    if size > _MAX_BYTES:
        return fail(f"檔案過大（{size // 1024} KB），請直接開檔", 413)
    text = open(path, encoding="utf-8", errors="replace").read()
    return ok(path=rel_to_repo(path), text=text, lines=text.count("\n") + 1,
              mtime=os.path.getmtime(path), bytes=size)
