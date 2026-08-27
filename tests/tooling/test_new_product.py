# -*- coding: utf-8 -*-
"""`scripts/new_product.py`（新產品接入）與產品定義單一來源的回歸測試。

用途：本工作區要成為可複製的範本，「接一個新產品進來」必須一步到位 ——
      漏掉任何一步（交接檔沒用對檔名結尾、Bug 前綴撞號、skill 名用了中文）
      都會在很久以後才以奇怪的方式爆出來。
      ★ 另一個重點是證明 `config/products.json` 的**單一來源真的生效** ——
      那份設定是為了消除「同一份產品資訊散在五處」的靜默分裂而建的。
前置條件：無（在 tmp_path 上偽造 repo，不碰真實 docs/）。
使用方式：`pytest tests/tooling/test_new_product.py -q`
"""
import io
import json
import os

import pytest

import new_product as np


BASE = {
    "products": [
        {"id": "CRUX", "label": "CRUX", "docs_dir": "CRUX", "bug_prefix": "CRUX",
         "aliases": ["crux"], "tests_dir": "crux", "qa_tools_dir": "crux_qa",
         "skill": "crux", "jira_key": "CRUX", "handovers": []},
    ],
    "common_handovers": [],
}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    pj = cfg / "products.json"
    pj.write_text(json.dumps(BASE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(np, "ROOT", str(tmp_path))
    monkeypatch.setattr(np, "PRODUCTS_JSON", str(pj))
    return tmp_path, pj


def _run(*args):
    return np.main(list(args))


def test_dry_run_不動任何檔案(sandbox, capsys):
    tmp, pj = sandbox
    before = pj.read_text(encoding="utf-8")
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto", "--dry-run")
    assert pj.read_text(encoding="utf-8") == before
    assert not (tmp / "docs" / "樂透").exists()
    assert "[dry]" in capsys.readouterr().out


def test_建立完整結構(sandbox, capsys):
    tmp, _ = sandbox
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    for rel in ["docs/樂透/bugs/shots", "docs/樂透/bugs/_reports", "docs/樂透/bugs/_handover",
                "tests/lotto", "tools/lotto_qa/pages", ".claude/skills/lotto"]:
        assert (tmp / rel).is_dir(), rel
    assert (tmp / ".claude/skills/lotto/SKILL.md").is_file()


def test_交接檔檔名必須以驗證交接結尾(sandbox):
    """★ 檔名結尾決定 lint D6 認不認得它 —— 取錯名等於這份交接檔永遠不會被檢查。"""
    tmp, _ = sandbox
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    hand = tmp / "docs" / "樂透" / "樂透_驗證交接.md"
    assert hand.is_file()
    body = hand.read_text(encoding="utf-8")
    assert "最後更新：" in body and "## 1. ⛔ 當前 blocker" in body and "## 5. 測試資料現況" in body


def test_註冊後產品定義讀得到(sandbox):
    """★ 證明單一來源生效：寫進 products.json 後，讀取端就看得到這個產品。"""
    tmp, pj = sandbox
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    data = json.loads(pj.read_text(encoding="utf-8"))
    ids = [p["id"] for p in data["products"]]
    assert "樂透" in ids
    entry = [p for p in data["products"] if p["id"] == "樂透"][0]
    assert entry["bug_prefix"] == "LOTTO" and entry["skill"] == "lotto"
    assert entry["handovers"] == ["docs/樂透/樂透_驗證交接.md"]


def test_重複的產品id被擋下(sandbox):
    with pytest.raises(SystemExit) as e:
        _run("--id", "CRUX", "--docs-dir", "CRUX2", "--bug-prefix", "XX")
    assert "已註冊" in str(e.value)


def test_重複的bug前綴被擋下(sandbox):
    """Bug 前綴撞號會讓兩個產品的 Bug ID 互相衝突。"""
    with pytest.raises(SystemExit) as e:
        _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "crux", "--alias", "lotto")
    assert "已被使用" in str(e.value)


def test_中文skill名被擋下(sandbox):
    """★ 回歸保障：未指定 alias/skill 時會推導出中文名，產生 tools/樂透_qa 這種目錄。"""
    with pytest.raises(SystemExit) as e:
        _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO")
    assert "小寫英數" in str(e.value)


def test_不覆蓋既有檔案(sandbox, capsys):
    tmp, _ = sandbox
    skill_md = tmp / ".claude" / "skills" / "lotto" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("我已經寫好了", encoding="utf-8")
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    assert skill_md.read_text(encoding="utf-8") == "我已經寫好了"
    assert "已存在，不覆蓋" in capsys.readouterr().out


def test_list列出已註冊產品(sandbox, capsys):
    assert _run("--list") == 0
    assert "CRUX" in capsys.readouterr().out


def test_bug_paths讀得到單一來源():
    """真實的 config/products.json 必須能被 bug_paths 正確載入（不走 fallback）。

    ⚠️ **不可以指名特定產品** —— 本測試隨範本發送，而同事的工作區裡
       原型那三個產品通常已被 `reset_workspace.py` 清掉。
       要驗的是「單一來源說有誰，bug_paths 就認得誰」，不是「有沒有 CRUX」。
       （2026-08-23：原本硬編 CRUX／投注機器人／七星，在只接了一個產品的範本裡當場紅。）
    """
    import json
    import bug_paths
    cfg = json.loads(io.open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(np.__file__))),
                     "config", "products.json"), encoding="utf-8").read())
    want = [p["id"] for p in cfg["products"]]
    assert set(bug_paths.PRODUCTS) == set(want), u"沒走到 products.json，可能退回了 fallback"
    for p in cfg["products"]:
        assert bug_paths.ID_PREFIX[p["id"]] == p["bug_prefix"]
        assert bug_paths.PRODUCT_DIRS[p["id"]] == p["docs_dir"]
        for alias in p.get("aliases") or []:
            assert bug_paths.PRODUCT_DIRS[alias] == p["docs_dir"]


def test_products_json格式正確():
    """設定檔壞掉時 bug_paths 會靜默退回 fallback —— 這裡直接驗真檔。

    ⚠️ **不斷言「一定有產品」** —— 剛匯出的範本 products 就是空的，
      而範本必須能通過自己的測試（`export_template.py` 的驗收條件之一）。
      這裡驗的是**結構**：有產品的話，每個都要欄位齊全。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(np.__file__)))
    data = json.loads(io.open(os.path.join(root, "config", "products.json"), encoding="utf-8").read())
    assert isinstance(data.get("products"), list)
    assert data.get("common_handovers")
    for p in data["products"]:
        for key in ("id", "docs_dir", "bug_prefix", "skill", "handovers"):
            assert key in p, "%s 缺 %s" % (p.get("id"), key)


def test_骨架不得留下會被D5判成斷連結的檔案指標(sandbox):
    """★ 迴歸：骨架原本寫 `docs/X/<檔>.md`，反引號裡是 .md 結尾 ——
    `lint_docs` D5 會當成真的檔案指標去找，**同事第一次照做就看到紅的**，
    而 new_product 自己印的驗收語卻是「lint 應為綠」（2026-08-22 修）。
    """
    import io
    import re
    _run("--id", "丙", "--docs-dir", "Gamma", "--bug-prefix", "GAMMA",
         "--alias", "gamma")
    skill = os.path.join(np.ROOT, ".claude", "skills", "gamma", "SKILL.md")
    text = io.open(skill, encoding="utf-8").read()
    refs = re.findall(r"`([^`]+\.md)`", text)
    placeholders = [r for r in refs if "<" in r or ">" in r]
    assert placeholders == [], (
        u"骨架的反引號裡留了佔位符檔名，D5 會當成真檔案去找並報斷連結：%s" % placeholders)


def test_不得寫進真實repo的平台設定(sandbox):
    """★ 迴歸：`PLATFORM_PRODUCTS_JSON` 原本是模組層常數，
    import 當下就固定成真實路徑 —— 測試沙箱只 monkeypatch `ROOT`，
    於是**測試把 gamma／lotto 寫進了真的 `tools/test_platform/registry/products.json`**
    （2026-08-23 實際發生，靠 commit 前的語意比對才發現）。

    路徑一律跟著 `ROOT` 走，這條釘住它。
    """
    import os as _os
    assert np.platform_products_json().startswith(np.ROOT), \
        "平台設定路徑沒跟著沙箱的 ROOT 走，會污染真實 repo"
    _run("--id", "丁", "--docs-dir", "Delta", "--bug-prefix", "DELTA", "--alias", "delta")
    real = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
        "tools", "test_platform", "registry", "products.json")
    assert "delta" not in io.open(real, encoding="utf-8").read(), "寫進真實 repo 了"


def test_接新產品會在INDEX建好分區(tmp_path, monkeypatch):
    """★ 沒有分區的話，**平台的「寫檔順便登記索引」永遠不會生效**。

    2026-08-23 實跑：範本的 `docs/INDEX.md` 只有「共通」一節，而 `new_product.py`
    只在最後的提示文字裡叫人「記得登記」——
    照本工作區自己的教訓，靠自律的規範必然漂移（`new_bug_doc.py` 就是同一個教訓）。
    """
    idx = tmp_path / "INDEX.md"
    idx.write_text("# docs 文件索引\n\n## 共通（工作區維護，跨產品）\n\n| 檔案 | 內容 |\n| --- | --- |\n",
                   encoding="utf-8")
    ctx = dict(pid="樂透", label="樂透", docs_dir="樂透", skill="lotto", today="2026-08-23")
    ok, why = np.add_index_section(str(idx), ctx)
    assert ok, why
    got = idx.read_text(encoding="utf-8")
    assert "## 樂透 專案" in got
    # ⚠️ 一定要有 `### ` 子節 —— 平台照子節登記，只有 `##` 的話它挑不到節
    assert got.count("\n### ") >= 3, got
    assert "樂透_驗證交接.md" in got, u"交接活文件沒被登記"

    # 冪等：再跑一次不會重複追加
    ok2, why2 = np.add_index_section(str(idx), ctx)
    assert not ok2 and "已有" in why2
    assert idx.read_text(encoding="utf-8") == got


# ── 環境設定骨架（2026-08-24 新增）────────────────────────
def test_接產品會放好環境設定骨架(sandbox):
    """★ 使用者：「初始化接產品時，環境設定應要可以在 UI 上進行…
    必須提供範例格式讓接產品的人知道該如何設定」。

    骨架比「提示去補」強：打開檔案時該填的層級已經在那裡，
    人只要把 `<後台網址>` 換掉，不會漏層級也不會把 slug 拼錯。
    """
    tmp, _ = sandbox
    env = tmp / "config" / "environments.json"
    env.write_text('{\n  "crux": { "qat": { "backend_url": "http://x/" } }\n}\n', encoding="utf-8")
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    data = json.loads(env.read_text(encoding="utf-8"))
    assert "lotto" in data, "接產品後應該有這個 slug 的骨架"
    assert data["lotto"]["qat"]["backend_url"].startswith("http://<")
    assert "password" in json.dumps(data["lotto"], ensure_ascii=False)


def test_骨架用文字插入_不重排既有內容(sandbox):
    """⛔ 迴歸：第一版用 `json.dumps(indent=2)` 整份寫回 ——
    而 `config/environments.json` 刻意把小物件寫成一行，
    結果改一個產品、diff 卻是整份檔（實測 118 增 21 刪）。

    平台的設定檔存回守同一條（`core/config_files.py` 的 `test_存回不重排版`）。
    """
    tmp, _ = sandbox
    env = tmp / "config" / "environments.json"
    compact = ('{\n  "connectivity_check": [\n'
               '    { "name": "A", "url": "http://a/" }\n  ],\n'
               '  "crux": { "qat": { "backend_url": "http://x/" } }\n}\n')
    env.write_text(compact, encoding="utf-8")
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    after = env.read_text(encoding="utf-8")
    assert '{ "name": "A", "url": "http://a/" }' in after, "既有的一行式物件被攤開了"
    assert '"crux": { "qat": { "backend_url": "http://x/" } }' in after
    json.loads(after)


def test_不可以寫到真的設定檔(sandbox):
    """⛔⛔ 迴歸：第一版把路徑寫成**模組層常數** `ENVIRONMENTS_JSON`，
    而 sandbox 只 monkeypatch `ROOT` —— 於是**跑一次 pytest 就把骨架寫進了
    真的 `config/environments.json`**，還順手把整份檔重排版（2026-08-24 實際發生）。

    同一支測試檔在上面早就對 `PLATFORM_PRODUCTS_JSON` 記過一模一樣的教訓。
    ★ 正解是**寫成函式、在呼叫當下由 `ROOT` 算**。
    """
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "config", "environments.json")
    before = io.open(real, encoding="utf-8").read() if os.path.isfile(real) else None
    tmp, _ = sandbox
    (tmp / "config" / "environments.json").write_text("{}\n", encoding="utf-8")
    _run("--id", "樂透", "--docs-dir", "樂透", "--bug-prefix", "LOTTO", "--alias", "lotto")
    if before is not None:
        assert io.open(real, encoding="utf-8").read() == before, "動到了真的 config/environments.json"
    assert np.environments_json() == os.path.join(np.ROOT, "config", "environments.json")
