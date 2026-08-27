# -*- coding: utf-8 -*-
"""把一則訊息交給 `claude.exe` headless session（階段 D-2，2026-08-23）。

用途：`web_ui/api/chat.py` 的接真後端。在此之前 `chat.py` 末行是
      `return fail("正式模式的 Claude session 尚未接上（M6）", 501)`。

使用方式：
    from core.claude_session import ask, available
    ok, why = available()                 # claude.exe 在不在、有沒有登入
    for ev in ask("CRUX 還有幾張沒修的單？", session_id=sid, model="sonnet"):
        ...                               # ev: {"type": "text"|"tool"|"done"|"error", ...}

前置條件與四條紀律：

  1. **白名單 ＋ 拒絕清單 ＋ 護欄，三層** ——
     2026-08-23 實測：只下 `--allowedTools` **擋不住**（session 照樣跑了 Bash），
     所以兩份清單都要下。
     ⭐ **2026-08-25 起 shell 與寫檔在白名單裡** —— 見 SAFE_TOOLS 的說明：
     「一律不給」擋掉的不只是風險，也擋掉了規範本身。
  2. ⛔ **仍然不給 commit 能力** —— `CLAUDE.md` §8：commit 前一律先向使用者確認，
     而這一側沒有人可以確認。
     ⚠️ 保障**換了一層**：先前靠「沒有 Bash 就碰不到索引」，
     現在靠 `guard/pretool_guard.py`（掛在 `--settings` 的 PreToolUse）擋 git 寫入。
     那支擋的是**誤觸與順手**，不是刻意繞過 —— 殘餘風險由「前後 `git status` 快照」補。
  3. **cwd ＝ repo root** —— 這樣 session 才會自動載入 `CLAUDE.md` 與 `.claude/skills/`。
     ⭐ 這也是「**skill 是平台的大腦**」那句話的實際落點（ROADMAP §2）。
  4. **`claude.exe` 不在或沒登入時要優雅停用**，不可讓整個平台掛掉 ——
     同事可能只想用索引與執行，不接對話。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading

from core.claude_probe import find_executable, probe_claude
from core.paths import LOGS_DIR, REPO_ROOT, python_exe

# 唯讀工具白名單（見紀律 1）。平台自己的 MCP 另外用 mcp__ 前綴放行。
READONLY_TOOLS = ["Read", "Grep", "Glob", "WebFetch"]
MCP_PREFIX = "mcp__test-platform"

# ⛔ **明確拒絕清單 —— 這才是真正擋得住的那一半。**
#
#    2026-08-23 兩次實測才收斂到這份清單：
#      ① 只給 `--allowedTools` 白名單 → session 照樣跑了 `Bash: git status --short`。
#         **白名單在 headless 模式下不是「只准這些」**，要擋就得明確拒絕。
#      ② 擋掉 Bash 之後 → 它**改用 `PowerShell`** 跑同一個指令。
#         這個環境同時有兩個 shell 工具，漏一個就等於沒擋。
#
#    所以清單是**從 `_init` 事件的實際工具全貌反推**的（不是憑印象列）：
#    保留 SAFE_TOOLS，其餘一律拒絕。
DENIED_TOOLS = [
    # ⭐ 2026-08-25：shell 與寫檔**已經還回去了** —— 見下方 SAFE_TOOLS 的說明。
    #    擋 git 寫入與「刪到自己家以外」改由 `guard/pretool_guard.py`（PreToolUse）負責，
    #    因為那才是真正要擋的兩件事，而「整個不給 shell」連規範都一起擋掉了。
    "NotebookEdit",
    # 會派生其他 agent／工作流（權限會被放大）
    "Task", "Workflow", "SendMessage", "ListAgents", "RemoteTrigger",
    # 排程與通知（會在對話結束後繼續發生事情）
    "CronCreate", "CronDelete", "CronList", "ScheduleWakeup",
    "PushNotification", "Monitor",
    # 對外發布／改動工作區狀態
    "Artifact", "DesignSync", "EnterWorktree", "ExitWorktree",
]

# 預設放行的工具。
# ⭐ `Skill` 一定要留 —— 「skill 是平台的大腦」靠它落實（ROADMAP §2）。
#
# ⭐ **2026-08-25：shell 與寫檔加了回來**（使用者裁示：「目標是平台 session
#    能做到與終端機 session 幾乎相同的事」）。
#    先前「一律不給」擋掉的不只是風險，**也擋掉了規範本身**：
#      · `bug-report` 要求「截圖拍完立刻 `stamp_shots.py` 搬走」→ 跑不了 → 8 張佐證整批遺失
#      · `writeback` 要求回寫後跑 `lint_docs` → 跑不了
#      · 知識回寫要 `next_todo_id.py` 當下取號 → 只能用推算的，會撞號
#    一個做不到規範的 session，交出來的東西**看起來像做完了，其實沒有**。
#
# ⛔ 放寬的前提是護欄先成立（`guard/pretool_guard.py`，掛在 `--settings` 的 PreToolUse）：
#    擋 **git 寫入**（提交要人點頭、索引是共用的）與 **刪到自己家以外**（2026-08-25 的事故）。
#    ⚠️ 護欄擋的是「誤觸與順手」，不是「刻意繞過」—— `python -c` 包一層仍然穿得過去。
#       真正降低殘餘風險的是「它沒有動機這麼做」＋「前後 `git status` 快照看得見它改了什麼」。
SAFE_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch",
              "ToolSearch", "Skill", "ReportFindings",
              # shell：兩個都要給 —— skill 裡寫的是 PowerShell 語法
              # （`python scripts\lint_docs.py`），在 bash 底下反斜線會被吃掉。
              "Bash", "BashOutput", "KillShell", "PowerShell",
              # 寫檔：與其讓它用 `python -c` 偷偷寫（看不見），不如明著給（工具列看得到）
              "Write", "Edit"}

# ⏱ 單次對話的上限（秒）。
#
# ⚠️ 這裡原本是 300 —— 而「探索新功能」任務的表單自己提供 **60／90 分鐘**的時間盒。
#    平台等於一邊說「你有 90 分鐘」，一邊在第 5 分鐘把程序殺掉，而且**不留任何訊息**
#    （被 kill 的程序沒有 stderr，錯誤那一段的兩個條件都不成立）。
#    2026-08-23 範本實跑時，探索 session 就只留下 82 個字。
#
# ⛔ **不再設逾時**（2026-08-26 使用者裁示）—— 延續 2026-08-23「移除時間盒」的同一條理由：
#    「沒有人能準確預測 session 運行時長，時間盒反而可能造成執行過程的資料遺失的風險。」
#    而 session 的工作量又長了一截：案例要**逐條跑 ＋ 整檔跑兩次**，
#    22 條 UI 案例跑三輪遠遠不只三小時。被砍掉的代價是已經跑了幾小時的產出。
# ⚠️ 代價：程序真的掛死時不會自己結束，要人在 session 列表按「關閉」。
#    掛死是罕見的，中途被砍是每次都可能發生的 —— 這個取捨是知情下做的。
DEFAULT_TIMEOUT = None


def available():
    """(可不可用, 原因)。不可用時 UI 要停用對話並顯示原因。"""
    info = probe_claude()
    if not info.get("executable"):
        return False, ("找不到 claude.exe。裝了 Claude Code 之後重開平台，"
                       "或在 config/platform_config.local.json 指定 claude.executable")
    auth = info.get("auth") or {}
    if not auth.get("loggedIn"):
        return False, "claude.exe 找到了但尚未登入 —— 在終端機執行 `claude` 登入後重試"
    return True, ""


#: 護欄腳本與它產生出來的 settings 檔（後者在 logs/ 底下 —— 已排除版控）
GUARD_SCRIPT = os.path.join(REPO_ROOT, "tools", "test_platform", "guard", "pretool_guard.py")
SETTINGS_FILE = os.path.join(LOGS_DIR, "session_settings.json")


def write_settings(path: str = SETTINGS_FILE) -> str:
    """產生**只給平台 session 用**的 settings（掛 PreToolUse 護欄）。回傳路徑。

    ⭐ 為什麼是 `--settings` 而不是專案的 `.claude/settings.json`：
      後者對**終端機 session 也會生效** —— 而那一側有人看著，不該被同一條線綁住
      （人隨時可以決定要不要 commit）。這個檔只在平台起 session 時掛上去。

    ⚠️ 用絕對路徑：hook 程序的 cwd 不保證是 repo root。
    """
    cfg = {"hooks": {"PreToolUse": [{
        "matcher": "Bash|PowerShell|BashOutput",
        "hooks": [{"type": "command",
                   "command": '"%s" "%s"' % (python_exe(), GUARD_SCRIPT)}],
    }]}}
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return path


#: 🛟 安全網門檻（token）。⚠️ CLI 只收 100k~1M，超出範圍會直接拒絕啟動。
DEFAULT_AUTOCOMPACT = 500_000


def _autocompact_tokens():
    """安全網門檻，可由設定檔 `claude.autocompact_tokens` 覆寫。

    ⚠️ **一定要夾在 100k~1M** —— CLI 對範圍外的值回
    `option '--autocompact <auto|tokens>' argument '50000' is invalid`
    然後**整支起不來**。設定寫錯不該讓平台的對話全掛。
    """
    try:
        from core.config import load_config
        v = (load_config().get("claude") or {}).get("autocompact_tokens")
        if v is not None:
            return max(100_000, min(1_000_000, int(v)))
    except Exception:                           # noqa: BLE001
        pass
    return DEFAULT_AUTOCOMPACT


def build_argv(text, *, session_id=None, model=None, resume=None, allow_tools=None):
    """組出 headless 呼叫。

    ⚠️ **白名單與拒絕清單都要下** —— 只下白名單擋不住（見 DENIED_TOOLS 的說明）。
    """
    exe, _ = find_executable()
    # ⭐ `allow_tools` 是**追加**，不是取代 —— SAFE_TOOLS 是唯讀底線
    #    （`Read`／`Grep`／`Glob` ＋ **`Skill`**）。取代的話探索 session 只剩
    #    宣告的那個 MCP，連 skill 都載入不了，而任務 prompt 的第一句就是
    #    「載入 `<產品 skill>` 與 `testcase-design`」（2026-08-23 範本驗收）。
    #    ⛔ 放寬的疑慮由 DENIED_TOOLS 承擔，不靠這裡收窄。
    tools = sorted(SAFE_TOOLS | set(allow_tools or []))
    tools.append(MCP_PREFIX)               # 平台自己的唯讀索引 ＋ propose_run
    argv = [exe, "-p", text,
            "--output-format", "stream-json", "--verbose",
            "--allowedTools", ",".join(tools),
            # ⛔ 白名單擋不住（實測過），要靠這一行
            "--disallowedTools", ",".join(DENIED_TOOLS),
            # ⛔ shell 開放之後的最後一道：擋 git 寫入與「刪到自己家以外」
            #    （`guard/pretool_guard.py`，只套用在平台 session）
            "--settings", write_settings(),
            # 🛟 **安全網，不是省 token 的手段** —— 省是 `core/session_compact.py`
            #    的邊界壓縮在做。這一個只擋「單段失控」：一則訊息內跑幾百輪、
            #    中間沒有任何邊界可壓。所以門檻刻意很高，平常不該觸發。
            #    ⛔ 調低就等於回到「途中壓縮」，會壓掉還沒寫成草稿的量測值。
            "--autocompact", str(_autocompact_tokens())]
    if model:
        argv += ["--model", model]
    if resume:
        argv += ["--resume", resume]
    return argv


def ask(text, *, session_id=None, model=None, resume=None, allow_tools=None,
        timeout=DEFAULT_TIMEOUT, _popen=None):
    """送一則訊息，**逐段 yield** 事件（供 SSE 串流）。

    事件形狀（前端只認這四種，不必懂 claude 的原始 schema）：
        {"type": "text",  "text": "..."}          助理輸出的一段
        {"type": "tool",  "name": "...", "input": {...}}   它呼叫了哪個工具
        {"type": "done",  "session_id": "...", "usage": {...}}
        {"type": "error", "message": "..."}
    """
    okay, why = available()
    if not okay:
        yield {"type": "error", "message": why}
        return

    argv = build_argv(text, session_id=session_id, model=model,
                      resume=resume, allow_tools=allow_tools)
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    popen = _popen or subprocess.Popen
    try:
        proc = popen(argv, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True,
                     encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        yield {"type": "error", "message": "啟動 claude.exe 失敗：%s" % e}
        return

    # ⚠️ 用一個可變旗標記下「是被逾時殺的」—— 被 kill 的程序沒有 stderr，
    #    不記的話下面的錯誤分支永遠不會觸發，session 會**無聲截斷**。
    killed = []
    # ⛔ `timeout` 為 None／<=0 就**不設上限**（2026-08-26 起的預設）。
    killer = threading.Timer(timeout, _kill, args=(proc, killed)) if timeout else None
    if killer:
        killer.start()
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue                    # 非 JSON 的雜訊行：忽略
            for out in _translate(ev):
                yield out
    finally:
        if killer:
            killer.cancel()
        try:
            proc.stdout.close()
        except Exception:                   # noqa: BLE001
            pass
        code = proc.wait()
        err = (proc.stderr.read() or "").strip() if proc.stderr else ""
        if killed:
            # ★ 這一則不能省 —— 沒有它，逾時看起來就只是「它自己講完了」
            yield {"type": "error",
                   "message": ("已達本次的時間上限（%s），session 被中止。"
                               "上面的內容是**中止前產出的部分**，已經留下來了。"
                               "要接下去的話**直接再送一則訊息**（例如「接著剛才的繼續」）"
                               "—— 它會帶著完整脈絡接下去，不必從頭講一次。"
                               % _human_duration(timeout))}
        elif code not in (0, None) and err:
            yield {"type": "error", "message": err[:800]}


def _translate(ev):
    """把 claude 的 stream-json 事件翻成前端認得的四種。

    ⚠️ 只挑需要的欄位 —— 原始 schema 會演進，翻譯層擋在中間，
      前端與 `chat.py` 都不必跟著改。
    """
    t = ev.get("type")
    if t == "assistant":
        for block in ((ev.get("message") or {}).get("content") or []):
            if block.get("type") == "text" and block.get("text"):
                yield {"type": "text", "text": block["text"]}
            elif block.get("type") == "tool_use":
                yield {"type": "tool", "name": block.get("name"),
                       "input": block.get("input") or {}}
    elif t == "result":
        yield {"type": "done",
               "session_id": ev.get("session_id"),
               "usage": ev.get("usage") or {},
               "cost_usd": ev.get("total_cost_usd"),
               "is_error": bool(ev.get("is_error"))}
    elif t == "system" and ev.get("subtype") == "init":
        tools = ev.get("tools") or []
        # ★ 執行期自檢：Claude Code 日後新增工具時，拒絕清單會**靜默過期** ——
        #   冒出沒見過的工具就記一筆，讓人有機會重新評估（不阻斷對話）。
        unexpected = [x for x in tools
                      if x not in SAFE_TOOLS and not x.startswith("mcp__")]
        if unexpected:
            import sys as _s
            print("⚠️ claude_session：出現未分類的工具 %s —— "
                  "請評估要不要加進 DENIED_TOOLS" % unexpected, file=_s.stderr)
        yield {"type": "tool", "name": "_init",
               "input": {"session_id": ev.get("session_id"),
                         "tools": tools, "unexpected_tools": unexpected,
                         "mcp_servers": ev.get("mcp_servers") or []}}


def _human_duration(sec) -> str:
    """秒 → 人看得懂的字。

    ⚠️ 先前是 `timeout // 60`，90 秒會顯示成「1 分鐘」——
       **講錯了上限**，人會以為自己設的時間盒沒生效（2026-08-23 實測畫面）。
    """
    sec = int(sec or 0)
    if sec < 90:
        return "%d 秒" % sec
    m, r = divmod(sec, 60)
    return "%d 分鐘" % m if r < 6 else "%d 分 %d 秒" % (m, r)


def _kill(proc, flag=None):
    """逾時處置。`flag` 是給呼叫端知道「這是被殺的、不是自己結束的」。"""
    if flag is not None:
        flag.append(True)
    try:
        proc.kill()
    except Exception:                       # noqa: BLE001
        pass
