"""/api/runs/* —— 啟動／停止／單一輪詢端點／歷史／日誌／sync 命令。"""
from __future__ import annotations

from flask import Blueprint, request

from adapters import get_adapter
from core import check_store, run_index, run_store
from core.registry import get_registry
from runner import manager
from web_ui.api import fail, ok

bp = Blueprint("runs", __name__)


@bp.post("/api/runs/start")
def start():
    body = request.get_json(force=True, silent=True) or {}
    reg = get_registry()
    tool_id = body.get("tool_id")
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    spec = reg.tools[tool_id]
    cmd = spec.command(body.get("command_id"))
    if not cmd:
        return fail("未知的命令", 404)
    if cmd.get("mode") != "run":
        return fail("此命令不是 run 型，請用 /api/runs/command")
    params = dict(body.get("params") or {})
    selection = body.get("selection") or []
    ctx = {}
    if spec.kind == "pytest":
        # 讓結果表能顯示中文標題
        idx = get_adapter(spec).list_cases() or {}
        ctx["case_titles"] = {c["nodeid"]: c.get("title") for c in idx.get("flat", [])}
        params["_products"] = manager.products_from_selection(idx.get("flat"), selection)
    else:
        params["_products"] = list(spec.products or ([spec.product] if spec.product else []))
    # case_picker 欄位的值就是 selection（前端另放 body 頂層），合併進 params 讓 validate 看得到
    for f in (cmd.get("params") or {}).get("fields", []):
        if f.get("type") == "case_picker" and selection:
            params[f["key"]] = selection
    try:
        st = manager.start(spec, cmd, params, remark=body.get("remark", ""),
                           selection=selection, profile_id=body.get("profile_id"), ctx=ctx)
    except manager.ConflictError as e:
        return fail(str(e), 409, blocking_run_id=e.blocking_run_id, blocking_tool=e.blocking_tool)
    except ValueError as e:
        return fail(str(e), 400)
    return ok(run_id=st["run_id"], status=st)


@bp.post("/api/runs/command")
def run_command():
    """mode=sync／python_call：同步執行，不建 run 目錄，直接回結果。"""
    body = request.get_json(force=True, silent=True) or {}
    reg = get_registry()
    tool_id = body.get("tool_id")
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    spec = reg.tools[tool_id]
    cmd = spec.command(body.get("command_id"))
    if not cmd:
        return fail("未知的命令", 404)
    if cmd.get("mode") == "run":
        return fail("此命令是 run 型，請用 /api/runs/start")
    ad = get_adapter(spec)
    params = dict(body.get("params") or {})
    # 與 start() 一致地注入虛擬欄位（sync 命令一樣可能用 visible_when 依產品切欄位）
    params.setdefault("_products", list(spec.products or ([spec.product] if spec.product else [])))
    try:
        clean = ad.validate(cmd, params)
        res = ad.run_command(cmd, clean)
    except ValueError as e:
        return fail(str(e), 400)
    # 前置檢查這類 sync 命令的結論要留下來，後續 run 才看得到（見 core/check_store.py）
    # ⭐ cmdline／耗時／工具自己的成敗一起存 —— 回到這一頁時要能完整還原
    #    「上次跑了什麼、跑多久、結果如何」（2026-08-24 走查盲點 ①）。
    rec = check_store.save(
        tool_id, cmd["id"], clean, res.get("result"),
        extra={"cmdline": res.get("cmdline"), "elapsed_ms": res.get("elapsed_ms"),
               "tool_ok": res.get("ok", True), "exit_code": res.get("exit_code"),
               "label": cmd.get("label")})
    # ⚠️ 信封的 `ok` 是「這個請求有沒有成功」，**不是**「工具跑出來的結論好不好」。
    #    兩者混用會出事：verify 有失敗筆數時退出碼是 1，前端 api.js 看到 ok=false 就直接
    #    丟成錯誤 toast，於是**結果表根本不會被渲染** —— 而那張表正是要看的東西。
    #    工具自己的成敗改放 `tool_ok`／`exit_code`。
    payload = {k: v for k, v in res.items() if k != "ok"}
    return ok(**payload, tool_ok=res.get("ok", True), checked_at=rec["at"], check_ok=rec["ok"])


@bp.get("/api/tools/<tool_id>/last-runs")
def last_sync_runs(tool_id):
    """這支工具每個 sync 命令的**最近一次執行**（含完整結果）。

    ★ 存在的理由：sync 命令不建 run 目錄，先前結果離開頁面就沒了 ——
      而它佔 28/33 條命令。工具頁載入時用這支還原結果區。
    """
    if tool_id not in get_registry().tools:
        return fail("未知的工具", 404)
    return ok(last=check_store.latest(tool_id))


@bp.post("/api/runs/preview")
def preview():
    """執行前的預覽：人話摘要 ＋ 命令列（secret 已遮罩）。不執行、不寫檔。

    ⛔ 取代前端原本 JSON.stringify(表單值) 的做法 —— 那會把被 visible_when 隱藏的欄位
       與 secret 明文一起顯示出來（前端 read() 不做條件過濾，後端 validate 才丟棄）。
    """
    from adapters.argv import preview as build_preview
    body = request.get_json(force=True, silent=True) or {}
    reg = get_registry()
    tool_id = body.get("tool_id")
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    spec = reg.tools[tool_id]
    cmd = spec.command(body.get("command_id"))
    if not cmd:
        return fail("未知的命令", 404)
    params = dict(body.get("params") or {})
    selection = body.get("selection") or []
    params.setdefault("_products", _products_for(spec, selection))
    for f in (cmd.get("params") or {}).get("fields", []):
        if f.get("type") == "case_picker" and selection:
            params[f["key"]] = selection
    try:
        clean = get_adapter(spec).validate(cmd, params)
    except ValueError as e:
        return fail(str(e), 400)
    pv = build_preview(spec, cmd, clean)
    gate = check_store.gate_status(spec, cmd)
    return ok(**pv, gate=gate, danger=cmd.get("danger") or spec.danger,
              typed_value=_typed_value(spec, cmd, clean))


def _typed_value(spec, cmd: dict, clean: dict) -> str:
    """require_typed_confirm 要人複誦的字串：由 registry 的 danger.typed_from 指定欄位。"""
    dg = cmd.get("danger") or spec.danger or {}
    key = dg.get("typed_from")
    if key and clean.get(key) not in (None, ""):
        return str(clean[key])
    return spec.id


def _products_for(spec, selection: list) -> list:
    """跨產品工具（pytest）依勾選案例推導；單產品工具就是它自己的產品。"""
    if spec.kind == "pytest":
        idx = get_adapter(spec).list_cases() or {}
        return manager.products_from_selection(idx.get("flat"), selection)
    return list(spec.products or ([spec.product] if spec.product else []))


@bp.get("/api/tools/<tool_id>/checks")
def tool_checks(tool_id):
    """該工具各 sync 命令的最近一次結果 ＋ 每個 run 型命令的 gate 判定（要不要提醒）。"""
    reg = get_registry()
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    spec = reg.tools[tool_id]
    gates = {}
    for c in spec.commands:
        g = check_store.gate_status(spec, c)
        if g:
            gates[c["id"]] = g
    return ok(checks=check_store.latest(tool_id), gates=gates)


@bp.post("/api/runs/stop")
def stop():
    body = request.get_json(force=True, silent=True) or {}
    rid = body.get("run_id")
    if not rid:
        return fail("缺 run_id")
    r = manager.stop(rid, force=bool(body.get("force")), reason=body.get("reason") or "user")
    return ok(**r) if r.get("ok") else fail(r.get("error", "停止失敗"), 400)


@bp.get("/api/runs/active")
def active():
    """★ 單一輪詢端點：不論幾個 run 都只打這一支。含剛結束保留 N 分鐘的。"""
    return ok(runs=manager.active(), server_time=run_store.now_str())


@bp.get("/api/runs/<run_id>")
def get_run(run_id):
    st = run_store.read_status(run_id)
    if not st:
        return fail("找不到 run", 404)
    meta = run_store.read_meta(run_id) or {}
    reg = get_registry()
    spec = reg.tools.get(st.get("tool_id"))
    return ok(status=st, meta=meta, live=manager.is_live(run_id),
              phases=spec.phases if spec else [], metrics_def=spec.run.get("metrics", []) if spec else [],
              stop=spec.stop if spec else {}, tool=spec.public() if spec else None)


@bp.get("/api/runs/<run_id>/logs")
def logs(run_id):
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0
    return ok(**run_store.tail_console(run_id, offset))


@bp.get("/api/runs")
def history():
    limit = min(200, max(1, int(request.args.get("limit", 20))))
    rows = run_index.recent(limit=limit, product=request.args.get("product") or None,
                            tool=request.args.get("tool") or None, status=request.args.get("status") or None,
                            since=request.args.get("since") or None)
    return ok(runs=rows, heat=run_index.hourly_heat(24) if request.args.get("heat") else None)


@bp.get("/api/runs/compare")
def compare():
    """兩個 run 的對比。★ 判準是 `summary.kind` 而不是 tool_id ——

    crux_perf 與 qixing_perf 同為 perf（都在講注數／失敗率／期數），**跨工具本來就該能比**；
    pytest 比 perf 則毫無意義（沒有共同的指標），直接擋掉。
    完整 summary（含 failed_cases）只存在 run_status.json —— run_index 的列已被裁成白名單 7 欄。
    """
    ids = [x for x in (request.args.get("ids") or "").split(",") if x.strip()]
    if len(ids) != 2:
        return fail("請給兩個 run_id（ids=a,b）")
    runs = []
    for rid in ids:
        st = run_store.read_status(rid)
        if not st:
            return fail(f"找不到 run：{rid}", 404)
        runs.append({"status": st, "meta": run_store.read_meta(rid) or {}})
    kinds = [(r["status"].get("summary") or {}).get("kind") for r in runs]
    if not kinds[0] or kinds[0] != kinds[1]:
        return fail(f"兩者的結果型別不同（{kinds[0] or '無'} vs {kinds[1] or '無'}），沒有共同指標可比")
    return ok(kind=kinds[0], runs=[_compare_side(r) for r in runs],
              params=_param_diff(runs), metrics=_metric_diff(runs),
              regression=_regression(runs) if kinds[0] == "pytest" else None)


def _compare_side(r: dict) -> dict:
    st, meta = r["status"], r["meta"]
    return {"run_id": st.get("run_id"), "tool_id": st.get("tool_id"), "tool_name": meta.get("tool_name"),
            "product": meta.get("product"), "command_label": meta.get("command_label"),
            "started_at": st.get("started_at"), "ended_at": st.get("ended_at"),
            "phase": st.get("phase"), "remark": meta.get("remark") or "",
            "summary": st.get("summary") or {}}


def _param_diff(runs: list) -> list:
    """只列**不一樣**的參數 —— 相同的那些不是這次要看的東西。

    ⚠️ 長清單（case_picker 的 selection 動輒數十條 nodeid）要摘要，不能整包丟出去 ——
       對比框是給人一眼看差異的，塞進 26 個 nodeid 就什麼都看不到了。
       改回報「幾條 ＋ 增減了哪幾條」，那才是差異本身。
    """
    a, b = (r["meta"].get("params") or {} for r in runs)
    rows = []
    for k in sorted(set(a) | set(b)):
        if k.startswith("_"):
            continue
        va, vb = a.get(k), b.get(k)
        if va == vb:
            continue
        if isinstance(va, list) or isinstance(vb, list):
            sa, sb = set(va or []), set(vb or [])
            rows.append({"key": k, "a": f"{len(sa)} 項", "b": f"{len(sb)} 項",
                         "added": sorted(sb - sa)[:8], "removed": sorted(sa - sb)[:8],
                         "added_n": len(sb - sa), "removed_n": len(sa - sb)})
        else:
            rows.append({"key": k, "a": va, "b": vb})
    return rows


_SKIP_METRIC = {"kind", "failed_cases", "stop_reason", "partial"}


def _metric_diff(runs: list) -> list:
    a, b = ((r["status"].get("summary") or {}) for r in runs)
    rows = []
    for k in [x for x in a if x not in _SKIP_METRIC] + [x for x in b if x not in _SKIP_METRIC and x not in a]:
        va, vb = a.get(k), b.get(k)
        # ⛔ **指標只能是純量**。summary 裡的嵌套結構（如 `analysis`、
        #    `allure`）不是可比的數值 —— 丟給前端就是一行
        #    「[object Object]」，而且**畫面上真的就長那樣**，沒有任何錯誤。
        #    （2026-08-23 情境 B 走查：執行對比的指標表。）
        #    可讀的摘要已經另有其欄（`analysis_line`）。
        if isinstance(va, (dict, list)) or isinstance(vb, (dict, list)):
            continue
        if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
            rows.append({"key": k, "a": va, "b": vb, "delta": None, "pct": None})
            continue
        rows.append({"key": k, "a": va, "b": vb, "delta": round(vb - va, 4),
                     "pct": round((vb - va) / va * 100, 1) if va else None})
    return rows


def _regression(runs: list) -> dict:
    """三組差異：新壞的（回歸，最該先看）／修好的（修復生效的佐證）／一直壞的。"""
    sa, sb = ((r["status"].get("summary") or {}) for r in runs)
    ca = {c["nodeid"]: c for c in (sa.get("failed_cases") or [])}
    cb = {c["nodeid"]: c for c in (sb.get("failed_cases") or [])}
    return {
        "newly_broken": [cb[k] for k in cb if k not in ca],
        "fixed": [ca[k] for k in ca if k not in cb],
        "still_broken": [cb[k] for k in cb if k in ca],
    }


@bp.get("/api/runs/heat")
def heat():
    return ok(heat=run_index.hourly_heat(int(request.args.get("hours", 24))))
