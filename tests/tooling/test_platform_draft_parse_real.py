# -*- coding: utf-8 -*-
"""草稿解析：**真實回覆**裡那些「格式不完全照模板」的寫法要收得住。

為什麼另開一支
    `test_platform_draft_parse.py` 用的是理想輸入。這一支收的是
    2026-08-23 兩場實跑（探索可寫入、需求驗證）**真的交回來**的寫法 ——
    每一種在修好之前都會靜默寫出壞資料：

      · 表格式的 `cells`（欄位說明 ＋ 多列）→ 併成一筆含換行的怪陣列
      · markdown 表格（表頭 ＋ `--- | ---` 分隔列）→ 表頭與分隔列各被當成一筆資料
      · YAML 塊標記（`body     |`）→ body 的第一行是一個孤零零的「|」
      · 完整路徑 ＋ 括號說明的 `path` → 寫出 `docsCRUXX.md（…）.md` 這種檔名

    ⚠️ 這些**都不會報錯**。錯誤會出現在交接檔與 docs/ 裡，而且沒有人在看。

使用方式：`pytest tests/tooling/test_platform_draft_parse_real.py -q`
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import draft_parse
    return draft_parse


# ── 探索（可寫入）那一輪交回來的測試資料草稿（節錄）────────────
EXPLORE = u"""
### ③ 測試資料異動

```
kind     handover
product  crux
section  data
title    探索賠率變動設置留下的兩筆設定
why      本次操作寫入了總監2/排列三的賠率變動設置記錄
cells    建立/修改了什麼 | 在哪個站台與帳號 | 還原了沒 | 刻意保留的屬哪一張單
         三码定位 357（變動賠率上限測 abc/1500/650） | 總監2 排列三 netsub2 | 已刪除 | 無保留
         三码定位 358（批量新增頁，變動賠率850） | 同上 | 已隨 357 一併刪除 | 無保留，同上
```
"""

# ── 需求驗證那一輪：YAML 塊標記 ＋ markdown 表格 ────────────────
VERIFY = u"""
```
kind     report
product  crux
topic    水賠間距保存驗證規則
title    R1~R7 逐項驗證
why      有一項 BLOCKED，建議寫檔存證
body     |
  # 水賠間距保存驗證規則 — 需求驗證報告

  | 項目 | 期望值 | 實際值 | 判定 |
  | --- | --- | --- | --- |
  | R2 | 被擋下 | 被擋下 | PASS |
```

```
kind     handover
product  crux
section  data
title    福彩3D 独胆／全胆拖2 的資料異動
why      需登記供稽核
cells    |
  異動對象 | 站台/帳號 | 動了什麼 | 還原了沒 | 備註
  --- | --- | --- | --- | ---
  独胆水賠間距 | 總監2／netsub4 | 四次負向嘗試皆被拒 | ⚠️ 回水值已變 | 見 todo_ext
  全胆拖2 定盤赔率下限 | 總監2／netsub4 | 改為 38.5 | ✅ 已還原 36.835 | 符合 R7
```
"""


def test_表格式的cells拆成多筆而不是一筆():
    """★ 交接檔一列就是一件事 —— 人要能逐列決定寫不寫。"""
    docs = _mod().parse(EXPLORE, "crux")["docs"]
    data = [d for d in docs if d.get("section") == "data"]
    assert len(data) == 2, [d["cells"] for d in data]
    assert data[0]["cells"][0].startswith("三码定位 357")
    assert data[1]["cells"][0].startswith("三码定位 358")
    # 每一列都是乾淨的四欄，沒有夾帶換行
    for d in data:
        assert len(d["cells"]) == 4, d["cells"]
        assert not any("\n" in c for c in d["cells"])


def test_欄位說明那一行不會變成資料():
    """session 常把模板的欄位說明原樣抄回來當第一列。"""
    docs = _mod().parse(EXPLORE, "crux")["docs"]
    cells = [c for d in docs for c in d.get("cells") or []]
    assert "建立/修改了什麼" not in cells
    assert "刻意保留的屬哪一張單" not in cells


def test_多筆草稿的簽章不相同():
    """⛔ 簽章相同會被去重掉，第二列就靜默不見了。"""
    docs = [d for d in _mod().parse(EXPLORE, "crux")["docs"]
            if d.get("section") == "data"]
    assert len({d["signature"] for d in docs}) == len(docs)


def test_YAML塊標記不會變成body的第一行():
    """`body     |` 之後才是內容 —— 照收的話 body 開頭是一個孤零零的「|」。"""
    rep = [d for d in _mod().parse(VERIFY, "crux")["docs"] if d["kind"] == "report"][0]
    assert rep["body"].lstrip().startswith("#"), repr(rep["body"][:40])
    assert "PASS" in rep["body"], u"表格內容沒併進 body"


def test_markdown表格的表頭與分隔列都要丟掉():
    """★ 判準是「下一列是不是 `--- | ---`」—— 比認欄位字樣可靠，
    因為 session 會自己造欄位名（這次是「異動對象／動了什麼／備註」）。"""
    docs = [d for d in _mod().parse(VERIFY, "crux")["docs"]
            if d.get("section") == "data"]
    assert len(docs) == 2, [d["cells"] for d in docs]
    first = [d["cells"][0] for d in docs]
    assert "異動對象" not in first, u"表頭被當成資料"
    assert not any(c.startswith("---") for d in docs for c in d["cells"]), u"分隔列被當成資料"
    assert first[0].startswith("独胆") and first[1].startswith("全胆拖2")


def test_報告仍然只有一筆():
    """report 沒有「多列」的概念，不該被展開。"""
    reps = [d for d in _mod().parse(VERIFY, "crux")["docs"] if d["kind"] == "report"]
    assert len(reps) == 1


def test_這兩輪都不該產生bug草稿():
    """⛔ 誤收就是配掉一個永不回收的 ID。"""
    for text in (EXPLORE, VERIFY):
        assert _mod().parse(text, "crux")["bugs"] == []


# ── 續行的相對縮排要保住 ──────────────────────────────────
NESTED = u"""
````
kind     report
product  crux
topic    縮排測試
title    t
body     |
  # 報告

  - 第一層
    - 第二層（相對縮排）

  ```
  程式碼區塊
      更深的縮排
  ```
````
"""


def test_續行的相對縮排不可以被壓平():
    """★ 逐行 strip() 會把巢狀清單與程式碼區塊壓平 —— **而且寫檔不會報錯**。"""
    rep = [d for d in _mod().parse(NESTED, "crux")["docs"] if d["kind"] == "report"][0]
    body = rep["body"]
    assert body.startswith("# 報告"), repr(body[:20])
    assert "\n  - 第二層" in body, u"第二層縮排被壓平了：%r" % body
    assert "\n    更深的縮排" in body, u"程式碼區塊的縮排被壓平了"


# ── 開單前三問：分隔符不能靠猜 ──────────────────────────────
def test_三問用分號分隔也要各自切開():
    """★ 三問的答案是「無人看管的 session 為什麼判定該開單」的唯一佐證 ——
    漏切的話三段全擠進 is_spec，另外兩問變成空的（2026-08-23 實跑）。"""
    text = (u"````\ntitle    某現象\nactual   某值\n"
            u"prechecks  is_spec：不是規格 —— 裁定寫的是靜默夾擠；"
            u"already_known：非重複 —— CRUX-105 談的是下界；"
            u"sample_power：有鑑別力 —— 同號碼兩路徑對照\n````")
    pc = _mod().parse(text, "crux")["bugs"][0]["prechecks"]
    assert set(pc) == {"is_spec", "already_known", "sample_power"}, pc
    assert pc["already_known"].startswith("非重複")
    assert pc["sample_power"].startswith("有鑑別力")
    assert "already_known" not in pc["is_spec"], u"第一問把後面兩問吃進去了"


# ── JIRA 重驗報告：檔名是「類型＋日期」，沒有主題 ────────────────
def test_JIRA重驗報告不需要topic():
    """★ 2026-08-23：`verify_jira` 跑得很完整卻交不出草稿 ——
    提示沒給格式是一半，另一半是解析器**硬要求 topic**，
    而 JIRA 重驗報告的檔名（`JIRA_Bug驗證報告_<日期>.md`）根本沒有主題可填。"""
    BT = chr(96) * 4
    text = (BT + "\nkind         report\nreport_kind  report\nproduct      crux\n"
            "title        CRUX-963 重驗\nbody         # 報告\n\n內容\n" + BT)
    docs = _mod().parse(text, "crux")["docs"]
    assert len(docs) == 1, docs
    assert docs[0]["report_kind"] == "report"


def test_需求驗證報告仍然要topic():
    """檔名帶主題的那兩種（需求驗證／效能）少了 topic 就不知道要寫成什麼檔。"""
    BT = chr(96) * 4
    text = (BT + "\nkind     report\nproduct  crux\nbody     # 報告\n" + BT)
    assert _mod().parse(text, "crux")["docs"] == []


# ── 欄位對齊造成的縮排不可以吃掉下一個欄位 ─────────────────────
ALIGNED = u"""
````
kind          case
product       crux
title         定盤頁兩彩種玩法分類清單一致
surface       backend
 preconditions 總監2 已登入
steps         1. 導覽 设置>定盘
              2. 切換彩種
expected      6 個分類名稱與順序逐一相同
markers       smoke
pom_hints     BetLimitPage.goto, BetLimitPage.click_lottery
````
"""


def test_對齊的縮排欄位不會被併進上一欄():
    """★ 2026-08-23 實跑：session 為了對齊把 `preconditions` 縮了一格，
    整行被當成 `surface` 的續行 —— `surface` 變成
    「backend\npreconditions 總監2 已登入」，**而且不會報錯**。"""
    c = _mod().parse(ALIGNED, "crux")["cases"][0]
    assert c["surface"] == "backend", repr(c["surface"])
    # ⚠️ 2026-08-26 起是清單（產碼端 `enumerate()` 它，字串會逐字元展開）
    assert c["preconditions"][0].startswith("總監2"), c["preconditions"]


def test_案例的多值欄位會切開():
    c = _mod().parse(ALIGNED, "crux")["cases"][0]
    assert c["markers"] == ["smoke"]


def test_pom_hints只留索引裡真的存在的方法():
    """⛔ 兩件事：形狀要與生成器一致（dict，不是字串 —— 字串會讓產碼當場炸），
    而且**編出來的方法名一律丟掉**（會產出叫不動的程式碼）。"""
    c = _mod().parse(ALIGNED, "crux")["cases"][0]
    for h in c["pom_hints"]:
        assert isinstance(h, dict) and h.get("method"), h
    fake = ALIGNED.replace("BetLimitPage.goto, BetLimitPage.click_lottery",
                           "完全不存在的類別.完全不存在的方法")
    assert _mod().parse(fake, "crux")["cases"][0]["pom_hints"] == []


def test_案例的信心一律標低():
    """session 推導的案例**沒有跑過** —— 標高會讓人略過檢視。"""
    assert _mod().parse(ALIGNED, "crux")["cases"][0]["confidence"] == "low"


def test_步驟的續行不會被當成新欄位():
    c = _mod().parse(ALIGNED, "crux")["cases"][0]
    # 續行要被併進 steps（而不是變成一個新欄位）—— 清單化後自帶的編號會被拿掉
    assert "切換彩種" in c["steps"], c["steps"]


# ── 表頭列：字面清單認不出的變體 ──────────────────────────────
REWORDED = u"""
````
kind     handover
product  crux
section  todo
title    本輪未驗完的三項
why      時間到了
cells    待驗內容 | 為什麼還沒驗 | 下一步
         改分批賠率後對既有注單的影響（是否追溯生效／僅影響新單） | 本輪唯讀 | 下一輪開可寫入
         排列五與七星彩的階數是否與排列三一致 | 需切彩種比對 | 下一輪一併做
````
"""


def test_換個說法的表頭也要丟掉():
    """★ 2026-08-23 實跑第三次撞到：session 把模板的「待辦內容」寫成
    「**待驗內容**」，字面清單認不得 —— 交接檔就多了一列
    `| T66 | 待驗內容 |`，**還佔掉一個永不回收的編號**。

    ⛔ 靠字面清單認表頭必然漏，所以加了結構判準
    （多列時第一列每欄都很短、後面明顯長 → 那是表頭）。
    """
    rows = [d for d in _mod().parse(REWORDED, "crux")["docs"]
            if d.get("section") == "todo"]
    assert len(rows) == 2, [r["cells"] for r in rows]
    firsts = [r["cells"][0] for r in rows]
    assert "待驗內容" not in firsts, u"表頭又漏進去了：%s" % firsts
    assert firsts[0].startswith("改分批賠率")


def test_短資料列不會被誤殺():
    """⚠️ 結構判準的代價 —— 只有「**每一欄都很短**」才判成表頭。"""
    BT = chr(96) * 4
    text = (BT + "\nkind     handover\nproduct  crux\nsection  data\n"
            "title    t\ncells    某個很長的對象描述文字放在這裡 | 總監2 | 已還原 | —\n"
            "         另一個同樣很長的對象描述文字 | 總監3 | 未還原 | CRUX-001\n" + BT)
    rows = [d for d in _mod().parse(text, "crux")["docs"]]
    assert len(rows) == 2, [r["cells"] for r in rows]
