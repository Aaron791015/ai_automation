# -*- coding: utf-8 -*-
"""落單時把 session 拍的佐證截圖自動搬進 `docs/<產品>/bugs/shots/`。

用途：截圖是整條動線上**唯一一個先前要人手動接的環節** —— 而人幾乎一定會忘：
      2026-08-25 一批 8 張放在共用暫存被清光、另一批 8 張拍完就沒人搬。

作法：Bug 落單拿到 ID 的那一刻，掃這個 session 的 `shots/`，
      **凡是這張單的 `evidence` 有提到檔名的**，就改名成 `<ID>_<序2碼>_<描述>.png` 搬過去。
      改名與蓋標記一律呼叫 `scripts/stamp_shots.py`，⛔ 不在這裡重寫一份搬移邏輯。

⚠️ **誠實邊界**：標記蓋的是 `marks=auto`（不是 `mcp`）——
   那個值是**來源標記**，記的是「平台代搬、標注由 session 在拍攝當下完成、**平台未驗證**」。
   ⛔ 不可以冒用 `mcp`：日後要查一張圖的來歷時，那是唯一分得出來的線索。
   真正保證「有標注」的是任務提示的第①步（先注入 `__annotate` 再拍），不是這支。

⛔ **只搬被引用的** —— session 常拍一堆過程圖，全搬過去只會在 `shots/` 堆出死圖（W1）。
"""
from __future__ import annotations

import os
import re
import subprocess

from core.paths import REPO_ROOT, SESSIONS_DIR, python_exe

#: 檔名裡不能留的字元（Windows 檔名限制 ＋ 命名規範的分隔用途）
_BAD = re.compile(r'[\\/:*?"<>|\s]+')
#: 從 evidence 文字裡認出檔名
_IMG = re.compile(r'[^\s`"\'（）()\[\]｜|，、。；;：:]+\.(?:png|jpg|jpeg)', re.I)


def shots_dir(sid: str) -> str:
    return os.path.join(SESSIONS_DIR, sid, "shots")


def referenced(evidence: str, names: list) -> list:
    """`evidence` 裡提到、且真的存在於 shots/ 的檔名。

    ⭐ **順序跟著 evidence 的敘述走，不是檔名排序** —— 序號 `_01_`／`_02_` 是給讀者看的，
      要對得上單子裡「先講哪張、再講哪張」。照檔名排序會讓中文檔名以碼位排列，
      與敘事順序無關（實測：「丙」的碼位小於「甲」）。
    """
    have = set(names)
    out = []
    for t in _IMG.findall(evidence or ""):
        n = os.path.basename(t.replace("\\", "/"))
        if n in have and n not in out:
            out.append(n)
    return out


def target_name(bug_id: str, seq: int, src_name: str, limit: int = 60) -> str:
    """`<ID>_<序2碼>_<描述>.png` —— 描述沿用原檔名（它本來就要求「帶得出內容」）。"""
    stem, ext = os.path.splitext(src_name)
    stem = _BAD.sub("_", stem).strip("_")[:limit] or "佐證"
    return "%s_%02d_%s%s" % (bug_id, seq, stem, ext.lower() or ".png")


def file_for_bug(sid: str, bug_id: str, product: str, evidence: str) -> dict:
    """搬這張單引用到的截圖。回 `{moved: [...], skipped: [...], error: str|None}`。

    ⚠️ 失敗一律**不中斷落單** —— 單子已經寫好了，搬圖失敗只該變成一行提醒。
    """
    out = {"moved": [], "skipped": [], "error": None}
    d = shots_dir(sid)
    try:
        names = sorted(f for f in os.listdir(d)
                       if f.lower().endswith((".png", ".jpg", ".jpeg")))
    except OSError:
        return out                                  # 沒有 shots/ 就是這輪沒拍，不是錯
    hit = referenced(evidence, names)
    if not hit:
        out["skipped"] = names
        return out

    pairs = []
    for i, n in enumerate(hit, 1):
        src = os.path.join(d, n).replace("\\", "/")
        pairs.append("%s=%s" % (src, target_name(bug_id, i, n)))
    argv = [python_exe(), os.path.join("scripts", "stamp_shots.py"),
            "--product", product, "--mark", "auto"] + pairs
    try:
        r = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=120)
    except Exception as e:                          # noqa: BLE001
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        return out
    if r.returncode != 0:
        # ⚠️ stamp_shots 是**整批不執行**（回傳碼 1 就是一張都沒搬），所以這裡不必回滾
        out["error"] = (r.stdout or r.stderr or "").strip()[:300] or "stamp_shots 回傳 %d" % r.returncode
        return out
    out["moved"] = [p.split("=", 1)[1] for p in pairs]
    out["skipped"] = [n for n in names if n not in hit]
    return out
