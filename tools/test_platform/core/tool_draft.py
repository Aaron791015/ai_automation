"""draft → 真的 `<id>.tool.json`，並用 `validate_spec()` 驗證它進得了 registry。

用途：使用者要求「**接新工具需要有介面可以進行**」。在此之前
      `web_ui/api/registry_api.py` 對 tool.json 是**唯讀的**（只有 profiles 可寫），
      接一支工具只能手動開檔照著 `docs/CONTRIB_TOOL.md` 抄。

四段式（與 `core/case_writer.py`、`core/spec_draft.py` 同一個模式）：

    draft → 人工調整 → 寫檔 → 驗證

其中「驗證」是關鍵：`case_writer` 用 `pytest --collect-only` 確認案例收得到，
這裡的對應物是 **`validate_spec()`** —— 確認這支 tool.json 真的會被 registry 收下。

⛔ **驗證失敗一律還原** —— 一支壞掉的 tool.json 會讓它自己從 `#/tools` 消失，
   而錯誤只出現在 `#/registry` 那個平常不會去看的頁面。與其留一個「看起來建好了、
   實際不存在」的工具，不如當場失敗並說清楚原因。

⚠️ **本檔只組骨架，不猜參數** —— 欄位（`params.fields`）留給人依
   `docs/CONTRIB_TOOL.md` 補。猜出來的欄位會變成「填了不生效」，
   那正是階段 G 花最多力氣在防的事。

使用方式：
    from core import tool_draft
    pv = tool_draft.preview(draft)          # 不寫檔，回完整 JSON 文字
    res = tool_draft.commit(draft)          # 寫檔 → validate_spec → 失敗還原
"""
from __future__ import annotations

import collections
import json
import os
import re

from core.paths import REGISTRY_DIR, REPO_ROOT, rel_to_repo
from core.registry import SPEC_VERSION, load_registry, validate_spec

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_KINDS = ("cli", "pytest", "http")


def target_path(draft: dict) -> str:
    return os.path.join(REGISTRY_DIR, "%s.tool.json" % (draft.get("id") or "").strip())


def _rel(path: str) -> str:
    return rel_to_repo(path)


def check_input(draft: dict) -> list[str]:
    """表單層級的檢查 —— 回錯誤字串清單（空＝可以往下走）。

    ⚠️ 與 `validate_spec()` 分工：這裡擋「人填錯」（id 格式、必填、撞名），
    `validate_spec()` 擋「組出來的 spec 不合契約」。兩層都要，因為
    骨架是本檔組的 —— 只驗人的輸入會漏掉組裝本身的錯。
    """
    errs: list[str] = []
    tool_id = (draft.get("id") or "").strip()
    if not tool_id:
        errs.append("工具 id 必填")
    elif not _ID_RE.match(tool_id):
        errs.append("工具 id 只能是小寫英數與底線、且開頭為字母（會直接當檔名 <id>.tool.json）")
    elif os.path.exists(target_path(draft)):
        errs.append("已經有一支叫 %s 的工具了 —— 換個 id，或直接編輯既有的那份" % tool_id)

    if not (draft.get("name") or "").strip():
        errs.append("顯示名稱必填")

    kind = draft.get("kind") or "cli"
    if kind not in _KINDS:
        errs.append("kind 必須是 %s 其中之一" % "／".join(_KINDS))

    scope = draft.get("scope") or "product"
    if scope not in ("product", "workspace"):
        errs.append('scope 必須是 "product" 或 "workspace"')
    if scope == "product" and not (draft.get("product") or draft.get("products")):
        errs.append("scope=product 時要選一個產品（不屬於任何產品的工具請改選「工作區級」）")

    if scope == "product" and draft.get("product"):
        reg = load_registry()
        known = {p.get("id") for p in reg.products}
        if draft["product"] not in known:
            errs.append("產品 %s 不在 config/products.json 裡 —— 先用「接一個產品」建立它"
                        % draft["product"])

    if not (draft.get("command_id") or "").strip():
        errs.append("第一個命令的 id 必填")
    elif not _ID_RE.match(draft["command_id"].strip()):
        errs.append("命令 id 只能是小寫英數與底線、且開頭為字母")

    if not (draft.get("argv") or "").strip():
        errs.append("argv 必填 —— 這是這支工具真正要執行的東西")
    return errs


def build_spec(draft: dict) -> dict:
    """把表單值組成 tool.json 的骨架（OrderedDict，寫檔順序即閱讀順序）。"""
    d: collections.OrderedDict = collections.OrderedDict()
    d["$schema"] = "./_schema.json"
    d["spec_version"] = SPEC_VERSION
    d["id"] = (draft.get("id") or "").strip()
    d["name"] = (draft.get("name") or "").strip()
    if (draft.get("subtitle") or "").strip():
        d["subtitle"] = draft["subtitle"].strip()
    d["kind"] = draft.get("kind") or "cli"

    scope = draft.get("scope") or "product"
    if scope == "workspace":
        d["scope"] = "workspace"
    elif draft.get("products"):
        d["products"] = draft["products"]
    else:
        d["product"] = draft.get("product")

    if draft.get("owner"):
        d["owner"] = draft["owner"]
    d["danger"] = collections.OrderedDict([("level", draft.get("danger") or "low")])

    runtime: collections.OrderedDict = collections.OrderedDict()
    if (draft.get("cwd") or "").strip():
        runtime["cwd"] = draft["cwd"].strip()
    if (draft.get("executable") or "").strip():
        runtime["executable"] = draft["executable"].strip()
    runtime["env"] = collections.OrderedDict([("PYTHONUNBUFFERED", "1"), ("PYTHONUTF8", "1")])
    mods = [m.strip() for m in re.split(r"[\s,，]+", draft.get("python_modules") or "") if m.strip()]
    if mods:
        runtime["requires"] = collections.OrderedDict([
            ("python_modules", mods),
            ("hint", draft.get("requires_hint")
                or "缺套件時：pip install -r requirements.txt"),
        ])
    d["runtime"] = runtime

    cmd: collections.OrderedDict = collections.OrderedDict()
    cmd["id"] = (draft.get("command_id") or "").strip()
    cmd["label"] = (draft.get("command_label") or cmd["id"]).strip()
    cmd["mode"] = draft.get("mode") or ("run" if d["kind"] != "cli" else "sync")
    cmd["argv"] = [a for a in re.split(r"\s+", (draft.get("argv") or "").strip()) if a]
    cmd["primary"] = True
    # ⚠️ 刻意留空：欄位要人依 CONTRIB_TOOL.md 補。
    #    猜出來的欄位會變成「填了不生效」——階段 G 花最多力氣防的就是這個。
    cmd["params"] = collections.OrderedDict([("fields", [])])
    d["commands"] = [cmd]

    d["_接入待辦"] = [
        "這份是介面產生的**骨架**，還不能算接好了。依 docs/CONTRIB_TOOL.md 補完：",
        "1. `commands[].params.fields` —— 這支工具要問使用者什麼？"
        "每個欄位的 `emit`／`arg` 決定它怎麼進命令列（13 種 type、11 種 emit）。",
        "2. ⛔ **憑證不要放進 fields** —— 走 config/config.local.json（憑證設定頁）。",
        "3. 吸收既有控制台時，先做**欄位對照盤點**（CONTRIB_TOOL §12／§15），"
        "否則會有設定悄悄消失、或「填了不生效」。",
        "4. run 型的話再補 `run.status_source`／`run.phases`／`artifacts`／`stop`，"
        "以及 `runtime.run_id_arg`（讓引擎的 run 目錄對得上平台的 run_id）。",
        "5. 補完後把這個 `_接入待辦` 欄位刪掉。",
    ]
    return d


def preview(draft: dict) -> dict:
    """組出整份 tool.json 文字，不寫檔。回 {path, text, errors, spec_errors}。"""
    errs = check_input(draft)
    if errs:
        return {"ok": False, "errors": errs, "text": "", "path": ""}
    spec = build_spec(draft)
    text = json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
    path = target_path(draft)
    spec_errs = validate_spec(spec, os.path.basename(path))
    return {"ok": not spec_errs, "errors": [], "spec_errors": spec_errs,
            "path": _rel(path), "abs": path, "text": text,
            "exists": os.path.exists(path)}


def commit(draft: dict) -> dict:
    """寫檔 → `validate_spec` → 失敗就刪掉。回 {ok, path, tool_id, errors}。

    ⛔ 驗證失敗一定要把檔刪掉 —— 留著的話它會**佔住 id**、在 `#/registry`
       掛一條錯誤，而使用者看到的是「工具建好了但不見了」。
    """
    pv = preview(draft)
    if pv.get("errors"):
        return {"ok": False, "errors": pv["errors"]}
    if pv.get("spec_errors"):
        return {"ok": False, "errors": [e["error"] for e in pv["spec_errors"]]}
    path = pv["abs"]
    if os.path.exists(path):
        return {"ok": False, "errors": ["%s 已存在" % pv["path"]]}

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(pv["text"])

    # 寫檔後再驗一次「registry 真的收得下」—— 這一步才是 case_writer
    # 用 `--collect-only` 在做的事：不是驗我組得對不對，是驗**系統收不收**。
    reg = load_registry(force=True)
    if draft["id"] not in reg.tools:
        why = [e["error"] for e in reg.errors
               if e.get("file") == os.path.basename(path)] or ["registry 沒有收下這支工具"]
        os.remove(path)
        load_registry(force=True)
        return {"ok": False, "restored": True, "errors": why}

    return {"ok": True, "path": pv["path"], "tool_id": draft["id"],
            "todo": reg.tools[draft["id"]].raw.get("_接入待辦") or []}
