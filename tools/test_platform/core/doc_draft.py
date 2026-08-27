"""文件草稿 → 寫檔：探索產出的機制文件、收尾補做的交接檔內容。

用途
    計畫 E-1b 的表格列了**五種**寫入型產出，而先前只做了兩種：

        開 Bug 單          → `core/bug_draft.py`     ✅
        撰寫案例          → `core/case_writer.py`    ✅
        探索（機制文件）  → **沒有實作**             ← 本檔
        收尾補做（交接檔）→ **沒有實作**             ← 本檔
        探索（覆蓋矩陣）  → 同上，走 `kind="doc"`

    症狀與那兩個一樣：session 產得出內容，但**介面上沒有任何地方能把它寫下來**。
    使用者只能自己複製貼上到編輯器 —— 那正是「草稿／寫檔兩段式」要消滅的手工。

三種 kind
    · `doc`      —— 新增或覆寫 `docs/<產品>/<檔名>.md`（機制文件、覆蓋矩陣）
    · `handover` —— **附加**一列到交接檔的 §2 待辦或 §5 測試資料現況
    · `report`   —— 寫進 `docs/<產品>/bugs/_reports/`（需求驗證報告／效能測試報告）。
                    ⛔ **檔名一律問 `scripts/new_bug_doc.py`**，不可自己拼
                    （2026-08-23 新增，配合「需求驗證」任務）

⛔ 三條紀律（與 Bug 那條動線同源）
    ① **草稿不寫檔** —— session 只產內容，寫檔一律由平台在人確認後執行。
    ② **編號當下取** —— 交接檔的 T／D／B 編號在**寫入的那一刻**才用
       `scripts/next_todo_id.py` 取，不可以由 session 事先推算
       （多 session 併行時沒有機制擋重複，`commit` skill 配套④）。
    ③ **不覆蓋既有內容** —— `handover` 一律附加到節末；`doc` 覆寫既有檔時
       要人明確確認（`overwrite=True`），預設拒絕。

使用方式
    from core import doc_draft
    doc_draft.save(source, {"drafts": [...]})     # session 交回來的草稿
    doc_draft.read_all()                          # 待寫檔清單（UI 用）
    doc_draft.preview(item)                       # 看會寫成什麼樣，不寫檔
    doc_draft.commit(item)                        # 真的寫
"""
from __future__ import annotations

import io
import os
import re
import subprocess

from core import paths
from core.jsonio import read_json, write_json_atomic
from core.paths import REPO_ROOT, python_exe, rel_to_repo
from core.registry import get_registry

DRAFT_FILE = "doc_drafts.json"

_KINDS = ("doc", "handover", "report", "skill")

# 產品 skill 可以附加的兩節。第三欄＝**要不要人按**（見本檔開頭的表）。
#
# ⚠️ 落點不是固定的：CRUX 的意圖對照表已經拆到
#    `.claude/skills/crux/references/意圖對照表.md`（原本佔 SKILL.md 的 77%），
#    而 SKILL.md §2 只剩一張「分類｜列數｜大致涵蓋」的摘要表。
#    附加到摘要表就完全錯了 —— 所以 `skill_target()` 要先找 references。
_SKILL_SECTIONS = {
    "intent":    ("2", "★ 意圖對照表", False),
    "invariant": ("1", "必記的不變量", True),
}

# `report` 的檔名**不可以自己拼** —— `bugs/_reports/` 的檔名是「類型＋日期」的固定組合，
# 同一天兩個 session 各驗一批就必然撞名，而 `docs/**/bugs/` 不版控，覆蓋掉沒有 git 可以救
# （`CLAUDE.md` §6 第 4 條，事故發生在 2026-08-14）。
# 一律問 `scripts/new_bug_doc.py` 要路徑；真的寫檔時再用 `--reserve` 原子佔位。
_REPORT_KINDS = {"requirement": "需求驗證報告", "perf": "效能測試報告",
                 "report": "JIRA_Bug驗證報告"}
# 交接檔可以附加的節 —— 只開這幾個口，其餘節次要人自己編輯。
#
# ⚠️ §2 底下有**四個子節**，它們就是拿來分流「今天能不能動手」的：
#      2.1 可立即動手 ／ 2.2 等外部裁定 ／ 2.3 等他人處理 ／ 2.4 被 blocker 擋住
#    只指到「§2」的話會附加到整節的最後一張表（＝ 2.4），
#    於是一筆「現在就能做」的事被寫進「被擋住」那一格，接手的人會直接跳過它
#    （2026-08-23 實測）。
_SECTIONS = {
    "todo":     ("2", "2.1", "★ 待辦總覽 → 可立即動手", "T"),
    "todo_ext": ("2", "2.2", "★ 待辦總覽 → 等外部裁定", "T"),
    "todo_who": ("2", "2.3", "★ 待辦總覽 → 等他人處理", "T"),
    "todo_blk": ("2", "2.4", "★ 待辦總覽 → 被 blocker 擋住", "T"),
    "data":     ("5", None,  "測試資料現況", None),
}


# ---------------------------------------------------------------- 來源與儲存
def _dir_of(source) -> str:
    """草稿檔放哪。與 `bug_draft` 同一套來源結構。"""
    src = source if isinstance(source, dict) else {"kind": "session", "id": source}
    if src.get("kind") == "run":
        from core import run_store as rs
        return rs.run_dir(src["id"])
    d = os.path.join(paths.SESSIONS_DIR, src["id"])
    os.makedirs(d, exist_ok=True)
    return d


def _cells(raw) -> list:
    """`cells` 一律正規化成 list。

    ⚠️ session 交回來的是**一行文字**（`A | B | C`），而寫檔那一段是
       `" | ".join(str(c) for c in cells)` —— 直接吃字串會**逐字元**join，
       一列變成「建 | 立 | 了 | 什 | 麼」。形狀在入口收，比在出口猜安全。
    """
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw]
    if not raw:
        return []
    return [x.strip() for x in re.split(r"[|｜]", str(raw)) if x.strip()]


def read(source) -> dict:
    return read_json(os.path.join(_dir_of(source), DRAFT_FILE), {}) or {}


def save(source, data: dict) -> dict:
    """寫某一個來源的文件草稿。缺欄位一律補成固定形狀 —— **形狀固定才顯示得出來**。"""
    src = source if isinstance(source, dict) else {"kind": "session", "id": source}
    out = {"source": src, "drafts": []}
    for d in (data.get("drafts") or []):
        kind = d.get("kind") if d.get("kind") in _KINDS else "doc"
        out["drafts"].append({
            "kind": kind,
            "signature": d.get("signature") or (d.get("path") or d.get("title") or "")[:120],
            "product": d.get("product") or "",
            "title": d.get("title") or "",
            "path": d.get("path") or "",          # doc：相對 docs/<產品>/ 的檔名
            "section": d.get("section") or "todo",  # handover：todo|data
            "index_desc": d.get("index_desc") or "",     # doc：要登記進 INDEX 的描述
            "index_section": d.get("index_section") or "",  # doc：登記到哪個子節
            "topic": d.get("topic") or "",        # report：檔名裡的主題
            "report_kind": d.get("report_kind") or "requirement",
            "body": d.get("body") or "",
            "cells": _cells(d.get("cells")),      # handover：表格列的各欄
            "why": d.get("why") or "",            # 為什麼要寫這一筆（給人判斷用）
            "written_as": d.get("written_as") or "",
        })
    write_json_atomic(os.path.join(_dir_of(src), DRAFT_FILE), out)
    return out


def read_all() -> list[dict]:
    """所有來源還沒寫檔的草稿。⚠️ run 與 session 兩處都要掃。"""
    import glob
    out = []
    for pat in (os.path.join(paths.RUNS_DIR, "*", DRAFT_FILE),
                os.path.join(paths.SESSIONS_DIR, "*", DRAFT_FILE)):
        for p in sorted(glob.glob(pat)):
            data = read_json(p, {}) or {}
            src = data.get("source") or {"kind": "session",
                                         "id": os.path.basename(os.path.dirname(p))}
            for d in data.get("drafts", []):
                if d.get("written_as") or d.get("dropped"):
                    continue
                out.append(dict(d, source=src))
    return out


def discard(source, signature_: str, why: str = "") -> bool:
    """捨棄一筆草稿。**不刪除**，只標記 —— 判斷過程本身值得留。

    ⛔ 沒有這個動作的話，判定「不該開」的草稿會永遠躺在清單裡
       （2026-08-23 UI 走查：`test_必定失敗` 那筆探針殘留就是）。
       清單愈長愈髒，久了沒有人願意看 —— 那才是真正的損失。
    """
    data = read(source)
    hit = False
    for d in data.get("drafts", []):
        if d.get("signature") == signature_:
            d["written_as"] = "（已捨棄）"
            d["dropped"] = True
            d["dropped_why"] = why or "（未填理由）"
            hit = True
    if hit:
        write_json_atomic(os.path.join(_dir_of(source), DRAFT_FILE), data)
    return hit


def mark_written(source, signature_: str, where: str) -> None:
    data = read(source)
    for d in data.get("drafts", []):
        if d.get("signature") == signature_:
            d["written_as"] = where
    if data:
        write_json_atomic(os.path.join(_dir_of(source), DRAFT_FILE), data)


# ---------------------------------------------------------------- 目標路徑
def _product(pid: str) -> dict | None:
    for p in get_registry().products:
        if p.get("virtual"):
            continue
        if pid in (p.get("id"), p.get("product_id"), p.get("label")):
            return p
    return None


def _docs_dir(pid: str) -> str | None:
    p = _product(pid)
    if not p:
        return None
    d = (p.get("knowledge") or {}).get("docs_dir")
    return os.path.join(REPO_ROOT, *d.split("/")) if d else None


def _skill_dir(pid: str) -> str | None:
    p = _product(pid)
    if not p:
        return None
    name = (p.get("knowledge") or {}).get("skill") or p.get("skill") or p.get("id")
    return os.path.join(REPO_ROOT, ".claude", "skills", name) if name else None


def skill_target(item: dict) -> str | None:
    """這一筆 skill 草稿要寫進哪個檔。

    ⚠️ 意圖對照表可能已經被拆到 `references/意圖對照表.md` —— 有就寫那裡，
       沒有才寫 `SKILL.md` 的 §2。不變量一律在 `SKILL.md`。
    """
    d = _skill_dir(item.get("product"))
    if not d:
        return None
    if (item.get("section") or "intent") == "intent":
        ref = os.path.join(d, "references", "意圖對照表.md")
        if os.path.isfile(ref):
            return ref
    return os.path.join(d, "SKILL.md")


def _handover_path(pid: str) -> str | None:
    p = _product(pid)
    if not p:
        return None
    hs = (p.get("knowledge") or {}).get("handover") or []
    return os.path.join(REPO_ROOT, *hs[0].split("/")) if hs else None


# ---------------------------------------------------------------- docs/INDEX.md
#
# ★ 為什麼「寫檔」還不夠：`writeback` skill 的「回寫完成的四個必做」第一條就是
#   **登記 `docs/INDEX.md`** —— 而 `CLAUDE.md` 舉過的教訓正是「期數還原 SOP 早就寫在
#   docs/CRUX/ 裡，但索引描述沒提到它，其他 session 依意圖搜尋完全找不到，**等於沒寫**」。
#
#   平台先前只在寫完後回一句「記得登記 docs/INDEX.md」—— 那是**靠自律的規範**，
#   而本工作區已經證明過那種規範必然漂移（`new_bug_doc.py` 的存在就是同一個教訓）。
#   所以這裡把它變成寫檔流程的一部分。
INDEX_PATH = os.path.join(REPO_ROOT, "docs", "INDEX.md")


def index_sections(pid: str) -> list[str]:
    """該產品在 `docs/INDEX.md` 底下有哪些子節（`### …`）。"""
    p = _product(pid)
    if not p or not os.path.isfile(INDEX_PATH):
        return []
    label = p.get("product_id") or p.get("label") or pid
    docs_dir = ((p.get("knowledge") or {}).get("docs_dir") or "").split("/")[-1]
    out, inside = [], False
    for ln in io.open(INDEX_PATH, encoding="utf-8").read().split("\n"):
        if ln.startswith("## "):
            inside = bool((label and label in ln) or (docs_dir and docs_dir in ln))
        elif inside and ln.startswith("### "):
            out.append(ln[4:].strip())
    return out


def index_plan(item: dict) -> dict:
    """要不要／能不能登記進 INDEX。回 {ok, section, row, reason}。

    ⛔ **挑不到節就不寫** —— 「附加到產品節的最後一張表」看起來可行，
       但那正是 `_append_to_section` 踩過的坑（東西被寫進不相干的子節，
       接手的人再也找不到它）。挑不到就明講，讓人自己選。
    """
    name = os.path.basename(target_of(item) or "")
    if not name:
        return {"ok": False, "reason": "還不知道會寫到哪個檔"}
    desc = (item.get("index_desc") or item.get("why") or "").strip()
    if not desc:
        return {"ok": False,
                "reason": "草稿沒有 index_desc —— 寫檔後請自己補一列到 docs/INDEX.md"}
    secs = index_sections(item.get("product"))
    if not secs:
        return {"ok": False, "reason": "docs/INDEX.md 裡找不到這個產品的分區"}
    want = (item.get("index_section") or "").strip()
    hit = next((x for x in secs if x == want), None)
    if not hit and want:
        hit = next((x for x in secs if want in x or x in want), None)
    if not hit:
        return {"ok": False, "section_options": secs,
                "reason": "index_section 對不上任何子節（可選：%s）" % "、".join(secs)}
    try:
        cur = io.open(INDEX_PATH, encoding="utf-8").read()
    except OSError as e:                    # noqa: BLE001
        return {"ok": False, "reason": "讀不到 docs/INDEX.md：%s" % e}
    if name in cur:
        return {"ok": False, "already": True,
                "reason": "`%s` 已經在 INDEX 裡了 —— 描述要不要更新請人自己判斷" % name}
    return {"ok": True, "section": hit, "row": "| `%s` | %s |" % (name, desc)}


def _append_index(section: str, row: str) -> bool:
    """把一列附加到 `### <section>` 底下那張表的末尾。"""
    lines = io.open(INDEX_PATH, encoding="utf-8").read().split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("### ") and ln[4:].strip() == section:
            start = i
            break
    if start is None:
        return False
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") or lines[i].startswith("### "):
            end = i
            break
    last = None
    for i in range(start, end):
        if lines[i].startswith("|") and not lines[i].startswith("| ---"):
            last = i
    if last is None:
        return False
    lines.insert(last + 1, row)
    io.open(INDEX_PATH, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return True


def report_path(pid: str, topic: str, report_kind: str = "requirement",
                *, reserve: bool = False) -> tuple[str, str]:
    """向 `scripts/new_bug_doc.py` 取報告路徑。回 (絕對路徑, 來源說明)。

    ⛔ **不可以自己拼檔名**（`CLAUDE.md` §6 第 4 條）—— 撞名時它會自動加「_第N批」，
       而 `bugs/` 不版控，覆蓋掉沒有 git 可以救。
    ⭐ `reserve=True` 走 `--reserve`：**原子建檔（O_EXCL）**，
       真正寫檔時用它，免得「預覽拿到名字 → 人看了兩分鐘 → 期間被別人佔走」。
    """
    p = _product(pid)
    prod = (p or {}).get("product_id") or pid
    script = os.path.join(REPO_ROOT, "scripts", "new_bug_doc.py")
    py = python_exe()
    argv = [py, script, "--product", prod, "--kind", report_kind]
    if report_kind in ("requirement", "perf"):
        argv += ["--topic", topic or "未命名"]
    if reserve:
        argv.append("--reserve")
    try:
        r = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    except Exception as e:                  # noqa: BLE001
        return "", "取檔名失敗：%s" % e
    lines = [x.strip() for x in (r.stdout or "").split("\n") if x.strip()]
    if r.returncode != 0 or not lines:
        return "", "new_bug_doc.py 取檔名失敗：%s" % ((r.stderr or r.stdout or "").strip()[:200])
    rel = lines[-1]                          # 檔頭寫明：最後一行就是可寫入的相對路徑
    return os.path.join(REPO_ROOT, *rel.replace("\\", "/").split("/")), "new_bug_doc.py"


def section_header(path: str, section_no: str, sub: str | None = None) -> list:
    """讀出目標（子）節那張表的表頭欄位。

    ★ 為什麼要讀：交接檔的欄位是**每個產品自己定的**（CRUX 的 §5 是
       「對象｜站台｜狀態｜記於」），而 session 交回來的 `cells` 欄數不一定對得上。
       欄數不符寫下去，Markdown 會把整張表渲染歪 —— 而那**很難事後發現**。
    """
    try:
        lines = io.open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return []
    start, end = _section_bounds(lines, section_no, sub)
    if start is None:
        return []
    for i in range(start, end):
        if lines[i].startswith("|") and i + 1 < end and lines[i + 1].startswith("| ---"):
            return [c.strip() for c in lines[i].strip().strip("|").split("|")]
    return []


def skill_header(path: str, section_no: str, group: str = "") -> list:
    """skill 檔案裡那張表的表頭（用 `_skill_bounds` 定位）。"""
    try:
        lines = io.open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return []
    start, end = _skill_bounds(lines, section_no, group)
    for i in range(start, end):
        if lines[i].startswith("|") and i + 1 < end and lines[i + 1].startswith("| ---"):
            return [c.strip() for c in lines[i].strip().strip("|").split("|")]
    return []


def append_skill_row(path: str, section_no: str, row: str, group: str = "") -> bool:
    """把一列附加到 skill 檔案裡那張表的末尾。"""
    lines = io.open(path, encoding="utf-8").read().split("\n")
    start, end = _skill_bounds(lines, section_no, group)
    last_row = None
    for i in range(start, end):
        if lines[i].startswith("|") and not lines[i].startswith("| ---"):
            last_row = i
    if last_row is None:
        return False
    lines.insert(last_row + 1, row)
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return True


def align_cells(cells: list, header: list) -> tuple[list, str]:
    """把 `cells` 對齊到表頭欄數。回 (對齊後, 說明)。

    ⛔ **不丟資訊**：多的併進最後一欄、少的補空欄，並把做了什麼講出來。
    """
    cells = [str(c) for c in (cells or [])]
    if not header or len(cells) == len(header):
        return cells, ""
    if len(cells) > len(header):
        keep = cells[:len(header) - 1] + ["；".join(cells[len(header) - 1:])]
        return keep, ("交回來 %d 欄、表頭只有 %d 欄 —— 多的已併進最後一欄"
                      % (len(cells), len(header)))
    return (cells + [""] * (len(header) - len(cells)),
            "交回來 %d 欄、表頭有 %d 欄 —— 不足的補空欄" % (len(cells), len(header)))


def target_of(item: dict) -> str | None:
    if item.get("kind") == "report":
        # ⚠️ 這裡**不取號** —— 列表會對每一筆呼叫它，而取號是要開子行程的；
        #    真正的檔名在 `preview()`／`commit()` 當下才取（也才不會過期）。
        return None
    if item.get("kind") == "handover":
        return _handover_path(item.get("product"))
    if item.get("kind") == "skill":
        return skill_target(item)
    base = _docs_dir(item.get("product"))
    if not base:
        return None
    return os.path.join(base, doc_name(item.get("path") or item.get("title")))


def doc_name(raw: str) -> str:
    """把 session 交回來的 `path` 正規化成一個**檔名**。

    ★ 2026-08-23 實跑：session 交回
      `docs/CRUX/CRUX_賠率變動設置.md（既有檔案，以下為要更新的段落，非整份替換）`，
      而原本的做法只是把不合法字元刪掉 —— 目標變成
      `docsCRUXCRUX_賠率變動設置.md（既有檔案，…）.md` 這種垃圾檔名，
      **而且它「寫得出來」**，於是 docs/ 底下就多一個沒人看得懂的檔。
    """
    name = str(raw or "未命名").strip()
    name = re.sub(r"[（(][^）)]*[）)]\s*$", "", name).strip()   # 砍掉尾巴的括號說明
    name = name.replace("\\", "/").rstrip("/").split("/")[-1]   # 只留最後一段
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", name).strip()
    if not name:
        name = "未命名"
    if not name.endswith(".md"):
        name += ".md"
    return name


# ---------------------------------------------------------------- 編號
def next_id(handover_path: str, kind: str = "T") -> tuple[str, str]:
    """向 `scripts/next_todo_id.py` 取號。回 (編號, 來源說明)。

    ⛔ **一定要在寫入的當下取** —— 多 session 併行時沒有任何機制擋重複，
       而 `commit` skill 配套④ 明訂改號的是後寫入者。
    """
    script = os.path.join(REPO_ROOT, "scripts", "next_todo_id.py")
    py = python_exe()
    try:
        r = subprocess.run([py, script, "--handover", handover_path, "--kind", kind],
                           cwd=REPO_ROOT, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        m = re.search(r"\*\*([TDB]\d+)\*\*", r.stdout or "")
        if m:
            return m.group(1), "next_todo_id.py"
    except Exception:                       # noqa: BLE001
        pass
    return "", "取號指令不可用 —— 請手動編號"


# ---------------------------------------------------------------- 預覽與寫檔
def preview(item: dict) -> dict:
    """組出「會寫成什麼樣」，不寫檔。回 {ok, path, mode, text, errors}。"""
    errs = []
    if item.get("kind") not in _KINDS:
        errs.append("kind 必須是 doc、handover、report 或 skill")
    if not item.get("product"):
        errs.append("要指定產品")
    if item.get("kind") == "report":
        if not (item.get("body") or "").strip():
            errs.append("報告是空的 —— body 要有內容")
        if errs:
            return {"ok": False, "errors": errs}
        rk = item.get("report_kind") or "requirement"
        target, src = report_path(item["product"], item.get("topic", ""), rk)
        if not target:
            return {"ok": False, "errors": [src]}
        return {"ok": True, "errors": [], "kind": "report",
                "path": rel_to_repo(target), "abs": target,
                # ⚠️ 講明「最終檔名寫入當下才定」—— 預覽到寫入之間隔著人的判斷時間，
                #    這中間別的 session 可能已經佔走同一個名字。
                "mode": "新增 %s（檔名由 %s 取，寫入當下會再取一次並原子佔位）"
                        % (_REPORT_KINDS.get(rk, "報告"), src),
                "exists": os.path.isfile(target),
                "text": (item.get("body") or "").rstrip() + "\n"}
    target = target_of(item)
    if not target:
        errs.append("找不到這個產品的 docs 目錄、交接檔或 skill —— 確認 config/products.json")
    if errs:
        return {"ok": False, "errors": errs}

    if item["kind"] == "doc":
        exists = os.path.isfile(target)
        wm = write_mode(item, exists)
        return {"ok": True, "errors": [], "kind": "doc",
                "path": rel_to_repo(target), "abs": target,
                "mode": {"new": "新增檔案", "append": "附加到既有檔的末尾",
                         "replace": "整檔覆寫"}[wm],
                "write_mode": wm,
                # ⛔ append 不算覆寫 —— 不必要人再確認一次「要覆寫嗎」
                "exists": exists and wm == "replace",
                # ★ 一併預告「會不會登記進 INDEX」—— 沒登記的文件別人搜尋不到
                "index": index_plan(item),
                "text": (item.get("body") or "").rstrip() + "\n"}

    if item["kind"] == "skill":
        sec, sec_title, needs_human = _SKILL_SECTIONS.get(
            item.get("section") or "intent", _SKILL_SECTIONS["intent"])
        group = str(item.get("group") or "").strip()
        header = skill_header(target, sec, group)
        cells = list(item.get("cells") or [])
        # 不變量那張表第一欄是流水號（`| # | 不變量 | 用途／後果 |`）——
        # 由平台接號，不要讓 session 自己猜（它看不到別人剛加的那一列）。
        num = ""
        if header and header[0].strip() in ("#", "＃"):
            num = str(_next_skill_no(target, sec, group))
            cells = [num] + cells
        cells, aligned = align_cells(cells, header)
        row = "| " + " | ".join(str(c) for c in cells) + " |"
        return {"ok": True, "errors": [], "kind": "skill",
                "path": rel_to_repo(target), "abs": target,
                "mode": "附加一列到 §%s" % sec_title,
                "section": sec, "sub": None, "id": num, "id_source": "",
                "needs_human": needs_human, "group": group,
                "mode_detail": ("分類「%s」" % group) if group else "（未指定分類 —— 會接在最後一張表）",
                "header": header, "aligned": aligned, "text": row}

    sec, sub, sec_title, id_kind = _SECTIONS.get(item.get("section") or "todo",
                                                 _SECTIONS["todo"])
    bug_id, id_src = ("", "")
    cells = list(item.get("cells") or [])
    if id_kind:
        bug_id, id_src = next_id(target, id_kind)
        cells = [bug_id or "?"] + cells
    header = section_header(target, sec, sub)
    cells, aligned = align_cells(cells, header)
    row = "| " + " | ".join(str(c) for c in cells) + " |"
    return {"ok": True, "errors": [], "kind": "handover",
            "path": rel_to_repo(target), "abs": target,
            "mode": "附加一列到 §%s" % sec_title,
            "section": sec, "sub": sub, "id": bug_id, "id_source": id_src,
            # ★ 表頭讓人看得出「這一列的每一格該放什麼」；欄數對不上時講明怎麼對齊的
            "header": header, "aligned": aligned,
            "text": row}


def _section_bounds(lines: list, section_no: str, sub: str | None = None):
    """(起, 迄) 行號。找不到回 (None, None)。子節優先。"""
    start = end = None
    if sub:
        for i, ln in enumerate(lines):
            if re.match(r"^###\s*§?%s[\s．.]" % re.escape(sub), ln):
                start = i
            elif start is not None and re.match(r"^#{2,3}\s", ln):
                end = i
                break
        if start is not None and end is None:
            end = len(lines)
    if start is None:
        for i, ln in enumerate(lines):
            m = re.match(r"^##\s*§?(\d+)\.", ln)
            if m:
                if m.group(1) == section_no:
                    start = i
                elif start is not None:
                    end = i
                    break
    if start is None:
        return None, None
    return start, (end if end is not None else len(lines))


def _skill_bounds(lines: list, section_no: str, group: str = ""):
    """skill 檔案裡那張表的 (起, 迄)。三層退路，見本函式所在改動的說明。

    ⚠️ 最後一層退路是「檔案最後一張表」—— **不能回 (None, None)**，
       否則 session 交了草稿、人按了寫入，卻什麼都沒發生（而且沒有錯誤訊息）。
    """
    if group:
        g = group.strip()
        start = None
        for i, ln in enumerate(lines):
            if re.match(r"^#{2,4}\s", ln) and g and g in ln:
                start = i
            elif start is not None and re.match(r"^#{2,4}\s", ln):
                return start, i
        if start is not None:
            return start, len(lines)
    start, end = _section_bounds(lines, section_no)
    if start is not None:
        return start, end
    # 最後一層：整份文件（`_append_to_section` 會挑裡面最後一列表格）
    return 0, len(lines)


def _next_skill_no(path: str, section_no: str, group: str = "") -> int:
    """不變量表的下一個流水號 ＝ 現有最大值 ＋ 1。

    ⛔ **在寫入的當下算**，不要在草稿產生時就決定 —— 這與 Bug ID／交接檔編號
       是同一條紀律（`CLAUDE.md` §6 第 3 條）：多 session 併行時，
       別的 session 隨時可能已經用掉你以為還空著的號。
    """
    try:
        lines = io.open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return 1
    start, end = _skill_bounds(lines, section_no, group)
    if start is None:
        return 1
    top = 0
    for i in range(start, end):
        if not lines[i].startswith("|") or lines[i].startswith("| ---"):
            continue
        first = lines[i].strip().strip("|").split("|")[0].strip()
        m = re.match(r"^(\d+)$", first)
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def write_mode(item: dict, exists: bool) -> str:
    """`new`／`append`／`replace`。

    ★ 為什麼要有 `append`：探索最常見的產出是「**補一節到既有機制文件**」——
      2026-08-23 那一輪交回來的兩筆 doc 草稿都自己講明「非整份替換／僅新增一小節」。
      而平台當時只有「整檔覆寫」一種寫法：按下去就是**用一段片段蓋掉整份文件**。

    判準：既有檔 ＋ 內容不是一份完整文件（沒有 H1 檔頭）→ 附加，不覆寫。
    ⛔ 拿不準時一律偏向 append —— 附加的錯誤看得見也刪得掉，覆寫是不可逆的。
    """
    want = (item.get("write_mode") or "").strip()
    if want in ("new", "append", "replace"):
        return want if exists or want != "append" else "new"
    if not exists:
        return "new"
    body = (item.get("body") or "").lstrip()
    return "replace" if body.startswith("# ") else "append"


def _append_to_section(path: str, section_no: str, row: str, sub: str | None = None) -> bool:
    """把一列附加到目標（子）節**最後一張表**的末尾。

    ⚠️ `sub` 一定要指定到子節（如 `2.1`）—— §2 底下有四個子節，
       只指到 §2 會附加到整節的最後一張表（＝ §2.4 被 blocker 擋住），
       把「現在就能做」的事寫進「被擋住」那一格（2026-08-23 實測）。
    """
    lines = io.open(path, encoding="utf-8").read().split("\n")
    start, end = _section_bounds(lines, section_no, sub)
    if start is None:
        return False
    last_row = None
    for i in range(start, end):
        if lines[i].startswith("|") and not lines[i].startswith("| ---"):
            last_row = i
    at = (last_row + 1) if last_row is not None else end
    lines.insert(at, row)
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return True


def is_auto_safe(item: dict) -> tuple[bool, str]:
    """這一筆能不能**自動**落檔？回 (可以嗎, 為什麼)。

    ★ 判準是「**錯了要付什麼代價**」，不是「這件事重不重要」
      （2026-08-23 使用者質疑「為何那麼多要人工確認」之後定的）：

      · 交接檔附加一列 → 多一列，刪掉就好　→ ✅
      · `doc` 附加一節 → 接在檔尾，可回退　→ ✅
      · 驗證報告寫檔 → 不版控、撞名自動讓開　→ ✅
      · `doc` **整檔覆寫** → 蓋掉別人寫的內容　→ ⛔ 要人按
      · Bug 落單 → 燒掉**永不回收**的 ID　→ ⛔ 要人按（那條在 `bug_draft`）
    """
    kind = item.get("kind")
    if kind == "handover":
        return True, "附加一列，可刪"
    if kind == "report":
        return True, "寫進不版控的 _reports/，撞名自動讓開"
    if kind == "skill":
        # ★ 2026-08-24 使用者裁示：**指路自動、規則要人按**。
        #   §2 意圖對照只說「去哪看」，錯了人點過去就發現 —— 它會自我修正。
        #   §1 不變量是「絕對不能搞錯的規則」，而 Claude 每次開場都會讀它：
        #   寫錯一列，之後所有 session 都照錯的做，且沒有人會去驗它。
        if (item.get("section") or "intent") == "invariant":
            return False, ("**必記的不變量**要你確認 —— 它每次對話開場都會被讀到，"
                           "寫錯會讓之後所有 session 照錯的規則做事")
        return True, "意圖對照表附加一列（只指路，不放知識本體），可刪"
    if kind == "doc":
        target = target_of(item)
        if target and os.path.isfile(target) and write_mode(item, True) == "replace":
            return False, "會**整檔覆寫**既有文件 —— 這一種要人確認"
        return True, "新檔或附加到檔尾，可回退"
    return False, "未知的類型"


def auto_commit_all(source) -> list:
    """把某個來源**能自動落檔的**全部寫掉。回每一筆的結果。

    ⛔ 不能自動的（整檔覆寫）原樣留在待寫清單裡，等人按。
    """
    out = []
    data = read(source)
    for d in data.get("drafts", []):
        if d.get("written_as") or d.get("dropped"):
            continue
        ok_auto, why = is_auto_safe(d)
        if not ok_auto:
            out.append({"ok": False, "skipped": True, "why": why,
                        "title": d.get("title", ""), "kind": d.get("kind")})
            continue
        try:
            res = commit(d)
        except Exception as e:                  # noqa: BLE001
            res = {"ok": False, "errors": [str(e)]}
        if res.get("ok"):
            mark_written(source, d.get("signature"), res["path"])
            _mark_auto(source, d.get("signature"))
        out.append(dict(res, title=d.get("title", ""), kind=d.get("kind"),
                        auto=True))
    return out


def _mark_auto(source, signature_: str) -> None:
    """標記「這是平台自動寫的」—— UI 要能區分，人才知道要不要回頭看一眼。"""
    data = read(source)
    for d in data.get("drafts", []):
        if d.get("signature") == signature_:
            d["auto_written"] = True
    if data:
        write_json_atomic(os.path.join(_dir_of(source), DRAFT_FILE), data)


def commit(item: dict, *, overwrite: bool = False) -> dict:
    """真的寫。回 {ok, path, id, errors}。

    ⛔ `doc` 覆寫既有檔要 `overwrite=True` —— 預設拒絕，
       否則一次誤按就蓋掉別人辛苦寫的機制文件（而 `docs/` 有版控，但 session
       產的內容不見得比既有的好）。
    """
    pv = preview(item)
    if not pv.get("ok"):
        return {"ok": False, "errors": pv.get("errors") or ["草稿不完整"]}
    target = pv["abs"]

    if pv["kind"] == "report":
        # ⭐ 寫入當下**重新取號並原子佔位** —— 預覽時拿到的名字可能已經被別人用掉。
        target, src = report_path(item["product"], item.get("topic", ""),
                                  item.get("report_kind") or "requirement",
                                  reserve=True)
        if not target:
            return {"ok": False, "errors": [src]}
        io.open(target, "w", encoding="utf-8", newline="\n").write(pv["text"])
        return {"ok": True, "path": rel_to_repo(target), "id": "",
                "note": "報告寫在 bugs/ 底下（整層不版控）—— 要交出去請走 "
                        "scripts/pack_bug_report.py"}

    if pv["kind"] == "doc":
        if pv["exists"] and not overwrite:
            return {"ok": False, "needs_overwrite": True, "path": pv["path"],
                    "errors": ["%s 已存在 —— 確認要**整檔覆寫**再送一次"
                               "（只是要補一節的話，把 write_mode 設成 append）"
                               % pv["path"]]}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if pv.get("write_mode") == "append":
            # ⭐ 附加：接在檔尾，前面留一個空行分隔
            cur = io.open(target, encoding="utf-8").read().rstrip()
            io.open(target, "w", encoding="utf-8", newline="\n").write(
                cur + "\n\n" + pv["text"])
        else:
            io.open(target, "w", encoding="utf-8", newline="\n").write(pv["text"])
        # ★ 連 INDEX 一起登記 —— `writeback` 四個必做的第一條。
        #   「寫完回一句提醒」等於沒有人會做（`new_bug_doc.py` 就是同一個教訓）。
        plan = pv.get("index") or {}
        if plan.get("ok") and _append_index(plan["section"], plan["row"]):
            note = ("已一併登記 docs/INDEX.md → §%s。產品 skill 的意圖對照表"
                    "由 `kind: skill` 的草稿補（session 應一併交出）" % plan["section"])
        else:
            note = ("⚠️ **沒有登記 docs/INDEX.md**（%s）—— 沒登記的文件別人搜尋不到，"
                    "請自己補一列；產品 skill 的意圖對照表用 `kind: skill` 的草稿補"
                    % (plan.get("reason") or "草稿沒帶登記資訊"))
        return {"ok": True, "path": pv["path"], "id": "", "note": note}

    if pv["kind"] == "skill":
        if not append_skill_row(target, pv["section"], pv["text"], pv.get("group") or ""):
            return {"ok": False,
                    "errors": ["在 %s 找不到可以附加的表格 —— 確認該 skill 有 §%s 那一節"
                               % (pv["path"], pv["section"])]}
    elif not _append_to_section(target, pv["section"], pv["text"], pv.get("sub")):
        return {"ok": False, "errors": ["在 %s 找不到 §%s 這一節" % (pv["path"], pv["section"])]}
    if pv["kind"] == "skill":
        return {"ok": True, "path": pv["path"], "id": pv.get("id", ""),
                "note": "產品 skill 已補一列 —— 到產品頁的「文件」分頁可以打開來看"}
    return {"ok": True, "path": pv["path"], "id": pv.get("id", ""),
            "note": "交接檔的「最後更新」日期記得改成今天"}
