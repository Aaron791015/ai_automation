"""路徑常數：REPO_ROOT／BASE_DIR 由 __file__ 推得，不依賴 cwd。

用途：平台內所有模組取路徑的唯一來源（沿用 tools/crux_qa/config_loader.py 的慣例）。
使用方式：from core.paths import REPO_ROOT, BASE_DIR, LOGS_DIR, CACHE_DIR
前置條件：本檔位於 tools/test_platform/core/。
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # tools/test_platform
REPO_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))                    # c:/GitLab/Automation

CONFIG_DIR = os.path.join(BASE_DIR, "config")
REGISTRY_DIR = os.path.join(BASE_DIR, "registry")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
RUNS_DIR = os.path.join(LOGS_DIR, "runs")
SESSIONS_DIR = os.path.join(LOGS_DIR, "sessions")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

DRAFTS_DIR = os.path.join(LOGS_DIR, "drafts")               # 案例 draft 的持久化
STATIC_DIR = os.path.join(BASE_DIR, "web_ui", "static")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
VENV_PYTHON = os.path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")


def python_exe() -> str:
    """要開子程序跑 Python 時用這支，⛔ 不要直接用 `VENV_PYTHON`。

    優先工作區 `.venv`，沒有就退回**目前跑平台的這支**直譯器。

    ⚠️ 為什麼要有這層：`.venv` 不存在時直接餵 `VENV_PYTHON` 會丟
    `[WinError 2] 系統找不到指定的檔案` —— 訊息裡**連是哪個檔案都沒有**。
    同事拿到範本、還沒跑 `setup_test_env.ps1` 就開平台時撞到的就是這個，
    而畫面上只會看到「案例 0 條」（2026-08-25 範本端到端驗收實際踩到）。
    `adapters/argv.py` 早就是這個寫法，`collect/case_index.py` 與
    `core/knowledge_index.py` 漏了 —— 而那兩支正好是儀表板的兩個主要數字。
    """
    return VENV_PYTHON if os.path.isfile(VENV_PYTHON) else (sys.executable or "python")


def repo_path(*parts: str) -> str:
    """回傳相對 repo root 的絕對路徑。"""
    return os.path.join(REPO_ROOT, *parts)


def rel_to_repo(path: str) -> str:
    """絕對路徑轉相對 repo root 的正斜線路徑（給前端／JSON 用）。"""
    try:
        return os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")
