# -*- coding: utf-8 -*-
"""工作區工具腳本測試的共用 fixture。

用途：`scripts/` 下的工具（Bug 索引、資產 lint、歸檔、交付打包）沒有測試時，
      每次改動都只能靠人工建沙箱驗證；本目錄補上回歸保障。
使用方式：`scripts\\run_ui_tests.ps1 -Filter tooling` 或 `pytest tests/tooling -q`
前置條件：無（全部在 tmp_path 上操作，不碰真實 docs/）。
"""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def products_from_config():
    """直接讀 `config/products.json`（產品定義的單一來源），回 [(slug, 權威id), …]。

    ⛔ **這支刻意不載入平台。** 模組層的守衛（`pytestmark = skipif(...)`）只能用它。

    為什麼：`from core.registry import …` 會把 `sys.modules['core']` 綁成
    **平台的 core**，而那發生在**收集期**。接著收集 `tests/wbot/perf/` 時，
    它的 conftest 想讓 `from core.time_utils import …` 指向
    `tools/wbot_Performance/core` —— 但 `core` 已經被佔住了，12 支測試直接
    `ModuleNotFoundError`。

    ⚠️ 後果不只是紅燈：**平台的案例索引重建是唯一會一次收集整個 `tests/` 的地方**，
       它因此一直失敗、一直沿用舊快取（`ok: true` 但 `stale: true`，
       案例數從來不變）。而單獨跑 `pytest tests/tooling` 或 `tests/wbot/perf`
       都是綠的 —— 這個缺陷躲過了所有人的日常指令（2026-08-24 走查才發現）。
    """
    import json
    path = os.path.join(ROOT, "config", "products.json")
    try:
        data = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for p in data.get("products") or []:
        if p.get("virtual"):
            continue
        slug = (p.get("aliases") or [None])[0] or p.get("skill") or p.get("id")
        if slug and p.get("id"):
            out.append((slug, p["id"]))
    return out


def has_product():
    """這個工作區有沒有接任何產品？—— **模組層守衛只能用這一支**（見上）。"""
    return bool(products_from_config())


def any_product():
    """從**實際的**產品註冊表取一個產品，回傳 `(slug, 權威id)`；一個都沒有就回 None。

    ⛔ **通用測試不可以寫死 `crux`。** 這個 repo 是要當範本發給同事的，
       而匯出的範本 `config/products.json` 是空的 —— 寫死產品的測試在那裡必紅，
       且紅的原因與「範本有沒有問題」無關。

    2026-08-24 匯出全新範本時，三條測試就是這樣紅的
    （而且被 `export_template.verify()` 的一個 NameError 蓋住了好幾天）。
    """
    import sys
    plat = os.path.join(ROOT, "tools", "test_platform")
    if plat not in sys.path:
        sys.path.insert(0, plat)
    try:
        from core.registry import get_registry
        for p in get_registry().products:
            if p.get("virtual"):
                continue
            return p.get("id"), (p.get("product_id") or p.get("label") or p.get("id"))
    except Exception:                       # noqa: BLE001
        pass
    return None


def need_product():
    """沒有產品就 skip（給依賴「至少有一個產品」的測試用）。"""
    got = any_product()
    if not got:
        pytest.skip("這個工作區還沒接任何產品（空範本）—— 這條測試需要至少一個")
    return got


def write(path, text):
    """寫檔並自動建立上層目錄（測試 fixture 用）"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def bug_doc(bug_id, title, status="open", body="", **extra):
    """產生一份最小可用的 Bug 單（frontmatter ＋ Actual／Expect）"""
    fm = ["---", "id: %s" % bug_id, "title: %s" % title, "product: CRUX",
          "status: %s" % status, "found: 2026-08-01"]
    fm += ["%s: %s" % (k, v) for k, v in extra.items()]
    fm.append("---")
    return "\n".join(fm) + "\n\n# %s %s\n\n## Actual result\n\n實際 1\n\n## Expect result\n\n預期 2\n\n%s\n" % (
        bug_id, title, body)


@pytest.fixture
def bugs_tree(tmp_path):
    """建立一棵最小的 bugs/ 目錄樹，回傳 (bugs_dir, product_base)。

    內容刻意涵蓋各檢查的邊界：
      - CRUX-001 open，引用一張**檔名含小數點**的圖（曾導致假斷圖）
      - CRUX-002 fixed，有 `_fixed_` 驗證圖（死圖檢查應豁免）
      - CRUX-003 superseded（不應列入待開立）
      - _reports/ 引用圖（以 `../shots/` 形式）
      - _deliver/ 自帶 shots/（不應被拿去比對主 shots/）

    ⚠️ 這裡的 `CRUX` 只是**通用測資的固定樣板 ID**，不代表這個工作區真的接了 CRUX——
    `lint_bug_assets.py`／`archive_bugs.py` 的 ID_RE／SHOT_NAME_RE 因此把
    `CRUX`／`WBOT`／`QX` 三個原型前綴當作**永遠承認的內建樣板前綴**，
    與 `config/products.json` 實際登記的前綴取聯集（見那兩支腳本的 `_PREFIXES` 註解），
    這樣不管這個 clone 實際接了哪個產品，本檔的固定測資都不會被自己的 regex 誤判。
    """
    base = tmp_path / "docs" / "CRUX"
    bugs = base / "bugs"
    shots = bugs / "shots"
    os.makedirs(str(shots))

    write(str(bugs / "CRUX-001_測試甲.md"),
          bug_doc("CRUX-001", "測試甲",
                  body="![實際回水 0.54，應為 0.27](shots/CRUX-001_01_回水0.54.png)"))
    write(str(bugs / "CRUX-002_測試乙.md"),
          bug_doc("CRUX-002", "測試乙", status="fixed",
                  body="![修復後顯示 −129.76](shots/CRUX-002_01_一般圖.png)"))
    write(str(bugs / "CRUX-003_測試丙.md"),
          bug_doc("CRUX-003", "測試丙", status="superseded"))

    # 截圖的 mtime 設在標注規範生效日之前 —— fixture 代表「既有狀態」，
    # 預設不該觸發 W7 未標注；要測新圖的案例自己把 mtime 改成現在。
    old = time.mktime(time.strptime("2026-01-01", "%Y-%m-%d"))
    for n in ("CRUX-001_01_回水0.54.png", "CRUX-002_01_一般圖.png",
              "CRUX-002_fixed_01_修復驗證.png"):
        p = write(str(shots / n), "PNG")
        os.utime(p, (old, old))

    write(str(bugs / "_reports" / "報告_2026-08-01.md"),
          "# 報告\n\n見 `../shots/CRUX-002_fixed_01_修復驗證.png`\n"
          "與 [單](../CRUX-001_測試甲.md)。\n")
    write(str(bugs / "_deliver" / "2026-08-01_交付" / "CRUX-001_測試甲.md"),
          "# CRUX-001\n\n![圖](shots/CRUX-001_01_回水0.54.png)\n")
    write(str(bugs / "_deliver" / "2026-08-01_交付" / "shots" / "CRUX-001_01_回水0.54.png"), "PNG")
    return str(bugs), str(base)
