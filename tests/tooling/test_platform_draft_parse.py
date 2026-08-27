# -*- coding: utf-8 -*-
"""session 交出來的草稿要接得住（動線的最後一段）。

為什麼需要這一支
    「草稿／寫檔兩段式」兩端都做好了 —— prompt 要求固定欄位、
    `bug_draft.save()` 收得下、`/api/bug-drafts` 列得出來、開單頁按一下就配號。
    **中間沒有人做**：沒有任何程式讀過 session 的回覆。

    2026-08-23 範本實跑 CRUX：探索 session 花 45 分鐘、交出格式完全正確的
    Bug 草稿與機制文件草稿，而 `/api/bug-drafts` 回 `0`。
    產出只活在對話文字裡 —— 整條動線在最後一步斷掉，而且**沒有任何錯誤**。

    下面的樣本**取自那一則真實回覆**（節錄），不是手寫的理想輸入。

使用方式：`pytest tests/tooling/test_platform_draft_parse.py -q`
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod():
    """⚠️ 不可以在模組層插 sys.path（見 `test_platform_js_syntax` 的同名檢查）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import draft_parse
    return draft_parse


# ── 2026-08-23 探索 session 的真實回覆（節錄）────────────────
REAL = u"""
## Bug 草稿（唯讀限制下的部分發現，供你判斷是否成單）

> **開單前三問**：說明略。

```
title      賠率變動設置批量新增頁欄位可輸入非數字字元，失焦無任何格式錯誤提示
module     設置＞賠率變動設置＞批量新增
severity   低
steps      1. 總監後台 > 设置 > 赔率变动设置 > 批量新增
           2. textarea 輸入「123各1元」失焦
           3. 「变动赔率上限」欄輸入「abc」
           4. 失焦，觀察欄位下方是否出現錯誤訊息
expected   待補——規格未明文，需 PM/SA 確認
actual     欄位為 `<input type="text">`，無 `pattern`／`min`／`max` 屬性
evidence   本次 MCP 探索過程：`browser_evaluate` 讀值
prechecks  is_spec=否（無變更聲明）／already_known=否（已查對照文件）／sample_power=部分——受唯讀限制
```

沒有需要新建知識文件的內容，建議補一行：

```
kind     doc
product  CRUX
path     CRUX_賠率變動設置.md
title    （沿用既有檔，僅新增一小節）
why      補記「非數字輸入」這個此前未驗證過的前端缺口
body     建議插入「邊界值行為」節末：

## ⚠️ 前端數字欄位缺乏格式檢查

批量新增頁欄位為 `<input type="text">`，無 `pattern` 屬性。
```
"""


def test_真實回覆解析得出兩種草稿():
    """★ 核心迴歸：這則回覆在修好之前，平台一筆都沒收到。"""
    got = _mod().parse(REAL, "CRUX")
    assert len(got["bugs"]) == 1, u"Bug 草稿沒解析出來"
    assert len(got["docs"]) == 1, u"文件草稿沒解析出來"


def test_bug草稿的每個欄位都對得上():
    b = _mod().parse(REAL, "CRUX")["bugs"][0]
    assert "非數字字元" in b["title"]
    assert b["module"] == "設置＞賠率變動設置＞批量新增"
    assert b["severity"] == "低"
    assert b["product"] == "CRUX"
    # ⚠️ steps 是多行 —— 續行被當成新的鍵的話，這裡只會剩第 1 步
    assert b["steps"].count("\n") >= 3, u"續行沒有併進 steps：%r" % b["steps"]
    assert "pattern" in b["actual"]
    assert "browser_evaluate" in b["evidence"]


def test_開單前三問的答案要留住():
    """⭐ 平台起的 session 是無人看管的 —— 三問的**答案**攤開才看得出它為什麼判定該開。"""
    b = _mod().parse(REAL, "CRUX")["bugs"][0]
    pc = b["prechecks"]
    assert set(pc) >= {"is_spec", "already_known", "sample_power"}, pc
    assert "無變更聲明" in pc["is_spec"]


def test_文件草稿的body是多行且完整():
    d = _mod().parse(REAL, "CRUX")["docs"][0]
    assert d["kind"] == "doc"
    assert d["path"] == "CRUX_賠率變動設置.md"
    assert "pattern" in d["body"], u"body 的續行沒有併進來"


def test_也吃JSON寫法():
    """模板日後改用 JSON 也要收得下。"""
    text = u'```json\n[{"kind":"bug","title":"某現象","actual":"某值"}]\n```'
    got = _mod().parse(text, "CRUX")
    assert len(got["bugs"]) == 1 and got["bugs"][0]["title"] == "某現象"


# ── ⛔ 不猜：只認明確宣告的區塊 ──────────────────────────

def test_散文不會被當成草稿():
    """⛔ 猜錯的代價是配掉一個**永不回收**的 Bug ID —— 寧可漏抓。"""
    text = u"我覺得這裡有問題，title 應該要驗一下，steps 大概是點進去看看。"
    got = _mod().parse(text, "CRUX")
    assert got["bugs"] == [] and got["docs"] == []


def test_只有標題沒有其他欄位不算草稿():
    text = u"```\ntitle      只有一個標題\n```"
    assert _mod().parse(text, "CRUX")["bugs"] == []


def test_模板本身的欄位說明不會被當成草稿():
    """⚠️ prompt 把欄位表也寫成 fenced 區塊，session 可能原樣覆述。

    只有 `title` 而沒有值的那種一律不收（上一條已擋）；這裡確認
    **文件草稿**的欄位說明同樣不會被誤收 —— 它沒有真的 path。
    """
    text = u"```\nkind     doc\nproduct  產品代號\npath     檔名，例：樂透_開獎機制.md\n```"
    got = _mod().parse(text, "CRUX")
    # path 有值（是說明文字），但這種情況只會多一筆待人檢視的草稿，不會配號 ——
    # 真正的護欄是「落單要人按」。這裡只釘住它不會變成 Bug 草稿。
    assert got["bugs"] == []


def test_同一個簽章不重複收():
    got = _mod().parse(REAL + REAL, "CRUX")
    assert len(got["bugs"]) == 1, u"同一份草稿出現兩次應該去重"


# ── 2026-08-23 第二輪：探索可寫入之後多出來的兩種草稿 ──────────

REAL2 = u"""
## 產出

```
kind     report
product  CRUX
topic    賠率變動設置批量新增
title    賠率變動設置批量新增的需求驗證：8 項 PASS、2 項 FAIL
why      這批要交給 PM，需要一份可追溯的逐項紀錄
body     # 需求驗證報告

| 項目 | 期望值 | 實際值 | 判定 |
| --- | --- | --- | --- |
| R1 變動賠率上限不得超過 oddsMax | 拒絕並提示 | 靜默夾擠成 900 | FAIL |
```

動過的資料要登記：

```
kind     handover
product  CRUX
section  data
title    批量新增建立的兩筆賠率變動設置
why      其中一筆是 CRUX-090 的重現環境
cells    建立 2 筆賠率變動設置（三码定位/123） | 總監2 netsub2 | 一筆已刪除 | 另一筆保留，屬 CRUX-090
```
"""


def test_報告草稿解析得出來():
    got = _mod().parse(REAL2, "CRUX")
    rep = [d for d in got["docs"] if d["kind"] == "report"]
    assert len(rep) == 1, got["docs"]
    assert rep[0]["topic"] == "賠率變動設置批量新增"
    assert "FAIL" in rep[0]["body"], u"body 的續行沒有併進來"


def test_報告沒有topic就不收():
    """⛔ 檔名要靠 topic 向 new_bug_doc.py 取號 —— 沒有它就不知道要寫成什麼檔。"""
    text = u"```\nkind     report\nproduct  CRUX\nbody     一些內容\n```"
    assert _mod().parse(text, "CRUX")["docs"] == []


def test_測試資料草稿的cells會切成欄位():
    """⚠️ 交回來是一行 `A | B | C`，不切的話寫檔時會被逐字元 join。"""
    got = _mod().parse(REAL2, "CRUX")
    data = [d for d in got["docs"] if d.get("section") == "data"][0]
    assert len(data["cells"]) == 4, data["cells"]
    assert data["cells"][1] == "總監2 netsub2"
    assert "CRUX-090" in data["cells"][3]


def test_報告不會被誤收成bug():
    got = _mod().parse(REAL2, "CRUX")
    assert got["bugs"] == [], u"report／handover 被當成 Bug 草稿會配掉永不回收的 ID"
