# -*- coding: utf-8 -*-
"""壓測控制台 ↔ 平台 tool.json 的欄位對照盤點（階段 G-0，2026-08-23）。

用途
----
使用者要求「**平台的設定介面需要與舊控制台一致**」。實查的落差：

    控制台          表單控制項   已對到   顯示用   已被平台取代   **待補**
    CRUX  (:5000)        43        9       5          13          16
    七星  (:5200)        27       10       0           8           9
    wbot  (:5100)        27        5       3           1          18
    ──────────────────────────────────────────────────────────────
    合計                 97       24       8          22          43

（先前憑目測估「115 個控制項」，實查以 `id=`/`name=` 為準是 97 個 ——
  這正是要有這支腳本而不是靠目測的原因。）

**待補 43 個。** 直接吸收會讓這些設定從介面上消失，而且**沒有人會發現**
（跑得起來、只是某個參數用了預設值）。

所以吸收的第一步是產出**欄位對照表**：舊控制台的每個控制項要嘛對到一個
tool.json 的 field，要嘛明確標成「顯示用」「已由平台取代」或「待補」。
⛔ **未歸屬（gap）必須為零** —— 那代表「還沒有人看過它」。

使用方式
--------
    python scripts\\perf_field_parity.py            # 列出對照結果
    python scripts\\perf_field_parity.py --gaps     # 只列還沒歸屬的
    python scripts\\perf_field_parity.py --json     # 給測試用

前置條件
--------
· 控制台的控制項以 HTML 的 `id=` / `name=` 為準（那是它們送參數的鍵）。
· 豁免清單寫在本檔的 `EXEMPT`，**每一條都要寫理由** —— 寫不出理由的，
  表示它其實該對到一個 field。
"""
import argparse
import glob
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")

CONSOLES = {
    "crux_perf": ("CRUX", "tools/CRUX_Performance/web_ui/static"),
    "qixing_perf": ("七星", "tools/qixing_Performance/web_ui/static"),
    "wbot_perf": ("投注機器人", "tools/wbot_Performance/web_ui/static"),
}

# 控制台上**不是設定**的控制項 —— ⚠️ **逐鍵明列，每條寫理由**。
#
# 第一版用子字串啟發式（key 含 "cancel"／"search" 就算顯示用），結果把
# `cancel_after_bet_count`（退碼設定）判成顯示用 —— 那是真設定。
# 判錯的代價是「盤點說沒問題，但吸收後那個參數不見了」，而且沒有人會發現。
EXEMPT = {
    # 1) 純顯示／互動，不進參數
    "display": {
        "api-op-search": "OpenAPI 操作清單的搜尋框",
        "api-profile-save-mode": "存檔方式（新增/覆蓋），屬存檔動作不是壓測參數",
        "api-profile-file": "profile 檔名，屬存檔動作不是壓測參數",
        "api-profile-note": "profile 備註，屬存檔動作不是壓測參數",
        "save-profile-name": "存檔用的 profile 名，屬存檔動作不是壓測參數",
        "save-profile-note": "存檔用的備註，屬存檔動作不是壓測參數",
        "debug_player_history": "偵錯開關：把某會員的下注歷史印出來，不影響壓測行為",
    },
    # 2) 已由平台的既有機制取代
    "replaced": {
        "modal-db-host": "DB 連線 → 平台走 config/config.local.json（憑證設定頁，階段 F）",
        "modal-db-port": "DB 連線 → 走 config.local.json（憑證設定頁）",
        "modal-db-name": "DB 連線 → 走 config.local.json（憑證設定頁）",
        "modal-db-user": "DB 連線 → 走 config.local.json（憑證設定頁）",
        "modal-db-password": "DB 密碼 → 走 config.local.json；⛔ 憑證不可進 tool.json 的 fields",
        "modal-director-account": "總監帳密 → 同上，走 config.local.json",
        "modal-director-pwd": "總監密碼 → 走 config.local.json（憑證設定頁）",
        "modal-member-pwd": "會員預設密碼 → 走 config.local.json（憑證設定頁）",
        "api-member-default-pwd": "會員預設密碼 → `run_api_perf` 退回 config/case6_env_config.json 的 Credentials（或環境變數 CRUX_MEMBER_DEFAULT_PWD）",
        "api-openapi-file": "OpenAPI 規格檔 → 端點的挑選仍在舊控制台完成並**存成 profile**；平台跑的是 profile，不必再讀規格檔",
        "chatroom_login_pwd": "聊天室密碼 → 走 config.local.json；⛔ 憑證不進 fields",
        "preflight-smoke-bet": "前置冒煙 → 已由 registry 的 run.gate 宣告取代",
        "headless": "瀏覽器模式 → 平台一律 headless 執行（run 是背景工作）",
    },

    # 3) **屬於平台還沒吸收的命令** —— 不是「待補欄位」
    #    ⚠️ 這一類與 todo 的差別很重要：todo 是「這個命令該有這個欄位」，
    #    not_absorbed 是「這個命令平台根本還沒有」。
    #    把它們當 todo 補進最近的命令，就會做出「填了不生效」的假欄位
    #    —— G-1 實際犯過一次（8 個 api-* 被塞進 bet_load）。
    "not_absorbed": {
        # ✅ 2026-08-24 清空：CRUX 的「OpenAPI 壓測」已吸收成 `crux_perf.api_load`
        #    （薄殼 `tools/CRUX_Performance/scripts/run_api_perf.py`）。
        #    ⚠️ 這一類**刻意保留** —— 下一個要吸收的工具還會用到，而它與 `todo`
        #    的差別是本檔最該記住的一件事：todo 是「這個命令該有這個欄位」，
        #    not_absorbed 是「這個命令平台根本還沒有」。混掉的代價是做出
        #    **填了不生效的假欄位**（G-1 對這 8 個 api-* 實際犯過一次）。
    },
}

# 4) **要補進 tool.json 的真設定** —— 這份清單就是 G-1 的工作項目。
#    盤點的產出不是「全部歸零」，而是把「哪些還沒補」講得清清楚楚。
TODO_FIELDS = {
    "crux_perf": [
        "cancel_after_bet_count", "enable_cancel_bets", "enable_wallet_check",
        "game_mode", "member_list_file", "sleep_after_bet", "stop_members",
        "wallet_sync_mode",
    ],
    "qixing_perf": [
        "backend_host", "host", "cancel_bets_enabled", "director_delay_mins",
        "enable_director_close_settle", "member_list_file", "reopen_after_settle",
        "single_player_bet_limit", "stop_members_on_director_close",
    ],
    "wbot_perf": [
        "bet_index_refresh_sec", "bet_interval_start", "bet_interval_end",
        "bet_profile_name", "create_player", "create_player_count",
        "master_count", "master_url", "max_overrun_sec", "num_processes",
        "period_poll_idle_sec", "player_bet_target", "player_wait_time",
        "players_per_master", "stop_at_period_boundary", "stop_grace_sec",
        "update_balance", "update_player",
    ],
}

# 控制台的 key ↔ tool.json 既有的 key —— **同一個設定的兩種叫法**。
#
# ⚠️ 沒有這張表，盤點會把它們判成「待補」，而 G-1 的補欄位腳本就會
#    真的補進去 —— 於是同一個設定在表單上出現兩次、argv 拿到兩次同一個旗標。
#    CRUX 更糟：`wallet_check`(--wallet-check) 與 `enable_wallet_check`
#    (--no-wallet-check) 是正反面，兩個都送引擎會直接以「不可同時指定」退出。
#    （2026-08-23 實際發生，三支工具共 16 對。）
ALIAS = {
    'crux_perf': {
        # 「OpenAPI 壓測」頁 → `api_load` 命令（2026-08-24 吸收）
        'api-profile-select': 'api_profile',
        'api-base-url': 'api_base_url',
        'api-signin-path': 'api_signin_path',
        'api-timeout': 'api_timeout',
        'api-verify-ssl': 'api_verify_ssl',
        'api-users-mode': 'api_users_mode',
        'api-member-list-file': 'api_member_list_file',
        'api-auth-enabled': 'api_auth',
        'api-auth-account': 'api_account',
        'api-auth-password': 'api_password',
        'enable_cancel_bets': 'cancel_bets',
        'enable_wallet_check': 'wallet_check',
        'stop_members': 'stop_members_on_close',
    },
    'qixing_perf': {
        # ⛔ 控制台的 `director_delay_mins` 與 `delay` 是**同一個 argparse dest**
        #    （`-d, --delay`）。tool.json 原本兩個欄位都留著 —— 兩個都填就會組出
        #    `-d 10 --delay 15`，argparse 取後者，而畫面上看不出哪個算數。
        #    2026-08-24 刪掉重複的那個，改用別名對回既有欄位。
        'director_delay_mins': 'delay',
        'cancel_bets_enabled': 'cancel',
        'enable_director_close_settle': 'director',
        'member_list_file': 'member_list',
        'reopen_after_settle': 'reopen',
        'single_player_bet_limit': 'player_limit',
    },
    'wbot_perf': {
        'bet_interval_end': 'interval_end',
        'bet_interval_start': 'interval_start',
        'bet_profile_name': 'profile',
        'master_count': 'masters',
        'num_processes': 'processes',
        'player_wait_time': 'player_wait',
        'players_per_master': 'players',
        'stop_at_period_boundary': 'boundary',
    },
}


_CTRL = re.compile(
    r'<(?:input|select|textarea)\b[^>]*?\b(?:id|name)\s*=\s*["\']([A-Za-z0-9_\-]+)["\']',
    re.I)


def console_controls(rel_dir):
    """掃控制台 HTML 的表單控制項鍵。"""
    out = {}
    for p in sorted(glob.glob(os.path.join(ROOT, rel_dir, "*.html"))):
        try:
            html = io.open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in _CTRL.finditer(html):
            out.setdefault(m.group(1), os.path.basename(p))
    return out


def tool_fields(tool_id):
    """tool.json 宣告的 {field key: emit}（含所有命令）。

    ⚠️ 回 emit 而不是只回 key —— **欄位存在不等於設定會生效**。
    `emit: none` 的欄位在表單上看得到、填得下去，但**組不進命令列也不進環境變數**，
    引擎收不到。這正是本盤點要防的「設定悄悄消失」，只是換了個形態：
    從「介面上不見了」變成「介面上有、按下去沒作用」——後者更難發現。
    """
    p = os.path.join(PLATFORM, "registry", "%s.tool.json" % tool_id)
    if not os.path.isfile(p):
        return {}
    d = json.load(io.open(p, encoding="utf-8"))
    out = {}
    for c in d.get("commands", []):
        for f in ((c.get("params") or {}).get("fields") or []):
            out[f["key"]] = f.get("emit") or ("flag_when_true" if f.get("type") == "boolean"
                                              else ("opt" if f.get("arg") else "none"))
    return out


def resolve_alias(key, tool_id=""):
    """控制台的 key 換成 tool.json 既有的 key（沒有別名就原樣回）。"""
    return (ALIAS.get(tool_id) or {}).get(key, key)


def classify(key, tool_id=""):
    """(歸屬, 理由)。歸屬 ∈ field｜display｜replaced｜todo｜gap

    · `todo` ＝ 已確認是真設定、還沒補進 tool.json（G-1 的工作項目）
    · `gap`  ＝ **還沒有人看過它** —— 這才是要擋下來的狀態
    """
    if key in EXEMPT["replaced"]:
        return "replaced", EXEMPT["replaced"][key]
    if key in EXEMPT["display"]:
        return "display", EXEMPT["display"][key]
    if key in EXEMPT.get("not_absorbed", {}):
        return "not_absorbed", EXEMPT["not_absorbed"][key]
    if key in (TODO_FIELDS.get(tool_id) or []):
        return "todo", "真設定，待補進 tool.json"
    return "gap", ""


def report():
    out = {}
    for tool_id, (label, rel) in CONSOLES.items():
        ctrls = console_controls(rel)
        fields = tool_fields(tool_id)
        rows = []
        for key in sorted(ctrls):
            fk = resolve_alias(key, tool_id)
            if fk in fields:
                if fields[fk] == "none":
                    rows.append({"key": key, "kind": "inert",
                                 "why": "欄位有，但 emit:none —— **填了不會送到引擎**"})
                else:
                    rows.append({"key": key, "kind": "field",
                                 "why": "已對到 tool.json（emit=%s）" % fields[fk]})
                continue
            kind, why = classify(key, tool_id)
            rows.append({"key": key, "kind": kind, "why": why, "file": ctrls[key]})
        out[tool_id] = {
            "label": label, "console_controls": len(ctrls),
            # 控制台目錄在不在 —— 不在時 main() 要說「略過」而不是算進綠燈
            "console_exists": os.path.isdir(os.path.join(ROOT, *rel.split("/"))),
            "declared_fields": len(fields), "rows": rows,
            "gaps": [r["key"] for r in rows if r["kind"] == "gap"],
            "todo": [r["key"] for r in rows if r["kind"] == "todo"],
            "inert": [r["key"] for r in rows if r["kind"] == "inert"],
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="壓測控制台 ↔ tool.json 欄位對照")
    ap.add_argument("--gaps", action="store_true", help="只列還沒歸屬的")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（給測試用）")
    a = ap.parse_args(argv)

    rep = report()
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    # ⚠️ 不在本工作區的控制台要**明講略過** —— 對著 0 個控制項印綠燈，
    #    等於宣稱「盤點過了」，而其實什麼都沒盤。（2026-08-23 在範本裡踩到。）
    absent = [tool_id for tool_id, d in rep.items() if not d.get("console_exists", True)]
    for tool_id in absent:
        print("\n%s（%s）—— ⏭ 略過：本工作區沒有 %s"
              % (rep[tool_id]["label"], tool_id, CONSOLES[tool_id][1]))
        rep.pop(tool_id)
    if not rep:
        print("\n沒有可盤點的壓測控制台 —— 本工作區沒有接任何壓測工具。")
        return 0

    total_gap = 0
    for tool_id, d in rep.items():
        n = {k: sum(1 for r in d["rows"] if r["kind"] == k)
             for k in ("field", "inert", "display", "replaced", "not_absorbed",
                       "todo", "gap")}
        total_gap += n["gap"]
        print("\n%s（%s）—— 控制項 %d、tool.json 宣告 %d"
              % (d["label"], tool_id, d["console_controls"], d["declared_fields"]))
        print("   已對到 %d｜**填了不生效 %d**｜顯示用 %d｜已由平台取代 %d｜"
              "命令未吸收 %d｜待補 %d｜未歸屬 %d"
              % (n["field"], n["inert"], n["display"], n["replaced"],
                 n["not_absorbed"], n["todo"], n["gap"]))
        for r in d["rows"]:
            if a.gaps and r["kind"] != "gap":
                continue
            mark = {"field": "  \u2713", "inert": "  \u26a0", "display": "  \u00b7",
                    "replaced": "  ~", "not_absorbed": "  \u25b3", "todo": "  \u25cb",
                    "gap": "  \u274c"}[r["kind"]]
            print("%s %-26s %s" % (mark, r["key"], r["why"] or "**還沒歸屬**"))

    todo_n = sum(len(d["todo"]) for d in rep.values())
    print("\n" + "=" * 60)
    print("待補進 tool.json 的真設定：%d 個（G-1 的工作項目）" % todo_n)
    if total_gap:
        print("❌ 還有 %d 個控制項沒有歸屬 —— 直接吸收會讓它們從介面上消失，"
              "而且沒有人會發現（跑得起來、只是用了預設值）。" % total_gap)
        print("   → 是設定就補進 tool.json 的 fields；"
              "不是設定就加進本檔的 EXEMPT（**要寫理由**）。")
        return 1
    total = sum(d["console_controls"] for d in rep.values())
    print("✅ %d 個控制項全部有歸屬。" % total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
