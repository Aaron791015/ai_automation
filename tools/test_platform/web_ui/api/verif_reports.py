# -*- coding: utf-8 -*-
"""/api/verification-reports —— 驗證報告清單（`docs/<產品>/bugs/_reports/`）。

## 為什麼需要這一支

`_reports/` 是**人寫給人看**的產出：需求驗證報告、JIRA 重驗報告、效能測試報告。
2026-08-23 實查：那裡有 **27 份**，而平台上**沒有任何畫面列得出來、點得開** ——
知識雷達只把它算成一個數字（reports: 40）。

使用者要的動線是「探索任務完成後，**在平台上檢視探索報告**」——
產出落了檔卻看不到，等於沒有落。

⛔ 唯讀。`bugs/` 整層不版控（含測試站帳密），所以**不提供下載或對外連結**，
   只在平台內顯示（與 `/api/doc` 同一條紀律）。
"""
from __future__ import annotations

import io
import os
import re
import time

from flask import Blueprint, request

from core import acks
from core.paths import REPO_ROOT, rel_to_repo
from core.registry import get_registry
from web_ui.api import fail, ok

bp = Blueprint("verif_reports", __name__)

#: 檔名 → 類型。`new_bug_doc.py` 的 KINDS 決定了這些前綴。
_KIND = [
    ("需求驗證報告", "需求驗證"),
    ("效能測試報告", "效能"),
    ("JIRA_Bug驗證報告", "JIRA 重驗"),
    ("交接_SideEffect待驗", "side effect 交接"),
]
_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def _dirs(product: str):
    """(產品 id, `_reports` 路徑, `_handover` 路徑) 逐一產出。"""
    for p in get_registry().products:
        if p.get("virtual"):
            continue
        pid = p.get("id")
        if product and product not in (pid, p.get("product_id"), p.get("label")):
            continue
        docs = (p.get("knowledge") or {}).get("docs_dir")
        if not docs:
            continue
        base = os.path.join(REPO_ROOT, *docs.split("/"), "bugs")
        yield pid, os.path.join(base, "_reports"), os.path.join(base, "_handover")


def _kind_of(name: str) -> str:
    for prefix, label in _KIND:
        if name.startswith(prefix):
            return label
    return "其他"


@bp.get("/api/verification-reports")
def list_reports():
    """列出驗證報告。`?product=` 可限定產品。

    ⚠️ 只回**中繼資料**（檔名、類型、日期、大小、標題）——
       全文走 `/api/doc`（那支已經處理過路徑白名單與渲染）。
    """
    product = (request.args.get("product") or "").strip()
    out = []
    for pid, rdir, hdir in _dirs(product):
        for d, group in ((rdir, "報告"), (hdir, "交接")):
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d), reverse=True):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(d, name)
                try:
                    st = os.stat(full)
                    head = io.open(full, encoding="utf-8").read(400)
                except OSError:
                    continue
                m = _DATE.search(name)
                title = ""
                for ln in head.split("\n"):
                    if ln.startswith("# "):
                        title = ln[2:].strip()
                        break
                out.append({
                    "product": pid,
                    "name": name,
                    "path": rel_to_repo(full),
                    "group": group,
                    "kind": _kind_of(name),
                    "date": m.group(1) if m else "",
                    "title": title,
                    "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M",
                                           time.localtime(st.st_mtime)),
                })
    out.sort(key=lambda x: (x["date"] or "0000", x["mtime"]), reverse=True)
    # ⭐「已確認」（2026-08-24 使用者要求）—— 讓人分得出哪些看過了、哪些還沒。
    #    ⚠️ 它是**閱讀狀態**，存在平台這邊（`logs/acks.json`），不動報告本身：
    #       報告在不版控的 `bugs/` 底下，而且它是產出，不該因為誰看過就被改。
    st = acks.status([r["path"] for r in out])
    for r in out:
        r.update(st.get(r["path"]) or {"acked": False, "at": "", "stale": False})
    return ok(reports=out, count=len(out),
              acked=sum(1 for r in out if r.get("acked")))


@bp.post("/api/verification-reports/ack")
def ack_report():
    """勾／取消勾一份報告。

    ⚠️ 只認**清單裡真的存在**的路徑 —— 這個端點會寫檔，不可以讓任意字串進來當 key。
    """
    body = request.get_json(force=True, silent=True) or {}
    path = (body.get("path") or "").replace("\\", "/").strip()
    if not path:
        return fail("缺少 path")
    full = os.path.join(REPO_ROOT, *path.split("/"))
    if not os.path.isfile(full) or "/bugs/" not in "/" + path:
        return fail("這不是一份驗證報告：%s" % path, 400)
    return ok(**acks.set_ack(path, bool(body.get("acked", True))))
