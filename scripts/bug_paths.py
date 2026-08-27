# -*- coding: utf-8 -*-
"""Bug 檔案結構的共用常數與工具函式（`scripts/` 內部用，非獨立執行）。

用途：`gen_bug_index` / `lint_bug_assets` / `archive_bugs` / `pack_bug_report`
      四支腳本都要知道「歸檔層叫什麼、frontmatter 怎麼讀」。
      2026-08-11 導入 `old/` 時這些常數各自複製了一份 —— 將來改目錄名時
      漏改任何一支，都會出現「某支找得到、某支找不到」的**靜默分裂**（不報錯，只漏資料）。
      故收斂到本檔，各腳本一律 import，不再自行定義。

前置條件：無。本檔不可執行，只供 import。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 目錄結構 ────────────────────────────────────────────────────
# Bug 單只會存在於**主目錄**或 **ARCHIVE_DIR**（見 CLAUDE.md §6）
ARCHIVE_DIR = "old"          # 歸檔層（已結案單）
VIEW_DIR = "_view"           # 分組檢視（自動生成）
SHOTS_DIR = "shots"          # 截圖

# ── 產品 ────────────────────────────────────────────────────────
# ── 產品定義：以 config/products.json 為單一來源 ─────────────
# ★ 2026-08-22：這三個常數原本寫死在這裡，而同一份資訊另外還散在 lint_docs.py、CLAUDE.md §1、
#   config/environments.json、test_platform/registry/products.json 共五處 ——
#   新增產品要改五個地方，漏改任何一處就是本檔 docstring 講的那種「靜默分裂」。
#   現改為讀 config/products.json；**讀不到時退回下方硬編碼**，確保設定檔壞掉不會讓所有腳本停擺。
_FALLBACK = {
    "PRODUCT_DIRS": {"CRUX": "CRUX", "投注機器人": "投注機器人", "wbot": "投注機器人", "七星": "七星"},
    "PRODUCTS": ["CRUX", "投注機器人", "七星"],
    "ID_PREFIX": {"CRUX": "CRUX", "投注機器人": "WBOT", "七星": "QX"},
    "JIRA_KEYS": {"CRUX": "CRUX", "投注機器人": "BOT"},   # 七星尚未確認
}


def _load_products():
    """讀 config/products.json，回傳 (PRODUCT_DIRS, PRODUCTS, ID_PREFIX, JIRA_KEYS)。"""
    import json
    path = os.path.join(ROOT, "config", "products.json")
    try:
        data = json.loads(io.open(path, encoding="utf-8").read())
        items = data["products"]
        dirs, names, prefix, jira = {}, [], {}, {}
        for p in items:
            pid = p["id"]
            names.append(pid)
            dirs[pid] = p["docs_dir"]
            prefix[pid] = p["bug_prefix"]
            # ⚠️ `jira_key` 是選填 —— None 代表「這個產品不比對 JIRA」，
            #    不是「還沒填」。七星與剛接的產品都是這個狀態。
            if p.get("jira_key"):
                jira[pid] = p["jira_key"]
            for alias in p.get("aliases") or []:
                dirs[alias] = p["docs_dir"]
        # ⚠️ **空的產品清單是合法狀態，不可以掉進 fallback。**
        #    「一個產品都還沒接」正是全新範本的樣子；退回原型三產品的話，
        #    同事的治理腳本會相信 CRUX／七星／投注機器人 存在，
        #    然後指向根本不存在的 docs/ 目錄（2026-08-23 乾淨重匯時抓到）。
        #    fallback 只保留給**檔案讀不出來**那一種（下面的 except）。
        return dirs, names, prefix, jira
    except Exception:
        f = _FALLBACK
        return (dict(f["PRODUCT_DIRS"]), list(f["PRODUCTS"]),
                dict(f["ID_PREFIX"]), dict(f["JIRA_KEYS"]))


# 別名 → docs/ 下的目錄名 ／ 正式產品名（供 argparse choices）／ 產品 → 本地 Bug ID 前綴
PRODUCT_DIRS, PRODUCTS, ID_PREFIX, JIRA_KEYS = _load_products()


def reload_products():
    """重新讀 `config/products.json` 並更新上面四個模組常數。

    ⭐ 給**長駐程序**用（測試助手是 Flask）—— CLI 腳本每次都是新程序，
      import 當下就是最新的，不需要呼叫這支。

    ⚠️ 不呼叫的話：從介面接一個新產品之後，平台的 Bug 索引**永遠看不到它**，
       產品頁顯示成「未建立 bugs/」，而畫面上看不出這是快取
       —— 人只會以為接產品失敗了（2026-08-24 拍手冊截圖時抓到）。
    """
    global PRODUCT_DIRS, PRODUCTS, ID_PREFIX, JIRA_KEYS
    PRODUCT_DIRS, PRODUCTS, ID_PREFIX, JIRA_KEYS = _load_products()
    return PRODUCTS


def product_base(product):
    """docs/<產品>/"""
    return os.path.join(ROOT, "docs", PRODUCT_DIRS[product])


def bugs_dir(product):
    """docs/<產品>/bugs/"""
    return os.path.join(product_base(product), "bugs")


def bug_layers(bugs_dir_path):
    """Bug 單與截圖所在的兩層（主目錄、歸檔層），依序回傳絕對路徑。"""
    return [bugs_dir_path, os.path.join(bugs_dir_path, ARCHIVE_DIR)]


def parse_frontmatter(path):
    """讀出檔頭 --- 之間的 key: value（本專案只用平坦字串欄位）。

    回傳 (meta 或 None, 全文)。
    """
    text = io.open(path, encoding="utf-8", errors="replace").read()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text
