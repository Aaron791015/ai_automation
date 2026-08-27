"""/api/settings —— Claude 上線檢查 ＋ **憑證設定**（階段 F-1 起可寫）。

⛔ 三條安全紀律見 `core/credentials.py`：
   絕不回傳已存的密碼／讀-改-寫只動平台擁有的鍵／寫進不版控的 config.local.json。
"""
from __future__ import annotations

from flask import Blueprint, request

from core import config_files as F
from core import credentials as C
from core.claude_probe import probe_claude
from core.config import load_config
from web_ui.api import fail, ok

bp = Blueprint("settings", __name__)


@bp.get("/api/settings/claude")
def claude_settings():
    info = probe_claude(refresh=request.args.get("refresh") == "1")
    cfg = load_config().get("claude") or {}
    return ok(**info, default_model=cfg.get("default_model", "sonnet"), fallback_model=cfg.get("fallback_model"),
              models=[{"value": "sonnet", "label": "Sonnet（日常查詢，便宜）"}, {"value": "opus", "label": "Opus（深入分析）"}, {"value": "fable", "label": "Fable"}])


@bp.get("/api/claude/usage")
def claude_usage():
    """Claude 用量。transcript 統計不阻塞（背景重掃）；額度百分比 5 分鐘節流。

    `?quota=force` 繞過節流立刻重打 —— 給狀態列右上角那顆 ↻ 用（使用者主動按才會走）。
    """
    from core.claude_usage import usage_summary
    return ok(**usage_summary(refresh=request.args.get("refresh") == "1",
                              quota_force=request.args.get("quota") == "force"))


# ────────────────────────────────── 憑證設定（階段 F-1）

@bp.get("/api/settings/credentials")
def credentials_status():
    """⛔ 只回「有沒有設定 ＋ 最後更新」—— **不含任何密碼**。"""
    return ok(**C.status())


@bp.post("/api/settings/credentials")
def credentials_save():
    body = request.get_json(force=True, silent=True) or {}
    # ⚠️ 空字串 ＝ 不改（表單不會回填已存的密碼），要清空請用 DELETE
    return ok(**C.save(body.get("values") or {}))


@bp.delete("/api/settings/credentials/<group>/<key>")
def credentials_clear(group, key):
    if group not in C.OWNED or key not in C.OWNED[group]:
        return fail("不是平台管理的設定：%s.%s" % (group, key), 400)
    return ok(**C.clear(group, key))


@bp.post("/api/settings/credentials/test")
def credentials_test():
    """唯讀連線測試。⛔ 不寫 JIRA（`jira-verify` §0 的邊界）。"""
    body = request.get_json(force=True, silent=True) or {}
    which = body.get("which") or "jira"
    if which == "jira":
        return ok(**C.test_jira())
    if which == "jira_attachment":
        return ok(**C.test_jira_attachment(body.get("issue_key") or ""))
    return fail("未知的測試項目：%s" % which, 400)


# ────────────────────────────────── 設定檔編輯（2026-08-24）
# 「環境設定也需要可以在介面上進行（直接開檔，編輯 json 後再存回）」——使用者要求。
# ⛔ 白名單見 `core/config_files.py`：key 是固定字串，不是路徑參數（否則有 ../ 逃逸）。


@bp.get("/api/settings/files")
def config_files_list():
    return ok(**F.listing())


@bp.get("/api/settings/files/<key>")
def config_file_read(key):
    try:
        return ok(**F.read(key))
    except KeyError:
        return fail("不是平台管理的設定檔：%s" % key, 404)


@bp.get("/api/settings/files/<key>/backups")
def config_file_backups(key):
    try:
        return ok(**F.backups(key))
    except KeyError:
        return fail("不是平台管理的設定檔：%s" % key, 404)


@bp.post("/api/settings/files/<key>/validate")
def config_file_validate(key):
    body = request.get_json(force=True, silent=True) or {}
    okay, why = F.validate(key, body.get("text") or "")
    return ok(valid=okay, reason=why)


@bp.put("/api/settings/files/<key>")
def config_file_write(key):
    body = request.get_json(force=True, silent=True) or {}
    try:
        if body.get("restore"):
            return ok(**F.restore(key, body["restore"]))
        return ok(**F.write(key, body.get("text") or ""))
    except KeyError:
        return fail("不是平台管理的設定檔：%s" % key, 404)
    except ValueError as e:
        return fail(str(e), 400)
