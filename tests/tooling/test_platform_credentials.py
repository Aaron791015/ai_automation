# -*- coding: utf-8 -*-
"""憑證設定與 JIRA 接真（階段 F，2026-08-23）。

用途：平台原本**對設定完全唯讀**。這一階段讓它能寫 `config/config.local.json`
      —— 那是整個平台**唯一會碰憑證**的地方，三條安全紀律一條都不能鬆：

      ① ⛔ **絕不把已存的密碼回傳給瀏覽器**（只回「有沒有設定」）
      ② ⛔ **讀-改-寫，只動平台擁有的鍵** —— 那個檔案還放著別的工具的憑證
      ③ ⛔ **空字串 ＝ 不改，不是清空** —— 表單不回填密碼，
         使用者只改一欄時其他欄送來的就是空字串；當成清空會**把密碼洗掉**

前置條件：⚠️ 匯入延後；全部在 tmp_path 上操作，**不碰真的 config.local.json**。
使用方式：`pytest tests/tooling/test_platform_credentials.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _c():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import core.credentials as C
    return C


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把 LOCAL_PATH 指到暫存檔 —— ⛔ 絕不在測試裡碰真的憑證檔。"""
    C = _c()
    p = str(tmp_path / "config.local.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps({
        "_說明": "別的工具的註解",
        "jira": {"username": "me", "password": "SECRET-PW",
                 "session_cookie": "JSESSIONID=OLD"},
        "crux": {"db_password": "別人的憑證"},          # 平台不擁有這一組
    }, ensure_ascii=False))
    monkeypatch.setattr(C, "LOCAL_PATH", p)
    return C, p


# ─────────────────────────────── ① 不回傳密碼

def test_status不含任何密碼(sandbox):
    C, p = sandbox
    blob = json.dumps(C.status(), ensure_ascii=False)
    assert "SECRET-PW" not in blob
    assert "JSESSIONID=OLD" not in blob
    assert "別人的憑證" not in blob


def test_status只說有沒有設定(sandbox):
    C, _ = sandbox
    j = C.status()["groups"]["jira"]
    assert j["password"]["set"] is True
    assert j["password"]["hint"] is None, "密碼連前綴都不該給"
    # 帳號可以給個認得出來的前綴，但**短值一律不給前綴**（4 碼以內就整個遮掉）
    hint = j["username"]["hint"]
    assert hint in ("…", None), "短帳號不該露出內容：%r" % hint


def test_未設定時也不炸(tmp_path, monkeypatch):
    C = _c()
    monkeypatch.setattr(C, "LOCAL_PATH", str(tmp_path / "不存在.json"))
    s = C.status()
    assert s["groups"]["jira"]["username"]["set"] is False


def test_設定檔壞掉時當成空的(tmp_path, monkeypatch):
    C = _c()
    p = str(tmp_path / "bad.json")
    io.open(p, "w", encoding="utf-8").write("{ 這不是 JSON")
    monkeypatch.setattr(C, "LOCAL_PATH", p)
    assert C.status()["groups"]["jira"]["username"]["set"] is False


# ─────────────────────────────── ② 只動自己的鍵

def test_不動別的工具的憑證(sandbox):
    C, p = sandbox
    C.save({"jira": {"session_cookie": "JSESSIONID=NEW"}})
    after = json.load(io.open(p, encoding="utf-8"))
    assert after["crux"]["db_password"] == "別人的憑證"
    assert after["_說明"] == "別的工具的註解"


def test_只寫OWNED裡宣告的鍵(sandbox):
    C, p = sandbox
    C.save({"jira": {"username": "u2", "亂塞的鍵": "x"},
            "crux": {"db_password": "想蓋掉別人"}})
    after = json.load(io.open(p, encoding="utf-8"))
    assert "亂塞的鍵" not in after["jira"]
    assert after["crux"]["db_password"] == "別人的憑證", "平台不擁有 crux，不該動它"


# ─────────────────────────────── ③ 空字串 ＝ 不改

def test_空字串不會洗掉已存的密碼(sandbox):
    """★ 最危險的一條：表單不回填密碼，使用者只改 cookie 時
    username／password 送來的就是空字串。當成清空會**把密碼洗掉**。"""
    C, p = sandbox
    r = C.save({"jira": {"username": "", "password": "",
                         "session_cookie": "JSESSIONID=NEW"}})
    after = json.load(io.open(p, encoding="utf-8"))
    assert after["jira"]["password"] == "SECRET-PW"
    assert after["jira"]["username"] == "me"
    assert after["jira"]["session_cookie"] == "JSESSIONID=NEW"
    assert r["changed"] == ["jira.session_cookie"]


def test_全空時不寫檔也不更新時間(sandbox):
    C, p = sandbox
    before = io.open(p, encoding="utf-8").read()
    r = C.save({"jira": {"username": "", "password": "", "session_cookie": ""}})
    assert r["changed"] == []
    assert io.open(p, encoding="utf-8").read() == before


def test_要清空得用clear(sandbox):
    C, p = sandbox
    C.clear("jira", "session_cookie")
    after = json.load(io.open(p, encoding="utf-8"))
    assert "session_cookie" not in after["jira"]
    assert after["jira"]["password"] == "SECRET-PW", "只清指定的那一個"


def test_會記錄最後更新時間(sandbox):
    C, _ = sandbox
    assert C.status()["groups"]["jira"]["_updated"] is None
    C.save({"jira": {"username": "u2"}})
    assert C.status()["groups"]["jira"]["_updated"]


# ─────────────────────────────── 降級

def test_沒有cookie時附件測試給得出處置(tmp_path, monkeypatch):
    C = _c()
    p = str(tmp_path / "c.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps({"jira": {}}))
    monkeypatch.setattr(C, "LOCAL_PATH", p)
    r = C.test_jira_attachment("X-1")
    assert r["ok"] is False and "留空" in r["detail"]


def test_連線測試失敗時回原因而不是拋例外(sandbox, monkeypatch):
    """同事沒有 JIRA 或設錯時，UI 要看得到原因，不是白畫面。"""
    C, _ = sandbox
    monkeypatch.setitem(sys.modules, "tools.jira_qa.jira_api", None)
    r = C.test_jira()
    assert r["ok"] is False and r["detail"]


# ─────────────────────────────── 範本化

def test_憑證檔不會被匯出():
    """⛔ `config.local.json` 是個人憑證 —— 白名單必須把它列為 NEVER。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import export_template as E
    assert E.classify("config/config.local.json", E.product_paths(E.ROOT)) == "never"


def test_設定頁本身要匯出():
    """頁面是通用的（每個同事都要設自己的 JIRA），只有憑證值是個人的。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import export_template as E
    p = E.product_paths(E.ROOT)
    for f in ("tools/test_platform/core/credentials.py",
              "tools/test_platform/web_ui/static/js/views/credentials.js"):
        assert E.classify(f, p) == "export", f
