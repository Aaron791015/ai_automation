# -*- coding: utf-8 -*-
"""新綜合（xzh）測試共用 fixtures：已登入的 page（平台層／公司層）。

前置條件：`config/environments.json` 的 `xzh.qat` 需已填好網址與帳密
         （`scripts/new_product.py` 建立時已放好骨架，2026-08-26 已補上實際值）。
"""
from __future__ import annotations

import pytest

from xzh_qa.config_loader import admin_credentials, qat
from xzh_qa.pages.login_page import LoginPage


@pytest.fixture
def xzh_qat():
    return qat()


@pytest.fixture
def platform_page(page, xzh_qat):
    """已登入平台層（含 2FA，QAT 目前任意 6 位數字即可通過）的 page。"""
    username, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_platform_url"])
    lp.login(username, password)
    if lp.is_otp_page():
        lp.submit_otp("123456")
    return page


@pytest.fixture
def company_page(page, xzh_qat):
    """已登入公司層的 page（目前不會跳 2FA，原因未明，見矩陣 A2）。"""
    username, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_company_url"])
    lp.login(username, password)
    return page


@pytest.fixture
def level1_agent_page(page, xzh_qat):
    """已登入一級代理層的 page。

    代理測試帳號是可審查的 QAT 測試資料；密碼與現有 QAT admin 共用，
    只由既有設定讀取，不另寫入測試碼、文件或 Allure 附件。
    """
    _, password = admin_credentials()
    lp = LoginPage(page)
    lp.goto(xzh_qat["backend_company_url"])
    lp.login("aaa111", password)
    if lp.is_otp_page():
        lp.submit_otp("123456")
    return page


# ---------------------------------------------------------------------------
# 賠率差（B88～B92、B98～B101）共用 fixtures
# ---------------------------------------------------------------------------

import json
import os

from xzh_qa.config_loader import agent_password
from xzh_qa.odds_gap_client import OddsGapClient
from xzh_qa.odds_gap_flows import GapContext
from xzh_qa.odds_gap_run_state import OddsGapRunState
from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS

_MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "xzh", "odds_gap_manifest.json")


@pytest.fixture(scope="session")
def odds_gap_manifest():
    """玩法／主副分支回歸快照（`data/xzh/odds_gap_manifest.json`）。

    ⚠️ 它是 2026-09-15 的**回歸基準**，不是已核准的規格；與現況不符時先判缺陷／開單，
    ⛔ 不得因為實測不同就直接改這份檔（CLAUDE.md §6「實測與文件不符」）。
    """
    with open(_MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def odds_gap_chain_exclusive(request):
    """整條帳號鏈共用同一鎖，避免不同層級各鎖各的而互相干擾。"""
    if "odds_gap_run" not in request.fixturenames and not request.node.name.startswith("test_odds_gap_"):
        yield
        return
    from xzh_qa.odds_gap_run_state import ChainBusy
    pause_file = os.environ.get("XZH_GAP_PAUSE_FILE")
    if pause_file and os.path.exists(pause_file):
        pytest.exit("已到安全批次邊界；上一案例已完成收尾，依停止檔不啟動下一案例", returncode=2)
    stop_file = os.environ.get("XZH_GAP_STOP_FILE")
    if stop_file and os.path.exists(stop_file):
        pytest.exit("有未解決還原異常，停止後續案例；請先核對 restore-pending 紀錄", returncode=2)
    state = OddsGapRunState.start("chain-owner")
    try:
        with state.chain_lock("aaa111-through-aaa010"):
            yield
    except ChainBusy as exc:
        pytest.skip(f"BLOCKED：{exc}")


@pytest.fixture
def odds_gap_run(request):
    """本次執行的狀態根目錄（`reports/odds_gap_runs/<run_id>/`），含日誌、快照與還原守衛。"""
    return OddsGapRunState.start(request.node.name)


@pytest.fixture
def odds_gap_login(browser, xzh_qat):
    """依帳號開一個**獨立 context** 並登入公司後台，回傳已登入的 page。

    不同身分各用獨立 context（規劃 §13.2），⛔ 不在同源分頁混用 token。
    context 在測試結束時一併關閉。
    """
    opened = []
    sessions = {}

    def _login(username: str):
        key = username
        if key in sessions:
            return sessions[key]
        password = agent_password(username) if username != "__company__" else None
        if username == "__company__":
            username, password = admin_credentials()
        assert password, f"{username} 沒有可用的測試密碼；請在 config 的 xzh.qat.agent_accounts 補上"
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        opened.append(context)
        page = context.new_page()
        page.set_default_timeout(20000)
        lp = LoginPage(page)
        lp.goto(xzh_qat["backend_company_url"])
        lp.login(username, password)
        if lp.is_otp_page():
            lp.submit_otp("123456")
        sessions[key] = page
        return page

    yield _login
    for context in opened:
        context.close()


@pytest.fixture
def odds_gap_platform_cap(browser, odds_gap_run):
    """先獨立讀平台company1上限，再允許公司登入；缺來源只阻擋公式判定。"""
    from xzh_qa.odds_gap_cap_source import read_platform_cap
    with browser.new_context(viewport={"width": 1920, "height": 1080}) as context:
        try:
            evidence = read_platform_cap(context.new_page(),
                                         str(odds_gap_run.dir) + "/platform-cap-before.png")
        except Exception as exc:
            evidence = {"source": "platform-company-edit", "account": "company1",
                        "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
    odds_gap_run.dump("platform-cap-before.json", evidence)
    return evidence


@pytest.fixture
def gap_context(odds_gap_login, odds_gap_run, odds_gap_platform_cap):
    """建立某個設定目標的操作上下文。

    `via="parent"`（預設）＝由**直屬上級**操作：一級由公司，二～九級與會員由其上一層代理。
    `via="company"` ＝一律由公司操作——用於 Snotra-006（公司保存下級 403）的回歸，
    ⛔ 失敗時不得自動改走 parent 再宣稱公司路徑通過。
    """
    reference = {}

    def _reference_client():
        """公司身分的唯讀 client——基準／最低賠率只有公司讀得到（代理讀 OddsSetting 為 403）。

        每個測試只建一次並重用，避免每個目標都多登入一次公司。
        """
        if "client" not in reference:
            page = odds_gap_login("__company__")
            observed = OddsGapClient.attach(page)
            probe = GapContext(page=page, target_index=0, run=odds_gap_run,
                               client=None, observed=observed)
            probe.setting.open_target(probe.level_name, probe.account)
            probe.setting.select_game("markSix")
            reference["client"] = OddsGapClient.from_page(page, observed)
            reference["client"].platform_cap_evidence = odds_gap_platform_cap
        return reference["client"]

    def _build(target_index: int, via: str = "parent") -> GapContext:
        if via == "company" or target_index == 0:
            operator = "__company__"
        else:
            operator = CHAIN_ACCOUNTS[target_index - 1]
        page = odds_gap_login(operator)
        observed = OddsGapClient.attach(page)
        # 先開一次目標頁把 Authorization 攔下來，再建立唯讀 client
        setting_probe = GapContext(page=page, target_index=target_index, run=odds_gap_run,
                                   client=None, observed=observed)
        setting_probe.setting.open_target(setting_probe.level_name, setting_probe.account)
        setting_probe.setting.select_game("markSix")
        client = OddsGapClient.from_page(page, observed)
        client.platform_cap_evidence = odds_gap_platform_cap
        odds_gap_run.log({"phase": "prepare", "operator": operator,
                          "target": CHAIN_ACCOUNTS[target_index], "via": via})
        if operator == "__company__" and "client" not in reference:
            # 本層操作者本身就是公司身分時，直接重用這個剛登入的 context 當唯讀基準 client，
            # ⛔ 不要再另外呼叫 `_reference_client()` 開第二個公司登入——
            # 2026-09-16 實測發現：同一個公司帳號在兩個瀏覽器 context 同時登入，
            # 會被後端判定「账号已在其他地方登录」而互踢，導致先開的那個 session
            # 在後續 `reload_tab` 時被踢回登入頁，使保存後的還原步驟整段中斷、
            # 值留在已修改狀態（B92 對 aaa111／index 0 每次執行必定重現）。
            reference["client"] = client
        def recover():
            # 403 跳登入後只為核對／還原重新登入同一操作身分，不切換路徑。
            username, password = (admin_credentials() if operator == "__company__"
                                  else (operator, agent_password(operator)))
            lp = LoginPage(page)
            lp.goto(qat()["backend_company_url"])
            lp.login(username, password)
            if lp.is_otp_page():
                lp.submit_otp("123456")
            setting_probe.setting.open_target(setting_probe.level_name, setting_probe.account)
            setting_probe.setting.select_game("markSix")
            client.headers = dict(observed["headers"])

        return GapContext(page=page, target_index=target_index, run=odds_gap_run,
                          client=client, observed=observed,
                          recover=recover,
                          reference_client=_reference_client(),
                          # 一級代理沒有祖先層 → 祖先合計為 0；仍需實際比例才可判絕對公式；
                          # 其餘層級預設 None（未載入），由案例自行補上再驗絕對值。
                          ancestor_rows=[] if target_index == 0 else None)

    return _build
