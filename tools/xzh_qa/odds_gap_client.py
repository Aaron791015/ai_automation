# -*- coding: utf-8 -*-
"""新綜合賠率差的**唯讀** API 讀取器。

用途：取得比對用的後端事實——差分設定、基準／最低賠率、平台開關與上限比例、占成報表金額。
      提供給案例當「讀取驗證」與前置資料準備使用。

使用方式：
    client = OddsGapClient.from_page(page)      # 沿用已登入 page 的 context 與 Authorization
    rows = client.gap_setting(target_user_id, "markSix")

前置條件：
- `page` 需已登入後台，且**至少開過一次賠率差分頁**（本類靠攔截該請求取得 Authorization header）。
- CLAUDE.md §5：被測行為（登入、授權、輸入、保存、投注、報表查詢）一律走 UI；
  本類只負責**非被測行為的前置準備與讀取驗證**，⛔ 不可用來代替受測的 UI 保存。

⚠️ 權限邊界（2026-09-16 複驗）：
- 公司經 UI 確認目標後可 GET 指定鏈的非直屬 `OddsGapSetting`；但 UI 保存非直屬下級仍403。
- GET 可讀不等於公司 PUT 可寫，保存結果必須按公司與直屬上級路徑分開判定。
- 代理身分讀 `OddsSetting`（基準／最低賠率）會回 403；獨立公式比對的基準必須由**公司身分**取得。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from xzh_qa.odds_gap_oracle import DEFAULT_CAP_RATE, dec

#: 三個適用彩種的 gameId 與後台顯示名稱（僅樂透彩系三種支援賠率差）。
GAMES = {"markSix": "香港六合彩", "ukLucky7": "英国天天彩", "bingo6": "宾果六合彩"}


class ReadOnlyApiError(AssertionError):
    """唯讀 API 取值失敗（含 403 權限邊界）。案例應據此判 BLOCKED 或 FAIL，不可靜默略過。"""

    def __init__(self, path: str, status: int, body: str = ""):
        self.path, self.status, self.body = path, status, body
        super().__init__(f"GET {path} → HTTP {status}；回應：{body[:400]}")


class OddsGapClient:
    """以已登入 page 的 request context 發唯讀 GET；`Authorization` 由攔截前端請求取得。"""

    def __init__(self, context, base_url: str, headers: dict):
        self.context = context
        self.base_url = base_url.rstrip("/")
        self.headers = headers

    # ---------------- 建立 ----------------

    @staticmethod
    def attach(page) -> dict:
        """在 page 掛上監聽，回傳一個會被就地填入的觀測結果 dict。

        必須在**開啟賠率差分頁之前**呼叫。回傳結構：
        - `headers`：攔到的 `Authorization`（唯讀 GET 用）。
        - `target_user_ids`：前端自己發的 `OddsGapSetting?targetUserId=` 依序記錄。
          ⭐ 這是取得 userId 的**唯一合法來源**——我們是先由 UI 開啟「某個帳號」的編輯頁，
          前端才發出這個請求，因此該 id 已經過身分驗證。
          ⛔ 不得用 `68 + 層級` 之類的推導（那只是 2026-09 當下的實測巧合）。
        """
        observed: dict = {"headers": {}, "target_user_ids": []}

        def _observe(response):
            if "/api/" not in response.url:
                return
            # headers 為已快取的請求資料；all_headers 另送 RPC，關閉 context 時會留下未完成 callback。
            for key, value in response.request.headers.items():
                if key.lower() == "authorization":
                    observed["headers"]["Authorization"] = value
            if "/api/OddsGapSetting" in response.url and "targetUserId=" in response.url:
                raw = response.url.split("targetUserId=", 1)[1].split("&", 1)[0]
                if raw.isdigit():
                    observed["target_user_ids"].append(int(raw))

        page.on("response", _observe)
        return observed

    @classmethod
    def from_page(cls, page, observed: dict) -> "OddsGapClient":
        base = page.url.split("//", 1)
        origin = base[0] + "//" + base[1].split("/", 1)[0]
        if not observed.get("headers", {}).get("Authorization"):
            raise ReadOnlyApiError("(attach)", 0, "尚未攔截到 Authorization；請先開啟賠率差分頁")
        return cls(page.context, origin, dict(observed["headers"]))

    # ---------------- 唯讀取值 ----------------

    def _get(self, path: str, params: Optional[dict] = None):
        url = self.base_url + path
        response = self.context.request.get(url, headers=self.headers, params=params or {})
        if response.status != 200:
            raise ReadOnlyApiError(path, response.status, response.text())
        return response.json()

    def gap_setting(self, target_user_id: int, game_id: str) -> list[dict]:
        """`GET /api/OddsGapSetting`：某帳號某彩種的逐列差分設定。

        欄位：playTypeId／playTypeName／oddsGap／subOddsGap／subOddsLabel／
        remainingOddsGap／remainingSubOddsGap／isEffective／depth／displayOrder。
        """
        return self._get("/api/OddsGapSetting",
                         {"targetUserId": target_user_id, "gameId": game_id})

    def odds_setting(self, game_id: str) -> dict:
        """`GET /api/OddsSetting`：逐玩法基準／最低賠率，回傳以 playTypeId 為鍵的 dict。

        ⚠️ 只有公司身分讀得到（代理身分 403）。
        """
        return {x["playTypeId"]: x for x in self._get("/api/OddsSetting", {"gameId": game_id})}

    def company_status(self) -> dict:
        """`GET /api/OddsGapSetting/CompanyStatus`：平台／公司層的賠率差開關。"""
        return self._get("/api/OddsGapSetting/CompanyStatus")

    def cap_rate(self) -> tuple[Decimal, bool]:
        """讀本次fixture取自平台company1編輯頁的百分比證據。

        2026-09-17使用者指定來源；Settings/Global不是公司上限來源。
        無本次有效證據仍回傳(文件假設0.8, False)，不可據此判完整公式PASS。
        """
        from xzh_qa.pages.platform_system_page import percent_to_rate
        evidence = getattr(self, "platform_cap_evidence", {})
        self.cap_rate_evidence = dict(evidence)
        if (evidence.get("source") == "platform-company-edit"
                and evidence.get("account") == "company1"
                and evidence.get("label") == "赔率差上限"
                and evidence.get("unit") == "%"
                and evidence.get("observed_at") and not evidence.get("error")):
            try:
                value = percent_to_rate(evidence["percent"])
                if value == Decimal(evidence["rate"]):
                    return value, True
            except (KeyError, ValueError, TypeError, ArithmeticError):
                pass
        return DEFAULT_CAP_RATE, False

    @staticmethod
    def _game_query(game_ids) -> str:
        """`gameIds` 是**重複出現的同名參數**（`gameIds=a&gameIds=b`），不是逗號串。"""
        if isinstance(game_ids, str):
            game_ids = [g.strip() for g in game_ids.split(",") if g.strip()]
        return "&".join(f"gameIds={g}" for g in game_ids)

    def share_report(self, date_from: str, date_to: str, game_ids=None,
                     parent_id: Optional[int] = None,
                     settlement_state: str = "settled") -> list[dict]:
        """`GET /api/Reports/Shares`：占成報表，回傳 `items`（每列含 `oddsGapAmount`）。

        列的鍵是 `descendantAccount`（下級帳號），值的歸屬則看**當下的 parentId**：
        ⚠️ `parentId` 決定表頭的 ancestorLevel——查一級收益要帶 aaa111 的 id 看其下級列，
        不能只憑列帳號判定收益歸屬（UI 元素對照 §4）。
        """
        query = [self._game_query(game_ids or list(GAMES)),
                 f"dateFrom={date_from}", f"dateTo={date_to}",
                 "companyView=false", f"settlementState={settlement_state}"]
        if parent_id is not None:
            query.append(f"parentId={parent_id}")
        payload = self._get("/api/Reports/Shares?" + "&".join(query))
        return payload.get("items", []) if isinstance(payload, dict) else payload

    def share_ancestors(self, user_id: int) -> list[dict]:
        """`GET /api/Reports/Shares/Ancestors/{id}`：該帳號的祖先鏈（`[{id, account, level}]`）。

        用來把「報表某列的金額」對應到**正確的受益層**，⛔ 不用列序或帳號字面推導。
        """
        payload = self._get(f"/api/Reports/Shares/Ancestors/{user_id}")
        return payload.get("items", []) if isinstance(payload, dict) else payload

    def member_bets(self, member_id: int, day: str, game_ids=None) -> dict:
        """`GET /api/Reports/Shares/Members/{id}/Bets`：會員某日注單明細。

        每筆含 `betAmount`、`odds`、`outcome`、`payout`、`layerShares`（逐層凍結占成金額）。

        ⚠️ 2026-09-14 實查：此來源**沒有逐層凍結的「有效差」**（Snotra-008）。
        缺有效差時 B98／B99 的金額正確性判 BLOCKED，⛔ 不可把假設值當期望，
        也不可用報表金額反推有效差再回頭驗同一份報表。
        """
        query = [self._game_query(game_ids or list(GAMES)), f"date={day}"]
        return self._get(f"/api/Reports/Shares/Members/{member_id}/Bets?" + "&".join(query))

    def all_member_bets(self, member_id: int, day: str, game_ids=None) -> list[dict]:
        """依實際分頁契約讀完已結算注單，數量／重複不符即失敗。"""
        items, total, page = [], None, 1
        while True:
            query = [self._game_query(game_ids or list(GAMES)), f"date={day}",
                     "settlementState=settled", f"pageIndex={page}", "pageSize=25"]
            data = self._get(f"/api/Reports/Shares/Members/{member_id}/Bets?" + "&".join(query))
            assert isinstance(data, dict) and "totalCount" in data and "pageCount" in data, "缺完整分頁資訊"
            if total is None:
                total = data["totalCount"]
            assert total == data["totalCount"], "讀取期間注單總數異動，停止合計"
            items.extend(data["items"])
            if page >= data["pageCount"]:
                break
            assert data["items"], "分頁提前為空"
            page += 1
        assert len(items) == total, "注單分頁未讀齊"
        ids = [str(item["serialNumber"]) for item in items]
        assert len(ids) == len(set(ids)), "注單分頁重複"
        return items


def gap_values(rows: list[dict]) -> dict:
    """把 `gap_setting()` 的回傳壓成 `{(playTypeId, 'oddsGap'|'subOddsGap'): Decimal}`，供前後比對。"""
    return {(r["playTypeId"], key): dec(r[key])
            for r in rows for key in ("oddsGap", "subOddsGap")}


def ancestor_sum(ancestor_rows: list[list[dict]]) -> dict:
    """把多層祖先的設定列加總成 `{(playTypeId, field): Decimal}`，供剩餘差分公式使用。"""
    total: dict = {}
    for rows in ancestor_rows:
        for key, value in gap_values(rows).items():
            total[key] = total.get(key, Decimal(0)) + value
    return total
