"""pytest plugin：以 --collect-only 匯出結構化案例清單（供測試助手的案例瀏覽器使用）。

用途：不執行任何測試，把 pytest 收集到的每個 item 匯出成 JSON —— nodeid、檔案:行號、
      中文標題（allure.title > docstring 首行 > 函式名）、markers、allure 五層標籤、
      fixtures（供反推前置依賴，如 wbot_target）、是否需瀏覽器、參數化 id、
      ★ 前置條件／步驟／測試範圍／判准／已知問題（靜態解析 `allure.step`／`allure.attach`，見 `_steps_and_criteria`；
      「測試範圍」是 `allure.attach(name="測試範圍：...")` 依前綴獨立拆出的欄位，見 `_SCOPE_PREFIX`）。
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

⚠️ 步驟／判准是**靜態解析**（AST，不執行案例）——`allure.step`／`allure.attach` 本來是
   執行期才記錄的東西，`--collect-only` 拿不到「這次跑出來的值」，這裡顯示的是
   「案例原始碼寫了什麼」。走訪規則跟 `scripts/lint_cases.py` 同一套（本體 ＋ 往下追一層
   同檔 helper），兩邊不同步會讓 lint 過了但平台看起來還是沒寫，所以規則本身不重複定義：
   有需要調整判準時兩邊一起改。
"""
from __future__ import annotations

import ast
import json
import os
import re

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

# ★ 新綜合（xzh）2026-09-02 起，多彩種／多玩法案例要求先輸出「測試範圍」區塊
#   （完整列出彩種＋玩法，見 `docs/新綜合/新綜合_測試案例撰寫規則.md` Step 5）。
#   案例裡用 `allure.attach(..., name="測試範圍：...")` 宣告，這裡依名稱前綴把它
#   從一般判准 attach 裡挑出來，獨立成 `scope` 欄位，不跟真正的判准佐證混在一起。
_PRECONDITION_PREFIX = "前置條件"
_SCOPE_PREFIX = "測試範圍"
_KNOWN_ISSUE_PREFIX = "已知問題"


# ---------------------------------------------------------------- 步驟／判准（靜態解析）
# 檔案內容 ＋ AST 只解一次；同一檔案裡多個參數化案例共用同一份。
_AST_CACHE: dict[str, tuple[str, dict, dict]] = {}


def _parse_file(path: str) -> tuple[str, dict, dict]:
    """回 (原始碼, {案例函式名: FunctionDef}, {helper 函式名: FunctionDef})；解析失敗回 ('', {}, {})。"""
    if path in _AST_CACHE:
        return _AST_CACHE[path]
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        _AST_CACHE[path] = ("", {}, {})
        return _AST_CACHE[path]
    cases: dict[str, ast.AST] = {}
    helpers: dict[str, ast.AST] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            (cases if n.name.startswith("test_") else helpers).setdefault(n.name, n)
    _AST_CACHE[path] = (src, cases, helpers)
    return _AST_CACHE[path]


def _lit(src: str, node: ast.AST) -> str | None:
    """把一個 AST 節點還原成人看得懂的文字——純字面字串去引號，f-string／運算式原樣附上原始碼。"""
    seg = ast.get_source_segment(src, node)
    if seg is None:
        return None
    s = seg.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return s
    return s


def _is_attr_or_name(func: ast.AST, name: str) -> bool:
    return ((isinstance(func, ast.Attribute) and func.attr == name)
            or (isinstance(func, ast.Name) and func.id == name))


def _step_texts(node: ast.AST, src: str) -> list[str]:
    """`with allure.step("..."):` 的步驟文字，依原始碼出現順序。

    ⚠️ 2026-09-01 修正：`ast.walk()` 是**廣度優先**（BFS），不是原始碼順序——當 `with
    allure.step(...)` 混雜著「函式本體的平行步驟」與「for/if 區塊裡巢狀的步驟」時，
    BFS 會把所有淺層節點（含巢狀迴圈本身）走完才下探迴圈內部，導致迴圈*之後*的平行
    步驟被排到迴圈*內部*步驟前面——跟本函式 docstring 自己承諾的「依原始碼出現順序」
    矛盾。改成先收集 `(lineno, col_offset)` 再排序，才是真的原始碼順序（實例：
    `test_lay_off_detail_all_categories_screen_elements` 的收尾步驟因此曾顯示在
    迴圈內的逐分類步驟前面）。
    """
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.With):
            for item in n.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and _is_attr_or_name(call.func, "step") and call.args:
                    t = _lit(src, call.args[0])
                    if t:
                        out.append((n.lineno, n.col_offset, t))
    out.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in out]


def _attach_titles(node: ast.AST, src: str) -> list[str]:
    """`allure.attach(..., name="...")` 的附件標題——判准佐證貼了什麼。依原始碼出現順序
    （同 `_step_texts()` 的 BFS 排序修正，見其檔頭說明）。"""
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and _is_attr_or_name(n.func, "attach"):
            name_node = next((kw.value for kw in n.keywords if kw.arg == "name"), None)
            if name_node is None and len(n.args) >= 2:
                name_node = n.args[1]
            out.append((n.lineno, n.col_offset, _lit(src, name_node) or "（未命名附件）"))
    out.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in out]


def _helper_names(node: ast.AST) -> list[str]:
    """本體呼叫的單純具名函式（`_verify(...)`，不含 `a.b()`）——依出現順序、去重（同上
    BFS 排序修正）。"""
    calls = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            calls.append((n.lineno, n.col_offset, n.func.id))
    calls.sort(key=lambda x: (x[0], x[1]))
    seen, out = set(), []
    for _, _, name in calls:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _split_sections(titles: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """依附件標題前綴拆成（前置條件、測試範圍、判準、已知問題）。

    舊案例沒有前置條件／已知問題附件時，對應欄位保持空陣列，維持向下相容。
    """
    preconditions = [t for t in titles if t.startswith(_PRECONDITION_PREFIX)]
    scope = [t for t in titles if t.startswith(_SCOPE_PREFIX)]
    known_issues = [t for t in titles if t.startswith(_KNOWN_ISSUE_PREFIX)]
    criteria = [
        t for t in titles
        if not t.startswith((_PRECONDITION_PREFIX, _SCOPE_PREFIX, _KNOWN_ISSUE_PREFIX))
    ]
    return preconditions, scope, criteria, known_issues


def _steps_and_criteria(fn: ast.AST, helpers: dict, src: str) -> tuple[list[str], list[str], list[str], list[str], list[str], bool]:
    """前置條件／步驟／測試範圍／判準／已知問題／有沒有 assert。

    內容來自本體及往下追一層同檔 helper（跟 lint_cases.py 同規則）。
    """
    steps = _step_texts(fn, src)
    preconditions, scope, criteria, known_issues = _split_sections(_attach_titles(fn, src))
    body_seg = ast.get_source_segment(src, fn) or ""
    has_assert = "assert " in body_seg
    for name in _helper_names(fn):
        h = helpers.get(name)
        if h is None:
            continue
        steps += _step_texts(h, src)
        h_preconditions, h_scope, h_criteria, h_known_issues = _split_sections(_attach_titles(h, src))
        preconditions += h_preconditions
        scope += h_scope
        criteria += h_criteria
        known_issues += h_known_issues
        has_assert = has_assert or "assert " in (ast.get_source_segment(src, h) or "")
    return preconditions, steps, scope, criteria, known_issues, has_assert


def _static_steps(item) -> tuple[list[str], list[str], list[str], list[str], list[str], bool]:
    """單筆失敗不可拖垮整份索引——解析失敗一律退回空結果，不往外丟例外。"""
    try:
        path = str(item.path)
        src, cases, helpers = _parse_file(path)
        fn = cases.get(getattr(item, "originalname", None) or item.name)
        if fn is None:
            return [], [], [], [], [], False
        return _steps_and_criteria(fn, helpers, src)
    except Exception:  # noqa: BLE001
        return [], [], [], [], [], False


def _inferred_preconditions(fixtures: list[str], suite: str | None, markers: set[str]) -> list[str]:
    """補上平台可直接閱讀的基本前置條件。

    案例原始碼以 fixture 宣告登入角色；平台不應要求 QA 反查 Python fixture 名稱。
    這裡只對飛單選項明細設置輸出通用前置，其他產品維持既有資料形狀。
    """
    if suite != "飞单选项明细设置":
        return []
    if "level1_agent_page" in fixtures:
        account = "帳號：一級代理"
    elif "company_page" in fixtures:
        account = "帳號：公司帳號"
    elif "platform_page" in fixtures:
        account = "帳號：平台層公司帳號"
    elif "browser" in fixtures:
        account = "帳號：依案例指定的一至九級代理帳號"
    else:
        account = "帳號：依案例指定帳號"
    page = "頁面：系統設置 → 飛單選項明細設置"
    restore = (
        "原值：需要修改設定時，先記錄被測欄位原值，結束後還原並重新讀取確認"
        if "write_action" in markers
        else "原值：唯讀案例不需記錄或修改設定"
    )
    return [account, page, restore]


def _inferred_evidence(
    suite: str | None,
    markers: set[str],
    steps: list[str],
    criteria: list[str],
) -> list[str]:
    """提供一般 QA 看得懂的佐證方式提示；實際附件仍由案例執行時產生。"""
    if suite != "飞单选项明细设置":
        return []
    evidence = [
        "截圖：保留關鍵欄位、按鈕、勾選狀態或提示文字",
        "頁面值：記錄操作前後畫面顯示的實際數值或狀態",
    ]
    joined = " ".join(steps + criteria)
    if "write_action" in markers or any(k in joined for k in ("API", "PUT", "GET", "網路")):
        evidence.append("自動化紀錄：需要時附上 API GET／PUT 或網路請求紀錄")
    return evidence


def _explicit_evidence_titles(criteria: list[str]) -> list[str]:
    """把「實際結果／登入失敗佐證」附件從預期結果移到佐證方式。"""
    prefixes = ("實際結果", "登入失敗佐證", "佐證方式", "截圖")
    return [t for t in criteria if t.startswith(prefixes)]


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
    preconditions, steps, scope, criteria, known_issues, has_assert = _static_steps(item)
    markers = sorted({m.name for m in item.iter_markers()} - _INTERNAL_MARKS)
    inferred = _inferred_preconditions(
        fixtures,
        (labels.get("suite") or [None])[0],
        set(markers),
    )
    # 顯式附件可覆蓋／補充通用前置；目前舊案例多未寫附件，因此先以 fixture 推導。
    preconditions = inferred + [p for p in preconditions if p not in inferred]
    evidence = _inferred_evidence(
        (labels.get("suite") or [None])[0], set(markers), steps, criteria
    )
    explicit_evidence = _explicit_evidence_titles(criteria)
    expected = [t for t in criteria if t not in explicit_evidence]
    evidence += [t for t in explicit_evidence if t not in evidence]
    # 明確宣告的 QA 文件優先；執行附件仍保留為佐證，未宣告者維持既有解析。
    documented = _documented_case(getattr(getattr(item, "obj", None), "__doc__", None))
    if documented:
        preconditions = documented["前置條件"]
        scope = documented["測試範圍"]
        steps = documented["步驟"]
        expected = documented["預期結果"]
        criteria = expected
        known_issues = documented.get("已知問題", [])

    return {
        "nodeid": item.nodeid,  # 中文原樣（JSON 以 ensure_ascii=False 寫出）
        "file": path,
        "lineno": (item.location[1] or 0) + 1,
        "func": getattr(item, "originalname", None) or item.name,
        "param_id": cs.id if cs else None,
        "title": title,
        "title_source": title_src,
        "markers": markers,
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
        # ★ 靜態解析（見檔頭說明）：案例原始碼寫了什麼步驟／貼了什麼判准佐證，不是執行結果
        # ★ scope＝「測試範圍」attach（見上方 _SCOPE_PREFIX 說明），目前僅新綜合(xzh)案例使用，
        #   其餘產品案例沒有這個 attach 就是空陣列，不影響原本 steps/criteria 的顯示。
        "scope": scope,
        "preconditions": preconditions,
        "steps": steps,
        "criteria": criteria,
        "expected": expected,
        "evidence": evidence,
        "known_issues": known_issues,
        "has_assert": has_assert,
    }


def _documented_case(doc: str | None) -> dict[str, list[str]] | None:
    """只接受 opt-in 的完整平台案例文件，避免改變既有自由格式 docstring。"""
    if not doc or not doc.strip().startswith("平台案例："):
        return None
    result: dict[str, list[str]] = {}
    section = None
    for raw in doc.splitlines()[1:]:
        line = raw.strip()
        if line == "實作備註：":
            break
        if line in {s + "：" for s in ("前置條件", "測試範圍", "步驟", "預期結果", "已知問題")}:
            section = line[:-1]
            result[section] = []
        elif line and section:
            result[section].append(re.sub(r"^(?:[-*] |\d+\. )", "", line))
    if not all(result.get(k) for k in ("前置條件", "測試範圍", "步驟", "預期結果")):
        raise ValueError("平台案例文件缺少前置條件、測試範圍、步驟或預期結果")
    if not 2 <= len(result["步驟"]) <= 4:
        raise ValueError("平台案例步驟需為 2～4 步")
    return result


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
