# -*- coding: utf-8 -*-
"""`scripts/lint_bug_assets.py` 的回歸測試。

用途：鎖住三個曾經踩過的實作陷阱，避免改動時重蹈覆轍：
      ① 截圖檔名含小數點時，引用比對不可用「像檔名的字串」（會從中間切斷 → 假斷圖）
      ② `_deliver/` 自帶 shots/，是自足快照，不可拿來比對主 shots/（會產生假斷圖）
      ③ `_fixed_` 驗證圖依 jira-verify 規範上傳 JIRA、本地不回貼，不算死圖
前置條件：無（全在 tmp_path）。
"""
import io
import os
import time

import pytest

import lint_bug_assets as L
from conftest import bug_doc, write


def run(base):
    return L.lint("CRUX", base)


def test_檔名含小數點的引用不應被判成斷圖(bugs_tree):
    """`shots/CRUX-001_01_回水0.54.png` 曾被 regex 從 `.54` 切開，產生 14 個假斷圖"""
    _bugs, base = bugs_tree
    errors, _w, _d, _s = run(base)
    assert not [e for e in errors if e.startswith("E1")], errors


def test_deliver自帶截圖不納入主shots比對(bugs_tree):
    """交付包引用自己的 shots/，若納入比對會說主 shots/ 缺圖"""
    _bugs, base = bugs_tree
    errors, _w, _d, _s = run(base)
    assert not errors, errors


def test_fixed驗證圖不算死圖(bugs_tree):
    """`CRUX-002_fixed_01` 只被 _reports 引用；即使沒人引用也應豁免"""
    bugs, base = bugs_tree
    os.remove(os.path.join(bugs, "_reports", "報告_2026-08-01.md"))
    _e, warnings, dead, _s = run(base)
    assert "CRUX-002_fixed_01_修復驗證.png" not in dead
    assert not [w for w in warnings if w.startswith("W1")], warnings


def test_真正的死圖會被抓到(bugs_tree):
    bugs, base = bugs_tree
    write(os.path.join(bugs, "shots", "CRUX-001_02_沒人引用.png"), "PNG")
    _e, warnings, dead, _s = run(base)
    assert "CRUX-001_02_沒人引用.png" in dead
    assert any(w.startswith("W1") for w in warnings)


def test_斷圖會被抓到(bugs_tree):
    bugs, base = bugs_tree
    os.remove(os.path.join(bugs, "shots", "CRUX-001_01_回水0.54.png"))
    errors, _w, _d, _s = run(base)
    assert any(e.startswith("E1") for e in errors), errors


def test_W9引用不存在的截圖會被抓到(bugs_tree):
    """2026-08-25：三張單引用 `.playwright-mcp/xxx.png`，而那是共用暫存、早被清掉。
    落單當下沒有任何檢查發現，事後 lint 也全綠 —— 因為它只認 `shots/` 形式的引用。"""
    bugs, base = bugs_tree
    write(os.path.join(bugs, "CRUX-004_測試丁.md"),
          bug_doc("CRUX-004", "測試丁",
                  body="佐證：截圖 .playwright-mcp/CRUX-004_01_證據.png"))
    _e, warnings, _d, _s = run(base)
    hit = [w for w in warnings if w.startswith("W9") and "CRUX-004_01_證據.png" in w]
    assert hit, warnings


def test_W9已經搬進shots的引用不報(bugs_tree):
    """搬進去了就歸 W1／W5／W7 管，W9 不該重複叫。"""
    _bugs, base = bugs_tree
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings
                if w.startswith("W9") and "CRUX-001_01_回水0.54.png" in w], warnings


def test_W9不把含空白的舊檔名切碎(bugs_tree):
    """⛔ 誤抓比漏抓嚴重：一噴十幾條假警告，整條檢查就會被當雜訊。"""
    bugs, base = bugs_tree
    write(os.path.join(bugs, "CRUX-005_測試戊.md"),
          bug_doc("CRUX-005", "測試戊",
                  body="當時的畫面是「截圖 2026-08-11 下午3.45.17.png」（已遺失，僅文字描述）"))
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings if w.startswith("W9")], warnings


def test_W9認得我們自己的命名而不必帶路徑(bugs_tree):
    """報告常寫「佐證截圖：`CRUX-1052_….png`」不帶目錄 —— 那也是引用，要抓得到。"""
    bugs, base = bugs_tree
    write(os.path.join(bugs, "_reports", "報告_測試.md"),
          "佐證截圖：`JIRA-CRUX-1052_01_不存在的圖.png`")
    _e, warnings, _d, _s = run(base)
    assert [w for w in warnings
            if w.startswith("W9") and "JIRA-CRUX-1052_01_不存在的圖.png" in w], warnings


def test_撞號會被抓到(bugs_tree):
    bugs, base = bugs_tree
    write(os.path.join(bugs, "CRUX-001_另一份.md"), bug_doc("CRUX-001", "重複"))
    errors, _w, _d, _s = run(base)
    assert any(e.startswith("E2") for e in errors), errors


def test_歸檔層的單與圖都會被掃到(bugs_tree):
    """Bug 單只存在主目錄或 old/；lint 掃不到 old/ 時會把已歸檔的圖判成斷圖"""
    bugs, base = bugs_tree
    old = os.path.join(bugs, L.ARCHIVE_DIR)
    write(os.path.join(old, "CRUX-004_已歸檔.md"),
          bug_doc("CRUX-004", "已歸檔", status="fixed",
                  body="![圖](shots/CRUX-004_01_圖.png)"))
    write(os.path.join(old, "shots", "CRUX-004_01_圖.png"), "PNG")
    errors, _w, _d, stat = run(base)
    assert not errors, errors
    assert "4 單" in stat


def test_JIRA前綴的圖不會被誤報為外部ID(bugs_tree):
    bugs, base = bugs_tree
    write(os.path.join(bugs, "shots", "JIRA-CRUX-882_fixed_01_他人單.png"), "PNG")
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings if w.startswith("W3")], warnings


def test_未加前綴的他人單圖會被提醒(bugs_tree):
    bugs, base = bugs_tree
    write(os.path.join(bugs, "shots", "CRUX-882_fixed_01_他人單.png"), "PNG")
    _e, warnings, _d, _s = run(base)
    assert any(w.startswith("W3") for w in warnings), warnings


@pytest.mark.parametrize("status", ["suggestion", "rejected", "superseded"])
def test_非缺陷單不要求Actual_Expect(bugs_tree, status):
    bugs, base = bugs_tree
    write(os.path.join(bugs, "CRUX-005_建議.md"),
          "---\nid: CRUX-005\ntitle: 建議\nstatus: %s\n---\n\n# 內文無 Actual\n" % status)
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings if "CRUX-005" in w and w.startswith("W4")], warnings


def test_索引過期會被抓到(bugs_tree):
    """過期的 BUG清單.md／_view/ 比沒有更危險：看起來權威卻可能少一張新單"""
    bugs, base = bugs_tree
    idx = write(os.path.join(bugs, "BUG清單.md"), "# 舊索引\n")
    old_time = os.path.getmtime(idx) - 3600
    os.utime(idx, (old_time, old_time))
    _e, warnings, _d, _s = run(base)
    assert any(w.startswith("W6") for w in warnings), warnings


def test_W7引用無說明會被抓到(bugs_tree):
    """`![](shots/x.png)` 讀者不知道要看什麼，等於沒說明"""
    bugs, base = bugs_tree
    p = os.path.join(bugs, "CRUX-001_測試甲.md")
    t = io.open(p, encoding="utf-8").read().replace("![實際回水 0.54，應為 0.27]", "![]")
    io.open(p, "w", encoding="utf-8", newline="\n").write(t)
    _e, warnings, _d, _s = run(base)
    assert any(w.startswith("W7 引用無說明") for w in warnings), warnings


def test_W7有說明時不報(bugs_tree):
    """fixture 的 alt 本來就寫了實際值 vs 應為值，符合規範"""
    _bugs, base = bugs_tree
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings if w.startswith("W7 引用無說明")], warnings


def test_W7新圖未標注會被抓到(bugs_tree):
    """規範生效日之後產生的圖，沒有標注標記就報"""
    bugs, base = bugs_tree
    img = os.path.join(bugs, "shots", "CRUX-001_01_回水0.54.png")
    now = time.time()
    os.utime(img, (now, now))                      # 視為今天新產的圖
    _e, warnings, _d, _s = run(base)
    assert any(w.startswith("W7 截圖未標注") for w in warnings), warnings


def test_W7舊圖不追溯(bugs_tree):
    """全部追溯會一次噴上百則警告，訊號被雜訊淹沒 → 大家學會忽略 lint"""
    bugs, base = bugs_tree
    img = os.path.join(bugs, "shots", "CRUX-001_01_回水0.54.png")
    old = time.mktime(time.strptime("2026-01-01", "%Y-%m-%d"))
    os.utime(img, (old, old))
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings if w.startswith("W7 截圖未標注")], warnings


def test_W7已標注的新圖不報(bugs_tree):
    bugs, base = bugs_tree
    img = os.path.join(bugs, "shots", "CRUX-001_01_回水0.54.png")
    # 造一張帶標記的最小 PNG（IHDR 之後插 tEXt）
    import struct, zlib
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(
        ">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    td = b"qa-annotated\x00marks=2"
    text = struct.pack(">I", len(td)) + b"tEXt" + td + struct.pack(
        ">I", zlib.crc32(b"tEXt" + td) & 0xFFFFFFFF)
    io.open(img, "wb").write(sig + ihdr + text)
    now = time.time()
    os.utime(img, (now, now))
    _e, warnings, _d, _s = run(base)
    assert not [w for w in warnings if w.startswith("W7 截圖未標注")], warnings


# ── W10 缺佐證截圖（2026-08-26 使用者裁示）────────────────
#
# ⭐ 「佐證截圖可以更快速的讓看的人了解問題點」—— 與 `bug-report` §4 第一句
#    「讀者要在 10 秒內知道哪裡錯」是同一件事。
# ⛔ 先前的反對理由「截圖不版控」只推得出「不能只有圖」，推不出「不該有圖」：
#    W4 已強制內文要有 Actual／Expect 數值，圖丟了還有數值兜底。

def _bug(tmp_path, name, fm_extra="", body="Actual result\n\n實際 5\n\nExpect result\n\n應為 3\n"):
    d = tmp_path / "bugs"
    d.mkdir(exist_ok=True)
    (d / name).write_text(
        "---\nid: CRUX-901\ntitle: 某現象\nproduct: CRUX\nstatus: open\n"
        "found: 2026-08-27\nenv: QAT\n%s---\n\n%s" % (fm_extra, body),
        encoding="utf-8")
    return d


def _w10(base):
    import lint_bug_assets as L
    return [w for w in L.lint("CRUX", str(base.parent), verbose=False)[1] if "W10" in w] \
        if hasattr(L, "lint") else []


def test_W10_沒圖要報(tmp_path, monkeypatch):
    import lint_bug_assets as L
    d = _bug(tmp_path, "CRUX-901_x.md")
    bugs, texts, shots = L.collect(str(d))[:3]
    # 直接驗判斷條件本身（lint() 需要完整的產品目錄結構）
    meta = list(bugs.values())[0][0][1]
    assert not meta.get("no_shot")
    assert str(meta.get("found")) >= L.SHOT_POLICY_DATE, u"生效日判斷會讓它被跳過"


def test_W10_生效日之前的舊單不追溯():
    """⛔ 全部追溯會一次噴四十幾則 —— 訊號被雜訊淹沒，比沒有檢查更糟（同 W7）。"""
    import lint_bug_assets as L
    assert L.SHOT_POLICY_DATE == "2026-08-26", L.SHOT_POLICY_DATE


def test_W10_視覺性缺陷要額外標出來():
    """★ 錯誤訊息、版面問題用文字描述永遠不如一張圖。"""
    import lint_bug_assets as L
    assert "非截圖不可" in L._visual_hint({"surface": "前台", "title": "x"}, "")
    assert "非截圖不可" in L._visual_hint({"surface": "後台", "title": "欄位顯示錯誤"}, "")
    assert L._visual_hint({"surface": "後台", "title": "金額對帳不符"}, "") == "", \
        u"純數值缺陷不該被額外標記 —— 那會變成雜訊"


def test_W10_可以明示豁免():
    """⭐ 重點是讓「不放圖」變成一個**要寫下理由的決定**，而不是默默省略。"""
    import lint_bug_assets as L
    # ⚠️ 用模組自己的檔案位置，不要另外算 ROOT（這個測試檔沒有那個常數）
    src = io.open(L.__file__, encoding="utf-8").read()
    assert 'meta.get("no_shot")' in src, u"沒有豁免出口 —— API／DB 類的缺陷會被一直吵"
