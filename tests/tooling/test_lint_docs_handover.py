# -*- coding: utf-8 -*-
"""`scripts/lint_docs.py` 的 D6「交接活文件是否跟上進度」檢查。

用途：交接紀律先前**完全靠自律** —— 工作區其他該守的事都有 lint 擋（文件 D1–D5、
      截圖 W1–W7），唯獨「收尾要更新交接檔」沒有。本工作區自己的教訓是
      「靠人自律的規範必然漂移」（見 `tools/qa_common/shot.py`），故補上 D6。
      這組測試確保它**該叫的時候叫、不該叫的時候閉嘴** —— 一個會誤報的檢查
      幾天內就會被所有人忽略，比沒有更糟。

前置條件：無。`git_last_commit_date` 一律以 monkeypatch 注入，不依賴真實 repo 狀態
          （否則測試結果會隨今天有沒有人 commit 而變動）。
使用方式：`pytest tests/tooling/test_lint_docs_handover.py -q`
"""
import io
import os

import pytest

import lint_docs


def _doc(tmp_path, name, head):
    p = tmp_path / name
    io.open(str(p), "w", encoding="utf-8", newline="\n").write(head)
    return str(p)


@pytest.fixture
def fake_commit(monkeypatch):
    """把「該範圍最新 commit 日期」換成可控值。"""
    def _set(date):
        monkeypatch.setattr(lint_docs, "git_last_commit_date", lambda scope: date)
    return _set


# ── 日期解析 ────────────────────────────────────────────────────

@pytest.mark.parametrize("head, expect", [
    ("# X\n\n> **最後更新：2026-08-13**（每次收尾更新）\n", (2026, 8, 13)),
    ("# CRUX 效能驗證 — 交接說明（2026-08-06 更新）\n", (2026, 8, 6)),   # H1 內含日期的舊格式
    ("# X\n\n> 最後更新 2026-01-02\n", (2026, 1, 2)),
])
def test_檔頭日期可解析(tmp_path, head, expect):
    assert lint_docs.handover_updated_date(_doc(tmp_path, "a_驗證交接.md", head)) == expect


def test_沒有更新字樣的日期不會被誤認(tmp_path):
    """內文到處都是實測日、佈版日 —— 只認帶「更新」二字那一行，否則抓到不相干的值。"""
    head = "# X\n\n> 2026-08-01 實測於總監2\n\n## 1. blocker\n\n2026-08-05 佈版\n"
    assert lint_docs.handover_updated_date(_doc(tmp_path, "a_驗證交接.md", head)) is None


def test_只掃前15行(tmp_path):
    head = "# X\n" + "\n" * 20 + "> **最後更新：2026-08-13**\n"
    assert lint_docs.handover_updated_date(_doc(tmp_path, "a_驗證交接.md", head)) is None


# ── 過期判定 ────────────────────────────────────────────────────

@pytest.mark.parametrize("doc_date, commit_date, should_warn", [
    ("2026-08-13", (2026, 8, 13), False),   # 同日
    ("2026-08-12", (2026, 8, 13), False),   # 落後 1 天＝容許值上限
    ("2026-08-11", (2026, 8, 13), True),    # 落後 2 天 → 警告
    ("2026-08-20", (2026, 8, 13), False),   # 文件比 commit 新（改了還沒 commit）
])
def test_落後超過一天才警告(tmp_path, fake_commit, doc_date, commit_date, should_warn):
    fake_commit(commit_date)
    path = _doc(tmp_path, "測試_驗證交接.md", "# X\n\n> **最後更新：%s**\n" % doc_date)
    w = lint_docs.check_handovers("CRUX", {"測試_驗證交接.md": path})
    assert bool(w) is should_warn, w
    if should_warn:
        assert w[0].startswith("D6 交接檔過期")


def test_缺日期會被指出而不是靜默通過(tmp_path, fake_commit):
    fake_commit((2026, 8, 13))
    path = _doc(tmp_path, "測試_驗證交接.md", "# X\n\n沒有任何日期\n")
    w = lint_docs.check_handovers("CRUX", {"測試_驗證交接.md": path})
    assert len(w) == 1 and w[0].startswith("D6 交接檔無日期")


# ── 不該被檢查的檔案 ────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "交接清單_BOT-799_STG.md",          # 一次性交接清單
    "交接_SideEffect待驗_2026-08-13.md",  # 批次 side effect 快照
    "CRUX_綜合報表.md",                  # 一般機制文件
])
def test_非活文件不檢查(tmp_path, fake_commit, name):
    """一次性快照本來就該停在當時的日期，拿它跟最新 commit 比是誤報。"""
    fake_commit((2026, 8, 13))
    path = _doc(tmp_path, name, "# X\n\n> 2026-01-01 建立\n")
    assert lint_docs.check_handovers("CRUX", {name: path}) == []


# ── 跨產品的工作區維護交接檔（docs/ 直下）────────────────────────

def test_維護交接後綴也算活文件(tmp_path, fake_commit):
    """`docs/共通_工作區維護交接.md` 用的是「維護交接.md」後綴 ——
    HANDOVER_SUFFIX 若只認「驗證交接.md」，這份新檔會完全不被檢查（等於白開）。"""
    fake_commit((2026, 8, 13))
    name = "共通_工作區維護交接.md"
    path = _doc(tmp_path, name, "# X\n\n> **最後更新：2026-08-01**\n")
    w = lint_docs.check_handovers("共通", {name: path})
    assert w and w[0].startswith("D6 交接檔過期")


def test_共通交接檔有登記路徑範圍():
    """沒登記 HANDOVER_SCOPE 會退回 `docs/共通` —— 那個目錄不存在，D6 等於靜默失效。"""
    scope = lint_docs.HANDOVER_SCOPE.get("共通_工作區維護交接.md")
    assert scope, "共通交接檔必須在 HANDOVER_SCOPE 登記負責路徑"
    # 它管的是共用基礎設施，不該把任何 docs/<產品>/ 也算進來（那些各有自己的交接檔）
    assert not [p for p in scope if p.startswith("docs/") and p != "docs/INDEX.md"], scope


def test_共通交接檔在COMMON_HANDOVERS中():
    """它不在任何 `docs/<產品>/` 底下，沒列進 COMMON_HANDOVERS 就掃不到。"""
    assert "共通_工作區維護交接.md" in lint_docs.COMMON_HANDOVERS


def test_共通交接檔未登記索引會被指出(monkeypatch, tmp_path):
    """D2 只掃產品目錄，跨產品檔要靠 check_common 自己補這一檢查。"""
    monkeypatch.setattr(lint_docs, "DOCS", str(tmp_path))
    monkeypatch.setattr(lint_docs, "git_last_commit_date", lambda scope: None)
    _doc(tmp_path, "共通_工作區維護交接.md", "# X\n\n> **最後更新：2026-08-14**\n")
    assert any(w.startswith("D2 未登記") for w in lint_docs.check_common({}))
    assert lint_docs.check_common({"共通_工作區維護交接.md": "有描述"}) == []


def test_沒有git或該範圍無commit時靜默跳過(tmp_path, monkeypatch):
    monkeypatch.setattr(lint_docs, "git_last_commit_date", lambda scope: None)
    path = _doc(tmp_path, "測試_驗證交接.md", "# X\n\n> **最後更新：2020-01-01**\n")
    assert lint_docs.check_handovers("CRUX", {"測試_驗證交接.md": path}) == []


# ── 範圍對應 ────────────────────────────────────────────────────

def test_每份交接檔各自比對自己的路徑(tmp_path, monkeypatch):
    """CRUX 有功能／效能兩份交接檔共用 `docs/CRUX/` ——
    壓測的 commit 不該讓功能線的交接檔顯示過期，反之亦然。"""
    seen = {}

    def fake(scope):
        seen[tuple(scope)] = True
        return (2026, 8, 13)

    monkeypatch.setattr(lint_docs, "git_last_commit_date", fake)
    # ⚠️ scope 自備，不讀 config/products.json —— 測試不該綁在某個實際存在的產品上
    #    （範本匯出後 products 是空的，這條測試曾因此紅掉）
    monkeypatch.setattr(lint_docs, "HANDOVER_SCOPE", dict(
        lint_docs.HANDOVER_SCOPE,
        **{"CRUX_Performance_效能驗證交接.md":
           ["tools/CRUX_Performance", "docs/CRUX/CRUX_Performance_*"],
           "CRUX_功能驗證交接.md":
           ["docs/CRUX", ":(exclude)docs/CRUX/CRUX_Performance_*", "tests/crux"]}))
    names = ["CRUX_功能驗證交接.md", "CRUX_Performance_效能驗證交接.md"]
    by_name = {n: _doc(tmp_path, n, "# X\n\n> **最後更新：2026-08-13**\n") for n in names}
    lint_docs.check_handovers("CRUX", by_name)

    scopes = list(seen)
    assert len(scopes) == 2, "兩份交接檔應各自查自己的路徑，不該共用同一組"
    perf = tuple(lint_docs.HANDOVER_SCOPE["CRUX_Performance_效能驗證交接.md"])
    func = tuple(lint_docs.HANDOVER_SCOPE["CRUX_功能驗證交接.md"])
    assert perf in seen and func in seen
    assert any(s.startswith(":(exclude)") for s in func), \
        "功能線的範圍必須排除 CRUX_Performance_*，否則壓測 commit 會誤報"


def test_未列於對應表者退回產品目錄(tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr(lint_docs, "git_last_commit_date",
                        lambda scope: got.setdefault("s", scope) and None)
    path = _doc(tmp_path, "新產品_驗證交接.md", "# X\n\n> **最後更新：2026-08-13**\n")
    lint_docs.check_handovers("七星", {"新產品_驗證交接.md": path})
    assert got["s"] == ["docs/七星"]
