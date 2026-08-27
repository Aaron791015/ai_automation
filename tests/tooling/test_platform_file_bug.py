# -*- coding: utf-8 -*-
"""落單（草稿 → Bug 單）那一段：配號與重現步驟。

為什麼需要這一支
    2026-08-23 走完整條 UI 動線時，落單預覽長這樣：

        配到 CRUX-001（沙箱流水號（取號指令不可用））
        Reproduce Steps：
        1. 1
        2. .
        3.
        4. 總
        5. 監
        …

    兩個缺陷疊在一起，而且**都不會報錯**：

    ⛔ `gen_bug_index.py --next-id` 收的是**權威 id**（`CRUX`），草稿帶的卻是
       平台 slug（`crux`）→ 指令一直失敗 → 平台**靜默退回沙箱流水號** →
       配出 `CRUX-001`，一個早就被用掉的號。
       `CLAUDE.md` §6 第 2、3 條：**ID 永不回收、撞號要靠當下取號避免** ——
       這裡等於自動撞號。
    · `steps` 是一段文字，`compose()` 直接 `enumerate()` → **逐字元**展開。

使用方式：`pytest tests/tooling/test_platform_file_bug.py -q`
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _mod():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from web_ui.api import bugs_file
    return bugs_file


def _a_product():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core.registry import get_registry
    for p in get_registry().products:
        if not p.get("virtual") and p.get("product_id"):
            return p
    return None


# ⛔ **模組層不可以 import 平台的 core** —— 那會在**收集期**把 `sys.modules['core']`
#    綁成平台的 core，於是接著收集 `tests/wbot/perf/` 時，那 12 支的
#    `from core.time_utils import …` 全部 ModuleNotFoundError。
#    後果是**平台的案例索引重建一直失敗、沿用舊快取**（2026-08-24 走查才發現，
#    因為單獨跑 `pytest tests/tooling` 是綠的）。見 test_collect_all_roots.py。
#
# ⛔ **也不要 `import conftest`** —— `tests/wbot/perf/` 也有一支 `conftest.py`，
#    兩者同名，誰先被匯入誰就佔住 `sys.modules['conftest']`。
#    → 這裡就地讀 `config/products.json`（產品定義的單一來源），不依賴任何人。
def _has_product():
    import json as _json
    try:
        _d = _json.load(open(os.path.join(ROOT, "config", "products.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(not p.get("virtual") for p in (_d.get("products") or []))


pytestmark = pytest.mark.skipif(not _has_product(),
                                reason="本工作區還沒接任何產品")


# ── 重現步驟 ────────────────────────────────────────────
def test_一段文字的重現步驟要一步一列而不是逐字元():
    steps = _mod()._as_steps(
        "1. 總監2 排列三，工具箱單筆新增\n2. inline 編輯填 1500\n3. 點「编辑」")
    assert len(steps) == 3, steps
    assert steps[0].startswith("總監2"), u"自帶的編號沒拿掉"
    assert steps[2] == "點「编辑」"


def test_已經是清單的照收():
    assert _mod()._as_steps(["A", " B ", ""]) == ["A", "B"]


def test_組出來的單子步驟是完整句子():
    draft = {"title": "某現象", "product": _a_product()["id"],
             "steps": "1. 開啟設定頁\n2. 填入 abc\n3. 送出",
             "expected": "被擋下", "actual": "寫進去了", "evidence": "API 回應"}
    text = _mod().compose(draft, "CRUX-999", {})
    assert "1. 開啟設定頁" in text
    assert "2. 填入 abc" in text
    assert "\n4. " not in text.split("Test Environment")[0], u"步驟被逐字元展開了"


def test_節序固定為bug_report第四節():
    """★ 讀者要在 10 秒內知道「哪裡錯、應該是多少」——
    所以 Actual／Expect 在前、站台帳號在後。

    ⛔ 2026-08-26 使用者指出 CRUX-115 順序不對：實際產出是
       `Reproduce → Test Environment → Expected → Actual → 佐證 → 開單前三問`，
       環境跑到最前面、Actual/Expect 對調，且開單前三問是**增節**（§4 明訂不得增節）。
    """
    draft = {"title": "某現象", "product": _a_product()["id"],
             "steps": "1. 開啟設定頁", "expected": "被擋下", "actual": "寫進去了",
             "evidence": "shots/X_01.png",
             "prechecks": [{"label": "是規格還是缺陷？", "answer": "缺陷"}]}
    text = _mod().compose(draft, "CRUX-999", {})
    assert "##" not in text, u"貼進 JIRA 會變成一堆字面的井號（那個描述欄不吃 markdown 標題）"
    # ⭐ 節名是**裸行、無 `##`、無冒號** —— 實抓 JIRA 的 CRUX-983／CRUX-969 就是這樣，
    #    而 Bug 單的下游是 JIRA（2026-08-26 使用者指出）。
    want = ["\nReproduce Steps\n", "\nActual result\n", "\nExpect result\n",
            "\n問題截圖\n", "\n【Test Environment】\n", "\n附註\n"]
    at = [text.find(x) for x in want]
    assert all(i >= 0 for i in at), dict(zip(want, at))
    assert at == sorted(at), u"節序不符 bug-report §4：%s" % dict(zip(want, at))


def test_開單前三問壓在附註而不是正文():
    """§4：我方的判斷經過不進正文 —— 但也不能丟掉（它是「為什麼該開」的唯一紀錄）。"""
    draft = {"title": "某現象", "product": _a_product()["id"], "steps": "1. x",
             "expected": "A", "actual": "B",
             "prechecks": [{"label": "樣本有沒有鑑別力？", "answer": "足夠"}]}
    text = _mod().compose(draft, "CRUX-999", {})
    assert "開單前三問" in text, u"丟掉了 —— 那是這張單為什麼該開的唯一紀錄"
    assert text.index("\n附註\n") < text.index("開單前三問"), u"三問跑到正文去了"


def test_run來源的節序也一樣():
    """兩個分支各寫一份節序，**改了一邊漏另一邊**是這種程式碼的常態失效。"""
    draft = {"title": "案例紅燈", "product": _a_product()["id"],
             "nodeid": "tests/x.py::test_y", "run_id": "r1",
             "message": "AssertionError", "console": "logs/a.log"}
    text = _mod().compose(draft, "CRUX-999", {})
    at = [text.find(x) for x in ["\nReproduce Steps\n", "\nActual result\n",
                                 "\nExpect result\n", "\n【Test Environment】\n"]]
    assert all(i >= 0 for i in at) and at == sorted(at), at


# ── JIRA wiki 標記（Bug 單是拿去轉貼 JIRA 的）──────────
def test_粗體轉成單星號():
    """`**x**` 在 JIRA wiki 不是粗體（使用者 2026-08-26 裁示）。"""
    t = _mod()._to_jira("這是 **重點** 而且 **很重要**")
    assert t == "這是 *重點* 而且 *很重要*", t


def test_圍欄轉成code巨集():
    t = _mod()._to_jira("前\n```\nAssertionError\n```\n後")
    assert "{code}\nAssertionError\n{code}" in t, t
    assert "```" not in t


def test_圍欄內的星號不動():
    """⭐ 程式碼裡的 `**` 是次方運算，跟著轉會把它改壞。"""
    t = _mod()._to_jira("```\nassert 2 ** 3 == 8\n```")
    assert "2 ** 3" in t, t


def test_表格分隔行會被吃掉並把表頭轉成雙豎線():
    """⚠️ JIRA 的 `|` 本來就是表格語法 —— `| --- |` 會渲染成一列全是破折號的儲存格。"""
    t = _mod()._to_jira("| 帳號 | 笔数 |\n| --- | --- |\n| a | 5 |")
    assert t.splitlines()[0] == "||帳號||笔数||", t
    assert "---" not in t
    assert t.splitlines()[1] == "| a | 5 |", u"資料列維持單豎線"


def test_frontmatter不會被轉():
    """frontmatter 是 YAML，不是要貼給 JIRA 的內容。"""
    text = _mod().compose({"title": "X", "product": _a_product()["id"],
                           "steps": ["a"], "expected": "**A**", "actual": "B"},
                          "CRUX-999", {})
    fm = text.split("---", 2)[1]
    assert "id: CRUX-999" in fm
    assert "*A*" in text.split("---", 2)[2] and "**A**" not in text


# ── 配號 ────────────────────────────────────────────────
def test_平台slug要轉成權威id才拿得到號():
    """`crux` → `CRUX`。不轉的話取號指令永遠失敗。"""
    p = _a_product()
    assert _mod()._authoritative_id(p["id"]) == p["product_id"]


def test_用slug也要配得到真號():
    """★ 這一條就是那個缺陷的迴歸：以前這裡會回 `CRUX-001`。"""
    bug_id, src = _mod().next_id(_a_product()["id"])
    assert bug_id, src
    assert "gen_bug_index.py" in src, u"又退回自己編號了：%s" % src
    assert not bug_id.endswith("-001"), u"配到 001 幾乎一定是撞號（ID 永不回收）"


def test_取不到號時拒絕開單而不是自己編一個(monkeypatch):
    """⛔ 編出來的號會撞掉別人的單，而且沒有任何警告。"""
    m = _mod()
    monkeypatch.setattr(m, "_real_next_id", lambda product: None)
    bug_id, why = m.next_id(_a_product()["id"])
    assert bug_id == "", u"取號指令壞掉時仍然編了一個號：%s" % bug_id
    assert "不會自己編號" in why or "取不到號" in why


# ── 落單之後還沒做完的事，要講出來 ──────────────────────────
#
# 2026-08-23 實跑「手動開 Bug 單」：session 拍了兩張佐證截圖丟在 **repo 根目錄**，
# 落單流程完全沒提它們 —— 單子引用的檔名指向不存在的位置，
# 事後才會被 lint_bug_assets 抓到「找不到截圖」。

def test_落單會自動搬截圖並回報(monkeypatch):
    """⭐ 2026-08-25 改為**自動搬**（`core/shot_filing.py`）——
    截圖先前是整條動線上唯一要人手動接的環節，兩批都因此掉了。

    ⚠️ 回報裡要講明標記是 `auto`：那代表**平台代搬、標注未經平台驗證**，
       人才知道值得瞄一眼紅框框對地方了沒。"""
    m = _mod()
    monkeypatch.setattr(m, "_file_shots",
                        lambda src, bid, prod, ev: {
                            "moved": ["CRUX-110_01_a.png", "CRUX-110_02_b.png"],
                            "skipped": [], "error": None})
    steps = m._next_steps({"evidence": "a.png、b.png", "nodeid": "t.py::x"},
                          "CRUX-110", "CRUX", {"kind": "session", "id": "s1"})
    joined = "\n".join(steps)
    assert "CRUX-110_01_a.png" in joined and "自動" in joined
    assert "marks=auto" in joined, "沒講來源標記＝人不知道這張沒被驗證過"


def test_自動搬失敗時要給手動補搬的指令(monkeypatch):
    """⛔ 失敗不能只是靜靜地什麼都沒搬 —— 那正是先前掉圖的形狀。"""
    m = _mod()
    monkeypatch.setattr(m, "_file_shots",
                        lambda src, bid, prod, ev: {"moved": [], "skipped": [],
                                                    "error": "目標已存在"})
    joined = "\n".join(m._next_steps(
        {"evidence": "a.png", "nodeid": "t.py::x"},
        "CRUX-110", "CRUX", {"kind": "session", "id": "s1"}))
    assert "目標已存在" in joined and "stamp_shots.py" in joined


def test_沒有回歸案例時要提醒補():
    steps = _mod()._next_steps({"evidence": "", "nodeid": ""}, "CRUX-110", "CRUX")
    assert any("regression" in s for s in steps)


def test_有回歸案例就不再提醒():
    steps = _mod()._next_steps({"evidence": "", "nodeid": "tests/x.py::t"},
                               "CRUX-110", "CRUX")
    assert not any("regression" in s for s in steps)


def test_一律提醒重跑索引():
    steps = _mod()._next_steps({}, "CRUX-110", "CRUX")
    assert any("gen_bug_index" in s for s in steps)


def test_問題截圖節永遠都在():
    """⛔ 先前有 evidence 才輸出這一節 —— **沒拍圖的單連提醒都沒有**。

    缺節是「靜靜地少一塊」：讀者不會發現，開單的人也不會被提示。
    讓它永遠在，等於每張單都問一次「這個缺陷需不需要圖？」
    （使用者 2026-08-26 裁示；與 lint 的 W10 是同一件事，只是提前到寫單當下）
    """
    draft = {"title": "某現象", "product": _a_product()["id"],
             "steps": ["開設定頁"], "expected": "A", "actual": "B"}
    text = _mod().compose(draft, "CRUX-999", {})
    assert "\n問題截圖\n" in text, u"沒圖就整節消失了"
    seg = text.split("問題截圖")[1].split("【Test Environment】")[0]
    assert "待補" in seg, u"沒提醒要補圖"
    assert "no_shot" in seg, u"沒給「真的沒畫面」的出口 —— 那類缺陷會被一直吵"


def test_有圖時不出現待補提醒():
    draft = {"title": "某現象", "product": _a_product()["id"], "steps": ["x"],
             "expected": "A", "actual": "B", "evidence": "shots/CRUX-999_01_x.png"}
    seg = _mod().compose(draft, "CRUX-999", {}).split("問題截圖")[1].split("【Test")[0]
    assert "CRUX-999_01_x.png" in seg and "待補" not in seg, seg
