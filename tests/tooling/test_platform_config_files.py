# -*- coding: utf-8 -*-
"""設定檔的「開檔 → 編輯 → 存回」（2026-08-24 使用者要求）。

> 「關於環境設定，也需要可以在介面上進行（可以直接開檔，編輯 json 後再存回）」

## 為什麼要釘這幾條

這是平台**第二次拿到寫檔權限**（第一次是憑證）。這幾份檔案又剛好是
`config/products.json`（產品定義的單一來源）、`config/environments.json`（站台設定）——
寫壞了不只平台自己不能用，`lint_docs`／`bug_paths`／`export_template` 會一起
**靜默**失效（多數呼叫端只 try/except）。

所以下面四條全部是「錯了會很貴」的：

| 釘什麼 | 錯了會怎樣 |
| --- | --- |
| 白名單以外開不到 | `config.local.json` 的帳密被讀回瀏覽器 |
| 壞 JSON 寫不進去 | 整個工作區的腳本一起壞，而且沒有紅燈 |
| **存回不重排版** | 改一個字元，git diff 卻是整份檔（共用檔沒人審得動） |
| 寫入前先備份 | 貼錯一次就要回 git 撈（`config.local.json` 根本撈不回來） |

使用方式：`pytest tests/tooling/test_platform_config_files.py -q`
"""
import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


@pytest.fixture(autouse=True)
def _隔離備份目錄(tmp_path, monkeypatch):
    """⛔ **每一條都要隔離**，不能靠各自記得 monkeypatch。

    `config_files._backup()` 寫的是 `logs/config_backups/<key>/`，
    而那個路徑是由 `core.paths` 從 `__file__` 推得的 —— **等於當下這個工作區的正式目錄**。
    2026-08-24 匯出全新範本時，驗收在匯出的資料夾裡跑 pytest，
    於是這兩條測試把 `_t`／`_t2` 的備份**寫進了交付物**，被殘留檢查抓到。

    ⚠️ 這與同一天修掉的「測試在 logs/sessions/ 留幽靈 session」是**同一類**缺陷：
       測試碰到真實路徑。差別只在那次是漏了一個 monkeypatch，這次是漏了兩條 ——
       所以改成 autouse，讓它不可能被漏掉。
    """
    monkeypatch.setattr(_F(), "BACKUP_DIR", str(tmp_path / "_backups"))


def _F():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import config_files
    return config_files


# ── 白名單 ────────────────────────────────────────────
def test_只開放程式讀的那幾份():
    """📝 2026-08-24 從四份改成三份：使用者裁示「人讀的可以不顯示，
    會要調整或增加的只有程式讀的才對」—— `config/environments.md` 移出白名單。
    """
    keys = set(_F().FILES)
    assert keys == {"environments", "products", "platform"}, keys


def test_全部都是程式讀的結構化檔():
    """⛔ 迴歸：不要再把敘述型的 markdown 放進來。
    這一頁的用途是「改程式讀的設定」，不是當編輯器用。"""
    for k, spec in _F().FILES.items():
        assert spec["kind"] == "json", "%s 的 kind 是 %s" % (k, spec["kind"])


def test_敏感檔不在白名單裡():
    """⛔ `config/config.local.json` 有帳密與 token —— 它走憑證頁（只寫不讀）。"""
    for spec in _F().FILES.values():
        assert "config.local" not in spec["path"].replace("\\", "/"), spec["path"]


def test_key不是路徑參數():
    """路徑逃逸的唯一防線就是「key 是固定字串」。"""
    F = _F()
    for bad in ("../config/config.local.json", "..\\..\\etc\\passwd", "environments/../platform"):
        with pytest.raises(KeyError):
            F.read(bad)


# ── 寫入前的驗證 ──────────────────────────────────────
def test_壞掉的json擋在寫入之前():
    F = _F()
    okay, why = F.validate("environments", "{ 這不是 json")
    assert not okay and "JSON" in why


def test_最外層不是物件也不給過():
    okay, why = _F().validate("products", '"只是一個字串"')
    assert not okay and "物件或陣列" in why


def test_環境設定要附範例格式():
    """★ 2026-08-24 使用者：「必須提供範例格式讓接產品的人知道該如何設定」。

    ⛔ 範例裡**不可以有任何真的帳密** —— 這份檔案是可版控的，
       而範例會被複製貼上，貼到哪裡去無從追蹤。
    """
    spec = _F().FILES["environments"]
    ex = spec.get("example") or ""
    assert ex.strip().startswith("{") and "qat" in ex, "範例要是可貼上的 JSON 片段"
    assert "<" in ex, "範例要用 <佔位符> 而不是看起來像真值的東西"
    import json as _json
    _json.loads(ex.replace("<產品 slug>", "x"))          # 範例本身要是合法 JSON
    low = ex.lower()
    for bad in ("123fff", "aa123456", "password123"):
        assert bad not in low, "範例裡混進了真的密碼：%s" % bad


# ── ⭐ 存回不可以重排版 ───────────────────────────────
def test_存回不重排版(tmp_path, monkeypatch):
    """★ 這一條是 2026-08-24 實測抓到的：原本存回會 `json.dumps(indent=2)`，
    而 `config/environments.json` 刻意把小物件寫成一行 ——
    改一個字元，diff 卻是整份檔（實測 5,610 → 6,150 字元）。
    """
    F = _F()
    p = tmp_path / "x.json"
    original = '{\n  "a": [\n    { "n": 1, "m": 2 }\n  ]\n}\n'
    io.open(str(p), "w", encoding="utf-8", newline="\n").write(original)
    monkeypatch.setitem(F.FILES, "_t", {"path": str(p), "label": "t", "kind": "json",
                                        "desc": "", "warn": ""})
    F.write("_t", original)
    assert io.open(str(p), encoding="utf-8").read() == original, "存回之後排版被改了"


def test_結尾補一個換行(tmp_path, monkeypatch):
    F = _F()
    p = tmp_path / "y.json"
    io.open(str(p), "w", encoding="utf-8", newline="\n").write("{}\n")
    monkeypatch.setitem(F.FILES, "_t2", {"path": str(p), "label": "t", "kind": "json",
                                         "desc": "", "warn": ""})
    F.write("_t2", '{"a": 1}')                     # 沒有結尾換行
    assert io.open(str(p), encoding="utf-8").read() == '{"a": 1}\n'


# ── 備份與還原 ────────────────────────────────────────
def test_寫入前先備份而且還原得回來(tmp_path, monkeypatch):
    F = _F()
    p = tmp_path / "z.json"
    monkeypatch.setattr(F, "BACKUP_DIR", str(tmp_path / "bk"))   # autouse 已隔離，這裡另指一份好斷言
    monkeypatch.setitem(F.FILES, "_t3", {"path": str(p), "label": "t", "kind": "json",
                                         "desc": "", "warn": ""})
    io.open(str(p), "w", encoding="utf-8", newline="\n").write('{"v": 1}\n')
    r = F.write("_t3", '{"v": 2}\n')
    assert r["backup"], "沒有留備份"
    assert json.loads(io.open(str(p), encoding="utf-8").read())["v"] == 2
    name = F.backups("_t3")["backups"][0]["name"]
    F.restore("_t3", name)
    assert json.loads(io.open(str(p), encoding="utf-8").read())["v"] == 1, "還原沒生效"
    # 還原本身也要留備份 —— 不然按錯就回不去了
    assert len(F.backups("_t3")["backups"]) == 2


def test_備份時間看得懂(tmp_path, monkeypatch):
    F = _F()
    monkeypatch.setattr(F, "BACKUP_DIR", str(tmp_path / "bk2"))
    d = tmp_path / "bk2" / "_t4"
    os.makedirs(str(d))
    io.open(str(d / "20260824_014356.bak"), "w", encoding="utf-8").write("{}")
    monkeypatch.setitem(F.FILES, "_t4", {"path": str(tmp_path / "a.json"), "label": "t",
                                         "kind": "json", "desc": "", "warn": ""})
    assert F.backups("_t4")["backups"][0]["at"] == "2026-08-24 01:43:56"


# ── 端點確實掛上去了 ──────────────────────────────────
def test_四個端點都掛在app上():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.app as A
    rules = {str(r) for r in A.app.url_map.iter_rules()}
    for want in ("/api/settings/files", "/api/settings/files/<key>",
                 "/api/settings/files/<key>/backups"):
        assert want in rules, "少了端點 %s（有的是 %s）" % (want, sorted(rules)[:5])


def test_真實的三份設定檔現在都讀得到而且是有效的():
    """⛔ 這一條同時是**現況體檢** —— 白名單指到不存在或壞掉的檔案時當場紅燈。"""
    F = _F()
    for key, spec in F.FILES.items():
        d = F.read(key)
        assert d["exists"], "%s 指到不存在的檔案：%s" % (key, d["path"])
        assert F.validate(key, d["text"])[0], "%s 目前的內容驗不過" % key
