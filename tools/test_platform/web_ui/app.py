"""測試助手 Web 服務（Flask :5300）—— 只做組裝與 blueprint 註冊。

用途：測試助手的入口；Dashboard（態勢感知）／工具操作／案例瀏覽器／執行監控／報告中心／
      待辦與 Bug 現況／Claude 上線檢查。前端為純靜態 ES modules，零建置。
使用方式：
    tools\\test_platform\\run_server.bat            # 用工作區 .venv → http://127.0.0.1:5300
前置條件：
    · 統一使用工作區 .venv（flask/psutil/requests 已有）。
    · host 預設 127.0.0.1 —— 同事各自跑自己的實例、用自己的 Claude 帳號；改 0.0.0.0 需手動且 UI 亮紅。
    · ⚠️ 改了本檔 import 的模組必須重啟 Flask（Python 不會重新載入已 import 的模組）。
API 慣例（沿用三個壓測控制台）：成功 {ok:true,...}；失敗 {ok:false,error} + 400／404／409；密碼只回 *_set:bool。
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from flask import Flask, jsonify, send_from_directory  # noqa: E402

from core.config import load_config  # noqa: E402
from core.paths import STATIC_DIR  # noqa: E402
from web_ui.api import register_all  # noqa: E402


def create_app() -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False  # type: ignore[attr-defined]
    # ⚠️ Flask 預設會**排序 JSON 的鍵**，於是 json_table 的欄位順序被改成字典序 ——
    #    「玩法／號碼／金額／小計」變成「小計／玩法／號碼／金額」，讀起來就亂了。
    #    產生資料的一方（腳本或 adapter）才知道正確的欄位順序，這裡不要動它。
    app.json.sort_keys = False  # type: ignore[attr-defined]

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.after_request
    def _no_cache_static(resp):
        # 零建置的 ES modules：靜態檔一律不快取，改檔即生效（內網單人工具，頻寬不是問題）
        if resp.mimetype in ("text/javascript", "application/javascript", "text/css", "text/html"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(404)
    def _404(e):
        return jsonify({"ok": False, "error": "not found"}), 404

    @app.errorhandler(500)
    def _500(e):
        return jsonify({"ok": False, "error": str(e)}), 500

    register_all(app)
    return app


app = create_app()


def main() -> None:
    cfg = load_config()
    host, port = cfg.get("host", "127.0.0.1"), int(cfg.get("port", 5300))

    # ⭐ 收拾上一次沒有好好結束的東西（2026-08-24）——
    #    run 的「進行中」只活在程序記憶體裡，session 的收尾在 `finally`，
    #    平台被 kill 時兩者都留下不一致的狀態（run 從 UI 消失、session 永遠卡 running）。
    #    ⛔ 只能在這裡跑（啟動當下保證只有一個實例）；執行期呼叫會把正在跑的標成中止。
    from core import reconcile
    fixed = reconcile.on_startup()
    if fixed["runs"] or fixed["sessions"]:
        print(f"已收拾上次中斷的：{fixed['runs']} 個 run、{fixed['sessions']} 個 session")

    print(f"測試助手：http://{host}:{port}")
    if host not in ("127.0.0.1", "localhost"):
        print("⚠️ host 非 127.0.0.1 —— 其他人連進來會用你的 OS 身分與 Claude 帳號執行，請確認這是你要的。")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
