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

import allure
import pytest

from xzh_qa.pages.dashboard_page import AgentHierarchyPage


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
def test_level1_agent_count_matches(company_page):
    """C0：「一级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level1_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：一级代理表格展開「公司～会员」逐層人數，加總等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level1_agent_search_by_account(company_page):
    """C5：「账号/昵称」關鍵字搜尋既有帳號 → 結果只顯示該帳號。

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
def test_level1_agent_cash_mode_shows_withdraw_action(company_page):
    """C6：「资金模式」篩選為「现金」時，結果每列都有「存取款」操作；篩選為「信用」時都沒有。

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
def test_level1_agent_table_columns_present(company_page):
    """C7：一级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level1_agent_status_filter_options(company_page):
    """C8：「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level1_agent_search_boundary(company_page):
    """C9：「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」而非報錯；清空後恢復顯示全部。

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
def test_level1_agent_direct_members_button(company_page):
    """C10：`aaa111` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level1_agent_operators_dialog(company_page):
    """C11：`aaa111` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level1_agent_logs_page(company_page):
    """C12：`aaa111` 的「日志」按鈕導向獨立日誌頁，「操作日志」／「登录日志」兩個子頁籤都能切換
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
def test_level2_agent_count_matches(company_page):
    """C0：「二级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level3_agent_count_matches(company_page):
    """C0：「三级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level4_agent_count_matches(company_page):
    """C0：「四级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level5_agent_count_matches(company_page):
    """C0：「五级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level6_agent_count_matches(company_page):
    """C0：「六级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level7_agent_count_matches(company_page):
    """C0：「七级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level8_agent_count_matches(company_page):
    """C0：「八级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level9_agent_count_matches(company_page):
    """C0：「九级代理」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_member_count_matches(company_page):
    """C0：「会员」子頁面的分頁人數與表格『共 N 条』一致（自檢不變量）。

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
def test_level2_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：二级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level2_agent_search_by_account(company_page):
    """C5：二级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa222`）→ 結果只顯示該帳號。

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
def test_level2_agent_table_columns_present(company_page):
    """C7：二级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level2_agent_status_filter_options(company_page):
    """C8：二级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level2_agent_search_boundary(company_page):
    """C9：二级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 6 筆。

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
def test_level2_agent_direct_members_button(company_page):
    """C10：`aaa222` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level2_agent_operators_dialog(company_page):
    """C11：`aaa222` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level2_agent_logs_page(company_page):
    """C12：`aaa222` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level3_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：三级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level3_agent_search_by_account(company_page):
    """C5：三级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa333`）→ 結果只顯示該帳號。

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
def test_level3_agent_table_columns_present(company_page):
    """C7：三级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level3_agent_status_filter_options(company_page):
    """C8：三级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level3_agent_search_boundary(company_page):
    """C9：三级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 3 筆。

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
def test_level3_agent_direct_members_button(company_page):
    """C10：`aaa333` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level3_agent_operators_dialog(company_page):
    """C11：`aaa333` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level3_agent_logs_page(company_page):
    """C12：`aaa333` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level4_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：四级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level4_agent_search_by_account(company_page):
    """C5：四级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa444`）→ 結果只顯示該帳號。

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
def test_level4_agent_table_columns_present(company_page):
    """C7：四级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level4_agent_status_filter_options(company_page):
    """C8：四级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level4_agent_search_boundary(company_page):
    """C9：四级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

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
def test_level4_agent_direct_members_button(company_page):
    """C10：`aaa444` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level4_agent_operators_dialog(company_page):
    """C11：`aaa444` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level4_agent_logs_page(company_page):
    """C12：`aaa444` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level5_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：五级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level5_agent_search_by_account(company_page):
    """C5：五级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa555`）→ 結果只顯示該帳號。

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
def test_level5_agent_table_columns_present(company_page):
    """C7：五级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level5_agent_status_filter_options(company_page):
    """C8：五级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level5_agent_search_boundary(company_page):
    """C9：五级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

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
def test_level5_agent_direct_members_button(company_page):
    """C10：`aaa555` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level5_agent_operators_dialog(company_page):
    """C11：`aaa555` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level5_agent_logs_page(company_page):
    """C12：`aaa555` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level6_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：六级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level6_agent_search_by_account(company_page):
    """C5：六级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa666`）→ 結果只顯示該帳號。

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
def test_level6_agent_table_columns_present(company_page):
    """C7：六级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level6_agent_status_filter_options(company_page):
    """C8：六级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level6_agent_search_boundary(company_page):
    """C9：六级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

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
def test_level6_agent_direct_members_button(company_page):
    """C10：`aaa666` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level6_agent_operators_dialog(company_page):
    """C11：`aaa666` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level6_agent_logs_page(company_page):
    """C12：`aaa666` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level7_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：七级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level7_agent_search_by_account(company_page):
    """C5：七级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa777`）→ 結果只顯示該帳號。

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
def test_level7_agent_table_columns_present(company_page):
    """C7：七级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level7_agent_status_filter_options(company_page):
    """C8：七级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level7_agent_search_boundary(company_page):
    """C9：七级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

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
def test_level7_agent_direct_members_button(company_page):
    """C10：`aaa777` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level7_agent_operators_dialog(company_page):
    """C11：`aaa777` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level7_agent_logs_page(company_page):
    """C12：`aaa777` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level8_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：八级代理表格展開後逐層人數加總，等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level8_agent_search_by_account(company_page):
    """C5：八级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa888`）→ 結果只顯示該帳號。

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
def test_level8_agent_table_columns_present(company_page):
    """C7：八级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level8_agent_status_filter_options(company_page):
    """C8：八级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level8_agent_search_boundary(company_page):
    """C9：八级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

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
def test_level8_agent_direct_members_button(company_page):
    """C10：`aaa888` 的「直属会员」按鈕導向「会员」分頁並依此帳號過濾（結構性掃描＋現況記錄）。

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
def test_level8_agent_operators_dialog(company_page):
    """C11：`aaa888` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level8_agent_logs_page(company_page):
    """C12：`aaa888` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level9_agent_subordinate_breakdown_sum_matches(company_page):
    """C4：九级代理表格展開後，「会员」欄（唯一更深層）的人數等於收合時「下级」欄的數字（自檢不變量）。

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
def test_level9_agent_search_by_account(company_page):
    """C5：九级代理「账号/昵称」關鍵字搜尋既有帳號（`aaa999`）→ 結果只顯示該帳號。

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
def test_level9_agent_table_columns_present(company_page):
    """C7：九级代理表格（收合狀態）欄位齊全，標籤文字正確（結構性掃描）。

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
def test_level9_agent_status_filter_options(company_page):
    """C8：九级代理「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_level9_agent_search_boundary(company_page):
    """C9：九级代理「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 2 筆。

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
def test_level9_agent_operators_dialog(company_page):
    """C11：`aaa999` 的「操作员」按鈕開啟彈窗，欄位齊全（結構性掃描＋現況記錄）。

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
def test_level9_agent_logs_page(company_page):
    """C12：`aaa999` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_level9_agent_no_direct_members_button(company_page):
    """C13：九级代理的操作欄**沒有**「直属会员」按鈕，只有 编辑／操作员／日志 三個
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
def test_member_search_by_account(company_page):
    """C5：会员「账号/昵称」關鍵字搜尋既有帳號（`aaa010`）→ 結果只顯示該帳號。

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
def test_member_table_columns_present(company_page):
    """C7：会员表格欄位齊全，標籤文字正確（結構性掃描）。

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
def test_member_status_filter_options(company_page):
    """C8：会员「状态」下拉選單正常開啟，選項為【启用／停用／停押】三個（結構性掃描）。

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
def test_member_search_boundary(company_page):
    """C9：会员「账号/昵称」搜尋邊界——查無結果顯示「暂无数据」；清空後恢復顯示全部 17 筆。

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
def test_member_logs_page(company_page):
    """C12：`aaa010` 的「日志」按鈕導向獨立日誌頁，兩個子頁籤都能切換且欄位正確（結構性掃描）。

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
def test_member_no_agent_only_buttons(company_page):
    """C14：会员的操作欄**只有**「编辑／日志」兩個按鈕，沒有「直属会员」「操作员」
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
def test_level1_agent_money_type_filter_options(company_page):
    """C15：一级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level2_agent_money_type_filter_options(company_page):
    """C15：二级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level3_agent_money_type_filter_options(company_page):
    """C15：三级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level4_agent_money_type_filter_options(company_page):
    """C15：四级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level5_agent_money_type_filter_options(company_page):
    """C15：五级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level6_agent_money_type_filter_options(company_page):
    """C15：六级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level7_agent_money_type_filter_options(company_page):
    """C15：七级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level8_agent_money_type_filter_options(company_page):
    """C15：八级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_level9_agent_money_type_filter_options(company_page):
    """C15：九级代理「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
def test_member_money_type_filter_options(company_page):
    """C15：会员「资金模式」下拉選單正常開啟，選項為【信用／现金】兩個（結構性掃描）。

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
