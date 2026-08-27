# -*- coding: utf-8 -*-
"""設定檔的「開檔 → 編輯 → 存回」（2026-08-24 使用者要求）。

> 「關於環境設定，也需要可以在介面上進行（可以直接開檔，編輯 json 後再存回）」

用途：讓 `config/environments.json`、`config/products.json`、平台設定這幾份
      **非敏感、可版控**的設定檔在介面上直接編輯，不必開編輯器。
使用方式：`web_ui/api/settings.py` 的 `/api/settings/files*` 三個端點。
前置條件：無。

## ⛔ 四條紀律

1. **白名單，不接受任意路徑** —— `key` 是固定字串，不是路徑參數。
   傳路徑進來就會有 `../` 逃逸，而這個服務跑在使用者自己的 OS 身分下。
2. **敏感檔不在白名單** —— `config/config.local.json`（帳密／token）**不開放**。
   它有專屬的憑證頁（`core/credentials.py`）：只寫不讀、永不回傳瀏覽器。
3. **寫入前先驗證** —— JSON 檔一律 `json.loads` 過才寫；壞掉的 JSON 會讓
   `lint_docs`／`bug_paths`／平台自己一起失效，而且**是靜默的**（多數呼叫端只 try/except）。
4. **寫入前先備份** —— 存到 `logs/config_backups/<key>/<時間戳>.bak`，保留最近 20 份。
   這幾份檔案裡有些是**產品定義的單一來源**，手滑貼錯一次就要從 git 撈回來
   （而 `config/config.local.json` 根本不版控，撈不回來）。
"""
from __future__ import annotations

import io
import json
import os
import time

from core.paths import LOGS_DIR, REPO_ROOT, rel_to_repo, repo_path

BACKUP_DIR = os.path.join(LOGS_DIR, "config_backups")
KEEP_BACKUPS = 20

# key → 這份檔案是什麼。⛔ 只有列在這裡的才編輯得到。
FILES = {
    "environments": {
        "path": repo_path("config", "environments.json"),
        "label": "測試環境（程式讀）",
        "kind": "json",
        "desc": "各產品的站台 URL、環境代號、非敏感的測試帳號。程式讀的就是這一份。",
        "warn": "⛔ 帳密／token 不要寫在這裡 —— 那些放 config.local.json，走「憑證」分頁。",
        # ⭐ 接產品的人打開這一份時，最需要的是「**我該寫成什麼樣子**」。
        #    2026-08-24 使用者：「必須提供範例格式讓接產品的人知道該如何設定」。
        #    ⚠️ 範例要**貼近真的長相**（產品 → 環境 → 站台 URL ＋ 帳號物件），
        #       但一個帳密都不能有 —— 這份檔案是可版控的。
        "example_title": "一個產品最少要有的樣子",
        "example": """{
  "<產品 slug>": {
    "_comment": "slug 要與 config/products.json 的 aliases[0] 一致 —— 平台用它當網址與 tool.json 的鍵",
    "qat": {
      "backend_url":  "http://<後台網址>/",
      "frontend_url": "http://<前台網址>/",
      "mobile_url":   "http://<手機版網址>/",
      "admin": { "username": "<測試帳號>", "password": "<測試密碼>" }
    },
    "stg": {
      "_comment": "⛔ STG 已交客戶試用，需逐次授權才可使用；沒有 STG 就整段不要寫",
      "backend_url": "https://<STG 後台>/"
    }
  }
}""",
        # ⚠️ 這一段是**用 `raw()` 直接塞進 DOM 的 HTML**，不是 markdown ——
        #    寫 `**粗體**` 會原樣印出星號（2026-08-24 走查看到）。要粗體就用 <b>。
        "example_note": "· 巢狀層次自己決定 —— 一個產品有多個彩種／多個總監站台時再往下分一層即可"
                        "（<code>crux</code> 分 director1/2/3、<code>qixing</code> 分 lucky5/sevenstar，"
                        "都在這份檔案裡看得到）。<br>"
                        "· <b>QAT 測試帳密可以寫在這裡</b>（政策見 <code>config/environments.md</code>）；"
                        "正式環境與 token 一律不行 —— 那些走「JIRA 憑證」分頁，"
                        "寫進不版控的 <code>config.local.json</code>。",
    },
    # 📝 2026-08-24 移除 `environments_md`（`config/environments.md`）——
    #    使用者：「人讀的可以不顯示，會要調整或增加的只有程式讀的才對」。
    #    那一份是給人看的敘述（子帳號分配慣例、各站台注意事項），用編輯器逐字改
    #    既不好用也不是這一頁的目的；它跟著 repo 走，要改就在編輯器裡改。
    "products": {
        "path": repo_path("config", "products.json"),
        "label": "產品定義（單一來源）",
        "kind": "json",
        "desc": "產品 id、文件目錄、Bug 前綴、skill、交接檔。lint_docs 與平台都讀這一份。",
        "warn": "⭐ 要**新增**產品請用「工作區」分頁的「接一個產品」—— 手動加會漏掉目錄與交接檔，"
                "而漏掉的部分不會被 lint 檢查到。這裡適合改既有產品的欄位。",
    },
    "platform": {
        "path": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "config", "platform_config.json"),
        "label": "平台設定（版控）",
        "kind": "json",
        "desc": "host／port、JIRA 快取分鐘數、預設模型。個人覆寫請放 platform_config.local.json。",
        "warn": "改 host／port 要重開平台才生效。",
    },
}


def _meta(key: str, spec: dict) -> dict:
    p = spec["path"]
    ex = os.path.isfile(p)
    return {
        "key": key, "label": spec["label"], "kind": spec["kind"],
        "example_title": spec.get("example_title"), "example": spec.get("example"),
        "example_note": spec.get("example_note"),
        "desc": spec["desc"], "warn": spec.get("warn", ""),
        "path": rel_to_repo(p), "exists": ex,
        "size": os.path.getsize(p) if ex else 0,
        "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))) if ex else "",
        "backups": len(_backups(key)),
    }


def listing() -> dict:
    return {"files": [_meta(k, v) for k, v in FILES.items()]}


def read(key: str) -> dict:
    spec = FILES.get(key)
    if not spec:
        raise KeyError(key)
    p = spec["path"]
    text = io.open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
    return dict(_meta(key, spec), text=text)


def validate(key: str, text: str) -> tuple[bool, str]:
    """寫入前的檢查。⛔ 壞掉的 JSON 會讓好幾支腳本**靜默**失效，所以擋在寫入之前。"""
    spec = FILES.get(key)
    if not spec:
        return False, "不是平台管理的設定檔：%s" % key
    if spec["kind"] != "json":
        return (True, "") if text.strip() else (False, "內容是空的")
    try:
        data = json.loads(text)
    except ValueError as e:                      # noqa: PERF203
        return False, "JSON 格式錯誤：%s" % e
    if not isinstance(data, (dict, list)):
        return False, "最外層要是物件或陣列"
    return True, ""


def _backups(key: str) -> list:
    d = os.path.join(BACKUP_DIR, key)
    if not os.path.isdir(d):
        return []
    return sorted((f for f in os.listdir(d) if f.endswith(".bak")), reverse=True)


def _backup(key: str, path: str) -> str:
    """存一份舊的。⛔ 失敗不擋寫入 —— 備份是加值，不是前提。"""
    if not os.path.isfile(path):
        return ""
    d = os.path.join(BACKUP_DIR, key)
    try:
        os.makedirs(d, exist_ok=True)
        # ⚠️ 檔名只到「秒」—— 同一秒存兩次會**蓋掉前一份**（實測：還原時緊接著再寫一次，
        #    兩份撞在同一秒，於是「還原前的樣子」直接消失，等於還原不可逆）。
        #    撞名就往後加序號。
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = stamp + ".bak"
        n = 1
        while os.path.exists(os.path.join(d, name)):
            n += 1
            name = "%s-%d.bak" % (stamp, n)
        dst = os.path.join(d, name)
        io.open(dst, "w", encoding="utf-8", newline="").write(
            io.open(path, encoding="utf-8", newline="").read())
        for old in _backups(key)[KEEP_BACKUPS:]:
            try:
                os.remove(os.path.join(d, old))
            except OSError:
                pass
        return rel_to_repo(dst)
    except OSError:
        return ""


def write(key: str, text: str) -> dict:
    spec = FILES.get(key)
    if not spec:
        raise KeyError(key)
    okay, why = validate(key, text)
    if not okay:
        raise ValueError(why)
    p = spec["path"]
    backup = _backup(key, p)
    # ⛔ **不要重新序列化 JSON**（原本這麼做，2026-08-24 實測後改掉）——
    #    `config/environments.json` 刻意把小物件寫成一行（`{ "name": "…" }`），
    #    `json.dumps(indent=2)` 會全部攤開：改一個字元，git diff 卻是整份檔
    #    （實測 5,610 → 6,150 字元）。這幾份都是**共用檔**，那種 diff 沒人審得動，
    #    也把別人刻意排的版蓋掉。只做兩件無爭議的事：換行統一成 LF、結尾一個換行。
    out = text.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
    if out and not out.endswith(chr(10)):
        out += chr(10)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(out)
    return dict(_meta(key, spec), backup=backup, normalized=(out != text))


def restore(key: str, name: str) -> dict:
    """把某一份備份還原回去（還原前一樣先備份現況，才不會單向）。"""
    spec = FILES.get(key)
    if not spec:
        raise KeyError(key)
    if name not in _backups(key):
        raise ValueError("找不到這份備份：%s" % name)
    src = os.path.join(BACKUP_DIR, key, name)
    return write(key, io.open(src, encoding="utf-8").read())


def backups(key: str) -> dict:
    if key not in FILES:
        raise KeyError(key)
    def _pretty(n: str) -> str:
        # 20260824_014356.bak → 2026-08-24 01:43:56（給人看的，不是給程式解析的）
        d, t = n[:8], n[9:15]
        seq = n[15:-4]                       # 同一秒的第 2 份起會有 `-2`
        return "%s-%s-%s %s:%s:%s%s" % (d[:4], d[4:6], d[6:8], t[:2], t[2:4], t[4:6],
                                        ("（%s）" % seq.lstrip("-")) if seq else "")

    return {"backups": [{"name": n, "at": _pretty(n)} for n in _backups(key)]}


assert REPO_ROOT                                  # 只是釘住 import（路徑常數的唯一來源）
