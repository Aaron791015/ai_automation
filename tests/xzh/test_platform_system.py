# -*- coding: utf-8 -*-
"""平台層系統管理/租戶管理案例（案例清單 A5、B7）。"""
from __future__ import annotations

import pytest

from xzh_qa.pages.platform_system_page import ALL_14_GAMES, PlatformSystemPage


@pytest.mark.write_action
def test_global_setting_image_domain_roundtrip(platform_page):
    """A5：全局設置的圖片網域改值並保存 → 重新整理後仍是新值（自檢不變量）。

    CLAUDE.md §5：測試資料用完即還原——結尾把原值填回去。
    """
    page = platform_page
    sp = PlatformSystemPage(page)
    sp.goto_global_setting()
    original = sp.image_domain()
    probe_value = "xzh-probe.example.com"  # 欄位名稱是「圖片網域」，實測會拿掉 scheme，探測值直接用純網域
    sp.set_image_domain(probe_value)
    sp.save()
    page.reload()
    assert sp.image_domain() == probe_value

    sp.set_image_domain(original)
    sp.save()


@pytest.mark.smoke
def test_company1_all_14_games_enabled(platform_page):
    """B7：company1「游戏」設定頁，14 個彩種目前皆為啟用（範圍快照，唯讀）。

    2026-08-26 使用者裁定：本專案只測其中 3 個，其餘 11 個不追蹤，
    但這裡先釘住「現況是全部啟用」做 regression，避免範圍被誤改都沒人發現。
    """
    page = platform_page
    ps = PlatformSystemPage(page)
    ps.goto_games("company1")
    for game in ALL_14_GAMES:
        assert ps.is_game_enabled(game), "%s 應為啟用（探索當下現況）" % game
