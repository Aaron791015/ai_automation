# -*- coding: utf-8 -*-
"""新綜合帳號鏈切換（`XZH_CHAIN`）的離線測試：預設仍是 aaa 鏈，`b` 才換第二條鏈。

用途：2026-10-02 為了兩條鏈併行跑賠率差測試新增切換；本檔守住「預設行為不變」與「b 鏈帳號／鎖檔一起換」。
使用方式：`pytest tests/tooling/test_xzh_chain_switch.py -q`（不連站台、不讀真實 config，以假設定取代）。
前置條件：無。
"""
import os
import subprocess
import sys

import pytest

from xzh_qa import config_loader

FAKE = {"qat": {
    "admin": {"username": "aaron01", "password": "pa"},
    "player": {"username": "aaa010", "password": "pp"},
    "agent_accounts": {"_comment": "x", "aaa111": {"password": "p111"}, "aaa222": {"password": "p222"}},
    "chain_b": {
        "_comment": "第二組",
        "admin": {"username": "aaron02", "password": "qa"},
        "player": {"username": "bbb010", "password": "qp"},
        "agent_accounts": {"bbb111": {"password": "q111"}, "bbb222": {"password": "q222"}},
    }}}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def fake_config(monkeypatch):
    monkeypatch.setattr(config_loader, "get_config", lambda: FAKE)


def test_default_chain_is_a_and_unchanged(fake_config, monkeypatch):
    monkeypatch.delenv("XZH_CHAIN", raising=False)
    assert config_loader.active_chain() == "a"
    assert config_loader.admin_credentials() == ("aaron01", "pa")
    assert config_loader.player_credentials() == ("aaa010", "pp")
    assert config_loader.agent_password("aaa222") == "p222"
    # 預設鏈順序寫死，不隨設定檔改變；鎖檔名與切換前一致
    assert config_loader.chain_accounts() == [f"aaa{i}{i}{i}" for i in range(1, 10)] + ["aaa010"]
    assert config_loader.chain_lock_name() == "aaa111-through-aaa010"


def test_a_value_is_same_as_default(fake_config, monkeypatch):
    monkeypatch.setenv("XZH_CHAIN", "A")
    assert config_loader.active_chain() == "a"
    assert config_loader.admin_credentials()[0] == "aaron01"


def test_aaa111_falls_back_to_admin_password_only_on_chain_a(fake_config, monkeypatch):
    monkeypatch.delenv("XZH_CHAIN", raising=False)
    assert config_loader.agent_password("aaa333") == ""            # 沒配置也沒 fallback
    monkeypatch.setenv("XZH_CHAIN", "b")
    assert config_loader.agent_password("aaa111") == ""            # b 鏈不套 aaa111 的相容 fallback


def test_chain_b_uses_second_group_and_own_lock(fake_config, monkeypatch):
    monkeypatch.setenv("XZH_CHAIN", "b")
    assert config_loader.active_chain() == "b"
    assert config_loader.admin_credentials() == ("aaron02", "qa")
    assert config_loader.player_credentials() == ("bbb010", "qp")
    assert config_loader.agent_password("bbb222") == "q222"
    assert config_loader.chain_accounts() == ["bbb111", "bbb222", "bbb010"]   # 假設定只有兩個代理；`_comment` 不算帳號
    assert config_loader.chain_lock_name() == "bbb111-through-bbb010"


def test_unknown_chain_value_raises_instead_of_falling_back(fake_config, monkeypatch):
    monkeypatch.setenv("XZH_CHAIN", "c")
    with pytest.raises(ValueError):
        config_loader.admin_credentials()


def test_chain_b_without_config_section_raises(monkeypatch):
    monkeypatch.setattr(config_loader, "get_config", lambda: {"qat": {"admin": {"username": "x"}}})
    monkeypatch.setenv("XZH_CHAIN", "b")
    with pytest.raises(KeyError):
        config_loader.admin_credentials()


def _chain_accounts_in_fresh_process(chain):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=os.path.join(ROOT, "tools"))
    env.pop("XZH_CHAIN", None)
    if chain:
        env["XZH_CHAIN"] = chain
    code = ("from xzh_qa.pages.odds_gap_setting_page import CHAIN_ACCOUNTS; "
            "print(','.join(CHAIN_ACCOUNTS))")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                         encoding="utf-8", cwd=ROOT, check=True)
    return out.stdout.strip().split(",")


def test_setting_page_chain_accounts_follow_env_in_a_fresh_process():
    """`CHAIN_ACCOUNTS` 在模組載入時決定，所以用新行程驗證（讀真實 config 的 chain_b 段落）。"""
    assert _chain_accounts_in_fresh_process(None) == [f"aaa{i}{i}{i}" for i in range(1, 10)] + ["aaa010"]
    assert _chain_accounts_in_fresh_process("b") == [f"bbb{i}{i}{i}" for i in range(1, 10)] + ["bbb010"]
