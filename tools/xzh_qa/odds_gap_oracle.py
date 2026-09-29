# -*- coding: utf-8 -*-
"""新綜合「賠率差」獨立驗算模組（oracle）。

用途：依 [`docs/新綜合/新綜合_賠率差公式.md`](../../docs/新綜合/新綜合_賠率差公式.md) 的規格，
      用 `Decimal` 重算剩餘差分、逐層有效差、玩家凍結賠率與結算收益，
      供測試案例當成**獨立期望值**使用。

使用方式：
    from xzh_qa.odds_gap_oracle import remaining_gap, effective_gaps, settle_bet

前置條件：
- 輸入值（基準／最低賠率、上限比例、各層差分、占成金額）必須來自**產品以外**的可追溯來源
  （唯讀 API 的設定端欄位、凍結稽核資料），不得拿產品算好的收益欄位回頭當期望值。
- 本模組**不連線、不依賴 playwright**，可單獨用 `tests/tooling/test_xzh_odds_gap_oracle.py` 驗證。

⚠️ 名詞對照（本模組一律用「受益者」而非「被設定者」表達收益歸屬）：
    索引 0..8 = 一级代理…九级代理，索引 9 = 会员。
    每一列差分的**受益者是直屬上級**：会员那一列的差分由九級代理賺，
    一级代理那一列的差分由公司賺（公司自身不可設差分列）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Sequence

#: 設定目標的順序：索引 0～8 為一～九級代理，索引 9 為會員（最靠近玩家的一列）。
GAP_TARGETS = ("agent1", "agent2", "agent3", "agent4", "agent5",
               "agent6", "agent7", "agent8", "agent9", "member")

#: 文件預設的差分總合上限比例；**僅在取不到平台實際設定時**才可使用，且需在報告標注為假設。
DEFAULT_CAP_RATE = Decimal("0.8")


def dec(value) -> Decimal:
    """把 None／int／float／str 統一轉成 `Decimal`；None 視為 0。

    ⚠️ float 先轉 str 再轉 Decimal，避免 `Decimal(0.1)` 帶入二進位誤差。
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# --------------------------------------------------------------------------
# 設定端：差分總合上限與剩餘可扣差分
# --------------------------------------------------------------------------

def cap_total(base_odds, min_odds, cap_rate=DEFAULT_CAP_RATE) -> Decimal:
    """差分總合上限 ＝ (玩法基準賠率 − 玩法最低賠率) × `odds_gap_cap_rate`。

    `base_odds` 取 `odds_setting.odds` 基準值，**不可**用公司層解析賠率（含盤口／跳水／手動）代入。
    """
    return (dec(base_odds) - dec(min_odds)) * dec(cap_rate)


def remaining_gap(base_odds, min_odds, own_gap, ancestor_gap_sum,
                  cap_rate=DEFAULT_CAP_RATE) -> Decimal:
    """剩餘可扣差分 ＝ 差分總合上限 ＋ 自身差分 ＋ 祖先鏈差分合計。

    差分皆為 ≤0，因此「加上」差分等於把額度扣掉。祖先鏈只算**本層以上**的設定列，
    不含本層自己（自身差分由 `own_gap` 單獨帶入，方便測「改一欄前後剩餘怎麼變」）。
    """
    return cap_total(base_odds, min_odds, cap_rate) + dec(own_gap) + dec(ancestor_gap_sum)


# --------------------------------------------------------------------------
# 投注端：下限截斷與逐層有效差
# --------------------------------------------------------------------------

def effective_gaps(company_odds, gaps: Sequence, min_odds) -> list[Decimal]:
    """套用下限截斷後，回傳各層**實際生效**的差分（順序同 `gaps`，由淺到深）。

    規格：`玩家凍結賠率 = max(min_odds, 公司層解析賠率 + 鏈上生效差分合計)`，
    且「下限截斷由**最深層**（最靠近玩家）的差分先縮減，再往上」。

    因此當合計會跌破下限時，從最後一個元素（會員列）開始把差分往 0 縮，縮完再往上一層縮。

    ⚠️ 休眠（授權未持有）的列請在呼叫前就填 0；本函式不判斷授權。
    """
    values = [dec(g) for g in gaps]
    company = dec(company_odds)
    low = dec(min_odds)
    shortfall = low - (company + sum(values, Decimal(0)))
    if shortfall <= 0:
        return values
    # 由最深層往上縮減：每層最多只能縮到 0（差分是負值，縮減即往 0 靠）
    for i in range(len(values) - 1, -1, -1):
        if shortfall <= 0:
            break
        room = -values[i]          # 這一層還能還回多少額度（差分為負，room ≥ 0）
        give = room if room < shortfall else shortfall
        values[i] += give
        shortfall -= give
    return values


def player_odds(company_odds, gaps: Sequence, min_odds) -> Decimal:
    """玩家凍結賠率 ＝ max(最低賠率, 公司層解析賠率 ＋ 生效差分合計)。"""
    company = dec(company_odds)
    low = dec(min_odds)
    total = sum(effective_gaps(company, gaps, low), Decimal(0))
    value = company + total
    return value if value > low else low


def level_odds(company_odds, gaps: Sequence, min_odds) -> list[Decimal]:
    """回傳 `[公司層解析賠率, 一級拿到, 二級拿到, …, 九級拿到, 玩家凍結]`（長度 = len(gaps)+1）。

    本級拿到的賠率 ＝ 上級拿到的賠率 ＋ **本級列**的生效差分（逐項累加）。
    """
    eff = effective_gaps(company_odds, gaps, min_odds)
    out = [dec(company_odds)]
    for g in eff:
        out.append(out[-1] + g)
    return out


def level_diffs(company_odds, gaps: Sequence, min_odds) -> list[Decimal]:
    """回傳 `[diff_Company, diff_1, …, diff_9]`（長度 = len(gaps)）——**依受益者**排列。

    `diff_N = 本級拿到的賠率 − 直屬下級拿到的賠率`（採下限截斷後的有效值）。
    由於 `odds(N+1) = odds(N) + gaps[N]`，等價於 `diff_N = −gaps[N]`（取截斷後值）。
    索引 0 是公司（受益於一级代理那一列），索引 9 是九級代理（受益於会员那一列）。
    """
    return [-g for g in effective_gaps(company_odds, gaps, min_odds)]


# --------------------------------------------------------------------------
# 結算端：remit／gapMoney／δ
# --------------------------------------------------------------------------

def remit(bet_amount, agent_shares: Sequence, level: int, holding_share=0) -> Decimal:
    """`remit(N) = bet_amount − 總控鏈前後兩段佔成 − Σ[j=N..9] agent_j_share_amount`。

    `agent_shares` 為一～九級的**凍結占成金額**（索引 0 = 一級），`level` 用 1～9 表示。
    `holding_share` 為自營總控鏈前＋鏈後兩段凍結佔成金額合計（2026-09-29 新版文件）；
    非自營總控公司恆為 0，公式退化回「投注額 − 本級及以下佔成」。
    """
    assert 1 <= level <= len(agent_shares), f"level 必須落在 1～{len(agent_shares)}"
    assert dec(holding_share) >= 0, "總控佔成不可為負"
    return (dec(bet_amount) - dec(holding_share)
            - sum((dec(s) for s in agent_shares[level - 1:]), Decimal(0)))


def gap_money(bet_amount, agent_shares: Sequence, diffs: Sequence, level: int,
              holding_share=0) -> Decimal:
    """`gapMoney(N) = remit(N) × diff_N`（僅贏局產生；輸局／和局退本由呼叫端傳 0 差或直接跳過）。

    `diffs` 為 `level_diffs()` 的輸出（索引 0 = 公司），故第 N 級取 `diffs[level]`。
    """
    return remit(bet_amount, agent_shares, level, holding_share) * dec(diffs[level])


def settle_bet(bet_amount, company_share, agent_shares: Sequence, diffs: Sequence,
               is_win: bool = True, agent1_keep_rate=None, holding_share=0) -> dict:
    """逐注計算九層 `remit`／`gapMoney`／δ 與公司 δ，並回傳守恆檢查。

    參數：
    - `agent_shares`：一～九級的凍結占成金額（索引 0 = 一級）。
    - `diffs`：`[diff_Company, diff_1..diff_9]`，長度 10；取自 `level_diffs()` 或凍結稽核值。
    - `is_win`：僅贏局產生 `gapMoney` 與 δ；輸局、和局退本一律 0。
    - `agent1_keep_rate`：phase-4 一級抽成保留比例。**預設 None ＝ 不套用**；
      未取得「已上線」的版本／設定證據前不得傳值（文件標示尚未實作）。
    - `holding_share`：自營總控鏈前＋鏈後兩段凍結佔成合計，預設 0（非自營總控公司）。
      守恆前提為「公司＋九層佔成＝投注額 − 總控兩段」；漏扣會讓 Σδ 偏離 0。

    回傳 dict：`remit`、`gap_money`、`delta`（皆為 1～9 的 list）、`delta_company`、
    `delta_sum`（守恆檢查，應為 0）、`agent1_remit_to_company`。
    """
    assert len(agent_shares) == 9, "agent_shares 需為一～九級共 9 筆凍結占成金額"
    assert len(diffs) == 10, "diffs 需為 [公司, 一級…九級] 共 10 筆"
    shares = [dec(s) for s in agent_shares]
    d = [dec(x) for x in diffs]

    if not is_win:
        zero = [Decimal(0)] * 9
        return {"remit": [remit(bet_amount, shares, n, holding_share) for n in range(1, 10)],
                "gap_money": list(zero), "delta": list(zero),
                "delta_company": Decimal(0), "delta_sum": Decimal(0),
                "agent1_remit_to_company": Decimal(0)}

    remits = [remit(bet_amount, shares, n, holding_share) for n in range(1, 10)]
    gaps = [remits[n - 1] * d[n] for n in range(1, 10)]
    # δ(N) = gapMoney(N) − agent_N_share_amount × Σ[j>N] diff_j
    deltas = [gaps[n - 1] - shares[n - 1] * sum(d[n + 1:], Decimal(0)) for n in range(1, 10)]
    delta_company = -dec(company_share) * sum(d[1:], Decimal(0))

    to_company = Decimal(0)
    if agent1_keep_rate is not None:
        # phase-4：一級代理抽成。未確認上線前不得呼叫（見公式文件「尚未實作」）。
        to_company = gaps[0] * (Decimal(1) - dec(agent1_keep_rate))
        deltas[0] -= to_company
        delta_company += to_company
        gaps[0] = gaps[0] * dec(agent1_keep_rate)   # 一級報表賠率差 ＝ gapMoney × keep_rate

    return {"remit": remits, "gap_money": gaps, "delta": deltas,
            "delta_company": delta_company,
            "delta_sum": delta_company + sum(deltas, Decimal(0)),
            "agent1_remit_to_company": to_company}


def sum_by_level(per_bet_results: Iterable[dict], key: str = "gap_money") -> list[Decimal]:
    """把多筆 `settle_bet()` 結果依層級加總，供「報表某層金額 ＝ 完整查詢範圍逐注合計」比對。"""
    total = [Decimal(0)] * 9
    for r in per_bet_results:
        for i, v in enumerate(r[key]):
            total[i] += v
    return total
