"""Claude Code 上線檢查：找執行檔 → auth status → doctor。全部唯讀、零額度消耗。

用途：#/settings/claude 頁與側翼遙測「Claude」燈；同事照這頁就能把自己弄上線。
使用方式：
    from core.claude_probe import probe_claude
    info = probe_claude()          # 快取 60 秒；refresh=True 強制
    python -m core.claude_probe
前置條件／踩坑（2026-08-19 本機實測）：
    · claude 多半不在 PATH（native 裝在 ~\\.local\\bin 但未加 PATH；VSCode 擴充內的 claude.exe 也不進 PATH）
      → 依序找：config.claude.executable → PATH → ~\\.local\\bin\\claude.exe → VSCode 擴充目錄取**版本號最大**者
    · VSCode 擴充目錄帶版本號（anthropic.claude-code-2.1.234-win32-x64），升級後會變，不可寫死
    · `claude auth status` 回結構化 JSON：{loggedIn, authMethod, apiProvider, email, orgName, subscriptionType}
    · `claude doctor` 回逐項警告 ＋ 可照做的修復指令；原樣顯示即可
    · 登入憑證存 ~/.claude/.credentials.json（使用者層級），與 VSCode 無關 —— 不需要「在 VSCode 登入」
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

from core.config import load_config

_cache: dict = {"ts": 0, "data": None}
_VER = re.compile(r"claude-code-(\d+)\.(\d+)\.(\d+)")


def _vscode_candidates() -> list[str]:
    home = os.path.expanduser("~")
    pats = [os.path.join(home, ".vscode", "extensions", "anthropic.claude-code-*", "resources", "native-binary", "claude.exe"),
            os.path.join(home, ".vscode-insiders", "extensions", "anthropic.claude-code-*", "resources", "native-binary", "claude.exe")]
    found = []
    for p in pats:
        found.extend(glob.glob(p))
    def ver(p):
        m = _VER.search(p)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    return sorted(found, key=ver, reverse=True)


def find_executable() -> tuple[str | None, str]:
    """回 (路徑, 來源)。來源 ∈ config|PATH|local_bin|vscode|none"""
    cfg = (load_config().get("claude") or {}).get("executable")
    if cfg and os.path.isfile(os.path.expandvars(os.path.expanduser(cfg))):
        return os.path.expandvars(os.path.expanduser(cfg)), "config"
    w = shutil.which("claude")
    if w:
        return w, "PATH"
    lb = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if os.path.isfile(lb):
        return lb, "local_bin"
    vs = _vscode_candidates()
    if vs:
        return vs[0], "vscode"
    return None, "none"


def _run(exe: str, args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"逾時（{timeout}s）"
    except OSError as e:
        return -2, "", str(e)


def probe_claude(refresh: bool = False) -> dict:
    now = time.time()
    if not refresh and _cache["data"] and now - _cache["ts"] < 60:
        return _cache["data"]
    exe, source = find_executable()
    out: dict = {"executable": exe, "source": source, "version": None, "auth": None,
                 "logged_in": False, "doctor": None, "ok": False, "hints": [], "checked_at": time.strftime("%H:%M:%S"),
                 "alternatives": _vscode_candidates()[:5]}
    if not exe:
        out["hints"] = [
            "找不到 claude 執行檔。兩條路任選：",
            "① 安裝 VSCode 擴充「Claude Code」（附帶 claude.exe，本平台會自動找到）",
            "② 終端機執行 `claude install`（native build，裝到 ~\\.local\\bin）",
            "也可在 config/platform_config.local.json 的 claude.executable 指定路徑",
        ]
        _cache.update(ts=now, data=out)
        return out
    code, so, se = _run(exe, ["--version"], 15)
    out["version"] = (so or se).strip().splitlines()[0] if (so or se).strip() else None
    code, so, se = _run(exe, ["auth", "status"], 20)
    try:
        auth = json.loads(so.strip() or "{}")
    except json.JSONDecodeError:
        auth = {"raw": (so or se).strip()[:400]}
    out["auth"] = auth
    out["logged_in"] = bool(auth.get("loggedIn"))
    if not out["logged_in"]:
        out["hints"].append("尚未登入。終端機執行 `claude auth login`（或在 VSCode 內登入，兩者共用同一份憑證 ~/.claude/.credentials.json）")
        out["hints"].append("企業／API key：可設環境變數 ANTHROPIC_API_KEY，或用 `claude setup-token` 產長效 token")
    code, so, se = _run(exe, ["doctor"], 30)
    doc_text = (so or "") + ("\n" + se if se.strip() else "")
    warnings = []
    cur = None
    for ln in doc_text.splitlines():
        s = ln.strip()
        if s.startswith("- ") and not s.startswith("- Feature"):
            cur = {"warning": s[2:], "fix": None}
            warnings.append(cur)
        elif s.startswith("Fix:") and cur:
            cur["fix"] = s[4:].strip()
    out["doctor"] = {"raw": doc_text[-3000:], "warnings": warnings}
    out["ok"] = out["logged_in"] and exe is not None
    if source == "vscode":
        out["hints"].append("目前使用 VSCode 擴充內的 claude.exe；擴充升級後路徑會變，本平台每次會重新取版本號最大者")
    _cache.update(ts=now, data=out)
    return out


def main(argv=None) -> int:
    info = probe_claude(refresh=True)
    print(json.dumps({k: v for k, v in info.items() if k != "doctor"}, ensure_ascii=False, indent=1))
    print("doctor warnings:", len((info.get("doctor") or {}).get("warnings", [])))
    for w in (info.get("doctor") or {}).get("warnings", []):
        print("  -", w["warning"][:80], "→", (w["fix"] or "")[:60])
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
