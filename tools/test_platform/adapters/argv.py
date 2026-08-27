"""argv 組裝器：把 registry 宣告的欄位 emit 規則，翻成真正要執行的命令列／環境變數。

用途：registry 的 `emit`（11 種）先前只被 `core/registry.py` 驗證合法性，**沒有任何消費者**。
      本檔是唯一的消費點，供三處共用：
        · `adapters/cli.py` —— 真的組出 argv 交給 subprocess
        · `POST /api/runs/preview` —— 確認框的命令列預覽（取代原本丟 JSON.stringify 的做法）
        · run 詳情頁的參數卡
使用方式：
    from adapters.argv import build_invocation
    inv = build_invocation(spec, command, clean_params)
    inv["argv"]      # ['C:/.../python.exe', 'parse.py', '--input-folder', 'All']
    inv["env"]       # {'PYTHONUTF8': '1', 'CRUX_QA_ENV': 'qat'}
    inv["human"]     # [{'label': '輸入資料夾', 'value': 'All'}, ...] 中文人話清單
    inv["redacted"]  # 同上但 secret／never_persist 已換成 ***，可直接顯示給人看
前置條件：
    · 傳進來的 params 必須是 `ToolAdapter.validate()` 的產物（已做型別轉換、已丟棄不該出現的欄位）。
    · secret 欄位一律 emit=env（`core/registry.py` 已強制），所以**永遠不會**進 argv。
    · `argsfile` 需要 run_dir 才寫得出檔；預覽時不給 run_dir，會回一個 <暫存檔> 佔位字串。
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys

from core.paths import REPO_ROOT, VENV_PYTHON, rel_to_repo

MASK = "***"


def resolve_exe(spec) -> str:
    """執行檔：registry 可指定，否則優先用工作區 .venv 的 python（與 scripts/ 慣例一致）。

    `executable` 的三種寫法：

    | 寫法 | 例 | 解析方式 |
    | --- | --- | --- |
    | 絕對路徑 | `C:\\Python312\\python.exe` | 原樣 |
    | repo 相對路徑 | `.venv/Scripts/python.exe` | 接在 REPO_ROOT 之後 |
    | **裸名** | `python` | **走 PATH**（`shutil.which`） |

    ⚠️ 裸名這一條是必要的：**CRUX 與七星壓測必須用系統 Python** ——
    工作區的 `.venv` 沒有 `locust`／`gevent`（兩支工具自己的 `run_server.bat`
    早就寫明「該 venv 沒有 locust/flask/gevent」）。而系統 Python 的絕對路徑
    因機器而異，寫死就不可攜，範本給同事就會壞。
    （2026-08-23 實測：平台組出的 argv 用 `.venv`，跑下去是 `ModuleNotFoundError:
      No module named 'locust'` —— 三支 tool.json 的 hint 當時還寫著「統一 .venv，已含 locust」。）
    """
    ex = (spec.runtime or {}).get("executable")
    if ex:
        if os.path.isabs(ex):
            return ex
        if os.sep in ex or "/" in ex:
            return os.path.join(REPO_ROOT, ex)
        return shutil.which(ex) or ex          # 裸名 → PATH；找不到就原樣交給 subprocess 報錯
    return VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def resolve_cwd(spec) -> str:
    cwd = (spec.runtime or {}).get("cwd") or "."
    return os.path.normpath(os.path.join(REPO_ROOT, cwd))


def _default_emit(f: dict) -> str:
    """未宣告 emit 時的推定：布林旗標 → flag_when_true；有 arg → opt；其餘不進命令列。"""
    if f.get("emit"):
        return f["emit"]
    if not f.get("arg"):
        return "none"
    return "flag_when_true" if f.get("type") == "boolean" else "opt"


def _as_list(v) -> list:
    if isinstance(v, (list, tuple, set)):
        return list(v)
    return [x for x in str(v).replace("，", " ").replace(",", " ").split() if x]


def _human_value(f: dict, v) -> str:
    """人話值：select 顯示選項的中文 label，布林顯示是／否，清單顯示「共 N 項」。"""
    t = f.get("type")
    if t == "boolean":
        return "是" if v else "否"
    if t in ("select", "file_select"):
        for o in f.get("options") or []:
            if str(o.get("value")) == str(v):
                return o.get("label") or str(v)
        return str(v)
    if t == "multiselect":
        labels = {str(o.get("value")): o.get("label") for o in (f.get("options") or [])}
        return "、".join(labels.get(str(x), str(x)) for x in _as_list(v))
    if t == "case_picker":
        return f"已勾選 {len(_as_list(v))} 條"
    if t == "number":
        return f"{v}{f.get('unit') or ''}"
    s = str(v)
    return (s[:60] + "…") if len(s) > 60 else s


def build_invocation(spec, command: dict, params: dict, *, run_dir: str | None = None) -> dict:
    """組出可執行的 argv／env，並同時產出「人話清單」與「遮罩版」。

    回傳 {exe, argv, env, cwd, human, redacted, argsfiles, notes}
    """
    fields = (command.get("params") or {}).get("fields", [])
    by_key = {f["key"]: f for f in fields}

    opts: list[str] = []
    positional: list[str] = []
    env: dict[str, str] = dict((spec.runtime or {}).get("env") or {})
    human: list[dict] = []
    argsfiles: list[dict] = []
    secret_keys = {f["key"] for f in fields if f.get("type") == "secret" or f.get("never_persist")}
    masked_env: set[str] = set()
    notes: list[str] = []

    for f in fields:
        k = f["key"]
        if k.startswith("_") or k not in params:
            continue
        v = params[k]
        if v in (None, "", []):
            continue
        emit = _default_emit(f)
        arg = f.get("arg")

        if emit == "none":
            human.append({"key": k, "label": f.get("label", k),
                          "value": MASK if k in secret_keys else _human_value(f, v), "emitted": False})
            continue
        if emit == "env":
            name = f.get("env") or k.upper()
            env[name] = str(v)
            if k in secret_keys:
                masked_env.add(name)
        elif emit == "flag_when_true":
            if v:
                opts.append(arg)
        elif emit == "flag_when_false":
            if not v:
                opts.append(arg)
        elif emit == "opt":
            opts.extend([arg, str(v)])
        elif emit == "opt_eq":
            opts.append(f"{arg}={v}")
        elif emit == "repeat":
            for item in _as_list(v):
                opts.extend([arg, str(item)])
        elif emit == "join":
            opts.extend([arg, (f.get("sep") or ",").join(str(x) for x in _as_list(v))])
        elif emit == "json":
            opts.extend([arg, json.dumps(v, ensure_ascii=False)])
        elif emit == "positional":
            positional.append(str(v))
        elif emit == "argsfile":
            lines = [str(x) for x in _as_list(v)]
            if run_dir:
                path = os.path.join(run_dir, f"args_{k}.txt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines))
            else:
                # 預覽時不寫檔，給個看得懂的佔位（人要看的是「有這麼一份清單」而不是路徑）
                path = f"<{f.get('label', k)}清單.txt：{len(lines)} 行>"
            argsfiles.append({"key": k, "path": path, "lines": lines})
            opts.extend([arg, path] if arg else [f"@{path}"])
        else:
            notes.append(f"欄位 {k} 的 emit「{emit}」尚無組裝規則，已略過")
            continue
        # ⛔ **`human` 也要遮罩** —— 它是確認卡與參數卡直接顯示的東西（`preview()` 原樣回傳）。
        #    先前只遮 `redacted`，因為當時沒有任何 run 命令宣告 secret 欄位；
        #    2026-08-24 加上 `crux_perf.api_load` 的登入密碼之後，確認框就會把明碼印出來。
        human.append({"key": k, "label": f.get("label", k),
                      "value": MASK if k in secret_keys else _human_value(f, v), "emitted": True})

    exe = resolve_exe(spec)
    base = list(command.get("argv") or [])
    argv = [exe] + base + opts + positional

    def _mask_argv(a: list[str]) -> list[str]:
        # secret 一律 emit=env（registry 強制），argv 理論上不含機密；仍保留這層以防 schema 日後放寬
        out, skip = [], False
        for i, tok in enumerate(a):
            if skip:
                out.append(MASK); skip = False; continue
            fk = next((kk for kk in secret_keys if by_key.get(kk, {}).get("arg") == tok), None)
            out.append(tok)
            if fk:
                skip = True
        return out

    red_argv = _mask_argv(argv)
    red_env = {k: (MASK if k in masked_env else v) for k, v in env.items()}
    return {
        "exe": exe,
        "argv": argv,
        "env": env,
        "cwd": resolve_cwd(spec),
        "human": human,
        "argsfiles": argsfiles,
        "notes": notes,
        "redacted": {
            "argv": red_argv,
            "env": red_env,
            "cmdline": " ".join(shlex.quote(t) for t in red_argv),
            "cwd": rel_to_repo(resolve_cwd(spec)),
        },
    }


def preview(spec, command: dict, params: dict) -> dict:
    """給確認框／參數卡用：只回人看的部分，不落任何檔案。"""
    inv = build_invocation(spec, command, params)
    r = inv["redacted"]
    return {
        "human": inv["human"],
        "cmdline": r["cmdline"],
        "argv": r["argv"],
        "env": {k: v for k, v in r["env"].items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")},
        "cwd": r["cwd"],
        "notes": inv["notes"],
    }
