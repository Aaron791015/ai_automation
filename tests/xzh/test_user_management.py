# -*- coding: utf-8 -*-
"""用户管理選單案例（案例清單 C0；2026-08-28 依子頁面補齊）。

「用户管理」底下的「一级代理」…「会员」是**真正的子頁面**（role=menuitem，切換會改變
URL query string，元素 role 跟「系统设置」「报表」底下的子選單同一種結構），不是同頁篩選。

⚠️ 十條案例故意寫成 10 個獨立函式、不用 `@pytest.mark.parametrize`：`allure.dynamic.suite()`
（parametrize 常見的動態標籤寫法）只在**真正執行**測試時才生效，`pytest --collect-only`
（test_platform 案例瀏覽器讀案例清單用的模式）讀不到，會讓 10 條案例在網頁上全部變成
「無 suite」、失去分組意義。要讓子頁面分組在**不執行、只收集**的情況下也讀得到，必須用
**靜態**的 `@allure.suite("...")` 裝飾器——這代表每個子頁面得各自一個函式，不能用
parametrize 共用（`test_system_setting.py` 也是同一種寫法，理由相同）。
"""
from __future__ import annotations

import io
import json
import os

import allure
import pytest

from xzh_qa.odds_gap_client import GAMES, gap_values
from xzh_qa.odds_gap_flows import (
    check_boundary_inputs, check_rows, describe_scope, run_save_flow, scope_games,
)
from xzh_qa.odds_gap_oracle import dec, effective_gaps, level_diffs, player_odds
from xzh_qa.pages.dashboard_page import AgentHierarchyPage
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS


def _check(company_page, level: str) -> None:
    """讀取指定層級子頁面的分頁人數與表格筆數並比對。

    ⚠️ 2026-08-31 更正：「導覽到用户管理頁、切換到哪個子頁面」這個 step 刻意**不**放在
    這個共用 helper 裡——test_platform 的 `_step_texts()` 是靜態解析原始碼，這裡若寫
    `f"...切換到「{level}」子頁面"`，10 個呼叫端（level1~9＋会员）在 test_platform 上
    會全部顯示同一個沒解開的 `{level}` 佔位符，看不出各自測的是哪個層級。改成由**每個
    呼叫端自己**用具體層級名稱包一層 `allure.step`（見下方 10 個 `test_levelN_...` 函式），
    這裡只保留跟層級名稱無關的共用步驟。
    """
    page = company_page
    ah = AgentHierarchyPage(page)
    ah.goto()
    ah.switch_tab(level)
    with allure.step("讀取分頁標籤人數與表格「共 N 条」的數字"):
        tab_count = ah.tab_label_count(level)
        table_count = ah.table_total_count()
    allure.attach(
        f"分頁標籤人數：{tab_count}\n表格「共 N 条」：{table_count}（期望：兩者相等）",
        name=f"{level} 分頁人數 vs 表格筆數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert tab_count == table_count


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：一级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level1_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：一级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「一级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「一级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「一级代理」子頁面"):
        _check(company_page, "一级代理")


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：一级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level1_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：一级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。記錄 aaa111 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa111 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：一级代理表格展開「公司～会员」逐層人數，加總等於收合時「下级」欄的數字（自檢不變量）。

    ⚠️ 編號從 C4 起——`新綜合_案例清單.md` 的 C1～C3 已配給「遊戲規則頁」三案例
    （`test_game_rule.py`），C 系列下一個空號是 C4。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 讀取任一列（`aaa111`，9 層下線皆有 1 人）收合狀態的「下级」欄總數
    3. 點「展开 »」，讀取同一列「二级代理～会员」逐層人數欄
    4. 逐層人數加總 vs 步驟 2 的「下级」總數

    預期結果：
    - 兩者相等

    oracle 來源：B 級（自檢不變量——「下级」欄本來就該是逐層人數的加總，2026-08-28 探索時
    以 `aaa111`（各層 1 人，合計 9）與 `tc1001`（各層 1 人＋会员 3 人，合計 11）交叉驗證過）。
    """
    ah = AgentHierarchyPage(company_page)
    account = "aaa111"
    with allure.step("導覽到「用户管理→一级代理」，讀取「aaa111」收合狀態的「下级」欄總數"):
        ah.goto()
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列「二级代理～会员」逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="一级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：一级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level1_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：一级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa111」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa111。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：「账号/昵称」關鍵字搜尋既有帳號 → 結果只顯示該帳號。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 在「账号/昵称」輸入既有帳號 `aaa111` 並送出

    預期結果：
    - 表格只剩 1 列，账号為 `aaa111`

    oracle 來源：B 級（自檢一致性——篩選條件與結果集的對應關係）。

    ⚠️ 2026-08-28 使用者裁示：測試資料僅能用 `aaa111` 及其下線，`tc1001`／`cashline1`／
    `e2ea1` 不可再引用（原本此案例用 `tc1001` 當搜尋樣本，已改為 `aaa111`）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」"):
        ah.goto()
    with allure.step("在「账号/昵称」輸入既有帳號「aaa111」並送出"):
        ah.search_account("aaa111")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa111']）",
        name="一级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa111"]


@allure.suite("一级代理")
@pytest.mark.skip(
    reason="C6：2026-08-28 探索時發現「资金模式=现金」的一级代理只有 cashline1／e2ea1 兩個帳號，"
    "但使用者裁示測試資料僅能用 aaa111 及其下線，這兩個現金帳號不可再引用；aaa111 本身是信用模式"
    "（A~I 盤口、無存取款鈕），撐不起「现金」那一半的正向驗證。使用者已表示之後會建立一個现金模式"
    "的測試帳號並告知帳號，屆時把 filter_money_type('现金') 那段接回來即可——AgentHierarchyPage 的"
    "filter_money_type／table_rows 方法已就緒，不必重寫。"
)
@allure.title('[功能驗證] C6：一级代理：切換資金模式後，「存取款」操作是否符合模式')
@allure.sub_suite("一般管理")
def test_level1_agent_cash_mode_shows_withdraw_action(company_page):
    """平台案例：[功能驗證] C6：一级代理：切換資金模式後，「存取款」操作是否符合模式
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 執行前需取得允許使用的現金及信用帳號；目前 aaa111 鏈僅能支撐信用條件。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 選「资金模式＝现金」，逐列核對「存取款」按鈕。
    3. 改選「资金模式＝信用」，逐列核對操作欄。
    預期結果：
    - 現金結果非空且每列都有「存取款」；信用結果非空且每列都沒有「存取款」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此案例保留 skip：缺少使用者允許的現金模式測試帳號，尚未實作完整正反向操作；不得將略過視為通過。
    實作備註：
    C6：「资金模式」篩選為「现金」時，結果每列都有「存取款」操作；篩選為「信用」時都沒有。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 篩選「资金模式=现金」，讀取所有列的操作欄
    3. 篩選「资金模式=信用」，讀取所有列的操作欄

    預期結果：
    - 「现金」篩選結果每列都有「存取款」按鈕
    - 「信用」篩選結果沒有任何一列有「存取款」按鈕

    oracle 來源：B 級（正反向都驗）。⚠️ 目前 skip，見上方 skip reason。
    """
    with allure.step("略過：现金模式測試帳號尚未建立（見上方 skip 原因）"):
        pass


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：一级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level1_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：一级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／一级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：一级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 讀取表格欄位標題（不展開「公司～会员」逐層欄）

    預期結果：
    - 依序為 账号／昵称／盘口／额度／余额／上级／一级代理／下级／状态／在线状态／操作，共 11 欄

    oracle 來源：B 級（結構快照，作為 regression baseline——本專案無其他頁面規格文件可比對，
    2026-08-28 探索當下實際欄位即基準）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」"):
        ah.goto()
    with allure.step("讀取表格欄位標題（不展開「公司～会员」逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级",
                "一级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="一级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：一级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level1_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：一级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 點開「状态」下拉

    預期結果：
    - 選項依序為 启用／停用／停押

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身正不正常（開得起來、選項對），
    **不驗篩選結果**——目前 11 個一级代理全部是「启用」，沒有「停用」「停押」樣本可比對
    篩選結果是否正確收斂，那條案例留待有對應樣本時再補（testcase-design §6②邊界樣本）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」"):
        ah.goto()
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="一级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：一级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level1_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：一级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 11 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 11 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 11 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」而非報錯；清空後恢復顯示全部。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 輸入一個確定不存在的帳號關鍵字並送出
    3. 清空輸入框並再次送出

    預期結果：
    - 步驟 2：畫面顯示「暂无数据」，不報錯、不是空白頁
    - 步驟 3：表格恢復顯示全部 11 筆

    oracle 來源：B 級（自檢一致性——查無結果與清空後的行為都是系統自身邏輯）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」"):
        ah.goto()
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="一级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：11）",
        name="一级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 11


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：一级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level1_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：一级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa111 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 點 aaa111 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa111` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 點 `aaa111` 列的「直属会员」

    預期結果：
    - 顯示「暂无数据」——現況記錄：`aaa111` 的下線是走完整 9 層鏈到最後一位會員
      （見 C4 逐層人數欄），該會員是**間接**下線，不是 `aaa111` 的**直屬**會員，
      兩者語意不同，此處 0 筆是預期中的現況，不是缺陷

    oracle 來源：B 級（現況記錄，非正確性判斷——類比案例清單 A4 的記法）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」"):
        ah.goto()
    with allure.step("點「aaa111」列的「直属会员」"):
        ah.open_direct_members("aaa111")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa111 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa111 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：一级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level1_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：一级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa111 尚未建立操作員。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 點 aaa111 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa111 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa111` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 點 `aaa111` 列的「操作员」

    預期結果：
    - 彈出對話框，標題為「aaa111 的操作员」
    - 欄位依序為 账号／昵称／操作员组／状态／在线状态／操作
    - 現況顯示「暂无数据」（`aaa111` 尚未設定任何操作員，現況記錄非缺陷）

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」"):
        ah.goto()
    with allure.step("點「aaa111」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa111")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa111 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：一级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level1_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：一级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa111 需已有操作紀錄及登入紀錄。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。點 aaa111 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    - 兩類日誌各至少 1 筆。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    實作備註：
    C12：`aaa111` 的「日志」按鈕導向獨立日誌頁，「操作日志」／「登录日志」兩個子頁籤都能切換
    且各自欄位正確、有資料（結構性掃描）。

    步驟：
    1. 導覽到「用户管理→一级代理」
    2. 點 `aaa111` 列的「日志」（預設落在「操作日志」子頁籤）
    3. 切換到「登录日志」子頁籤

    預期結果：
    - 「操作日志」欄位含 類型／操作动作／目标／变更项／变更前值／变更后值／操作者／IP 地址／时间，
      且至少 1 筆紀錄（`aaa111` 建立時就會留下帳號/信用額度等變更紀錄）
    - 「登录日志」欄位為 IP 地址／登录时间／登出时间／持续时长／登出原因，
      且至少 1 筆紀錄（本次 MCP 探索登入時已留下）

    oracle 來源：B 級（結構快照＋自檢：兩個子頁籤都應有資料，不是空狀態）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→一级代理」，點「aaa111」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.open_logs_page("aaa111")
        op_headers = ah.logs_table_headers()
        op_row_count = ah.logs_row_count()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）\n筆數：{op_row_count}（期望：>= 1）",
        name="aaa111 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers
    assert op_row_count >= 1

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
        login_row_count = ah.logs_row_count()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）\n筆數：{login_row_count}（期望：>= 1）",
        name="aaa111 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers
    assert login_row_count >= 1


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：二级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level2_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：二级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「二级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「二级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「二级代理」子頁面"):
        _check(company_page, "二级代理")


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：三级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level3_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：三级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「三级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「三级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「三级代理」子頁面"):
        _check(company_page, "三级代理")


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：四级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level4_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：四级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「四级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「四级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「四级代理」子頁面"):
        _check(company_page, "四级代理")


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：五级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level5_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：五级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「五级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「五级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「五级代理」子頁面"):
        _check(company_page, "五级代理")


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：六级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level6_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：六级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「六级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「六级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「六级代理」子頁面"):
        _check(company_page, "六级代理")


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：七级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level7_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：七级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「七级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「七级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「七级代理」子頁面"):
        _check(company_page, "七级代理")


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：八级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level8_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：八级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「八级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「八级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「八级代理」子頁面"):
        _check(company_page, "八级代理")


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：九级代理：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_level9_agent_count_matches(company_page):
    """平台案例：[功能驗證] C0：九级代理：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「九级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「九级代理」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「九级代理」子頁面"):
        _check(company_page, "九级代理")


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[功能驗證] C0：会员：切換子頁面後，分頁人數與表格總筆數是否一致')
@allure.sub_suite("一般管理")
def test_member_count_matches(company_page):
    """平台案例：[功能驗證] C0：会员：切換子頁面後，分頁人數與表格總筆數是否一致
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 記錄子頁面標籤人數與表格下方「共 N 条」，比對兩者。
    預期結果：
    - 分頁標籤人數等於表格總筆數；採總筆數，不以當頁可見列數替代。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C0：「会员」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

    步驟：
    1. 導覽到「用户管理」頁
    2. 切換到「会员」子頁面
    3. 讀取分頁標籤上顯示的人數，跟表格下方「共 N 条」的數字

    預期結果：
    - 兩個數字應該相等

    oracle 來源：B 級（自檢不變量——分頁標籤數字本來就該等於該層級表格的實際筆數）。
    """
    with allure.step("導覽到「用户管理」頁，切換到「会员」子頁面"):
        _check(company_page, "会员")


# ============================================================================
# 二级代理～会员的結構性掃描（2026-08-28 第二批）：欄位齊全性、下拉選單、搜尋邊界、
# 「直属会员／操作员／日志」三顆按鈕的目的頁結構——比照一级代理（C4~C12）的做法，
# 逐層複算，全部只用 aaa111 的下線鏈帳號（aaa222→aaa333→…→aaa999→aaa010，
# 2026-08-28 探索找出，見各案例說明），沒有新建或引用其他人的測試資料。
#
# 放在檔案最後、接在全部 10 個 C0 之後（沒有跟各層的 C0 交錯排列），純粹是編輯順序的
# 選擇——`case_index.py` 的樹狀化是依 `@allure.suite(...)` 的值分組，不是依檔案內的
# 物理位置，所以底下這些函式仍會正確歸類到各自的「N级代理」「会员」suite 節點下。
# ============================================================================


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：二级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level2_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：二级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。記錄 aaa222 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa222 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：二级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa222`（aaa111 下線鏈第 2 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」，讀取「aaa222」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("二级代理")
        account = "aaa222"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="二级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：二级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level2_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：二级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa222」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa222。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：二级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa222`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa222」並送出"):
        ah.search_account("aaa222")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa222']）",
        name="二级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa222"]


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：二级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level2_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：二级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／二级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：二级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "二级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="二级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：二级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level2_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：二级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：二级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="二级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：二级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level2_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：二级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 6 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 6 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 6 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：二级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 6 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="二级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：6）",
        name="二级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 6


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：二级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level2_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：二级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa222 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 點 aaa222 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa222` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa222` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("點「aaa222」列的「直属会员」"):
        ah.open_direct_members("aaa222")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa222 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa222 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：二级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level2_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：二级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa222 尚未建立操作員。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 點 aaa222 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa222 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa222` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("點「aaa222」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa222")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa222 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：二级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level2_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：二级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。點 aaa222 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa222` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→二级代理」，點「aaa222」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("二级代理")
        ah.open_logs_page("aaa222")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa222 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa222 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：三级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level3_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：三级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。記錄 aaa333 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa333 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：三级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa333`（aaa111 下線鏈第 3 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」，讀取「aaa333」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("三级代理")
        account = "aaa333"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="三级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：三级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level3_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：三级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa333」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa333。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：三级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa333`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa333」並送出"):
        ah.search_account("aaa333")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa333']）",
        name="三级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa333"]


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：三级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level3_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：三级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／三级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：三级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "三级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="三级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：三级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level3_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：三级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：三级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="三级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：三级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level3_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：三级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 3 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 3 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 3 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：三级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 3 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="三级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：3）",
        name="三级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 3


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：三级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level3_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：三级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa333 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 點 aaa333 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa333` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa333` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("點「aaa333」列的「直属会员」"):
        ah.open_direct_members("aaa333")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa333 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa333 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：三级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level3_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：三级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa333 尚未建立操作員。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 點 aaa333 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa333 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa333` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("點「aaa333」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa333")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa333 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：三级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level3_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：三级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。點 aaa333 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa333` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→三级代理」，點「aaa333」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("三级代理")
        ah.open_logs_page("aaa333")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa333 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa333 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：四级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level4_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：四级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。記錄 aaa444 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa444 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：四级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa444`（aaa111 下線鏈第 4 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」，讀取「aaa444」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("四级代理")
        account = "aaa444"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="四级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：四级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level4_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：四级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa444」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa444。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：四级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa444`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa444」並送出"):
        ah.search_account("aaa444")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa444']）",
        name="四级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa444"]


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：四级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level4_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：四级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／四级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：四级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "四级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="四级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：四级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level4_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：四级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：四级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="四级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：四级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level4_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：四级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 2 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 2 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 2 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：四级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="四级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：2）",
        name="四级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 2


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：四级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level4_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：四级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa444 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 點 aaa444 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa444` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa444` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("點「aaa444」列的「直属会员」"):
        ah.open_direct_members("aaa444")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa444 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa444 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：四级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level4_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：四级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa444 尚未建立操作員。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 點 aaa444 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa444 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa444` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("點「aaa444」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa444")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa444 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：四级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level4_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：四级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。點 aaa444 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa444` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→四级代理」，點「aaa444」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("四级代理")
        ah.open_logs_page("aaa444")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa444 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa444 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：五级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level5_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：五级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。記錄 aaa555 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa555 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：五级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa555`（aaa111 下線鏈第 5 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」，讀取「aaa555」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("五级代理")
        account = "aaa555"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="五级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：五级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level5_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：五级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa555」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa555。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：五级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa555`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa555」並送出"):
        ah.search_account("aaa555")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa555']）",
        name="五级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa555"]


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：五级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level5_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：五级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／五级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：五级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "五级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="五级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：五级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level5_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：五级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：五级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="五级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：五级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level5_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：五级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 2 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 2 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 2 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：五级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="五级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：2）",
        name="五级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 2


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：五级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level5_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：五级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa555 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 點 aaa555 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa555` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa555` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("點「aaa555」列的「直属会员」"):
        ah.open_direct_members("aaa555")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa555 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa555 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：五级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level5_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：五级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa555 尚未建立操作員。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 點 aaa555 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa555 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa555` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("點「aaa555」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa555")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa555 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：五级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level5_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：五级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。點 aaa555 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa555` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→五级代理」，點「aaa555」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("五级代理")
        ah.open_logs_page("aaa555")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa555 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa555 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：六级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level6_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：六级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。記錄 aaa666 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa666 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：六级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa666`（aaa111 下線鏈第 6 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」，讀取「aaa666」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("六级代理")
        account = "aaa666"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="六级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：六级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level6_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：六级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa666」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa666。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：六级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa666`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa666」並送出"):
        ah.search_account("aaa666")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa666']）",
        name="六级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa666"]


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：六级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level6_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：六级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／六级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：六级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "六级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="六级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：六级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level6_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：六级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：六级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="六级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：六级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level6_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：六级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 2 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 2 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 2 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：六级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="六级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：2）",
        name="六级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 2


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：六级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level6_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：六级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa666 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 點 aaa666 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa666` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa666` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("點「aaa666」列的「直属会员」"):
        ah.open_direct_members("aaa666")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa666 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa666 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：六级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level6_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：六级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa666 尚未建立操作員。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 點 aaa666 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa666 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa666` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("點「aaa666」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa666")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa666 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：六级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level6_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：六级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。點 aaa666 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa666` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→六级代理」，點「aaa666」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("六级代理")
        ah.open_logs_page("aaa666")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa666 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa666 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：七级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level7_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：七级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。記錄 aaa777 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa777 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：七级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa777`（aaa111 下線鏈第 7 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」，讀取「aaa777」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("七级代理")
        account = "aaa777"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="七级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：七级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level7_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：七级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa777」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa777。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：七级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa777`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa777」並送出"):
        ah.search_account("aaa777")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa777']）",
        name="七级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa777"]


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：七级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level7_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：七级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／七级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：七级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "七级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="七级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：七级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level7_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：七级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：七级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="七级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：七级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level7_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：七级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 2 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 2 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 2 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：七级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="七级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：2）",
        name="七级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 2


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：七级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level7_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：七级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa777 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 點 aaa777 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa777` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa777` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("點「aaa777」列的「直属会员」"):
        ah.open_direct_members("aaa777")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa777 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa777 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：七级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level7_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：七级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa777 尚未建立操作員。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 點 aaa777 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa777 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa777` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("點「aaa777」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa777")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa777 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：七级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level7_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：七级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。點 aaa777 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa777` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→七级代理」，點「aaa777」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("七级代理")
        ah.open_logs_page("aaa777")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa777 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa777 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：八级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level8_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：八级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。記錄 aaa888 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa888 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：八级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理的 C4 同一套邏輯，改用 `aaa888`（aaa111 下線鏈第 8 層）驗證，
    確認同一元件在不同層級都成立，不是一级代理獨有的巧合。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」，讀取「aaa888」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("八级代理")
        account = "aaa888"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="八级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：八级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level8_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：八级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa888」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa888。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：八级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa888`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa888」並送出"):
        ah.search_account("aaa888")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa888']）",
        name="八级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa888"]


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：八级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level8_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：八级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／八级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：八级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "八级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="八级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：八级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level8_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：八级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：八级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。⚠️ 只驗下拉選單本身，不驗篩選結果——理由同一级代理 C8。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="八级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：八级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level8_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：八级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 2 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 2 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 2 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：八级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="八级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：2）",
        name="八级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 2


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C10：八级代理：點「直属会员」後，間接會員是否不列入直屬結果')
@allure.sub_suite("一般管理")
def test_level8_agent_direct_members_button(company_page):
    """平台案例：[功能驗證] C10：八级代理：點「直属会员」後，間接會員是否不列入直屬結果
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa888 沒有直屬會員，aaa010 位於九級代理下。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 點 aaa888 列的「直属会员」，核對會員結果。
    預期結果：
    - 顯示「暂无数据」；完整下線鏈的 aaa010 為間接會員，不列為此代理的直屬會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 只覆蓋無直屬會員的空結果；既有程式未獨立斷言目標 URL 或有直屬會員的正向情境。
    實作備註：
    C10：`aaa888` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

    現況記錄：`aaa888` 在 aaa111 這條下線鏈裡的直屬下級是下一層代理，不是會員，
    所以「直属会员」現況一定是「暂无数据」——跟一级代理 C10 同一個道理（見該案例說明）。

    oracle 來源：B 級（現況記錄，非正確性判斷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("點「aaa888」列的「直属会员」"):
        ah.open_direct_members("aaa888")
        no_data = ah.shows_no_data()
    allure.attach(
        f"實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}"
        "（期望：顯示——aaa888 的下線是間接下線，非直屬會員，現況記錄非缺陷）",
        name="aaa888 直属会员現況",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：八级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level8_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：八级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa888 尚未建立操作員。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 點 aaa888 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa888 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa888` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("點「aaa888」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa888")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa888 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：八级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level8_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：八级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。點 aaa888 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa888` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→八级代理」，點「aaa888」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("八级代理")
        ah.open_logs_page("aaa888")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa888 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa888 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C4：九级代理：展開逐層人數後，加總是否等於「下级」總數')
@allure.sub_suite("一般管理")
def test_level9_agent_subordinate_breakdown_sum_matches(company_page):
    """平台案例：[功能驗證] C4：九级代理：展開逐層人數後，加總是否等於「下级」總數
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。記錄 aaa999 列收合時的「下级」數值。
    2. 點「展开 »」，讀取 aaa999 列本層以下至「会员」的各層人數並加總。
    預期結果：
    - 展開後各下線層級人數加總，等於同一帳號收合時的「下级」總數；九級只加總會員。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C4：九级代理表格展開後，「会员」欄（唯一更深層）的人數等於收合時「下级」欄的數字（自檢不變量）。

    跟一级代理～八级代理同一套邏輯，但九级代理已經是代理的最後一層，展開後只剩「会员」
    這一欄還是人數（其餘公司～八级代理欄都是占成% 鏈），用 `aaa999` 驗證。

    oracle 來源：B 級（自檢不變量）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」，讀取「aaa999」收合狀態的「下级」欄總數"):
        ah.goto()
        ah.switch_tab("九级代理")
        account = "aaa999"
        collapsed_total = ah.row_collapsed_subordinate_count(account)
    with allure.step("點「展开 »」，讀取同一列逐層人數欄並加總"):
        ah.expand_level_columns()
        breakdown_sum = ah.row_level_breakdown_sum(account, tier="九级代理")
    allure.attach(
        f"收合狀態「下级」欄總數：{collapsed_total}\n逐層人數加總：{breakdown_sum}（期望：兩者相等）",
        name=f"{account} 逐層人數加總 vs 下级欄總數",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert breakdown_sum == collapsed_total


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：九级代理：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_level9_agent_search_by_account(company_page):
    """平台案例：[功能驗證] C5：九级代理：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa999」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa999。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：九级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa999`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa999」並送出"):
        ah.search_account("aaa999")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa999']）",
        name="九级代理帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa999"]


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：九级代理：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_level9_agent_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：九级代理：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／九级代理／下级／状态／在线状态／操作，共 11 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：九级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("讀取表格欄位標題（不展開逐層欄）"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "九级代理", "下级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="九级代理表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：九级代理：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level9_agent_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：九级代理：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：九级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="九级代理狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：九级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_level9_agent_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：九级代理：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 2 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 2 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 2 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：九级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="九级代理搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：2）",
        name="九级代理搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 2


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C11：九级代理：點「操作员」後，彈窗表頭與空資料是否正確')
@allure.sub_suite("一般管理")
def test_level9_agent_operators_dialog(company_page):
    """平台案例：[功能驗證] C11：九级代理：點「操作员」後，彈窗表頭與空資料是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - aaa999 尚未建立操作員。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 點 aaa999 列的「操作员」，讀取彈窗標題、表頭與內容。
    預期結果：
    - 開啟「aaa999 的操作员」彈窗。
    - 表頭依序為：账号／昵称／操作员组／状态／在线状态／操作；內容顯示「暂无数据」。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 空資料為既有環境條件；新增操作員後需調整資料前提，不能直接判產品缺陷。
    實作備註：
    C11：`aaa999` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

    oracle 來源：B 級（結構快照＋現況記錄）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("點「aaa999」列的「操作员」，讀取彈窗欄位與內容"):
        dialog = ah.open_operators_dialog("aaa999")
        headers = dialog.locator("thead th").all_inner_texts()
        dialog_text = dialog.inner_text()
    expected_headers = ["账号", "昵称", "操作员组", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected_headers}\n"
        f"是否含「暂无数据」：{'暂无数据' in dialog_text}（期望：True，現況記錄）",
        name="aaa999 操作员彈窗結構",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected_headers
    assert "暂无数据" in dialog_text


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：九级代理：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_level9_agent_logs_page(company_page):
    """平台案例：[功能驗證] C12：九级代理：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。點 aaa999 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa999` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」，點「aaa999」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("九级代理")
        ah.open_logs_page("aaa999")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa999 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa999 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C13：九级代理：讀取操作欄後，按鈕清單是否符合層級')
@allure.sub_suite("一般管理")
def test_level9_agent_no_direct_members_button(company_page):
    """平台案例：[畫面驗證] C13：九级代理：讀取操作欄後，按鈕清單是否符合層級
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 逐項讀取 aaa999 列操作欄的按鈕名稱。
    預期結果：
    - 按鈕依序為：编辑／操作员／日志。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C13：九级代理的操作欄**沒有**「直属会员」按鈕，只有 编辑／操作员／日志 三個
    （結構性掃描——2026-08-28 探索發現的層級差異，一级代理～八级代理都有這顆按鈕，九级代理沒有）。

    步驟：
    1. 導覽到「用户管理→九级代理」
    2. 讀取 `aaa999` 列操作欄的按鈕清單

    預期結果：
    - 依序為 编辑／操作员／日志，沒有「直属会员」

    oracle 來源：B 級（結構快照——記錄這個邊界層跟其餘代理層級不同的地方，
    避免之後有人以為「一级代理有的按鈕，其餘代理層級應該也都有」而誤判為缺陷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→九级代理」"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("讀取「aaa999」列操作欄的按鈕清單"):
        actions = ah.row_action_names("aaa999")
    allure.attach(
        f"實際按鈕：{actions}（期望：['编辑', '操作员', '日志']，不含「直属会员」）",
        name="九级代理操作欄按鈕",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert actions == ["编辑", "操作员", "日志"]


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[功能驗證] C5：会员：輸入帳號搜尋後，是否只顯示目標帳號')
@allure.sub_suite("一般管理")
def test_member_search_by_account(company_page):
    """平台案例：[功能驗證] C5：会员：輸入帳號搜尋後，是否只顯示目標帳號
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 在「账号/昵称」輸入「aaa010」並按 Enter，記錄結果帳號與筆數。
    預期結果：
    - 結果只有 1 列，帳號為 aaa010。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C5：会员「账号/昵称」關鍵字搜尋既有帳號（`aaa010`）→ 結果只顯示該帳號。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→会员」"):
        ah.goto()
        ah.switch_tab("会员")
    with allure.step("在「账号/昵称」輸入既有帳號「aaa010」並送出"):
        ah.search_account("aaa010")
        names = ah.row_account_names()
    allure.attach(
        f"篩選結果實際帳號：{names}（期望：['aaa010']）",
        name="会员帳號搜尋結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert names == ["aaa010"]


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[畫面驗證] C7：会员：讀取收合表格後，欄位名稱與順序是否符合基準')
@allure.sub_suite("一般管理")
def test_member_table_columns_present(company_page):
    """平台案例：[畫面驗證] C7：会员：讀取收合表格後，欄位名稱與順序是否符合基準
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 保持逐層人數欄收合，逐欄讀取表頭名稱及順序。
    預期結果：
    - 表頭依序為：账号／昵称／盘口／额度／余额／上级／状态／在线状态／操作，共 9 欄。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 此判準為既有 UI 回歸基準，並非獨立產品規格；若規格變更需先更新基準。
    實作備註：
    C7：会员表格欄位齊全，標籤文字正確（結構性掃描）。

    ⚠️ 會員是最底層、沒有下線，欄位比代理層級少兩欄——沒有「本層占成%」欄
    （代理層級的「N级代理」欄），也沒有「下级」欄（2026-08-28 探索發現）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→会员」"):
        ah.goto()
        ah.switch_tab("会员")
    with allure.step("讀取表格欄位標題"):
        headers = ah.column_headers()
    expected = ["账号", "昵称", "盘口", "额度", "余额", "上级", "状态", "在线状态", "操作"]
    allure.attach(
        f"實際欄位：{headers}\n期望欄位：{expected}",
        name="会员表格欄位",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert headers == expected


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[畫面驗證] C8：会员：開啟「状态」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_member_status_filter_options(company_page):
    """平台案例：[畫面驗證] C8：会员：開啟「状态」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 開啟「状态」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 启用／停用／停押。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C8：会员「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→会员」"):
        ah.goto()
        ah.switch_tab("会员")
    with allure.step("點開「状态」下拉"):
        options = ah.status_options()
    allure.attach(
        f"實際選項：{options}（期望：['启用', '停用', '停押']）",
        name="会员狀態下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["启用", "停用", "停押"]


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[邊界驗證] C9：会员：搜尋不存在帳號再清空後，空結果與恢復列表是否正確')
@allure.sub_suite("一般管理")
def test_member_search_boundary(company_page):
    """平台案例：[邊界驗證] C9：会员：搜尋不存在帳號再清空後，空結果與恢復列表是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    - 此層列表需符合原固定基準 17 筆；不存在「不存在的帳號xyz999」。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 在「账号/昵称」輸入「不存在的帳號xyz999」並按 Enter，核對空結果。
    3. 清空「账号/昵称」並按 Enter，記錄恢復後的列表筆數。
    預期結果：
    - 不存在帳號的結果顯示「暂无数据」。
    - 清空後顯示 17 筆；此數字是既有程式的固定環境基準。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 既有程式固定斷言 17 筆且未動態取得篩選前總數；環境帳號增減可能造成失敗，需先區分資料變動與功能缺陷。
    實作備註：
    C9：会员「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 17 筆。

    oracle 來源：B 級（自檢一致性）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→会员」"):
        ah.goto()
        ah.switch_tab("会员")
    with allure.step("輸入一個確定不存在的帳號關鍵字並送出"):
        ah.search_account("不存在的帳號xyz999")
        no_data = ah.shows_no_data()
    allure.attach(
        f"查無結果時實際：{'顯示「暂无数据」' if no_data else '沒有顯示「暂无数据」'}（期望：顯示）",
        name="会员搜尋查無結果",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert no_data

    with allure.step("清空輸入框並再次送出"):
        ah.search_account("")
        names = ah.row_account_names()
    allure.attach(
        f"清空後實際筆數：{len(names)}（期望：17）",
        name="会员搜尋清空後恢復",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert len(names) == 17


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[功能驗證] C12：会员：切換操作與登入日誌後，兩頁表頭是否正確')
@allure.sub_suite("一般管理")
def test_member_logs_page(company_page):
    """平台案例：[功能驗證] C12：会员：切換操作與登入日誌後，兩頁表頭是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。點 aaa010 列「日志」，讀取「操作日志」表頭。
    2. 切換「登录日志」，讀取表頭。
    預期結果：
    - 「操作日志」表頭至少包含「操作动作」與「变更项」。
    - 「登录日志」表頭依序為：IP 地址／登录时间／登出时间／持续时长／登出原因。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 操作日誌僅斷言兩個指定欄位；不宣稱其餘欄位已逐項驗證。
    - 此層既有程式不斷言日誌筆數或內容。
    實作備註：
    C12：`aaa010` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→会员」，點「aaa010」列的「日志」（預設落在「操作日志」）"):
        ah.goto()
        ah.switch_tab("会员")
        ah.open_logs_page("aaa010")
        op_headers = ah.logs_table_headers()
    allure.attach(
        f"操作日志欄位：{op_headers}（期望包含：操作动作、变更项）",
        name="aaa010 操作日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert "操作动作" in op_headers and "变更项" in op_headers

    with allure.step("切換到「登录日志」子頁籤"):
        ah.switch_logs_tab("登录日志")
        login_headers = ah.logs_table_headers()
    expected_login_headers = ["IP 地址", "登录时间", "登出时间", "持续时长", "登出原因"]
    allure.attach(
        f"登录日志欄位：{login_headers}（期望：{expected_login_headers}）",
        name="aaa010 登录日志",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert login_headers == expected_login_headers


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[畫面驗證] C14：会员：讀取操作欄後，按鈕清單是否符合層級')
@allure.sub_suite("一般管理")
def test_member_no_agent_only_buttons(company_page):
    """平台案例：[畫面驗證] C14：会员：讀取操作欄後，按鈕清單是否符合層級
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 逐項讀取 aaa010 列操作欄的按鈕名稱。
    預期結果：
    - 按鈕依序為：编辑／日志。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    實作備註：
    C14：会员的操作欄**只有**「编辑／日志」兩個按鈕，沒有「直属会员」「操作员」
    （結構性掃描——2026-08-28 探索發現：這兩顆按鈕是代理層級專屬的管理功能，
    會員是最底層帳號，沒有下線可管、也不需要操作員帳號）。

    步驟：
    1. 導覽到「用户管理→会员」
    2. 讀取 `aaa010` 列操作欄的按鈕清單

    預期結果：
    - 依序為 编辑／日志

    oracle 來源：B 級（結構快照——避免之後有人以為會員也該有「操作员」按鈕而誤判為缺陷）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理→会员」"):
        ah.goto()
        ah.switch_tab("会员")
    with allure.step("讀取「aaa010」列操作欄的按鈕清單"):
        actions = ah.row_action_names("aaa010")
    allure.attach(
        f"實際按鈕：{actions}（期望：['编辑', '日志']，不含「直属会员」「操作员」）",
        name="会员操作欄按鈕",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert actions == ["编辑", "日志"]


# ============================================================================
# 「资金模式」下拉結構檢查（C15，2026-08-28 第三批）：拆自 C6 —— 下拉選單本身不需要
# 任何帳號就能驗，缺现金帳號只擋得住「篩選後結果對不對」那一半，不該連這條也一起 skip。
# ============================================================================


@allure.suite("一级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：一级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level1_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：一级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：一级代理；涉及指定帳號時使用 aaa111。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「一级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：一级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「一级代理」子頁面"):
        ah.goto()
        ah.switch_tab("一级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="一级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("二级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：二级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level2_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：二级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：二级代理；涉及指定帳號時使用 aaa222。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「二级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：二级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「二级代理」子頁面"):
        ah.goto()
        ah.switch_tab("二级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="二级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("三级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：三级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level3_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：三级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：三级代理；涉及指定帳號時使用 aaa333。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「三级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：三级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「三级代理」子頁面"):
        ah.goto()
        ah.switch_tab("三级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="三级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("四级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：四级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level4_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：四级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：四级代理；涉及指定帳號時使用 aaa444。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「四级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：四级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「四级代理」子頁面"):
        ah.goto()
        ah.switch_tab("四级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="四级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("五级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：五级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level5_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：五级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：五级代理；涉及指定帳號時使用 aaa555。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「五级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：五级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「五级代理」子頁面"):
        ah.goto()
        ah.switch_tab("五级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="五级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("六级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：六级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level6_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：六级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：六级代理；涉及指定帳號時使用 aaa666。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「六级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：六级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「六级代理」子頁面"):
        ah.goto()
        ah.switch_tab("六级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="六级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("七级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：七级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level7_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：七级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：七级代理；涉及指定帳號時使用 aaa777。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「七级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：七级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「七级代理」子頁面"):
        ah.goto()
        ah.switch_tab("七级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="七级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("八级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：八级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level8_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：八级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：八级代理；涉及指定帳號時使用 aaa888。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「八级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：八级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「八级代理」子頁面"):
        ah.goto()
        ah.switch_tab("八级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="八级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("九级代理")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：九级代理：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_level9_agent_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：九级代理：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：九级代理；涉及指定帳號時使用 aaa999。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「九级代理」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：九级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「九级代理」子頁面"):
        ah.goto()
        ah.switch_tab("九级代理")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="九级代理資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


@allure.suite("会员")
@pytest.mark.smoke
@allure.title('[畫面驗證] C15：会员：開啟「资金模式」後，選項名稱與順序是否正確')
@allure.sub_suite("一般管理")
def test_member_money_type_filter_options(company_page):
    """平台案例：[畫面驗證] C15：会员：開啟「资金模式」後，選項名稱與順序是否正確
    前置條件：
    - 環境：QAT 公司後台；使用已配置的公司操作員，執行期間避免同帳號其他登入。
    - 資料：既有 aaa111 → aaa222 → aaa333 → aaa444 → aaa555 → aaa666 → aaa777 → aaa888 → aaa999 → aaa010 下線鏈；不新增帳號。
    - 操作：僅讀取、篩選或導覽；不修改帳號設定。
    測試範圍：
    - 層級：会员；涉及指定帳號時使用 aaa010。
    - 彩種／玩法：不適用，驗證用户管理共用功能。
    步驟：
    1. 公司後台登入 →「用户管理」→「会员」，等待列表載入完成。
    2. 開啟「资金模式」下拉，逐項讀取選項後按 Escape 收起。
    預期結果：
    - 下拉可開啟，選項依序為 信用／现金。
    佐證方式：
    - 保留本層帳號、篩選條件與表頭的截圖；記錄各步驟實際值及預期值；自動化附件依原測試輸出。
    已知問題：
    - 僅檢查選項，不驗選取後的資料篩選；缺少停用／停押或現金模式樣本的覆蓋另列。
    實作備註：
    C15：会员「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

    ⚠️ 只驗下拉選單本身（開得起來、選項對），不驗篩選結果——理由同一级代理 C6 的 skip reason：
    aaa111 整條下線鏈都是信用模式，沒有现金樣本可驗證篩選收斂是否正確，那部分留待使用者
    提供现金測試帳號後再補。這條檢查本身不需要任何帳號，現在就能做。

    oracle 來源：B 級（結構快照）。
    """
    ah = AgentHierarchyPage(company_page)
    with allure.step("導覽到「用户管理」頁，切換到「会员」子頁面"):
        ah.goto()
        ah.switch_tab("会员")
    with allure.step("點開「资金模式」下拉"):
        options = ah.money_type_options()
    allure.attach(
        f"實際選項：{options}（期望：['信用', '现金']）",
        name="会员資金模式下拉選項",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert options == ["信用", "现金"]


# 賠率差人工案例：供平台瀏覽與QA執行；未實作自動化，明確 skip。


@allure.suite("一级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：一级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
def test_level1_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run):
    """平台案例：[畫面驗證] B89：一级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa111（一级代理），直屬上級 公司。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa111 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 一级代理 aaa111；由公司編輯一級代理。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 一级代理 aaa111 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 公司 開啟 aaa111 頁核對並記錄（與公司入口同一條路徑，不重複測試）；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 一级代理 aaa111 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in ("parent",):
        ctx = gap_context(0, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa111 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("一级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：一级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
def test_level1_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run):
    """平台案例：[功能驗證] B90：一级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa111（一级代理），直屬上級 公司。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa111 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 一级代理 aaa111；由公司編輯一級代理。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa111 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa111 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa111 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in ("parent",):
        ctx = gap_context(0, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa111 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("一级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：一级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
def test_level1_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run):
    """平台案例：[邊界驗證] B91：一级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa111（一级代理），直屬上級 公司。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa111 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 一级代理 aaa111；由公司編輯一級代理。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa111 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in ("parent",):
        ctx = gap_context(0, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa111 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("二级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：二级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level2_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：二级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa222（二级代理），直屬上級 aaa111。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa222 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 二级代理 aaa222；公司編輯與直屬上級 aaa111 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 二级代理 aaa222 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa111 開啟 aaa222 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 二级代理 aaa222 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(1, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa222 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("二级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：二级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level2_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：二级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa222（二级代理），直屬上級 aaa111。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa222 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 二级代理 aaa222；公司編輯與直屬上級 aaa111 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa222 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa222 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa222 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(1, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa222 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("二级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：二级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level2_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：二级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa222（二级代理），直屬上級 aaa111。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa222 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 二级代理 aaa222；公司編輯與直屬上級 aaa111 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa222 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(1, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa222 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("三级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：三级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level3_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：三级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa333（三级代理），直屬上級 aaa222。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa333 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 三级代理 aaa333；公司編輯與直屬上級 aaa222 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 三级代理 aaa333 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa222 開啟 aaa333 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 三级代理 aaa333 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(2, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa333 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("三级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：三级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level3_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：三级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa333（三级代理），直屬上級 aaa222。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa333 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 三级代理 aaa333；公司編輯與直屬上級 aaa222 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa333 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa333 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa333 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(2, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa333 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("三级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：三级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level3_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：三级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa333（三级代理），直屬上級 aaa222。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa333 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 三级代理 aaa333；公司編輯與直屬上級 aaa222 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa333 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(2, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa333 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("四级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：四级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level4_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：四级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa444（四级代理），直屬上級 aaa333。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa444 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 四级代理 aaa444；公司編輯與直屬上級 aaa333 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 四级代理 aaa444 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa333 開啟 aaa444 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 四级代理 aaa444 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(3, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa444 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("四级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：四级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level4_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：四级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa444（四级代理），直屬上級 aaa333。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa444 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 四级代理 aaa444；公司編輯與直屬上級 aaa333 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa444 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa444 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa444 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(3, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa444 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("四级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：四级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level4_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：四级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa444（四级代理），直屬上級 aaa333。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa444 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 四级代理 aaa444；公司編輯與直屬上級 aaa333 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa444 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(3, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa444 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("五级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：五级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level5_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：五级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa555（五级代理），直屬上級 aaa444。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa555 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 五级代理 aaa555；公司編輯與直屬上級 aaa444 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 五级代理 aaa555 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa444 開啟 aaa555 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 五级代理 aaa555 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(4, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa555 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("五级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：五级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level5_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：五级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa555（五级代理），直屬上級 aaa444。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa555 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 五级代理 aaa555；公司編輯與直屬上級 aaa444 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa555 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa555 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa555 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(4, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa555 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("五级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：五级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level5_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：五级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa555（五级代理），直屬上級 aaa444。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa555 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 五级代理 aaa555；公司編輯與直屬上級 aaa444 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa555 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(4, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa555 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("六级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：六级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level6_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：六级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa666（六级代理），直屬上級 aaa555。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa666 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 六级代理 aaa666；公司編輯與直屬上級 aaa555 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 六级代理 aaa666 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa555 開啟 aaa666 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 六级代理 aaa666 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(5, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa666 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("六级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：六级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level6_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：六级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa666（六级代理），直屬上級 aaa555。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa666 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 六级代理 aaa666；公司編輯與直屬上級 aaa555 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa666 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa666 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa666 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(5, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa666 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("六级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：六级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level6_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：六级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa666（六级代理），直屬上級 aaa555。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa666 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 六级代理 aaa666；公司編輯與直屬上級 aaa555 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa666 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(5, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa666 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("七级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：七级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level7_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：七级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa777（七级代理），直屬上級 aaa666。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa777 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 七级代理 aaa777；公司編輯與直屬上級 aaa666 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 七级代理 aaa777 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa666 開啟 aaa777 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 七级代理 aaa777 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(6, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa777 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("七级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：七级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level7_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：七级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa777（七级代理），直屬上級 aaa666。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa777 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 七级代理 aaa777；公司編輯與直屬上級 aaa666 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa777 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa777 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa777 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(6, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa777 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("七级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：七级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level7_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：七级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa777（七级代理），直屬上級 aaa666。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa777 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 七级代理 aaa777；公司編輯與直屬上級 aaa666 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa777 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(6, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa777 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("八级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：八级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level8_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：八级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa888（八级代理），直屬上級 aaa777。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa888 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 八级代理 aaa888；公司編輯與直屬上級 aaa777 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 八级代理 aaa888 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa777 開啟 aaa888 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 八级代理 aaa888 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(7, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa888 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("八级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：八级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level8_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：八级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa888（八级代理），直屬上級 aaa777。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa888 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 八级代理 aaa888；公司編輯與直屬上級 aaa777 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa888 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa888 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa888 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(7, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa888 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("八级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：八级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level8_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：八级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa888（八级代理），直屬上級 aaa777。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa888 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 八级代理 aaa888；公司編輯與直屬上級 aaa777 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa888 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(7, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa888 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("九级代理")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：九级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level9_agent_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：九级代理赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa999（九级代理），直屬上級 aaa888。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa999 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 九级代理 aaa999；公司編輯與直屬上級 aaa888 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 九级代理 aaa999 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa888 開啟 aaa999 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 九级代理 aaa999 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(8, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa999 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("九级代理")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：九级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level9_agent_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：九级代理赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa999（九级代理），直屬上級 aaa888。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa999 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 九级代理 aaa999；公司編輯與直屬上級 aaa888 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa999 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa999 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa999 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(8, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa999 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("九级代理")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：九级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_level9_agent_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：九级代理赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa999（九级代理），直屬上級 aaa888。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa999 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 九级代理 aaa999；公司編輯與直屬上級 aaa888 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa999 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(8, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa999 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("会员")
@allure.sub_suite("赔率差分")
@allure.title('[畫面驗證] B89：会员赔率差分：切換彩種後，玩法與主副欄是否完整顯示')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@pytest.mark.parametrize("via", ["company", "parent"])
def test_member_all_levels_fields_and_play_names(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[畫面驗證] B89：会员赔率差分：切換彩種後，玩法與主副欄是否完整顯示
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa010（会员），直屬上級 aaa999。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa010 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 会员 aaa010；公司編輯與直屬上級 aaa999 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 公司登入「用户管理」，確認授權後，開啟 会员 aaa010 的「编辑→赔率差分」，記錄缺頁或可達狀態。
    2. 依序選香港六合彩、英国天天彩、宾果六合彩，逐列核對「玩法／赔率差分／剩余差分」表頭、列名及可輸入主副欄。
    3. 逐一核對七碼的單0～單7八個代表列及每列四葉文字；確認過關不列出、無副賠率玩法不出現副差分欄，記錄新增／缺少的列。
    4. 由直屬上級 aaa999 開啟 aaa010 頁核對並記錄；不保存設定。
    預期結果：
    - 正式表頭與核准玩法清單一致，無截斷、錯名、重複列或漏列；歷史快照不作母體；完整性依正式101列124欄及允許別名判定。
    - 過關不出現在差分設定頁；七碼僅八個代表列，每列顯示四個對應葉；沒有副賠率的玩法不提供副差分欄。
    - 授權成立的 会员 aaa010 有可達入口；不能把代理缺頁改列不適用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    marks = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(9, via=via)
        for game_id in scope_games():
            with allure.step(f"以 {via} 路徑開啟 aaa010 的「赔率差分」分頁，"
                             f"切到 {GAMES[game_id]} 並逐列核對玩法與主副欄"):
                found = check_rows(ctx, game_id, odds_gap_manifest)
            headers = "".join(found["headers"])
            bad = []
            if found["missing"]:
                bad.append(f"缺少列 {found['missing']}")
            if found["unexpected"]:
                bad.append(f"多出列 {found['unexpected']}")
            if found["sub_mismatch"]:
                bad.append(f"主副欄與 subOddsLabel 不符 {found['sub_mismatch']}")
            for name in ("玩法", "赔率差分", "剩余差分"):
                if name not in headers:
                    bad.append(f"表頭缺「{name}」（實際 {found['headers']}）")
            if [n for n in found["ui_names"] if "过关" in n]:
                bad.append("過關出現在差分設定頁（Aaron 2026-09-09 裁定不支援）")
            summary.append(
                f"{via} 路徑｜{GAMES[game_id]}｜列數 {found['ui_row_count']}/"
                f"{found['expected_row_count']}｜欄數 {found['ui_column_count']}/"
                f"{found['expected_column_count']}｜表頭 {found['headers']}｜"
                f"{'／'.join(bad) if bad else '相符'}")
            if bad:
                marks.append({"via": via, "game": game_id, "problems": bad})
    allure.attach("\n".join(summary), name="設定列核對結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not marks, f"設定列核對不符：{marks}"



@allure.suite("会员")
@allure.sub_suite("赔率差分")
@allure.title('[功能驗證] B90：会员赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_member_all_fields_input_plus_minus_save(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[功能驗證] B90：会员赔率差分：逐欄輸入小額差分及點擊加減後，保存重載是否保留
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa010（会员），直屬上級 aaa999。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa010 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    - 額度需保留一次減號的 0.0001；以「目前剩餘−原差分＋測試差分」估算保存後額度，本層逐格重算，不將前輪 213 格數量當作本輪固定值。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 会员 aaa010；公司編輯與直屬上級 aaa999 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa010 每彩種逐欄記錄原值與可用額度；準備 -1.1，若額度不足改 -0.001 並登記原因；連 -0.001 都不足則該格列資料受阻。
    2. 逐欄鍵盤輸入選定值並按 Tab，立即核對沒有回跳、空白或仍為原值；點「−」一次核對減 0.0001，再點「＋」一次核對回到輸入值。
    3. aaa010 每一彩種完成全欄輸入後點「保存」，重新整理並重開該彩種，逐欄比對保存值、剩餘值與未操作欄，留每格成功／失敗紀錄。
    4. 依原始快照逆序還原並保存重載，逐欄確認恢復；aaa010 三彩種全欄均執行，不以其他層結果或抽樣取代。
    預期結果：
    - 輸入、失焦、−、＋與保存重載每一階段皆與預期值一致；任一階段回跳或未寫入即記該格失敗。
    - 本次已實測步進基準 0.0001；輸入 -1.1 時減號後 -1.1001、加號後 -1.1；輸入 -0.001 時減號後 -0.0011、加號後 -0.001。
    - 所有可測格保存後值保留，無跨格／跨彩種誤寫；恢復後與本輪原值一致。
    - -0.001 補測不抵銷整數加小數的 -1.1 覆蓋；無足夠額度的 -1.1 欄位需另外標示未覆蓋。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(9, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa010 的 {GAMES[game_id]} "
                                 f"逐欄輸入、加減、保存、重載並還原"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest)
                problems = []
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}"
                                    f"{'（且跳回登入，見 Snotra-006）' if outcome['bounced_to_login'] else ''}")
                else:
                    if not outcome["saved_all_ok"]:
                        problems.append("有欄位保存重載後未保留輸入值")
                    if outcome["step_ok"] is False:
                        problems.append("「−」／「＋」按鈕未依 0.0001 步進正確增減")
                    if outcome["untouched_changed"]:
                        problems.append(f"未操作欄位被誤改 {outcome['untouched_changed']}")
                    if not outcome["restored"]:
                        problems.append("測試資料未完成還原，需人工確認")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜保存 HTTP {outcome['save_status']}｜"
                    f"可測 {len(outcome['checks'])} 欄／受阻 {len(outcome['blocked'])} 欄｜"
                    f"保存值保留 {outcome['saved_all_ok']}｜加減步進 {outcome['step_ok']}｜"
                    f"未操作欄誤改 {outcome['untouched_changed'] or '無'}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '全部符合'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="保存流程結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"保存流程失敗：{failures}"



@allure.suite("会员")
@allure.sub_suite("赔率差分")
@allure.title('[邊界驗證] B91：会员赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@pytest.mark.parametrize("via", ["company", "parent"])
def test_member_invalid_and_precision_inputs(gap_context, odds_gap_manifest, odds_gap_run, via):
    """平台案例：[邊界驗證] B91：会员赔率差分：輸入零、正數與超位小數後，保存結果是否符合規格
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT；公司操作員；目標帳號 aaa010（会员），直屬上級 aaa999。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、aaa010 的祖先授權與本層主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：僅 会员 aaa010；公司編輯與直屬上級 aaa999 編輯分開記錄；替代路徑通過不抵銷公司缺頁。
    - 代表欄候選玩法快照（2026-09-09 實測，非核准規格；本案例不逐玩法重複非法輸入）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。代表欄涵蓋一般主欄、含副欄及七碼；不同欄位行為不一致時才擴大。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. aaa010 逐彩種記錄代表欄原值；依序測 0、-0.0001、1、-0.00001、abc、空白及貼上文字，每次從原值開始。
    2. 各輸入按 Tab，記錄欄位與提示；點保存並重新整理核對實際儲存值，避免僅看輸入畫面即判成功。
    3. 另將測試差分設為「原差分−當下剩餘差分−0.0001」（取至小數4位）以製造超扣，保存後重新整理核對讀回值；只在核准的隔離資料上操作，不下注。
    4. 每一輸入完成即還原該格並重讀；代表層級與主／副／七碼欄完整覆蓋輸入条件，異常不逐欄重複；行為不一致時擴大同類覆蓋。
    預期結果：
    - 0 與額度足夠的 -0.0001 可保存並讀回；正數 1 不得成為有效正差分。
    - 保存值須符合非正數且最多四位小數；五位小數、空值及文字的拒絕／轉換方式缺明確規格時，記錄實際行為並列待確認，不自行規定截斷或空值等於原值。
    - 超扣可保存，重新整理後讀回值等於輸入值（2026-09-29 新版文件：儲存時不檢查超扣，最終由投注時最低賠率擋住）；新版文件另記「由前端把關」，若日後前端改為阻擋超扣，需先確認變更依據再調整預期。
    - 每次還原讀回一致，錯誤不得導致其他欄位被修改。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 超位小數依 Aaron 最新指示改列待確認，僅記錄行為並列 BLOCKED；非法輸入提示文案與空值處理亦待規格明訂。
    """
    failures = []
    summary = [describe_scope()]
    for via in (via,):
        ctx = gap_context(9, via=via)
        with odds_gap_run.chain_lock(f"{ctx.account}-{via}"):
            for game_id in scope_games():
                with allure.step(f"以 {via} 路徑對 aaa010 的 {GAMES[game_id]} "
                                 f"依序輸入合法與非法值，保存後讀回並逐次還原"):
                    outcome = check_boundary_inputs(ctx, game_id, odds_gap_manifest)
                problems = [f"{x['input']} 讀回 {x['read_back']}，期望 {x['expected']}"
                            for x in outcome["legal"] if not x["ok"]]
                if outcome["positive_persisted"]:
                    problems.append("正數被持久化成有效正差分（規格要求差分 ≤ 0）")
                for x in outcome["undefined"]:
                    if x["read_back"] > 0:
                        problems.append(f"輸入 {x['input']!r} 後讀回正值 {x['read_back']}")
                summary.append(
                    f"{via} 路徑｜{GAMES[game_id]}｜合法輸入 "
                    f"{sum(1 for x in outcome['legal'] if x['ok'])}/{len(outcome['legal'])} 符合｜"
                    f"未定規格輸入 {len(outcome['undefined'])} 項（僅記錄行為，列待確認）｜"
                    f"正數被持久化 {outcome['positive_persisted']}｜"
                    f"{'／'.join(problems) if problems else '符合規格'}")
                if problems:
                    failures.append({"via": via, "game": game_id, "problems": problems})
    allure.attach("\n".join(summary), name="輸入邊界結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, (
        f"輸入邊界不符規格：{failures}。"
        "（五位小數、空值與文字的處置方式規格未定，僅記錄實際行為列待確認，未計入此判定）")



@allure.suite("賠率差分跨層驗證")
@allure.title('[功能驗證] B88：赔率差分：切換上級授權並保存後，下級分頁是否啟用且原值保留')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
@allure.step("逐對取消與恢復授權，核對設定保留及投注凍結證據")
def test_odds_gap_authorization_controls_descendant_tab(browser, gap_context, odds_gap_manifest, odds_gap_run):
    """平台案例：[功能驗證] B88：赔率差分：切換上級授權並保存後，下級分頁是否啟用且原值保留
    前置條件：QAT aaa111～aaa999→aaa010 帳號鏈；使用既有授權，原值須可讀並於操作後還原。
    測試範圍：九組父子關係、三彩種；XZH_GAP_AUTH_LEVELS 可縮小，實際範圍見附件。
    步驟：
    1. 記錄授權與下級三彩種差分；由直屬上級 UI 關閉該代理授權並重新讀回。
    2. 記錄下級分頁是否可見及 API 生效旗標，核對原差分仍保留；finally 恢復授權並核對差分。
    3. 有有效凍結来源及投注計畫時，分別在關閉與恢復後 UI 新下注，等待自然結算，核對有效差停止／恢復套用。
    預期結果：原值保留與還原正確；關閉後受影響收益層有效差為零，恢復後有非零可辨識樣本。
    佐證方式：b88-pairs.json、授權快照、journal、注單ID與來源匯出；公司／直屬路徑依實際操作者記錄。
    已知問題：分頁仍可見不等於差分生效；未取得完整設計判準時只記錄入口現況。缺凍結資料不下注，投注驗證 BLOCKED，UI 子檢查不能當完整通過。
    """

    from xzh_qa.odds_gap_scenarios import run_authorization
    run_authorization(browser, gap_context, odds_gap_run)



@allure.suite("賠率差分跨層驗證")
@allure.title('[邏輯驗證] B92：赔率差分：逐層保存後，「剩余差分」是否累計本層與祖先差分')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.write_action
def test_odds_gap_remaining_across_agent_member_chain(gap_context, odds_gap_manifest, odds_gap_run):
    """平台案例：[邏輯驗證] B92：赔率差分：逐層保存後，「剩余差分」是否累計本層與祖先差分
    前置條件：
    - 執行方式：pytest 自動化，依案例操作 UI；缺凍結資料或必要樣本列 BLOCKED，不代表通過。
    - 環境：QAT 公司後台與各直屬代理；僅使用 aaa111（一級）→ aaa222（二級）→ aaa333（三級）→ aaa444（四級）→ aaa555（五級）→ aaa666（六級）→ aaa777（七級）→ aaa888（八級）→ aaa999（九級）→ aaa010（會員）。
    - 來源：Aaron 2026-09-09～14 指示、新綜合_賠率差公式.md、UI元素對照 §2；优先級：高。
    - 記錄公司功能開關、各層「赚取赔率差」授權與主副差分原值；取得當下基準賠率、最低賠率及實際差分上限比例。不得固定假設最低賠率＝基準×0.8。
    - 設定測試需獨立操作時段，結束依快照逆序還原並重新讀回；遇他人異動先停止還原、保留差異。
    測試範圍：
    - 彩種：香港六合彩、英国天天彩、宾果六合彩；各自獨立執行。
    - 層級：aaa111（一級）→ aaa222（二級）→ aaa333（三級）→ aaa444（四級）→ aaa555（五級）→ aaa666（六級）→ aaa777（七級）→ aaa888（八級）→ aaa999（九級）→ aaa010（會員）；公司編輯與直屬上級編輯分開記錄，後者通過不抵銷公司缺頁。
    - 設定列全量回歸清單（2026-09-09 實測基準，非獨立規格）：特码A／特码B／正码／正特码A／正特码B／两面／二全中／二中特／二特串／三全中／三中二／四全中／生肖中／生肖不中／尾数中／尾数不中／红大／红小／红单／红双／蓝大／蓝小／蓝单／蓝双／绿大／绿小／绿单／绿双／六肖／红波／蓝波／绿波／特肖／二肖连中／二肖连不中／三肖连中／三肖连不中／四肖连中／四肖连不中／五肖连中／五肖连不中／二尾连中／二尾连不中／三尾连中／三尾连不中／四尾连中／四尾连不中／五不中／六不中／七不中／八不中／九不中／十不中／十一不中／十二不中／五中一／六中一／七中一／八中一／九中一／十中一／一粒任中／二粒任中／三粒任中／四粒任中／五粒任中／二合肖中／二合肖不中／三合肖中／三合肖不中／四合肖中／四合肖不中／五合肖中／五合肖不中／单0·大0·双7·小7／单1·大1·双6·小6／单2·大2·双5·小5／单3·大3·双4·小4／单4·大4·双3·小3／单5·大5·双2·小2／单6·大6·双1·小1／单7·大7·双0·小0／五行／肖2／肖3／肖4／肖5／肖6／肖7／尾2／尾3／尾4／尾5／尾6／尾7／一比一／一比二／一比三／一比四／一比五／一比六。
    - 主副欄：每列主欄；下列列另含副欄：二中特／三中二／生肖中／生肖不中／尾数中／尾数不中／特肖／二肖连中／三肖连中／四肖连中／五肖连中／二尾连不中／三尾连不中／四尾连不中／五行。逐欄覆蓋，不抽首／中／末列。
    - 過關不支援：不應出現在差分設定頁；新增或缺少其他列須與核准規格核對，不得只因與舊快照不同就判錯。
    步驟：
    1. 記錄每彩種每玩法的基準、最低、實際上限比例與整條鏈原差分；副欄另記副基準、副最低及副差分。
    2. 由一級至會員依序設定，該格可容納時輸入 -1.1，否則輸入 -0.001；每層保存重載後，逐欄依公式計算並核對本層剩餘。
    3. 保留上層本輪設定，再測下一層；每次核對祖先層未被下級反向改寫、另一彩種及未改主副欄保持原值；會員仍需獨立核對。
    4. 依會員至一級逆序還原全部改動，每次保存重載後核對主副值與剩餘額度恢復。
    預期結果：
    - 主欄剩餘＝（基準賠率−最低賠率）×實際上限比例＋本層主差分＋祖先主差分合計；不包含子孫差分。
    - 副欄獨立使用副基準、副差分與副最低；副最低為 null 才退回主最低。剩餘額度不等於收益金額。
    - 每格保留完整精度期望與 API 實值，畫面另按四位小數比對；API 比對容許差 0.000001、UI 容許差 0.00005，臨界捨入方式待規格確認。
    - 每一層應依實際祖先原值與新值重算；9/9 的 41.993、33.5944、0.8 僅歷史例子，不可固定套用。
    佐證方式：
    - 逐格記錄：登入角色／目標帳號／彩種／玩法／主副欄／原值／輸入值／保存讀回值／預期與實際結果／還原結果。
    - 截圖標示被測欄位與帳號；必要時留去除認證資訊的請求及回應。失敗、受阻與未執行分開記錄。
    已知問題：
    - 自動化狀態：已接線；實際覆蓋依本輪附件，抽測、部分驗證與完整驗收分開判定。
    - Snotra-005：先前公司編輯二級至會員缺差分分頁，九級編輯直屬會員亦缺頁。符合授權前提仍缺頁應判入口失敗，下游測試列受阻，不列通過。
    - 2026-09-09 的各彩種 101 列／116 欄是實測快照；玩法完整性依2026-09-17正式101列124欄規格。今日報表的「位置单双／位置大小」與設定列對應尚待確認，不得自行排除。
    - 最低賠率生成公式未提供；本案例驗證使用 minOdds 的剩餘算法，不宣稱驗證 minOdds 本身正確。
    """
    ancestors_by_game = {g: [] for g in scope_games()}
    failures = []
    blocked_formulas = []
    summary = [describe_scope()]
    for index in range(10):
        ctx = gap_context(index)
        with odds_gap_run.chain_lock(ctx.account):
            for game_id in scope_games():
                ctx.ancestor_rows = list(ancestors_by_game[game_id])
                with allure.step(f"對 {CHAIN_ACCOUNTS[index]} 的 {GAMES[game_id]} 逐欄改值並保存，"
                                 f"以 Decimal 重算剩餘差分後比對 UI 與唯讀 GET"):
                    outcome = run_save_flow(ctx, game_id, odds_gap_manifest,
                                            verify_step_buttons=False,
                                            verify_remaining_formula=True)
                problems = []
                if not outcome["cap_rate_independent"]:
                    blocked_formulas.append(f"{ctx.account}/{game_id}：缺平台實際上限比例")
                if outcome["save_status"] not in (200, 204):
                    problems.append(f"保存回應 HTTP {outcome['save_status']}")
                elif outcome["remaining_all_ok"] is False:
                    problems.append("剩餘差分與 (基準−最低)×比例＋自身差分＋祖先合計 不符")
                elif not outcome["delta_all_ok"]:
                    problems.append("本層差分改動量與剩餘變化量不一致")
                if not outcome["restored"]:
                    problems.append("測試資料未完成還原")
                summary.append(
                    f"{CHAIN_ACCOUNTS[index]}｜{GAMES[game_id]}｜"
                    f"保存 HTTP {outcome['save_status']}｜"
                    f"剩餘絕對值吻合 {outcome['remaining_all_ok']}｜"
                    f"改動量↔剩餘變化量吻合 {outcome['delta_all_ok']}｜"
                    f"還原 {outcome['restored']}｜"
                    f"{'／'.join(problems) if problems else '相符'}")
                if problems:
                    failures.append({"account": CHAIN_ACCOUNTS[index],
                                     "game": game_id, "problems": problems})
        # 逐層往下累積祖先鏈：每一層都由其**直屬上級**身分讀回，不跨權限猜值
        for game_id in scope_games():
            ancestors_by_game[game_id].append(ctx.api_rows(game_id))
    allure.attach("\n".join(summary), name="剩餘差分逐層結果（實際 vs 期望）",
                  attachment_type=allure.attachment_type.TEXT)
    assert not failures, f"剩餘差分公式驗證失敗：{failures}"
    if blocked_formulas:
        pytest.skip(f"BLOCKED（部分）：保存及相對變化已驗；絕對公式缺來源：{blocked_formulas}")



@allure.suite("賠率差分跨層驗證")
@allure.title('[邏輯驗證] B101：赔率差分：逐層設定後，有效賠率與特殊玩法套用是否符合公式')
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.smoke
@allure.step("以下注時解析賠率核對截斷、主副鏈及特殊玩法覆蓋")
def test_odds_gap_effective_odds_and_special_play_rules(company_page, odds_gap_manifest, odds_gap_run):
    """平台案例：[邏輯驗證] B101：赔率差分：逐層設定後，有效賠率與特殊玩法套用是否符合公式
    前置條件：QAT 指定帳號鏈；具完整已結算範圍與下注當時可追溯的公司解析賠率、最低值、授權後設定鏈及有效差。
    測試範圍：三彩種全部適用規則分支，分支內用代表選項；不截斷、最低值截斷、最深層先縮、主副擇一、連肖連尾、雙凍結及七碼同步。
    步驟：
    1. UI 查詢並下鑽完整報表，核對全部注單及凍結來源身分，不以當前設定補下注快照。
    2. 逐注獨立計算凍結賠率與10層有效差，核對主副實際凍結欄及中獎分支。
    3. 三中二／二中特另驗另一側完整凍結定價；七碼核對代表葉對應四葉的非零同步值。
    4. 計算九層收益並比較產品逐注實值與完整範圍報表；核對各彩種分支及截斷樣本齊全。
    預期結果：凍結賠率＝max(當時最低值, 公司解析賠率＋生效差分合計)；截斷從最深層縮減，主副擇一／雙凍結／七碼均與產品相符。
    佐證方式：唯讀稽核來源、完整注單清單、規則覆蓋及九層產品實值；計算附件本身不當通過證據。
    已知問題：本案例使用可追溯既有樣本做唯讀驗算；缺解析值、來源、某分支或截斷樣本列 BLOCKED，不以合成向量代替端到端結果。
    """

    from xzh_qa.odds_gap_audit import AuditBlocked, require, verify_special, verify_settlement, special_coverage_key, truncation_coverage, SPECIAL_REQUIRED
    from xzh_qa.odds_gap_report_checks import checked_audit
    from xzh_qa.odds_gap_oracle import sum_by_level
    try:
        audit, actual = checked_audit(company_page)
        settlements = []
        rules = {g: set() for g in scope_games()}
        truncation = {g: set() for g in scope_games()}
        for record in audit["records"]:
            verify_special(record)
            settlements.append(verify_settlement(record))
            rules[record["gameId"]].add(special_coverage_key(record))
            truncation[record["gameId"]].update(truncation_coverage(record))
        assert sum_by_level(settlements) == actual, "特殊玩法完整範圍收益合計與產品九層報表不符"
        allure.attach(str({"rules": rules, "truncation": truncation, "actual": actual}),
                      "特殊分支與產品收益核對", allure.attachment_type.TEXT)
        required = SPECIAL_REQUIRED
        require(all(v == required for v in rules.values()), f"特殊分支樣本不齊：{rules}")
        require(all(v == {"不截斷", "最低賠率截斷", "最深層優先可辨識"} for v in truncation.values()),
                f"缺不截斷／最低值／可辨識最深層優先樣本：{truncation}")
    except AuditBlocked as exc:
        pytest.skip(f"BLOCKED：{exc}；補齊下注時解析賠率與特殊分支原始稽核後再跑")
