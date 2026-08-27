# -*- coding: utf-8 -*-
"""把 task session 回覆裡的草稿區塊接進平台的草稿倉。

## 為什麼需要這一支

「草稿／寫檔兩段式」的設計是完整的，兩端也都做好了：

  · **前端**：`tasks/*.json` 的 prompt 明確要求 session 用固定欄位交草稿
  · **後端**：`core/bug_draft.save()`／`core/doc_draft.save()` 收得下，
    `/api/bug-drafts`／`/api/doc-drafts` 列得出來，開單頁按一下就配號寫檔

**中間那一段沒有人做** —— 沒有任何程式讀過 session 的回覆。
2026-08-23 範本實跑 CRUX：探索 session 花了 45 分鐘、交出格式完全正確的
Bug 草稿與機制文件草稿，而 `/api/bug-drafts` 回 `0`。
產出只存在於對話文字裡，等於整條動線在最後一步斷掉。

## 判準：只認「明確宣告」的區塊，不猜

⛔ **不從散文裡推測** —— 草稿會變成真的 Bug 單（配掉一個永不回收的 ID），
   猜錯的代價比漏抓高得多。只接受 fenced 區塊，而且要有足夠的必要欄位。

支援兩種寫法（模板要哪一種都行）：

  · **鍵值式**（現行模板的格式）—— `title      一句話…`，續行縮排
  · **JSON** —— `{"kind": "bug", "title": …}` 或一個陣列

使用方式：`parse(text)` → `{"bugs": [...], "docs": [...]}`；
落點由 `absorb(session_id, product, text)` 負責（會與既有草稿合併，不覆蓋）。
"""
from __future__ import annotations

import hashlib
import json
import re

#: fenced 區塊。照 CommonMark 配對：**開啟幾個字元，收尾就要至少幾個同樣的字元**。
#:
#: ⚠️ 這一條不是為了嚴謹，是實跑撞到的：需求驗證報告的 body 幾乎一定有程式碼區塊
#:    （API 回應、算式明細），而草稿區塊本身也用三個反引號 —— 內層的 ``` 會**提早
#:    關閉外層**，body 被截斷，後面的內容還會被當成一個新的草稿區塊。
#:    所以模板的草稿區塊改用**四個**反引號，而這裡要認得任意長度。
_FENCE = re.compile(
    r"(?ms)^(?P<f>`{3,}|~{3,})[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?$\n(?P<b>.*?)\n(?P=f)[`~]*[ \t]*\r?$")

#: `key   value` 的鍵。⚠️ 鍵一定在**行首、無縮排**，續行則必須縮排 ——
#: 少了這條，Bug 的 `steps` 裡那幾行編號會被當成新的鍵。
_KV = re.compile(r"^[ ]{0,4}([a-z_]{3,14})[ \t]{1,}(.*)$")
#: 鍵名獨佔一行、內容全在續行（多行欄位如 `code` 最自然的寫法）。
#: ⛔ `_KV` 要求鍵名後至少一個空白，所以 `code` 單獨一行**完全不匹配** ——
#:    整段內容會被當成上一個欄位的續行，而且不會報錯（2026-08-26 實測）。
#:    只認 `_KNOWN_KEYS` 裡的鍵：放寬成「任何小寫字」的話，
#:    正文裡一個孤零零的「steps」就會開一個新欄位。
_KV_BARE = re.compile(r"^[ ]{0,4}([a-z_]{3,14})[ \t]*$")

#: 模板用到的欄位。**縮排 ≤4 且落在這個集合裡**才容許當新鍵 ——
#:
#: ⚠️ 2026-08-23：session 為了對齊把 `preconditions` 縮了一格，
#:    整行被當成 `surface` 的續行，於是 `surface` 的值變成
#:    "backend\\npreconditions 總監1（…）已登入"。**而且不會報錯。**
#:    純靠縮排太脆；純靠鍵名又會把 steps 內文誤判成鍵 —— 兩個條件一起用。
_KNOWN_KEYS = {
    "kind", "product", "path", "title", "why", "body", "topic", "report_kind",
    "index_section", "index_desc", "section", "cells",
    "module", "severity", "steps", "expected", "actual", "evidence", "prechecks",
    "surface", "preconditions", "markers", "pom_hints", "note", "behavior",
    # ⭐ `verified`：這條案例在站台上實際跑過了嗎（2026-08-24 起 `write_cases` 要求填）
    "verified",
    # ⭐ `code`：這條案例的**程式碼本體**（2026-08-26 起 `write_cases` 要求交）。
    #    ⚠️ 內容必須縮排 ≥6 —— `_KV` 認的是「縮排 ≤4 ＋ 小寫鍵名」，
    #       而 Python 碼的 `    actual = …`／`    expected = …` 剛好命中，
    #       會被當成新欄位而把整段碼從中間切斷（且不會報錯）。
    "code",
    # ⭐ `wrote`：session **自己已經寫好並跑過**的檔案路徑（2026-08-26 起的主路徑）。
    #    有它就代表「邊寫邊測」那條路走完了，平台不再落檔、只驗收。
    "wrote",
    # ⭐ `kind case_run` 的欄位：整檔跑兩次的結果 ＋ 「本來就該紅」的登記
    #    ⚠️ 名字**不可以含數字** —— `_KV` 的鍵名是 `[a-z_]{3,14}`，
    #       叫 `run1`／`run2` 會整個認不得（而且不報錯，草稿就靜靜地掉了）。
    "full_run", "rerun", "known_fail",
}

#: Bug 草稿的必要欄位（缺就不當草稿看）
_BUG_REQUIRED = ("title",)
_BUG_ENOUGH = ("steps", "actual", "expected")

_DOC_KINDS = ("doc", "handover", "report", "skill")


#: 草稿區塊的第一個鍵一定是 `kind  <型別>`（模板如此，`_as_*` 也依賴它）。
#: 這是**圍欄之外的第二個錨點** —— 見下方 `_blocks` 的說明。
_KIND_LINE = re.compile(r"(?m)^kind[ \t]+(bug|handover|report|doc|case|requirement|perf)[ \t]*\r?$")


def _blocks(text: str) -> list[str]:
    """回傳草稿區塊。**圍欄優先，抓不到就用 `kind` 當錨點補救。**

    ⚠️ 為什麼需要補救：模型偶爾會把收尾圍欄與後文寫在同一行
      （2026-08-25 實跑：`` ```登入成功。直接導到… ``）。那一行不算收尾，
      於是外層圍欄一路吃下去，把後面**格式完全正確**的草稿區塊當成收尾用掉，
      三筆產出就這樣靜靜地沒了。
      ⛔ 修「認得壞掉的 markdown」不是重點 —— 重點是**產出不可以無聲消失**。
    """
    text = text or ""
    out, spans = [], []
    for m in _FENCE.finditer(text):
        b = m.group("b")
        if b.strip():
            out.append(b)
            spans.append(m.span())

    def covered(i):
        return any(a <= i < z for a, z in spans)

    for m in _KIND_LINE.finditer(text):
        if covered(m.start()):
            continue
        # 從這一行往下收，遇到圍欄行或連續空行就停 —— 鍵值式區塊不需要圍欄也讀得出來
        lines, started = [], text[m.start():].splitlines()
        blank = 0
        for ln in started:
            if re.match(r"^[ \t]*(`{3,}|~{3,})", ln):
                break
            if not ln.strip():
                blank += 1
                if blank >= 2:
                    break
            else:
                blank = 0
            lines.append(ln)
        if lines:
            out.append("\n".join(lines).rstrip())
    return out


def _parse_kv(block: str) -> dict:
    """鍵值式區塊 → dict。續行（縮排的行）併進上一個鍵。

    ⚠️ 續行**不可以逐行 `strip()`** —— 那會把 markdown 的相對縮排壓平
       （巢狀清單、縮排的程式碼區塊整段毀掉），而且**寫檔不會報錯**。
       正確做法是收原始行，最後只砍掉共同的那一層縮排（2026-08-23 實跑）。
    """
    from textwrap import dedent

    heads: dict[str, str] = {}
    tails: dict[str, list] = {}
    key = None
    for line in block.split("\n"):
        if not line.strip():
            if key:
                tails[key].append("")
            continue
        m = _KV.match(line)
        bare = None if m else _KV_BARE.match(line)
        if bare and bare.group(1) in _KNOWN_KEYS:
            key = bare.group(1)
            heads[key] = ""
            tails[key] = []
            continue
        if m and (not line[:1].isspace() or m.group(1) in _KNOWN_KEYS):
            key = m.group(1)
            val = m.group(2).strip()
            # ⚠️ session 常用 YAML 的塊標記（`body     |` 之後才是內容）——
            #    照收的話 body 的第一行會是一個孤零零的「|」。
            heads[key] = "" if val in ("|", "|-", "|+", ">", ">-") else val
            tails[key] = []
        elif key:
            tails[key].append(line.rstrip())
    out: dict[str, str] = {}
    for k, head in heads.items():
        body = dedent("\n".join(tails[k])) if tails[k] else ""
        text = (head + "\n" + body) if (head and body) else (head or body)
        if text.strip():
            out[k] = text.strip("\n").rstrip()
    return out


def _parse_json(block: str) -> list[dict]:
    try:
        got = json.loads(block.strip())
    except ValueError:
        return []
    if isinstance(got, dict):
        return [got]
    if isinstance(got, list):
        return [x for x in got if isinstance(x, dict)]
    return []


def _sig(*parts) -> str:
    return hashlib.sha1("｜".join(str(p or "") for p in parts).encode("utf-8")).hexdigest()[:16]


#: 開單前三問的鍵（`bug-report` §3.9）。切分靠它們自己，不靠分隔符。
_PRECHECK_KEYS = ("is_spec", "already_known", "sample_power")
_PRECHECK_KV = re.compile(
    r"(%s)\s*[=：:]\s*(.*?)(?=(?:%s)\s*[=：:]|$)"
    % ("|".join(_PRECHECK_KEYS), "|".join(_PRECHECK_KEYS)), re.S)


def _prechecks(raw) -> dict:
    """`is_spec=否（…）／already_known=否／sample_power=部分…` → dict。

    ⚠️ 分隔符要吃全形頓號、斜線與換行 —— 模板沒有規定，session 三種都會用。
    """
    if isinstance(raw, dict):
        return {k: str(v) for k, v in raw.items()}
    text = str(raw or "")
    out: dict[str, str] = {}
    # ★ 切在**下一個問的鍵**之前，不要猜分隔符 ——
    #   模板沒規定分隔符，實跑看過 `／`、換行、`；` 三種，
    #   而漏切的後果是三問的答案全擠進第一問（2026-08-23）。
    for m in _PRECHECK_KV.finditer(text):
        out[m.group(1)] = m.group(2).strip().strip("；;、,／/").strip()
    if out:
        return out
    for chunk in re.split(r"[／/\n]|、(?=[a-z_]{3,}=)", text):
        m = re.match(r"\s*([a-z_]{3,20})\s*[=：:]\s*(.+)$", chunk.strip(), re.S)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _as_bug(d: dict, product: str) -> dict | None:
    if not all(d.get(k) for k in _BUG_REQUIRED):
        return None
    if not any(d.get(k) for k in _BUG_ENOUGH):
        return None
    if d.get("kind") in _DOC_KINDS:
        return None
    return {
        "signature": _sig(d.get("title")),
        "nodeid": "",                       # session 來源沒有案例粒度
        "title": d.get("title", "")[:120],
        "product": _norm_product(d.get("product") or product),
        "module": d.get("module", ""),
        "surface": d.get("surface") or "探索",
        "severity": d.get("severity") or "中",
        "message": d.get("actual", ""),
        "steps": d.get("steps", ""),
        "expected": d.get("expected", ""),
        "actual": d.get("actual", ""),
        "evidence": d.get("evidence", ""),
        "prechecks": _prechecks(d.get("prechecks")),
        "count": 1,
        "filed_as": "",
    }


def _as_doc(d: dict, product: str) -> dict | None:
    kind = d.get("kind")
    if kind not in _DOC_KINDS:
        # 沒宣告 kind 時，要有 path ＋ body 才算文件草稿
        if not (d.get("path") and d.get("body")):
            return None
        kind = "doc"
    if kind == "doc" and not d.get("path"):
        return None
    if kind == "skill":
        # skill 是「表格裡的一列」——沒有 cells 就沒有東西可寫
        if not d.get("cells"):
            return None
        # 只認這兩節；沒寫或寫錯一律當意圖對照（指路），因為那一節是自動的、
        # 錯了刪掉就好；猜成不變量反而會把它送進「等你按」而卡住
        if (d.get("section") or "") not in ("intent", "invariant"):
            d = dict(d, section="intent")
    if kind == "handover" and not (d.get("body") or d.get("cells")):
        return None
    # ⚠️ report 的必要欄位是 body ＋ topic，**不是 path** —— 檔名由平台在寫檔當下
    #    向 `new_bug_doc.py` 取（`CLAUDE.md` §6 第 4 條），session 自己拼的一律不採用。
    # ⚠️ `topic` 只有**檔名帶主題**的那兩種需要（需求驗證／效能報告）——
    #    JIRA 重驗報告的檔名是「類型＋日期」，沒有主題可填（2026-08-23）。
    if kind == "report":
        if not d.get("body"):
            return None
        if (d.get("report_kind") or "requirement") != "report" and not d.get("topic"):
            return None
    return {
        "kind": kind,
        "signature": _sig(kind, d.get("path") or d.get("topic"), d.get("title")),
        "product": _norm_product(d.get("product") or product),
        "title": d.get("title", ""),
        "path": d.get("path", ""),
        "section": d.get("section") or ("intent" if kind == "skill" else "todo"),
        # 意圖對照表可能拆成好幾張分類表（CRUX 有七張）—— session 要指定哪一張
        "group": d.get("group", ""),
        "topic": d.get("topic", ""),
        "report_kind": d.get("report_kind") or "requirement",
        "body": d.get("body", ""),
        "cells": _cells(d.get("cells")),
        "rows": _rows(d.get("cells")),     # ⭐ 一張表可能有很多列
        "why": d.get("why", ""),
        "written_as": "",
    }


#: 提示模板裡那一行**欄位說明**的字樣。session 常把它原樣抄回來當第一列，
#: 不濾掉的話交接檔會多出一列「對象 | 站台與帳號 | 狀態 | 記於」的假資料。
_HEADER_WORDS = {
    "對象", "站台與帳號", "狀態", "記於", "站台", "帳號",
    "建立/修改了什麼", "在哪個站台與帳號", "還原了沒", "刻意保留的屬哪一張單",
    "待辦內容", "為什麼還沒做", "下一步", "本次任務",
    "要裁定的問題", "卡在誰身上", "影響哪幾項驗證",
}


def _cells(raw) -> list:
    """`A | B | C` → `["A","B","C"]`（單列）。

    ⚠️ session 交回來的是一行文字，而寫檔那一段會 `" | ".join(cells)` ——
       原樣交出去會被**逐字元** join（一列變成「建 | 立 | 了 | 什 | 麼」）。
    """
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw]
    if not raw:
        return []
    return [x.strip() for x in re.split(r"[|｜]", str(raw)) if x.strip()]


def _is_header_row(cells: list) -> bool:
    """這一列是不是**複述提示模板的欄位說明**（而不是真的資料）。"""
    if not cells:
        return True
    plain = [re.sub(r"[（(].*?[）)]", "", c).strip() for c in cells]
    return all(c in _HEADER_WORDS for c in plain if c)


def _looks_like_header(first: list, rest: list) -> bool:
    """結構判準：**多列時**，第一列每一欄都很短而後面明顯長 → 那是表頭。

    ⛔ 靠字面清單認表頭必然漏 —— 2026-08-23 實跑三次，第三次 session 把
       「待辦內容」寫成「**待驗內容**」就破功了，交接檔多一列
       `| T66 | 待驗內容 |`（還佔掉一個編號）。

    誤殺的是「每一欄都不到 8 個字」的資料列 —— 那種列本來也沒有資訊量，
    代價遠低於漏抓。
    """
    if not rest or not first:
        return False
    if any(len(c) > 8 for c in first):
        return False
    longest = max((len(c) for row in rest for c in row), default=0)
    return longest > 12


def _json_rows(raw):
    """整段是 JSON 陣列 → 明確的列，不要按行切。回 None 表示「不是這種」。

    ★ 2026-08-24 實跑（收尾體檢）：session 把**一列**寫成跨行的 JSON 陣列，
      而 `_rows()` 是按行切的 —— 那一列被拆成三列寫進交接檔，每一列都只有片段
      （`["補 CRUX-001 回歸案例",` ／ `"regression 欄…` ／ `"高"]`），
      **而且沒有任何錯誤訊息**。這與 `_rows` 檔頭記的 2026-08-23 那次是同一種失效：
      形狀猜錯了，而錯得很安靜。

    ⚠️ 只認兩種：**純量的陣列**（一列）與**陣列的陣列**（多列）。
       其餘一律回 None 交還給按行切的老路 —— 不要在這裡自作聰明。
    """
    s = str(raw or "").strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    try:
        v = json.loads(s)
    except Exception:                       # noqa: BLE001  不是合法 JSON 就走老路
        return None
    if not isinstance(v, list) or not v:
        return None
    if all(isinstance(x, list) for x in v):
        return [[str(c).strip() for c in row] for row in v]
    if all(not isinstance(x, (list, dict)) for x in v):
        return [[str(x).strip() for x in v]]
    return None


def _rows(raw) -> list:
    """`cells` → **多列**。

    ★ 2026-08-23 實跑：探索 session 交回來的是一整張表（欄位說明 ＋ 三列資料），
      而平台當成一筆吞下去 —— 存進去的 `cells` 變成
      `['建立/修改了什麼', ..., '刻意保留的屬哪一張單\n三码定位 357（…）', ...]`。
      寫進交接檔就是一列爆掉的表格，而且**沒有任何錯誤**。
    """
    if isinstance(raw, (list, tuple)):
        raw = "\n".join(" | ".join(str(x) for x in r) if isinstance(r, (list, tuple))
                        else str(r) for r in raw)
    # ⚠️ 整段是一個 JSON 陣列時，那是**一列**，不是多列 —— 見 `_json_rows`。
    j = _json_rows(raw)
    if j is not None:
        return j
    parsed = [_cells(line) for line in str(raw or "").split("\n")]
    skip = set()
    for i, cells in enumerate(parsed):
        if _is_separator(cells):
            # ★ markdown 分隔列（`--- | --- |`）本身要丟，**它前面那一列是表頭**，
            #   也要丟 —— 這比認字樣可靠得多（session 會自己造欄位名）。
            skip.add(i)
            if i:
                skip.add(i - 1)
    out = []
    for i, cells in enumerate(parsed):
        if i in skip or not cells or _is_header_row(cells):
            continue
        out.append(cells)
    # 結構判準：第一列看起來像表頭就丟掉（字面清單認不出的變體）
    if len(out) > 1 and _looks_like_header(out[0], out[1:]):
        out = out[1:]
    return out


def _is_separator(cells: list) -> bool:
    """markdown 表格的分隔列：`| --- | :--- |`。"""
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells)


def _pom_key(product: str) -> str:
    """POM 索引的鍵是**平台 slug**（`crux`），草稿的 `product` 是**權威 id**（`CRUX`）。

    ⛔ 不轉的話 `flat_methods()` 回 0 筆，於是**每一個 pom_hints 都被當成模型編的**
       而濾掉 —— 產碼只好走 `pytest.skip("找不到對應的 Page Object 方法")`。
       2026-08-25 那批 22 條案例全數變成骨架，這是其中一個成因。
    ⚠️ 方向與 `bugs_file._authoritative_id` 相反（那裡要 id）—— 兩邊都要，別搞混。
    """
    if not product:
        return product
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if product in (p.get("id"), p.get("product_id"), p.get("label")):
                return p.get("id") or product
    except Exception:                       # noqa: BLE001
        pass
    return product


def _pom_hints(raw, product: str) -> list:
    """`"Cls.method, Cls.other"` → 生成器要的 dict 清單。

    ⚠️ 形狀要與 `generators/` 產出的一致（`{cls, method, args, doc}`）——
       交回字串的話產碼會在 `m.get("args")` 當場炸（2026-08-23 實跑）。
    ⛔ **只留 POM 索引裡真的存在的方法** —— 模型編出來的方法名會產出
       叫不動的程式碼（`generators/claude.py` 的 `_keep_real_pom` 同一條紀律）。
    """
    if isinstance(raw, str):
        names = [x.strip() for x in re.split(r"[,，、\n]+", raw) if x.strip()]
    elif isinstance(raw, (list, tuple)):
        names = [x for x in raw if x]
    else:
        return []
    try:
        from core.pom_index import flat_methods
        real = {"%s.%s" % (m.get("cls"), m.get("method")): m
                for m in (flat_methods(_pom_key(product)) or [])}
    except Exception:                       # noqa: BLE001
        real = {}
    out = []
    for n in names:
        if isinstance(n, dict):             # 已經是對的形狀
            out.append(n)
            continue
        hit = real.get(str(n).strip())
        if hit:
            out.append(hit)
    return out


def _as_lines(raw) -> list:
    """一段文字（常自帶「1. 2. 3.」）→ 一行一列。已經是清單就照收。

    與 `web_ui/api/bugs_file._as_steps` 同一件事 —— 那邊 2026-08-23 就修了，
    案例這一邊漏掉（同一個 bug 的兩個載體）。
    """
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    out = []
    for line in str(raw or "").split("\n"):
        line = line.strip()
        if line:
            out.append(re.sub(r"^\d+[.、)]\s*", "", line))
    return out


def _as_case(d: dict, product: str) -> dict | None:
    """`kind case` → 動線 D 的案例形狀（與 `generators/` 的產出同構）。

    ⭐ 欄位刻意與 `generators/rulebased.py` 一致 —— 收進來的草稿要能直接
       走「③產碼 → ④寫檔 → `--collect-only` 驗證」，不必再轉一次形狀。
    """
    if d.get("kind") != "case":
        return None
    if not d.get("title"):
        return None
    markers = d.get("markers")
    if isinstance(markers, str):
        markers = [x.strip() for x in re.split(r"[,，、/／\s]+", markers) if x.strip()]
    hints = _pom_hints(d.get("pom_hints"), d.get("product") or product)
    return {
        "title": d.get("title", "")[:120],
        "product": _norm_product(d.get("product") or product),
        "surface": d.get("surface") or "backend",
        "kind": d.get("behavior") or "verify",
        # ⛔ **一定要是清單** —— `generators/rulebased` 對它們 `enumerate()`，
        #    交字串進去會被**逐字元**展開（2026-08-25 實跑：3285 行、80 KB，
        #    整檔幾乎全是「# 步驟 1：1／# 步驟 2：.」這種一個字一列的註解）。
        #    ⚠️ 本函式的 docstring 寫「欄位刻意與 rulebased 一致」，但一直沒真的一致。
        "preconditions": _as_lines(d.get("preconditions")),
        "steps": _as_lines(d.get("steps")),
        "expected": d.get("expected", ""),
        "markers": markers or ["smoke"],
        "pom_hints": hints,
        # ⭐ 信心由 `verified` 決定（2026-08-24 起 `write_cases` 會開瀏覽器實跑）。
        #    ⛔ **最高只給 medium** —— `verified: yes` 是 session 自己說的，
        #       `high` 保留給真的在平台上執行過並綠燈的案例。
        #    ⚠️ 沒填 `verified` 一律當沒跑過（舊格式、或它跳過了那一步）。
        "verified": _verified(d.get("verified")),
        "confidence": "medium" if _verified(d.get("verified")) == "yes" else "low",
        # ⭐ session 自己寫的程式碼；有就直接用，沒有才退回規則式產碼（見 `case_writer.preview`）
        "code": (d.get("code") or "").rstrip() or None,
        # ⭐ session 已經寫進 repo 並跑過的檔案 —— 有它平台就不落檔，只驗收
        "wrote": (d.get("wrote") or "").strip() or None,
        "note": d.get("note") or "由任務 session 推導，判準需人工確認",
        "source_line": d.get("title", ""),
    }


def _as_run(d: dict, product: str) -> dict | None:
    """`kind case_run` → 整檔執行的回報。

    ⛔ `full_run` 是必要的 —— 沒有它就代表**整檔根本沒跑過**，
       而逐條跑抓不到互相影響（共用 fixture、前一條沒還原站台狀態）。
    """
    if d.get("kind") != "case_run" or not d.get("full_run"):
        return None
    kf = d.get("known_fail") or ""
    if str(kf).strip() in ("無", "none", "None", "-", ""):
        kf = ""
    return {
        "product": _norm_product(d.get("product") or product),
        "wrote": (d.get("wrote") or "").strip(),
        "full_run": str(d.get("full_run") or "").strip(),
        "rerun": str(d.get("rerun") or "").strip(),
        # ⚠️ 原文照留 —— 這是要給人核對的東西，不要自作聰明去解析成結構
        "known_fail": str(kf).strip(),
        "signature": "case_run:%s" % (d.get("wrote") or d.get("full_run") or "")[:80],
    }


def _verified(raw) -> str:
    """`verified` 欄位正規化 → yes／partial／no。認不得的一律當 `no`。"""
    v = str(raw or "").strip().lower()
    if v.startswith(("yes", "y", "是", "有")):
        return "yes"
    if v.startswith(("partial", "部分", "一部")):
        return "partial"
    return "no"


def _norm_product(pid: str) -> str:
    """草稿的產品一律存**權威 id**（`CRUX`），不要一下 slug 一下 id。

    ⚠️ 2026-08-23 UI 走查：待開單清單的「產品」欄同時出現 `CRUX` 與 `crux`
       —— 同一欄兩種寫法，看起來像兩個產品；而**配號要用權威 id**
       （用 slug 會取不到號，見 `bugs_file._authoritative_id`）。
    """
    if not pid:
        return pid
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if pid in (p.get("id"), p.get("product_id"), p.get("label")):
                return p.get("product_id") or p.get("label") or pid
    except Exception:                       # noqa: BLE001
        pass
    return pid


def parse(text: str, product: str = "") -> dict:
    """回 {"bugs": [...], "docs": [...], "cases": [...]}，三者都可能是空的。"""
    bugs, docs, cases, runs = [], [], [], []
    for block in _blocks(text):
        candidates = _parse_json(block) or [_parse_kv(block)]
        for d in candidates:
            if not d:
                continue
            run = _as_run(d, product)
            if run:
                runs.append(run)
                continue
            case = _as_case(d, product)
            if case:
                cases.append(case)
                continue
            doc = _as_doc(d, product)
            if doc:
                docs.extend(_expand_rows(doc))
                continue
            bug = _as_bug(d, product)
            if bug:
                bugs.append(bug)
    for i, c in enumerate(cases, 1):
        c["id"] = "C%02d" % i
    # ⭐ **接不住就要講** —— 回覆裡有幾個 `kind` 錨點、實際解析出幾筆，對不上就報數。
    #    ⛔ 先前是靜靜地掉：session 交了三筆正確的草稿，平台一筆都沒接、也沒吭聲，
    #       產出只活在對話文字裡（2026-08-25 補拍任務實跑）。
    seen = len(_KIND_LINE.findall(text or ""))
    made = len(bugs) + len(docs) + len(cases) + len(runs)
    return {"bugs": _dedupe(bugs), "docs": _dedupe(docs), "cases": cases,
            "runs": _dedupe(runs), "missed": max(0, seen - made)}


def _expand_rows(doc: dict) -> list[dict]:
    """`handover` 的多列 → 多筆草稿（各自落檔、各自取號）。

    ⛔ 不合併成一筆 —— 交接檔一列就是一件事，人要能逐列決定寫不寫。
    """
    rows = doc.pop("rows", None) or []
    if doc.get("kind") != "handover" or len(rows) <= 1:
        if rows:
            doc["cells"] = rows[0]
        return [doc]
    out = []
    for i, cells in enumerate(rows, 1):
        d = dict(doc)
        d["cells"] = cells
        d["signature"] = "%s-%d" % (doc["signature"], i)
        d["title"] = "%s（%d/%d）" % (doc.get("title") or "", i, len(rows))
        out.append(d)
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for x in items:
        if x["signature"] in seen:
            continue
        seen.add(x["signature"])
        out.append(x)
    return out


def absorb(session_id: str, product: str, text: str) -> dict:
    """解析並存進該 session 的草稿倉（**與既有的合併，不覆蓋**）。

    ⚠️ 合併而非覆蓋 —— 一個 session 會來回好幾輪，
       第二則回覆把第一則的草稿洗掉的話，人按下「落單」時才會發現東西不見了。
       已經落過單的（`filed_as` 有值）尤其不能被覆蓋。
    """
    from core import bug_draft, doc_draft

    got = parse(text, product)
    src = {"kind": "session", "id": session_id}
    added = {"bugs": 0, "docs": 0, "cases": 0, "runs": got.get("runs") or []}

    if got["cases"]:
        # ⭐ 仍然建一個 spec_draft —— 它是**寫檔的輸入**（`case_writer.commit()`
        #    吃的就是 draft），也是「這批案例是誰、什麼時候、從哪來的」的紀錄，
        #    案例瀏覽器的「新寫入待確認」就是從這裡列出來的。
        #    ⚠️ 2026-08-24 起 `#/require` 已移除，它不再是給人編輯的中間態。
        from core import spec_draft
        d = spec_draft.create(
            requirement="（由任務 session 推導，見對話 %s）" % session_id[:8],
            product=product, source_ref="session:%s" % session_id,
            title=got["cases"][0]["title"][:60])
        spec_draft.put_cases(d["id"], got["cases"], generated_by="task-session")
        added["cases"] = len(got["cases"])
        added["spec_draft_id"] = d["id"]

    if got["bugs"]:
        prev = bug_draft.read(src) or {}
        by_sig = {d.get("signature"): d for d in prev.get("drafts") or []}
        for b in got["bugs"]:
            if b["signature"] in by_sig:
                continue                     # 已經有了（可能已落單），不動
            by_sig[b["signature"]] = b
            added["bugs"] += 1
        if added["bugs"]:
            bug_draft.save(src, {"drafts": list(by_sig.values())})

    if got["docs"]:
        prev = doc_draft.read(src) or {}
        by_sig = {d.get("signature"): d for d in prev.get("drafts") or []}
        for d in got["docs"]:
            if d["signature"] in by_sig:
                continue
            by_sig[d["signature"]] = d
            added["docs"] += 1
        if added["docs"]:
            doc_draft.save(src, {"drafts": list(by_sig.values())})

    # ⭐ 一路帶到結果確認 —— 「有幾筆沒接住」是人唯一能發現產出掉了的線索
    added["missed"] = got.get("missed", 0)
    return added
