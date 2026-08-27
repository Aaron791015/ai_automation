"""前置檢查結果的存放：讓 sync 命令（preflight 這類）的結論能被後續的 run 看見。

用途：走查發現「前置檢查跑出 ❌（DB 連線失敗）卻不擋執行，30 分鐘壓測註定白跑」。
      結果原本只回前端、離開頁面就消失，`manager.start` 也完全不看它。
使用方式：
    from core import check_store
    check_store.save(tool_id, command_id, params, result)     # sync 命令回傳前寫一份
    check_store.latest(tool_id)                               # {command_id: {...}}，給工具頁判斷
前置條件：
    · 存 `logs/checks/<tool_id>/<command_id>.json`，一個命令只留最新一次（歷史在 run 那邊，不在這）。
    · `ok` 的判定：checklist 型看每個 item 的 ok；其餘型別沒有明確語意，一律視為 True。
    · ⛔ 只提示不硬擋 —— 有時就是要在環境不全的情況下跑（例如刻意驗「後端掛掉時前台怎麼反應」）。
"""
from __future__ import annotations

import os
import time

from core.jsonio import read_json, write_json_atomic
from core.paths import LOGS_DIR

CHECKS_DIR = os.path.join(LOGS_DIR, "checks")


def _path(tool_id: str, command_id: str) -> str:
    return os.path.join(CHECKS_DIR, tool_id, f"{command_id}.json")


def result_ok(result: dict | None) -> bool:
    """checklist 有任何一項 ok=False 就算沒過；其他結果型別無明確語意，視為通過。"""
    if not isinstance(result, dict):
        return True
    if result.get("kind") == "checklist":
        return all(bool(i.get("ok")) for i in (result.get("items") or []))
    return True


#: 存下來的結果上限（字元）。超過就截斷 —— `parse_batch` 這類會回幾千列。
MAX_RESULT_CHARS = 200_000


def save(tool_id: str, command_id: str, params: dict, result: dict | None,
         *, extra: dict | None = None) -> dict:
    """存這個 sync 命令的最近一次執行。

    ⭐ 2026-08-24 起**連完整結果一起存** —— 先前只存 `ok` 與失敗項的 label，
      於是結果離開頁面就消失（走查盲點 ①）。而 sync 佔 28/33 條命令，
      其中包含 `export`（匯出範本給同事）與 `recycle_issue`（`danger: high`）。

    ⚠️ 一個命令只留**最新一次** —— 歷史在 run 那邊，這是本檔原本就定好的邊界。
    """
    rec = {
        "tool_id": tool_id, "command_id": command_id,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "at_ts": time.time(),
        "ok": result_ok(result),
        "params": params or {},
        "failed": [i.get("label") for i in ((result or {}).get("items") or []) if not i.get("ok")],
        "result": _capped(result),
        **(extra or {}),
    }
    write_json_atomic(_path(tool_id, command_id), rec)
    return rec


def _capped(result: dict | None) -> dict | None:
    """結果太大就截斷 —— 存不下不是理由讓 `logs/checks/` 無限長大。"""
    if not result:
        return result
    import json as _json
    try:
        blob = _json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"kind": "text", "text": "（結果無法序列化，只留摘要）"}
    if len(blob) <= MAX_RESULT_CHARS:
        return result
    kind = result.get("kind")
    if kind == "text":
        return {**result, "text": (result.get("text") or "")[:MAX_RESULT_CHARS],
                "truncated": True}
    # 表格類：留前 200 列就夠看出長相，人要完整的去看產物本身
    for key in ("rows", "items"):
        if isinstance(result.get(key), list):
            return {**result, key: result[key][:200], "truncated": True}
    return {"kind": "text", "text": "（結果過大，未保存；重跑一次可看完整內容）",
            "truncated": True}


def get(tool_id: str, command_id: str) -> dict | None:
    return read_json(_path(tool_id, command_id))


def latest(tool_id: str) -> dict:
    """該工具所有 sync 命令的最近一次檢查結果：{command_id: rec}。"""
    d = os.path.join(CHECKS_DIR, tool_id)
    if not os.path.isdir(d):
        return {}
    out = {}
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        rec = read_json(os.path.join(d, fn))
        if rec:
            out[fn[:-5]] = rec
    return out


def gate_status(spec, command: dict) -> dict | None:
    """依命令宣告的 `gate` 判斷「該不該提醒」。回 None＝沒宣告 gate 或一切正常。

    回 {state, message, check}；state 為 notice／missing／stale／failed。

    ⚠️ 一律**只提示不硬擋**。`notice` 更是如此：平台看不到外部行程
    （你在終端機跑的 pytest、用 MCP 開的瀏覽器），硬擋只會擋錯人。
    """
    gate = command.get("gate") or {}

    # 靜態提示：與任何 check 無關，就是「跑之前請先確認這件事」。
    # 用途見 `ui_tests` 的子帳號互踢提示（C-5／R2-4）。
    notice = gate.get("notice")

    need = gate.get("requires_check")
    if not need:
        return {"state": "notice", "check": None, "message": notice} if notice else None
    rec = get(spec.id, need)
    label = next((c.get("label", need) for c in spec.commands if c.get("id") == need), need)
    if not rec:
        return {"state": "missing", "check": need,
                "message": f"尚未執行「{label}」—— 環境沒問題再跑比較保險"}
    age_min = (time.time() - float(rec.get("at_ts") or 0)) / 60
    max_age = gate.get("max_age_minutes")
    if not rec.get("ok"):
        bad = "、".join(rec.get("failed") or []) or "有項目未通過"
        return {"state": "failed", "check": need, "at": rec.get("at"),
                "message": f"「{label}」上次未通過（{rec.get('at')}）：{bad}"}
    if max_age and age_min > float(max_age):
        return {"state": "stale", "check": need, "at": rec.get("at"),
                "message": f"「{label}」是 {int(age_min)} 分鐘前跑的（建議 {max_age} 分鐘內），環境可能已經變了"}
    # check 一切正常，但仍有靜態提示要說
    if notice:
        return {"state": "notice", "check": need, "message": notice}
    return None
