"""Page Object 索引：用 ast 掃出各產品可用的頁面類別與方法簽章。

用途：動線 D（需求 → 案例 → 可執行實作）的**產碼護欄** ——
      生成器只能呼叫這份清單裡真的存在的方法，不准自由發明 API。
      這是規則式生成器產出的碼「跑得起來」的主要保障（另一道是寫檔後的 --collect-only）。
使用方式：
    from core.pom_index import build_pom_index
    idx = build_pom_index()          # {product: {module, classes:[{name, methods:[{name, args, doc}]}]}}
    python -m core.pom_index         # 印出摘要
前置條件：
    · 純靜態解析（ast），**不 import 任何產品模組** —— import 會拉起 playwright 等相依，
      而且產品程式碼本來就可能有 side effect。
    · 只收公開方法（不以 _ 開頭），略過 __init__ 之外的 dunder。
    · 結果快取在 cache/pom_index.json，以來源檔的 mtime 總和當版本鍵。
"""
from __future__ import annotations

import ast
import glob
import os
import re
import sys

from core.jsonio import read_json, write_json_atomic
from core.paths import CACHE_DIR, REPO_ROOT, rel_to_repo

CACHE = os.path.join(CACHE_DIR, "pom_index.json")

# 產品 → POM 根目錄（沿用 CLAUDE.md §8.3 的命名規則 tools/<專案>_qa/）
def pom_roots() -> dict:
    """產品 slug → POM 目錄（`tools/<slug>_qa/pages`）。

    ⛔ **不可寫死** —— 這裡原本硬編 crux／wbot／qixing 三個產品，於是同事用
       `new_product.py` 接的產品（它明明會建 `tools/<slug>_qa/pages/`）
       **永遠掃不到**，「撰寫案例」整條動線對新產品是空的
       （2026-08-23 走查「測試工程師的一天」發現）。

    ⚠️ 命名慣例來自 CLAUDE.md：`tools/<專案>_qa/` 是該產品的專屬路徑，
       而 slug 就是 `new_product.py` 用的 skill 名。
    """
    try:
        from core.registry import get_registry
        return {p["id"]: "tools/%s_qa/pages" % p["id"]
                for p in get_registry().products if not p.get("virtual") and p.get("id")}
    except Exception:                       # noqa: BLE001 —— 取不到就回空，不讓整個索引掛掉
        return {}


def _args_of(fn: ast.FunctionDef) -> list[str]:
    out = []
    a = fn.args
    for arg in a.posonlyargs + a.args:
        if arg.arg == "self":
            continue
        out.append(arg.arg)
    if a.vararg:
        out.append("*" + a.vararg.arg)
    for arg in a.kwonlyargs:
        out.append(arg.arg + "=")
    if a.kwarg:
        out.append("**" + a.kwarg.arg)
    return out


def _first_line(node) -> str:
    doc = ast.get_docstring(node) or ""
    return doc.strip().splitlines()[0].strip() if doc else ""


def scan_file(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError):
        return []
    classes = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = []
        for m in node.body:
            if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if m.name.startswith("_") and m.name != "__init__":
                continue
            methods.append({"name": m.name, "args": _args_of(m), "doc": _first_line(m),
                            "line": m.lineno, "is_async": isinstance(m, ast.AsyncFunctionDef)})
        if methods:
            classes.append({"name": node.name, "doc": _first_line(node),
                            "bases": [ast.unparse(b) for b in node.bases],
                            "methods": methods, "line": node.lineno})
    return classes


def build_pom_index(refresh: bool = False) -> dict:
    files, stamp = [], 0.0
    for product, root in pom_roots().items():
        for p in sorted(glob.glob(os.path.join(REPO_ROOT, root, "**", "*.py"), recursive=True)):
            if os.path.basename(p) == "__init__.py":
                continue
            files.append((product, p))
            stamp += os.path.getmtime(p)
    key = f"{len(files)}:{stamp:.0f}"
    if not refresh:
        cached = read_json(CACHE)
        if cached and cached.get("key") == key:
            return cached

    out: dict = {"key": key, "products": {}, "total_methods": 0}
    for product, path in files:
        classes = scan_file(path)
        if not classes:
            continue
        rel = rel_to_repo(path)
        # ⚠️ import 路徑要去掉開頭的 `tools.` —— pyproject 的 pythonpath = ["tools", "."]，
        #    測試裡一律寫 `from crux_qa.pages...`，多一層 tools. 會 ImportError。
        mod = re.sub(r"^tools\.", "", rel[:-3].replace("/", "."))
        blk = out["products"].setdefault(product, {"files": [], "class_count": 0, "method_count": 0})
        blk["files"].append({"path": rel, "module": mod, "classes": classes})
        blk["class_count"] += len(classes)
        n = sum(len(c["methods"]) for c in classes)
        blk["method_count"] += n
        out["total_methods"] += n
    write_json_atomic(CACHE, out)
    return out


def flat_methods(product: str, idx: dict | None = None) -> list[dict]:
    """攤平成 [{module, cls, method, args, doc}]，給生成器挑用。"""
    idx = idx or build_pom_index()
    rows = []
    for f in (idx.get("products", {}).get(product) or {}).get("files", []):
        for c in f["classes"]:
            for m in c["methods"]:
                if m["name"] == "__init__":
                    continue
                rows.append({"module": f["module"], "path": f["path"], "cls": c["name"],
                             "method": m["name"], "args": m["args"], "doc": m["doc"]})
    return rows


def main() -> int:
    idx = build_pom_index(refresh=True)
    for pid, blk in idx["products"].items():
        print(f"{pid:8} {len(blk['files']):3} 檔　{blk['class_count']:3} 類　{blk['method_count']:4} 個公開方法")
    print(f"合計 {idx['total_methods']} 個方法")
    for pid in idx["products"]:
        for r in flat_methods(pid, idx)[:3]:
            print(f"  {pid} · {r['cls']}.{r['method']}({', '.join(r['args'])})　{r['doc'][:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
