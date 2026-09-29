"""凍結稽核契約與獨立驗算。缺資料不降級成零，現行設定不代替下注快照。

JSON schemaVersion=1；scope 含 date/gameIds/memberAccount/chain/settlementState/
complete/betIds；records 每筆含下注識別、凍結算式輸入、實際逐層收益與來源。
自營總控公司的注單另帶 holdingShare（總控鏈前＋鏈後兩段凍結佔成合計），未帶視為 0。
來源須是可審查的唯讀匯出證据，不可由報表收益反推 diffs。
"""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from xzh_qa.odds_gap_oracle import effective_gaps, player_odds, settle_bet
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS


class AuditBlocked(ValueError):
    """必要稽核資料缺失、範圍不符或無法追溯。"""


def require(condition, reason):
    if not condition:
        raise AuditBlocked(reason)


def number(value):
    require(value is not None and not isinstance(value, bool), "數值不可為 null/bool")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AuditBlocked(f"非法十進位數值：{value!r}")
    require(result.is_finite(), "數值不可為 NaN/Infinity")
    return result


def vector(record, key, size):
    values = record.get(key)
    require(isinstance(values, list) and len(values) == size, f"{key} 必須有 {size} 層")
    return [number(v) for v in values]


def load_audit(path, day, games):
    require(bool(path), "缺 XZH_GAP_FROZEN_AUDIT：需逐注凍結有效差、占成及獨立結算實值")
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError) as exc:
        raise AuditBlocked(f"凍結稽核檔不可讀：{exc}")
    require(isinstance(data, dict) and data.get("schemaVersion") == 1, "需 schemaVersion=1 的完整稽核物件，不能使用未識別清單")
    scope = data.get("scope", {})
    require(isinstance(scope, dict), "scope 須為查詢範圍物件")
    require(isinstance(scope.get("gameIds"), list) and isinstance(scope.get("betIds"), list), "scope 缺完整彩種／注單清單")
    require(len(scope["betIds"]) == len(set(map(str, scope["betIds"]))), "scope 注單清單重複")
    require(scope.get("date") == day, "稽核日期與報表日期不符")
    require(set(scope.get("gameIds", [])) == set(games), "稽核彩種與查詢範圍不符")
    require(scope.get("chain") == CHAIN_ACCOUNTS, "凍結帳號鏈不符")
    require(scope.get("memberAccount") == CHAIN_ACCOUNTS[-1], "會員不符")
    require(scope.get("settlementState") == "settled" and scope.get("complete") is True,
            "需完整已結算範圍，不能拿部分注單比較報表")
    records = data.get("records")
    require(isinstance(records, list) and bool(records), "凍結資料不能為空")
    ids = []
    for r in records:
        require(isinstance(r, dict), "注單須為物件")
        for key in ("betId", "gameId", "playTypeId", "selection", "issue", "betAt", "settledAt",
                    "inputSource", "settlementSource"):
            require(bool(r.get(key)), f"缺 {key}")
        for source_key in ("inputSource", "settlementSource"):
            source = Path(path).parent / r[source_key]
            require(source.is_file(), f"缺可審查來源檔：{source_key}")
            try:
                source_data = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise AuditBlocked(f"來源 {source_key} 需為可讀 JSON 唯讀匯出")
            require(isinstance(source_data, (list,dict)), "來源需為注單物件或清單")
            candidates = source_data if isinstance(source_data, list) else source_data.get("records", [source_data])
            matched = [x for x in candidates if isinstance(x,dict) and str(x.get("betId")) == str(r["betId"])]
            require(len(matched) == 1, f"{source_key} 無唯一對應注單")
            keys = ("betAmount", "companyShare", "agentShares", "diffs", "gameId", "playTypeId", "betAt") if source_key == "inputSource" else ("actualGapMoney", "outcome", "settledAt")
            keys += ("chain", "memberAccount", "gameId", "playTypeId", "selection", "issue", "reportDate")
            if source_key == "inputSource":
                keys += tuple(k for k in ("holdingShare", "companyResolvedOdds", "minOddsAtBet", "chainGapsAtBet",
                              "frozenOdds", "frozenMainOddsGap", "frozenSubOddsGap", "otherPricing",
                              "sevenLeafGaps", "sevenRepresentative") if k in r)
            elif "isSubOddsWin" in r:
                keys += ("isSubOddsWin",)
            if source_key == "settlementSource" and r.get("outcome") == "tie":
                keys += ("payout", "betAmount")
            require(all(matched[0].get(k) == r.get(k) and k in matched[0] for k in keys), f"{source_key} 與稽核輸入／實值不符")
        require(r["inputSource"] != r["settlementSource"], "凍結輸入與產品結算實值需分開追溯")
        require(r.get("chain") == CHAIN_ACCOUNTS and r.get("memberAccount") == CHAIN_ACCOUNTS[-1], "逐注帳號鏈不符")
        require(r["gameId"] in games and r.get("reportDate") == day, "逐注彩種／報表日期不符")
        try:
            placed, settled = datetime.fromisoformat(r["betAt"]), datetime.fromisoformat(r["settledAt"])
            require(placed.tzinfo is not None and settled.tzinfo is not None and placed <= settled, "下注／結算時間須含時區且順序正確")
        except (ValueError, TypeError):
            raise AuditBlocked("下注／結算時間格式錯誤")
        require(r.get("outcome") in ("won", "lost", "refund", "tie"), "缺明確結算分支")
        if r.get("outcome") == "tie":
            require(number(r.get("payout")) == number(r.get("betAmount")), "和局退本需獨立結算來源證明 payout 等於本金")
        require(number(r.get("betAmount")) > 0, "投注額需大於零")
        shares = vector(r, "agentShares", 9)
        company = number(r.get("companyShare"))
        # 自營總控鏈前＋鏈後兩段佔成須由下注凍結來源明確提供；未提供即視為非自營總控（0），
        # 不從差額反推，避免把缺漏的占成層誤當總控佔成。
        holding = number(r["holdingShare"]) if "holdingShare" in r else Decimal(0)
        require(company >= 0 and holding >= 0 and all(v >= 0 for v in shares), "凍結占成不可負值")
        require(company + sum(shares) + holding == number(r["betAmount"]),
                "凍結占成金額未守恆（公司＋九層＋總控兩段須等於投注額）")
        diffs = vector(r, "diffs", 10)
        require(all(v >= 0 for v in diffs), "凍結實得差不可為負")
        vector(r, "actualGapMoney", 9)
        ids.append(str(r["betId"]))
    require(len(ids) == len(set(ids)), "注單 ID 重複")
    require(set(ids) == set(map(str, scope.get("betIds", []))), "完整注單 ID 清單不一致")
    require(set(games) == {r["gameId"] for r in records}, "某彩種無樣本")
    return data


def verify_live_ids(audit, live_ids):
    require(set(map(str, live_ids)) == set(map(str, audit["scope"]["betIds"])),
            "線上完整注單 ID 與稽核範圍不符，停止合計比對")


def verify_settlement(record):
    require(record.get("outcome") in ("won", "lost", "refund", "tie"), "缺明確結算分支")
    if record["outcome"] == "tie":
        require(number(record.get("payout")) == number(record.get("betAmount")), "和局退本需 payout 等於本金")
    result = settle_bet(record["betAmount"], record["companyShare"], record["agentShares"],
                        record["diffs"], is_win=record["outcome"] == "won",
                        holding_share=record.get("holdingShare", 0))
    actual = vector(record, "actualGapMoney", 9)
    assert result["delta_sum"] == 0, "輸入占成／差分守恆不符"
    assert actual == result["gap_money"], f"注單 {record['betId']} 九層收益錯誤：實際 {actual}，期望 {result['gap_money']}"
    return result


def zero_conditions(record, result):
    conditions = []
    if record["outcome"] == "lost": conditions.append("輸局")
    if record["outcome"] in ("refund", "tie"): conditions.append("和局退本")
    if record["outcome"] == "won":
        if any(number(v) == 0 for v in record["diffs"][1:]): conditions.append("有效差為零")
        if any(v == 0 for v in result["remit"]): conditions.append("上繳額為零")
    return conditions


def verify_pricing(record):
    """使用下注時公司解析值與已套授權的原差分，驗截斷後凍結值。"""
    company = number(record.get("companyResolvedOdds"))
    low = number(record.get("minOddsAtBet"))
    gaps = vector(record, "chainGapsAtBet", 10)
    require(all(g <= 0 for g in gaps), "原差分須非正數")
    require(company >= low >= 0, "解析賠率低於最低值，需補明確規格")
    expected = player_odds(company, gaps, low)
    assert number(record.get("frozenOdds")) == expected, f"{record['betId']} 凍結賠率不符"
    assert vector(record, "diffs", 10) == [-g for g in effective_gaps(company, gaps, low)], "逐層凍結有效差／最深層截斷不符"
    return expected


#: 七碼在**注單層**有 32 個獨立 playTypeId，設定頁／賠率頁只露出 8 個 `sevenNumberOdd{k}` 代表列。
#: ⚠️ 只認 `sevenNumberOdd` 前綴會讓 `sevenNumberBig3` 這類葉被標成 standard 而**直接通過、完全繞過四葉檢查**
#: （2026-09-18 發現，與先前修掉的 miss5～12 漏驗同型）。
SEVEN_LEAF_PREFIXES = ("sevenNumberOdd", "sevenNumberBig", "sevenNumberEven", "sevenNumberSmall")

#: 「两面」(`twoWay`) 同樣是代表列，注單層對應下列 5 個葉，皆不在 101 列或 102 列清單中。
#: 這些葉不可當一般分支計入 standard 覆蓋 —— 否則一注 twoWay 就會被當成「一般玩法已驗」。
TWO_WAY_LEAF_PLAYS = {
    "positionBigSmall", "positionOddEven", "positionDigitSumOddEven",
    "positionTailBigSmall", "sumBigSmall",
}


def seven_representative(play, declared=None):
    """由注單層的七碼葉 id 反推代表值 k：单k≡大k≡双(7−k)≡小(7−k)。

    `declared` 為記錄自填值，有填就必須與葉 id 反推的結果一致 —— 不允許自填標籤蓋過實際玩法。
    """
    for prefix, invert in (("sevenNumberOdd", False), ("sevenNumberBig", False),
                           ("sevenNumberEven", True), ("sevenNumberSmall", True)):
        if play.startswith(prefix):
            suffix = play[len(prefix):]
            require(suffix.isdigit(), f"七碼葉 {play} 缺數字後綴")
            index = int(suffix)
            require(0 <= index <= 7, f"七碼葉 {play} 的索引須0～7")
            k = 7 - index if invert else index
            require(declared is None or declared == k,
                    f"七碼代表值自填 {declared} 與葉 {play} 反推的 {k} 不符")
            return k
    require(False, f"{play} 不是七碼葉")


def verify_special(record):
    """主副鏈分開驗算，分支與實際欄位核對，不能只靠自填 branch 標籤。"""
    require(record.get("playTypeId") not in UNRESOLVED_MISS_PLAYS,
            "不中副欄的投注選用與凍結規則尚未確認，不能按一般或主副擇一玩法判定")
    expected = verify_pricing(record)
    rule = record.get("rule")
    require(rule in ("standard", "single-main", "single-sub", "linked-main", "linked-sub",
                     "dual-main", "dual-sub", "seven"), "缺特殊玩法映射規則")
    play = record["playTypeId"]
    singles = {"zodiacHit", "zodiacMiss", "tailNumberHit", "tailNumberMiss", "bonusNumberZodiac", "fiveElements"}
    if rule.startswith("single-"):
        require(play in singles, "主副擇一規則與玩法不符")
    if rule.startswith("linked-"):
        require(play.startswith(("chainZodiac", "chainTail")), "連肖連尾規則與玩法不符")
    if rule.startswith("dual-"):
        require(play in {"pickTwoHitBonus", "pickThreeHitTwo"}, "雙凍結規則與玩法不符")
    if rule == "seven":
        require(play.startswith(SEVEN_LEAF_PREFIXES), "七碼規則與玩法不符")
    if rule == "standard":
        require(play not in singles | {"pickTwoHitBonus", "pickThreeHitTwo"} | TWO_WAY_LEAF_PLAYS
                and not play.startswith(("chainZodiac", "chainTail") + SEVEN_LEAF_PREFIXES),
                "特殊玩法不可冒充一般分支")
    if rule in ("single-main", "linked-main"):
        require("frozenSubOddsGap" in record, "缺未使用副層的凍結欄佐證")
        assert record["frozenSubOddsGap"] is None, "未使用副層必須為 NULL"
        assert number(record.get("frozenMainOddsGap")) == -sum(vector(record, "diffs", 10)), "主差凍結合計不符"
    if rule in ("single-sub", "linked-sub"):
        assert number(record.get("frozenMainOddsGap")) == 0, "使用副層卻凍結主差"
        assert number(record.get("frozenSubOddsGap")) == -sum(vector(record,"diffs",10)), "副差凍結合計不符"
    if rule in ("dual-main", "dual-sub"):
        require(isinstance(record.get("otherPricing"), dict), "缺另一層雙凍結證據")
        required = {"companyResolvedOdds", "minOddsAtBet", "chainGapsAtBet", "frozenOdds", "diffs"}
        require(required.issubset(record["otherPricing"]), "另一層不能沿用本層資料補缺")
        verify_pricing({**record, **record["otherPricing"]})
        require(isinstance(record.get("isSubOddsWin"),bool), "缺主副中獎分支")
        assert record["isSubOddsWin"] == (rule == "dual-sub"), "結算未使用對應主副凍結鏈"
        main, sub = (record, record["otherPricing"]) if rule == "dual-main" else (record["otherPricing"], record)
        assert number(record.get("frozenMainOddsGap")) == -sum(vector(main, "diffs", 10)), "雙凍結主差合計不符"
        assert number(record.get("frozenSubOddsGap")) == -sum(vector(sub, "diffs", 10)), "雙凍結副差合計不符"
    if rule == "seven":
        leaves = record.get("sevenLeafGaps", {})
        k = seven_representative(play, record.get("sevenRepresentative"))
        require(isinstance(k,int) and 0 <= k <= 7, "七碼代表值須0～7")
        keys = {f"odd{k}",f"big{k}",f"even{7-k}",f"small{7-k}"}
        require(set(leaves) == keys, "缺七碼四個對應葉的讀回證據")
        assert len({number(v) for v in leaves.values()}) == 1, "七碼四葉差分不同步"
        require(any(number(v) != 0 for v in leaves.values()), "七碼僅全零值，無法證明非零差分同步")
    return expected


def special_coverage_key(record):
    play, rule = record["playTypeId"], record["rule"]
    if rule in ("standard", "seven"):
        return rule
    if rule.startswith("linked-"):
        branch = rule.split("-")[-1]
        return f'{"chainZodiac" if play.startswith("chainZodiac") else "chainTail"}:{branch}'
    return f"{play}:{rule.split('-')[-1]}"


def truncation_coverage(record):
    gaps = vector(record, "chainGapsAtBet", 10)
    budget = number(record["companyResolvedOdds"]) - number(record["minOddsAtBet"])
    if -sum(gaps) <= budget:
        return {"不截斷"}
    covered = {"最低賠率截斷"}
    # 全部縮成零或只有一個負差的樣本，不能區別先縮深層或先縮淺層。
    if budget > 0 and sum(g < 0 for g in gaps) >= 2:
        covered.add("最深層優先可辨識")
    return covered


# 設定頁已確認八個副欄，但投注選用／凍結判準仍未定；保留覆蓋缺口，不能漏樣本即通過。
UNRESOLVED_MISS_PLAYS = {f"miss{count}" for count in range(5, 13)}

SPECIAL_REQUIRED = {f"{play}:sub" for play in UNRESOLVED_MISS_PLAYS} | {"standard", "seven"} | {
    f"{chain}:{branch}" for chain in ("chainZodiac", "chainTail") for branch in ("main", "sub")} | {
    f"{play}:{branch}" for play in (
        "zodiacHit", "zodiacMiss", "tailNumberHit", "tailNumberMiss", "bonusNumberZodiac",
        "fiveElements", "pickTwoHitBonus", "pickThreeHitTwo") for branch in ("main", "sub")}
