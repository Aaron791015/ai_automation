"""離線驗證三彩種批次順序與防重送；不登入、不建立 QAT 注單。"""
import pytest

from tools.xzh_qa.real_combo_batch import (
    BatchJournal, MarketClosed, run_batch, run_multi_level_batch,
)


def targets():
    return [{"game": game, "game_id": game, "play_type_id": str(index),
             "label": str(index), "relation_mode": "unrelated"}
            for game in ("uk", "hk", "bingo") for index in range(2)]


def test_all_frontend_before_single_backend_login_and_resume(tmp_path):
    events = []
    items = targets()
    path = tmp_path / "batch.jsonl"

    def place(target):
        events.append(("bet", target["game"], target["label"]))
        assert BatchJournal(path).rows[BatchJournal.key(target)]["status"] == "betting"
        return {"issue": "123456"}

    def check(target):
        events.append(("check", target["game"], target["label"]))
        assert target["issue"] == "123456"
        return {"actual_rows": [{"actualShareAmount": 0}]}

    login = lambda: events.append(("login",))
    assert run_batch(items, BatchJournal(path), place, login, check) == []
    assert events == ([("bet", t["game"], t["label"]) for t in items] +
                      [("login",)] + [("check", t["game"], t["label"]) for t in items])
    assert all(r["settings_retained"] for r in BatchJournal(path).rows.values())
    events.clear()
    assert run_batch(items, BatchJournal(path), place, login, check) == []
    assert events == []


@pytest.mark.parametrize("status", ["legacy_audit", "betting", "partial", "bet_unknown",
                                    "checking", "configuring", "readback", "backend_failed"])
def test_uncertain_targets_never_automatically_rebet(tmp_path, status):
    journal = BatchJournal(tmp_path / "batch.jsonl")
    target = targets()[0]
    journal.record(target, status)

    def forbidden(*args):
        pytest.fail("待稽核注單不可重送，也不可假裝完成")

    assert len(run_batch([target], journal, forbidden, forbidden, forbidden)) == 1
    assert journal.rows[journal.key(target)]["status"] == status


def test_backend_login_failure_resumes_without_betting(tmp_path):
    path = tmp_path / "batch.jsonl"
    items = targets()

    def login_failure():
        raise RuntimeError("登入失敗")

    with pytest.raises(RuntimeError, match="登入失敗"):
        run_batch(items, BatchJournal(path), lambda t: {"issue": "123456"},
                  login_failure, lambda t: {})

    def forbidden(target):
        pytest.fail("已確認下注不可重送")

    assert run_batch(items, BatchJournal(path), forbidden, lambda: None, lambda t: {}) == []


def test_bet_exception_and_backend_exception_are_not_passes(tmp_path):
    path = tmp_path / "batch.jsonl"
    items = targets()[:2]

    def place(target):
        if target == items[0]:
            raise TimeoutError("送出後未取得確認")
        return {}

    def check(target):
        raise AssertionError("占成不為零")

    assert len(run_batch(items, BatchJournal(path), place, lambda: None, check)) == 2
    assert [r["status"] for r in BatchJournal(path).rows.values()] == ["bet_unknown", "backend_failed"]


def test_closed_market_can_retry_without_prior_bet(tmp_path):
    journal = BatchJournal(tmp_path / "batch.jsonl")
    target = targets()[0]

    def closed(target):
        raise MarketClosed("未開盤")

    assert len(run_batch([target], journal, closed, lambda: pytest.fail("不可登入"), lambda t: {})) == 1
    assert len(run_batch([target], journal, lambda t: pytest.fail("預設不可重試"),
                         lambda: None, lambda t: {})) == 1
    assert run_batch([target], journal, lambda t: {}, lambda: None, lambda t: {},
                     resume_closed=True) == []


def test_interrupt_after_submit_blocks_automatic_resend(tmp_path):
    path = tmp_path / "batch.jsonl"
    target = targets()[0]

    def interrupted(target):
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_batch([target], BatchJournal(path), interrupted, lambda: None, lambda t: {})
    assert BatchJournal(path).rows[BatchJournal.key(target)]["status"] == "betting"


def test_multi_level_backend_does_not_skip_or_overwrite_other_levels(tmp_path):
    """九層驗證：下注只做一次，但每層都要各驗一輪且各自留下紀錄。

    這條擋的是「key 少了層級維度」造成的靜默失敗——第一層驗完之後其餘八層
    會被 `status == "verified"` 判成已完成而整批跳過，批次卻不報任何錯。
    """
    path = tmp_path / "batch.jsonl"
    items = targets()[:2]
    levels = ["aaa999", "aaa888", "aaa222"]
    events = []

    def place(target):
        events.append(("bet", target["label"]))
        return {"issue": "123456", "bet_message": "注單#1"}

    def login(level):
        events.append(("login", level))

    def check(target, level):
        events.append(("check", level, target["label"]))
        assert target["agent_level"] == level
        assert target["issue"] == "123456"
        return {"before_amount": "500", "after_amount": "0"}

    assert run_multi_level_batch(items, BatchJournal(path), place, levels, login, check) == []
    assert events == [("bet", t["label"]) for t in items] + [
        step for level in levels
        for step in [("login", level)] + [("check", level, t["label"]) for t in items]
    ]
    rows = BatchJournal(path).rows
    # 2 筆下注（不帶層級）＋ 3 層 × 2 目標各自獨立的後台紀錄。
    assert len(rows) == len(items) * (1 + len(levels))
    for level in levels:
        for target in items:
            row = rows[BatchJournal.key(target, level)]
            assert row["status"] == "verified" and row["agent_level"] == level
            assert row["before_amount"] == "500" and row["after_amount"] == "0"

    # 續跑：注單不重下、已驗層級不重驗。
    events.clear()
    assert run_multi_level_batch(items, BatchJournal(path),
                                 lambda t: pytest.fail("已確認下注不可重送"),
                                 levels, login, check) == []
    assert events == []


def test_multi_level_resumes_only_missing_levels(tmp_path):
    """某一層中斷後續跑，只補跑缺的層級，不重下注也不重驗已完成的層級。"""
    path = tmp_path / "batch.jsonl"
    items = targets()[:1]

    def check_first_level_only(target, level):
        if level != "aaa999":
            raise RuntimeError("本次只跑第一層")
        return {}

    assert len(run_multi_level_batch(items, BatchJournal(path), lambda t: {"issue": "1"},
                                     ["aaa999", "aaa888"], lambda level: None,
                                     check_first_level_only)) == 1
    checked = []

    def check(target, level):
        checked.append(level)
        return {}

    assert run_multi_level_batch(items, BatchJournal(path),
                                 lambda t: pytest.fail("已確認下注不可重送"),
                                 ["aaa999", "aaa888"], lambda level: None, check,
                                 resume_backend_failed=True) == []
    assert checked == ["aaa888"]
