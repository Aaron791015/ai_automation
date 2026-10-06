# -*- coding: utf-8 -*-
"""`scripts/analyze_run.py`（執行結果三分類）的回歸測試。

用途：這支腳本要回答「這批能不能發」，因此**分類錯誤的代價不對稱** ——
      把真失敗誤判成環境雜訊會讓缺陷溜過發版，反過來只是多看幾條。
      ★ 最重要的回歸：**比對已知 Bug 單時要看 `name` 與 `fullName` 兩個欄位** ——
      allure 的 fullName 是模組路徑，單號寫在 name（中文標題）裡；
      只看其中一個會讓 8 條已知問題全被當成新失敗（2026-08-22 實測踩到）。
前置條件：無（在 tmp_path 上偽造 allure-results，不讀真實 reports/）。
使用方式：`pytest tests/tooling/test_analyze_run.py -q`
"""
import json
import os

import analyze_run as ar


def _res(tmp_path, recs):
    d = tmp_path / "allure-results"
    d.mkdir(exist_ok=True)
    for i, r in enumerate(recs):
        (d / ("%d-result.json" % i)).write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return str(d)


def _rec(name="t", status="failed", msg="", full="tests.x#t"):
    return {"name": name, "fullName": full, "status": status,
            "statusDetails": {"message": msg}, "start": 1755000000000}


# ── 分類 ────────────────────────────────────────────────────
def test_環境問題被歸為雜訊():
    for msg in ["令牌过期，请重新登录", "TimeoutError: Timeout 30000ms exceeded",
                "net::ERR_CONNECTION_REFUSED"]:
        assert ar.classify({"status": "failed", "msg": msg, "trace": ""}) == "env", msg


def test_前置未備被歸為prereq():
    assert ar.classify({"status": "skipped", "msg": "", "trace": ""}) == "prereq"
    assert ar.classify({"status": "failed", "msg": "未跑 Z0，wbot_target 不存在", "trace": ""}) == "prereq"


def test_分不出來一律歸真失敗():
    """★ 判準刻意保守：誤判成雜訊會讓缺陷溜過發版。"""
    assert ar.classify({"status": "failed", "msg": "AssertionError: 期望 103.0，實際 102.0",
                        "trace": ""}) == "real"
    assert ar.classify({"status": "failed", "msg": "", "trace": ""}) == "real"


# ── 比對已知 Bug 單 ──────────────────────────────────────────
BUGS = [("CRUX-009", "open", "⚠️ 待補", "報表"),
        ("CRUX-042", "fixed", "tests/crux/backend/test_two_factor_log.py::test_2fa", "日誌")]


def test_單號寫在中文標題也要比對得到():
    """★ 回歸保障：只看 fullName 會漏掉全部（單號多半在 @allure.title 的中文標題裡）。"""
    rec = _rec(name="CRUX-009／JIRA CRUX-873：匯總的会员盈亏須等於明細逐注合計",
               full="tests.crux.backend.test_profit#test_summary")
    rec = {"name": rec["name"], "full": rec["fullName"], "msg": "", "trace": ""}
    hit = ar.match_known(rec, BUGS)
    assert hit and hit[0] == "CRUX-009" and hit[2] == "案例名含單號"


def test_regression欄命中nodeid():
    rec = {"name": "兩步驗證日誌", "full": "tests/crux/backend/test_two_factor_log.py::test_2fa",
           "msg": "", "trace": ""}
    hit = ar.match_known(rec, BUGS)
    assert hit and hit[0] == "CRUX-042" and hit[2] == "regression 欄"


def test_待補的regression欄不可當成命中():
    """`⚠️ 待補` 是佔位字串，拿它去比對會亂命中。"""
    rec = {"name": "無關案例", "full": "tests/x.py::test_y", "msg": "", "trace": ""}
    assert ar.match_known(rec, BUGS) is None


def _allure(full, name="案例"):
    """allure 實際寫出的 fullName 是 `模組#函式`，不是 pytest nodeid。"""
    return {"name": name, "full": full, "msg": "", "trace": ""}


def test_regression欄的nodeid要命中allure的fullName():
    """★ 回歸保障（2026-09-23）：regression 欄寫 `路徑.py::函式`，allure 是 `模組#函式`，
    舊版只用 `::` 切，已知失敗全被當成新失敗。"""
    hit = ar.match_known(_allure("tests.crux.backend.test_two_factor_log#test_2fa"), BUGS)
    assert hit and hit[0] == "CRUX-042" and hit[2] == "regression 欄"


def test_regression欄比對要完全相等不可前綴命中():
    """`::test_2fa` 不可命中 `#test_2fa_backup`，否則新失敗會被誤歸為已知問題。"""
    assert ar.match_known(_allure("tests.crux.backend.test_two_factor_log#test_2fa_backup"), BUGS) is None
    assert ar.match_known(_allure("tests.crux.backend.test_two_factor_log_v2#test_2fa"), BUGS) is None


def test_regression欄帶參數與類別也要命中():
    bugs = [("XZH-001", "open", "tests/xzh/test_a.py::TestB::test_c[chromium]", "設定")]
    hit = ar.match_known(_allure("tests.xzh.test_a.TestB#test_c"), bugs)
    assert hit and hit[0] == "XZH-001"


def test_regression欄只寫檔案時整檔守門():
    """實際單上有「檔案；附註」的寫法：同模組的案例都算命中，其他模組不算。"""
    bugs = [("XZH-007", "fixed", "tests/xzh/test_two_sides.py；2026-09-17 三十組皆存在", "賠率差")]
    hit = ar.match_known(_allure("tests.xzh.test_two_sides#test_any"), bugs)
    assert hit and hit[0] == "XZH-007"
    assert ar.match_known(_allure("tests.xzh.test_two_sides_more#test_any"), bugs) is None


# ── 整體流程 ────────────────────────────────────────────────
def test_統計與離開碼(tmp_path, capsys):
    d = _res(tmp_path, [
        _rec("通過", "passed"),
        _rec("真失敗", "failed", "AssertionError: 1 != 2"),
        _rec("環境", "failed", "令牌过期，请重新登录"),
        _rec("前置", "skipped", ""),
    ])
    code = ar.main(["--results", d])
    out = capsys.readouterr().out
    assert code == 1                       # 有真失敗 → 非零
    assert "總計 4 條：通過 1／非通過 3" in out
    assert "新失敗        1 條" in out and "前置未備        1 條" in out and "環境雜訊        1 條" in out


def test_無真失敗時回零(tmp_path, capsys):
    d = _res(tmp_path, [_rec("通過", "passed"), _rec("環境", "failed", "TimeoutError")])
    assert ar.main(["--results", d]) == 0
    assert "✅ 無新失敗" in capsys.readouterr().out


def test_找不到結果時不當機(tmp_path, capsys):
    d = tmp_path / "empty"
    d.mkdir()
    assert ar.main(["--results", str(d)]) == 0
    assert "找不到 allure 結果" in capsys.readouterr().out


def test_since過濾舊結果(tmp_path):
    d = _res(tmp_path, [_rec("舊", "failed", "x")])
    # start 是 2026-08-12 附近；用更晚的日期過濾應該全部濾掉
    assert ar.load_results(d, since=99999999999) == []
