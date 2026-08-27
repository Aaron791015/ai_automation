"""待辦索引：解析各產品交接活文件（*驗證交接.md／*維護交接.md）的 §1 blocker 與 §2 待辦表。

用途：Dashboard「待辦與 Bug 現況」面板、Ctrl+K 搜 T21、知識雷達「健康度」圈（交接檔是否過期）。
使用方式：
    from core.todo_index import build_todo_index
    idx = build_todo_index()
    python -m core.todo_index --dump
前置條件：
    · 交接檔的表格列以編號開頭：`| T1 |`／`| **T21** |`（未完成）、`| ~~T22~~ |`（已完成，刪除線是既有慣例）。
    · 子節：2.1 可立即動手／2.2 等外部裁定／2.3 等 RD／2.4 被 blocker 擋住；標題文字略有差異，以「2.N」數字判定。
    · ★ 儲存格內容常超過 20 行（含完成紀錄、教訓、交叉引用）—— 本索引輸出「首句摘要（截 80 字）」與全文，
      UI 列表只顯示摘要，點開才渲染全文。
    · 檔頭「最後更新：YYYY-MM-DD」用於健康度（D6 判準：落後該產品最新 commit 超過 1 天）。
"""
from __future__ import annotations

import os
import re
import sys
import time

from core.paths import REPO_ROOT, rel_to_repo
from core.registry import get_registry

_ROW = re.compile(r"^\|\s*(?P<raw>(?:\*\*)?(?:~~)?(?P<id>[TDB]\d+)(?:~~)?(?:\*\*)?)\s*\|(?P<rest>.*)\|\s*$")
_SEC2 = re.compile(r"^###\s*(?:2\.(?P<n>\d)|(?P<letter>[A-Z]′?)\.)\s*(?P<title>.*)$")
_H2 = re.compile(r"^##\s*§?(?P<n>\d+)\.?\s*(?P<title>.*)$")
_UPDATED = re.compile(r"(?:最後更新[：:]\s*\**\s*|（)(\d{4}-\d{2}-\d{2})(?:\s*更新）)?")
_BLOCKER_ROW = re.compile(r"^\|\s*(?!#|---)(?P<n>[^|]*)\|(?P<rest>.*)\|\s*$")

_SUB_LABEL = {"1": "可立即動手", "2": "等外部裁定", "3": "等 RD", "4": "被 blocker 擋住"}


def _split_cells(rest: str) -> list[str]:
    # 儲存格內可能含 `\|`？交接檔慣例不用；直接以 | 切
    return [c.strip() for c in rest.split("|")]


# §5「測試資料現況」的節標題 —— 各產品的交接檔用字略有出入
#（「測試資料現況」／「測試資料與環境現況」），一律以關鍵字比對。
_DATA_SEC = "測試資料"


_KEPT_YES = ("保留", "不還原", "⛔", "勿刪", "不要還原", "未還原")
# ⚠️ 否定詞要**先判** —— 「資料無保留價值」也含「保留」
_KEPT_NO = ("已刪除", "已還原", "已退碼", "✅", "無保留價值", "不必保留")


def _is_kept(header, cells) -> bool:
    """這一列的資料是不是「刻意保留、不要當殘留清掉」。

    ⭐ 判準取自「**還原了嗎**」那一欄 —— 那一欄的用途就是回答這件事。
       先前用整列比對，於是
       「LOTTO-003 已撤銷，資料**無保留**價值」這種備註會讓已刪除的資料
       被標成⛔刻意保留（2026-08-23 實測）。
       誤判的方向很糟：**把已刪除的東西標成「不要動」** ——
       人一旦發現警示不準就會整塊略過，連真正該看的那一筆也一起略過。
    """
    target = None
    for i, h in enumerate(header or []):
        if "還原" in (h or ""):
            if i < len(cells):
                target = cells[i]
            break
    text = target if target is not None else " ".join(cells)
    if any(k in text for k in _KEPT_NO):
        return False
    return any(k in text for k in _KEPT_YES)


def _data_rows(lines) -> list[dict]:
    """抽出 §5「測試資料現況」的表格列。

    ⭐ 為什麼一定要撈出來：`handoff` §1.A 的兩節裡，這一節是**唯一
       「不先讀會造成不可逆傷害」**的 —— 標明「刻意保留、屬哪一張單」的資料
       清掉之後，那張單就不可重現了（RD 照步驟走會看不到現象）。
       而它的觸發時機是「我看到一批看起來像殘留的資料」，
       那一刻**不會有任何訊號提醒你先去查交接檔**。平台要替人把它推到眼前。

    ⚠️ 只認**表格列**，不做語意判斷 —— 判斷留給人。
       只標出「看起來像刻意保留」的那些（含「保留」「不還原」「⛔」）讓它們排前面。
    """
    rows, inside, header = [], False, None
    for ln in lines:
        h2 = _H2.match(ln)
        if h2:
            inside = _DATA_SEC in (h2.group("title") or "")
            header = None
            continue
        if not inside:
            continue
        if ln.startswith("| ---"):
            continue
        if not ln.strip():
            # ⚠️ 空行 ＝ 這張表結束。§5 常有**兩張表**（骨架自帶一張、
            #    後來又加一張），不重設的話第二張的表頭會被當成資料列
            #    （2026-08-23 實測：跑出「動了什麼／屬哪張單」這一列）。
            header = None
            continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if header is None:
                header = cells
                continue
            # 佔位列（骨架預留的「（尚無）」）不是資料
            if cells and cells[0].strip("（）() ") in ("尚無", "無", "—", "-", ""):
                continue
            if not any(cells) or all(c in ("—", "-", "") for c in cells):
                continue
            rows.append({
                "cells": cells,
                "header": header,
                "what": cells[0] if cells else "",
                "kept": _is_kept(header, cells),
            })
    # 刻意保留的排前面 —— 那些才是「動了會回不去」的
    rows.sort(key=lambda r: (not r["kept"],))
    return rows


def _priority_of(header_cells, cells) -> str:
    """依**表頭**取「優先」欄；這張表沒有這一欄就回空字串。

    ⛔ 不可以退回 `cells[-1]` —— 各節的最後一欄意義完全不同，
       退回去等於把「解除後怎麼做」印在優先級的位置上。
    """
    if not header_cells:
        return ""
    for i, h in enumerate(header_cells):
        if "優先" in (h or ""):
            j = i - 1                      # cells 不含第一欄（編號）
            if 0 <= j < len(cells):
                return (cells[j] or "").strip()
    return ""


def _first_sentence(md: str, limit: int = 80) -> str:
    s = re.sub(r"<br\s*/?>", " ", md)
    # ⚠️ 只清 markdown 的強調記號（`**`／`~~`／反引號）——
    #    **不可以連單個 `~` 一起刪**：`0~3` 會變成 `03`，那是改變語意
    #    （2026-08-23 情境 B 走查，儀表板顯示「中獎位數超出 03」）。
    s = re.sub(r"\*\*|~~|`", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # 到第一個句號／破折號段落
    for sep in ("。", " —— ", "——"):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    return (s[:limit] + "…") if len(s) > limit else s


def parse_handover(path: str) -> dict:
    text = open(path, encoding="utf-8", errors="replace").read()
    lines = text.splitlines()
    m = _UPDATED.search(text[:2000])
    updated = m.group(1) if m else None
    doc_rel = rel_to_repo(path)
    items: list[dict] = []
    blockers: list[dict] = []
    sec = None      # 目前 ## N
    sub = None      # 目前 2.N
    sub_title = ""
    header_cells: list[str] = []
    # ★ 逐行編號：待辦項目要能「看全文並跳到來源那一行」（docview 的 #L<n>），
    #   所以每筆都帶 doc（來源檔）＋ line（1-based 行號）。
    #   先前 doc 是前端 flatMap 時各自補的（overview.js／todopanel.js 兩處），改由後端給就只有一個來源。
    for lineno, ln in enumerate(lines, 1):
        h2 = _H2.match(ln)
        if h2:
            sec = h2.group("n")
            sub = None
            header_cells = []
            continue
        s2 = _SEC2.match(ln)
        if s2:
            sub = s2.group("n") or s2.group("letter")
            sub_title = s2.group("title").strip()
            header_cells = []
            continue
        if ln.startswith("| #") or ln.startswith("| ---"):
            if ln.startswith("| #"):
                header_cells = _split_cells(ln.strip("|"))
            continue
        if sec == "1":
            b = _ROW.match(ln)   # 只認 B\d+ 編號列；已解除（刪除線）的不算 blocker
            if b and b.group("id").startswith("B") and "~~" not in b.group("raw"):
                cells = _split_cells(b.group("rest"))
                blockers.append({"n": b.group("id"), "what": cells[0] if cells else "",
                                 "who": cells[1] if len(cells) > 1 else "", "impact": cells[2] if len(cells) > 2 else "",
                                 "updated": cells[3] if len(cells) > 3 else "",
                                 "doc": doc_rel, "line": lineno})
            continue
        if sec != "2":
            continue
        r = _ROW.match(ln)
        if not r:
            continue
        cells = _split_cells(r.group("rest"))
        raw = r.group("raw")
        done = raw.startswith("~~") or "~~" in raw
        starred = raw.startswith("**") or "⭐" in (cells[0] if cells else "")
        body = cells[0] if cells else ""
        items.append({
            "id": r.group("id"),
            "done": done,
            "starred": starred,
            "doc": doc_rel, "line": lineno,
            "sub": sub, "sub_label": _SUB_LABEL.get(sub or "", sub_title or "其他"), "sub_title": sub_title,
            "summary": _first_sentence(body),
            "body": body,
            "cols": {header_cells[i + 1]: cells[i] for i in range(1, min(len(cells), len(header_cells) - 1))} if header_cells else {},
            # ⚠️ 只有 §2.1 的最後一欄是「優先」——
            #    §2.2 是「我方已備好的材料」、§2.3 是「等誰」、
            #    §2.4 是「解除後怎麼做」。無條件取 cells[-1] 會把一整句
            #    「拿到裁定後補 3~4 條案例…」當成優先級顯示
            #    （2026-08-23 情境 B 走查）。依表頭查，查不到就留空。
            "priority": _priority_of(header_cells, cells),
        })
    return {"path": rel_to_repo(path), "updated": updated, "blockers": blockers, "items": items,
            "data_rows": _data_rows(lines),
            "open": sum(1 for i in items if not i["done"]), "done": sum(1 for i in items if i["done"])}


def build_todo_index() -> dict:
    reg = get_registry()
    products = {}
    for p in reg.products:
        files = (p.get("knowledge") or {}).get("handover", [])
        docs = []
        for rel in files:
            ap = os.path.join(REPO_ROOT, rel)
            if not os.path.isfile(ap):
                docs.append({"path": rel, "present": False})
                continue
            d = parse_handover(ap)
            d["present"] = True
            docs.append(d)
        present = [d for d in docs if d.get("present")]
        products[p["id"]] = {
            "docs": docs,
            "open": sum(d["open"] for d in present),
            "done": sum(d["done"] for d in present),
            "blockers": [b for d in present for b in d["blockers"]],
            "by_sub": {k: sum(1 for d in present for i in d["items"] if not i["done"] and i["sub"] == k)
                       for k in ("1", "2", "3", "4")},
            # ★ 開工必讀（handoff §1.A）—— 刻意保留的資料排在最前面
            "data_status": [dict(r, doc=d["path"]) for d in present
                            for r in (d.get("data_rows") or [])],
            "latest_update": max((d["updated"] for d in present if d.get("updated")), default=None),
        }
    return {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "products": products}


def main(argv=None) -> int:
    idx = build_todo_index()
    for pid, p in idx["products"].items():
        print(f"{pid}: open={p['open']} done={p['done']} blockers={len(p['blockers'])} by_sub={p['by_sub']} updated={p['latest_update']}")
        for d in p["docs"]:
            if not d.get("present"):
                print(f"   - {d['path']}  (不存在)")
                continue
            print(f"   - {d['path']}  updated={d['updated']} open={d['open']} done={d['done']}")
            for i in [x for x in d["items"] if not x["done"]][:3]:
                print(f"       {i['id']:5} [{i['sub_label']}] {i['summary'][:60]}  ({i['priority'][:10]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
