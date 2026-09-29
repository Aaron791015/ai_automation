# -*- coding: utf-8 -*-
"""`xzh_qa.odds_gap_oracle` 的獨立公式測試（規劃 §3、§14 階段 C）。

用途：用**手算固定向量**驗證剩餘差分、下限截斷、逐層有效差與結算守恆，
      確保站台比對時用的期望值本身是對的。

前置條件：無。⚠️ 本檔**不連線、不登入、不下注**，任何環境都跑得起來；
         所有期望值都是依 `docs/新綜合/新綜合_賠率差公式.md` 手算而來，
         ⛔ 不得改成「拿產品回傳值當期望」。
"""
from __future__ import annotations

import json
import os
from decimal import Decimal as D

import pytest

from xzh_qa.odds_gap_oracle import (
    DEFAULT_CAP_RATE, cap_total, effective_gaps, gap_money, level_diffs, level_odds,
    player_odds, remaining_gap, remit, settle_bet, sum_by_level,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST = os.path.join(ROOT, "data", "xzh", "odds_gap_manifest.json")


# --------------------------------------------------------------------------
# 設定端：差分總合上限與剩餘可扣差分
# --------------------------------------------------------------------------

def test_差分總合上限依基準與最低賠率乘上限比例():
    """香港特碼A 實測值：(41.993 − 33.5944) × 0.8 ＝ 6.71888（2026-09-15 報告 §3）。"""
    assert cap_total("41.993", "33.5944", D("0.8")) == D("6.71888")


def test_上限比例預設值為文件記載的零點八():
    assert DEFAULT_CAP_RATE == D("0.8")


def test_剩餘可扣差分等於上限加自身差分加祖先合計():
    """差分皆 ≤0，所以「加上」差分就是把額度扣掉。"""
    assert remaining_gap("41.993", "33.5944", own_gap="-1.1",
                         ancestor_gap_sum="-0.5") == D("5.11888")


def test_零差分時剩餘等於上限本身():
    assert remaining_gap("41.993", "33.5944", own_gap=0, ancestor_gap_sum=0) == D("6.71888")


def test_最低賠率等於基準時上限為零():
    assert cap_total("10", "10") == D("0")


def test_剩餘可扣差分不因浮點輸入而失準():
    """float 先轉 str 再進 Decimal；若直接 Decimal(0.1) 會帶入二進位誤差。"""
    assert remaining_gap(41.993, 33.5944, own_gap=-1.1, ancestor_gap_sum=-0.5) == D("5.11888")


# --------------------------------------------------------------------------
# 投注端：下限截斷與逐層有效差
# --------------------------------------------------------------------------

def test_未觸及下限時生效差分即為原設定值():
    """公式文件例：公司層 49、差分 −2 與 −3、最低 1 → 玩家 44。"""
    assert effective_gaps("49", ["-2", "-3"], "1") == [D("-2"), D("-3")]
    assert player_odds("49", ["-2", "-3"], "1") == D("44")


def test_跌破下限時由最深層先縮減():
    """公司 10、三層各 −1、最低 8.5：需還回 1.5，先把最深層還滿再往上。"""
    assert effective_gaps("10", ["-1", "-1", "-1"], "8.5") == [D("-1"), D("-0.5"), D("0")]
    assert player_odds("10", ["-1", "-1", "-1"], "8.5") == D("8.5")


def test_下限截斷後淺層差分不受影響():
    """縮減額度用完就停：最深一層還回 0.4 即足夠，其餘層維持原值。"""
    assert effective_gaps("10", ["-1", "-1"], "8.4") == [D("-1"), D("-0.6")]


def test_全部差分被截斷後合計為零():
    assert effective_gaps("10", ["-2", "-3"], "10") == [D("0"), D("0")]
    assert player_odds("10", ["-2", "-3"], "10") == D("10")


def test_玩家賠率不會低於最低賠率():
    assert player_odds("10", ["-99"], "3") == D("3")


def test_逐層賠率依序累加本級差分():
    """公式文件兩層範例：一級 −1（10→9）、二級 −1（9→8）。"""
    assert level_odds("10", ["-1", "-1"], "1") == [D("10"), D("9"), D("8")]


def test_實得差等於本級與直屬下級的賠率差():
    """diff 依**受益者**排列：索引 0＝公司、索引 1＝一級代理。"""
    diffs = level_diffs("10", ["-1", "-1"], "1")
    assert diffs == [D("1"), D("1")]


def test_只有一級設差分時一級自己的實得差為零():
    """文件的核心提醒：「設自己的差分不是自己賺，是上一層賺」。

    一級設 −1、二級未設 → 公司賺 1，一級自己 diff ＝ 0。
    """
    assert level_diffs("10", ["-1", "0"], "1") == [D("1"), D("0")]


def test_會員那一列的差分由九級代理受益():
    """十個設定目標＝一～九級代理＋会员；会员列的受益者是九級代理（索引 9）。"""
    gaps = ["0"] * 9 + ["-0.5"]
    diffs = level_diffs("50", gaps, "1")
    assert diffs[9] == D("0.5")
    assert sum(diffs[:9]) == D("0")


def test_截斷後的實得差以有效值計算不可用原設定值():
    """公司 10、兩層各 −1、最低 9：深層被截成 0，diff_1 應為 0 而不是 1。"""
    assert level_diffs("10", ["-1", "-1"], "9") == [D("1"), D("0")]


# --------------------------------------------------------------------------
# 結算端：remit／gapMoney／δ
# --------------------------------------------------------------------------

def test_remit為投注額扣除本級至九級凍結占成():
    """公式文件例：投注 1,000、本級及以下占成合計 600 → remit ＝ 400。"""
    shares = [D("100")] * 9          # 一～九級各 100，第 5 級起合計 ＝ 500
    assert remit("1000", shares, 5) == D("500")
    shares = [D("0")] * 3 + [D("600")] + [D("0")] * 5
    assert remit("1000", shares, 4) == D("400")


def test_gapMoney為remit乘以本級有效實得差():
    """同一個文件例：remit 400、有效實得差 2 → gapMoney ＝ 800。"""
    shares = [D("0")] * 3 + [D("600")] + [D("0")] * 5
    diffs = [D("0")] * 10
    diffs[4] = D("2")
    assert gap_money("1000", shares, diffs, 4) == D("800")


def test_輸局與退本不產生任何差分收益():
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "100", shares, diffs, is_win=False)
    assert result["gap_money"] == [D("0")] * 9
    assert result["delta"] == [D("0")] * 9
    assert result["delta_company"] == D("0")


def test_有效實得差為零時該層收益為零():
    """B99 的第三種情境：贏局但 diff＝0。"""
    shares = [D("100")] * 9
    diffs = [D("0")] * 10
    diffs[3] = D("0.5")                          # 僅三級代理有實得差
    result = settle_bet("1000", "100", shares, diffs)
    assert result["gap_money"][0] == D("0")      # 一級 diff＝0 → 收益 0
    assert result["gap_money"][2] == D("150")    # 三級 remit＝1000−700＝300，×0.5＝150


def test_remit為零時該層收益為零():
    """B99 的第四種情境：贏局但 remit＝0（本級及以下占成吃滿整注）。"""
    shares = [D("0")] * 8 + [D("1000")]
    diffs = [D("1")] * 10
    result = settle_bet("1000", "0", shares, diffs)
    assert result["remit"][8] == D("0")
    assert result["gap_money"][8] == D("0")


def test_九層逐注計算的remit與gapMoney明細():
    """完整手算向量：投注 1000、公司 100、一～九級各 100（合計 ＝ 投注額）。

    remit(N) ＝ 1000 − 100×(10−N)；diff_N ＝ 0.5（N＝1..9）。
    """
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "100", shares, diffs)
    assert result["remit"] == [D("1000") - D("100") * (10 - n) for n in range(1, 10)]
    assert result["remit"][0] == D("100")
    assert result["remit"][8] == D("900")
    assert result["gap_money"][0] == D("50")
    assert result["gap_money"][8] == D("450")


def test_δ為gapMoney扣除本級占成乘更下層實得差合計():
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "100", shares, diffs)
    # 一級：gapMoney 50 − 100 × (0.5×8) ＝ 50 − 400 ＝ −350
    assert result["delta"][0] == D("-350")
    # 九級：gapMoney 450 − 100 × 0 ＝ 450
    assert result["delta"][8] == D("450")


def test_公司δ為負的公司占成乘九層實得差合計():
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "100", shares, diffs)
    assert result["delta_company"] == D("-450")


def test_跨層修正合計恆為零():
    """守恆檢查：δ(Company) ＋ Σδ(N) ＝ 0。"""
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    assert settle_bet("1000", "100", shares, diffs)["delta_sum"] == D("0")


@pytest.mark.parametrize("company_share,agent_shares,diffs", [
    (D("50"), [D("30"), D("40"), D("20"), D("60"), D("10"), D("80"), D("25"), D("15"), D("70")],
     [D("0.2"), D("1.5"), D("0"), D("0.75"), D("2"), D("0.1"), D("0"), D("3.25"), D("0.4"), D("1")]),
    (D("0"), [D("0")] * 9,
     [D("1")] * 10),
    (D("120.5"), [D("11.25")] * 9,
     [D("0.0001")] * 10),
])
def test_不同占成與差分組合下守恆仍成立(company_share, agent_shares, diffs):
    """投注額 ＝ 公司占成 ＋ 九層占成（守恆的前提），任意組合 Σδ 都應為 0。"""
    bet = company_share + sum(agent_shares)
    assert settle_bet(bet, company_share, agent_shares, diffs)["delta_sum"] == D("0")


def test_跳層缺席的層級不產生收益():
    """缺席層凍結占成為 0 且 diff 為 0——不影響其他層的守恆。"""
    shares = [D("100"), D("0"), D("100"), D("0"), D("100"), D("0"), D("100"), D("0"), D("100")]
    diffs = [D("0.5"), D("0.5"), D("0"), D("0.5"), D("0"), D("0.5"), D("0"), D("0.5"), D("0"), D("0.5")]
    result = settle_bet(D("500") + D("100"), D("100"), shares, diffs)
    assert result["gap_money"][1] == D("0")
    assert result["delta_sum"] == D("0")


def test_四位小數差分的金額不產生浮點誤差():
    shares = [D("111.11")] * 9
    diffs = [D("0.0001")] * 10
    result = settle_bet(D("111.11") * 10, D("111.11"), shares, diffs)
    assert result["delta_sum"] == D("0")
    assert result["gap_money"][8] == D("111.11") * 9 * D("0.0001")


# --------------------------------------------------------------------------
# 自營總控公司：上繳額先扣總控鏈前後兩段佔成（2026-09-29 新版文件）
# --------------------------------------------------------------------------

def test_自營總控公司的remit先扣總控兩段佔成():
    """公式文件例：投注 1,000、總控兩段合計 100、本級及以下 600 → remit 300、實得差 2 → 600。"""
    shares = [D("0")] * 3 + [D("600")] + [D("0")] * 5
    assert remit("1000", shares, 4, holding_share="100") == D("300")
    diffs = [D("0")] * 10
    diffs[4] = D("2")
    assert gap_money("1000", shares, diffs, 4, holding_share="100") == D("600")


def test_總控佔成為零時與原公式相同():
    shares = [D("100")] * 9
    assert remit("1000", shares, 5, holding_share="0") == remit("1000", shares, 5)


def test_有總控佔成時扣除後跨層修正合計仍為零():
    """公司＋九層佔成＝投注額 − 總控兩段；依新公式 Σδ＝0。"""
    shares = [D("80")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "180", shares, diffs, holding_share="100")
    assert result["remit"][0] == D("180")          # 1000 − 100 − 720
    assert result["delta_sum"] == D("0")


def test_漏扣總控佔成會讓跨層修正合計偏離零():
    """反例：同一注不扣總控兩段，Σδ ＝ 總控佔成 × 九層實得差合計 ≠ 0（憑空造錢）。"""
    shares = [D("80")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "180", shares, diffs)
    assert result["delta_sum"] == D("100") * D("0.5") * 9


# --------------------------------------------------------------------------
# phase-4 一級抽成（文件標示尚未實作，預設不套用）
# --------------------------------------------------------------------------

def test_預設不套用一級抽成():
    """未取得「已上線」證據前，`agent1_keep_rate` 必須維持 None。"""
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    result = settle_bet("1000", "100", shares, diffs)
    assert result["agent1_remit_to_company"] == D("0")


def test_套用一級抽成後守恆仍成立且一級報表值按保留比例縮減():
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    plain = settle_bet("1000", "100", shares, diffs)
    phase4 = settle_bet("1000", "100", shares, diffs, agent1_keep_rate=D("0.8"))
    assert phase4["agent1_remit_to_company"] == plain["gap_money"][0] * D("0.2")
    assert phase4["gap_money"][0] == plain["gap_money"][0] * D("0.8")
    assert phase4["delta"][0] == plain["delta"][0] - phase4["agent1_remit_to_company"]
    assert phase4["delta_sum"] == D("0")


# --------------------------------------------------------------------------
# 報表加總與玩法清單
# --------------------------------------------------------------------------

def test_多筆注單依層級加總():
    shares = [D("100")] * 9
    diffs = [D("0.5")] * 10
    win = settle_bet("1000", "100", shares, diffs)
    lose = settle_bet("1000", "100", shares, diffs, is_win=False)
    total = sum_by_level([win, win, lose])
    assert total[8] == D("900")          # 兩筆贏注各 450，輸注 0
    assert total[0] == D("100")


def test_玩法清單三彩種皆為一百列一百十五欄():
    """回歸基準（2026-09-15 快照）。與現況不符時先判缺陷／開單，不是直接改這份檔。"""
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    for game in ("markSix", "ukLucky7", "bingo6"):
        assert manifest["games"][game]["rowCount"] == 100
        assert manifest["games"][game]["columnCount"] == 115


def test_玩法清單的副欄與案例文件所列十五項一致():
    expected = ["二中特", "三中二", "生肖中", "生肖不中", "尾数中", "尾数不中", "特肖",
                "二肖连中", "三肖连中", "四肖连中", "五肖连中",
                "二尾连不中", "三尾连不中", "四尾连不中", "五行"]
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    for game in ("markSix", "ukLucky7", "bingo6"):
        actual = [r["playTypeName"] for r in manifest["games"][game]["rows"] if r["hasSub"]]
        assert actual == expected


def test_玩法清單不含過關():
    """Aaron 2026-09-09 裁定：過關不支援賠率差，不應出現在設定頁。"""
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    for game in ("markSix", "ukLucky7", "bingo6"):
        names = [r["playTypeName"] for r in manifest["games"][game]["rows"]]
        assert not [n for n in names if "过关" in n or "過關" in n]


def test_玩法清單的七碼只有八個代表列():
    """七碼僅接受 单0～单7 共 8 個代表葉。"""
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    for game in ("markSix", "ukLucky7", "bingo6"):
        names = [r["playTypeName"] for r in manifest["games"][game]["rows"]]
        seven = [n for n in names if n.startswith("单") and "·" in n]
        assert len(seven) == 8
