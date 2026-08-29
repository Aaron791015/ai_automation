# -*- coding: utf-8 -*-
"""任務模板：一顆按鈕 ＝ 一組提示 ＋ 對應 skill ＋ 一個 Claude session（階段 E，2026-08-23）。

用途：平台的價值在「聚合與觸發」，而測試工程師的日常有一半是**創作**
      （探索、設計、判斷、寫報告）—— 那是 session 在做的事。
      任務模板是兩者的接點：**平台帶好上下文，把判斷交給 session**。

使用方式：
    from core import tasks
    tasks.load()                       # 內建 ＋ custom
    tasks.render(task, values)         # → {"prompt": ..., "context": ..., "skills": [...]}
    tasks.findings_for_handoff()       # 收尾體檢的自動發現

前置條件：
    · `tasks/` 是內建（隨範本匯出）、`tasks/custom/` 是個人的（不匯出）——
      兩者載入方式相同，分開只為範本化的歸屬。
    · ⛔ **`writes: draft` 的任務不給 `Write`／`Edit`／`Bash`** ——
      session 產草稿，**寫檔由平台執行**（配號也在那一刻）。
      這是 `core/bug_draft.py` 檔頭那條 2026-08-21 裁示的推廣。
"""
from __future__ import annotations

import glob
import os

from core.jsonio import read_json
from core.paths import BASE_DIR

TASKS_DIR = os.path.join(BASE_DIR, "tasks")
CUSTOM_DIR = os.path.join(TASKS_DIR, "custom")

_BOUNDARY_LABEL = {
    "readonly": "本次唯讀（只看不改）",
    "write": "可寫入 QAT（已預先授權，直接執行）",
}

# ⭐ 安全邊界不能只給一個標籤 —— 那是 2026-08-23 實跑抓到的第二種「跑起來才看得到」：
#
#    探索 session 拿到「安全邊界：可寫入 QAT」五個字之後，**仍然全程唯讀** ——
#    它讀了 `CLAUDE.md` §5，看到「執行測試前先說明會做什麼」「需先取得確認」那一類句子，
#    而它**問不到人**（平台這一側沒有人回答），於是選了最保守的解釋。
#    結果是整場探索只驗得到「欄位有沒有 pattern 屬性」這種讀得到的東西，
#    **驗不了任何一條會改狀態的規則** —— 而金流邏輯的正確性全在那一側。
#
#    所以這裡把 §5 授權表的結論**攤成可以直接照做的條款**，連同它的三條紀律
#    （波及他人的操作要避開、不動他人資料、用完即還原但開單的保留）一起帶進去。
#: 會波及**同站台其他人**的操作。⚠️ 判準是「這台是不是本次專用」，不是操作危不危險。
#
#  ⛔ 這裡原本只有一句「不要做」，而 `_PREAMBLE` 同時寫著「本次指定給你的站台照做」
#     —— **同一則訊息裡兩條相反的指示**，session 只會選嚴的那邊（CLAUDE.md §7.0
#     記過的失效模式：保守到把工作本身擋掉）。
#  ⭐ 2026-08-27 改成看表單的「本次專用站台」欄：人指定了才展開授權那組。
#     沒指定時**要講得出怎麼取得授權**，否則它只會再一次卡在「被什麼阻塞」。
_STATION_SHARED = u"""⛔ **不要做會波及同站台其他人的操作**：開獎「获取结果」「一键结账」、關盤、
  反結算、改期數狀態、平台重置期數、結算重置。
  判準是**會不會影響到別人**，不是操作本身危不危險 —— 而這次**沒有指定專用站台**，
  所以要當成別人也在用。
  ⭐ 少了它就驗不下去的話，寫進回覆的「被什麼阻塞」段並**講明需要哪一台**，
  人可以填「本次專用站台」再開一次任務。"""

_STATION_DEDICATED = u"""✅ **本次專用站台：%s** —— 人已指定這一台歸你，所以
  開獎「获取结果」「一键结账」、關盤、反結算、改期數狀態、重置期數**可以做**
  （CLAUDE.md §5 第 3 條：該站台若是本 session 專用就不必逐次請示）。
  ⛔ **只限這一台** —— 其他站台仍當成別人在用，不要碰。
  ⭐ **做了就在回覆裡寫明**（哪一台、做了什麼、幾點）—— 這一側沒有人可以事前批准，
  但事後看得到就補得回來。"""

_BOUNDARY_RULES = {
    "write": u"""✅ **QAT 的 Web／UI 寫入已預先授權**（`CLAUDE.md` §5 授權表）——
  下注、退碼、出貨、建帳號、改設定、觸發日誌**直接做**，
  ⛔ **不要為了「要不要寫入」停下來請示** —— 這一側沒有人能回答你。
  為了取證而寫入是測試的常態；**只用讀得到的東西驗，等於沒驗**。
⛔ **DB 一律唯讀** —— 本任務**不含**任何 DB 寫入的例外（重置期數改 `DrawTime`
  那條例外要人在場裁示，不在平台任務的授權範圍）。
{station_rules}
⛔ **不動他人的測試資料** —— 需要資料自己建、自己收。
♻️ **用完即還原**（退碼／改回原值／停用或刪除新建資料）。
  ⭐ **例外：據以開立 Bug 單的資料一律保留不還原** —— 那批資料就是該單的重現環境，
  還原掉等於單子不可重現。
📋 **收工一定要交一筆「測試資料」草稿**（下方 `handover` 區塊，`section data`）：
  建了什麼、還原了沒、刻意保留的屬哪一張單。**沒交這一筆就等於沒有人知道你動過什麼。**
🌐 **瀏覽器有兩組**（`playwright` 與 `playwright2`，各自獨立 profile）——
  照 `config/environments.md` 的慣例挑：不同子帳號用不同那一組，
  同時有別的任務在跑時才不會互搶。
📸 **佐證截圖三步驟，順序不可換**（`bug-report` 的截圖規範）：

  **① 先標注，再拍** —— ⛔ **標注做不到事後補**：乾淨畫面事後畫框沒有依據文字，
     蓋「已標注」標記等於騙過 lint 的 W7。所以**拍之前**先注入：
     ```
     browser_evaluate  () => { window.__annotate = <qa_common/shot.py 的 ANNOTATE_JS 內容>; }
     browser_evaluate  async () => await window.__annotate({
                         marks:[{selector:"…", label:"實際 X，應為 Y（依據）"}],
                         note:"一句話標題" })
     ```
     ⚠️ 回傳的 `missing`／`overlays` 要是空的、`drift` 要接近 0，否則那張圖不能用（重來）。
     ⭐ **同時框「錯的」與「對的」** —— 只框錯值，讀者無從判斷基準。

  **② 拍進自己的目錄**（已為你建好、已排除版控）：
     `filename: "tools/test_platform/logs/sessions/__SID__/shots/<檔名>.png"`
     ⛔ 不要存 `.playwright-mcp/`（**共用暫存**，MCP 與別的 session 都會清它 ——
     2026-08-25 有一批佐證就是這樣整批消失的）；也不要存 repo 根或 `docs/` 底下。
     拍完記得用 `CLEAR_JS` 把標注清掉再繼續操作。

  **③ 拍完**立刻**搬走，不要等一批拍完再一起搬**（你有 shell，自己跑）：
     ```
     python scripts/stamp_shots.py --product <產品>        "tools/test_platform/logs/sessions/__SID__/shots/<檔名>.png=<ID>_<序2碼>_<說明>.png"
     ```
     ⚠️ 目標檔名要**照規範**：`<ID>_<序2碼>_<說明>.png`（改善建議走 `-S01` 序列）。
     ID 還沒配到號時（草稿階段）先留在自己的目錄，**落單拿到號之後立刻補搬**。""",
    "readonly": u"""⛔ **本次唯讀** —— 只看不改，不按「新增」「編輯」「刪除」「結算」。
⚠️ 唯讀能驗的只有「讀得到的東西」（欄位屬性、既有資料的顯示、API 回應形狀）。
  **需要改狀態才驗得下去的功能點，不要硬猜結論** ——
  把它列進回覆的「還有什麼沒探」，並註明「需要可寫入的一輪才驗得了」。
🌐 **瀏覽器有兩組**（`playwright` 與 `playwright2`，各自獨立 profile）——
  照 `config/environments.md` 的慣例挑，同時有別的任務在跑時才不會互搶。
📸 **佐證截圖三步驟，順序不可換**（`bug-report` 的截圖規範）：

  **① 先標注，再拍** —— ⛔ **標注做不到事後補**：乾淨畫面事後畫框沒有依據文字，
     蓋「已標注」標記等於騙過 lint 的 W7。所以**拍之前**先注入：
     ```
     browser_evaluate  () => { window.__annotate = <qa_common/shot.py 的 ANNOTATE_JS 內容>; }
     browser_evaluate  async () => await window.__annotate({
                         marks:[{selector:"…", label:"實際 X，應為 Y（依據）"}],
                         note:"一句話標題" })
     ```
     ⚠️ 回傳的 `missing`／`overlays` 要是空的、`drift` 要接近 0，否則那張圖不能用（重來）。
     ⭐ **同時框「錯的」與「對的」** —— 只框錯值，讀者無從判斷基準。

  **② 拍進自己的目錄**（已為你建好、已排除版控）：
     `filename: "tools/test_platform/logs/sessions/__SID__/shots/<檔名>.png"`
     ⛔ 不要存 `.playwright-mcp/`（**共用暫存**，MCP 與別的 session 都會清它 ——
     2026-08-25 有一批佐證就是這樣整批消失的）；也不要存 repo 根或 `docs/` 底下。
     拍完記得用 `CLEAR_JS` 把標注清掉再繼續操作。

  **③ 拍完**立刻**搬走，不要等一批拍完再一起搬**（你有 shell，自己跑）：
     ```
     python scripts/stamp_shots.py --product <產品>        "tools/test_platform/logs/sessions/__SID__/shots/<檔名>.png=<ID>_<序2碼>_<說明>.png"
     ```
     ⚠️ 目標檔名要**照規範**：`<ID>_<序2碼>_<說明>.png`（改善建議走 `-S01` 序列）。
     ID 還沒配到號時（草稿階段）先留在自己的目錄，**落單拿到號之後立刻補搬**。""",
}


def load(force: bool = False) -> list[dict]:
    """內建 ＋ 自訂。同 id 時**自訂覆蓋內建**（讓人能改內建任務而不必改範本）。"""
    out: dict[str, dict] = {}
    for d, builtin in ((TASKS_DIR, True), (CUSTOM_DIR, False)):
        for p in sorted(glob.glob(os.path.join(d, "*.json"))):
            t = read_json(p, None)
            if not t or not t.get("id"):
                continue
            t["builtin"] = builtin
            out[t["id"]] = t
    return sorted(out.values(), key=lambda t: (t.get("order", 99), t["id"]))


def get(task_id: str) -> dict | None:
    return next((t for t in load() if t["id"] == task_id), None)


# ⭐ 每個任務 session 都會拿到的前言。
#
#    為什麼放這裡而不是逐份寫進 `tasks/*.json`：這幾條對**所有**任務都成立，
#    分散到七份模板裡必然漂移（少寫一份就是那一個按鈕壞掉，而且不會有人發現）。
#
#    ⚠️ 第二條是實測出來的：2026-08-23 按下「探索新功能」，session 第一則回覆是
#       「Please approve the tool call so I can continue」—— 工具其實已經在白名單裡，
#       它只是不知道自己沒有人可以批准。任務就停在那裡。
_PRE_HEAD = u"""> **這是測試助手起的 session。**
> · **工具權限已由平台預先授權**，白名單以外的工具是刻意不給的。
>   ⛔ **不要停下來請求批准 —— 這一側沒有人能回答你。** 某個工具真的用不了，
>   就換一種做法，或在回覆裡寫明「因為缺 X 所以這一段沒做」。
> · **你有 shell 與寫檔工具，請照 skill 的規範做事** —— 該跑 `gen_bug_index --next-id` 配號、
>   該跑 `stamp_shots.py` 搬截圖、該跑 `lint_docs.py` 收尾，就真的去跑，不要只寫在回覆裡。
> · 你**沒有人在旁邊看著**，而同一台機器上有其他 session 併行。兩件事平台會擋下來：
>   ⛔ **git 的寫入操作**（add／commit／stash／push）—— 提交要人點頭，而索引是共用的；
>   你照常改檔就好，**平台會在這一輪結束時列出你動了哪些檔**，由人來提交。
>   （唯讀的 `git status`／`diff`／`log` 可以用。）
>   ⛔ **遞迴刪除自己工作目錄以外的東西** —— 2026-08-25 有一批佐證截圖就是這樣沒的。
"""

#: 站台段（任務版）—— 指向表單「安全邊界」展開的 `{station_rules}` 條款。
_PRE_STATION_TASK = u"""> · ⚠️ **開獎「获取结果」「一键结账」、關盤、反結算、重置期數這一類會波及同站台的其他人** ——
>   ⭐ **不是不能做**（那些常常就是測試流程本身），但**能不能做看下方「安全邊界」那一節**：
>   人有指定「本次專用站台」才可以，沒指定就當成別人也在用。⭐ 做了一定要在回覆裡寫明。
"""

#: 站台段（對話版）—— ⚠️ 對話視窗**沒有那張表單**，所以沒有任何指定專用站台的途徑。
#   ⛔ 這裡不可以照抄任務版的「看下方安全邊界那一節」：對話的提示裡根本沒有那一節，
#      指過去就是叫它去讀一段不存在的文字（提示自相矛盾比沒寫更糟）。
_PRE_STATION_CHAT = u"""> · ⚠️ **開獎「获取结果」「一键结账」、關盤、反結算、重置期數這一類會波及同站台的其他人** ——
>   ⛔ 對話視窗**沒有指定專用站台的欄位**，所以一律當成別人也在用、**不要做**。
>   ⭐ 少了它就走不下去的話，講明**需要哪一台**：人可以改開一個任務並填「本次專用站台」。
"""

_PRE_TAIL = u"""> · 需要暫存檔就寫 `tools/test_platform/logs/sessions/__SID__/work/`（已為你建好、不進版控）——
>   ⛔ 不要把中間產物丟在 repo 根目錄或 `docs/` 底下。
> · ⚠️ **工具回傳會一直留在 context，之後每一輪都要重讀一次** —— 一筆 5k 不是花 5k，
>   是 5k ×（後面還剩幾輪）。實測 `evaluate` 與 `Bash` 就佔了 context 成長的七成。
>   ⭐ **只帶回要拿來判斷的值**（筆數、合計、對不上的樣本、欄位名），
>   篩選在**查詢裡**做（`.filter().slice()`／`grep`／`head`），⛔ 不要整包撈回來自己看。
>   ⭐ **能一次問完就不要問三次**（一支 `evaluate` 取五個值 ≪ 五支各取一個）。
>   ⚠️ **這不是叫你少驗** —— 要看的照看、該取的證照取，只是別把不看的一起帶回來；
>   真的需要整包就寫進上面的 `work/`，再用 `grep` 取用。
> · 站台一律 **QAT**；⛔ STG 與正式環境不碰（`CLAUDE.md` §5）。
>   要登入的話先看 `config/environments.md` 的子帳號分配 ——
>   站台是「同帳號他處登入即踢掉前者」，用錯會互踢。
> · **全程繁體中文** —— ⚠️ 不只是最後那段結論：**工具與工具之間的過程敘述**
>   （「我先載入…」「接著查…」「已確認…」）也要中文。
>   ⛔ 實測不講清楚就會變成英文：`CLAUDE.md` 只規定「回覆／註解／文件」用繁體中文，
>   它會把跑到一半的敘述當成不在其中（2026-08-27 兩則 session 實例）。

"""

#: 任務 session 的前言。
_PREAMBLE = _PRE_HEAD + _PRE_STATION_TASK + _PRE_TAIL

#: ★ **非任務對話**（`#/sessions` 與對話面板）的前言 —— 只在該 session 的**第一則**訊息前置。
#
#   ⚠️ 2026-08-27 之前這條路**完全沒有前言**：`chat.py` 送出的就是
#      `壓縮種子 + 使用者打的字`。造成的實際後果不只是語言：
#        · 它不知道「這一側沒有人能批准」→ 會停下來等人按（2026-08-23 已在任務那側踩過）
#        · 它不知道 git 寫入會被護欄擋 → 擋下來時會當成環境壞掉
#        · 它不知道暫存檔該寫哪 → 中間產物落在 repo 根目錄
#      ⭐ 所以修法是「**共用同一份規則**」，不是「補一句請講中文」。
CHAT_PREAMBLE = _PRE_HEAD + _PRE_STATION_CHAT + _PRE_TAIL


def _product_label(pid: str) -> str:
    """平台 slug → 權威產品名（`crux` → `CRUX`）。認不得就原樣回傳。"""
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if pid in (p.get("id"), p.get("product_id"), p.get("label")):
                return p.get("product_id") or p.get("label") or pid
    except Exception:                           # noqa: BLE001
        pass
    return pid


def render(task: dict, values: dict, *, product_skill: str = "") -> dict:
    """把欄位值套進 `prompt_template`。

    ⚠️ 缺的欄位一律填「（未填）」而不是留下 `{{key}}` ——
      模板漏字會讓 session 看到半句話，比明講「沒填」更糟。
    """
    v = dict(values or {})
    v.setdefault("product_skill", product_skill or v.get("product", ""))
    # ⭐ 提示裡的產品要用**權威名稱**（`CRUX`／`投注機器人`），不要用平台內部的 slug。
    #    session 拿它去配 Bug ID、去 `lint_docs --product`、去找 `docs/<目錄>/` ——
    #    給 slug 會讓它用 `crux-` 當前綴或在 MCP 上查不到東西
    #    （2026-08-24 實測：提示寫「產品：crux」，而 Bug 單前綴是 `CRUX-`）。
    #    `product_skill` 仍維持 slug —— skill 名就是小寫的（`/crux`）。
    if v.get("product"):
        v["product"] = _product_label(v["product"])
    if "boundary" in v:
        v["boundary_label"] = _BOUNDARY_LABEL.get(v["boundary"], v["boundary"])
        # ⭐ 把邊界展開成**條款**（見 `_BOUNDARY_RULES` 的說明）——
        #    模板只寫 `{boundary_rules}`，兩種邊界的規則就都在同一個地方維護。
        # ⭐ 站台條款依表單的「本次專用站台」切換（見 `_STATION_SHARED` 的說明）
        st = str(v.get("station") or "").strip()
        v["station_rules"] = (_STATION_DEDICATED % st) if st else _STATION_SHARED
        v["boundary_rules"] = (_BOUNDARY_RULES.get(v["boundary"],
                                                   _BOUNDARY_RULES["readonly"])
                               .replace("{station_rules}", v["station_rules"]))
    text = _PREAMBLE + task.get("prompt_template", "")
    for key in _placeholders(text):
        val = v.get(key)
        text = text.replace("{%s}" % key,
                            str(val) if val not in (None, "") else "（未填）")
    return {
        "prompt": text,
        "skills": list(task.get("skills") or []),
        "writes": task.get("writes", "none"),
        "allowed_tools": list(task.get("allowed_tools") or []),
        # ⏱ 這個任務的單次上限（秒）。⚠️ **一定要跟著任務走** ——
        #    探索任務的表單自己提供 60／90 分鐘的時間盒，而 `claude_session`
        #    的預設上限只有 15 分鐘：不帶出來就會在時間盒還沒到時被殺掉，
        #    而且（修好之前）連一則訊息都沒有（2026-08-23）。
        "timeout_sec": _timeout_sec(task, v),
        # ⚠️ 濾掉底線開頭的**內部虛擬欄位**（如 run 參數用的 `_products`）——
        #    它們會被表單順手帶進來，然後原封不動出現在 session 的上下文行裡，
        #    讓 Claude 讀到一個空的、與這次任務無關的值（2026-08-23 範本驗收）。
        "context": {"task": task["id"], "task_label": task.get("label"),
                    **{k: v[k] for k in v
                       if k != "product_skill" and not k.startswith("_")}},
    }


#: 程序硬上限（分鐘）。⛔ **2026-08-26 起預設不設限**（見 `_timeout_sec`）——
#: 個別任務仍可在 tool json 宣告 `timeout_minutes` 自我設限。
_TIMEOUT_DEFAULT, _TIMEOUT_CEIL = 0, 24 * 60


def _timeout_sec(task: dict, values: dict) -> int:
    """程序的硬上限（秒）。**0 ＝ 不設限**（2026-08-26 起的預設）。

    ⛔ **不要再用它限制 session 該做多久**（2026-08-23 使用者裁示）：

        「沒有人能準確預測 session 運行時長，
          時間盒反而可能造成執行過程的資料遺失的風險。」

    先前表單有「時間盒」欄位、上限跟著它算，於是**時間成了中斷因素** ——
    而中斷的代價是已經跑了幾十分鐘的探索被切一半。
    現在範圍改由「**功能區塊**」界定：探索該探多少，看那個區塊有多大。

    ⛔ 2026-08-26 使用者裁示**連這個硬上限也拿掉** —— 同一條理由再走一次，
    而且 session 的工作量又長了一截（案例要逐條跑 ＋ 整檔跑兩次）。
    ⚠️ 代價：掛死的程序不會自己結束，要人在 session 列表按「關閉」。

    這個值**不出現在任何提示裡** —— 講了只會讓 session 自我設限。
    """
    declared = task.get("timeout_minutes")
    if not declared:
        return _TIMEOUT_DEFAULT              # 0 ＝ 不設限
    return int(min(max(int(declared), 1), _TIMEOUT_CEIL) * 60)


def _placeholders(text):
    import re
    return set(re.findall(r"\{(\w+)\}", text))


def findings_for_handoff() -> str:
    """收尾體檢的自動發現。

    ★ 這是**平台獨有、單一 session 看不到**的東西（跨 session 視野）：
      交接檔過不過期、run 跑完有沒有留下紀錄、積壓多少。
      資料來源全部現成 —— 不重算，只是把三處拼起來。
    """
    lines = []
    try:
        from core.todo_index import build_todo_index
        idx = build_todo_index()
        for pid, data in (idx.get("products") or {}).items():
            for doc in data.get("docs") or []:
                if doc.get("stale"):
                    lines.append("⚠️ `%s` 交接檔可能過期（%s）"
                                 % (doc.get("path"), doc.get("updated") or "無日期"))
            for b in data.get("blockers") or []:
                # ⚠️ blocker 的欄位是 what／who／impact（`todo_index` 的表格欄位），
                #    不是 `text` —— 先前讀錯鍵，於是每一條都印成「blocker：」空字串。
                what = (b.get("what") or "").strip()
                who = (b.get("who") or "").strip()
                if not what or what.startswith("—"):
                    continue                      # 「目前無 blocker」那一列不用報
                lines.append("⛔ [%s] blocker：%s%s"
                             % (pid, what[:80], "（卡在 %s）" % who if who else ""))
    except Exception as e:                       # noqa: BLE001
        lines.append("（待辦索引讀取失敗：%s）" % e)

    try:
        from core import run_index
        recent = run_index.recent(limit=20)
        if recent:
            top = recent[0]
            lines.append("📊 最近 %d 次執行，最新一次：%s（%s）"
                         % (len(recent),
                            top.get("tool_name") or top.get("tool_id") or "?",
                            top.get("phase")))
    except Exception:                            # noqa: BLE001
        pass

    try:
        from core import bug_draft
        n = len(bug_draft.read_all())
        if n:
            lines.append("📦 有 %d 筆 Bug 草稿還沒開單" % n)
    except Exception:                            # noqa: BLE001
        pass

    # ★ D10 積壓 —— 這一組正是計畫 E-1 範例裡的那一行，先前漏掃
    #   （2026-08-23 範本端到端驗收第 ⑨ 步）。
    #   ⛔ 不重算規則 —— `bug_index` 已經把四個跨比數字算好了。
    try:
        from core.bug_index import build_bug_index
        _LABEL = [("unfiled", "待開立（本地有單、JIRA 未開）"),
                  ("no_regr", "缺回歸案例"),
                  ("to_close", "該關單"),
                  ("revisit", "待重驗")]
        for pid, blk in (build_bug_index(jira="off").get("products") or {}).items():
            if not isinstance(blk, dict):
                continue
            cc = blk.get("cross_counts") or {}
            hit = ["%s %d" % (lbl, cc[k]) for k, lbl in _LABEL if cc.get(k)]
            if hit:
                lines.append("📦 [%s] 積壓：%s（lint D10）" % (pid, "、".join(hit)))
    except Exception:                            # noqa: BLE001
        pass

    return "\n".join("· " + x for x in lines) or "· （平台沒掃到明顯的漏收尾跡象）"
