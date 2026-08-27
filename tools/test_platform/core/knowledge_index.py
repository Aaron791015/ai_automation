"""知識雷達索引：各產品五圈（規格機制／測試案例／缺陷／驗證紀錄／健康度）的數量與正規化值。

用途：Dashboard 知識雷達（放射狀 HUD）與產品頁的唯一資料來源。純掃檔案系統，唯讀、零風險。
使用方式：
    from core.knowledge_index import build_knowledge_index
    idx = build_knowledge_index(cases_by_product=..., bugs=..., todos=...)
    python -m core.knowledge_index --dump
前置條件：
    · 扇形＝產品（等分，不依數量分配 —— 依數量分配會讓七星細到看不見，反而藏起最該被看到的缺口）
    · 弧長＝該產品在該圈相對全域最大值的比例（0~1）；第 5 圈「健康度」為反向（越健康越滿）
    · docs/*/bugs/ 不版控，缺目錄時 present=False（「未建立」而非 0）
    · lint_docs 目前沒有 --json，先解析 stdout 統計 D1~D7 各幾筆（M1 加 --json）。lint 較慢，快取 10 分鐘。
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import time

from core.jsonio import read_json, write_json_atomic
from core.paths import CACHE_DIR, REPO_ROOT, python_exe, rel_to_repo
from core.registry import get_registry

_LINT_LINE = re.compile(r"^\s*(D[1-7])\s")


def _lint_product(pid: str) -> str | None:
    """slug（`lotto`）→ `lint_docs --product` 要的 id（`樂透`）。

    ⛔ 不可硬編 —— 硬編的話新接的產品查不到，`_lint()` 直接回 skipped，
       **知識雷達的 lint 環永遠是空的且不報錯**（2026-08-23 範本驗收）。
       registry 合併了 config/products.json，`product_id` 就是要的值。
    """
    for p in get_registry().products:
        if p.get("id") == pid and not p.get("virtual"):
            return p.get("product_id") or p.get("id")
    return None


_LINT_TTL = 600


def _scan_docs(docs_dir: str, depth: int | None) -> dict:
    ap = os.path.join(REPO_ROOT, docs_dir)
    if not os.path.isdir(ap):
        return {"present": False, "md_files": 0, "md_lines": 0, "source_files": 0, "files": []}
    pattern = os.path.join(ap, "*.md") if depth == 1 or True else os.path.join(ap, "**", "*.md")
    mds = sorted(glob.glob(pattern))
    lines = 0
    files = []
    for p in mds:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
        except OSError:
            n = 0
        lines += n
        files.append({"path": rel_to_repo(p), "name": os.path.basename(p), "lines": n, "mtime": os.path.getmtime(p)})
    src = 0
    for ext in ("*.pdf", "*.docx", "*.xlsx", "*.pptx"):
        src += len(glob.glob(os.path.join(ap, ext)))
    return {"present": True, "md_files": len(mds), "md_lines": lines, "source_files": src, "files": files}


def _scan_reports(bug_product: str | None) -> dict:
    if not bug_product:
        return {"present": False, "reports": 0, "handovers": 0, "delivers": 0}
    base = os.path.join(REPO_ROOT, "docs", bug_product, "bugs")
    if not os.path.isdir(base):
        return {"present": False, "reports": 0, "handovers": 0, "delivers": 0}
    def cnt(sub, pat="*.md"):
        d = os.path.join(base, sub)
        return len(glob.glob(os.path.join(d, pat))) if os.path.isdir(d) else 0
    return {"present": True, "reports": cnt("_reports"), "handovers": cnt("_handover"),
            "delivers": len([d for d in glob.glob(os.path.join(base, "_deliver", "*")) if os.path.isdir(d)])}


def _skill_files(skill: str | None) -> list:
    """產品 skill 的檔案清單（SKILL.md ＋ references/ 底下的 md）。

    ★ 為什麼要列出來：2026-08-24 起平台會自動往意圖對照表補列
      （`kind: skill` 的草稿）。而**寫得進去卻在畫面上看不到，等於沒寫** ——
      27 份驗證報告沒有入口那次就是這樣（見共通交接檔 T24）。
    """
    if not skill:
        return []
    base = os.path.join(REPO_ROOT, ".claude", "skills", skill)
    out = []
    for path in ([os.path.join(base, "SKILL.md")]
                 + sorted(glob.glob(os.path.join(base, "references", "*.md")))):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = sum(1 for _ in f)
        except OSError:
            continue
        # ⛔ 用 `rel_to_repo` 不要手刻 relpath —— 跨磁碟機時 os.path.relpath 會丟
        #    ValueError（`tests/tooling/test_relpath_cross_drive.py` 守著這條）
        out.append({"name": os.path.basename(path), "lines": lines,
                    "mtime": int(os.path.getmtime(path)),
                    "path": rel_to_repo(path)})
    return out


def _skill_rows(skill: str | None) -> int:
    if not skill:
        return 0
    p = os.path.join(REPO_ROOT, ".claude", "skills", skill, "SKILL.md")
    if not os.path.isfile(p):
        return 0
    with open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for ln in f if ln.startswith("| ") and not ln.startswith("| ---"))


def _lint(pid: str) -> dict:
    """{ok, counts:{D1..D7}, cached_at, error}；快取 10 分鐘。"""
    prod = _lint_product(pid)
    if not prod:
        return {"ok": True, "counts": {}, "skipped": True}
    cp = os.path.join(CACHE_DIR, f"lint_{pid}.json")
    c = read_json(cp)
    if c and time.time() - c.get("ts", 0) < _LINT_TTL:
        return c
    counts = {f"D{i}": 0 for i in range(1, 8)}
    try:
        r = subprocess.run([python_exe(), os.path.join(REPO_ROOT, "scripts", "lint_docs.py"), "--product", prod],
                           cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
        for ln in (r.stdout or "").splitlines():
            m = _LINT_LINE.match(ln)
            if m:
                counts[m.group(1)] += 1
        out = {"ok": r.returncode == 0, "counts": counts, "ts": time.time(),
               "cached_at": time.strftime("%H:%M"), "exit": r.returncode}
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "counts": counts, "ts": time.time(), "error": str(e)[:200]}
    write_json_atomic(cp, out)
    return out


def _health(pid: str, lint: dict, todos: dict | None, bugs: dict | None) -> dict:
    """0~100。扣分：D1/D5 各 -15、D3/D4 各 -2、D6 -20、D7 -10；交接檔過期 -15；缺回歸案例比例 ×20。"""
    score = 100
    reasons = []
    c = lint.get("counts", {})
    for k, w in (("D1", 15), ("D5", 15), ("D6", 20), ("D7", 10), ("D2", 5)):
        if c.get(k):
            score -= w * min(c[k], 3)
            reasons.append(f"{k}×{c[k]}")
    for k in ("D3", "D4"):
        if c.get(k):
            score -= 2 * min(c[k], 10)
            reasons.append(f"{k}×{c[k]}")
    if todos:
        lu = todos.get("latest_update")
        if lu:
            try:
                days = (time.time() - time.mktime(time.strptime(lu, "%Y-%m-%d"))) / 86400
                if days > 3:
                    score -= min(15, int(days))
                    reasons.append(f"交接檔 {int(days)} 天未更新")
            except ValueError:
                pass
        if todos.get("blockers"):
            score -= 10
            reasons.append(f"blocker×{len(todos['blockers'])}")
    if bugs and bugs.get("present"):
        act = bugs.get("active", 0)
        nr = (bugs.get("cross_counts") or {}).get("no_regr", 0)
        if act:
            ratio = nr / max(act, 1)
            score -= int(ratio * 20)
            if nr:
                reasons.append(f"缺回歸案例 {nr}/{act}")
        rv = (bugs.get("cross_counts") or {}).get("revisit", 0)
        if rv:
            score -= min(10, rv * 3)
            reasons.append(f"待重驗×{rv}")
    return {"score": max(0, min(100, score)), "reasons": reasons}


def build_knowledge_index(cases_by_product: dict | None = None, bugs: dict | None = None,
                          todos: dict | None = None, *, with_lint: bool = True) -> dict:
    reg = get_registry()
    products = {}
    for p in reg.products:
        # 偽產品（如 `common` 共通）不是產品：沒有 docs_dir／bugs／交接檔可掃，
        # 放進雷達只會多一個永遠空的扇形（2026-08-23 階段 A）
        if p.get("virtual"):
            continue
        pid = p["id"]
        k = p.get("knowledge") or {}
        docs = _scan_docs(k.get("docs_dir", ""), k.get("docs_depth"))
        rep = _scan_reports(k.get("bug_product"))
        cases = (cases_by_product or {}).get(pid) or {}
        b = (bugs or {}).get("products", {}).get(pid) if bugs else None
        t = (todos or {}).get("products", {}).get(pid) if todos else None
        lint = _lint(pid) if with_lint else {"counts": {}, "skipped": True}
        health = _health(pid, lint, t, b)
        products[pid] = {
            "label": p["label"], "color": p.get("color"),
            # 產品 skill 的檔案清單 —— 產品頁的「文件」分頁要列出來且點得開
            "skill_files": _skill_files(k.get("skill")),
            "rings": {
                "spec": {"label": "規格機制", "value": docs["md_files"], "detail": f"{docs['md_files']} 檔 · {docs['md_lines']:,} 行 · {docs['source_files']} 來源檔",
                         "present": docs["present"], "skill_rows": _skill_rows(k.get("skill"))},
                "cases": {"label": "測試案例", "value": cases.get("total", 0),
                          "detail": f"{cases.get('total', 0)} 條 · smoke {cases.get('smoke', 0)} · write {cases.get('write_action', 0)}" if cases else "0 條",
                          "present": bool(cases)},
                "bugs": {"label": "缺陷", "value": (b or {}).get("active", 0) if b else 0,
                         "detail": (f"活躍 {b['active']} · 歸檔 {b['archived']} · 共 {len(b['bugs'])}" if b and b.get("present") else "未建立 bugs/"),
                         "present": bool(b and b.get("present")),
                         "cross": (b or {}).get("cross_counts") if b else None},
                "reports": {"label": "驗證紀錄", "value": rep["reports"] + rep["handovers"],
                            "detail": f"報告 {rep['reports']} · 交接 {rep['handovers']} · 交付 {rep['delivers']}", "present": rep["present"]},
                "health": {"label": "健康度", "value": health["score"], "detail": "、".join(health["reasons"]) or "無扣分項",
                           "present": True, "lint": lint.get("counts"), "reasons": health["reasons"]},
            },
            "docs": docs["files"][:60],
            "todos": {"open": (t or {}).get("open", 0), "blockers": len((t or {}).get("blockers", [])), "latest_update": (t or {}).get("latest_update")} if t else None,
        }
    # 正規化：每圈相對全域最大值；health 直接 /100
    for ring in ("spec", "cases", "bugs", "reports"):
        mx = max((pp["rings"][ring]["value"] for pp in products.values()), default=0) or 1
        for pp in products.values():
            pp["rings"][ring]["norm"] = round(pp["rings"][ring]["value"] / mx, 3)
    for pp in products.values():
        pp["rings"]["health"]["norm"] = round(pp["rings"]["health"]["value"] / 100, 3)
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ring_order": ["spec", "cases", "bugs", "reports", "health"], "products": products}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    from core.bug_index import build_bug_index
    from core.todo_index import build_todo_index
    from collect.case_index import build_or_load
    reg = get_registry()
    cases_by = {}
    for spec in reg.tools.values():
        if spec.kind == "pytest":
            cases_by = build_or_load(spec, allow_background=False).get("by_product", {})
    idx = build_knowledge_index(cases_by, build_bug_index(jira="off"), build_todo_index(), with_lint="--no-lint" not in argv)
    for pid, p in idx["products"].items():
        r = p["rings"]
        print(f"{pid:8} spec={r['spec']['value']:3}({r['spec']['norm']:.2f}) cases={r['cases']['value']:4}({r['cases']['norm']:.2f}) bugs={r['bugs']['value']:3}({r['bugs']['norm']:.2f}) reports={r['reports']['value']:3}({r['reports']['norm']:.2f}) health={r['health']['value']:3}  {r['health']['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
