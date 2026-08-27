"""allure CLI 的**唯一**解析與呼叫點。

為什麼需要這一支（2026-08-23 範本端到端驗收第 ⑦ 步發現的兩件事）：

① **兩套解析、兩個答案。** 儀表板的健康列用「npm 全域優先」找到 2.43.0，
   而工具頁的健康檢查用 `shutil.which("allure")` 找到 `C:\\Program Files\\allure-2.7.0`。
   同一台機器、同一個畫面上的兩處，報出不同版本 —— 而 **2.7.0 讀不動現代的
   allure-results**。`scripts/setup_test_env.ps1` 早就寫著「優先取 npm 全域安裝的
   allure（避免 PATH 上的舊版 2.7.0 蓋過）」，平台這側漏了。

② **`generate_allure` 是 inert 欄位。** `ui_tests.tool.json` 宣告了它、預設開、
   表單上看得到，`adapters/pytest_.py` 甚至有一個叫 `generating_reports` 的階段 ——
   但**沒有任何程式讀它**，也從來沒有人執行 `allure generate`。
   於是 `reports()` 找 `allure-report/index.html` 永遠找不到，
   使用者按下「產生 Allure 報告」什麼也不會發生。
   這正是階段 G 花最多力氣在防的「填了不生效」。

使用方式：
    from core.allure_cli import find_allure, generate
    ok, detail = generate(results_dir, out_dir)
"""
from __future__ import annotations

import os
import shutil
import subprocess

_cached: tuple[str | None, bool] = (None, False)


def find_allure(refresh: bool = False) -> str | None:
    """回 allure 執行檔路徑（找不到回 None）。

    ⭐ **npm 全域優先** —— PATH 上常留著很舊的 allure（本機是 2.7.0），
       它讀不動現代的 allure-results。與 `scripts/setup_test_env.ps1` 同一個順序。
    """
    global _cached
    if _cached[1] and not refresh:
        return _cached[0]
    found = None
    npm = shutil.which("npm")
    if npm:
        try:
            prefix = subprocess.run([npm, "prefix", "-g"], capture_output=True,
                                    text=True, timeout=10).stdout.strip()
            cand = os.path.join(prefix, "allure.cmd")
            if os.path.isfile(cand):
                found = cand
        except Exception:                       # noqa: BLE001 —— 找不到就往下試 PATH
            pass
    _cached = (found or shutil.which("allure"), True)
    return _cached[0]


def version(exe: str | None = None) -> str:
    exe = exe or find_allure()
    if not exe:
        return ""
    try:
        return (subprocess.run([exe, "--version"], capture_output=True, text=True,
                               timeout=10).stdout or "").strip()
    except Exception:                           # noqa: BLE001
        return ""


def generate(results_dir: str, out_dir: str, *, timeout: int = 180) -> tuple[bool, str]:
    """`allure generate <results> -o <out> --clean`。回 (成功, 說明)。

    ⚠️ 失敗**不該讓整個 run 收尾失敗** —— 案例已經跑完了，報告產不出來是次要問題。
       呼叫端請把說明寫進 summary，讓人看得到為什麼沒有報告。
    """
    if not os.path.isdir(results_dir) or not os.listdir(results_dir):
        return False, "沒有 allure-results 可以產（案例可能一條都沒跑）"
    exe = find_allure()
    if not exe:
        return False, "找不到 allure CLI —— npm i -g allure-commandline"
    try:
        p = subprocess.run([exe, "generate", results_dir, "-o", out_dir, "--clean"],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "allure generate 逾時（%d 秒）" % timeout
    except Exception as e:                      # noqa: BLE001
        return False, "allure generate 失敗：%s" % str(e)[:160]
    if p.returncode != 0:
        return False, "allure generate 退出碼 %s：%s" % (
            p.returncode, ((p.stderr or p.stdout or "").strip()[-200:]))
    if not os.path.isfile(os.path.join(out_dir, "index.html")):
        return False, "allure generate 回報成功，但沒有產出 index.html"
    return True, "%s（%s）" % (out_dir, version(exe) or "版本不明")
