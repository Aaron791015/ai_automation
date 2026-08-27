"""/api/knowledge、/api/todos、/api/bugs、/api/health、/api/hints —— 態勢感知的資料端點。

knowledge：知識雷達五圈（真的，掃檔案系統）
todos：交接檔待辦（真的）
bugs：本地 Bug × JIRA 交叉狀態（本地真的；JIRA 在 Demo 為快照）
health：直譯器／allure／埠佔用／索引新鮮度／Claude
hints：規則式助手提示
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import time

from flask import Blueprint, request

from collect.case_index import build_or_load
from core import run_index, run_store
from core.bug_index import build_bug_index
from core.claude_probe import probe_claude
from core.config import load_config
from core.jsonio import read_json
from core.knowledge_index import build_knowledge_index
from core.paths import CACHE_DIR, REPO_ROOT, VENV_PYTHON
from core.registry import get_registry
from core.todo_index import build_todo_index
from runner import manager
from web_ui.api import ok

bp = Blueprint("knowledge", __name__)

_memo: dict[str, tuple[float, object]] = {}


def _memoize(key: str, ttl: float, fn):
    now = time.time()
    hit = _memo.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _memo[key] = (now, val)
    return val


def invalidate(*keys: str) -> None:
    """清掉指定的索引快取（不給 key 就全清）。

    ⛔ **每個會改動索引來源的寫入，寫完都要呼叫** ——
       否則人在畫面上看到的是最多 60 秒前的舊資料，
       而「落了檔卻看不到」等於沒落（2026-08-23 實測：回填 JIRA 單號之後
       Bug 列表還是顯示「漏開單」）。
    """
    if not keys:
        _memo.clear()
        return
    for k in keys:
        for cached in [x for x in _memo if x == k or x.startswith(k + ":")]:
            _memo.pop(cached, None)


def _cases_by_product() -> dict:
    reg = get_registry()
    spec = next((t for t in reg.tools.values() if t.kind == "pytest"), None)
    if not spec:
        return {}
    return build_or_load(spec).get("by_product", {})


@bp.get("/api/knowledge")
def knowledge():
    lint = request.args.get("lint", "1") != "0"
    def build():
        return build_knowledge_index(_cases_by_product(), _memoize("bugs", 60, lambda: build_bug_index()),
                                     _memoize("todos", 30, build_todo_index), with_lint=lint)
    return ok(**_memoize(f"knowledge:{lint}", 60, build))


@bp.get("/api/todos")
def todos():
    idx = _memoize("todos", 30, build_todo_index)
    pid = request.args.get("product")
    if pid:
        return ok(product=pid, **(idx["products"].get(pid) or {}))
    return ok(**idx)


@bp.get("/api/bugs")
def bugs():
    refresh = request.args.get("refresh") == "1"
    if refresh:
        _memo.pop("bugs", None)
    idx = _memoize("bugs", 60, lambda: build_bug_index(jira="refresh" if refresh else "cached"))
    pid = request.args.get("product")
    want_slim = request.args.get("slim") == "1"
    if pid:
        p = dict(idx["products"].get(pid) or {})
        if want_slim:
            p["bugs"] = [_slim_bug(b) for b in p.get("bugs", [])]
        return ok(product=pid, jira_source=idx["jira_source"], jira_fetched_at=idx["jira_fetched_at"], **p)
    # 不帶 product：預設剔掉 bugs[]（整包太大）；帶 slim=1 則保留白名單欄位 ——
    # 總覽側欄要四個產品分頁共用一份資料，不能為了列 Bug 就打四次 API。48 筆 × 11 欄，量很小。
    products = {k: ({**p, "bugs": [_slim_bug(b) for b in p.get("bugs", [])]} if want_slim
                    else {k2: v for k2, v in p.items() if k2 != "bugs"})
                for k, p in idx["products"].items()}
    return ok(generated_at=idx["generated_at"], jira_source=idx["jira_source"], jira_fetched_at=idx["jira_fetched_at"], products=products)


#  surface／found 是「複製開單資訊」要用的（介面、發現日）—— 少了它們貼出去的單會缺欄位
_SLIM_BUG_KEYS = ("id", "title", "severity", "status", "status_label", "module", "surface",
                  "found", "reported", "jira", "cross", "archived", "regression", "path")


def _slim_bug(b: dict) -> dict:
    return {k: b.get(k) for k in _SLIM_BUG_KEYS}


# ---------------------------------------------------------------- health
def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _probe_modules(mods: list[str], exe: str | None = None) -> dict:
    """⚠️ `exe` 一定要能指定 —— 不同工具可能跑在不同的 Python 上，
    全部用 .venv 檢查會得到與工具頁相反的答案（2026-08-23）。"""
    code = ("import importlib.util,json,sys;m=json.loads(sys.argv[1]);"
            "print(json.dumps({x: importlib.util.find_spec(x) is not None for x in m}))")
    import json as _j
    try:
        r = subprocess.run([exe or VENV_PYTHON, "-c", code, _j.dumps(mods)], capture_output=True, text=True, timeout=20)
        return _j.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {m: False for m in mods}


def _allure_cli() -> str | None:
    """⚠️ 解析只能有一處 —— 先前這裡與 `adapters/base.py` 的外部指令檢查
    各有一套，同一個畫面上報出 2.43.0 與 2.7.0 兩個版本（2026-08-23 範本驗收）。"""
    from core.allure_cli import find_allure
    return find_allure()


@bp.get("/api/health")
def health():
    def build():
        reg = get_registry()
        # ⚠️ **依工具各自的直譯器分組檢查** —— 不同工具可能跑在不同的 Python 上
        #    （壓測工具宣告 `runtime.executable: "python"`，因為 .venv 沒有
        #    locust／gevent）。全部丟給 .venv 檢查的話，儀表板永遠紅
        #    「缺 gevent, locust」，而工具頁的健康檢查（用對的直譯器）是全綠的 ——
        #    同一個畫面上兩個相反的答案（2026-08-23 路線 1 驗證）。
        from adapters.argv import resolve_exe
        by_exe: dict = {}
        for t_ in reg.tools.values():
            mods = (t_.runtime.get("requires") or {}).get("python_modules") or []
            if not mods:
                continue
            try:
                exe = resolve_exe(t_)
            except Exception:                    # noqa: BLE001
                exe = VENV_PYTHON
            by_exe.setdefault(exe, set()).update(mods)
        need = sorted({m for ms in by_exe.values() for m in ms})
        missing_by_exe = {}
        for exe, mods in by_exe.items():
            have_ = _probe_modules(sorted(mods), exe)
            miss = [m for m in sorted(mods) if not have_.get(m)]
            if miss:
                missing_by_exe[exe] = miss
        missing = sorted({m for ms in missing_by_exe.values() for m in ms})
        spec = next((t for t in reg.tools.values() if t.kind == "pytest"), None)
        idx = build_or_load(spec) if spec else {}
        du = shutil.disk_usage(REPO_ROOT)
        cl = probe_claude()
        checks = [
            {"key": "venv", "label": "工作區 .venv", "ok": os.path.isfile(VENV_PYTHON), "detail": VENV_PYTHON if os.path.isfile(VENV_PYTHON) else "找不到", "hint": "powershell -File scripts\\setup_test_env.ps1"},
            {"key": "modules", "label": "套件完整性", "ok": not missing,
             "detail": ("；".join("%s 缺 %s" % (os.path.basename(e), ", ".join(m))
                                  for e, m in missing_by_exe.items())
                        if missing else f"{len(need)} 個必要套件齊全"),
             # ⚠️ hint 要講**哪一支直譯器**要裝 —— 先前一律叫人裝 .venv，
             #    而壓測工具的套件該裝在系統 Python，照做沒用。
             "hint": ("　".join('"%s" -m pip install %s' % (e, " ".join(m))
                                for e, m in missing_by_exe.items()) if missing else None)},
            {"key": "allure", "label": "allure CLI", "ok": bool(_allure_cli()), "detail": _allure_cli() or "找不到（npm 全域優先）", "hint": "npm i -g allure-commandline" if not _allure_cli() else None},
            # ⚠️ 「更新中」不是故障 —— stale 只代表 tests/ 有變更、待重建，而且它會背景
            #    自動重建。判紅會讓人以為壞了，先前還沒有給任何 hint（2026-08-23）。
            {"key": "cases", "label": "案例索引", "ok": bool(idx.get("count")),
             "detail": f"{idx.get('count', 0)} 條 · {idx.get('generated_at', '—')}"
                       + ("（tests/ 有變更，重建中）" if idx.get("stale") else ""),
             "hint": "到「案例」頁按『↻ 重建索引』可立即更新" if idx.get("stale") else None},
            {"key": "claude", "label": "Claude Code", "ok": cl.get("ok"), "detail": (cl.get("version") or "未找到") + (f" · {cl['auth'].get('email')}" if cl.get("logged_in") else " · 未登入"), "hint": (cl.get("hints") or [None])[0]},
            {"key": "disk", "label": "磁碟餘量", "ok": du.free > 5 * 1024**3, "detail": f"{du.free / 1024**3:.1f} GB 可用", "hint": None},
        ]
        # ⛔ 不可寫死任何產品的控制台 —— 範本裡那些工具不存在，同事會看到
        #    三盞他沒聽過的燈（2026-08-23 範本端到端驗收）。
        #    埠號由各工具在 runtime.legacy_console_port 自己宣告。
        ports = {}
        for t in get_registry().tools.values():
            lp = (t.runtime or {}).get("legacy_console_port")
            if lp:
                ports[t.name or t.id] = _port_in_use(int(lp))
        return {"checks": checks, "ports": ports,
                "score": int(sum(1 for c in checks if c["ok"]) / len(checks) * 100),
                "checked_at": time.strftime("%H:%M:%S")}
    return ok(**_memoize("health", 60, build))


# ---------------------------------------------------------------- hints（規則式）
@bp.get("/api/hints")
def hints():
    out = []
    reg = get_registry()
    # 上次 pytest 失敗 → 只重跑失敗
    for r in run_index.recent(limit=30):
        if r.get("kind") == "pytest" and (r.get("summary") or {}).get("failed"):
            st = run_store.read_status(r["run_id"]) or {}
            fc = (st.get("summary") or {}).get("failed_cases") or []
            if fc:
                out.append({"kind": "rerun_failed", "tone": "warn", "title": f"上次「{r.get('tool_name')}」有 {len(fc)} 條失敗",
                            "action": "只重跑這幾條", "payload": {"tool_id": r["tool_id"], "selection": [c["nodeid"] for c in fc]},
                            "run_id": r["run_id"]})
            break
    # 案例索引過期
    spec = next((t for t in reg.tools.values() if t.kind == "pytest"), None)
    if spec:
        idx = build_or_load(spec)
        if idx.get("stale"):
            out.append({"kind": "rebuild_index", "tone": "info", "title": "案例索引已過期（tests/ 有檔案變更）", "action": "重建索引", "payload": {}})
    # 上次壓測參數一鍵重跑
    for r in run_index.recent(limit=30):
        if r.get("kind") == "cli" and r.get("phase") == "completed":
            meta = run_store.read_meta(r["run_id"]) or {}
            if meta.get("params"):
                out.append({"kind": "rerun_last", "tone": "info", "title": f"「{r.get('tool_name')}」上次參數：{_brief(meta['params'])}",
                            "action": "一鍵重跑", "payload": {"tool_id": r["tool_id"], "command_id": meta.get("command_id"), "params": meta["params"]}})
            break
    # 待重驗
    b = _memoize("bugs", 60, lambda: build_bug_index())
    for pid, p in b["products"].items():
        rv = p.get("cross", {}).get("revisit", [])
        if rv:
            out.append({"kind": "revisit", "tone": "info", "title": f"{pid.upper()} 有 {len(rv)} 張單 JIRA 已完成、本地仍 open：{', '.join(rv[:4])}",
                        "action": "查看", "payload": {"product": pid, "cross": "revisit"}})
    # 缺案例的產品（⛔ 不可寫死某個產品 —— 範本裡那個產品根本不存在，
    #   同事會看到他沒聽過的名字。2026-08-23 範本端到端驗收）
    cb = _cases_by_product()
    for p in reg.products:
        pid = p.get("id")
        if p.get("virtual") or not pid or cb.get(pid):
            continue
        tests_dir = ((p.get("knowledge") or {}).get("tests_prefix")
                     or "tests/%s/" % pid).rstrip("/")
        # ⚠️ 目錄「不存在」與「存在但沒案例」是兩回事 —— new_product 會把目錄建好，
        #    照舊說「不存在」會讓人以為建失敗了（2026-08-23 範本驗收）。
        why = "還沒有案例" if os.path.isdir(os.path.join(REPO_ROOT, tests_dir)) else "目錄不存在"
        out.append({"kind": "gap", "tone": "warn",
                    "title": "%s尚無 UI 測試案例（%s/ %s）"
                             % (p.get("label") or pid, tests_dir, why),
                    "action": "查看產品頁", "payload": {"product": pid}})
    return ok(hints=out[:6])


def _brief(p: dict) -> str:
    keys = [k for k in ("users", "run_time", "lottery", "game_id", "players", "stop_mode") if k in p]
    return "、".join(f"{k}={p[k]}" for k in keys[:3]) or "—"
