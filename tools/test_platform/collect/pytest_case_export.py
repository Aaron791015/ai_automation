"""pytest plugin：以 --collect-only 匯出結構化案例清單（供測試助手的案例瀏覽器使用）。

用途：不執行任何測試，把 pytest 收集到的每個 item 匯出成 JSON —— nodeid、檔案:行號、
      中文標題（allure.title > docstring 首行 > 函式名）、markers、allure 五層標籤、
      fixtures（供反推前置依賴，如 wbot_target）、是否需瀏覽器、參數化 id。
使用方式（由平台 collect/case_index.py 以 subprocess 呼叫，帶 90s timeout）：
    .venv\\Scripts\\python.exe -m pytest --collect-only -q -p no:cacheprovider \\
        -p tools.test_platform.collect.pytest_case_export \\
        --case-export=<輸出 json> --alluredir=<拋棄式目錄>
前置條件：
    · 本檔不進 pyproject 的 addopts，避免污染一般測試執行。
    · ★ 自己把 JSON 寫檔（ensure_ascii=False），平台不解析 stdout —— 繞開 Windows cp950 console。
    · ★ 命令列必須再給一次 --alluredir 指向拋棄式目錄，覆蓋 pyproject 無條件帶的
      reports/allure-results（argparse 後者覆蓋前者）。不要用 -p no:allure_pytest，
      那會讓 allure.title 相關 marker 註冊失敗而噴 warning。
"""
from __future__ import annotations

import json
import os

# allure 的取值邏輯直接沿用官方 util，避免自己重寫版本相容問題：
#   · allure.title  → item.obj.__allure_display_name__（★ 屬性，不是 marker）
#   · feature/story/suite/parentSuite/subSuite → allure_label marker 的 label_type kwarg
try:
    from allure_pytest.utils import allure_description, allure_labels, allure_title
except ImportError:  # 沒裝 allure 也要能列舉
    def allure_title(item):  # type: ignore[misc]
        return None

    def allure_labels(item):  # type: ignore[misc]
        return []

    def allure_description(item):  # type: ignore[misc]
        return getattr(getattr(item, "function", None), "__doc__", None)


_INTERNAL_MARKS = {"allure_label", "allure_description", "allure_description_html",
                   "allure_link", "parametrize", "usefixtures", "filterwarnings"}


def pytest_addoption(parser):
    parser.addoption("--case-export", action="store", default=None,
                     help="測試助手：案例清單匯出路徑（JSON）")


def _title(item) -> tuple[str, str]:
    """回 (顯示標題, 來源)。優先序：allure.title > docstring 首行 > 函式名。"""
    try:
        t = allure_title(item)
    except Exception:  # noqa: BLE001
        t = None
    if t:
        # allure.title 支援 {param} 佔位；參數化案例盡量就地代入，代不進去就原樣
        cs = getattr(item, "callspec", None)
        if cs:
            try:
                t = t.format(**cs.params)
            except (KeyError, IndexError, AttributeError, ValueError):
                pass
        return str(t), "allure_title"
    doc = ""
    try:
        doc = allure_description(item) or ""
    except Exception:  # noqa: BLE001
        doc = getattr(getattr(item, "function", None), "__doc__", None) or ""
    first = next((ln.strip() for ln in str(doc).splitlines() if ln.strip()), "")
    if first:
        return first, "docstring"
    return item.name, "function_name"


def _collect_one(item, rootdir: str) -> dict:
    labels: dict[str, list[str]] = {}
    try:
        for name, value in allure_labels(item):
            labels.setdefault(str(name), []).append(str(value))
    except Exception:  # noqa: BLE001
        pass

    cs = getattr(item, "callspec", None)
    path = os.path.relpath(str(item.path), rootdir).replace("\\", "/")
    title, title_src = _title(item)
    fixtures = [f for f in getattr(item, "fixturenames", []) if not f.startswith("_")]

    return {
        "nodeid": item.nodeid,  # 中文原樣（JSON 以 ensure_ascii=False 寫出）
        "file": path,
        "lineno": (item.location[1] or 0) + 1,
        "func": getattr(item, "originalname", None) or item.name,
        "param_id": cs.id if cs else None,
        "title": title,
        "title_source": title_src,
        "markers": sorted({m.name for m in item.iter_markers()} - _INTERNAL_MARKS),
        "allure": {
            "feature": labels.get("feature", []),
            "story": labels.get("story", []),
            "parent_suite": (labels.get("parentSuite") or [None])[0],
            "suite": (labels.get("suite") or [None])[0],
            "sub_suite": (labels.get("subSuite") or [None])[0],
            "severity": (labels.get("severity") or [None])[0],
        },
        # ★ 前置依賴用 fixture 反推，比檔名規則可靠：
        #   tests/wbot/conftest.py 的 wbot_target 缺 master 就 skip → 必須先跑階段0
        "fixtures": fixtures,
        "needs_browser": "page" in fixtures or "context" in fixtures or "browser" in fixtures,
    }


def pytest_collection_finish(session):
    out = session.config.getoption("case_export")
    if not out:
        return
    rootdir = str(session.config.rootpath)
    cases = []
    for item in session.items:
        try:
            cases.append(_collect_one(item, rootdir))
        except Exception as e:  # noqa: BLE001 單筆失敗不可拖垮整份索引
            cases.append({"nodeid": getattr(item, "nodeid", "?"), "error": str(e)})
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = f"{out}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:  # ★ 自己寫檔，不經 stdout（避開 cp950）
        json.dump({"rootdir": rootdir.replace("\\", "/"), "count": len(cases), "cases": cases},
                  f, ensure_ascii=False, indent=1)
    os.replace(tmp, out)
