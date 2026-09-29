# -*- coding: utf-8 -*-
"""B108（交接 T66）：賠率差分變更是否在「操作日志」與帳號「日志」兩個入口都查得到。

用途：整批修改差分並保存、再由 UI 改回原值後，逐筆核對兩個入口的紀錄——
      玩法、「差分／副差分」變更前後值、操作者，以及兩入口是否為同一批紀錄。
使用方式：
    expected = expected_records(before_rows, after_rows, "宾果六合彩")
    reader = AuditLogReader(viewer_page)          # 查閱者（公司或上級代理）已登入的 page
    records = reader.records(day, since, until, operator="aaron01", account="aaa222")
    outcome = match_expected(expected, records, operator="aaron01")
前置條件：查閱者已登入後台。讀 `/api/AuditLogs` 只是讀取驗證（與畫面同一支 API、同一組參數），
          ⛔ 不可用來代替受測的 UI 保存；畫面是否顯示同一批紀錄另由 `OperationLogPage` 抽查。

2026-09-29 MCP 實測（公司 aaron01 與一級代理 aaa111）：
- 「操作日志」頁：`GET /api/AuditLogs?topic=oddsGapSetting&startDate&endDate&pageIndex&pageSize`；
  帳號「日志」頁再加 `targetUserId`。伺服器列表每頁固定 25 筆（要求 3 筆仍回 25）。
- 一次保存改到多個玩法時併成一批（`batchId`、`batchCount`）：列表只回一筆當代表，
  畫面標「共 N 笔」，展開時另查 `batchId=`（pageSize＝batchCount），其餘以子列接在代表列下。
- 一筆＝一個玩法：`entityId`「帳號 / 彩種 / 玩法」（帳號「日志」頁不帶帳號）、
  `fields` 只列有變動的「差分」「副差分」、`beforeValues`／`afterValues`、`operatorAccount`、
  `createdAt`（UTC）。七碼記代表列（如「单0」）。
- 上級代理也看得到公司對其下級所做的修改（aaa111 看得到公司改 aaa222～aaa666 的紀錄）。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from xzh_qa.odds_gap_client import ReadOnlyApiError
from xzh_qa.odds_gap_oracle import dec

TOPIC = "oddsGapSetting"
#: 「类型」下拉的正式選項文字（兩個入口相同，2026-09-29 MCP 實測）
TOPIC_LABEL = "赔率差分设定"
#: 設定欄位 → 日誌「变更项」文字
FIELD_LABELS = (("oddsGap", "差分"), ("subOddsGap", "副差分"))
TAIPEI = timezone(timedelta(hours=8))
#: 本機與伺服器時鐘可能有落差，收集紀錄時的時間窗前後各放寬
CLOCK_MARGIN = timedelta(seconds=90)


def _value(value) -> Decimal | None:
    return None if value is None else dec(value)


def play_label(row: dict) -> str:
    """設定列的玩法名稱；七碼列「单0·大0·双7·小7」取代表名「单0」，與日誌目标一致（2026-09-29 冒煙實測）。"""
    return row["playTypeName"].split("/")[0].split("·")[0].strip()


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text)


def ui_time(text: str) -> str:
    """API 的 UTC 時間 → 畫面「时间」欄格式（台北時間到秒）。"""
    return parse_time(text).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


def expected_records(before_rows: list[dict], after_rows: list[dict], game_name: str) -> dict:
    """由保存前後的設定列推出應有的紀錄：`{"彩種 / 玩法": {fields, before, after}}`。

    只列有變動的欄位（2026-09-29 實測：只改主欄時紀錄只有「差分」一項）。
    """
    after_map = {r["playTypeId"]: r for r in after_rows}
    out = {}
    for row in before_rows:
        new = after_map.get(row["playTypeId"])
        if new is None:
            continue
        fields, before, after = [], [], []
        for key, label in FIELD_LABELS:
            old_value, new_value = _value(row.get(key)), _value(new.get(key))
            if old_value != new_value:
                fields.append(label)
                before.append(old_value)
                after.append(new_value)
        if fields:
            out[f"{game_name} / {play_label(row)}"] = {"fields": fields, "before": before, "after": after}
    return out


def normalize(item: dict, account: str | None = None) -> dict:
    """API 紀錄 → 比對用格式；「操作日志」頁的 entityId 帶帳號前綴，去掉後與帳號頁同格式。"""
    entity = item.get("entityId") or ""
    prefix = f"{account} / " if account else None
    return {"id": item.get("id"), "entity": entity[len(prefix):] if prefix and entity.startswith(prefix) else entity,
            "raw_entity": entity, "fields": list(item.get("fields") or []),
            "before": [_value(v) for v in item.get("beforeValues") or []],
            "after": [_value(v) for v in item.get("afterValues") or []],
            "operator": item.get("operatorAccount"), "action": item.get("action"),
            "topic": item.get("topic"), "batch": item.get("batchId"), "at": item.get("createdAt")}


class AuditLogReader:
    """以查閱者已登入 page 的 token 讀 `/api/AuditLogs`（畫面背後同一支 API）。"""

    def __init__(self, page):
        self.page = page
        scheme, rest = page.url.split("//", 1)
        self.origin = scheme + "//" + rest.split("/", 1)[0]

    def _headers(self) -> dict:
        token = self.page.evaluate("() => localStorage.getItem('accessToken')")
        assert token, "查閱者頁面沒有 accessToken，請先登入"
        return {"Authorization": token if token.startswith("Bearer") else "Bearer " + token}

    def _get(self, params: dict) -> dict:
        response = self.page.context.request.get(self.origin + "/api/AuditLogs",
                                                 headers=self._headers(), params=params)
        if response.status != 200:
            raise ReadOnlyApiError("/api/AuditLogs", response.status, response.text())
        return response.json()

    def heads(self, day: str, since: datetime, until: datetime,
              target_user_id: int | None = None, max_pages: int = 20) -> list[dict]:
        """讀當日列表（新到舊），收集 createdAt 落在時間窗內的紀錄；翻到早於時間窗即停。"""
        found = []
        for index in range(1, max_pages + 1):
            params = {"topic": TOPIC, "startDate": day, "endDate": day, "pageIndex": index, "pageSize": 25}
            if target_user_id is not None:
                params["targetUserId"] = target_user_id
            body = self._get(params)
            items = body.get("items") or []
            found += [i for i in items if since - CLOCK_MARGIN <= parse_time(i["createdAt"]) <= until + CLOCK_MARGIN]
            if (not items or parse_time(items[-1]["createdAt"]) < since - CLOCK_MARGIN
                    or index >= (body.get("pageCount") or 0)):
                break
        return found

    def members(self, head: dict, target_user_id: int | None = None) -> list[dict]:
        """展開一批；沒有 batchId 的單筆紀錄就是它自己。"""
        if not head.get("batchId"):
            return [head]
        out, index = [], 1
        while True:
            params = {"batchId": head["batchId"], "pageIndex": index, "pageSize": 100}
            if target_user_id is not None:
                params["targetUserId"] = target_user_id
            body = self._get(params)
            items = body.get("items") or []
            out += items
            if not items or len(out) >= (body.get("totalCount") or 0):
                return out
            index += 1

    def records(self, day: str, since: datetime, until: datetime, *, operator: str, account: str,
                game_name: str, target_user_id: int | None = None) -> list[dict]:
        """時間窗內、該操作者對該帳號該彩種的全部紀錄（已展開批次、已正規化）。

        `target_user_id` 為 None ＝「操作日志」頁（依類型）；有值＝帳號「日志」頁。
        """
        prefix = f"{game_name} / " if target_user_id is not None else f"{account} / {game_name} / "
        out, seen = [], set()
        for head in self.heads(day, since, until, target_user_id):
            if head.get("operatorAccount") != operator or not (head.get("entityId") or "").startswith(prefix):
                continue
            for item in self.members(head, target_user_id):
                if item["id"] in seen or not (item.get("entityId") or "").startswith(prefix):
                    continue
                seen.add(item["id"])
                record = normalize(item, None if target_user_id is not None else account)
                # 畫面只顯示代表列（展開才有其餘子列），定位時要用代表列的目标與时间
                record.update(head=head.get("id"), head_at=head.get("createdAt"),
                              batch_count=head.get("batchCount") or 1)
                out.append(record)
        return out


def match_expected(expected: dict, records: list[dict], operator: str) -> dict:
    """逐玩法找出與預期完全相符的紀錄（玩法、变更项、前後值、操作者、類型、動作）。"""
    by_entity = defaultdict(list)
    for record in records:
        by_entity[record["entity"]].append(record)
    matched, missing, mismatched, duplicated = {}, [], [], []
    for entity, want in expected.items():
        exact = [r for r in by_entity.get(entity, [])
                 if r["fields"] == want["fields"] and r["before"] == want["before"] and r["after"] == want["after"]]
        good = [r for r in exact if r["operator"] == operator and r["topic"] == TOPIC and r["action"] == "update"]
        if len(good) == 1:
            matched[entity] = good[0]
        elif len(good) > 1:
            duplicated.append({"entity": entity, "ids": [r["id"] for r in good]})
        elif exact:
            mismatched.append({"entity": entity, "expected": want, "actual": exact[0],
                               "reason": "操作者、類型或動作不符"})
        else:
            others = by_entity.get(entity, [])
            (mismatched if others else missing).append(
                {"entity": entity, "expected": want, "actual": others[0] if others else None,
                 "reason": "有該玩法紀錄但变更项／前後值不符" if others else "查無該玩法紀錄"})
    batches = {r["batch"] for r in matched.values()}
    return {"matched": matched, "missing": missing, "mismatched": mismatched, "duplicated": duplicated,
            "batches": sorted(str(b) for b in batches),
            "ok": not (missing or mismatched or duplicated) and len(matched) == len(expected)}


def unexpected_records(records: list[dict], *matches: dict) -> list[dict]:
    """時間窗內同操作者、同帳號同彩種，卻不屬於任何一次預期保存的紀錄（如未改動的玩法被記錄）。"""
    used = {r["id"] for m in matches for r in m["matched"].values()}
    return [r for r in records if r["id"] not in used]


def parse_ui_row(cells: list[str]) -> dict:
    """畫面一列：[展開欄(共 N 笔), 类型, 操作动作, 目标, 变更项, 变更前值, 变更后值, 操作者, IP 地址, 时间]。"""
    split = lambda text: [x.strip() for x in text.split("\n") if x.strip()]
    return {"hint": cells[0], "type": cells[1], "action": cells[2], "target": cells[3],
            "fields": split(cells[4]), "before": [_value(x) for x in split(cells[5])],
            "after": [_value(x) for x in split(cells[6])], "operator": cells[7], "time": cells[9]}


def compare_ui_batch(ui_rows: list[dict], api_records: list[dict], *, account: str | None) -> list[str]:
    """畫面展開後的整批列 vs API 同批紀錄；回傳不一致描述（空＝一致）。"""
    strip = (lambda t: t[len(account) + 3:] if account and t.startswith(account + " / ") else t)
    ui = sorted((strip(r["target"]), tuple(r["fields"]), tuple(r["before"]), tuple(r["after"]), r["operator"], r["time"])
                for r in ui_rows)
    api = sorted((r["entity"], tuple(r["fields"]), tuple(r["before"]), tuple(r["after"]), r["operator"], ui_time(r["at"]))
                 for r in api_records)
    problems = []
    if len(ui) != len(api):
        problems.append(f"畫面 {len(ui)} 筆、API {len(api)} 筆")
    only_ui, only_api = sorted(set(ui) - set(api)), sorted(set(api) - set(ui))
    problems += [f"只在畫面：{x[0]} {list(x[1])} {[str(v) for v in x[2]]}→{[str(v) for v in x[3]]}" for x in only_ui[:5]]
    problems += [f"只在 API：{x[0]} {list(x[1])} {[str(v) for v in x[2]]}→{[str(v) for v in x[3]]}" for x in only_api[:5]]
    return problems
