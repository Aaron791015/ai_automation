# -*- coding: utf-8 -*-
"""任務啟動器與草稿模式（階段 E，2026-08-23）。

用途：任務按鈕是「平台聚合 × session 創作」的接點。要釘住的是**紀律**，
      不是渲染細節：

      ① ⛔ **`writes: draft` 的任務不給 `Write`／`Edit`／`Bash`** ——
         session 產草稿，**寫檔由平台執行**（`gen_bug_index --next-id` 配號也在那一刻）。
         這是 `core/bug_draft.py` 檔頭那條 2026-08-21 裁示的推廣。
      ② ⛔ **`prompt_template` 點名 skill、不重寫方法論** ——
         抄進 prompt 就會與 skill 分岔（本工作區反覆踩過的「兩份副本」）。
      ③ **內建與自訂分目錄** —— 不分的話，同事加一個自己的任務按鈕，
         `--compare` 就會報一筆他看不懂的差異。
      ④ **`bug_draft` 要 source-agnostic** —— 探索任務沒有 run_id，
         原本 `build(run_id)` 寫死路徑，草稿無處可放。

前置條件：⚠️ 匯入延後到函式內。
使用方式：`pytest tests/tooling/test_platform_tasks.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")
TASKS_DIR = os.path.join(PLATFORM, "tasks")


def _t():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.tasks as T
    return T


# ─────────────────────────────── 模型選擇（2026-08-24）

def _pick():
    # ⚠️ 不要叫 `_api` —— 本檔後段已經有一支同名的（回傳的是模組），
    #    後定義的會蓋掉先定義的，症狀是 `'module' object is not callable`。
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from web_ui.api.tasks_api import pick_model
    return pick_model


def test_人在任務框選的模型優先():
    assert _pick()({"model": "opus"}, {"id": "explore"}) == "opus"


def test_沒選就用任務自己宣告的預設():
    assert _pick()({}, {"id": "explore", "model": "opus"}) == "opus"


def test_都沒有就回None交給config補():
    """⚠️ 不可以在這裡硬塞 'sonnet' —— 預設值的**唯一來源**是
    `platform_config.json` 的 `claude.default_model`（`api_create_session` 讀它）。
    這裡也塞一份，改設定就會有一處改不到。"""
    assert _pick()({}, {"id": "explore"}) is None


def test_空字串當成沒給():
    """⛔ 下拉在極端情況下會送 `""` —— 直接傳下去就是 `--model ""`，
    那是個一定會失敗的命令列，而錯誤訊息只會說「模型無效」。"""
    assert _pick()({"model": ""}, {"id": "explore"}) is None
    assert _pick()({"model": "  "}, {"id": "explore", "model": "opus"}) == "opus"


def test_前端真的有把模型送出去():
    """★ 這一條才是重點：**後端整條線本來就是通的**
    （`launch` → `api_create_session` → `chat.py` 的 `--model`），
    缺的一直是前端只送 `{ values }`、從來沒送過 model ——
    於是「可以選模型」這件事在畫面上不存在，而且不會有任何錯誤訊息。

    這是本平台反覆出現的那一類缺陷（宣告存在、效果不存在），所以直接釘住呼叫端。
    """
    src = io.open(os.path.join(PLATFORM, "web_ui", "static", "js", "ui", "tasklauncher.js"),
                  encoding="utf-8").read()
    assert "{ values, model }" in src, "launch 的 body 沒帶 model"
    assert "data-model" in src, "任務框沒有模型下拉"


# ─────────────────────────────── ③ 內建與自訂

def test_九項內建任務都在():
    T = _t()
    ids = {t["id"] for t in T.load()}
    assert ids >= {"start_day", "explore", "verify_requirement", "write_cases",
                   "verify_jira", "file_bug_from_run", "file_bug", "perf",
                   "handoff_check"}


def test_一天的頭尾各有一支():
    """★ 先前只有收尾體檢 —— 開工只有被動看板，
    而 `handoff` §1 的開工清單有一條**無法按需讀取**：
    「哪些測試資料不能動」沒有任何訊號會提醒你去查（2026-08-23 補）。"""
    T = _t()
    start = T.get("start_day")
    assert start and start.get("order") == 0, u"開工要排在最前面"
    tpl = start["prompt_template"]
    assert "blocker" in tpl and "測試資料" in tpl and "可立即動手" in tpl
    assert "{findings}" in tpl, u"沒帶入平台的跨 session 發現"
    assert not (start.get("allowed_tools") or []), u"開工只是讀與判斷，不該給站台工具"


def test_內建與自訂分目錄且自訂可覆蓋(tmp_path, monkeypatch):
    """同 id 時自訂覆蓋內建 —— 讓人能改內建任務而不必改範本。"""
    T = _t()
    d, c = str(tmp_path / "tasks"), str(tmp_path / "tasks" / "custom")
    os.makedirs(c)
    io.open(os.path.join(d, "a.json"), "w", encoding="utf-8").write(
        json.dumps({"id": "a", "label": "內建"}, ensure_ascii=False))
    io.open(os.path.join(c, "a.json"), "w", encoding="utf-8").write(
        json.dumps({"id": "a", "label": "我改的"}, ensure_ascii=False))
    io.open(os.path.join(c, "b.json"), "w", encoding="utf-8").write(
        json.dumps({"id": "b", "label": "我自己加的"}, ensure_ascii=False))
    monkeypatch.setattr(T, "TASKS_DIR", d)
    monkeypatch.setattr(T, "CUSTOM_DIR", c)

    got = {t["id"]: t for t in T.load()}
    assert got["a"]["label"] == "我改的" and got["a"]["builtin"] is False
    assert got["b"]["builtin"] is False


def test_custom不匯出而內建要匯出():
    """★ 範本化歸屬：內建是通用層（該同步），自訂是個人層（不同步）。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import export_template as E
    p = E.product_paths(E.ROOT)
    assert E.classify("tools/test_platform/tasks/explore.json", p) == "export"
    assert E.classify("tools/test_platform/tasks/custom/我的.json", p) == "never"


# ─────────────────────────────── ① 草稿模式的權限紀律

def test_寫入型任務不給寫檔工具():
    """⛔ session 產草稿，寫檔由平台執行 —— 給了 Write 就繞過確認與配號。"""
    T = _t()
    for t in T.load():
        tools = set(t.get("allowed_tools") or [])
        bad = tools & {"Write", "Edit", "Bash", "PowerShell", "NotebookEdit"}
        assert not bad, "%s 放行了寫入／shell 工具：%s" % (t["id"], bad)


def test_寫入型任務的提示要明講不能寫repo的檔():
    """⭐ 要講「不能寫 **repo 裡的檔案**」，不是籠統的「不能寫檔」。

    2026-08-23：探索任務原本寫「⛔ 你不能寫檔」，session 把它連同站台操作
    一起解讀成「什麼都不能改」，於是全程唯讀 —— **兩種寫入是不同的東西**，
    提示裡就得分開講。
    """
    T = _t()
    for t in T.load():
        if t.get("writes") != "draft":
            continue
        # ⭐ `write_cases` 是例外：案例要**邊寫邊跑**就得寫進 `tests/<產品>/`
        #    （寫別處拿不到 conftest 的 fixture，根本跑不起來）。
        #    使用者 2026-08-26 裁示比照終端機 session。它另有專屬測試（見下）。
        if t["id"] == "write_cases":
            continue
        tpl = t.get("prompt_template", "")
        assert "不能寫 repo 裡的檔案" in tpl or "不能寫檔" in tpl,             "%s 沒告訴 session 它不能寫 repo 的檔" % t["id"]
    # 會操作站台的兩支要**明確把站台排除在外**
    for tid in ("explore", "verify_requirement"):
        tpl = T.get(tid)["prompt_template"]
        assert "不能寫 repo 裡的檔案" in tpl, tid
        assert "站台的操作不在此限" in tpl,             "%s 沒把「站台寫入」與「寫 repo 檔案」分開講" % tid


def test_開單型任務要走開單前三問且不自己配號():
    """★ Bug ID 永不回收 —— 配號一定要在人按開單那一刻。"""
    T = _t()
    for tid in ("file_bug", "file_bug_from_run"):
        tpl = T.get(tid)["prompt_template"]
        assert "三問" in tpl, "%s 沒要求走開單前三問" % tid
        assert "配號" in tpl, "%s 沒禁止自己配號" % tid


def test_探索任務的安全邊界不含STG():
    """⛔ STG 已交客戶試用，需逐次授權（CLAUDE.md §5）—— 不該出現在下拉選單裡。"""
    T = _t()
    f = next(x for x in T.get("explore")["fields"] if x["key"] == "boundary")
    vals = {o["value"] for o in f["options"]}
    assert "stg" not in vals and not any("STG" in o["label"] for o in f["options"])


# ─────────────────────────────── ② 點名 skill 而非重寫方法論

def test_每個任務都點名了skill():
    T = _t()
    for t in T.load():
        assert t.get("skills"), "%s 沒有指定 skill" % t["id"]
        for s in t["skills"]:
            assert os.path.isdir(os.path.join(ROOT, ".claude", "skills", s)), \
                "%s 指向不存在的 skill：%s" % (t["id"], s)


def test_案例開發的紀律要在skill裡而不是散在提示():
    """★ 規則的**單一來源**是 `ui-test` skill —— 平台任務與終端機 session 都讀它。

    ⛔ 抄一份到提示裡就會漂：平台改了、終端機沒改，同一件事兩套答案。
       使用者 2026-08-26：「補 Bug 回歸案例的時候，也需要使用同一套案例撰寫規則」。
    """
    md = io.open(os.path.join(ROOT, ".claude", "skills", "ui-test", "SKILL.md"),
                 encoding="utf-8").read()
    # 紅燈兩種（最重要的一條）
    assert "紅燈有兩種" in md, u"skill 沒講紅燈可能是「案例對、系統錯」"
    assert "不准動判準" in md, u"skill 沒禁止把抓到缺陷的案例改成綠"
    assert "本來就該是紅的" in md, u"skill 沒講回歸案例在缺陷修好前該是紅的"
    # 整檔跑兩次
    assert "整檔跑兩次" in md, u"skill 沒要求整檔跑兩次"
    assert "互相影響" in md and "反覆執行" in md, u"skill 沒說兩次各抓什麼"


def test_撰寫案例的提示要指到skill而不是自己抄一份():
    """⭐ 提示留指標就好；規則本體在 skill（見上一條）。"""
    tpl = next(x for x in _t().load() if x["id"] == "write_cases")["prompt_template"]
    assert "階段 2.6" in tpl and "階段 2.7" in tpl, u"提示沒指到 skill 的章節"


def test_撰寫案例要講明紅燈有兩種且不准把FAIL改成PASS():
    """⛔⛔ 這是使用者 2026-08-26 特別提醒的一條，也是放寬長度上限的代價。

    把一條抓到缺陷的案例改成 PASS，等於**用測試把 bug 合法化** ——
    `CLAUDE.md` 明列那是測試工作最嚴重的失誤型態，而且傷害會擴散：
    之後沒有人會再去驗它。
    """
    tpl = next(x for x in _t().load() if x["id"] == "write_cases")["prompt_template"]
    assert "抓到缺陷" in tpl, u"沒告訴它紅燈可能是「案例對、系統錯」"
    assert "不准動判準" in tpl or "不准改判準" in tpl, u"沒禁止它把判準改到綠"
    assert "known_fail" in tpl, u"沒給它「這條本來就該紅」的登記處"


def test_撰寫案例要求整檔跑兩次():
    """★ 逐條跑抓不到互相影響，跑一次抓不到「不可反覆執行」。"""
    tpl = next(x for x in _t().load() if x["id"] == "write_cases")["prompt_template"]
    assert "整檔跑兩次" in tpl or "跑兩次" in tpl, u"沒要求整檔跑兩次"
    assert "互相影響" in tpl, u"沒說第一次是為了抓什麼"
    assert "反覆執行" in tpl, u"沒說第二次是為了抓什麼"
    assert "case_run" in tpl, u"沒有回報整檔結果的區塊 —— 平台就查不到它跑了沒"


def test_撰寫案例要求一條一條寫一條一條跑():
    """★ 這是 `write_cases` 取代「不能寫 repo」的那條規則 —— 不能兩條都沒有。

    ⛔ 整批寫完才跑 ≠ 邊寫邊測：前者錯了要再開一輪對話，後者當場修。
    """
    t = next(x for x in _t().load() if x["id"] == "write_cases")
    tpl = t.get("prompt_template", "")
    assert "tests/{product}/" in tpl, u"沒告訴它寫去哪"
    assert "pytest" in tpl, u"沒給它跑測試的指令"
    assert "綠了再寫下一條" in tpl or "一條一條" in tpl, u"沒講「邊寫邊跑」"
    assert "wrote" in tpl, u"沒要它回報寫在哪 —— 平台就不知道要驗收哪個檔"


def test_提示裡有引用skill的章節而不是抄內容():
    """抄進 prompt 就會與 skill 分岔。抽驗：提示應短，且帶 § 章節指標。

    ⚠️ **不算 fenced 區塊** —— 那些是草稿的**欄位契約**（平台照著解析），
       不是方法論；它們本來就得逐字寫，而且與 skill 不會分岔
       （2026-08-23：探索加了「測試資料」草稿、又新增需求驗證任務之後，
        原本的字數上限開始抓錯東西）。
    """
    import re
    T = _t()
    for t in T.load():
        tpl = re.sub(r"```.*?```", "", t.get("prompt_template", ""), flags=re.S)
        # 2026-08-23 由 1200 放寬到 1500：移除時間盒後補進「範圍由區塊／需求界定」
        # 那幾句 —— 那是**紀律**不是方法論，但確實佔字數。
        #
        # ⭐ `write_cases` 2026-08-26 放寬到 1900：它比別的任務多背了
        #    「案例交出去之前要做什麼」那一段。
        #    ⚠️ 規則**本體不在這裡** —— 在 `ui-test` skill 的階段 2.6／2.7，
        #       提示只留指標（那正是本測試的名字在講的事）。
        #       規則的釘子在 `test_案例開發的紀律要在skill裡而不是散在提示`。
        cap = 1900 if t["id"] == "write_cases" else 1500
        assert len(tpl) < cap, "%s 的提示過長（%d），可能把方法論抄進來了" % (t["id"], len(tpl))


# ─────────────────────────────── 渲染

def test_缺欄位填未填而不是留佔位():
    """模板漏字會讓 session 看到半句話，比明講「沒填」更糟。"""
    T = _t()
    r = T.render(T.get("explore"),
                 {"product": "CRUX", "area": "X", "boundary": "readonly"},
                 product_skill="crux")
    # ⚠️ 判準是「有沒有**沒被替換的佔位符**」，不是「有沒有大括號」——
    #    提示裡現在帶了一段 JS 範例（`{ window.__annotate = … }`、`{selector:"…"}`），
    #    那些不是佔位符。`_placeholders` 認的是 `{\\w+}`，兩者不會相撞
    #    （2026-08-25 加截圖三步驟時這條測試紅了，正好證明它守到了該守的邊界）。
    import re as _re
    left = _re.findall(r"\{(\w+)\}", r["prompt"])
    assert not left, "有未替換的佔位符：%s" % left
    assert "（未填）" in r["prompt"]


def test_安全邊界會翻成人看得懂的字():
    T = _t()
    r = T.render(T.get("explore"), {"boundary": "write"})
    assert "可寫入 QAT" in r["prompt"]


# ─────────────────────── ★ 安全邊界要是**條款**，不是一個標籤
#
# 2026-08-23 實跑抓到的：session 拿到「安全邊界：可寫入 QAT」五個字之後**仍然全程唯讀** ——
# 它讀了 CLAUDE.md §5 裡「執行前先說明會做什麼」那一類句子，而它**問不到人**，
# 於是選了最保守的解釋。結果整場探索只驗得到讀得出來的東西，
# 一條會改狀態的規則都沒驗到 —— 而金流邏輯全在那一側。

def _write_prompt(task_id="explore"):
    T = _t()
    return T.render(T.get(task_id), {"product": "X", "area": "A", "topic": "T",
                                     "source": "S", "requirement": "R",
                                     "boundary": "write"})["prompt"]


def test_可寫入時要明講已預先授權且不必請示():
    p = _write_prompt()
    assert "預先授權" in p, u"沒講授權，session 會自己降級成唯讀"
    assert "請示" in p and "沒有人能回答" in p


def test_可寫入時仍要擋住三種操作():
    """放寬的是 QAT 的 Web／UI —— DB、波及他人的操作、他人的資料都不放。"""
    p = _write_prompt()
    assert "DB 一律唯讀" in p
    for word in ("一键结账", "反結算", "關盤"):
        assert word in p, u"沒擋住會波及其他 session 的操作：%s" % word
    assert "不動他人的測試資料" in p


def test_可寫入時要求還原但開單的資料要保留():
    """⛔ 據以開單的資料還原掉，單子就不可重現（CLAUDE.md §5 第 1 條例外）。"""
    p = _write_prompt()
    assert "用完即還原" in p
    assert "保留不還原" in p


def test_可寫入時一定要交測試資料草稿():
    """動過站台卻沒登記，等於沒有人知道你動過什麼。"""
    p = _write_prompt()
    assert "section data" in p or "section  data" in p


def test_唯讀時不可以硬猜結論():
    T = _t()
    p = T.render(T.get("explore"), {"boundary": "readonly"})["prompt"]
    assert "本次唯讀" in p
    assert "不要硬猜結論" in p
    assert "Web／UI 寫入已預先授權" not in p, u"唯讀卻帶了寫入授權條款"


def test_探索預設就是可寫入():
    """⭐ 預設唯讀＝預設驗不到東西。"""
    T = _t()
    f = next(x for x in T.get("explore")["fields"] if x["key"] == "boundary")
    assert f["default"] == "write"


# ─────────────────────── ★ 需求驗證：本工作區最嚴重的失誤型態要擋在提示裡

def test_需求驗證要有權威規格來源():
    T = _t()
    keys = {f["key"]: f for f in T.get("verify_requirement")["fields"]}
    assert keys["source"]["required"], u"沒有規格來源就判不了 FAIL，那是探索不是驗證"
    assert keys["requirement"]["required"]
    assert keys["topic"]["required"], u"報告檔名要用它"


def test_需求驗證要擋住把缺陷改寫成規格():
    """⛔ CLAUDE.md 明列為最嚴重的失誤型態 —— 平台起的 session 無人看管，更要擋。"""
    tpl = _t().get("verify_requirement")["prompt_template"]
    assert "有沒有人說要改" in tpl
    assert "不要改任何文件" in tpl
    assert "缺陷" in tpl and "FAIL" in tpl


def test_需求驗證不確定不可以判PASS():
    tpl = _t().get("verify_requirement")["prompt_template"]
    assert "BLOCKED" in tpl
    assert "不可以寫 PASS" in tpl


def test_需求驗證的報告不自己拼檔名():
    """`bugs/_reports/` 撞名會覆蓋，而那一層不版控（CLAUDE.md §6 第 4 條）。"""
    tpl = _t().get("verify_requirement")["prompt_template"]
    assert "不要自己拼檔名" in tpl
    assert "new_bug_doc.py" in tpl


def test_render帶出context供session追溯():
    T = _t()
    r = T.render(T.get("verify_jira"), {"product": "CRUX", "tickets": "CRUX-1"})
    assert r["context"]["task"] == "verify_jira"
    assert r["context"]["product"] == "CRUX"


def test_收尾體檢的發現不會炸也不會空():
    """資料來源全部現成 —— 任何一個壞掉都不該讓按鈕不能用。"""
    T = _t()
    s = T.findings_for_handoff()
    assert isinstance(s, str) and s.strip().startswith("·")


# ─────────────────────────────── ④ bug_draft 泛化

def test_草稿支援session來源(tmp_path, monkeypatch):
    """★ 探索任務沒有 run_id —— 原本 `build(run_id)` 寫死路徑，草稿無處可放。"""
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.bug_draft as B
    monkeypatch.setattr(B.paths, "SESSIONS_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(B.paths, "RUNS_DIR", str(tmp_path / "r"))
    src = {"kind": "session", "id": "sid1"}
    B.save(src, {"drafts": [{"signature": "s1", "title": "探索發現的缺陷"}]})
    assert B.read(src)["drafts"][0]["title"] == "探索發現的缺陷"
    assert [d["title"] for d in B.read_all()] == ["探索發現的缺陷"]


def test_開單後不再出現在待開單清單(tmp_path, monkeypatch):
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.bug_draft as B
    monkeypatch.setattr(B.paths, "SESSIONS_DIR", str(tmp_path / "s"))
    monkeypatch.setattr(B.paths, "RUNS_DIR", str(tmp_path / "r"))
    src = {"kind": "session", "id": "sid1"}
    B.save(src, {"drafts": [{"signature": "s1", "title": "X"}]})
    B.mark_filed(src, "s1", "CRUX-999")
    assert B.read_all() == []
    assert B.read(src)["drafts"][0]["filed_as"] == "CRUX-999"


def test_read_all同時掃兩種來源(tmp_path, monkeypatch):
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.bug_draft as B
    runs, sess = str(tmp_path / "r"), str(tmp_path / "s")
    os.makedirs(os.path.join(runs, "run1"))
    io.open(os.path.join(runs, "run1", B.DRAFT_FILE), "w", encoding="utf-8").write(
        json.dumps({"drafts": [{"signature": "a", "title": "run 來的"}]}, ensure_ascii=False))
    monkeypatch.setattr(B.paths, "RUNS_DIR", runs)
    monkeypatch.setattr(B.paths, "SESSIONS_DIR", sess)
    B.save({"kind": "session", "id": "s1"},
           {"drafts": [{"signature": "b", "title": "探索來的"}]})
    titles = sorted(d["title"] for d in B.read_all())
    assert titles == ["run 來的", "探索來的"]
    kinds = {d["source"]["kind"] for d in B.read_all()}
    assert kinds == {"run", "session"}


# ═══════ 第二輪對齊檢查（驗語意而非存在）抓到的三個缺口 ═══════
#
# 前一輪只驗「檔案／符號在不在」，三項都「過」了 —— 但東西在、功能沒接通。

class TestTaskEntryPointsAreWired:
    """★ 每個 task 宣告的 `entry`，對應的 view 必須真的渲染任務列。

    迴歸：`file_bug_from_run.json` 宣告 `entry: ["run"]`、`tasklauncher` 也會依
    entry 過濾，但 **`views/run.js` 從來沒呼叫 `renderTaskBar`** ——
    於是計畫 E-1 表上那顆「從失敗 run 開單」**根本出不來**。

    這正是存在性檢查看不到的缺口：task 檔在、元件在、過濾邏輯在，
    只差沒有人把它掛上去。
    """

    VIEW_OF = {"overview": "overview.js", "product": "product.js", "run": "run.js"}

    def _declared_entries(self):
        import glob
        import io as _io
        import json as _json
        out = set()
        for p in glob.glob(os.path.join(ROOT, "tools/test_platform/tasks/*.json")):
            for e in (_json.load(_io.open(p, encoding="utf-8")).get("entry") or []):
                out.add(e)
        return out

    def test_每個宣告的entry都有view在渲染(self):
        import io as _io
        entries = self._declared_entries()
        assert entries, "沒有任何 task 宣告 entry"
        missing = []
        for e in sorted(entries):
            fn = self.VIEW_OF.get(e)
            assert fn, "未知的 entry：%s（VIEW_OF 要同步更新）" % e
            src = _io.open(os.path.join(
                ROOT, "tools/test_platform/web_ui/static/js/views", fn),
                encoding="utf-8").read()
            if "renderTaskBar" not in src:
                missing.append("%s → %s" % (e, fn))
        assert not missing, "這些 entry 宣告了卻沒有 view 在渲染：%s" % missing

    def test_run頁把run上下文帶給任務(self):
        """「從失敗 run 開單」要能自動帶入 nodeid 與錯誤訊息（計畫 E-1）。"""
        import io as _io
        src = _io.open(os.path.join(
            ROOT, "tools/test_platform/web_ui/static/js/views/run.js"),
            encoding="utf-8").read()
        assert "entry: 'run'" in src
        # ⚠️ 不能用 split("renderTaskBar")[1] —— 那會抓到 **import** 那次出現，
        #    不是呼叫處（第一版就這樣誤判了）。改看 `entry: 'run'` 附近。
        near = src[src.index("entry: 'run'"):][:500]
        assert "failed_cases" in near, "run 頁沒把失敗案例帶進任務的 ctx"
        assert "run_id" in near, "run 頁沒把 run_id 帶進任務的 ctx"


class TestPrechecksVisible:
    """★ 計畫 E-1c：草稿要**保留開單前三問的答案**，讓人一眼看出它為什麼判定該開。

    先前 `save()` 收任意 dict，session 可以塞三問，但**沒有定義欄位、
    前端也不顯示** —— 等於沒交付。判準是「人在開單前看不看得到那三個答案」。
    """

    def test_三問有固定形狀(self):
        from core.bug_draft import PRECHECK_QUESTIONS
        assert len(PRECHECK_QUESTIONS) == 3
        keys = {q["key"] for q in PRECHECK_QUESTIONS}
        assert keys == {"is_spec", "already_known", "sample_power"}

    def test_沒答的要留空欄位而不是消失(self):
        """看得到「它沒答」比看不到這件事重要。"""
        from core.bug_draft import normalize_prechecks
        out = normalize_prechecks(None)
        assert len(out) == 3
        assert all(q["answer"] == "" for q in out)

    def test_list與dict兩種形狀都收(self):
        from core.bug_draft import normalize_prechecks
        a = normalize_prechecks({"is_spec": "是缺陷"})
        b = normalize_prechecks([{"key": "is_spec", "answer": "是缺陷"}])
        assert a[0]["answer"] == b[0]["answer"] == "是缺陷"

    def test_save會正規化每一筆草稿(self, tmp_path, monkeypatch):
        from core import bug_draft
        monkeypatch.setattr(bug_draft, "_dir_of", lambda src: str(tmp_path))
        data = bug_draft.save({"kind": "session", "id": "s1"},
                              {"drafts": [{"signature": "x", "title": "t"}]})
        assert data["drafts"][0]["prechecks"], "save 沒有正規化 prechecks"

    def test_開單頁真的顯示三問(self):
        import io as _io
        src = _io.open(os.path.join(
            ROOT, "tools/test_platform/web_ui/static/js/views/run.js"),
            encoding="utf-8").read()
        assert "prechecksBlock" in src
        assert "未回答" in src, "沒答的題目沒有標示出來"


class TestHandoffFindings:
    """★ 收尾體檢的自動發現要讀對欄位。

    迴歸：讀 `b.get("text")` 但 blocker 的欄位其實是 `what`／`who`／`impact`
    —— 於是每一條都印成「blocker：」空字串，而**沒有任何錯誤**。
    """

    def test_blocker讀得到實際內容(self):
        from core.tasks import findings_for_handoff
        out = findings_for_handoff()
        for line in out.splitlines():
            if "blocker：" in line:
                tail = line.split("blocker：", 1)[1].strip()
                assert tail, "blocker 印成空字串：%r" % line

    def test_工具名沒有印成None(self):
        from core.tasks import findings_for_handoff
        assert "：None（" not in findings_for_handoff()

    def test_launch會把發現帶進去(self):
        import inspect
        import web_ui.api.tasks_api as m
        assert "findings_for_handoff" in inspect.getsource(m)


# ─────────────────────────────── ⑤ 產品下拉真的填得出選項

def _api():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.api.tasks_api as A
    return A


def test_宣告了products的欄位一定要展開成options():
    """★ 核心迴歸：`options_from: {source: "products"}` 沒人展開的話，
    表單上是**空的下拉**，而「產品」是必填 → **任務永遠按不下去**，
    而且畫面上看不出原因。

    （2026-08-23 範本端到端驗收：五支內建任務全中。先前的驗收是用 API
    直接送 values，正好繞過這個下拉。）
    """
    T, A = _t(), _api()
    from core.registry import get_registry
    # ⚠️ 乾淨的範本還沒接產品 —— 那不是缺陷，是它的正常狀態。
    #    （寫死「一定要有選項」的話，同事第一次跑 pytest 就看到紅燈。）
    has_products = any(not p.get("virtual") for p in get_registry().products)
    checked = 0
    for task in T.load():
        for f in task.get("fields") or []:
            if (f.get("options_from") or {}).get("source") != "products":
                continue
            checked += 1
            got = A._expand_options(task)
            ef = next(x for x in got["fields"] if x["key"] == f["key"])
            assert "options" in ef, (
                u"任務 %s 的欄位 %s 沒有被展開 —— 前端只讀 f.options，這顆按鈕按不下去"
                % (task["id"], f["key"]))
            if has_products:
                assert ef["options"], u"工作區有產品，展開後卻是空的：%s" % task["id"]
            for o in ef["options"]:
                assert o.get("value") and o.get("label"), o
    assert checked, u"沒有任何任務宣告 source=products —— 這條測試失去意義，請確認宣告還在"


def test_展開不會動到原始task():
    """`T.get()` 回的是快取物件 —— 就地改會污染下一次讀取。"""
    T, A = _t(), _api()
    task = next(t for t in T.load()
                if any((f.get("options_from") or {}).get("source") == "products"
                       for f in t.get("fields") or []))
    A._expand_options(task)
    f = next(x for x in task["fields"]
             if (x.get("options_from") or {}).get("source") == "products")
    assert not f.get("options"), u"展開時就地改到了原始 task"


def test_只有一個產品時自動選好():
    """少一次「沒有選擇的選擇」—— 範本剛接第一個產品時就是這個情境。"""
    T, A = _t(), _api()
    from core.registry import get_registry
    real = [p for p in get_registry().products if not p.get("virtual")]
    task = next(t for t in T.load()
                if any((f.get("options_from") or {}).get("source") == "products"
                       for f in t.get("fields") or []))
    got = A._expand_options(task)
    f = next(x for x in got["fields"]
             if (x.get("options_from") or {}).get("source") == "products")
    if len(real) == 1:
        assert f.get("default") == real[0]["id"]
    else:
        assert len(f["options"]) == len(real)


# ─────────────────────────────── ⑥ 草稿來源的向後相容

def _bd():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import bug_draft
    return bug_draft


def test_草稿來源吃得下run_id字串():
    """★ 迴歸：E-1c 把來源泛化成 `{kind, id}` 之後，`_dir_of()` 的第一行
    `.get("kind")` 會對字串丟 `AttributeError` —— 而 `web_ui/api/bugs_file.py`
    正是傳字串進來的。

    症狀是 run 結果頁的 `bug-drafts` 端點 **500**，
    「從失敗 run 開單」整條動線直接斷掉，而且畫面上只是「開單（0）」看不出原因
    （2026-08-23 範本端到端驗收第 ⑧ 步）。
    """
    B = _bd()
    d1 = B._dir_of("20990101_000000_probe")
    d2 = B._dir_of({"kind": "run", "id": "20990101_000000_probe"})
    assert d1 == d2, u"字串與 dict 兩種來源必須指到同一個目錄"


def test_讀不存在的草稿回空dict而不是炸掉():
    B = _bd()
    assert B.read("20990101_000000_probe") == {}


def test_bugs_file的呼叫方式真的行得通():
    """直接照 `web_ui/api/bugs_file.py` 的用法呼叫一次 —— 型別對不上就會紅。"""
    B = _bd()
    src = io.open(os.path.join(PLATFORM, "web_ui", "api", "bugs_file.py"),
                  encoding="utf-8").read()
    assert "bug_draft.read(run_id)" in src, u"呼叫方式變了，請同步更新本測試"
    B.read("20990101_000000_probe")          # 不可丟例外


# ─────────────────────────────── ⑦ 開單模板不得編造

def _compose():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from web_ui.api.bugs_file import compose
    return compose


def test_探索來源不得產出run的重現步驟():
    """★ 核心迴歸：模板原本假設草稿一定來自 run，於是探索發現的缺陷會落成 ——

        1. 執行 `None` 的「執行案例」，環境 QAT。
        2. 只勾選這一條案例：`None`。
        Expected：案例通過。　Actual：案例失敗…

    ⛔ **Reproduce Steps 是 Bug 單最重要的一段** —— RD 照著走只會困惑，
       而「案例失敗」對一個規格缺陷根本不成立（2026-08-23 走查發現）。
    """
    compose = _compose()
    text = compose({"title": "倍率缺一列", "product": "樂透", "module": "派彩"},
                   "LOTTO-009", {})
    for forbidden in ("只勾選這一條案例", "案例通過", "案例失敗", "None"):
        assert forbidden not in text, u"探索來源的單出現了 run 專屬敘述：%s" % forbidden
    assert "待補" in text, u"沒有的資訊要明講「待補」，不可靜靜地留白"


def test_探索來源用草稿自己的欄位():
    compose = _compose()
    text = compose({
        "title": "倍率缺一列", "product": "樂透", "module": "派彩",
        "steps": ["開設定頁", "刪掉一列", "回前台對獎"],
        "expected": "應擋下", "actual": "靜默取 0",
        "evidence": ["截圖 a.png"],
        "prechecks": [{"key": "is_spec", "label": "是規格還是缺陷？", "answer": "缺陷"}],
    }, "LOTTO-009", {})
    assert "1. 開設定頁" in text and "3. 回前台對獎" in text
    # ⚠️ 2026-08-26 起順序改為 §4 的 Actual → Expect（原本 Expected 排在 Actual 前面），
    #    節名是**裸行、無冒號**（對齊 JIRA，實抓 CRUX-983／969）。節序另有專屬測試。
    assert "\nExpect result\n\n應擋下" in text and "\nActual result\n\n靜默取 0" in text
    assert "截圖 a.png" in text
    assert "開單前三問" in text and "缺陷" in text
    # ⚠️ 只看**正文** —— frontmatter 的 `regression: ⚠️ 待補` 是刻意的：
    #    探索發現的缺陷本來就還沒有回歸案例，而 CLAUDE.md 要求那一欄不可留白
    #    （「沒填就補，或標明為何補不了」）。
    # ⚠️ 排除【Test Environment】—— 2026-08-26 起它會在**查不到站台**時提醒補 URL 與帳密，
    #    而這個 draft 本來就沒有站台資訊（樂透、步驟是「開設定頁／填入 abc」），
    #    那個提醒是對的。本條守的是「steps／actual／expected／evidence 有給就不要寫待補」。
    body = text.split("---", 2)[-1].split("【Test Environment】")[0]
    assert "待補" not in body, u"欄位齊全時正文不該再出現「待補」"


def test_環境段落查不到站台就要提醒補():
    """⭐ RD 沒有 URL 與帳密就重現不了 —— 那是這張單最實際的失效方式。"""
    compose = _compose()
    text = compose({"title": "X", "product": "樂透", "steps": ["開設定頁"],
                    "expected": "A", "actual": "B"}, "LOTTO-009", {})
    env = text.split("【Test Environment】")[1]
    assert "站台 URL 與帳密待補" in env, env[:200]


def test_步驟裡有站台就把URL與帳密展開():
    """⚠️ 只在真的缺的時候提醒 —— 恆常出現的提醒等於沒有提醒。"""
    compose = _compose()
    cfg = json.load(io.open("config/environments.json", encoding="utf-8"))
    if "director2" not in ((cfg.get("crux") or {}).get("qat") or {}):
        pytest.skip("本工作區沒有 crux/qat/director2")
    text = compose({"title": "X", "product": "CRUX",
                    "steps": ["總監2 後台 设置 > 赔率变动设置，排列三 26097"],
                    "expected": "A", "actual": "B"}, "CRUX-999", {})
    env = text.split("【Test Environment】")[1].split("附註")[0]
    assert "待補" not in env, env
    assert "後台：" in env and "http" in env, env


def test_run來源維持原本的敘述():
    """⛔ 分流不可以把 run 那條動線改壞 —— 那套敘述對 run 是準確的。"""
    compose = _compose()
    text = compose({
        "title": "對獎截短", "product": "樂透", "module": "開獎",
        "nodeid": "tests/lotto/test_x.py::test_y", "run_id": "20260823_000000_ui_tests",
        "tool_name": "UI 自動化測試", "message": "AssertionError",
    }, "LOTTO-009", {})
    assert "只勾選這一條案例" in text and "tests/lotto/test_x.py::test_y" in text
    assert "自動化執行" in text


def test_探索草稿的欄位規格有寫進prompt():
    """平台照欄位組單 —— session 不知道要交哪些欄位的話，開單就只剩「待補」。"""
    T = _t()
    for tid in ("explore", "file_bug"):
        tpl = (T.get(tid) or {}).get("prompt_template", "")
        for key in ("steps", "expected", "actual", "evidence", "prechecks"):
            assert key in tpl, u"任務 %s 的 prompt 沒告訴 session 要交 %s" % (tid, key)


# ─────────────────────── 任務 session 的執行紀律前言

def test_每個任務的prompt都帶執行紀律前言():
    """★ 核心迴歸：session 停下來要「批准」，而平台這一側沒有人能回答。

    2026-08-23 範本驗收實測：按「探索新功能」→ 第一則回覆是
    「Please approve the tool call so I can continue」，任務就停在那裡。
    工具**本來就在白名單裡**（照原樣重現 argv，瀏覽器開得起來）——
    它只是不知道自己是 headless 起的。

    前言放在 `render()`（唯一組裝點），所以**每個**任務都該有。
    """
    tasks = _t()
    all_tasks = tasks.load()
    assert all_tasks, u"一個任務都沒載到"
    for tk in all_tasks:
        out = tasks.render(tk, {"product": "crux"}, product_skill="crux")
        p = out["prompt"]
        assert u"不要停下來請求批准" in p, u"%s 缺「不要停下來請求批准」" % tk["id"]
        assert u"這一側沒有人能回答" in p, u"%s 缺「沒有人能回答」" % tk["id"]
        assert u"繁體中文" in p, u"%s 缺語言要求" % tk["id"]
        assert u"QAT" in p and u"STG" in p, u"%s 缺站台邊界" % tk["id"]


# ─────────────────────── 時間盒要真的傳到 claude_session

def test_探索任務的時間盒會變成session的上限():
    """★ 核心迴歸：平台宣告 90 分鐘，卻在第 5 分鐘把程序殺掉。

    2026-08-23 範本實跑：探索 session 只留下 82 個字就沒了，
    而且**沒有任何訊息** —— 被 kill 的程序沒有 stderr，錯誤分支永遠不觸發。
    """
    tasks = _t()
    tk = tasks.get("explore")
    assert tk, "沒有 explore 任務"
    r = tasks.render(tk, {"product": "crux"}, product_skill="crux")
    sec = r.get("timeout_sec")
    # ⭐ 2026-08-26 起**預設不設限**（使用者裁示）—— 同一條理由再走一次：
    #    「沒有人能準確預測 session 運行時長」。而工作量又長了一截
    #    （案例要逐條跑 ＋ 整檔跑兩次）。0 ＝ 不設限。
    #    ⛔ 這一條釘的還是同一件事：**上限不可以卡到正常的長工作**。
    assert sec == 0 or sec >= 90 * 60, u"上限只有 %s 秒 —— 長一點的探索會被切一半" % sec


def test_沒宣告上限的任務一律不設限():
    """⛔ 2026-08-26 起不再有全域上限 —— 被砍掉的代價是已經跑了幾小時的產出。

    ⚠️ 換來的代價：掛死的程序不會自己結束，要人在 session 列表按「關閉」。
       掛死是罕見的，中途被砍是每次都可能發生的。
    """
    tasks = _t()
    for tk in tasks.load():
        sec = tasks.render(tk, {"product": "crux"}, product_skill="crux").get("timeout_sec")
        if tk.get("timeout_minutes"):
            continue                          # 自己宣告的另有一條測試
        assert sec == 0, u"%s 還帶著上限 %s 秒" % (tk["id"], sec)


def test_不設限時不可以去建Timer():
    """⛔ `threading.Timer(None, ...)` 會當場炸 —— 而那正是所有 session 的預設路徑。"""
    import os as _os
    import sys as _sys
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    p = _os.path.join(root, "tools", "test_platform")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    src = io.open(_os.path.join(p, "core", "claude_session.py"), encoding="utf-8").read()
    assert "if timeout else None" in src, u"沒有守住 timeout 為 0／None 的情況"
    assert "if killer:" in src, u"cancel 沒有守 —— None.cancel() 會炸"


def test_逾時被殺時一定要留下訊息():
    """⛔ 無聲截斷是最糟的失敗方式 —— 看起來就像「它自己講完了」。"""
    import sys as _sys
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    p = _os.path.join(root, "tools", "test_platform")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    import io as _io
    src = _io.open(_os.path.join(p, "core", "claude_session.py"), encoding="utf-8").read()
    assert "if killed:" in src, u"逾時沒有專屬分支 —— 被 kill 的程序沒有 stderr，錯誤永遠吐不出來"
    assert "時間上限" in src, u"逾時訊息沒有寫明上限"


# ─────────────────────── ★ 結構性護欄：有瀏覽器就一定要有邊界
#
# 這一類缺口 2026-08-23 一天之內出現三次（explore／verify_jira／file_bug）：
# 任務給了瀏覽器，卻沒有任何地方告訴 session「站台可以動到什麼程度」——
# 於是它自己降級成唯讀，把「我沒辦法重現」寫成 BLOCKED 甚至 PASS。
# 靠記憶維持一致必然漏，所以改成一條會紅燈的檢查。

def test_給了瀏覽器的任務一定要有安全邊界():
    T = _t()
    for t in T.load():
        tools = " ".join(t.get("allowed_tools") or [])
        if "playwright" not in tools:
            continue
        keys = {f["key"] for f in t.get("fields") or []}
        assert "boundary" in keys, \
            "%s 有瀏覽器卻沒有 boundary 欄位 —— session 會自己降級成唯讀" % t["id"]
        assert "{boundary_rules}" in t.get("prompt_template", ""), \
            "%s 只有 boundary 欄位、提示裡卻沒展開條款（一個標籤擋不住）" % t["id"]


def test_有安全邊界的任務都要能指定子帳號():
    """站台是「同帳號他處登入即踢掉前者」—— 兩個任務同時跑就會互踢，
    症狀是「令牌过期，请重新登录」，**極易誤判成平台的 bug**。"""
    T = _t()
    for t in T.load():
        keys = {f["key"] for f in t.get("fields") or []}
        if "boundary" not in keys:
            continue
        assert "account" in keys, "%s 沒有指定子帳號的欄位" % t["id"]


# ─────────────────────── ★ 不再有時間盒（2026-08-23 使用者裁示）
#
# > 「沒有人能準確預測 session 運行時長，
# >   時間盒反而可能造成執行過程的資料遺失的風險。」
#
# 先前表單有「時間盒」欄位、程序上限跟著它算 —— **時間成了中斷因素**，
# 而中斷的代價是跑了幾十分鐘的探索被切一半。
# 現在範圍由「功能區塊／那份需求」界定，程序上限退回純粹的防掛死防線。

def test_任務表單裡沒有時間盒欄位():
    T = _t()
    for t in T.load():
        keys = {f["key"] for f in t.get("fields") or []}
        assert "timebox" not in keys, "%s 還留著時間盒欄位" % t["id"]


def test_提示裡不提時間():
    """⛔ 提示裡出現「N 分鐘」只會讓 session 自我設限。"""
    import re
    T = _t()
    for t in T.load():
        tpl = t.get("prompt_template", "")
        assert not re.search(r"時間盒", tpl), "%s 的提示還在講時間盒" % t["id"]
        assert not re.search(r"\{timebox\}", tpl), t["id"]


def test_範圍改由區塊或需求界定():
    T = _t()
    assert "範圍以上面那個功能區塊為界，不設時間" in T.get("explore")["prompt_template"]
    assert "範圍以上面那份需求為界，不設時間" in \
        T.get("verify_requirement")["prompt_template"]


def test_上限不會卡到正常的長工作():
    """不設限（0）或給得很寬都可以 —— 不可以的是「短到會切掉正常的工作」。"""
    T = _t()
    for t in T.load():
        sec = T.render(t, {"product": "X"})["timeout_sec"]
        assert sec == 0 or sec >= 60 * 60, \
            "%s 的上限只有 %s 秒，會卡到正常的長工作" % (t["id"], sec)


def test_任務仍可自己宣告上限():
    """開工接手這種「只是讀」的任務可以短一點。"""
    T = _t()
    task = dict(T.get("explore"), timeout_minutes=45)
    assert T.render(task, {})["timeout_sec"] == 45 * 60


# ─────────────────────── ★ 產草稿的任務一定要給得出格式
#
# 2026-08-23：`verify_jira` 跑得很完整（真的登入站台、還原資料、五值判定），
# 然後草稿是 `{'bugs': 0, 'docs': 0}` —— 因為提示只寫「先回在對話裡」，
# **沒有給草稿格式**。一份完整的重驗報告就只活在對話文字裡。

def _draft_blocks(tpl):
    import re
    return re.findall(r"`{3,}[^\n]*\n(.*?)`{3,}", tpl, re.S)


def test_寫入型任務都給得出草稿格式():
    T = _t()
    for t in T.load():
        if t.get("writes") != "draft":
            continue
        blocks = _draft_blocks(t.get("prompt_template", ""))
        assert blocks, "%s 宣告 writes=draft，提示裡卻沒有任何草稿區塊" % t["id"]
        keys = {ln.split()[0] for b in blocks for ln in b.split("\n")
                if ln.strip() and not ln[:1].isspace()}
        assert keys & {"title", "kind"}, \
            "%s 的草稿區塊認不出必要欄位：%s" % (t["id"], keys)


def test_會操作站台的任務都要收測試資料():
    """動過站台卻沒登記，等於沒有人知道你動過什麼。"""
    T = _t()
    for t in T.load():
        keys = {f["key"] for f in t.get("fields") or []}
        if "boundary" not in keys or t.get("writes") != "draft":
            continue
        tpl = t.get("prompt_template", "")
        assert "section  data" in tpl or "section   data" in tpl or "section data" in tpl, \
            "%s 會操作站台，卻沒要求交測試資料草稿" % t["id"]


def test_產報告的任務不自己拼檔名():
    T = _t()
    for t in T.load():
        tpl = t.get("prompt_template", "")
        if "kind         report" not in tpl and "kind     report" not in tpl:
            continue
        assert "new_bug_doc.py" in tpl and "不要自己拼檔名" in tpl, t["id"]


def test_前言講會波及別人的操作但不禁止():
    """⛔ **不可以寫成「一律不要做」**（2026-08-26 使用者指出我第一版過度限制）。

    開獎、一键结账、結算重置**常常就是測試流程本身** —— 要驗中獎判定就得開獎。
    擋掉等於讓整類測試做不了，而那正是這個平台記錄過的失效模式：
    「『一律不給』擋掉的不只是風險，**也擋掉了規範本身**」（見 `SAFE_TOOLS`）。

    `CLAUDE.md` §5 第 3 條的判準是「會不會影響到別人」，且**專用站台不必問**。
    """
    T = _t()
    pre = T._PREAMBLE
    assert "一键结账" in pre and "反結算" in pre, u"前言沒提會波及別人的操作"
    assert "會不會影響到別人" in pre, u"沒給判準，它只會避開清單上的字面詞"
    assert "不是不能做" in pre, u"⛔ 寫成禁止會讓整類測試做不了"
    assert "在回覆裡寫明" in pre, u"沒要求留下紀錄 —— 事後就查不到它動了哪一台"
    # ⛔ 反向釘：不可以出現「一律不要做」這種寫法
    assert "一律不要做" not in pre, u"又寫成禁止清單了"


def test_前言要求工具回傳精簡但不擋取證():
    """⭐ 2026-08-26 實測後新增：工具回傳是 context 成長的最大宗。

    量測（`58dd5699` 探索 session，238 輪、輸入面累計 61.9M token）：
      · context 起始 41k，之後成長 408k
      · 其中 `browser_evaluate` 42%、`Bash` 30% —— **合計七成**
      · 成本是**複利**的：第 k 輪進 context 的東西，之後每一輪都要重讀
      · 反事實模擬（兩者回傳壓到 500 token）：61.9M → 35.0M，**省 43%**

    ⛔ **不可以寫成「少查一點」** —— 那會擋掉取證，正是本檔記錄過的失效模式
    （見 `test_前言講會波及別人的操作但不禁止`）。要的是**篩在查詢裡**，不是少驗。
    """
    T = _t()
    pre = T._PREAMBLE
    assert u"每一輪都要重讀" in pre, u"沒講複利 —— 只說「精簡」它不會知道為什麼"
    assert u"一次問完" in pre, u"沒講批次 —— 一個值一支 evaluate 是輪次爆炸的主因"
    for kw in (u"filter", u"grep"):
        assert kw in pre, u"沒給「篩在查詢裡」的具體做法：%s" % kw
    # ⛔ 反向釘：不可以變成「少驗」
    assert u"不是叫你少驗" in pre, u"沒有反向保護，會被讀成少查一點"
    assert u"要看的照看" in pre, u"沒講清楚該取的證照取"
