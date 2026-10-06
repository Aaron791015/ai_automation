# -*- coding: utf-8 -*-
"""`xzh_qa.odds_gap_oplog` 的離線比對邏輯（B108／交接 T66；B109～B111 的新紀錄判定與權限差集）。

前置條件：無；不連線、不改設定。樣本格式取自 2026-09-29 MCP 實測的 `/api/AuditLogs` 回應。
"""
from decimal import Decimal as D

from xzh_qa.odds_gap_oplog import (AuditLogReader, compare_ui_batch, expected_records, for_target, match_expected,
                                   normalize, parse_ui_row, permission_change, ui_time, unexpected_records)


def _row(pid, name, main, sub=None):
    return {"playTypeId": pid, "playTypeName": name, "oddsGap": main, "subOddsGap": sub}


BEFORE = [_row("specialA", "特码A", 0), _row("specialZodiac", "特肖", 0, 0),
          _row("sevenSingle0", "单0 / 大0 / 双7 / 小7", -0.0002), _row("twoWay", "两面", -0.01)]
AFTER = [_row("specialA", "特码A", -0.0001), _row("specialZodiac", "特肖", -0.0001, -0.0001),
         _row("sevenSingle0", "单0 / 大0 / 双7 / 小7", -0.0003), _row("twoWay", "两面", -0.01)]


def _item(i, entity, fields, before, after, operator="aaron01", batch="b1"):
    return {"id": i, "batchId": batch, "batchCount": 3, "topic": "oddsGapSetting", "action": "update",
            "entityId": entity, "fields": fields, "beforeValues": before, "afterValues": after,
            "operatorAccount": operator, "createdAt": "2026-09-29T08:01:36.333143+00:00"}


def test_只列有變動的玩法與欄位_七碼取代表名():
    exp = expected_records(BEFORE, AFTER, "宾果六合彩")
    assert set(exp) == {"宾果六合彩 / 特码A", "宾果六合彩 / 特肖", "宾果六合彩 / 单0"}
    assert exp["宾果六合彩 / 特码A"] == {"fields": ["差分"], "before": [D("0")], "after": [D("-0.0001")]}
    assert exp["宾果六合彩 / 特肖"]["fields"] == ["差分", "副差分"]


def test_改回原值時前後值對調():
    exp = expected_records(AFTER, BEFORE, "宾果六合彩")
    assert exp["宾果六合彩 / 单0"] == {"fields": ["差分"], "before": [D("-0.0003")], "after": [D("-0.0002")]}


def test_操作日志的帳號前綴去掉後與帳號日志同格式():
    r = normalize(_item(1, "aaa222 / 宾果六合彩 / 特码A", ["差分"], [0], [-0.0001]), "aaa222")
    assert r["entity"] == "宾果六合彩 / 特码A" and r["raw_entity"] == "aaa222 / 宾果六合彩 / 特码A"
    assert r["after"] == [D("-0.0001")]


def _records():
    return [normalize(_item(1, "宾果六合彩 / 特码A", ["差分"], [0], [-0.0001])),
            normalize(_item(2, "宾果六合彩 / 特肖", ["差分", "副差分"], [0, 0], [-0.0001, -0.0001])),
            normalize(_item(3, "宾果六合彩 / 单0", ["差分"], [-0.0002], [-0.0003]))]


def test_全部相符():
    m = match_expected(expected_records(BEFORE, AFTER, "宾果六合彩"), _records(), "aaron01")
    assert m["ok"] and len(m["matched"]) == 3 and m["batches"] == ["b1"]


def test_缺漏與值不符分開回報():
    records = _records()[:2]
    records[1]["after"] = [D("-0.0001"), D("0")]
    m = match_expected(expected_records(BEFORE, AFTER, "宾果六合彩"), records, "aaron01")
    assert not m["ok"]
    assert [x["entity"] for x in m["missing"]] == ["宾果六合彩 / 单0"]
    assert [x["entity"] for x in m["mismatched"]] == ["宾果六合彩 / 特肖"]


def test_操作者不符不算相符():
    records = [normalize(_item(1, "宾果六合彩 / 特码A", ["差分"], [0], [-0.0001], operator="aaa111"))]
    m = match_expected({"宾果六合彩 / 特码A": {"fields": ["差分"], "before": [D(0)], "after": [D("-0.0001")]}},
                       records, "aaron01")
    assert not m["ok"] and m["mismatched"][0]["reason"] == "操作者、類型或動作不符"


def test_未改動玩法出現紀錄列為多出():
    records = _records() + [normalize(_item(9, "宾果六合彩 / 两面", ["差分"], [-0.01], [-0.01]))]
    m = match_expected(expected_records(BEFORE, AFTER, "宾果六合彩"), records, "aaron01")
    assert [r["entity"] for r in unexpected_records(records, m)] == ["宾果六合彩 / 两面"]


def test_畫面列解析與時間換算():
    cells = ["共 3 笔", "赔率差分设定", "修改", "aaa222 / 宾果六合彩 / 特肖", "差分\n副差分",
             "0\n0", "-0.0001\n-0.0001", "aaron01", "192.168.71.1", "2026-09-29 16:01:36"]
    row = parse_ui_row(cells)
    assert row["fields"] == ["差分", "副差分"] and row["after"] == [D("-0.0001"), D("-0.0001")]
    assert ui_time("2026-09-29T08:01:36.333143+00:00") == "2026-09-29 16:01:36"


def test_畫面整批與API比對():
    records = _records()
    ui_rows = [parse_ui_row(["", "赔率差分设定", "修改", "aaa222 / " + r["entity"], "\n".join(r["fields"]),
                             "\n".join(str(v) for v in r["before"]), "\n".join(str(v) for v in r["after"]),
                             "aaron01", "x", "2026-09-29 16:01:36"]) for r in records]
    assert compare_ui_batch(ui_rows, records, account="aaa222") == []
    assert compare_ui_batch(ui_rows[:2], records, account="aaa222")[0] == "畫面 2 筆、API 3 筆"


def test_篩目標帳號與彩種_兩入口格式不同():
    items = [{"id": 1, "entityId": "aaa222 / 宾果六合彩 / 特码A"}, {"id": 2, "entityId": "aaa2222 / 宾果六合彩 / 特码A"},
             {"id": 3, "entityId": "aaa222 / 香港六合彩 / 特码A"}, {"id": 4, "entityId": "aaa999"}]
    assert [i["id"] for i in for_target(items, "aaa222", "宾果六合彩", scoped=False)] == [1]
    assert [i["id"] for i in for_target(items, "aaa999", scoped=False)] == [4]
    scoped = [{"id": 5, "entityId": "宾果六合彩 / 特码A"}, {"id": 6, "entityId": "香港六合彩 / 正码"}]
    assert [i["id"] for i in for_target(scoped, "aaa222", "宾果六合彩", scoped=True)] == [5]


def test_權限清單差集找出切換的那一項():
    off = {"fields": ["权限"], "beforeValues": [["飞单", "赚取赔率差"]], "afterValues": [["飞单"]]}
    on = {"fields": ["权限"], "beforeValues": [["飞单"]], "afterValues": [["赚取赔率差", "飞单"]]}
    assert permission_change(off) == ([], ["赚取赔率差"])
    assert permission_change(on) == (["赚取赔率差"], [])
    assert permission_change({"fields": ["昵称"], "beforeValues": ["a"], "afterValues": ["b"]}) == ([], [])


class _FakeReader(AuditLogReader):
    """不連線：依 pageIndex／batchId 回預先準備的回應。"""

    def __init__(self, pages, batches):
        self.pages, self.batches, self.calls = pages, batches, []

    def _get(self, params):
        self.calls.append(params)
        if "batchId" in params:
            return {"items": self.batches[params["batchId"]], "totalCount": len(self.batches[params["batchId"]])}
        return {"items": self.pages[params["pageIndex"] - 1], "pageCount": len(self.pages)}


def test_只取操作前最大id之後的紀錄_展開新批次_不碰舊批次():
    pages = [[{"id": 30, "batchId": "new", "batchCount": 2}, {"id": 21, "batchId": None, "batchCount": 1}],
             [{"id": 10, "batchId": "old", "batchCount": 5}]]
    reader = _FakeReader(pages, {"new": [{"id": 30}, {"id": 31}], "old": [{"id": 10}, {"id": 25}]})
    assert reader.latest_id("2026-09-30") == 30
    got = reader.records_after("2026-09-30", 20)
    assert [i["id"] for i in got] == [21, 30, 31]
    assert not any(c.get("batchId") == "old" for c in reader.calls), "舊批次不應展開"
    assert reader.records_after("2026-09-30", 31) == []
