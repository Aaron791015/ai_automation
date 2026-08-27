"""Bug 草稿：run 進終態時，把失敗案例整理成「可以直接開單」的草稿。

★ 為什麼是草稿而不是直接開單（2026-08-21 使用者裁示，理由寫下來免得日後被翻案）：
    走查實測三筆 run 的結果都是「通過 136／失敗 14／略過 9」，而且是**同樣那 14 條**。
    自動開正式單 ＝ 42 張，而 CLAUDE.md 明訂 **Bug ID 永不回收**，改 rejected 也永久佔號。
    更根本的是**測試失敗 ≠ 缺陷** —— 可能是測試碼壞了、環境沒起來、資料被別的 session 動過。
    拆成草稿／開單兩段，「當下證據最完整」這個好處一點不少，而且草稿能做手動開單做不到的兩件事：
      ① **跨 run 去重**（同 nodeid ＋ 同錯誤訊息累計出現次數）
      ② **比對既有活躍單**（提示「這可能是 CRUX-034」，避免重複開）
使用方式：
    from core import bug_draft
    bug_draft.build(run_id)            # run 終態時呼叫，寫 logs/runs/<run_id>/bug_drafts.json
    bug_draft.read(run_id)             # 給 API 用
前置條件：
    · 只處理 `summary.kind == "pytest"` 的 run（perf 沒有「案例」這個粒度）。
    · 既有單由 core.bug_index 提供，**唯讀**。
"""
from __future__ import annotations

import os
import re

from core.jsonio import read_json, write_json_atomic
from core import paths
from core import run_store as rs

DRAFT_FILE = "bug_drafts.json"

def _product_prefixes() -> list[tuple[str, str]]:
    """`tests/<slug>/` → Bug 單的產品名（config/products.json 的 id）。

    ⛔ 不可寫死 —— 範本接的產品對不到任何前綴，
       而舊的預設值是 `"CRUX"`：同事的 `tests/lotto/` 失敗
       會被標成 CRUX，開單時拿 CRUX 的前綴去配號
       （2026-08-23 範本端到端驗收第 ⑧ 步）。
    """
    try:
        from core.registry import get_registry
        out = []
        for p in get_registry().products:
            if p.get("virtual"):
                continue
            pref = ((p.get("knowledge") or {}).get("tests_prefix")
                    or "tests/%s/" % p.get("id"))
            out.append((pref.rstrip("/") + "/", p.get("product_id") or p.get("id")))
        return sorted(out, key=lambda x: -len(x[0]))
    except Exception:                       # noqa: BLE001
        return []
_NOISE = re.compile(r"(0x[0-9a-f]+|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}|\b\d{6,}\b)", re.I)


def bug_product(nodeid: str) -> str:
    """nodeid → Bug 單的產品名（bug_paths.PRODUCTS 的用字，與 registry 的 id 不同）。"""
    for prefix, prod in _product_prefixes():
        if nodeid.startswith(prefix):
            return prod
    # ⚠️ 對不到就回第一個產品（單一產品的工作區這就是對的），
    #    都沒有就回空字串 —— **不可以隨便挑一個具體的產品名**，
    #    這個值會拿去決定開單用哪個 Bug 前綴配號。
    prefixes = _product_prefixes()
    return prefixes[0][1] if len(prefixes) == 1 else ""


def module_of(nodeid: str) -> str:
    """取檔名當模組（tests/crux/test_hold_ratio.py::test_x → hold_ratio）。"""
    head = nodeid.split("::")[0]
    name = os.path.basename(head)
    return re.sub(r"^test_|\.py$", "", name) or head


def signature(nodeid: str, message: str) -> str:
    """去重鍵：nodeid ＋ 抹掉時間戳／位址／長數字後的錯誤訊息首行。

    不抹這些的話，同一個缺陷每次跑都因為訊息帶了不同的期號而被當成新問題。
    """
    first = (message or "").strip().splitlines()[0] if message else ""
    return f"{nodeid}||{_NOISE.sub('#', first)[:180]}"


_CLOSED = {"fixed", "verified", "rejected", "superseded", "not_a_defect"}


def _is_closed(bug: dict) -> bool:
    return (bug.get("status") or "").strip() in _CLOSED


_KEY = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def _base_nodeid(nodeid: str) -> str:
    """去掉 pytest 的參數化後綴（`[chromium]`）—— Bug 單的 regression 欄多半不帶它。"""
    return re.sub(r"\[[^\]]*\]$", "", (nodeid or "").strip())


def _regression_nodeids(text: str | None) -> set[str]:
    """把 regression 欄拆成 nodeid 集合做**精確**比對。

    ⚠️ 不可以用 `nodeid in text` 的子字串比對：一條 nodeid 常是另一條的前綴
       （`::test_a` vs `::test_abc`），會比中不相干的單。
    """
    out = set()
    for tok in re.split(r"[\s,、；;]+", str(text or "")):
        tok = tok.strip("`（）()「」")
        if "::" in tok:
            out.add(_base_nodeid(tok))
    return out


def _match_existing(nodeid: str, title: str, product: str, bugs: list[dict]) -> dict | None:
    """比對既有活躍單，三種線索由強到弱，命中最強的那條就回：

    ① **該單的 regression 欄直接寫著這條 nodeid** —— 這是最硬的證據（守門案例本來就是為它寫的）。
    ② **案例標題或 nodeid 裡出現單號**（本地 `CRUX-034` 或 JIRA `CRUX-934`）——
       實務上回歸案例的標題都會帶單號（例：`test_crux009_…`、「JIRA CRUX-934」），
       這條命中率遠高於模組比對。
    ③ 模組名相符 —— 只當弱提示，因為測試檔名（ledger_level_labels）與
       Bug 單的模組欄（「分類帳報表」）用字本來就不一樣。
    """
    hay = f"{nodeid} {title}"
    same = [b for b in bugs if b.get("product_label") == product]
    base = _base_nodeid(nodeid)
    for b in same:
        if base and base in _regression_nodeids(b.get("regression")):
            return {"id": b["id"], "title": b.get("title", ""), "confidence": "high",
                    "status": b.get("status"), "regressed": _is_closed(b),
                    "why": (f"⚠ 這條就是 {b['id']} 的守門案例，而該單已標為"
                            f"「{b.get('status_label') or b.get('status')}」＝ **回歸**"
                            if _is_closed(b) else "該單的回歸案例就是這一條")}
    keys = {k.upper() for k in _KEY.findall(hay)} | {k.upper().replace("_", "-") for k in
                                                     _KEY.findall(hay.replace("_", "-"))}
    for b in same:
        cand = {b["id"].upper()} | {k.upper() for k in (b.get("jira_keys") or [])}
        hit = keys & cand
        if hit:
            return {"id": b["id"], "title": b.get("title", ""), "confidence": "high",
                    "status": b.get("status"), "regressed": _is_closed(b),
                    "why": (f"⚠ {b['id']} 已標為「{b.get('status_label') or b.get('status')}」，"
                            f"這次又失敗了 ＝ **回歸**，請優先處理"
                            if _is_closed(b) else f"案例名稱含單號 {sorted(hit)[0]}")}
    mod = module_of(nodeid)
    for b in same:
        bm = (b.get("module") or "").strip()
        if bm and (bm in hay or bm.lower() in mod.lower()):
            return {"id": b["id"], "title": b.get("title", ""), "confidence": "low",
                    "why": f"模組相符（{bm}）—— 只是弱提示，請自行確認"}
    return None


def _known_bugs() -> list[dict]:
    """比對用的單子。**含已歸檔（fixed）的單** —— 理由見下。

    ⚠️ 一開始只取活躍單，結果 `CRUX-040`（分類帳占成合计，狀態 fixed、已歸檔）比不中。
       但那正是**最該講出來的一種**：一條標成 fixed 的缺陷又失敗了，那是**回歸**，
       比新缺陷更緊急。所以歸檔的也一起比，只是在提示裡標明它的狀態。
    """
    from core.bug_index import build_bug_index
    idx = build_bug_index(jira="off")
    out = []
    # ⛔ 同樣不寫死 —— slug → 顯示名一律從 registry 拿
    from core.registry import get_registry
    label = {p.get("id"): (p.get("product_id") or p.get("label") or p.get("id"))
             for p in get_registry().products}
    for pid, blk in (idx.get("products") or idx).items():
        if not isinstance(blk, dict) or not blk.get("bugs"):
            continue
        for b in blk["bugs"]:
            out.append({**b, "product_label": label.get(pid, pid)})
    return out


def _with_prechecks(drafts: list) -> list:
    """run 來源的草稿也要有 `prechecks` 欄位（內容為空）。

    ⚠️ 形狀不一致的代價：UI 只能對「有這個鍵」的那一種顯示，
       而本檔自己的原則就是「**形狀固定才顯示得出來**」。
       run 來源沒有三問的答案是**正常**的（它是自動整理的，沒有人做過判斷）——
       但那要**看得到「它沒答」**，不是靜靜地缺一個鍵
       （2026-08-23 路線 1 驗證）。
    """
    for d in drafts:
        d["prechecks"] = normalize_prechecks(d.get("prechecks"))
    return drafts


def build(run_id: str) -> dict:
    """從 run 的失敗案例產草稿。已存在就更新（保留人的勾選與編輯）。"""
    st = rs.read_status(run_id) or {}
    meta = rs.read_meta(run_id) or {}
    summary = st.get("summary") or {}
    if summary.get("kind") != "pytest":
        return {"run_id": run_id, "drafts": [], "note": "非 pytest run，沒有案例粒度可以開單"}

    prev = read(run_id)
    prev_by_sig = {d["signature"]: d for d in prev.get("drafts", [])}
    try:
        bugs = _known_bugs()
    except Exception:
        bugs = []

    env = {k: v for k, v in (meta.get("params") or {}).items()
           if k.endswith("_env") or k.endswith("_director") or k in ("lottery", "game_id")}
    drafts = []
    for c in summary.get("failed_cases") or []:
        nodeid = c.get("nodeid", "")
        msg = c.get("message", "")
        sig = signature(nodeid, msg)
        prior = prev_by_sig.get(sig) or {}
        seen = list(prior.get("seen_in") or [])
        if run_id not in seen:
            seen.append(run_id)
        product = bug_product(nodeid)
        title = prior.get("title") or (c.get("title") or nodeid.split("::")[-1])
        existing = _match_existing(nodeid, title, product, bugs)
        drafts.append({
            "signature": sig,
            "nodeid": nodeid,
            "title": title,
            "product": product,
            "module": module_of(nodeid),
            "surface": prior.get("surface") or "UI 自動化",
            "severity": prior.get("severity") or _guess_severity(msg),
            "message": msg,
            "tool_id": st.get("tool_id"),
            "tool_name": meta.get("tool_name"),
            "command_label": meta.get("command_label"),
            "env": env,
            "run_id": run_id,
            "seen_in": seen,
            "seen_count": len(seen),
            "console": f"/reports/{run_id}/console.log",
            "allure": next((a.get("href") for a in (st.get("artifacts") or [])
                            if a.get("kind") == "html" and a.get("exists")), None),
            "found": (st.get("ended_at") or st.get("started_at") or "")[:10],
            "likely_existing": existing,
            "filed_as": prior.get("filed_as"),      # 已開單者記下 ID，不再重複提示
        })
    payload = {"run_id": run_id, "built_at": rs.now_str(), "drafts": _with_prechecks(drafts),
               "matched_against": len(bugs)}
    write_json_atomic(os.path.join(rs.run_dir(run_id), DRAFT_FILE), payload)
    return payload


def _guess_severity(message: str) -> str:
    """粗略給個預設，人一定會改 —— 但總比每次都從「中」開始好。

    ⚠️ 用字必須與既有 Bug 單一致（高／中／低），不是 high／medium ——
    `scripts/gen_bug_index.py` 依這欄分組，不一致會多出一個假分類。
    """
    m = (message or "").lower()
    if any(k in m for k in ("timeout", "connection", "refused", "no such element", "崩潰", "500")):
        return "高"
    return "中"


def _dir_of(source: dict) -> str:
    """草稿檔放哪。

    ★ 兩種來源（2026-08-23 階段 E-1c 泛化）：
      · `{"kind": "run", "id": <run_id>}`      → run 目錄（**維持原樣**，不影響動線 C）
      · `{"kind": "session", "id": <sid>}`     → `logs/sessions/<sid>/`
        探索任務沒有 run_id，草稿本來無處可放。
    """
    # ⚠️ **先正規化再判型別。**本函式的最後一行已經在接受字串了，
    #    但第一行的 `.get("kind")` 會先對字串丟 `AttributeError`
    #    —— 向後相容只做了一半，而 `web_ui/api/bugs_file.py` 正是傳字串進來的。
    #    症狀：run 結果頁的 `bug-drafts` 端點 500，「從失敗 run 開單」
    #    整條動線直接斷掉（2026-08-23 範本端到端驗收第 ⑧ 步）。
    src = source if isinstance(source, dict) else {"kind": "run", "id": source}
    if src.get("kind") == "session":
        d = os.path.join(paths.SESSIONS_DIR, src["id"])
        os.makedirs(d, exist_ok=True)
        return d
    return rs.run_dir(src["id"])


def read(source) -> dict:
    """讀某一個來源的草稿。`source` 可以是 run_id 字串（向後相容）或 source dict。

    ⚠️ **讀的時候也要正規化** —— 草稿是快取，早於 `prechecks` 這個欄位的檔案
       在野外還存在（實測：原型有 30 筆舊草稿沒有這個鍵）。
       只在 build 時補的話，舊快取永遠是缺的形狀，而 UI 只對「有這個鍵」的顯示。
    """
    data = read_json(os.path.join(_dir_of(source), DRAFT_FILE), {}) or {}
    for d in data.get("drafts") or []:
        d["prechecks"] = normalize_prechecks(d.get("prechecks"))
    return data


# 開單前三問（`bug-report` §3.9）—— **草稿要保留答案，不是只保留結論**。
#
# ⭐ 為什麼：平台起的 session 是**無人看管**的（你按下按鈕就去做別的事了）。
#    「Claude 說它做過三問」和「**你看過它的判斷**」是兩回事，
#    而 `CLAUDE.md` §6：Bug ID 配發後永不回收 —— 燒錯號的代價是永久的。
#    把三個答案攤在開單頁上，按確認之前一眼就能看出它為什麼判定該開。
PRECHECK_QUESTIONS = [
    {"key": "is_spec", "label": "是規格還是缺陷？",
     "hint": "找不到任何人說要改 → 是缺陷；有變更聲明 → 更新文件，不開單"},
    {"key": "already_known", "label": "這現象是不是已經被查證過／撤銷過？",
     "hint": "比對既有活躍單與已撤銷的單，避免重開"},
    {"key": "sample_power", "label": "樣本有沒有鑑別力？",
     "hint": "這批資料能不能區分「真的錯」與「剛好長這樣」"},
]


def normalize_prechecks(raw) -> list[dict]:
    """把 session 交回來的三問答案正規化成固定形狀（缺的補空）。

    ⚠️ 形狀固定才顯示得出來 —— 讓 session 自由發揮的話，
    前端就只能整包丟一段文字，人還是得自己讀完才知道它答了什麼。
    """
    got = {}
    if isinstance(raw, dict):
        got = raw
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("key"):
                got[item["key"]] = item.get("answer") or item.get("value") or ""
    out = []
    for q in PRECHECK_QUESTIONS:
        v = got.get(q["key"])
        out.append({"key": q["key"], "label": q["label"],
                    "answer": (v if isinstance(v, str) else "").strip()})
    return out


def save(source, data: dict) -> dict:
    """寫某一個來源的草稿（探索任務用；run 來源仍走 build()）。

    每一筆草稿的 `prechecks` 一律正規化 —— 沒答的會留空欄位，
    **看得到「它沒答」比看不到這件事重要**。
    """
    for d in (data.get("drafts") or []):
        d["prechecks"] = normalize_prechecks(d.get("prechecks"))
    data.setdefault("source", source if isinstance(source, dict)
                    else {"kind": "run", "id": source})
    write_json_atomic(os.path.join(_dir_of(source), DRAFT_FILE), data)
    return data


def _source_files() -> list[tuple[str, dict]]:
    """(草稿檔路徑, source) —— run 與 session 兩種來源都要掃。

    ⚠️ 只掃 run 目錄的話，探索任務產出的草稿永遠不會被看到。
    """
    import glob
    out = []
    pats = [os.path.join(paths.RUNS_DIR, "*", DRAFT_FILE),
            os.path.join(paths.SESSIONS_DIR, "*", DRAFT_FILE)]
    kinds = ["run", "session"]
    for kind, pat in zip(kinds, pats):
        for path in sorted(glob.glob(pat)):
            data = read_json(path, {}) or {}
            src = data.get("source") or {
                "kind": kind, "id": os.path.basename(os.path.dirname(path))}
            out.append((path, src))
    return out


def read_all() -> list[dict]:
    """列出**所有來源**還沒開單的草稿，**同一個失敗只回一筆**。

    ★ 去重鍵是 `signature`（nodeid ＋ 錯誤訊息）。

    ⛔ 為什麼一定要合併：同一條案例在 6 次執行裡各留一份草稿，UI 就會列
       **6 筆一模一樣的東西**，人得一筆筆判斷、一筆筆按（2026-08-24 走查實見）。
       而「這是不是缺陷」的判斷對象是**那個失敗**，不是「那一次執行」。

    合併規則：
      · 以**最新的一份**當底（訊息、allure、console 連結都取最新那次）
      · `seen_in` 取所有來源的聯集，`seen_count` 隨之更新 —— 這就是「反覆失敗幾次」
      · `sources` 保留全部來源，讓 `discard`／`mark_filed` 能一次掃乾淨
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for path, src in _source_files():
        data = read_json(path, {}) or {}
        for d in data.get("drafts", []):
            if d.get("filed_as") or d.get("dropped"):
                continue                     # 已開單／已捨棄的不再提示
            sig = d.get("signature") or d.get("nodeid") or ""
            cur = dict(d, source=src, sources=[src])
            prev = merged.get(sig)
            if prev is None:
                merged[sig] = cur
                order.append(sig)
                continue
            # 新的蓋舊的（檔案是依 run_id／時間排序掃進來的，後面的比較新）
            seen = list(dict.fromkeys(list(prev.get("seen_in") or [])
                                      + list(cur.get("seen_in") or [])))
            srcs = prev.get("sources", []) + [src]
            cur["seen_in"] = seen
            cur["seen_count"] = len(seen) or 1
            cur["sources"] = srcs
            merged[sig] = cur
    return [merged[k] for k in order]


def is_auto_fileable(draft: dict) -> tuple[bool, str]:
    """這一筆能不能**自動開單**？回 (可以嗎, 為什麼)。

    ★ 判準是「**這個判定是誰做的、有沒有經過三問**」：

      · **session 來源** → 它走過 `bug-report` §3.9 的開單前三問 → ✅ 自動開
      · **run 來源** → 「測試失敗 ≠ 缺陷」，同樣那幾條會反覆失敗 → ⛔ 留草稿

    ⚠️ 「ID 永不回收」不是要人確認的理由 —— 它要求的是**不要回收再用**，
       而自動開單同樣走 `gen_bug_index --next-id`（寫檔當下取），不會撞號。
    """
    src = draft.get("source") or {}
    if (src.get("kind") or "") != "session":
        return False, "run 失敗的草稿留給人判斷（測試失敗 ≠ 缺陷）"
    pre = draft.get("prechecks")
    answered = 0
    if isinstance(pre, dict):
        answered = sum(1 for v in pre.values() if str(v or "").strip())
    elif isinstance(pre, list):
        answered = sum(1 for q in pre if str((q or {}).get("answer") or "").strip())
    if answered < 2:
        return False, "開單前三問只答了 %d 題 —— 判斷不完整，留給人看" % answered
    return True, "session 判定 ＋ 三問已答（%d 題）" % answered


def _sweep(signature_: str, apply) -> int:
    """對**所有來源**裡同一個 signature 的草稿套用 `apply(d)`，回改到幾筆。

    ⛔ 為什麼要掃全部而不是只改傳進來的那個來源：`read_all()` 已經把同一個失敗
       合併成一列，UI 上只有一個按鈕。只標記其中一個來源的話，**另外幾筆下次
       會冒回來** —— 使用者看到的是「按了沒用」。
       判斷的對象是「這個失敗」，不是「這一次執行」。
    """
    n = 0
    for path, _src in _source_files():
        data = read_json(path, {}) or {}
        hit = False
        for d in data.get("drafts", []):
            if d.get("signature") == signature_:
                apply(d)
                hit = True
                n += 1
        if hit:
            write_json_atomic(path, data)
    return n


def discard(source, signature_: str, why: str = "") -> bool:
    """捨棄一筆草稿。**不刪除**，只標記 —— 判斷過程本身值得留。

    ⛔ 沒有這個動作的話，判定「不該開」的草稿會永遠躺在清單裡
       （2026-08-23 UI 走查：`test_必定失敗` 那筆探針殘留就是）。
       清單愈長愈髒，久了沒有人願意看 —— 那才是真正的損失。

    ⚠️ `source` 保留在簽名裡是為了向後相容；實際會掃過**所有**來源（見 `_sweep`）。
    """
    def _apply(d):
        d["filed_as"] = "（已捨棄）"
        d["dropped"] = True
        d["dropped_why"] = why or "（未填理由）"
    return _sweep(signature_, _apply) > 0


def mark_filed(source, signature_: str, bug_id: str) -> None:
    """開單後回填，讓同一批草稿不會被重複開。

    `source` 可以是 run_id 字串（向後相容）或 `{"kind","id"}`，
    但一律掃過**所有**來源 —— 同一個失敗在別次執行留下的草稿也要一起收掉。
    """
    _sweep(signature_, lambda d: d.__setitem__("filed_as", bug_id))
