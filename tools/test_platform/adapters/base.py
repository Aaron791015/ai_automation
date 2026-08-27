"""工具介接的唯一契約：ToolAdapter。

用途：cli／pytest／http 三種 adapter 皆實作本介面；web_ui 只認得本介面，
      不認得任何工具細節。這是「假在 adapter，不在前端」與「同事接工具不改平台程式」的基礎。
使用方式：
    from adapters import get_adapter
    ad = get_adapter(spec, ctx)
    ad.validate(params) → 乾淨 params（失敗 raise ValueError）
    ad.start(StartRequest) → RunHandle；ad.status/logs/reports/stop(run_id)
    ad.run_command(command_id, params) → dict（mode=sync／python_call）
前置條件：validate 是後端權威（前端只做即時提示）。
"""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_DURATION = re.compile(r"^(\d+h)?(\d+m)?(\d+s)?$")


@dataclass
class StartRequest:
    tool_id: str
    command_id: str
    params: dict
    run_id: str
    platform_run_dir: str
    profile_id: str | None = None
    remark: str = ""
    selection: list[str] = field(default_factory=list)   # pytest：nodeid 清單


@dataclass
class RunHandle:
    run_id: str
    pid: int | None = None
    external: bool = False


@dataclass
class ArtifactRef:
    key: str
    label: str
    href: str
    kind: str = "html"           # html|json|csv|text
    exists: bool = True
    open: str = "newtab"         # newtab|iframe|download
    primary: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class ToolAdapter(ABC):
    kind: str = ""

    def __init__(self, spec, ctx: dict | None = None):
        self.spec = spec
        self.ctx = ctx or {}

    # ---- 準備 ----
    def validate(self, command: dict, params: dict) -> dict:
        """依欄位描述子做型別／範圍／必填／pattern 檢核，回正規化後的 params。子類可覆寫再加工具專屬檢核。"""
        fields = (command.get("params") or {}).get("fields", [])
        clean: dict[str, Any] = {}
        errors: list[str] = []
        for f in fields:
            k = f["key"]
            v = params.get(k, f.get("default"))
            if not _cond(f.get("visible_when"), params) or not _cond(f.get("available_when"), params):
                continue
            req = f.get("required") or _cond_req(f.get("required_when"), params)
            if v in (None, "", []):
                if req:
                    errors.append(f"「{f['label']}」為必填")
                continue
            t = f["type"]
            try:
                if t == "number":
                    v = float(v)
                    if v.is_integer() and not f.get("step") or (f.get("step") and float(f["step"]).is_integer()):
                        v = int(v)
                    if f.get("min") is not None and v < f["min"]:
                        errors.append(f"「{f['label']}」不可小於 {f['min']}")
                    if f.get("max") is not None and v > f["max"]:
                        errors.append(f"「{f['label']}」不可大於 {f['max']}")
                elif t == "boolean":
                    v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "on", "yes")
                elif t == "duration":
                    if not _DURATION.match(str(v)) or str(v) in ("",):
                        errors.append(f"「{f['label']}」格式應為 30m／2h／1h30m")
                elif t in ("select", "file_select"):
                    opts = [o["value"] for o in f.get("options", [])]
                    if opts and str(v) not in opts and not f.get("options_from"):
                        errors.append(f"「{f['label']}」的值不在選項內")
                    v = str(v)
                elif t == "multiselect":
                    v = list(v) if isinstance(v, (list, tuple)) else [x for x in str(v).split(",") if x]
                elif t == "number_list":
                    v = [int(x) for x in (v if isinstance(v, list) else str(v).replace("，", ",").replace(" ", ",").split(","))
                         if str(x).strip() != ""]
                elif t == "case_picker":
                    v = list(v) if isinstance(v, (list, tuple)) else [x for x in str(v).splitlines() if x.strip()]
                    if not v and req:
                        errors.append("請至少勾選一條案例")
                elif t in ("text", "textarea", "secret", "path_picker"):
                    v = str(v)
                    if f.get("pattern") and not re.match(f["pattern"], v):
                        errors.append(f"「{f['label']}」格式不符")
            except (TypeError, ValueError):
                errors.append(f"「{f['label']}」的值無法解析：{v!r}")
                continue
            clean[k] = v
        if errors:
            raise ValueError("；".join(errors))
        return clean

    def options(self, field_key: str, params: dict) -> list[dict]:
        return []

    def health(self) -> dict:
        """依 `runtime.requires` 宣告做健康檢查 —— **所有 adapter 共用**。

        ⚠️ 這段原本只長在 `CliAdapter` 上，基底是 `return {"ok": True, "checks": []}`
        —— 於是 pytest 型工具（`ui_tests`）的健康檢查頁**永遠是綠的、一項都不檢查**。
        同事 fresh clone 少裝 playwright 時看到的也是綠燈，等按下去跑才失敗。
        （2026-08-23 由「adapter 必須自己實作契約的每個方法」這條測試抓出來。）

        檢查項全部由宣告驅動，本方法不認得任何工具：
        `requires.python_modules[]`、`requires.external[]`、直譯器、工作目錄。
        """
        import shutil
        import subprocess
        from adapters.argv import resolve_cwd, resolve_exe

        req = (self.spec.runtime or {}).get("requires") or {}
        checks: list[dict] = []
        py = resolve_exe(self.spec)
        checks.append({"label": "Python 直譯器", "ok": bool(py) and os.path.exists(py),
                       "detail": py or "（解析不到）",
                       "hint": None if (py and os.path.exists(py))
                       else "跑 scripts/setup_test_env.ps1 建立 .venv"})
        for mod in req.get("python_modules") or []:
            r = subprocess.run([py, "-c", "import %s" % mod], capture_output=True, text=True)
            checks.append({"label": "Python 套件 %s" % mod, "ok": r.returncode == 0,
                           "detail": "已安裝" if r.returncode == 0 else (r.stderr or "").strip()[-160:],
                           "hint": None if r.returncode == 0 else "%s -m pip install %s" % (py, mod)})
        for ext in req.get("external") or []:
            cmd = ext.get("cmd")
            # ⚠️ allure 不可用裸 `which` —— PATH 上常留著讀不動現代結果的舊版
            #    （本機是 2.7.0），而儀表板那側是 npm 全域優先，
            #    兩處會報出不同版本（2026-08-23 範本端到端驗收）。
            if cmd == "allure":
                from core.allure_cli import find_allure
                found = find_allure()
            else:
                found = shutil.which(cmd)
            ver = ""
            if found:
                try:
                    ver = (subprocess.run([found, "--version"], capture_output=True, text=True,
                                          timeout=10).stdout or "").strip()
                except Exception:
                    ver = ""
            checks.append({"label": "外部指令 %s" % cmd, "ok": bool(found),
                           "detail": ("%s　%s" % (found, ver)).strip() if found else "不在 PATH",
                           "hint": None if found else ext.get("hint")})
        cwd = resolve_cwd(self.spec)
        checks.append({"label": "工作目錄", "ok": os.path.isdir(cwd), "detail": cwd,
                       "hint": None if os.path.isdir(cwd) else "registry 的 runtime.cwd 指到不存在的路徑"})
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    # ---- run ----
    @abstractmethod
    def start(self, req: StartRequest) -> RunHandle: ...

    @abstractmethod
    def stop(self, run_id: str, *, force: bool = False, reason: str = "user") -> dict: ...

    @abstractmethod
    def status(self, run_id: str) -> dict: ...

    @abstractmethod
    def logs(self, run_id: str, offset: int = 0, limit_bytes: int = 262144) -> dict: ...

    @abstractmethod
    def reports(self, run_id: str) -> list[ArtifactRef]: ...

    # ---- 案例（僅 pytest 類）----
    def list_cases(self, *, refresh: bool = False) -> dict | None:
        return None

    # ---- sync／python_call ----
    def run_command(self, command: dict, params: dict) -> dict:
        raise ValueError(f"{self.spec.id} 不支援同步命令：{command.get('id')}")


# ---------------------------------------------------------------- 條件式（與前端 form.js 同語意）
def _cond(cond: dict | None, values: dict) -> bool:
    """{key: [允許值...]}，全部 key 皆滿足才 True；None＝無條件。

    ★ 待測值是 list/tuple/set 時改判「交集非空」——給 `_products` 這類虛擬欄位用
      （見 form.js 的 evalCond，兩邊必須同語意：分歧會造成前端顯示、後端丟棄的鬼欄位）。
    """
    if not cond:
        return True
    for k, allowed in cond.items():
        v = values.get(k)
        if isinstance(v, (list, tuple, set)):
            allowed_s = {str(a) for a in allowed}
            if not any(str(x) in allowed_s for x in v):
                return False
            continue
        if isinstance(v, str) and v.lower() in ("true", "false"):
            v = v.lower() == "true"
        if v not in allowed and str(v) not in [str(a) for a in allowed]:
            return False
    return True


def _cond_req(cond: dict | None, values: dict) -> bool:
    return bool(cond) and _cond(cond, values)
