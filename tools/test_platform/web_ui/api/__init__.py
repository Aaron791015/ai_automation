"""API blueprint 註冊與共用 helper。

用途：register_all(app) 掛上全部 blueprint；fail()／ok() 統一回應格式。
"""
from __future__ import annotations

from flask import jsonify


def ok(**kw):
    return jsonify({"ok": True, **kw})


def fail(message: str, code: int = 400, **kw):
    return jsonify({"ok": False, "error": str(message), **kw}), code


def register_all(app) -> None:
    from web_ui.api import (bootstrap, bugs_file, cases, chat, docs_api, drafts, knowledge,
                             registry_api, reports, runs, search, settings, sessions,
                             tasks_api, verif_reports)
    for m in (bootstrap, registry_api, runs, cases, reports, knowledge, search, settings, sessions,
              chat, docs_api, bugs_file, drafts, tasks_api, verif_reports):
        app.register_blueprint(m.bp)
