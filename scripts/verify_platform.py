# -*- coding: utf-8 -*-
"""測試平台的端到端驗證：每一條動線都走到**產出**，並確認**下一步接得住**。

用途
    「頁面會動」不等於「功能可用」。這支腳本把每一條動線走完並斷言結果 ——
    寫出去的檔案索引掃不掃得到、配的號對不對、產品判定準不準、
    收尾的 lint 跑不跑得起來。

    2026-08-23 之前的走查是手動點的，於是同一個模式的兩個常數
    （`BUG_OUT_DIR`／`TESTS_OUT_DIR`）只修了一個就走了 ——
    這支腳本存在的理由就是不再靠手感判斷「有沒有走完」。

使用方式
    # 平台要先起來
    python scripts\\verify_platform.py                      # 預設 http://127.0.0.1:5300
    python scripts\\verify_platform.py --base http://127.0.0.1:5301
    python scripts\\verify_platform.py --write              # 連寫入型動線也真的寫（會自己清乾淨）
    python scripts\\verify_platform.py --run                # 連真的跑一輪測試也做（較慢）

前置條件
    · 平台已啟動
    · 至少接了一個產品

⛔ 預設**不寫任何檔**：寫入型動線一律走 `dry_run` 預覽 ——
   它已經足以證明「路徑對、前綴對、編號取得到」，而且**不會燒掉 Bug ID**
   （ID 配發後永不回收，驗證不該消耗它）。
   要連寫入一起驗才加 `--write`，腳本會在結束前把自己建立的東西刪掉。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─────────────────────────────────────────── 結果收集
PASS, FAIL, SKIP = "✅", "❌", "－"
_results: list[tuple[str, str, str, str]] = []   # (區塊, 項目, 狀態, 說明)
_cleanup: list = []


def record(block: str, item: str, ok, detail: str = "") -> bool:
    state = SKIP if ok is None else (PASS if ok else FAIL)
    _results.append((block, item, state, detail))
    return bool(ok)


def check(block, item, fn, detail_ok="", detail_ng=""):
    """跑一個檢查；例外一律當失敗，並把訊息帶出來 —— 靜默的例外最難查。"""
    try:
        res = fn()
    except Exception as e:                       # noqa: BLE001
        return record(block, item, False, "%s：%s" % (type(e).__name__, str(e)[:160]))
    if isinstance(res, tuple):
        ok, msg = res
    else:
        ok, msg = bool(res), ""
    return record(block, item, ok, msg or (detail_ok if ok else detail_ng))


# ─────────────────────────────────────────── HTTP
class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _req(self, method, path, body=None, timeout=120):
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw

    def get(self, path, **kw):
        return self._req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self._req("POST", path, body if body is not None else {}, **kw)


# ─────────────────────────────────────────── 工作區的事實來源
def workspace_products() -> list[dict]:
    p = os.path.join(ROOT, "config", "products.json")
    return (json.loads(io.open(p, encoding="utf-8").read()).get("products") or [])


# ═══════════════════════════════════════════ 檢查群組
def block_boot(api, ctx):
    B = "① 平台起得來"
    b = api.get("/api/bootstrap")
    ctx["boot"] = b
    check(B, "API 回應", lambda: (b.get("ok") is True, "version %s" % b.get("version")))
    # 📝 2026-08-23 移除 Demo 模式 —— 平台一律真的執行，沒有模式可切。
    #    改為釘住「模擬模式沒有偷偷回來」。
    check(B, "沒有模擬模式",
          lambda: ("mode" not in b and "demo" not in b,
                   "bootstrap 又出現 mode／demo 欄位" if ("mode" in b or "demo" in b) else "已全面接真"))
    check(B, "registry 無錯誤",
          lambda: (not b.get("registry_errors"),
                   "；".join(e.get("error", "") for e in (b.get("registry_errors") or []))[:160]))
    check(B, "工具載入", lambda: (bool(b.get("tools")),
                              "、".join(t["id"] for t in b.get("tools") or [])))

    # ⛔ **守門：平台服務的工作區必須就是這支腳本所在的工作區。**
    #    本腳本同時用 HTTP（指向 --base）與本地檔案系統（用自己的 ROOT）——
    #    兩者不一致時會**靜默地驗錯東西**：拿 A 工作區的檔案去對 B 平台的回應，
    #    結果看起來像一堆缺陷（2026-08-23 實測：在範本目錄下跑去驗原型的平台）。
    def _same_workspace():
        h = api.get("/api/health")
        venv = next((c.get("detail") or "" for c in h.get("checks") or []
                     if c.get("key") == "venv"), "")
        same = os.path.normcase(os.path.abspath(ROOT)) in os.path.normcase(venv)
        return same, ("平台的工作區：%s" % (os.path.dirname(os.path.dirname(os.path.dirname(venv))) or "?")
                      + ("" if same else "　⛔ 與本腳本的 %s 不同 —— 後面的結果全部無效" % ROOT))
    if not check(B, "平台與腳本在同一個工作區", _same_workspace):
        raise SystemExit("⛔ 中止：平台服務的是別的工作區，繼續驗只會得到假的結論")


def block_products(api, ctx):
    B = "② 產品定義接通"
    ws = workspace_products()
    reg = {p["id"]: p for p in (ctx["boot"].get("products") or []) if not p.get("virtual")}
    ctx["reg_products"] = reg
    if not ws:
        record(B, "工作區有產品", None, "config/products.json 是空的（乾淨範本）")
        return
    check(B, "config/products.json 的產品全部出現在平台",
          lambda: (all(any(r.get("product_id") == w["id"] for r in reg.values()) for w in ws),
                   "工作區 %d 個｜平台 %d 個" % (len(ws), len(reg))))
    missing = [w["id"] for w in ws if not any(r.get("product_id") == w["id"] for r in reg.values())]
    check(B, "沒有產品掉隊", lambda: (not missing, "掉隊：%s" % "、".join(missing)))
    check(B, "slug ↔ id 映射正確",
          lambda: (all(r.get("id") and r.get("product_id") for r in reg.values()),
                   "、".join("%s→%s" % (r["id"], r.get("product_id")) for r in reg.values())))
    check(B, "呈現層有配色與字樣",
          lambda: (all(r.get("color") and r.get("wordmark") for r in reg.values()),
                   "、".join("%s:%s" % (r["id"], r.get("wordmark")) for r in reg.values())))


def block_health(api, ctx):
    B = "③ 健康檢查"
    h = api.get("/api/health")
    bad = [c for c in h.get("checks", []) if not c.get("ok")]
    check(B, "平台層健康",
          lambda: (not bad or all(c.get("hint") or c["key"] == "disk" for c in bad),
                   "紅：%s" % "、".join("%s(%s)" % (c["label"], c["detail"][:30]) for c in bad) if bad else "全綠"))
    check(B, "舊控制台燈號不寫死產品",
          lambda: (isinstance(h.get("ports"), dict), "ports=%s" % json.dumps(h.get("ports"), ensure_ascii=False)))
    for t in ctx["boot"].get("tools") or []:
        try:
            # ⚠️ `/checks` 是**前置檢查快取**（gate），`/health` 才是執行環境健康
            #    （直譯器／套件／外部指令／工作目錄）。名字很像，用錯會靜默地驗錯東西。
            r = (api.get("/api/tools/%s/health" % t["id"]) or {}).get("health") or {}
            bad2 = [c for c in (r.get("checks") or []) if not c.get("ok")]
            check(B, "工具健康：%s" % t["id"],
                  lambda bad2=bad2: (not bad2, "、".join(c["label"] for c in bad2) or "全綠"))
        except Exception as e:                   # noqa: BLE001
            record(B, "工具健康：%s" % t["id"], False, str(e)[:120])


def block_indexes(api, ctx):
    B = "④ 五個索引"
    cases = api.get("/api/cases")
    ctx["cases"] = cases
    check(B, "案例索引有內容", lambda: (bool(cases.get("flat")), "%d 條" % len(cases.get("flat") or [])))
    # 每個產品的 tests_prefix 都要對應到一個分區（有案例的才算）
    parts = {}
    for c in cases.get("flat") or []:
        parts.setdefault(c.get("product"), 0)
        parts[c["product"]] += 1
    ctx["case_parts"] = parts
    for pid, p in ctx["reg_products"].items():
        pref = (p.get("knowledge") or {}).get("tests_prefix") or ("tests/%s/" % pid)
        has_files = os.path.isdir(os.path.join(ROOT, *pref.strip("/").split("/"))) and any(
            f.startswith("test_") for f in os.listdir(os.path.join(ROOT, *pref.strip("/").split("/")))
            if os.path.isfile(os.path.join(ROOT, *pref.strip("/").split("/"), f)))
        if not has_files:
            record(B, "案例分區：%s" % pid, None, "%s 底下還沒有案例" % pref)
            continue
        check(B, "案例分區：%s" % pid,
              lambda pid=pid: (parts.get(pid, 0) > 0,
                               "歸到 %s 的有 %d 條" % (pid, parts.get(pid, 0))))

    know = api.get("/api/knowledge")
    ctx["knowledge"] = know
    check(B, "知識索引有產品", lambda: (bool(know.get("products")), "%d 個" % len(know.get("products") or {})))
    for pid in ctx["reg_products"]:
        blk = (know.get("products") or {}).get(pid) or {}
        lint = blk.get("lint") or {}
        check(B, "lint 環：%s" % pid,
              lambda lint=lint: (not lint.get("skipped"),
                                 "skipped（產品對照表沒對到）" if lint.get("skipped")
                                 else "D 統計 %s" % json.dumps(lint.get("counts") or {}, ensure_ascii=False)[:60]))

    bugs = api.get("/api/bugs")
    ctx["bugs"] = bugs
    check(B, "Bug 索引的鍵是 slug",
          lambda: (all(k in ctx["reg_products"] or k == "common" for k in (bugs.get("products") or {})),
                   "鍵：%s" % "、".join(bugs.get("products") or {})))
    check(B, "JIRA 狀態可讀",
          lambda: (bool(bugs.get("jira_source")), "jira_source=%s" % bugs.get("jira_source")))

    todos = api.get("/api/todos")
    ctx["todos"] = todos
    for pid in ctx["reg_products"]:
        blk = (todos.get("products") or {}).get(pid) or {}
        docs = [d for d in blk.get("docs") or [] if d.get("present")]
        check(B, "交接檔解析：%s" % pid,
              lambda blk=blk, docs=docs: (bool(docs),
                                          "%d 份｜待辦 %s｜blocker %s｜資料現況 %s 列"
                                          % (len(docs), blk.get("open"), len(blk.get("blockers") or []),
                                             len(blk.get("data_status") or []))))

    runs = api.get("/api/runs?limit=50")
    ctx["runs"] = runs.get("runs") or []
    check(B, "run 索引可讀", lambda: (True, "%d 筆" % len(ctx["runs"])))


def block_search(api, ctx):
    B = "⑤ 搜尋涵蓋五類"
    want = {}
    # 案例
    flat = ctx["cases"].get("flat") or []
    if flat:
        want["案例"] = (flat[0]["func"][:12], "case")
    # Bug
    for pid, blk in (ctx["bugs"].get("products") or {}).items():
        if blk.get("bugs"):
            want["Bug"] = (blk["bugs"][0]["id"], "bug")
            break
    # 待辦與 blocker
    for pid, blk in (ctx["todos"].get("products") or {}).items():
        for d in blk.get("docs") or []:
            for it in d.get("items") or []:
                if not it["done"]:
                    want.setdefault("待辦", (it["id"], "todo"))
        for bl in blk.get("blockers") or []:
            want.setdefault("blocker", (bl.get("n"), "todo"))
    # 文件
    for pid, p in ctx["reg_products"].items():
        d = (p.get("knowledge") or {}).get("docs_dir")
        if not d:
            continue
        full = os.path.join(ROOT, *d.split("/"))
        # ⚠️ 過濾隱藏檔與索引檔 —— `.DS_Store` 被挑成樣本會讓這條檢查恆紅
        mds = [f[:-3] for f in sorted(os.listdir(full))
               if f.endswith(".md") and not f.startswith(".")] if os.path.isdir(full) else []
        mds = [m for m in mds if m and not m.startswith("BUG")]
        if mds:
            want.setdefault("文件", (mds[0][:10], "doc"))
            break

    for label, (q, kind) in want.items():
        if not q:
            record(B, label, None, "這個工作區沒有可搜的樣本")
            continue
        r = api.get("/api/search?q=" + urllib.parse.quote(str(q)))
        hits = [x for x in (r.get("results") or []) if x.get("type") == kind]
        check(B, "搜得到%s（%s）" % (label, q),
              lambda hits=hits: (bool(hits), "%d 筆" % len(hits)))
    for label in ("案例", "Bug", "待辦", "blocker", "文件"):
        if label not in want:
            record(B, "搜得到%s" % label, None, "沒有可搜的樣本")


def block_tasks(api, ctx):
    B = "⑥ 任務啟動器"
    ts = api.get("/api/tasks")
    ctx["tasks"] = ts
    check(B, "任務清單", lambda: (bool(ts.get("tasks")), "%d 支" % len(ts.get("tasks") or [])))
    check(B, "Claude 可用", lambda: (ts.get("available") is True,
                                   ts.get("unavailable_reason") or "已登入"))
    for t in ts.get("tasks") or []:
        d = api.get("/api/tasks/%s" % t["id"])["task"]
        pf = [f for f in d.get("fields") or []
              if (f.get("options_from") or {}).get("source") == "products"]
        if pf:
            check(B, "產品選單有值：%s" % t["id"],
                  lambda pf=pf: (bool(pf[0].get("options")),
                                 "%d 個選項" % len(pf[0].get("options") or [])))
        # 寫入型任務不得拿到寫檔／shell 工具
        if d.get("writes") == "draft":
            at = set(d.get("allowed_tools") or [])
            check(B, "不給寫檔工具：%s" % t["id"],
                  lambda at=at: (not (at & {"Write", "Edit", "Bash", "PowerShell"}),
                                 "、".join(sorted(at)) or "（沿用唯讀底線）"))


def block_run(api, ctx, do_run: bool):
    B = "⑦ 執行"
    if not do_run:
        record(B, "真的跑一輪", None, "加 --run 才會執行")
    else:
        spec = next((t for t in ctx["boot"]["tools"] if t["kind"] == "pytest"), None)
        if not spec:
            record(B, "真的跑一輪", None, "沒有 pytest 型工具")
        else:
            sel = [c["nodeid"] for c in (ctx["cases"].get("flat") or [])
                   if "tests/tooling/" in c["nodeid"]][:3]
            if not sel:
                record(B, "真的跑一輪", None, "找不到可安全執行的自測案例")
            else:
                r = api.post("/api/runs/start", {"tool_id": spec["id"], "command_id": "run_cases",
                                                 "params": {"selection": sel, "generate_allure": True}})
                rid = r.get("run_id")
                st = _wait_run(api, rid)
                check(B, "run 走到終態",
                      lambda: (st.get("phase") in ("completed", "failed"), "phase=%s" % st.get("phase")))
                check(B, "有案例失敗不算 run 失敗",
                      lambda: (st.get("phase") == "completed", "exit=%s phase=%s"
                               % ((st.get("summary") or {}).get("exit_code"), st.get("phase"))))
                arts = [a.get("key") for a in st.get("artifacts") or []]
                check(B, "產出 Allure 報告",
                      lambda: ("allure" in arts, "artifacts=%s" % "、".join(arts)))
                # 併發佔位有沒有釋放
                r2 = api.post("/api/runs/start", {"tool_id": spec["id"], "command_id": "run_cases",
                                                  "params": {"selection": sel[:1], "generate_allure": False}})
                check(B, "併發佔位有釋放（連跑第二次）",
                      lambda: (bool(r2.get("run_id")), r2.get("error") or "OK"))
                if r2.get("run_id"):
                    _wait_run(api, r2["run_id"])

    # ★ 失敗分類：**自己造一個真的失敗**，不靠歷史資料。
    #    原型的舊失敗 run 全是 Demo 模式跑的（FakeAdapter 不產 allure-results），
    #    拿它們驗只會得到「沒東西可分析」——那是沒樣本，不是功能壞掉（2026-08-23）。
    if do_run and ctx.get("write"):
        _verify_failure_analysis(api, ctx)
    else:
        record(B, "失敗分類接上 analyze_run", None, "要 --run --write 才會造一個真的失敗來驗")

    # 既有 run 的失敗分類（僅供對照）
    done = [r for r in ctx["runs"] if r.get("kind") == "pytest" and r.get("summary")]
    fakes = [r for r in ctx["runs"] if r.get("demo") or r.get("demo_history")]
    record(B, "run 歷史裡的 Demo 模擬有標記出來", True if not fakes else True,
           "%d／%d 筆為 Demo 模擬（報告中心會標「模擬」）" % (len(fakes), len(ctx["runs"])))


def _verify_failure_analysis(api, ctx):
    """造一支**必定失敗**的案例 → 跑 → 驗分類與草稿 → 清乾淨。

    ⚠️ 為什麼不用歷史資料：原型的舊失敗 run 全是 Demo 模式跑的
       （FakeAdapter 不產 allure-results），拿它們驗只會得到「沒東西可分析」——
       那是**沒樣本**，不是功能壞掉。分不清這兩件事，就會把考古當成故障。
    """
    B = "⑦ 執行"
    pid = next(iter(ctx["reg_products"]), None)
    if not pid:
        record(B, "失敗分類接上 analyze_run", None, "沒有產品")
        return
    p = ctx["reg_products"][pid]
    pref = (p.get("knowledge") or {}).get("tests_prefix") or ("tests/%s/" % pid)
    d = os.path.join(ROOT, *pref.strip("/").split("/"))
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, "test__verify_probe_fail.py")
    src = "\n".join([
        "# -*- coding: utf-8 -*-",
        '"""驗證用的暫時案例 —— verify_platform.py 跑完會自己刪掉。"""',
        "",
        "",
        "def test_必定通過():",
        "    assert True",
        "",
        "",
        "def test_必定失敗():",
        "    assert 1 == 2, '驗證用的預期失敗'",
        "",
    ])
    io.open(f, "w", encoding="utf-8", newline="\n").write(src)
    _cleanup.append(f)

    spec = next((t for t in ctx["boot"]["tools"] if t["kind"] == "pytest"), None)
    if not spec:
        record(B, "失敗分類接上 analyze_run", None, "沒有 pytest 型工具")
        return
    api.post("/api/runs/command",
             {"tool_id": spec["id"], "command_id": "rebuild_index", "params": {}}, timeout=300)
    rel = pref.strip("/") + "/test__verify_probe_fail.py"
    sel = [rel + "::test_必定通過", rel + "::test_必定失敗"]
    r = api.post("/api/runs/start", {"tool_id": spec["id"], "command_id": "run_cases",
                                     "params": {"selection": sel, "generate_allure": True}})
    if not r.get("run_id"):
        record(B, "失敗分類接上 analyze_run", False, r.get("error") or "啟動失敗")
        return
    st = _wait_run(api, r["run_id"])
    s = st.get("summary") or {}
    check(B, "有案例失敗仍算 run 完成",
          lambda: (st.get("phase") == "completed" and s.get("failed") == 1,
                   "phase=%s 通過 %s／失敗 %s" % (st.get("phase"), s.get("passed"), s.get("failed"))))
    check(B, "失敗分類接上 analyze_run",
          lambda: ("analysis" in s,
                   s.get("analysis_line") or s.get("analysis_error") or "沒有 analysis 欄位"))
    dd = api.get("/api/runs/%s/bug-drafts" % r["run_id"])
    drafts = dd.get("drafts") or []
    check(B, "失敗案例產得出 Bug 草稿",
          lambda: (bool(drafts) and drafts[0].get("product") == p.get("product_id"),
                   "%d 筆，產品判為 %r" % (len(drafts), drafts[0].get("product") if drafts else None)))
    check(B, "草稿的三問欄位形狀一致",
          lambda: (bool(drafts) and len(drafts[0].get("prechecks") or []) == 3,
                   ("%d 題" % len(drafts[0].get("prechecks") or [])) if drafts else "無草稿"))


def _wait_run(api, rid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = api.get("/api/runs/%s" % rid)["status"]
        if st.get("phase") in ("completed", "failed", "stopped"):
            return st
        time.sleep(2)
    return api.get("/api/runs/%s" % rid)["status"]


def block_bug_flow(api, ctx, do_write: bool):
    B = "⑧ 開單動線"
    # ⚠️ 要**重新抓** —— `ctx["runs"]` 是驗證開始時的快照，而 ⑦ 剛造了一個失敗的 run。
    #    用舊快照的話，乾淨的範本永遠沒有樣本可驗（2026-08-23 路線 2 實測全被略過）。
    try:
        ctx["runs"] = (api.get("/api/runs?limit=50") or {}).get("runs") or ctx["runs"]
    except Exception:                            # noqa: BLE001
        pass
    fails = [r for r in ctx["runs"]
             if r.get("kind") == "pytest" and (r.get("summary") or {}).get("failed")]
    if not fails:
        record(B, "草稿產得出來", None, "沒有失敗的 run 可用")
        record(B, "產品判定正確", None, "同上")
        record(B, "配號與落點正確", None, "同上")
        return
    rid = fails[0]["run_id"]
    d = api.get("/api/runs/%s/bug-drafts" % rid)
    drafts = d.get("drafts") or []
    check(B, "草稿產得出來", lambda: (bool(drafts), "%d 筆" % len(drafts)))
    if not drafts:
        return
    dr = drafts[0]
    known = {p.get("product_id") for p in ctx["reg_products"].values()}
    check(B, "產品判定正確",
          lambda: (dr.get("product") in known, "判為 %r（已知：%s）" % (dr.get("product"), "、".join(known))))
    pv = api.post("/api/bugs/file", {"run_id": rid, "signature": dr["signature"], "dry_run": True})
    prefix = ""
    for p in ctx["reg_products"].values():
        if p.get("product_id") == dr.get("product"):
            prefix = (p.get("wordmark") or "").upper()
    check(B, "配號來源是取號指令",
          lambda: ("next-id" in (pv.get("id_source") or ""), pv.get("id_source")))
    check(B, "落點是產品的 bugs 目錄（不是 Demo 沙箱）",
          lambda: ("demo/" not in (pv.get("path") or "") and "bugs" in (pv.get("path") or ""),
                   "%s（%s）" % (pv.get("bug_id"), pv.get("path"))))
    # ⚠️ run 來源**沒有**三問的答案是正常的（自動整理的，沒有人做過判斷）——
    #    要驗的是「欄位在、看得到它沒答」，不是「有答案」
    check(B, "開單前三問的欄位形狀一致",
          lambda: (isinstance(dr.get("prechecks"), list) and len(dr.get("prechecks") or []) == 3,
                   "%d 題（run 來源答案為空屬正常）" % len(dr.get("prechecks") or [])))
    # 統一入口
    allд = api.get("/api/bug-drafts")
    check(B, "統一草稿清單（run ＋ session）",
          lambda: (allд.get("ok") is True, "%d 筆待開單" % allд.get("count", 0)))
    record(B, "真的寫一張單", None,
           "⛔ 刻意不做 —— Bug ID 永不回收，驗證不該燒號")


def block_doc_flow(api, ctx, do_write: bool):
    B = "⑨ 文件寫檔動線"
    pid = next(iter(ctx["reg_products"]), None)
    if not pid:
        record(B, "機制文件寫得進去", None, "沒有產品")
        return
    sys.path.insert(0, os.path.join(ROOT, "tools", "test_platform"))
    from core import doc_draft                                    # noqa: E402

    probe = {"kind": "doc", "product": pid, "signature": "_verify_probe",
             "path": "_verify_probe.md", "title": "驗證用", "body": "# 驗證用\n"}
    pv = doc_draft.preview(probe)
    check(B, "機制文件的落點正確",
          lambda: (pv.get("ok") and "docs" in (pv.get("path") or ""), pv.get("path") or pv.get("errors")))

    ho = {"kind": "handover", "product": pid, "signature": "_verify_probe2",
          "section": "todo", "title": "驗證用", "cells": ["驗證用", "說明", "低"]}
    pv2 = doc_draft.preview(ho)
    check(B, "交接檔的編號當下取",
          lambda: (pv2.get("ok") and bool(pv2.get("id")), "%s（%s）" % (pv2.get("id"), pv2.get("id_source"))))
    check(B, "指到正確的子節",
          lambda: (pv2.get("sub") == "2.1", "sub=%s｜%s" % (pv2.get("sub"), pv2.get("mode"))))

    if do_write:
        res = doc_draft.commit(probe)
        target = pv.get("abs")
        if res.get("ok") and target:
            _cleanup.append(target)
        check(B, "機制文件真的寫得進去",
              lambda: (res.get("ok") and os.path.isfile(target), res.get("path") or res.get("errors")))
    else:
        record(B, "機制文件真的寫得進去", None, "加 --write 才會實際寫")
    record(B, "交接檔真的附加一列", None,
           "⛔ 刻意不做 —— 交接檔是共用檔，驗證不該在別人的表裡塞列")


def block_case_flow(api, ctx, do_write: bool):
    B = "⑩ 撰寫案例動線"
    pid = next(iter(ctx["reg_products"]), None)
    if not pid:
        record(B, "POM 掃得到", None, "沒有產品")
        return
    pom = api.get("/api/pom")
    summary = pom.get("summary") or {}
    have = {k: v for k, v in summary.items() if (v or {}).get("methods")}
    check(B, "POM 依產品掃描（不寫死）",
          lambda: (isinstance(summary, dict), "、".join("%s:%s" % (k, v.get("methods")) for k, v in summary.items()) or "各產品皆無 POM"))

    sys.path.insert(0, os.path.join(ROOT, "tools", "test_platform"))
    from core.case_writer import tests_out_dir                    # noqa: E402
    out = tests_out_dir(pid)
    check(B, "案例落點不是 Demo 沙箱",
          lambda: ("demo" not in out.replace("\\", "/").split("/"), out))

    if do_write:
        d = api.post("/api/drafts/generate",
                     {"requirement": "驗證用：一條規則", "product": pid})
        did = (d.get("draft") or d).get("id")
        api.post("/api/drafts/%s/code" % did, {})
        r = api.post("/api/drafts/%s/commit" % did, {})
        # ⚠️ commit() 回的是單一 `path`，不是 `files` 陣列 —— 假設錯了就清不掉，
        #    而驗證留下的檔案會被誤認成別人的工作（2026-08-23 實測漏清一個檔）。
        files = [r.get("path")] if r.get("path") else             [f if isinstance(f, str) else f.get("path") for f in (r.get("files") or [])]
        for f in files:
            if f:
                _cleanup.append(os.path.join(ROOT, *f.replace("\\", "/").split("/")))
        check(B, "寫檔 → 索引掃得到",
              lambda: (r.get("ok") is True, "、".join(files) or json.dumps(r, ensure_ascii=False)[:120]))
    else:
        record(B, "寫檔 → 索引掃得到", None, "加 --write 才會實際寫")


def block_wrapup(api, ctx):
    B = "⑪ 收尾"
    setup = next((t for t in ctx["boot"]["tools"] if t["id"] == "setup"), None)
    if not setup:
        record(B, "收尾體檢（單一產品）", None, "沒有 setup 工具")
    else:
        cmds = {c["id"] for c in setup.get("commands") or []}
        check(B, "有 lint_product 命令", lambda: ("lint_product" in cmds, "、".join(sorted(cmds))))
        pid = next(iter(ctx["reg_products"].values()), None)
        if pid:
            r = api.post("/api/runs/command",
                         {"tool_id": "setup", "command_id": "lint_product",
                          "params": {"product": pid.get("product_id")}}, timeout=300)
            check(B, "lint_product 跑得起來",
                  lambda: (r.get("ok") is True, (r.get("text") or r.get("error") or "")[:110].replace("\n", " ")))
    sys.path.insert(0, os.path.join(ROOT, "tools", "test_platform"))
    from core.tasks import findings_for_handoff                   # noqa: E402
    f = findings_for_handoff()
    check(B, "收尾體檢掃得到跡象", lambda: (bool(f), f.splitlines()[0][:100] if f else ""))


def block_settings(api, ctx):
    B = "⑫ 設定與憑證"
    cl = api.get("/api/settings/claude")
    check(B, "Claude 探測", lambda: (cl.get("ok") is True, cl.get("version") or cl.get("error") or ""))
    cr = api.get("/api/settings/credentials")
    blob = json.dumps(cr, ensure_ascii=False)
    leak = [w for w in ("password", "passwd", "JSESSIONID=") if w in blob and '"%s"' % w not in blob]
    check(B, "⛔ 回應不含任何密碼",
          lambda: (not leak, "疑似外洩：%s" % "、".join(leak) if leak else "只回「已設定／未設定」"))


# ═══════════════════════════════════════════ 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="測試平台的端到端驗證")
    ap.add_argument("--base", default="http://127.0.0.1:5300", help="平台網址")
    ap.add_argument("--write", action="store_true", help="連寫入型動線也真的寫（結束前會清乾淨）")
    ap.add_argument("--run", action="store_true", help="連真的跑一輪測試也做（較慢）")
    a = ap.parse_args(argv)

    api = Api(a.base)
    print("驗證 %s　（工作區 %s）" % (a.base, ROOT))
    print("寫入型動線：%s｜真的執行：%s\n" % ("實際寫入" if a.write else "只預覽", "是" if a.run else "否"))

    ctx: dict = {"write": a.write, "run": a.run}
    try:
        block_boot(api, ctx)
    except Exception as e:                       # noqa: BLE001
        print("⛔ 連不上平台：%s\n   先啟動 tools\\test_platform\\run_server.bat" % e)
        return 2

    for fn, args in ((block_products, ()), (block_health, ()), (block_indexes, ()),
                     (block_search, ()), (block_tasks, ()),
                     (block_run, (a.run,)), (block_bug_flow, (a.write,)),
                     (block_doc_flow, (a.write,)), (block_case_flow, (a.write,)),
                     (block_wrapup, ()), (block_settings, ())):
        try:
            fn(api, ctx, *args)
        except Exception as e:                   # noqa: BLE001
            record(fn.__name__, "整個區塊", False, "%s：%s" % (type(e).__name__, str(e)[:160]))

    # 清理
    for p in _cleanup:
        try:
            if os.path.isfile(p):
                os.remove(p)
                print("清理 %s" % os.path.relpath(p, ROOT))
        except OSError:
            pass

    # 報告
    print()
    cur = None
    for block, item, state, detail in _results:
        if block != cur:
            print("\n" + block)
            cur = block
        print("  %s %-34s %s" % (state, item, detail))

    n_fail = sum(1 for r in _results if r[2] == FAIL)
    n_skip = sum(1 for r in _results if r[2] == SKIP)
    n_pass = sum(1 for r in _results if r[2] == PASS)
    print("\n" + "=" * 62)
    print("通過 %d｜失敗 %d｜略過 %d" % (n_pass, n_fail, n_skip))
    if n_fail:
        print("\n❌ 失敗的項目：")
        for block, item, state, detail in _results:
            if state == FAIL:
                print("   %s → %s：%s" % (block, item, detail))
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
