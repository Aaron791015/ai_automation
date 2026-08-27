# -*- coding: utf-8 -*-
"""平台 MCP server：把平台的索引暴露給 Claude（階段 D-1，2026-08-23）。

用途：讓 Claude（終端機的、以及平台起的 session）能查到**真實**的案例／Bug／待辦／
      執行紀錄／知識雷達，並且**只能提議執行、不能自己執行**
      （`ARCHITECTURE.md` 決策 8）。

使用方式：由 `.mcp.json` 註冊，Claude 以 stdio 啟動它。
    "test-platform": {
      "command": ".venv/Scripts/python.exe",
      "args": ["tools/test_platform/mcp/server.py"]
    }
    ⚠️ 路徑一律相對 repo root —— `.mcp.json` 會隨範本發給同事。
    手動驗證：`python tools/test_platform/mcp/server.py --selftest`

前置條件（三條）：
    · ⛔ **只准 stdlib** —— 不裝 `mcp` SDK。範本的原則是「`setup_test_env.ps1`
      跑完就能用」，每多一個相依就多一個「在同事機器上裝不起來」的機會
      （階段 0 的 flask 就是這樣漏掉的）。MCP 是 JSON-RPC 2.0 over stdio，
      工具型 server 只需要 initialize／tools/list／tools/call 三個方法。
    · ⛔ **stdout 只准放 JSON-RPC** —— 任何 print 都會污染協定。
      診斷訊息一律走 stderr。
    · ⛔ **一律唯讀** —— 唯一的動作型工具是 `propose_run`，它**只回一段提議**，
      不呼叫 `runner.manager`。真的要跑得由人在 UI 按確認卡。
"""
from __future__ import annotations

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(_HERE)
if PLATFORM not in sys.path:
    sys.path.insert(0, PLATFORM)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "test-platform", "version": "1.0.0"}


# ───────────────────────────────────────── 工具定義
# ⚠️ 每個工具的 description 要寫「**什麼時候該用它**」，不是只寫「它回什麼」——
#    Claude 是靠 description 決定要不要呼叫的。

def _tools():
    return [
        {
            "name": "list_cases",
            "description": "列出工作區的自動化測試案例（pytest 收集結果）。"
                           "要回答「有哪些案例」「某功能有沒有涵蓋到」「案例總數」時用。",
            "inputSchema": {"type": "object", "properties": {
                "product": {"type": "string", "description": "只看某個產品（slug，如 crux）"},
                "keyword": {"type": "string", "description": "以關鍵字過濾 nodeid 或標題"},
                "limit": {"type": "integer", "default": 50},
            }},
        },
        {
            "name": "get_bugs",
            "description": "查本地 Bug 單的現況（frontmatter × JIRA 交叉狀態）。"
                           "要回答「還有幾張沒修」「某單什麼狀態」「待補回歸有哪些」時用。",
            "inputSchema": {"type": "object", "properties": {
                "product": {"type": "string"},
                "status": {"type": "string", "description": "open／fixed／rejected…"},
                "limit": {"type": "integer", "default": 50},
            }},
        },
        {
            "name": "get_todos",
            "description": "查各產品交接活文件的 blocker 與待辦（§1／§2）。"
                           "要回答「現在卡在哪」「還有什麼沒做完」「接手要先看什麼」時用。",
            "inputSchema": {"type": "object", "properties": {
                "product": {"type": "string"},
            }},
        },
        {
            "name": "get_runs",
            "description": "查最近的執行紀錄（跨工具）。"
                           "要回答「上次跑的結果」「哪些失敗了」「什麼時候跑的」時用。",
            "inputSchema": {"type": "object", "properties": {
                "product": {"type": "string"},
                "tool": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            }},
        },
        {
            "name": "get_knowledge",
            "description": "查知識雷達：各產品的規格機制／測試案例／缺陷／驗證紀錄／健康度五圈。"
                           "要回答「哪個產品的知識最薄弱」「涵蓋率如何」時用。",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_drafts",
            "description": "查**還沒落檔**的草稿：Bug 草稿（尚未配號開單）與文件草稿"
                           "（機制文件／驗證報告／交接檔待補列）。"
                           "⛔ 收尾體檢說「有 N 筆草稿還沒開單」時，用這個查是哪幾筆 ——"
                           "**草稿不佔 Bug ID**，落檔要人在平台上按。",
            "inputSchema": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["bug", "doc", "all"],
                         "description": "預設 all"},
                "product": {"type": "string"},
            }},
        },
        {
            "name": "list_tools",
            "description": "列出平台上可執行的工具與它們的命令。"
                           "**要提議執行之前先用這個確認 tool_id 與 command_id**。",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "propose_run",
            "description": "提議執行某個工具的某個命令。"
                           "⛔ 這**不會真的執行** —— 只是回一段提議，"
                           "由人在平台 UI 上按確認卡才會跑。要跑測試或壓測時用它。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    "command_id": {"type": "string"},
                    "params": {"type": "object", "description": "命令參數"},
                    "reason": {"type": "string", "description": "為什麼建議跑這個"},
                },
                "required": ["tool_id", "command_id"],
            },
        },
    ]


# ───────────────────────────────────────── 工具實作（全部唯讀）

def _call(name, args):
    args = args or {}
    # ⛔ **產品名一律先正規化成 slug** —— 這個工作區有兩套 id
    #    （權威 `CRUX` ／ 平台 slug `crux`），而 session 手上拿到的常是權威 id。
    #    不轉的話 `by_prod.get("CRUX")` → None，呼叫端把它當成「沒有資料」而回 0。
    #    2026-08-24 實測：對話裡問「CRUX 有幾張活躍 Bug」→ **回 0 張**，
    #    畫面上卻寫 60 張 —— 錯得很有自信，而且完全不報錯。
    if args.get("product"):
        from core.registry import to_slug
        args = dict(args, product=to_slug(args["product"]))
    if name == "get_drafts":
        kind = (args.get("kind") or "all").lower()
        prod = args.get("product")
        out = {}
        if kind in ("bug", "all"):
            from core import bug_draft
            rows = [d for d in bug_draft.read_all()
                    if not prod or d.get("product") == prod]
            out["bugs"] = [{"title": d.get("title"), "product": d.get("product"),
                            "severity": d.get("severity"),
                            "source": d.get("source"),
                            "prechecks": d.get("prechecks"),
                            "filed_as": d.get("filed_as") or ""} for d in rows]
        if kind in ("doc", "all"):
            from core import doc_draft
            rows = [d for d in doc_draft.read_all()
                    if not prod or d.get("product") == prod]
            out["docs"] = [{"kind": d.get("kind"), "title": d.get("title"),
                            "product": d.get("product"),
                            "path": d.get("path") or d.get("topic"),
                            "section": d.get("section"),
                            "why": d.get("why")} for d in rows]
        out["note"] = ("草稿**不佔 Bug ID**；要落檔請人在平台的『待開單／待寫檔』"
                       "清單上按，配號與檔名都在那一刻才取")
        return out
    if name == "list_cases":
        from collect.case_index import build_or_load
        from core.registry import get_registry
        spec = get_registry().tools.get("ui_tests")
        if not spec:
            return {"error": "沒有註冊 ui_tests 工具，無法收集案例"}
        idx = build_or_load(spec) or {}
        flat = idx.get("flat") or []
        kw, prod = args.get("keyword"), args.get("product")
        if prod:
            flat = [c for c in flat if c.get("product") == prod]
        if kw:
            k = kw.lower()
            flat = [c for c in flat
                    if k in (c.get("nodeid", "") + c.get("title", "")).lower()]
        limit = int(args.get("limit") or 50)
        return {"total": len(flat), "showing": min(limit, len(flat)),
                "cases": [{"nodeid": c.get("nodeid"), "title": c.get("title"),
                           "product": c.get("product")} for c in flat[:limit]]}

    if name == "get_bugs":
        from core.bug_index import build_bug_index
        idx = build_bug_index(jira="cached")
        # ⚠️ 索引是**依產品分層**的（`products.<slug>.bugs`），不是頂層一個平表。
        by_prod = idx.get("products") or {}
        if args.get("product") and args["product"] not in by_prod:
            # ⛔ 寧可講「沒有這個產品」也不要回 0 —— 回 0 會被讀成「沒有 Bug」
            return {"error": "沒有這個產品：%s（有的是 %s）"
                             % (args["product"], "、".join(by_prod)), "total": 0, "bugs": []}
        wanted = [args["product"]] if args.get("product") else list(by_prod)
        items = []
        for pid in wanted:
            for b in (by_prod.get(pid) or {}).get("bugs") or []:
                items.append(dict(b, product=pid))
        if args.get("status"):
            items = [b for b in items if b.get("status") == args["status"]]
        limit = int(args.get("limit") or 50)
        return {"total": len(items), "showing": min(limit, len(items)),
                "jira_source": idx.get("jira_source"),
                "bugs": items[:limit]}

    if name == "get_todos":
        from core.todo_index import build_todo_index
        idx = build_todo_index()
        if args.get("product"):
            by = idx.get("products") or {}
            if args["product"] not in by:
                return {"error": "沒有這個產品：%s（有的是 %s）"
                                 % (args["product"], "、".join(by))}
            return {"product": args["product"], "data": by[args["product"]]}
        return idx

    if name == "get_runs":
        from core import run_index
        return {"runs": run_index.recent(
            limit=int(args.get("limit") or 10), product=args.get("product"),
            tool=args.get("tool"), status=args.get("status"))}

    if name == "get_knowledge":
        from core.knowledge_index import build_knowledge_index
        return build_knowledge_index()

    if name == "list_tools":
        from core.registry import get_registry
        reg = get_registry()
        return {"tools": [{
            "tool_id": t.id, "name": t.name, "scope": t.scope,
            "products": t.products, "danger": (t.danger or {}).get("level"),
            "commands": [{"command_id": c["id"], "label": c.get("label"),
                          "mode": c.get("mode"),
                          "description": c.get("description", "")[:200]}
                         for c in t.commands],
        } for t in reg.tools.values()]}

    if name == "propose_run":
        # ⛔ 只回提議，**絕不呼叫 runner.manager** —— 決策 8 的閘門就在這裡。
        from core.registry import get_registry
        reg = get_registry()
        tid, cid = args.get("tool_id"), args.get("command_id")
        spec = reg.tools.get(tid)
        if not spec:
            return {"error": "未知的工具：%s（先用 list_tools 確認）" % tid}
        cmd = spec.command(cid)
        if not cmd:
            return {"error": "工具 %s 沒有命令 %s" % (tid, cid)}
        return {
            "proposal": {
                "tool_id": tid, "tool_name": spec.name,
                "command_id": cid, "command_label": cmd.get("label"),
                "params": args.get("params") or {},
                "reason": args.get("reason", ""),
                "danger": (cmd.get("danger") or spec.danger or {}).get("level", "low"),
            },
            "note": "這只是提議。請在平台的確認卡上按下執行 —— "
                    "MCP 不會、也不能替你執行任何命令。",
        }

    return {"error": "未知的工具：%s" % name}


# ───────────────────────────────────────── JSON-RPC over stdio

def _result(rid, payload):
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def _error(rid, code, msg):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


def handle(msg):
    """處理一則 JSON-RPC 訊息。回 None ＝ 這是通知，不必回應。"""
    method, rid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return _result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized"):
        return None                      # 通知沒有 id，不回應
    if method == "tools/list":
        return _result(rid, {"tools": _tools()})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            data = _call(p.get("name"), p.get("arguments"))
        except Exception as e:                       # noqa: BLE001
            print(traceback.format_exc(), file=sys.stderr)
            data = {"error": "%s: %s" % (type(e).__name__, e)}
        is_err = isinstance(data, dict) and "error" in data
        return _result(rid, {
            "content": [{"type": "text",
                         "text": json.dumps(data, ensure_ascii=False, indent=2)}],
            "isError": bool(is_err),
        })
    if method == "ping":
        return _result(rid, {})
    if rid is None:
        return None                      # 未知的通知：忽略
    return _error(rid, -32601, "未支援的方法：%s" % method)


def serve(stdin=None, stdout=None):
    """stdio 主迴圈：一行一則 JSON-RPC。

    ⛔ stdout 只准放 JSON-RPC —— 任何 print 都會污染協定，
      Claude 那端會直接判定 server 壞掉。診斷走 stderr。
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            out = handle(msg)
        except Exception:                            # noqa: BLE001
            print(traceback.format_exc(), file=sys.stderr)
            out = _error(msg.get("id"), -32603, "內部錯誤（詳見 stderr）")
        if out is not None:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()


def _selftest():
    """不進 stdio 迴圈，直接驗每個工具都叫得動（給人手動確認用）。"""
    print("protocol:", PROTOCOL_VERSION, file=sys.stderr)
    for t in _tools():
        name = t["name"]
        args = {"limit": 1} if name in ("list_cases", "get_bugs", "get_runs") else {}
        if name == "propose_run":
            args = {"tool_id": "ui_tests", "command_id": "run_cases"}
        try:
            r = _call(name, args)
            head = json.dumps(r, ensure_ascii=False)[:110]
            print("  %-16s %s" % (name, head), file=sys.stderr)
        except Exception as e:                       # noqa: BLE001
            print("  %-16s ❌ %s: %s" % (name, type(e).__name__, e), file=sys.stderr)
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    serve()
