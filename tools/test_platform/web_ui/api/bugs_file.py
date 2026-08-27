"""開單：把 Bug 草稿寫成一張真的 Bug 單（Demo 落沙箱）。

★ 配號**真的呼叫** `scripts/gen_bug_index.py --next-id`（subprocess、唯讀查詢）——
  CLAUDE.md §6 第 3 條明訂那是唯一的權威取號方式，理由是它會掃到 `old/` 的已歸檔單，
  而 ID 永不回收、漏掉就直接撞號。⛔ 不可用 `ls bugs/` 自行推算。
  沙箱另記「已模擬佔用」的號，避免同一輪連開兩張同號（沙箱的檔不在真實 bugs/ 裡，
  下一次 --next-id 看不到它）。

★ 落點見 `bug_out_dir()` —— Demo 寫沙箱、live 寫 `docs/<產品>/bugs/`。舊說明：
  檔案真的產生、frontmatter 與真實單完全一致，只是不碰 docs/<產品>/bugs/
  （那裡是別的 session 的真資料，而且整層不版控、寫壞沒有 git 可以救）。
  M1 之後要切真實落點只需改那個常數。

使用方式：
    POST /api/bugs/file  {run_id, signature, title?, severity?, module?, surface?, dry_run?}
      dry_run=true（預設）→ 只回預覽（含配到的號與全文），**不寫檔**
      dry_run=false        → 真的寫檔，回 path 與全文
"""
from __future__ import annotations

import io
import os
import re
import subprocess

from flask import Blueprint, request

from core import bug_draft
from core.jsonio import read_json, write_json_atomic
from core.paths import LOGS_DIR, REPO_ROOT, VENV_PYTHON, rel_to_repo
from web_ui.api import fail, ok

bp = Blueprint("bugs_file", __name__)

# 本平台這一次啟動以來配過的號 —— 與 `gen_bug_index --next-id` 取聯集，
# 讓「同一批連開好幾張」不會拿到同一個號（不版控）。
_LEDGER = os.path.join(LOGS_DIR, "_allocated_ids.json")
# ⛔ 前綴一律從 `config/products.json` 取（經 scripts/bug_paths）——
#    寫死的話新接的產品會落回預設值 "CRUX"，樂透的單被配成 CRUX-001
#    （2026-08-23 範本端到端驗收）。
def _prefix_of(product: str) -> str:
    try:
        import sys
        sp = os.path.join(REPO_ROOT, "scripts")
        if sp not in sys.path:
            sys.path.insert(0, sp)
        import bug_paths
        # ⚠️ 與 `core/bug_index.py` 同一個理由：常數是 import 當下凍結的，
        #    而平台長駐。接完新產品之後不重讀，這裡就對不到前綴而退回
        #    `product.upper()[:8]` —— 那會決定這張單燒掉哪一組號，而 ID 永不回收。
        bug_paths.reload_products()
        pre = (bug_paths.ID_PREFIX or {}).get(product)
        if pre:
            return pre
    except Exception:                    # noqa: BLE001
        pass
    # ⚠️ 對不到就用產品名本身，**不要挑一個別的產品的前綴** ——
    #    那個前綴會決定這張單燒掉誰的號，而 ID 永不回收。
    return (product or "BUG").upper()[:8]


def bug_out_dir(product: str) -> str:
    """開單目錄 ＝ 產品的 `docs/<產品>/bugs/`。

    ⛔ 判準來自 `scripts/bug_paths.py`（Bug 目錄結構的單一事實來源）——
       平台不自己拼路徑，否則它與 `gen_bug_index`／`lint_docs` 會各走各的。
    """
    import sys
    sp = os.path.join(REPO_ROOT, "scripts")
    if sp not in sys.path:
        sys.path.insert(0, sp)
    import bug_paths
    d = bug_paths.bugs_dir(product)
    if not d:
        raise ValueError("產品 %s 沒有登記 —— 確認 config/products.json" % product)
    return d
_NEXT_RE = re.compile(r"([A-Z]+)-(\d+)")

# 環境欄要寫人看得懂的字（真實單寫的是「QAT」「總監2」，不是 crux_director=director2）
_ENV_LABEL = {"crux_env": "CRUX 環境", "crux_director": "總監站台", "wbot_env": "投注機器人環境",
              "qixing_env": "七星環境", "qixing_lottery": "彩種", "lottery": "彩種", "game_id": "彩種"}
_ENV_VALUE = {"qat": "QAT", "stg": "STG", "director1": "總監1", "director2": "總監2",
              "director3": "總監3", "lucky5": "幸運五星彩", "sevenstar": "七星彩", "p5": "排列五"}


# 期號長這樣（`26097`／`19387`），彩種名直接用 `_ENV_VALUE` 裡登記過的
_ISSUE_RE = re.compile(r"(?<!\d)\d{5,6}(?!\d)")


def _env_block(product: str, env, steps_text: str) -> list:
    """【Test Environment】的內容 —— 讓 RD 拿著就能重現（`bug-report` §4）。

    ⭐ 站台名從 `_ENV_VALUE` 反查（`總監2` → `director2`）—— **不硬編產品詞彙**，
       這支程式碼會跟著範本發給別人，而別人的產品沒有「總監」這種東西。
    ⛔ 找不到就寫「待補」，**不要挑一個站台填進去** ——
       RD 會照著去錯的站台，然後回報「重現不了」，那比缺資訊更難查。
    ⚠️ 提醒只在**真的缺**的時候出現：恆常出現的提醒等於沒有提醒
       （同 `lint_bug_assets` W7 的取捨：訊號被雜訊淹沒，人就學會忽略）。
    """
    raw = env if isinstance(env, dict) else {}
    txt = " ".join([str(env or "")] + [str(v) for v in raw.values()] + [steps_text or ""])
    # 中文站台名 → 設定檔的節點鍵（`總監2` → `director2`）
    key = next((k for k, label in _ENV_VALUE.items()
                if k.startswith("director") and label in txt), None)
    if not key:
        key = next((k for k in ("director1", "director2", "director3") if k in txt), None)
    out, node = [], None
    if key:
        try:
            from core.jsonio import read_json
            from core.paths import REPO_ROOT
            cfg = read_json(os.path.join(REPO_ROOT, "config", "environments.json"), {}) or {}
            node = ((cfg.get(product.lower()) or {}).get("qat") or {}).get(key)
        except Exception:                   # noqa: BLE001
            node = None
    if node:
        d = node.get("director") or {}
        out.append("- 後台：`%s`（`%s` / `%s`）"
                   % (node.get("backend_url", ""), d.get("username", ""), d.get("password", "")))
        if node.get("frontend_url"):
            mb = node.get("test_member") or {}
            out.append("- 前台：`%s`（`%s` / `%s`）"
                       % (node["frontend_url"], mb.get("username", ""), mb.get("password", "")))
    else:
        out.append("- ⚠️ **站台 URL 與帳密待補** —— RD 沒有這兩樣就重現不了"
                   "（見 `config/environments.md`）")
    # 彩種／期號：找得到就不囉嗦
    has_game = any(v in txt for k, v in _ENV_VALUE.items() if not k.startswith("director")
                   and v not in ("QAT", "STG"))
    if not (has_game or _ISSUE_RE.search(txt)):
        out.append("- ⚠️ **彩種與期號待補** —— 依重現當下的實際值填")
    return out


def _authoritative_id(product: str) -> str:
    """平台 slug（`crux`）→ 權威產品 id（`CRUX`）。

    ⛔ `gen_bug_index.py` 收的是**權威 id** —— 傳 slug 進去它會找不到產品，
       指令失敗，然後（修好之前）平台會靜默退回一個**必然撞號**的流水號。
    """
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if product in (p.get("id"), p.get("product_id"), p.get("label")):
                return p.get("product_id") or p.get("label") or product
    except Exception:                       # noqa: BLE001
        pass
    return product


def _invalidate() -> None:
    """清索引快取。⛔ 失敗不影響寫入結果（它只是讓畫面早一點跟上）。"""
    try:
        from web_ui.api.knowledge import invalidate
        invalidate("bugs", "todos", "knowledge")
    except Exception:                       # noqa: BLE001
        pass


def next_id(product: str) -> tuple[str, str]:
    """回 (bug_id, 來源說明)。真實查詢 ＋ 沙箱佔用取較大者。

    ⛔ 取號**指令**是唯一權威（它看得到 `old/` 的已歸檔單，而 ID 永不回收）。
       指令拿不到號時回 `("", 原因)` —— 呼叫端必須拒絕開單，
       ⛔ **不可以自己編一個號**（2026-08-23：編出來的是 `CRUX-001`，早就被用掉了）。
    """
    real = _real_next_id(_authoritative_id(product))
    if not real:
        return "", ("取不到號 —— `scripts/gen_bug_index.py %s --next-id` 沒有回應。"
                    "⛔ 平台不會自己編號（ID 永不回收，編錯就是撞號）"
                    % _authoritative_id(product))
    used = (read_json(_LEDGER, {}) or {}).get(product) or []
    prefix = _prefix_of(product)
    nums = [int(m.group(2)) for m in (_NEXT_RE.match(x) for x in used) if m]
    if real:
        m = _NEXT_RE.match(real)
        if m:
            nums.append(int(m.group(2)) - 1)      # real 已是「下一個可用」，先退回已用最大
            prefix = m.group(1)
    n = (max(nums) + 1) if nums else 1
    src = "gen_bug_index.py --next-id"
    if used and int(_NEXT_RE.match(real).group(2)) <= n:
        # 本平台這一輪已經配過、但索引還沒重建時的備援去重
        src += " ＋ 本平台已配過的號"
    return f"{prefix}-{n:03d}", src


def _real_next_id(product: str) -> str | None:
    script = os.path.join(REPO_ROOT, "scripts", "gen_bug_index.py")
    py = VENV_PYTHON if os.path.exists(VENV_PYTHON) else "python"
    try:
        r = subprocess.run([py, script, product, "--next-id"], cwd=REPO_ROOT,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    except Exception:
        return None
    m = _NEXT_RE.search(r.stdout or "")
    return m.group(0) if m else None


# ── markdown → JIRA wiki 標記 ────────────────────────────
# Bug 單是**拿去轉貼 JIRA** 的（使用者 2026-08-26 裁示），所以正文直接寫 wiki 標記。
_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
#: markdown 表格的分隔行。⚠️ JIRA 的 `|` 本來就是表格語法，這一行會被渲染成
#:  「一列全是破折號的儲存格」—— 留著就是一列垃圾。
_TABLE_SEP = re.compile(r"^\|[\s\-:|]+\|[ \t]*$")


def _to_jira(text: str) -> str:
    """把正文的 markdown 轉成 JIRA wiki 標記。

    ⭐ 圍欄**先切出來**，內容原樣搬進 `{code}` —— 程式碼裡的 `**` 是次方運算，
       跟著轉會把它改壞。
    """
    out, last = [], 0
    for m in _FENCE.finditer(text):
        out.append(_plain_to_jira(text[last:m.start()]))
        out.append("{code}\n%s{code}" % m.group(1))
        last = m.end()
    out.append(_plain_to_jira(text[last:]))
    return "".join(out)


def _plain_to_jira(seg: str) -> str:
    seg = _BOLD.sub(r"*\1*", seg)
    lines, out = seg.split("\n"), []
    for ln in lines:
        if _TABLE_SEP.match(ln) and out and out[-1].lstrip().startswith("|"):
            # 上一行是表頭 → 改成 `||a||b||`，分隔行本身丟掉
            cells = [c.strip() for c in out[-1].strip().strip("|").split("|")]
            out[-1] = "||" + "||".join(cells) + "||"
            continue
        out.append(ln)
    return "\n".join(out)


_SHOT_RE = re.compile(r"[^\s，、。；;：:（）()\[\]｜|]+\.(?:png|jpg|jpeg)", re.I)


def _shots_dir_hint(source) -> str:
    """截圖現在落在哪 —— session 來源給它自己的目錄，run 來源沒有截圖概念。

    ⚠️ 2026-08-25 之前這裡寫死「還在 `.playwright-mcp/`」，而那是**共用暫存**：
       MCP 會清、別的 session 也會清。訊息指到已經被清掉的目錄，比不提醒更糟 ——
       人照著去找，找不到，才發現東西早就沒了。
    """
    sid = source.get("id") if isinstance(source, dict) and source.get("kind") == "session" else None
    return ("`tools/test_platform/logs/sessions/%s/shots/`" % sid) if sid else "這個 session 的 `shots/` 目錄"


def _file_shots(source, bug_id: str, product: str, evidence: str) -> dict:
    """自動搬圖。⛔ **任何例外都不可以讓落單失敗** —— 單子已經寫好了。"""
    sid = source.get("id") if isinstance(source, dict) and source.get("kind") == "session" else None
    if not sid:
        return {}
    try:
        from core import shot_filing
        return shot_filing.file_for_bug(sid, bug_id, product, evidence)
    except Exception as e:                          # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def _next_steps(draft: dict, bug_id: str, product: str, source=None) -> list:
    """落單之後**還沒做完**的事 —— 講出來，不要讓它靜默斷掉。

    ★ 2026-08-23 實跑：session 拍了兩張佐證截圖放在 repo 根目錄，
      落單流程完全沒提它們 —— 單子引用的檔名指向不存在的位置，
      `lint_bug_assets` 事後才會報「找不到截圖」。

    ⭐ 2026-08-25 起**引用到的截圖會自動搬**（`core/shot_filing.py`）——
       標注改由任務提示的第①步保證（拍之前先注入 `__annotate`），
       而平台代搬的圖蓋的是 `marks=auto`（不是 `mcp`），來歷查得出來。
       這裡只留「沒被引用的那些」與失敗時的提醒。
    """
    steps = []
    filed = _file_shots(source, bug_id, product, draft.get("evidence") or "")
    if filed.get("moved"):
        steps.append("已自動把 %d 張佐證截圖搬進 `bugs/shots/`：%s。"
                     "⚠️ 標記是 `marks=auto`（平台代搬，標注由 session 拍攝當下完成、平台未驗證）"
                     "—— 值得瞄一眼紅框框對地方了沒。"
                     % (len(filed["moved"]), "、".join(filed["moved"][:3])))
    if filed.get("error"):
        steps.append("⚠️ 自動搬截圖失敗：%s —— 手動補搬："
                     "`python scripts/stamp_shots.py --product %s \"<來源>=%s_01_<描述>.png\"`"
                     % (filed["error"], product, bug_id))
    if filed.get("skipped"):
        steps.append("%s 還有 %d 張沒被這張單引用（%s…）—— 要用就自己搬，不用就留著。"
                     % (_shots_dir_hint(source), len(filed["skipped"]),
                        "、".join(filed["skipped"][:2])))
    if not (draft.get("nodeid") or "").strip():
        steps.append("`regression` 欄目前是「待補」—— 補一條回歸案例，"
                     "或在單子裡寫明為什麼補不了。")
    steps.append("`python scripts/gen_bug_index.py %s` 重跑索引，"
                 "讓這張單進 `bugs/_view/`。" % product)
    return steps


def _remember(product: str, bug_id: str) -> None:
    data = read_json(_LEDGER, {}) or {}
    data.setdefault(product, [])
    if bug_id not in data[product]:
        data[product].append(bug_id)
    write_json_atomic(_LEDGER, data)


def slug(title: str) -> str:
    """檔名用的短 slug：沿用既有單「<ID>_<主旨>.md」的形狀，去掉檔名不合法的字元。"""
    s = re.sub(r'[\/:*?"<>|\r\n\t]+', "", title or "").strip()
    s = re.sub(r"\s+", "_", s)
    return s[:40] or "未命名"


def _today() -> str:
    import time
    return time.strftime("%Y-%m-%d")


def _as_steps(raw) -> list:
    """重現步驟 → 一步一列。

    ⚠️ session 交回來的是**一段文字**（多行，常自帶「1. 2. 3.」編號），
       而原本直接 `enumerate()` —— 字串被**逐字元**展開成
       「1. 1／2. .／3. 　／4. 總／5. 監…」（2026-08-23 實跑）。
    """
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    out = []
    for line in str(raw or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        # 自帶編號就把編號拿掉 —— 下面會重新編
        out.append(re.sub(r"^\d+[.、)]\s*", "", line))
    return out


def compose(draft: dict, bug_id: str, over: dict) -> str:
    """組出 Bug 單全文（frontmatter ＋ 重現步驟 ＋ 佐證），格式與 docs/<產品>/bugs/ 的既有單一致。"""
    title = over.get("title") or draft.get("title") or ""
    env_txt = "、".join(_ENV_LABEL.get(k, k) + "：" + _ENV_VALUE.get(str(v), str(v))
                       for k, v in (draft.get("env") or {}).items()) or "QAT"
    rel = draft.get("likely_existing") or {}
    fm = [
        "---",
        f"id: {bug_id}",
        f"title: {title}",
        f"product: {draft.get('product', 'CRUX')}",
        f"surface: {over.get('surface') or draft.get('surface') or 'UI 自動化'}",
        f"module: {over.get('module') or draft.get('module') or ''}",
        f"severity: {over.get('severity') or draft.get('severity') or '中'}",
        "status: open",
        f"found: {draft.get('found') or _today()}",
        "reported:",
        "verified:",
        f"env: {env_txt}",
        f"regression: {draft.get('nodeid') or '⚠️ 待補'}",
        f"related: [{rel.get('id', '')}]" if rel.get("id") else "related:",
        # ⚠️ batch 只有 run 來源才寫得出來 —— 探索來源硬填會變成「 自動化執行」
        (f"batch: {draft.get('run_id')} 自動化執行" if draft.get("run_id")
         else "batch: 探索發現（平台 session 草擬）"),
        "---",
        "",
    ]
    # ⭐ 節序固定為 `bug-report` §4：標題 → Reproduce Steps → **Actual result** →
    #    **Expect result** → 問題截圖 → 【Test Environment】 → 附註。
    #    ⛔ 不得增節、不得調序 —— 我方的判斷經過（開單前三問、草擬來源）一律壓進附註。
    #
    # ⭐ 節名寫法對齊**下游的 JIRA**，不是對齊本地 .md：實抓 `CRUX-983`／`CRUX-969`
    #    的 description，兩張都是「節名單獨一行、**不加 `##`、不加冒號**，空一行才接內容」。
    #    ⛔ 本地人工單寫 `## Actual result`，但那批貼進 JIRA 之前有一道人工轉換把 `##` 拿掉了
    #    —— Bug 單的下游是 JIRA，格式要對齊下游（2026-08-26 使用者指出）。
    #    標題行同理不帶 `# `：它對應的是 JIRA 的 summary 欄。
    body = [
        f"[{draft.get('product', 'CRUX')}][{over.get('surface') or draft.get('surface') or 'UI 自動化'}]"
        f"[{over.get('module') or draft.get('module') or ''}] {title}",
        "",
    ]
    notes = []                     # → 最後統一收進 `## 附註`
    # ★ 依**來源**分流 —— run 的敘述（「只勾選這一條案例」「案例失敗」）
    #   對探索發現的缺陷完全不成立，硬套會產出編造的重現步驟。
    #   ⛔ 沒有的資訊一律寫「待補」，一個字都不編（2026-08-23 走查）。
    if draft.get("nodeid") or draft.get("run_id"):
        body += [
            "Reproduce Steps",
            "",
            f"1. 執行 `{draft.get('tool_name') or draft.get('tool_id')}` 的「{draft.get('command_label') or '執行案例'}」，"
            f"環境 {env_txt}。",
            f"2. 只勾選這一條案例：`{draft.get('nodeid')}`。",
            "3. 觀察執行結果。",
            "",
            "Actual result",
            "",
            "案例失敗，錯誤訊息如下 —",
            "",
            "```",
            (draft.get("message") or "（無訊息）").strip(),
            "```",
            "",
            "Expect result",
            "",
            "案例通過。",
            "",
            "佐證",
            "",
            f"- 主控台輸出：`{draft.get('console')}`",
        ]
        if draft.get("allure"):
            body.append(f"- Allure 報告：`{draft['allure']}`")
        body += [
            f"- 出現次數：{draft.get('seen_count', 1)} 次（run：{'、'.join(draft.get('seen_in') or [])}）",
            "",
            "【Test Environment】",
            "",
            env_txt,
            "",
        ]
        notes.append("⚠️ 本單由測試助手從執行結果自動草擬後、經人工確認開單。"
                     "**測試失敗 ≠ 缺陷** —— 請先確認不是測試碼或環境問題再送 JIRA。")
    else:
        steps = _as_steps(draft.get("steps"))
        body += [
            "Reproduce Steps",
            "",
        ]
        body += ([f"{i}. {s}" for i, s in enumerate(steps, 1)] if steps
                 else ["⚠️ **待補** —— 探索過程中發現，開單時尚未整理成步驟。",
                       "　依 `bug-report` §4：5 步以內、不寫成因推導。"])
        body += [
            "",
            "Actual result",
            "",
            (draft.get("actual") or draft.get("message") or "⚠️ **待補**"),
            "",
            "Expect result",
            "",
            (draft.get("expected") or "⚠️ **待補**"),
            "",
        ]
        # ⭐ 這一節**永遠輸出** —— 沒圖時就寫成提醒（2026-08-26 使用者裁示）。
        #   ⛔ 先前有 evidence 才輸出，於是**沒拍圖的單連提醒都沒有**，
        #      而缺節是「靜靜地少一塊」：讀者不會發現，開單的人也不會被提示。
        #   ⚠️ 與 lint 的 W10 是同一件事，只是提前到寫單的當下。
        body += ["問題截圖", ""]
        if draft.get("evidence"):
            body += [f"- {x}" for x in (draft["evidence"] if isinstance(draft["evidence"], list)
                                        else [draft["evidence"]])]
        else:
            body.append("⚠️ **待補** —— 圖能讓讀者 10 秒內看懂問題點（`bug-report` §4）。"
                        "標注三要件：框出問題點／寫上實際值 vs 應為值／一句話標題。")
            body.append("　真的沒有畫面（API 回應、DB 對帳、壓測數據）就在 frontmatter "
                        "寫 `no_shot: <理由>`，lint 的 W10 才不會一直提醒。")
        body.append("")
        body += [
            "【Test Environment】",
            "",
            "- 環境：" + env_txt,
            *_env_block(draft.get("product", "CRUX"), draft.get("env"),
                        "\n".join(steps)),
            "",
        ]
        # ★ 開單前三問是**我方的判斷經過**，§4 明訂不進正文 —— 但也不能丟掉：
        #   它是「這張單為什麼該開」的唯一紀錄，而 session 是無人看管的。故壓進附註。
        pre = [q for q in (draft.get("prechecks") or []) if (q.get("answer") or "").strip()]
        if pre:
            notes.append("開單前三問（`bug-report` §3.9）：")
            notes += [f"- **{q['label']}**　{q['answer']}" for q in pre]
            notes.append("")
        notes.append("⚠️ 本單由**探索 session** 草擬後、經人工確認開單。"
                     "重現步驟與期望值請開單者再核對一次 —— session 是無人看管的。")
    if rel.get("id") and rel.get("regressed"):
        notes += ["", f"🔴 **回歸**：`{rel['id']}`（{rel.get('title', '')}）已標為"
                      f"「{rel.get('status')}」，本次執行**又失敗了**。",
                  "",
                  "依既有慣例，**修復後又壞掉的殘留一律開新單承接，舊單維持原狀不回填**，"
                  f"所以本單即為 `{rel['id']}` 的承接單。"]
    elif rel.get("id"):
        notes += ["", f"⚠️ 疑似與既有單 **{rel['id']}**（{rel.get('title', '')}）為同一問題 —— "
                      f"依據：{rel.get('why', '')}。若確為同一件事，請改為在該單補重現紀錄，不要另開。"]
    if notes:
        body += ["附註", ""] + notes
    # ⭐ frontmatter **不轉** —— 它是 YAML，不是要貼給 JIRA 的內容
    return "\n".join(fm) + "\n" + _to_jira("\n".join(body)) + "\n"


@bp.post("/api/bugs/file")
def file_bug():
    body = request.get_json(force=True, silent=True) or {}
    # ⚠️ 兩種來源：run（既有呼叫傳 run_id 字串）與 session（傳 source dict）。
    #    舊呼叫維持原樣 —— run 結果頁的「開單」不必改（2026-08-23）。
    sig = body.get("signature")
    source = body.get("source") or body.get("run_id")
    if not source or not sig:
        return fail("缺 run_id／source 或 signature")
    data = bug_draft.read(source)
    draft = next((d for d in data.get("drafts", []) if d["signature"] == sig), None)
    if not draft:
        return fail("找不到這筆草稿（run 可能已被清掉，或草稿尚未產生）", 404)
    if draft.get("filed_as"):
        return fail(f"這筆已開單為 {draft['filed_as']}，不再重複開", 409)

    over = {k: body.get(k) for k in ("title", "severity", "module", "surface") if body.get(k)}
    product = draft.get("product") or ""
    if not product:
        return fail("這筆草稿判不出產品 —— 請確認 config/products.json 有登記，"
                    "且案例落在該產品的 tests_prefix 底下")
    bug_id, id_source = next_id(product)
    if not bug_id:
        return fail(id_source, 503)         # 503：取號服務不可用，不是使用者的錯
    text = compose(draft, bug_id, over)
    out_dir = bug_out_dir(product)
    path = os.path.join(out_dir, f"{bug_id}_{slug(over.get('title') or draft.get('title'))}.md")

    if body.get("dry_run", True):
        return ok(preview=True, bug_id=bug_id, id_source=id_source,
                  path=rel_to_repo(path), text=text)

    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    _remember(product, bug_id)
    bug_draft.mark_filed(source, sig, bug_id)
    _invalidate()                            # 新單要立刻出現在 Bug 列表
    return ok(preview=False, bug_id=bug_id, id_source=id_source,
              path=rel_to_repo(path), text=text,
              next_steps=_next_steps(draft, bug_id, product, source))


def auto_file_session_bugs(sid: str) -> list:
    """把某個 session 的 Bug 草稿**自動開單**。回每一筆的結果。

    ⛔ 只做 `is_auto_fileable` 說可以的那些；其餘原樣留在待開單清單。
    """
    src = {"kind": "session", "id": sid}
    out = []
    data = bug_draft.read(src)
    for d in data.get("drafts", []):
        if d.get("filed_as") or d.get("dropped"):
            continue
        okay, why = bug_draft.is_auto_fileable(dict(d, source=src))
        if not okay:
            out.append({"ok": False, "skipped": True, "why": why,
                        "title": d.get("title", "")})
            continue
        product = d.get("product") or ""
        bug_id, id_source = next_id(product)
        if not bug_id:
            out.append({"ok": False, "title": d.get("title", ""),
                        "errors": [id_source]})
            continue
        text = compose(d, bug_id, {})
        out_dir = bug_out_dir(product)
        path = os.path.join(out_dir, "%s_%s.md"
                            % (bug_id, slug(d.get("title"))))
        os.makedirs(out_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        _remember(product, bug_id)
        bug_draft.mark_filed(src, d.get("signature"), bug_id)
        out.append({"ok": True, "bug_id": bug_id, "path": rel_to_repo(path),
                    "title": d.get("title", ""), "auto": True,
                    "next_steps": _next_steps(d, bug_id, product, src)})
    if any(r.get("ok") for r in out):
        _invalidate()
    return out


@bp.post("/api/bugs/<bug_id>/jira")
def backfill_jira(bug_id):
    """把 JIRA 單號回填到本地單的 `reported` 欄。

    ★ 這是使用者實際的動線：**Bug 列表看到新單 → 轉開到 JIRA → 回填單號**
      （2026-08-23）。⛔ 平台不寫 JIRA（`jira-verify` §0 的唯讀邊界）——
      開單是人在 JIRA 網頁上做，平台只負責把單號記回來。
    """
    body = request.get_json(force=True, silent=True) or {}
    key = (body.get("jira_key") or "").strip()
    product = (body.get("product") or "").strip()
    if not key:
        return fail("要填 JIRA 單號")
    if not product:
        return fail("要指定產品")
    import glob
    import re as _re
    d = bug_out_dir(product)
    hit = None
    for p2 in glob.glob(os.path.join(d, "%s_*.md" % bug_id)) + \
            glob.glob(os.path.join(d, "old", "%s_*.md" % bug_id)):
        hit = p2
        break
    if not hit:
        return fail("找不到 %s 的本地單" % bug_id, 404)
    txt = io.open(hit, encoding="utf-8").read()
    new_txt, n = _re.subn(r"^reported:.*$", "reported: %s" % key, txt,
                          count=1, flags=_re.M)
    if not n:
        return fail("這張單沒有 reported 欄 —— 格式不符，請手動編輯")
    io.open(hit, "w", encoding="utf-8", newline="\n").write(new_txt)
    _invalidate()                            # ⛔ 不清的話列表還是顯示「漏開單」
    return ok(bug_id=bug_id, jira_key=key, path=rel_to_repo(hit),
              note="已回填並更新索引 —— Bug 列表上的「漏開單」標記會消失")


@bp.post("/api/drafts/discard")
def discard_draft():
    """捨棄一筆草稿（Bug 或文件）。**標記不刪除** —— 判斷過程值得留。

    ⛔ 沒有這個動作時，判定「不該開」的草稿會永遠躺在清單裡，
       清單愈長愈髒，久了沒有人願意看（2026-08-23 UI 走查）。
    """
    body = request.get_json(force=True, silent=True) or {}
    src, sig = body.get("source"), body.get("signature")
    kind = (body.get("kind") or "bug").lower()
    why = (body.get("why") or "").strip()
    if not src or not sig:
        return fail("缺 source 或 signature")
    if not why:
        return fail("要寫一句理由 —— 「當初為什麼判定不開」正是下次要看的東西")
    if kind == "doc":
        from core import doc_draft as mod
    else:
        mod = bug_draft
    if not mod.discard(src, sig, why):
        return fail("找不到這筆草稿", 404)
    return ok(discarded=True)


# ---------------------------------------------------------------- 文件草稿
# ⭐ 探索產出的機制文件、收尾補做的交接檔內容 —— 計畫 E-1b 列了五種寫入型產出，
#    先前只做了 Bug 與案例兩種，這兩種**根本沒有寫檔路徑**（session 產得出來、
#    介面上寫不下去，使用者只能自己複製貼上）。

@bp.get("/api/doc-drafts")
def doc_drafts():
    from core import doc_draft
    items = doc_draft.read_all()
    for d in items:
        src = d.get("source") or {}
        d["source_label"] = ("對話 %s" % (src.get("id") or "")[:8]) if src.get("kind") == "session"             else ("執行 %s" % (src.get("id") or ""))
        d["target"] = doc_draft.target_of(d)
        # report 的檔名在**寫入當下**才向 new_bug_doc.py 取（撞名會加「_第N批」），
        # 列表這裡先講清楚，免得看起來像「不知道會寫到哪」。
        d["target_rel"] = (rel_to_repo(d["target"]) if d.get("target")
                           else ("bugs/_reports/…（寫入當下取檔名）"
                                 if d.get("kind") == "report" else ""))
    return ok(drafts=items, count=len(items))


@bp.post("/api/doc-drafts/write")
def write_doc_draft():
    """預覽（`dry_run`，預設 true）→ 人確認 → 真的寫。

    ⛔ 與 Bug 同一條紀律：**編號在寫入的那一刻才取**，
       覆寫既有的機制文件要明確帶 `overwrite`。
    """
    from core import doc_draft
    body = request.get_json(force=True, silent=True) or {}
    source, sig = body.get("source"), body.get("signature")
    if not source or not sig:
        return fail("缺 source 或 signature")
    data = doc_draft.read(source)
    item = next((d for d in data.get("drafts", []) if d["signature"] == sig), None)
    if not item:
        return fail("找不到這筆草稿", 404)
    if item.get("written_as"):
        return fail("這筆已寫入 %s，不再重複寫" % item["written_as"], 409)
    # 允許人在確認框裡改掉標題／檔名／內容
    for k in ("title", "path", "body", "section", "cells", "topic",
              "index_desc", "index_section"):
        if body.get(k) is not None:
            item[k] = body[k]

    if body.get("dry_run", True):
        return ok(preview=True, **doc_draft.preview(item))
    res = doc_draft.commit(item, overwrite=bool(body.get("overwrite")))
    if not res.get("ok"):
        return fail("；".join(res.get("errors") or ["寫入失敗"]), 409 if res.get("needs_overwrite") else 400)
    doc_draft.mark_written(source, sig, res["path"])
    _invalidate()                            # 交接檔／機制文件都會影響待辦與知識索引
    return ok(preview=False, **res)


@bp.get("/api/bug-drafts")
def all_drafts():
    """**所有來源**的待開單草稿（run ＋ session）。

    ⚠️ 先前只有 `/api/runs/<run_id>/bug-drafts` —— 於是探索任務、手動開單任務
       產出的草稿**在介面上不存在**，而「草稿／寫檔兩段式」整個設計就靠這一步
       （2026-08-23 使用者提問：session 的執行結果要怎麼檢視）。
    """
    items = bug_draft.read_all()
    for d in items:
        src = d.get("source") or {}
        # 帶上人看得懂的來源標示，UI 才不必自己解讀 kind
        if src.get("kind") == "session":
            d["source_label"] = "對話 %s" % (src.get("id") or "")[:8]
            d["source_href"] = "#/sessions?session=%s" % src.get("id")
        else:
            d["source_label"] = "執行 %s" % (src.get("id") or "")
            d["source_href"] = "#/run/%s" % src.get("id")
    return ok(drafts=items, count=len(items))

@bp.get("/api/runs/<run_id>/bug-drafts")
def run_drafts(run_id):
    """草稿：已存在就直接讀，沒有就當場產一份（run 結束後才有意義）。"""
    data = bug_draft.read(run_id)
    if not data or request.args.get("refresh"):
        data = bug_draft.build(run_id)
    return ok(**data)
