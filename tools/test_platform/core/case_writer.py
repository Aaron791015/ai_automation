"""draft → 真的測試檔，並用 pytest --collect-only 驗證它收得到。

用途：動線 D 的第 ④ 格。這一格**不因生成器而異**（規則式或 Claude 都走這裡）。
使用方式：
    from core import case_writer
    prev = case_writer.preview(draft)              # 只組字串，不寫檔
    res  = case_writer.commit(draft)               # 寫檔 → --collect-only 驗證 → 收不到就還原
前置條件：
    · 落點見 `tests_out_dir()` —— **Demo 寫沙箱、live 寫 `tests/<產品>/`**。
      ⛔ Demo 一律不寫 `tests/`（那是原型的版控目錄，別的 session 正在用）；
      live 則相反：那就是這位使用者自己的工作區，不寫進去等於這條動線沒有產出。
    · `registry/ui_tests.tool.json` 的 `cases.roots` 在 demo 模式會含這個沙箱目錄，
      所以生成的案例**真的會出現在案例瀏覽器、真的能勾選執行**。
    · 驗證是真的跑 `pytest --collect-only -q <檔>`：語法錯、import 錯、fixture 名打錯都會當場現形。
      收不到就把檔案還原（新檔則刪掉），不留一個會讓整包索引壞掉的檔。
"""
from __future__ import annotations

import os
import re
import subprocess

from core.paths import CACHE_DIR, REPO_ROOT, python_exe, rel_to_repo
from core.registry import get_registry

_SLUG = re.compile(r"[^\w一-鿿]+")


def slug(text: str) -> str:
    return _SLUG.sub("_", text or "").strip("_")[:40] or "generated"


def tests_out_dir(product: str) -> str:
    """案例寫到哪 ＝ 產品的 `tests/<產品>/`（由 `config/products.json` 的
    `tests_prefix` 決定）。

    ⛔ 先前恆指向 `demo/generated_tests/` —— 而 `collect_roots()` 只在 demo 模式
       才把沙箱加進掃描範圍，於是寫出去的案例**索引掃不到、跑不了**，
       也不在 `tests/` 不會被版控。這是移除 Demo 模式的直接理由之一。
    """
    # ⭐ **三種寫法都認**（slug `crux`／權威 id `CRUX`／label）——
    #    比照 `doc_draft._product()`。⛔ 只認 slug 的話 `tests_out_dir("CRUX")` 會炸，
    #    而同一個 draft 裡兩種寫法是並存的：頂層 `product` 是 slug，
    #    每條 case 的 `product` 被 `_norm_product` 正規化成權威 id
    #    （2026-08-26 code review 抓到，當時沒炸只是因為 `preview()` 剛好讀頂層那個）。
    for p in get_registry().products:
        if p.get("virtual"):
            continue
        if product in (p.get("id"), p.get("product_id"), p.get("label")):
            pref = ((p.get("knowledge") or {}).get("tests_prefix")
                    or ("tests/%s/" % p.get("id") or product))
            return os.path.join(REPO_ROOT, *pref.strip("/").split("/"))
    raise ValueError("產品 %s 沒有登記 —— 確認 config/products.json" % product)


def target_path(draft: dict) -> str:
    product = draft.get("product") or "crux"
    return os.path.join(tests_out_dir(product), f"test_{slug(draft.get('title'))}.py")


def _cases_fingerprint(draft: dict) -> str:
    """案例清單的指紋 —— 只要有一條被改過，快取就失效。"""
    import hashlib
    import json as _json
    payload = _json.dumps(draft.get("cases") or [], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _safe_generator(name):
    """查不到就退回預設 —— 產碼不該被「案例是誰提的」擋住。

    ⚠️ `generators` 是**延遲匯入**的（避免 core 與 generators 互相 import），
       所以這裡也要在函式內 import。
    """
    from generators import get_generator
    try:
        return get_generator(name)
    except ValueError:
        return get_generator(None)


def preview(draft: dict, generator=None, *, use_cache: bool = True) -> dict:
    """組出整份檔案內容，不寫檔。回 {path, text, cases, warnings}。

    ⚠️ **產碼結果要快取。** 規則式是毫秒級，但 Claude 供應者是「一條案例一次 API
       呼叫」—— 實測 12 條要 422 秒。而 `commit()` 又會再跑一次 `preview()`，
       等於同一份碼產兩次、等快 15 分鐘（2026-08-23 範本實跑）。
       快取的鍵是案例清單的指紋，人一改案例就自動失效。
    """
    from generators import get_generator
    # ⚠️ `generated_by` 記的是「**案例是誰提的**」（可能是 task-session），
    #    不是「用哪支產碼」—— 拿它去查生成器會炸（2026-08-23 實跑 500）。
    gen = generator or _safe_generator(draft.get("generated_by"))
    cases = draft.get("cases") or []
    fp = _cases_fingerprint(draft)
    cached = draft.get("_preview_cache") or {}
    if use_cache and cached.get("fingerprint") == fp and cached.get("generator") == gen.name:
        out = dict(cached["result"])
        out["abs"] = target_path(draft)
        out["exists"] = os.path.exists(out["abs"])
        out["cached"] = True
        return out
    bodies, imports = [], []
    seen_names: set[str] = set()
    warnings = []
    by_session = 0                 # 幾條是 session 自己寫的碼（其餘是產碼器的骨架）
    for c in cases:
        # ⭐ session 自己交的程式碼優先 —— 它剛在站台上把 selector 與期望值量出來，
        #   產碼器只能再猜一次（使用者 2026-08-24 裁示：由 session 生成）。
        #   ⚠️ 沒有 `def test_` 就不是一段能用的案例碼，退回產碼器而不是寫進去。
        code = c.get("code") if _func_of(c.get("code") or "") else None
        if code:
            by_session += 1
        else:
            code = gen.write_code(c, {"product": draft.get("product")})
        name = _func_of(code)
        if name in seen_names:
            warnings.append(f"函式名重複：{name} —— 後一條會覆蓋前一條，請改標題")
        seen_names.add(name)
        if c.get("code") and not _func_of(c.get("code") or ""):
            warnings.append(f"{c.get('id')}「{(c.get('title') or '')[:24]}」交了 code 但裡面沒有 "
                            "`def test_…` —— 已退回產碼器的骨架，請確認草稿的縮排（內容要縮 ≥6）")
        if c.get("confidence") == "low" and not c.get("code"):
            # ⭐ 分辨兩種「信心低」—— 人要做的事完全不同：
            #    沒實跑過 → 自己去站台走一遍；找不到 POM → 補 page object。
            why = ("沒有在站台上實際跑過（verified=%s）" % c.get("verified")
                   if c.get("verified") in ("no", "partial")
                   else "找不到夠近的既有案例或 POM 方法")
            warnings.append(f"{c.get('id')}「{(c.get('title') or '')[:24]}」信心低：{why}")
        # 生成器是「一條案例一段碼」，import 自然散在每段開頭；這裡把它們提到檔頭去重排序。
        # 散在中間雖然 Python 收得到（--collect-only 也會過），但沒有人手寫的測試檔長那樣。
        body, imps = _hoist_imports(code)
        imports.extend(imps)
        bodies.append(body)
    uniq = sorted(set(imports))
    text = "\n".join([gen.module_header(draft), *uniq, *bodies]).rstrip() + "\n"
    path = target_path(draft)
    if by_session and by_session < len(cases):
        # ⛔ 混在同一個檔裡最危險：看起來整份都是人寫的，其實有幾條是骨架。
        warnings.append("這批有 %d/%d 條是 session 自己寫的碼，其餘 %d 條是產碼器的骨架"
                        "（`pytest.skip` 或 `assert … is not None`）—— 別把整檔當成可信的回歸"
                        % (by_session, len(cases), len(cases) - by_session))
    out = {"path": rel_to_repo(path), "abs": path, "text": text,
           "case_count": len(cases), "warnings": warnings, "by_session": by_session,
           "exists": os.path.exists(path), "disclaimer": getattr(gen, "disclaimer", ""),
           "cached": False}
    # 存回 draft（呼叫端負責 save）—— `abs` 不進快取，它是本機路徑
    draft["_preview_cache"] = {
        "fingerprint": fp, "generator": gen.name,
        "result": {k: v for k, v in out.items() if k not in ("abs", "exists", "cached")}}
    return out


def commit(draft: dict, generator=None, *, text: str | None = None) -> dict:
    """寫檔 → 驗證 → 失敗就還原。回 {ok, path, collected, error, restored}。

    `text` 給了就**直接用它當檔案內容**，不走產碼器（2026-08-24 新增）。

    ★ 為什麼要這條路：使用者裁示「使用者確認沒問題，則**由 session 依照清單項目
      去生成自動化測試案例**」—— 也就是程式碼由 session 寫，不是規則式產碼器拼。
      但**安全網要一模一樣**：寫檔 → 真的跑 `--collect-only` → 收不到就還原。
      那一段與「誰寫的程式碼」無關，是這個平台不該讓步的底線
      （一個語法壞掉的檔會讓**整包**案例索引 collect 失敗，連帶讓別人的
      案例瀏覽器空掉）。
    """
    if text is not None:
        pv = {"abs": target_path(draft), "path": rel_to_repo(target_path(draft)),
              "text": text, "warnings": [], "cases": draft.get("cases") or []}
    else:
        pv = preview(draft, generator)
    path = pv["abs"]
    before = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            before = f.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(pv["text"])

    res = collect_check(path)
    if not res["ok"]:
        # ⚠️ 收不到就還原：一個語法壞掉的檔會讓**整包**案例索引 collect 失敗，
        #    連帶讓別人的案例瀏覽器空掉 —— 代價遠大於「這次沒生成成功」。
        if before is None:
            os.remove(path)
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(before)
        return {"ok": False, "path": pv["path"], "restored": True,
                "error": res["error"], "output": res["output"], "warnings": pv["warnings"]}
    return {"ok": True, "path": pv["path"], "restored": False, "collected": res["collected"],
            "nodeids": res["nodeids"], "warnings": pv["warnings"], "text": pv["text"]}


def collect_check(path: str) -> dict:
    """真的跑 pytest --collect-only —— 語法、import、fixture 名都在這一關現形。"""
    py = python_exe()
    # ⚠️ pyproject 的 addopts 帶了 --alluredir，關掉 allure 外掛會讓那個旗標變成無法辨識的參數。
    #    所以不關外掛，改把結果導到一個丟棄用的目錄（與 collect/case_index.py 同一手法）。
    throwaway = os.path.join(CACHE_DIR, "collect_alluredir")
    os.makedirs(throwaway, exist_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "TEST_PLATFORM_COLLECT": "1"}
    try:
        r = subprocess.run([py, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                            f"--alluredir={throwaway}", path],
                           cwd=REPO_ROOT, capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:
        return {"ok": False, "error": f"無法執行 pytest：{e}", "output": "", "collected": 0, "nodeids": []}
    out = (r.stdout or "") + (r.stderr or "")
    nodeids = [ln.strip() for ln in (r.stdout or "").splitlines()
               if "::" in ln and not ln.startswith(("=", "E ", "ERROR", "<"))]
    if r.returncode != 0 or not nodeids:
        first_err = next((ln for ln in out.splitlines() if ln.startswith(("E ", "ERROR"))), "")
        return {"ok": False, "error": first_err or f"pytest --collect-only 退出碼 {r.returncode}",
                "output": out[-4000:], "collected": 0, "nodeids": nodeids}
    return {"ok": True, "error": "", "output": out[-2000:], "collected": len(nodeids), "nodeids": nodeids}


def _hoist_imports(code: str) -> tuple[str, list[str]]:
    """把一段案例碼裡的 import 行抽出來，回 (去掉 import 的碼, import 行清單)。"""
    keep, imps = [], []
    for ln in code.splitlines():
        (imps if ln.startswith(("import ", "from ")) else keep).append(ln)
    return "\n".join(keep).strip("\n") and "\n\n" + "\n".join(keep).strip("\n"), imps


def _func_of(code: str) -> str:
    m = re.search(r"^def (\w+)\(", code, re.M)
    return m.group(1) if m else ""
