# -*- coding: utf-8 -*-
"""`scripts/lint_docs.py` 的 D7「帶裁定來源的規格行被刪改」檢查。

用途：這是本工作區最嚴重的失誤型態的守門 —— **把缺陷改寫成規格**。
      2026-08-14 有 session 實測到系統行為與文件不符，卻把文件改成配合系統，
      等於用測試者的手把 bug 合法化（JIRA CRUX-983）。
      當時被覆蓋的那段文字**開頭就寫著「這是規格，不是缺陷 —— 使用者 2026-08-12 裁定」**
      —— 來源就在眼前仍然改了，證明「文件內的標注」擋不住，必須有機檢絆線。

      這組測試確保它**該叫的時候叫、不該叫的時候閉嘴**：
      誤報率高的檢查幾天內就會被所有人忽略，比沒有更糟（同 D6 的設計理由）。

前置條件：無。`git_diff_vs_head` 一律以 monkeypatch 注入固定 diff，不依賴真實 repo 狀態。
使用方式：`pytest tests/tooling/test_lint_docs_spec_edit.py -q`
"""
import pytest

import lint_docs


@pytest.fixture
def fake_diff(monkeypatch):
    """注入一段固定的 `git diff -U0 HEAD` 輸出。"""
    def _set(text):
        monkeypatch.setattr(lint_docs, "git_diff_vs_head", lambda paths: text)
    return _set


def _diff(file_name, removed=(), added=()):
    """組出最小可解析的 unified diff。"""
    lines = ["diff --git a/docs/CRUX/%s b/docs/CRUX/%s" % (file_name, file_name),
             "--- a/docs/CRUX/%s" % file_name,
             "+++ b/docs/CRUX/%s" % file_name,
             "@@ -1,1 +1,1 @@"]
    lines += ["-" + r for r in removed]
    lines += ["+" + a for a in added]
    return "\n".join(lines) + "\n"


def _run(product="CRUX"):
    return lint_docs.check_spec_edits(product)


# ── 該叫的時候要叫 ──────────────────────────────────────────────

def test_刪掉帶裁定的行會被抓到(fake_diff):
    """CRUX-983 的真實情境：把「使用者裁定的規格」整段改寫成新行為。"""
    fake_diff(_diff(
        "CRUX_綜合報表.md",
        removed=["**這是規格，不是缺陷** —— 使用者 2026-08-12 裁定：「期數狀態為結算，才會顯示出來」。"],
        added=["綜合報表**會顯示未結算期**了（笔数／总投納入、盈亏為 0）。"]))
    w = _run()
    assert w and w[0].startswith("D7 規格被改動")
    assert "缺陷" in w[0] and "開單" in w[0]
    assert any("CRUX_綜合報表.md" in x for x in w)


@pytest.mark.parametrize("body", [
    "> 這是規格，不是缺陷 —— 週報表同樣如此",
    "CRUX-944「今日顯示暫無數據」屬 **as-designed**。",
    "使用者 2026-08-12 裁示：多彩種取 max",
    "📌 規格（來源：Rovan Kuo 2026-08-06）：上級取下級的 max",
])
def test_各種裁定字樣都認得(fake_diff, body):
    fake_diff(_diff("CRUX_綜合報表.md", removed=[body], added=["改寫後的內容"]))
    assert _run(), "帶裁定來源的行被刪改卻沒被抓到：%s" % body


def test_多檔多行會一起列出並去重(fake_diff):
    dup = "使用者 2026-08-12 裁定：只顯示已結算"
    text = (_diff("A.md", removed=[dup, "as-designed 的另一條"], added=["x"])
            + _diff("B.md", removed=[dup], added=["y"]))
    w = _run()
    fake_diff(text)
    w = _run()
    # 同一句話出現在兩個檔 → 算兩筆（檔名不同）；同檔重複才去重
    assert "共 3 行" in w[0]
    assert any("A.md" in x for x in w) and any("B.md" in x for x in w)


# ── 不該叫的時候要閉嘴（誤報防線）──────────────────────────────

def test_純觀測值被更新不會誤報(fake_diff):
    """CRUX-969 的真實情境：文件記的是上次量到的下限，RD 明講改了 → 更新文件是對的。"""
    fake_diff(_diff(
        "UI元素對照_總監後台.md",
        removed=["    &fromDate=&toDate=          # fromDate 須 ≥ 2025-01-02"],
        added=["    &fromDate=&toDate=          # fromDate 須 ≥ 2025-01-01"]))
    assert _run() == [], "只是更新觀測值，不該觸發 D7"


def test_交接活文件不納入檢查(fake_diff):
    """交接檔是**狀態型**：劃掉待辦是它的正常運作（CLAUDE.md §8.3 配套②(a)），
    而 T／D／B 列又常引用「使用者×× 裁示」。

    ⚠️ 這條是 D7 上線當天被自己的誤報打臉後補的 ——
       原本每劃掉一條待辦就叫一次，那種檢查幾天內就會被所有人忽略。
    """
    text = ('diff --git a/docs/CRUX/CRUX_功能驗證交接.md b/docs/CRUX/CRUX_功能驗證交接.md\n'
            '--- a/docs/CRUX/CRUX_功能驗證交接.md\n'
            '+++ b/docs/CRUX/CRUX_功能驗證交接.md\n'
            '@@ -1,1 +1,1 @@\n'
            '-| T17 | 某事 —— **使用者 2026-08-14 裁示交由其他 session 調整** |\n'
            '+| ~~T17~~ | ✅ 完成 |\n')
    fake_diff(text)
    assert _run() == [], "劃掉交接檔的待辦不該觸發 D7"


def test_機制文件仍受保護(fake_diff):
    """排除交接檔**不能**連帶把機制文件也放掉 —— 規格就住在那裡。"""
    fake_diff(_diff("CRUX_綜合報表.md",
                    removed=["使用者 2026-08-12 裁定：只顯示已結算"], added=["改寫"]))
    assert _run(), "機制文件的規格行仍必須被保護"


def test_只新增不刪除不會誤報(fake_diff):
    """補一段新的規格說明是正常的知識回寫，不是覆蓋。"""
    fake_diff(_diff("CRUX_綜合報表.md",
                    added=["> 使用者 2026-08-14 裁定：本行為屬規格"]))
    assert _run() == []


def test_沒有異動時不叫(fake_diff):
    fake_diff("")
    assert _run() == []


def test_git不可用時靜默跳過(monkeypatch):
    monkeypatch.setattr(lint_docs, "git_diff_vs_head", lambda paths: None)
    assert lint_docs.check_spec_edits("CRUX") == []


def test_diff檔頭本身不會被當成刪除行(fake_diff):
    """`--- a/path` 也是以 `-` 開頭 —— 若沒排除會把檔名當內容掃。"""
    fake_diff(_diff("CRUX_裁定範例.md", removed=["普通內容"], added=["普通內容2"]))
    assert _run() == [], "檔名含「裁定」二字不該讓 diff 檔頭觸發警告"


# ── 檔名解析（中文路徑）────────────────────────────────────────

def test_中文檔名可正確解析(fake_diff):
    """本專案文件全是中文檔名 —— 解析不出來會顯示成 `?`，警告等於沒用。"""
    fake_diff(_diff("CRUX_綜合報表.md",
                    removed=["使用者 2026-08-12 裁定：只顯示已結算"], added=["x"]))
    w = _run()
    assert any("CRUX_綜合報表.md：" in x for x in w[1:])


def test_git加引號的舊格式也要能解析(fake_diff):
    """未關 `core.quotepath` 時 git 會輸出 `+++ "b/docs/…"`（引號在 b/ 之前）。

    腳本已用 `-c core.quotepath=false` 關掉，但保留這條防呆 ——
    換 git 版本或有人改了呼叫方式時，至少檔名不會退化成 `?`。
    """
    text = ('diff --git "a/docs/CRUX/X.md" "b/docs/CRUX/X.md"\n'
            '--- "a/docs/CRUX/X.md"\n'
            '+++ "b/docs/CRUX/X.md"\n'
            '@@ -1,1 +1,1 @@\n'
            '-使用者 2026-08-12 裁定：只顯示已結算\n'
            '+改寫\n')
    fake_diff(text)
    w = _run()
    assert any("X.md：" in x for x in w[1:]), w


# ── 輸出可讀性 ──────────────────────────────────────────────────

def test_超過上限會摘要而不是刷屏(fake_diff):
    removed = ["第 %d 條 使用者 2026-08-12 裁定" % i for i in range(20)]
    fake_diff(_diff("CRUX_綜合報表.md", removed=removed, added=["x"]))
    w = _run()
    assert "共 20 行" in w[0]
    # 首行摘要 ＋ 上限行數 ＋ 一行「另有 N 行」
    assert len(w) == 1 + lint_docs.SPEC_MAX_SHOWN + 1
    assert "另有 %d 行" % (20 - lint_docs.SPEC_MAX_SHOWN) in w[-1]


def test_過長的行會截斷(fake_diff):
    fake_diff(_diff("CRUX_綜合報表.md",
                    removed=["使用者 2026-08-12 裁定：" + "長" * 200], added=["x"]))
    w = _run()
    assert any(x.endswith("…") for x in w[1:])


# ── D12：產品要在 docs/INDEX.md 有分區（含子節）──────────────────
#
# 2026-08-23 實跑：範本接了 CRUX（用**搬資產**的方式，沒走 new_product.py），
# 而 `INDEX.md` 只有「共通」一節 —— `writeback` 四個必做的第一條沒有落點，
# **平台寫機制文件時的自動登記也永遠不會生效**。而 lint 全綠。

def test_D12抓得到沒有分區的產品(tmp_path, monkeypatch):
    L = lint_docs
    root = tmp_path
    (root / "docs").mkdir()
    (root / "config").mkdir()
    (root / "docs" / "INDEX.md").write_text(
        "# docs 文件索引\n\n## 共通（工作區維護，跨產品）\n", encoding="utf-8")
    (root / "config" / "products.json").write_text(
        '{"products":[{"id":"樂透","docs_dir":"docs/樂透"}]}', encoding="utf-8")
    monkeypatch.setattr(L, "ROOT", str(root))
    errs = L.check_index_sections()
    assert errs and "樂透" in errs[0] and "沒有分區" in errs[0]


def test_D12也抓得到有大節卻沒有子節(tmp_path, monkeypatch):
    """★ 只有 `##` 而沒有 `###` 時，平台挑不到要登記到哪一格 —— 等於還是沒落點。"""
    L = lint_docs
    root = tmp_path
    (root / "docs").mkdir()
    (root / "config").mkdir()
    (root / "docs" / "INDEX.md").write_text(
        "# docs\n\n## 樂透 專案\n\n| 檔案 | 說明 |\n| --- | --- |\n", encoding="utf-8")
    (root / "config" / "products.json").write_text(
        '{"products":[{"id":"樂透","docs_dir":"docs/樂透"}]}', encoding="utf-8")
    monkeypatch.setattr(L, "ROOT", str(root))
    errs = L.check_index_sections()
    assert errs and "子節" in errs[0]


def test_D12對完整的索引不報():
    """本 repo 自己要是綠的。"""
    assert lint_docs.check_index_sections() == []


# ── W：repo 根目錄的殘留（session 留下的截圖與 page snapshot）──────
#
# 2026-08-23 實跑：任務 session 用 MCP 截圖時只帶檔名，檔案就落在 repo 根目錄
# （工具的預設是 cwd）；page snapshot 的 .yml 也一樣。
# `CLAUDE.md` §8.3 明訂不得留在 repo 根目錄，而 **D11 只看已版控的檔案** ——
# 在此之前沒有任何機制會報。

def test_殘留檢查抓得到未版控又沒分類的檔(monkeypatch):
    import export_template as X
    monkeypatch.setattr(X, "unclassified_untracked",
                        lambda root: ["截圖_某頁.png", "page-2026.yml"])
    got = lint_docs.check_workspace_residue()
    assert got and "2 個" in got[0]
    assert "截圖_某頁.png" in got[0]
    # 兩種可能都要講 —— 處置是相反的（刪掉 vs 去白名單分類）
    assert "刪掉" in got[0] and "白名單" in got[0]


def test_沒有殘留時不報(monkeypatch):
    import export_template as X
    monkeypatch.setattr(X, "unclassified_untracked", lambda root: [])
    assert lint_docs.check_workspace_residue() == []
