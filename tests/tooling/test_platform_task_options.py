# -*- coding: utf-8 -*-
"""任務框的動態選項：`options_from` 展開、`/api/tasks/<id>/options/<key>`、
以及「指派給我的 JIRA 單」那一份選單（2026-08-27 使用者要求）。

⭐ 本檔最重要的一條是 `test_除了Done以外不可以依狀態過濾`：`jira-verify` skill §4 明文寫著

    > JIRA 單的 status 不是「能否驗證」的判準，不得據此拒驗或建議延後。

  第一版設計本來想「只列 Resolved」—— 那正好是 skill 禁止的事。
  釘住它，免得日後有人覺得「100 張太多」而加回狀態過濾。

  ★ **唯一的例外是 `Done`**（2026-08-27 使用者裁示）—— 它是流程的終點，不是
    「還沒輪到驗」的中間狀態。而豁免之所以站得住腳，全靠
    `test_Done被擋在選單外_但仍然驗得到` 那一條：**單號欄仍打得進任何值**，
    所以擋掉的是選單的雜訊、不是驗證的權利（CLAUDE.md §7.0）。
    ⚠️ 這條例外**不可以再擴大**：Backlog／In Progress 一旦也被濾掉，
    就真的變成「平台幫你決定哪張不用驗」了。

前置條件：無（不連 JIRA，`_search` 一律注入假的）。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _load(name):
    """⛔ 不在模組層動 `sys.path`（會污染整場 pytest）。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import importlib
    return importlib.import_module(name)


FAKE = [
    {"key": "CRUX-1081", "status": "Backlog", "summary": "彈出 MySQL 例外"},
    {"key": "CRUX-1082", "status": "In Progress", "summary": "貢獻度只回溯一季"},
    {"key": "CRUX-1073", "status": "Resolved", "summary": "出貨賠率被限制在 1000"},
    {"key": "CRUX-1055", "status": "Selected for Development", "summary": "定盤排序錯誤"},
    # ★ 唯一該被濾掉的那一張（大小寫刻意不同 —— JIRA 各站台的寫法不保證一致）
    {"key": "CRUX-1040", "status": "DONE", "summary": "已結案，不該出現在選單"},
]
LIVE = [i for i in FAKE if i["status"].lower() != "done"]


@pytest.fixture
def M(monkeypatch, tmp_path):
    m = _load("core.jira_mine")
    monkeypatch.setattr(m, "_cache_path", lambda: str(tmp_path / "jira_mine.json"))
    monkeypatch.setattr(m, "_search", lambda key: list(FAKE))
    monkeypatch.setattr(m, "_jira_key", lambda pid: "CRUX" if pid == "crux" else None)
    return m


# ────────────────────────────── ★ 最重要的一條

def test_除了Done以外不可以依狀態過濾(M):
    """⛔ `jira-verify` §4：狀態不是能否驗證的判準，不得據此拒驗。

    狀態流轉未必即時反映實際修復進度 —— 濾掉 Backlog／In Progress 就等於
    幫使用者決定了「這幾張不用驗」，那不是平台該做的判斷。
    """
    got = M.mine_for_product("crux")
    keys = [o["value"] for o in got["options"]]
    assert len(keys) == len(LIVE), u"少了幾張 —— 是不是又加了別的狀態過濾？"
    for f in LIVE:
        assert f["key"] in keys, u"%s（%s）被濾掉了" % (f["key"], f["status"])


def test_Done被擋在選單外_但仍然驗得到(M):
    """★ 2026-08-27 使用者裁示：Done 不進選單（那是流程終點，不是還沒驗）。

    ⭐ 這條豁免之所以不牴觸 §4，關鍵在後半段：**單號欄仍打得進任何值** ——
       要回頭複驗一張 Done 的單，照打即可。擋掉的是選單的雜訊，不是驗證的權利。
       所以這裡一併驗「還有別條路」，而不是只驗「濾掉了」。
    """
    got = M.mine_for_product("crux")
    assert "CRUX-1040" not in [o["value"] for o in got["options"]], u"Done 還在選單裡"
    assert "Done" in got["reason"], u"沒說「已略過幾張 Done」—— 人會以為那張單不見了"

    T = _load("core.tasks")
    fields = {f["key"]: f for f in T.get("verify_jira")["fields"]}
    assert fields["tickets"]["type"] == "textarea",         u"單號欄不是自由輸入了 —— Done 的豁免會連「複驗已結案的單」一起擋掉"


def test_大小寫不同的Done也要濾掉(M):
    """⚠️ 各站台的狀態字串大小寫不保證一致（本站是 `Done`，樣本刻意寫 `DONE`）。

    比對寫死大小寫的話，濾網會**看起來有效但實際漏掉** —— 最難察覺的那種壞法。
    """
    assert M._hidden({"status": "done"}) and M._hidden({"status": " Done "})
    assert not M._hidden({"status": "Backlog"}) and not M._hidden({"status": ""})


def test_狀態要顯示出來但只當資訊(M):
    """⭐ skill 說狀態的用途是「解讀結果」—— 所以要看得到，只是不當篩選。"""
    got = M.mine_for_product("crux")
    labels = " ".join(o["label"] for o in got["options"])
    for s in ("Backlog", "In Progress", "Resolved"):
        assert s in labels, u"標籤裡看不到狀態 %s，人就無從解讀" % s
    assert "判準" in got["reason"], u"沒提醒「狀態不是判準」，下次還是有人會想拿它來濾"


# ────────────────────────────── 降級路徑

def test_產品沒有jira專案時要說得出原因(M):
    """⚠️ 七星的 `jira_key` 就是 None —— 這不是故障，是常態。"""
    got = M.mine_for_product("qixing")
    assert got["options"] == []
    assert "jira_key" in got["reason"], u"只給空清單、不說原因 → 人會以為壞了"


def test_連不上jira不可以拋(M, monkeypatch):
    """⛔ 同事可能根本沒有 JIRA —— 任務框要照常打得開。"""
    def boom(key):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(M, "_search", boom)
    got = M.mine_for_product("crux")
    assert got["options"] == []
    assert "手動輸入" in got["reason"], u"沒告訴人還有別條路可走"


def test_有快取就不要每次都問jira(M, monkeypatch):
    calls = []
    monkeypatch.setattr(M, "_search", lambda key: calls.append(key) or list(FAKE))
    M.mine_for_product("crux")
    M.mine_for_product("crux")
    assert len(calls) == 1, u"每次切換產品都重打 JIRA 會很慢"


# ────────────────────────────── 展開與端點

def test_產品選項展開後要拿掉_options_from():
    """⛔ 留著的話前端會再問一次不存在的網址 —— **每開一次任務框噴一個 404**。"""
    A = _load("web_ui.api.tasks_api")
    T = _load("core.tasks")
    R = _load("core.registry")
    got = A._expand_options(T.get("verify_jira"))
    prod = next(f for f in got["fields"] if f["key"] == "product")
    assert "options_from" not in prod, u"沒拿掉 —— 前端會再問一次，那一趟是 404"
    assert "options" in prod, u"沒展開成 options，表單會是空下拉且必填過不了"
    # ⚠️ **不可以直接斷言非空** —— 乾淨範本裡一個產品都還沒接，空的才是對的
    #    （2026-08-27 鏡像驗收當場紅給我看）。要比就跟實際的產品數比。
    real = [p for p in R.get_registry().products if not p.get("virtual")]
    assert len(prod["options"]) == len(real)


def test_jira_mine要給前端一個網址():
    """★ 這一類不能在 `/api/tasks/<id>` 就展開 —— 它要看「現在選了哪個產品」。"""
    A = _load("web_ui.api.tasks_api")
    T = _load("core.tasks")
    got = A._expand_options(T.get("verify_jira"))
    mine = next(f for f in got["fields"] if f["key"] == "mine")
    assert mine["options_from"].get("url", "").endswith("/options/mine")


def test_端點回得出選項而且不會5xx(monkeypatch, tmp_path):
    m = _load("core.jira_mine")
    monkeypatch.setattr(m, "_cache_path", lambda: str(tmp_path / "c.json"))
    monkeypatch.setattr(m, "_search", lambda key: list(FAKE))
    monkeypatch.setattr(m, "_jira_key", lambda pid: "CRUX" if pid == "crux" else None)
    app = _load("web_ui.app").create_app()
    c = app.test_client()
    r = c.get("/api/tasks/verify_jira/options/mine?product=crux")
    assert r.status_code == 200 and len(r.get_json()["options"]) == len(LIVE)
    r2 = c.get("/api/tasks/verify_jira/options/mine?product=qixing")
    assert r2.status_code == 200, u"沒有 JIRA 專案時不可以回 5xx，選單只是輔助"
    assert r2.get_json()["options"] == []


# ────────────────────────────── 表單契約

def test_單號欄位必須仍然打得進任意值():
    """⛔ **不可以把 `tickets` 換成下拉** —— 那會擋掉「驗別人指派的單／剛開的單」。

    選單只是省得手打（CLAUDE.md §7.0：訂「一律不准」之前，先問這條會不會
    連正當用途一起擋掉）。
    """
    T = _load("core.tasks")
    fields = {f["key"]: f for f in T.get("verify_jira")["fields"]}
    assert fields["tickets"]["type"] == "textarea", u"單號欄被換成下拉了"
    assert fields["mine"].get("appends_to") == "tickets", u"挑選器沒有接到單號欄"
    assert fields["product"].get("reload_on_change"), u"換產品不會重查，選單會停在上一個產品"


def test_前端有實作_appends_to():
    """宣告了 `appends_to` 而前端沒實作的話，選了完全沒反應（看不出壞在哪）。"""
    import io
    p = os.path.join(PLATFORM, "web_ui", "static", "js", "ui", "form.js")
    src = io.open(p, encoding="utf-8").read()
    assert "appends_to" in src and "function appendInto" in src
    assert "have.concat(add)" in src, u"沒有去重／追加的實作"


# ────────────────────────────── 兩段式（`prestep`）

def _js(name):
    import io
    return io.open(os.path.join(PLATFORM, "web_ui", "static", "js", "ui", name),
                   encoding="utf-8").read()


def test_verify_jira宣告成兩段式():
    """★ 2026-08-27 使用者：「頁面變得很醜，請改成兩段式」。

    ⭐ 釘的是**宣告**而不是那支任務 —— `prestep` 是通用機制（任何任務都能用），
       寫死成「verify_jira 專屬分支」的話下一個任務又要改一次前端。
    """
    T = _load("core.tasks")
    t = T.get("verify_jira")
    pre = t.get("prestep")
    assert pre and pre.get("field") == "mine", u"沒有宣告 prestep，會退回單一大表單"
    f = next(x for x in t["fields"] if x["key"] == pre["field"])
    assert f.get("appends_to") == "tickets", u"prestep 的欄位沒接到目標欄位 —— 挑完會沒地方放"
    assert (f.get("options_from") or {}).get("source"), u"prestep 的欄位沒有動態選項來源"


def test_prestep宣告的欄位一定要存在():
    """⚠️ 打錯 key 的話第一段會**整個跳過**（`runPrestep` 找不到欄位就直接放行），
    表面上只是「怎麼又變回一頁了」，沒有任何錯誤。"""
    T = _load("core.tasks")
    for t in T.load():
        pre = t.get("prestep")
        if not pre:
            continue
        keys = [f["key"] for f in (t.get("fields") or [])]
        assert pre.get("field") in keys, u"%s 的 prestep 指向不存在的欄位 %s" % (t["id"], pre.get("field"))


def test_前端有實作prestep():
    src = _js("taskprestep.js")
    assert "export function runPrestep" in src
    launcher = _js("tasklauncher.js")
    assert "runPrestep" in launcher and "taskprestep.js" in launcher


def test_取消第一段要整個中止():
    """⛔ 取消後照樣開第二段的話，畫面上看起來像「取消沒有作用」。

    `runPrestep` 用 `null` 表示取消（`{}` 是「這個任務沒有 prestep」）——
    兩者混用就會把取消當成「沒挑東西但要繼續」。
    """
    launcher = _js("tasklauncher.js")
    assert "=== null" in launcher and "return;" in launcher
    assert "onClose" in _js("taskprestep.js"), u"Esc／點背景關掉時不會回 null"


def test_第二段不再顯示挑過的欄位():
    """留著的話同一件事問兩次，而且那個控件是空的 —— 看起來像「剛才選的沒生效」。"""
    launcher = _js("tasklauncher.js")
    assert "task.prestep && f.key === task.prestep.field" in launcher


def test_挑選清單過濾後不可以清掉已勾選的():
    """人常「搜 A 勾一張、再搜 B 勾一張」—— 重畫時不還原的話第一張會無聲消失。"""
    src = _js("taskprestep.js")
    assert "picked.has(c.value)" in src, u"重畫沒有還原勾選狀態"
