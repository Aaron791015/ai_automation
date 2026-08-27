# -*- coding: utf-8 -*-
"""`scripts/export_template.py` —— 把工作區匯出成乾淨的標準專案範本。

用途：這支腳本的產出會直接交到同事手上，**漏掉一個檔案就是憑證或產品資料外流**。
      四件事要釘住：
      ① 白名單分類必須**涵蓋整個 repo**（`--audit` 為空）—— 這是唯一的維護防線，
         新增檔案卻忘了分類就會靜默漏掉，所以這裡直接跑真實的稽核
      ② 產品層、gitignored 的東西**不得**進入匯出計畫
      ③ 判定順序：產品層與 NEVER **優先於** EXPORT（`scripts/` 整個在白名單裡，
         但 `scripts/explore_<產品>.py` 是產品層）
      ④ 匯出條件是「git 追蹤 **AND** 白名單」——兩層缺一不可

前置條件：無。除 ① 之外全部在 tmp_path 造假。
使用方式：`pytest tests/tooling/test_export_template.py -q`
"""
import io
import json
import os

import pytest

import export_template as E


# ─────────────────────────────── ① 真實 repo 的稽核

def test_白名單涵蓋整個repo():
    """★ 最重要的一條：`--audit` 必須為空。

    白名單唯一的失效模式是「新增了東西卻忘了分類」——
    分類漏掉 → 該檔不會被匯出（通用檔）或被誤匯出（產品檔），
    而且**沒有任何人會發現**。這條測試把它變成紅燈。

    紅了怎麼辦：跑 `python scripts\\export_template.py --audit` 看是哪個路徑，
    然後決定它屬於 EXPORT／SKELETON／NEVER／產品層（products.json 的 extra_paths）。
    """
    miss = E.unclassified(E.ROOT)
    assert miss == [], (
        u"下列路徑未分類，範本會漏帶或誤帶：%s" % miss)


def test_容器不可放進NEVER():
    """★ 迴歸：第一版把 docs／tools／tests 放進 NEVER，於是任何新增的子項
    都被「在 NEVER 底下」掃成 never —— `--audit` 當場全綠、毫無作用。
    """
    for c in E.PARTIAL:
        assert c not in E.NEVER, u"%s 是容器，放進 NEVER 會讓 audit 失效" % c


def test_每條NEVER都寫得出理由():
    """寫不出理由的表示還沒想清楚，日後沒人敢動它。"""
    for path, why in E.NEVER.items():
        assert why and len(why) >= 4, u"%s 沒有寫理由" % path


# ─────────────────────────────── ② 分類邏輯

PRODUCTS = {"products": [
    {"id": "甲", "docs_dir": "Alpha", "tests_dir": "alpha", "qa_tools_dir": "alpha_qa",
     "skill": "alpha", "bug_prefix": "ALPHA", "aliases": ["alpha"],
     "extra_paths": ["tools/Alpha_Performance", "scripts/explore_alpha.py"]},
]}


@pytest.fixture
def products():
    """一個假產品宣告出來的所有路徑（等同 `product_paths()` 對上方 PRODUCTS 的結果）。"""
    return {"docs/Alpha", "tests/alpha", "tools/alpha_qa", ".claude/skills/alpha",
            "tools/Alpha_Performance", "scripts/explore_alpha.py"}


@pytest.mark.parametrize("rel,expect", [
    ("scripts/lint_docs.py", "export"),
    ("scripts/explore_alpha.py", "product"),      # ★ 產品層要贏過 scripts 的整目錄白名單
    ("tools/qa_common/shot.py", "export"),
    ("tools/alpha_qa/pages/p.py", "product"),
    ("tools/Alpha_Performance/runner.py", "product"),
    (".claude/skills/handoff/SKILL.md", "export"),
    (".claude/skills/alpha/SKILL.md", "product"),
    (".claude/skills/theme-factory/SKILL.md", "never"),
    ("config/config.local.json", "never"),
    ("config/products.json", "skeleton"),
    ("docs/Alpha/機制.md", "product"),
    ("docs/INDEX.md", "skeleton"),
    ("tools/test_platform/registry/crux_perf.tool.json", "never"),
    ("tools/test_platform/registry/_schema.json", "export"),
    ("tools", "container"),
    ("tools/somethingnew", None),                 # ★ 沒分類過的東西要浮出來
])
def test_分類(products, rel, expect):
    assert E.classify(rel, products) == expect


def test_產品層優先於白名單(products):
    """`scripts` 整個在 EXPORT 裡，但產品專屬的探索腳本必須先被攔下。"""
    assert E.classify("scripts/explore_alpha.py", products) == "product"
    assert E.classify("scripts/lint_docs.py", products) == "export"


# ─────────────────────────────── ③ 匯出計畫

def touch(path, text=u"x"):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    r = str(tmp_path)
    touch(os.path.join(r, "config", "products.json"),
          json.dumps(PRODUCTS, ensure_ascii=False))
    files = [
        "CLAUDE.md", "README.md",
        "scripts/lint_docs.py", "scripts/explore_alpha.py",
        "tools/qa_common/shot.py", "tools/alpha_qa/p.py",
        "tools/Alpha_Performance/runner.py",
        ".claude/skills/handoff/SKILL.md", ".claude/skills/alpha/SKILL.md",
        ".claude/skills/theme-factory/SKILL.md",
        ".claude/memory-seed/x.md",
        "docs/Alpha/機制.md", "docs/Alpha/bugs/單.md",
        "tests/tooling/test_x.py", "tests/alpha/test_a.py",
        "config/config.local.json",
    ]
    for f in files:
        touch(os.path.join(r, f.replace("/", os.sep)))
    # 預設「全部都在版控裡」，個別測試再收窄
    monkeypatch.setattr(E, "tracked_files", lambda root: set(files))
    return r


def test_匯出計畫只含通用層(fake_repo):
    plan = E.export_plan(fake_repo)
    for good in ["CLAUDE.md", "scripts/lint_docs.py", "tools/qa_common/shot.py",
                 ".claude/skills/handoff/SKILL.md", ".claude/memory-seed/x.md",
                 "tests/tooling/test_x.py"]:
        assert good in plan, good
    for bad in ["scripts/explore_alpha.py", "tools/alpha_qa/p.py",
                "tools/Alpha_Performance/runner.py", ".claude/skills/alpha/SKILL.md",
                ".claude/skills/theme-factory/SKILL.md", "docs/Alpha/機制.md",
                "docs/Alpha/bugs/單.md", "tests/alpha/test_a.py",
                "config/config.local.json"]:
        assert bad not in plan, bad


def test_不在版控的檔案不匯出(fake_repo, monkeypatch):
    """★ 第二層防線：`.gitignore` 已宣告過的 run 產物與敏感檔一律不帶。

    （迴歸：平台的 `cache/`／`logs/`／`demo/artifacts/` 曾被整包複製進範本，
      393 個檔、好幾 MB —— 而 `.gitignore` 早就寫了。）
    """
    monkeypatch.setattr(E, "tracked_files",
                        lambda root: {"CLAUDE.md", "scripts/lint_docs.py"})
    plan = E.export_plan(fake_repo)
    assert plan == ["CLAUDE.md", "scripts/lint_docs.py"]


def test_取不到git時不過濾(fake_repo, monkeypatch):
    """不是 git repo 就退回純白名單，不要整個匯不出來。"""
    monkeypatch.setattr(E, "tracked_files", lambda root: None)
    assert "tools/qa_common/shot.py" in E.export_plan(fake_repo)


def test_實際寫出檔案與骨架(fake_repo, tmp_path):
    out = str(tmp_path / "out")
    n_copy, n_skel = E.do_export(fake_repo, out)
    assert n_copy > 0 and n_skel == len(E.SKELETON)
    assert os.path.isfile(os.path.join(out, "CLAUDE.md"))
    assert not os.path.exists(os.path.join(out, "docs", "Alpha"))

    # 骨架：products 必須是空的，否則同事一開始就帶著別人的產品定義
    data = json.load(io.open(os.path.join(out, "config", "products.json"),
                             encoding="utf-8"))
    assert data["products"] == []


def test_骨架與reset共用同一份INDEX():
    """兩支腳本產出的 INDEX 骨架必須一致 —— 各留一份就會分岔。"""
    import reset_workspace
    assert E.SKELETON["docs/INDEX.md"] is reset_workspace.INDEX_SKELETON


# ─────────────────────────────── ④ review 修正的迴歸（2026-08-23）

def test_檔名帶產品字樣卻被判成通用要被抓到(monkeypatch):
    """★ R1：`scripts` 整個在 EXPORT 裡，是 fail-open 的容器。

    新增 `scripts/explore_<產品>_ui.py` 卻忘了登記 `extra_paths` 時，
    classify 會回 "export"、`--audit` 全綠 —— 產品腳本被靜默匯出。
    用**路徑**判定（檔名是命名，不是行文），所以通用 skill 內文提到原型產品不會誤報。

    ⚠️ 產品字樣一律由 `leak_words` 注入，**不依賴 repo 實際註冊了哪些產品** ——
      剛匯出的範本 products 是空的，靠真實產品名的話這條在範本裡會紅
      （2026-08-23 實際發生：匯出後 `pytest` 就這一條失敗）。
    """
    monkeypatch.setattr(E, "leak_words", lambda root: {"甲產品", "YIBOT"})
    fake = ["scripts/lint_docs.py", "scripts/explore_甲產品_ui.py",
            "tools/qa_common/YIBOT_helper.py"]
    hits = dict(E.suspicious(E.ROOT, plan=fake))
    assert "scripts/explore_甲產品_ui.py" in hits
    assert "tools/qa_common/YIBOT_helper.py" in hits
    assert "scripts/lint_docs.py" not in hits


def test_沒有註冊產品時不誤報(monkeypatch):
    """空範本（products 為空）沒有產品字樣可比對，應直接回空，不是報一堆。"""
    monkeypatch.setattr(E, "leak_words", lambda root: set())
    assert E.suspicious(E.ROOT, plan=["scripts/explore_甲產品_ui.py"]) == []


def test_真實匯出計畫沒有可疑檔名():
    """已登記的產品腳本不該出現在計畫裡，所以真實計畫應為零命中。"""
    assert E.suspicious(E.ROOT) == []


def test_EXPORT指到不存在的路徑要被列出():
    """R3：通用 skill 改名後若沒同步 EXPORT，會**無聲地不再匯出**。"""
    assert E.missing_export_entries(E.ROOT) == []
    E.EXPORT.append(".claude/skills/被改名的skill")
    try:
        assert E.missing_export_entries(E.ROOT) == [".claude/skills/被改名的skill"]
    finally:
        E.EXPORT.pop()


def test_不認得的非空目錄不可寫(tmp_path):
    """R2：本工具會 rmtree 目標，認錯目錄的代價太大 —— 沒有 --force 可繞過。"""
    d = tmp_path / "別人的資料"
    os.makedirs(str(d))
    touch(str(d / "重要.txt"))
    ok, why = E.can_write(str(d))
    assert not ok and E.MARKER in why


def test_空目錄與新目錄可寫(tmp_path):
    assert E.can_write(str(tmp_path / "還沒建"))[0]
    empty = tmp_path / "空的"
    os.makedirs(str(empty))
    assert E.can_write(str(empty))[0]


def test_自己的舊匯出可覆蓋且會先清空(tmp_path, monkeypatch):
    """R2：不清的話上次的殘留（甚至手動丟進去的憑證）會跟著交出去。"""
    out = str(tmp_path / "out")
    os.makedirs(out)
    touch(os.path.join(out, E.MARKER), u"# marker")
    touch(os.path.join(out, "殘留.md"), u"上次留下的")
    assert E.can_write(out) == (True, "reexport")

    monkeypatch.setattr(E, "export_plan", lambda root: [])
    E.do_export(E.ROOT, out)
    assert not os.path.exists(os.path.join(out, "殘留.md"))
    assert os.path.isfile(os.path.join(out, E.MARKER))


# ─────────────────────────────── ④b 同步到版控中的鏡像（--sync）
#
# 維護流程（使用者 2026-08-25 指定）：原版匯出 → 覆蓋乾淨範本 → 檢查差異 → stage → commit → push。
# ⛔ 覆蓋一個有 .git/ 的目錄本來是被擋掉的（rmtree 會連歷史一起刪），
#    所以放行的**唯一前提**是「working tree 乾淨 ＝ 覆蓋掉的都救得回來」。


def _mirror(tmp_path, dirty=False):
    """造一個「上次匯出、已經 git init 並提交」的鏡像目錄。"""
    import subprocess
    out = str(tmp_path / "mirror")
    os.makedirs(out)
    touch(os.path.join(out, E.MARKER), u"# marker")
    touch(os.path.join(out, "舊檔.md"), u"上一版")
    touch(os.path.join(out, ".gitignore"), u"docs/**/bugs/" + chr(10))   # 照實情：bugs/ 不版控
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.check_call(["git", "-C", out] + cmd)
    if dirty:
        touch(os.path.join(out, "舊檔.md"), u"改到一半，還沒 commit")
    return out


def test_sync_乾淨的鏡像可以覆蓋且保留git(tmp_path, monkeypatch):
    out = _mirror(tmp_path)
    assert E.can_write(out) [0] is False, "沒有 --sync 時仍該擋住（.git 是 in_use 跡象）"
    assert E.can_write(out, sync=True) == (True, "sync")

    monkeypatch.setattr(E, "export_plan", lambda root: [])
    monkeypatch.setattr(E, "SKELETON", {})
    E.do_export(E.ROOT, out, keep=E.KEEP_ON_SYNC)
    assert os.path.isdir(os.path.join(out, ".git")), "⛔ commit 歷史被刪掉了"
    assert not os.path.exists(os.path.join(out, "舊檔.md")), "來源已無的檔案要一併消失"


def test_sync_髒的鏡像一律拒絕(tmp_path):
    """⛔ 未提交的改動一覆蓋就沒了，而它不在任何 commit 裡。"""
    out = _mirror(tmp_path, dirty=True)
    ok, why = E.can_write(out, sync=True)
    assert not ok
    assert "未提交" in why and "舊檔.md" in why


def test_sync_只有戳記檔有差異時仍可同步(tmp_path):
    """MARKER 是工具每次自己重寫的時間戳 —— 讓它擋住流程，等於「看完差異決定先不提交」
    的人下一次就卡住。⚠️ 這條同時釘住欄位切法：git status 的行首空白被 strip 掉之後，
    用 L[3:] 取路徑會錯開一格，豁免就無聲失效。"""
    out = _mirror(tmp_path)
    touch(os.path.join(out, E.MARKER), u"# 上一次同步的戳記，內容不同了")
    assert E.mirror_dirty(out)[0] is False
    assert E.can_write(out, sync=True) == (True, "sync")


def test_sync_鏡像裡有bug單就拒絕(tmp_path):
    """bugs/ 不版控 —— 乾淨的 working tree 保護不到它，所以要單獨擋。"""
    out = _mirror(tmp_path)
    touch(os.path.join(out, "docs", "某產品", "bugs", "X-001.md"), u"# 單子")
    ok, why = E.can_write(out, sync=True)
    assert not ok and "bugs" in why


def test_sync_只在有marker且有git時成立(tmp_path):
    """--sync 不是萬用鑰匙：來路不明的 git repo 照樣不碰。"""
    import subprocess
    d = str(tmp_path / "別人的repo")
    os.makedirs(d)
    touch(os.path.join(d, "重要.txt"))
    subprocess.check_call(["git", "-C", d, "init", "-q"])
    ok, why = E.can_write(d, sync=True)
    assert not ok and E.MARKER in why


def test_product_paths欄位缺失不會整支掛掉(tmp_path):
    """R5：其餘欄位都用 .get()，只有 docs_dir 是直接索引 —— 不一致就會爆。"""
    r = str(tmp_path)
    touch(os.path.join(r, "config", "products.json"),
          json.dumps({"products": [{"id": "殘缺", "skill": "broken"}]},
                     ensure_ascii=False))
    assert ".claude/skills/broken" in E.product_paths(r)


def test_suspicious例外都寫得出理由():
    """比照 NEVER：寫不出理由的例外，表示它其實不該被匯出。

    （這份清單是 2026-08-23 commit 後才需要的 —— 那兩份 references 在提交前
      還是未版控，被 `export_plan` 的 git 過濾擋在計畫外，檢查掃不到；
      一 commit 就進了計畫、立刻誤報。）
    """
    assert E.SUSPICIOUS_OK, "至少要有一條，否則這個常數該刪掉"
    for path, why in E.SUSPICIOUS_OK.items():
        assert why and len(why) >= 10, u"%s 沒有寫理由" % path


def test_suspicious例外的檔案真的存在():
    """例外指到不存在的檔案 = 清單過期，會默默放行一個本來該擋的檔名。"""
    for path in E.SUSPICIOUS_OK:
        assert os.path.exists(os.path.join(E.ROOT, path.replace("/", os.sep))), path


# ─────────────────────────────── ⑤ 範本更新同步（--compare）

def _mini_export(root, out, monkeypatch, files):
    """造一份最小的匯出（含基準線），files 為 {rel: 內容}。"""
    for rel, content in files.items():
        touch(os.path.join(root, rel.replace("/", os.sep)), content)
    monkeypatch.setattr(E, "export_plan", lambda r: sorted(files))
    monkeypatch.setattr(E, "SKELETON", {})
    E.do_export(root, out, stamp="2026-01-01 00:00")


def test_compare_三方分類(tmp_path, monkeypatch):
    """★ 光比「現在的範本 vs 他的目錄」分不出「他改的」與「範本更新的」。

    基準線（匯出當下的 sha1）讓三方比較成立：
      只有範本變 → 可直接覆蓋｜只有他變 → 別覆蓋｜兩邊都變 → 要人合併
    """
    root = str(tmp_path / "repo")
    out = str(tmp_path / "theirs")
    _mini_export(root, out, monkeypatch, {
        "a.md": u"原始", "b.md": u"原始", "c.md": u"原始", "d.md": u"原始"})

    # 範本這邊：a 改了、c 改了、新增 e
    touch(os.path.join(root, "a.md"), u"範本改過")
    touch(os.path.join(root, "c.md"), u"範本改過")
    touch(os.path.join(root, "e.md"), u"新的")
    # 同事那邊：b 改了、c 也改了
    touch(os.path.join(out, "b.md"), u"同事改過")
    touch(os.path.join(out, "c.md"), u"同事改過")

    monkeypatch.setattr(E, "export_plan",
                        lambda r: ["a.md", "b.md", "c.md", "d.md", "e.md"])
    m, has_base = E.compare(root, out)
    assert has_base
    assert m["template_only"] == ["a.md"]
    assert m["yours_only"] == ["b.md"]
    assert m["both"] == ["c.md"]
    assert m["same"] == ["d.md"]
    assert m["new"] == ["e.md"]


def test_compare_沒有基準線時誠實說判不出來(tmp_path, monkeypatch):
    """舊版匯出或 clone 來的沒有基準線 —— 不可把差異一律當成「範本更新」。"""
    root = str(tmp_path / "repo")
    out = str(tmp_path / "theirs")
    touch(os.path.join(root, "a.md"), u"範本")
    touch(os.path.join(out, "a.md"), u"不一樣")
    monkeypatch.setattr(E, "export_plan", lambda r: ["a.md"])
    monkeypatch.setattr(E, "SKELETON", {})

    m, has_base = E.compare(root, out)
    assert has_base is False
    assert m["unknown"] == ["a.md"]
    assert m["template_only"] == [] and m["both"] == []


def test_compare_範本移除的檔案會列出(tmp_path, monkeypatch):
    root = str(tmp_path / "repo")
    out = str(tmp_path / "theirs")
    _mini_export(root, out, monkeypatch, {"a.md": u"x", "舊的.md": u"y"})
    monkeypatch.setattr(E, "export_plan", lambda r: ["a.md"])
    m, _ = E.compare(root, out)
    assert m["removed"] == ["舊的.md"]


def test_行尾差異不算變更(tmp_path, monkeypatch):
    """CRLF/LF 差異會讓整份範本看起來全變了 —— 那是假警報。"""
    root = str(tmp_path / "repo")
    out = str(tmp_path / "theirs")
    _mini_export(root, out, monkeypatch, {"a.md": u"一行\n二行\n"})
    io.open(os.path.join(out, "a.md"), "wb").write(u"一行\r\n二行\r\n".encode("utf-8"))
    monkeypatch.setattr(E, "export_plan", lambda r: ["a.md"])
    m, _ = E.compare(root, out)
    assert m["same"] == ["a.md"]


def test_未版控的未分類路徑降為警告(tmp_path, monkeypatch):
    """★ 迴歸：另一個 session 在 repo 根目錄留下兩張 png，D11 當場全紅 ——
    但那兩個檔**根本不可能被匯出**（匯出條件是「git 追蹤 ∩ 白名單」）。

    已版控＋未分類 → 錯誤（真的會影響匯出）
    未版控＋未分類 → 警告（可能是暫存物，也可能是你剛新增還沒 commit 的通用檔）
    """
    r = str(tmp_path)
    touch(os.path.join(r, "config", "products.json"), u'{"products": []}')
    touch(os.path.join(r, "別人的暫存.png"))
    touch(os.path.join(r, "我新加的.md"))
    monkeypatch.setattr(E, "ROOT", r)
    monkeypatch.setattr(E, "tracked_files", lambda root: {"我新加的.md"})

    assert E.unclassified(r) == ["我新加的.md"]          # 已版控 → 錯誤
    assert E.unclassified_untracked(r) == ["別人的暫存.png"]   # 未版控 → 警告


# ─────────────────────────────── ⑥ 共同語言層與匯出後處理

def test_共同語言層的檔案都存在():
    """★ 這一層分岔了，同事之間就看不懂彼此的報告 —— 指標斷了等於這道防線消失。"""
    assert E.SHARED_LANGUAGE, "至少要有一條"
    for path, why in E.SHARED_LANGUAGE.items():
        assert os.path.exists(os.path.join(E.ROOT, path.replace("/", os.sep))), path
        assert why and len(why) >= 6, u"%s 沒寫清楚它承載什麼" % path


def test_compare會單獨標出共同語言層(tmp_path, monkeypatch):
    root = str(tmp_path / "repo")
    out = str(tmp_path / "theirs")
    shared = sorted(E.SHARED_LANGUAGE)[0]
    files = {shared: u"原始", "scripts/普通.py": u"原始"}
    for rel, c in files.items():
        touch(os.path.join(root, rel.replace("/", os.sep)), c)
    monkeypatch.setattr(E, "export_plan", lambda r: sorted(files))
    monkeypatch.setattr(E, "SKELETON", {})
    E.do_export(root, out, stamp="2026-01-01 00:00")

    touch(os.path.join(root, shared.replace("/", os.sep)), u"範本改過")
    touch(os.path.join(root, "scripts", "普通.py"), u"範本改過")
    m, _ = E.compare(root, out)
    assert len(m["shared_language"]) == 1
    rel, kind, _ = m["shared_language"][0]
    assert rel == shared and kind == "template_only"


def test_TRANSFORMS的來源段落還在():
    """★ 原文改過卻沒同步轉換規則 → 範本裡留下一段**對讀者不成立**的敘述。

    （例如叫拿到乾淨範本的人去跑 `reset_workspace`，那在空範本裡是空轉。）
    這條檢查刻意放在測試與 `--audit`，**不放在 do_export** ——
    放執行期會炸掉「README 本來就不含該段落」的正常情境。

    ⚠️ **只在原型 repo 有意義** —— 匯出的範本裡 README 已經被轉換過，
      來源段落本來就不在了。靠 `.template-export` 判斷自己在哪一邊。
    """
    if os.path.isfile(os.path.join(E.ROOT, E.MARKER)):
        pytest.skip("這是匯出的範本，README 已轉換過（本檢查只對原型 repo 成立）")
    assert E.stale_transforms(E.ROOT) == []


def test_匯出時真的套用了轉換(tmp_path, monkeypatch):
    root = str(tmp_path / "repo")
    out = str(tmp_path / "out")
    touch(os.path.join(root, "README.md"), u"前\n只給維護者看的段落\n後\n")
    monkeypatch.setattr(E, "TRANSFORMS",
                        {"README.md": [(u"只給維護者看的段落", u"給範本讀者看的段落")]})
    monkeypatch.setattr(E, "export_plan", lambda r: ["README.md"])
    monkeypatch.setattr(E, "SKELETON", {})
    E.do_export(root, out)
    got = io.open(os.path.join(out, "README.md"), encoding="utf-8").read()
    assert u"給範本讀者看的段落" in got and u"只給維護者看的" not in got


def test_來源段落不存在時匯出不中斷(tmp_path, monkeypatch):
    """production 寬鬆、測試嚴格 —— 匯出不該因為轉換規則過期就整個失敗。"""
    root = str(tmp_path / "repo")
    out = str(tmp_path / "out")
    touch(os.path.join(root, "README.md"), u"完全不一樣的內容\n")
    monkeypatch.setattr(E, "TRANSFORMS", {"README.md": [(u"不存在的段落", u"x")]})
    monkeypatch.setattr(E, "export_plan", lambda r: ["README.md"])
    monkeypatch.setattr(E, "SKELETON", {})
    E.do_export(root, out)          # 不應拋出
    assert io.open(os.path.join(out, "README.md"),
                   encoding="utf-8").read() == u"完全不一樣的內容\n"


# ─────────────────────────────── 驗收要用對直譯器

def test_驗收不得直接用sys_executable():
    """★ 迴歸：`verify()` 原本用 `sys.executable` 跑 pytest。

    同事很自然會用系統 Python 執行 `python scripts/export_template.py --out ...`，
    而**系統 Python 多半沒有 `allure-pytest`** —— `pyproject.toml` 的 `addopts`
    帶著 `--alluredir`，pytest 會以「unrecognized arguments」的**用法錯誤**退出，
    於是驗收印出「❌ 驗收未過，範本先不要交出去」，
    但**測試其實一條都沒跑、也一條都沒壞**（同一份範本手動跑是 405 passed）。

    2026-08-23 實際發生。改為優先用工作區的 `.venv`。
    """
    import export_template as E
    py = E._verify_python()
    assert py, "_verify_python 回了空值"
    venv = os.path.join(E.ROOT, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv):
        assert os.path.normcase(py) == os.path.normcase(venv), \
            "工作區有 .venv 卻沒用它：%s" % py


def test_pytest用法錯誤要與測試失敗分開報():
    """用法錯誤（exit 4）是**環境缺套件**，不是範本壞掉 ——
    兩者混為一談會讓人以為範本不能交，而去查一個不存在的問題。"""
    import inspect
    import export_template as E
    src = inspect.getsource(E.verify)
    assert "_PYTEST_USAGE_ERROR" in src, "verify() 沒有區分 pytest 的用法錯誤"
    assert E._PYTEST_USAGE_ERROR == 4


# ─────────────────────────────── ⑤ 重覆匯出的守門（rmtree 保護）

def _fake_export(root):
    """造一個「上次的匯出」—— 只要有 MARKER 檔就算。"""
    os.makedirs(str(root), exist_ok=True)
    io.open(os.path.join(str(root), E.MARKER), "w", encoding="utf-8").write("x")
    return str(root)


def test_乾淨的舊匯出可以重來(tmp_path):
    out = _fake_export(tmp_path / "t")
    ok, why = E.can_write(out)
    assert ok and why == "reexport"


@pytest.mark.parametrize("sign", [".git", ".venv"])
def test_有人在工作的目標一律擋下來(tmp_path, sign):
    """★ 核心迴歸：`do_export()` 下一步就是 `shutil.rmtree(out)`。

    MARKER 檔會**永久留在同事的 repo 裡** —— 用了三個月的工作區照樣
    `looks_like_export()` 為真。而 `bugs/` 與 `config.local.json` 都不版控，
    刪掉沒有 git 可以救。（2026-08-23 範本端到端驗收發現。）
    """
    out = _fake_export(tmp_path / "t")
    os.makedirs(os.path.join(out, sign))
    ok, why = E.can_write(out)
    assert not ok, u"目標有 %s 卻放行了 —— 會 rmtree 掉別人的工作" % sign
    assert sign in why


def test_接了產品的目標也擋下來(tmp_path):
    out = _fake_export(tmp_path / "t")
    os.makedirs(os.path.join(out, "config"))
    io.open(os.path.join(out, "config", "products.json"), "w", encoding="utf-8").write(
        u'{"products": [{"id": "樂透"}]}')
    ok, why = E.can_write(out)
    assert not ok and "products.json" in why


def test_空的產品清單不算在工作(tmp_path):
    """剛匯出的範本 `products: []` —— 那是骨架，不該被當成「有人在工作」。"""
    out = _fake_export(tmp_path / "t")
    os.makedirs(os.path.join(out, "config"))
    io.open(os.path.join(out, "config", "products.json"), "w", encoding="utf-8").write(
        u'{"products": []}')
    ok, _ = E.can_write(out)
    assert ok


def test_有bug單的目標擋下來(tmp_path):
    out = _fake_export(tmp_path / "t")
    b = os.path.join(out, "docs", u"樂透", "bugs")
    os.makedirs(b)
    io.open(os.path.join(b, "LOTTO-001.md"), "w", encoding="utf-8").write("x")
    ok, why = E.can_write(out)
    assert not ok and "bugs" in why
