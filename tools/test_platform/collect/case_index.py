"""案例索引：呼叫 pytest collect（經 pytest_case_export plugin）→ 標記產品／階段／前置依賴 → 樹狀化 → 快取。

用途：案例瀏覽器、Ctrl+K 搜尋、知識雷達「測試案例」圈的唯一資料來源。
使用方式：
    from collect.case_index import build_or_load, to_tree
    idx = build_or_load(spec)             # 快取新鮮就直接回；過期先回舊的＋stale=True 並背景重建
    idx = build_or_load(spec, refresh=True)
    python -m collect.case_index --rebuild   # 手動重建（唯讀，不執行任何測試）
前置條件：
    · 快取簽章 = 各 watch_globs 檔案的 (mtime_ns, size)；不符即視為過期。
    · Demo 模式且無快取時，退回 demo/cases/ui_tests.raw.json（那是真的 collect 產出，只是預存）。
    · collect 一律 subprocess ＋ timeout；失敗時回退舊快取並保留 stderr 供 UI 顯示。
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict

from core.jsonio import read_json, write_json_atomic
from core.paths import BASE_DIR, CACHE_DIR, REPO_ROOT, python_exe

_lock = threading.Lock()
_rebuilding: set[str] = set()


# ---------------------------------------------------------------- 簽章與路徑
def _cache_path(spec) -> str:
    rel = (spec.cases or {}).get("cache") or f"cache/cases/{spec.id}.json"
    return os.path.join(BASE_DIR, rel)


def _raw_path(spec) -> str:
    return os.path.join(CACHE_DIR, "cases", f"_{spec.id}.raw.json")


def _stderr_path(spec) -> str:
    return os.path.join(CACHE_DIR, "cases", f"_{spec.id}.stderr.txt")


def collect_roots(spec) -> list[str]:
    """collect 的掃描範圍（`cases.roots`）。

    ⚠️ 目錄不存在時要略過 —— pytest 收到不存在的路徑會直接 exit 4，把整包索引弄壞。

    📝 2026-08-23 移除 `demo_extra_roots`（生成測試的沙箱）——
       寫案例現在直接寫進 `tests/<產品>/`，本來就在掃描範圍內。
    """
    cases = spec.cases or {}
    return list(cases.get("roots", ["tests"]))


def compute_signature(watch_globs: list[str]) -> dict:
    sig: dict[str, list[int]] = {}
    for g in watch_globs:
        for p in glob.glob(os.path.join(REPO_ROOT, g), recursive=True):
            if os.path.isfile(p):
                st = os.stat(p)
                sig[os.path.relpath(p, REPO_ROOT).replace("\\", "/")] = [st.st_mtime_ns, st.st_size]
    return sig


# ---------------------------------------------------------------- collect
def run_collect(spec) -> tuple[bool, str]:
    """執行 pytest --collect-only 匯出 raw JSON。回 (ok, stderr_text)。"""
    cases = spec.cases or {}
    out = _raw_path(spec)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    roots = collect_roots(spec)
    throwaway = os.path.join(CACHE_DIR, "collect_alluredir")
    os.makedirs(throwaway, exist_ok=True)
    py = python_exe()
    cmd = [py, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
           "-p", "tools.test_platform.collect.pytest_case_export",
           f"--case-export={out}", f"--alluredir={throwaway}", *roots]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "TEST_PLATFORM_COLLECT": "1", "CRUX_QA_ENV": os.environ.get("CRUX_QA_ENV", "qat")}
    try:
        r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=int(cases.get("collect_timeout_sec", 90)), env=env)
        stderr = (r.stderr or "") + ("\n" + r.stdout[-2000:] if r.returncode not in (0, 5) else "")
    except subprocess.TimeoutExpired as e:
        stderr = f"collect 逾時（{cases.get('collect_timeout_sec', 90)}s）\n{e}"
        return False, stderr
    except OSError as e:
        return False, (f"無法啟動 pytest：{e}\n直譯器：{py}\n"
                       "→ 先跑 scripts\\setup_test_env.ps1 建 .venv 並安裝相依，"
                       "或在 platform_config.local.json 指定其他直譯器")
    with open(_stderr_path(spec), "w", encoding="utf-8") as f:
        f.write(stderr)
    return os.path.isfile(out) and r.returncode in (0, 5), stderr


# ---------------------------------------------------------------- 標記與樹狀化
def _registry_prefixes() -> list[dict]:
    """從 `config/products.json`（經 registry 合併）推導 `tests/<slug>/` → 產品。

    ⭐ 為什麼需要這層：`product_map` 是**人手寫的**，只列得出寫的當下存在的產品。
       同事用 `new_product.py` 接了自己的產品之後，`tests/<slug>/` 沒有人宣告，
       案例會掉進「工作區工具自測（非產品）」—— 而 `ui_tests` 正是隨範本
       出貨的標準內建工具（2026-08-23 範本端到端驗收）。
    """
    try:
        from core.registry import get_registry
        out = []
        for p in get_registry().products:
            if p.get("virtual"):
                continue
            pref = ((p.get("knowledge") or {}).get("tests_prefix")
                    or "tests/%s/" % p.get("id"))
            if pref:
                out.append({"prefix": pref.rstrip("/") + "/",
                            "product": p.get("id"), "kind": "e2e"})
        # 長的前綴先比 —— `tests/wbot/perf/` 要贏過 `tests/wbot/`
        return sorted(out, key=lambda m: -len(m["prefix"]))
    except Exception:                       # noqa: BLE001 —— 推導失敗就退回 common
        return []


def _product_of(file: str, product_map: list[dict]) -> dict:
    # ⚠️ 明確宣告**優先** —— 它們帶著 `kind`／`label`／`needs_browser`／`collapsed`
    #    這些從產品定義推導不出來的細節。
    for m in product_map:
        if file.startswith(m["prefix"]):
            return m
    for m in _registry_prefixes():
        if file.startswith(m["prefix"]):
            return m
    return {"product": "common", "kind": "unknown"}


def _stage_of(file: str, stages: list[dict]) -> dict | None:
    return next((s for s in stages if file == s["path"]), None)


def annotate(raw_cases: list[dict], spec) -> list[dict]:
    cases_cfg = spec.cases or {}
    pmap = cases_cfg.get("product_map", [])
    stages = cases_cfg.get("stages", [])
    rules = cases_cfg.get("prerequisite_rules", [])
    out = []
    for c in raw_cases:
        if "error" in c:
            out.append(c)
            continue
        m = _product_of(c["file"], pmap)
        c = dict(c)
        c["product"] = m.get("product", "common")
        c["kind"] = m.get("kind", "e2e")
        if m.get("needs_browser") is False:
            c["needs_browser"] = False
        st = _stage_of(c["file"], stages)
        c["stage"] = st["id"] if st else None
        c["stage_label"] = st["label"] if st else None
        req = None
        for r in rules:
            if r.get("when_fixture") in c.get("fixtures", []):
                req = r["requires_stage"]
                break
        c["requires_stage"] = req
        c["needs_prereq"] = bool(req) and c["stage"] != req
        out.append(c)
    return out


def _counts(cs: list[dict]) -> dict:
    return {
        "total": len(cs),
        "smoke": sum(1 for c in cs if "smoke" in c.get("markers", [])),
        "write_action": sum(1 for c in cs if "write_action" in c.get("markers", [])),
        "needs_prereq": sum(1 for c in cs if c.get("needs_prereq")),
        "needs_browser": sum(1 for c in cs if c.get("needs_browser")),
    }


def to_tree(cases: list[dict], spec) -> list[dict]:
    """產品 → 檔案 → （檔案內若貼了 allure suite 標籤才分組）→ 案例。

    ⚠️ 2026-08-28 由「產品 → suite → 檔案 → 案例」改成「產品 → 檔案 → suite → 案例」：
    原本 suite 分岔在檔案**之上**，同一檔案有多個子頁面（如 `test_system_setting.py`
    橫跨投注限額／遊戲設置／退水設置…）就會在樹上被拆成好幾支、檔名重複出現好幾次——
    使用者要的是「點開一個檔案，就能看到裡面案例對應哪個子頁面」，不是把檔案本身拆散。
    沒貼 suite 標籤的案例維持原樣（檔案下直接列案例，不多一層）。
    """
    cases_cfg = spec.cases or {}
    pmap = {m["product"]: m for m in cases_cfg.get("product_map", [])}
    by_product: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        if "error" in c:
            continue
        by_product[c["product"]].append(c)

    def leaf(c: dict) -> dict:
        return {"type": "case", "id": c["nodeid"], "label": c["title"], "case": c}

    def group(items: list[dict], keyfn, level_type: str, id_prefix: str) -> list[dict]:
        buckets: dict[str | None, list[dict]] = defaultdict(list)
        order: list[str | None] = []
        for c in items:
            k = keyfn(c)
            if k not in buckets:
                order.append(k)
            buckets[k].append(c)
        nodes = []
        for k in order:
            nodes.append((k, buckets[k]))
        return nodes

    def build_case_groups(fcases: list[dict], id_prefix: str) -> list[dict]:
        """檔案節點底下的案例；有 allure suite／sub_suite 標籤才分組，否則直接列案例。"""
        def lvl(c, k):
            return (c.get("allure") or {}).get(k)
        if all(lvl(c, "suite") is None for c in fcases):
            return [leaf(c) for c in fcases]
        nodes = []
        for suite, scases in group(fcases, lambda c: lvl(c, "suite"), "suite", id_prefix):
            sid = f"{id_prefix}/{suite or '_'}"
            if all(lvl(c, "sub_suite") is None for c in scases):
                children = [leaf(c) for c in scases]
            else:
                children = []
                for sub, subcases in group(scases, lambda c: lvl(c, "sub_suite"), "sub_suite", sid):
                    ssid = f"{sid}/{sub or '_'}"
                    children.append({"type": "sub_suite", "id": ssid, "label": sub or "（未分類）",
                                     "counts": _counts(subcases), "children": [leaf(c) for c in subcases]})
            nodes.append({"type": "suite", "id": sid, "label": suite or "（未分類）",
                          "counts": _counts(scases), "children": children})
        return nodes

    def build_files(items: list[dict], id_prefix: str) -> list[dict]:
        nodes = []
        for fpath, fcases in group(items, lambda c: c["file"], "file", id_prefix):
            stage = fcases[0].get("stage_label")
            fid = f"{id_prefix}/{fpath}"
            nodes.append({
                "type": "file", "id": fid, "label": stage or os.path.basename(fpath),
                "sublabel": fpath if stage else None, "file": fpath,
                "stage": fcases[0].get("stage"), "counts": _counts(fcases),
                "children": build_case_groups(fcases, fid),
            })
        return nodes

    # ⭐ `product_map` 只有少數幾條寫了 `label`（生成骨架那三條、tests/tooling），
    #    其餘沒寫的先前直接退回 slug —— 於是樹上出現 `crux`／`wbot`，
    #    而同一頁的篩選下拉、工具看板、產品頁都是「CRUX」「投注機器人」
    #    （2026-08-24 走查）。⛔ 不要在 product_map 逐條補 label：那是把產品名
    #    複製第二份，正是「產品定義單一來源」要消滅的東西 —— 改成回註冊表問。
    labels = {}
    try:
        from core.registry import get_registry      # 延後 import，避免載入期循環
        labels = {p["id"]: p.get("label") or p["id"] for p in get_registry().products}
    except Exception:                               # noqa: BLE001
        labels = {}

    tree = []
    for pid, pcases in sorted(by_product.items(), key=lambda kv: kv[0]):
        m = pmap.get(pid, {})
        tree.append({
            "type": "product", "id": pid,
            "label": m.get("label") or labels.get(pid) or pid, "product": pid,
            "collapsed": bool(m.get("collapsed")), "counts": _counts(pcases),
            "children": build_files(pcases, pid),
        })
    # 產品順序：crux, wbot, qixing, common（common 收合在最後）
    order = {"crux": 0, "wbot": 1, "qixing": 2, "common": 9}
    tree.sort(key=lambda n: order.get(n["id"], 5))
    return tree


# ---------------------------------------------------------------- 主流程
def _assemble(spec, raw: dict, sig: dict) -> dict:
    cases = annotate(raw.get("cases", []), spec)
    return {
        "tool_id": spec.id,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "signature": sig,
        "count": len([c for c in cases if "error" not in c]),
        "errors": [c for c in cases if "error" in c],
        "counts": _counts([c for c in cases if "error" not in c]),
        "by_product": {p: _counts([c for c in cases if c.get("product") == p])
                       for p in sorted({c.get("product") for c in cases if "error" not in c})},
        "stages": (spec.cases or {}).get("stages", []),
        "flat": cases,
        "tree": to_tree(cases, spec),
    }


def rebuild(spec, sig: dict | None = None) -> dict:
    sig = sig if sig is not None else compute_signature((spec.cases or {}).get("watch_globs", []))
    ok, stderr = run_collect(spec)
    raw = read_json(_raw_path(spec)) if ok else None
    if not raw:
        # collect 失敗時沿用上一次的快取並標 stale —— 索引壞掉不該讓整個案例頁空白，
        # 但要讓人看得出「這是舊的」。
        # 📝 2026-08-23 移除其後的 demo 快照 fallback（`demo/cases/ui_tests.raw.json`）。
        old = read_json(_cache_path(spec))
        if old:
            old["stale"] = True
            old["collect_error"] = stderr[-3000:]
            return old
        return {"tool_id": spec.id, "count": 0, "flat": [], "tree": [], "stale": True,
                "collect_error": stderr[-3000:], "counts": _counts([]), "by_product": {}, "stages": []}
    idx = _assemble(spec, raw, sig)
    idx["stale"] = False
    write_json_atomic(_cache_path(spec), idx)
    return idx


def _bg_rebuild(spec, sig: dict) -> None:
    try:
        rebuild(spec, sig)
    finally:
        with _lock:
            _rebuilding.discard(spec.id)


def build_or_load(spec, *, refresh: bool = False, allow_background: bool = True) -> dict:
    cache = read_json(_cache_path(spec))
    sig = compute_signature((spec.cases or {}).get("watch_globs", []))
    if cache and not refresh and cache.get("signature") == sig:
        cache["stale"] = False
        return cache
    if cache and not refresh and allow_background:
        with _lock:
            if spec.id not in _rebuilding:
                _rebuilding.add(spec.id)
                threading.Thread(target=_bg_rebuild, args=(spec, sig), daemon=True).start()
        cache["stale"] = True
        return cache
    return rebuild(spec, sig)


def main(argv: list[str] | None = None) -> int:
    from core.registry import get_registry
    argv = argv if argv is not None else sys.argv[1:]
    reg = get_registry()
    for spec in reg.tools.values():
        if spec.kind != "pytest":
            continue
        idx = rebuild(spec) if "--rebuild" in argv else build_or_load(spec, allow_background=False)
        print(f"{spec.id}: {idx.get('count')} 案例 stale={idx.get('stale')} by_product={idx.get('by_product')}")
        if idx.get("collect_error"):
            print("  collect_error:", idx["collect_error"][:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
