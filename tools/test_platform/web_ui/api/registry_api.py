"""/api/tools/* —— 工具描述、健康、動態選項、profile。"""
from __future__ import annotations

import glob
import os

from flask import Blueprint, request

from adapters import get_adapter
from core.jsonio import read_json, write_json_atomic
from core.paths import REGISTRY_DIR, REPO_ROOT
from core.registry import get_registry, load_registry
from web_ui.api import fail, ok

bp = Blueprint("registry_api", __name__)


@bp.get("/api/tools")
def list_tools():
    reg = get_registry()
    return ok(tools=[t.public() for t in reg.tools.values()],
              errors=reg.errors, notes=reg.notes)


@bp.get("/api/tools/<tool_id>")
def get_tool(tool_id):
    reg = get_registry()
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    return ok(tool=reg.tools[tool_id].public())


@bp.get("/api/tools/<tool_id>/health")
def tool_health(tool_id):
    reg = get_registry()
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    return ok(health=get_adapter(reg.tools[tool_id]).health())


@bp.get("/api/tools/<tool_id>/options/<field_key>")
def tool_options(tool_id, field_key):
    reg = get_registry()
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    spec = reg.tools[tool_id]

    # ── 通用 options_from（宣告式，所有工具共用）────────────────
    # ⚠️ 下面那些是逐工具硬編碼的特例；能用通用來源就別再加特例
    #    （CONTRIB_TOOL 三層原則第②層：擴充宣告能力，不新增專屬處理）。
    field = next((f for c in spec.commands
                  for f in ((c.get("params") or {}).get("fields") or [])
                  if f.get("key") == field_key), None)
    source = ((field or {}).get("options_from") or {}).get("source")
    if source == "products":
        # `value: "product_id"` ＝ 用**權威 id**（`CRUX`／`七星`）而不是 slug ——
        # `lint_docs --product`／`gen_bug_index` 吃的是權威 id，slug 會對不上。
        key = ((field or {}).get("options_from") or {}).get("value") or "id"
        return ok(options=[{"value": p.get(key, p["id"]), "label": p.get("label", p["id"])}
                           for p in reg.products if not p.get("virtual")])
    if source == "tools":
        return ok(options=[{"value": t.id, "label": t.name}
                           for t in reg.tools.values()])
    if source == "files":
        return ok(options=_file_options(spec, (field or {}).get("options_from") or {}))

    return ok(options=get_adapter(spec).options(field_key, request.args.to_dict()))


def _file_options(spec, src: dict) -> list:
    """`options_from: {source:"files", dir, glob, strip_ext?}` —— 列出工具目錄底下的檔名。

    ⭐ 這是**通用宣告**，取代原本 `qixing_perf.member_list` 與 `wbot_perf.profile`
       兩處逐工具硬編碼的分支（CONTRIB_TOOL 三層原則第②層：擴充宣告能力，
       不新增專屬處理）—— 同事接自己的工具時「從某個目錄挑檔」是最常見的需求，
       每來一支就加一個 `if` 是走不下去的。

    ⛔ `dir` 一律相對於該工具的 `runtime.cwd`，並且**擋掉 `..`** ——
       這個端點是 GET、任何人都打得到，不可以變成任意目錄列舉。
    """
    rel = str(src.get("dir") or "").replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        return []
    cwd = (spec.runtime or {}).get("cwd")
    if not cwd:
        return []
    base = os.path.join(REPO_ROOT, cwd.replace("/", os.sep), rel.replace("/", os.sep))
    pat = str(src.get("glob") or "*")
    if "/" in pat or os.sep in pat or ".." in pat:
        return []
    strip = bool(src.get("strip_ext"))
    names = sorted(os.path.basename(x) for x in glob.glob(os.path.join(base, pat)))
    return [{"value": os.path.splitext(n)[0] if strip else n,
             "label": os.path.splitext(n)[0] if strip else n} for n in names]


@bp.post("/api/registry/reload")
def reload_registry():
    reg = load_registry(force=True)
    return ok(tools=len(reg.tools), errors=reg.errors, notes=reg.notes)


# ---------------------------------------------------------------- profiles
def _profiles_dir(tool_id: str) -> str:
    return os.path.join(REGISTRY_DIR, "profiles", tool_id)


@bp.get("/api/tools/<tool_id>/profiles")
def list_profiles(tool_id):
    d = _profiles_dir(tool_id)
    out = []
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        j = read_json(p, {}) or {}
        out.append({"id": os.path.splitext(os.path.basename(p))[0], "label": j.get("label") or os.path.basename(p),
                    "command_id": j.get("command_id"), "note": j.get("note", ""), "params": j.get("params", {})})
    return ok(profiles=out)


@bp.post("/api/tools/<tool_id>/profiles")
def save_profile(tool_id):
    reg = get_registry()
    if tool_id not in reg.tools:
        return fail("未知的工具", 404)
    body = request.get_json(force=True, silent=True) or {}
    pid = (body.get("id") or "").strip()
    if not pid or not pid.replace("_", "").replace("-", "").isalnum():
        return fail("profile id 只能含英數、底線、連字號")
    spec = reg.tools[tool_id]
    cmd = spec.command(body.get("command_id"))
    secrets = {f["key"] for f in (cmd.get("params") or {}).get("fields", []) if f.get("type") == "secret" or f.get("never_persist")} if cmd else set()
    params = {k: v for k, v in (body.get("params") or {}).items() if k not in secrets}
    path = os.path.join(_profiles_dir(tool_id), f"{pid}.json")
    if os.path.exists(path) and not body.get("overwrite"):
        return fail("同名 profile 已存在", 409)
    write_json_atomic(path, {"label": body.get("label") or pid, "command_id": cmd["id"] if cmd else None,
                             "note": body.get("note", ""), "params": params})
    return ok(id=pid)


@bp.delete("/api/tools/<tool_id>/profiles/<pid>")
def delete_profile(tool_id, pid):
    path = os.path.join(_profiles_dir(tool_id), f"{pid}.json")
    if not os.path.isfile(path):
        return fail("找不到 profile", 404)
    os.remove(path)
    return ok()


# ─────────────────────────── 接一支新工具（B-3）
#
# 使用者要求「接新工具需要有介面可以進行」。在此之前本檔對 tool.json 是**唯讀的**
# —— 只有 profiles 可寫，接一支工具只能手動開檔照著 CONTRIB_TOOL.md 抄。
#
# 走 `core/tool_draft.py` 的四段式（draft → 人工調整 → 寫檔 → 驗證），
# 與 `case_writer`／`spec_draft` 同一個模式。

@bp.post("/api/registry/tools/preview")
def preview_tool():
    """只組不寫 —— 讓人先看到 tool.json 長什麼樣再決定要不要寫檔。"""
    from core import tool_draft
    return ok(**tool_draft.preview(request.get_json(force=True, silent=True) or {}))


@bp.post("/api/registry/tools")
def create_tool():
    """寫檔 ＋ 驗證。⛔ registry 收不下就把檔刪掉，不留半成品佔住 id。"""
    from core import tool_draft
    res = tool_draft.commit(request.get_json(force=True, silent=True) or {})
    if not res.get("ok"):
        return fail("；".join(res.get("errors") or ["建立失敗"]), 400)
    return ok(**res)
