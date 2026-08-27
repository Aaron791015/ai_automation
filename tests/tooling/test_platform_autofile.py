# -*- coding: utf-8 -*-
"""「AI 做完 → 平台落檔 → 人在既有畫面看結果」的三條紀律。

## 為什麼有這一支

2026-08-23 使用者裁示：

> 「在平台上不就是檢視 session 執行任務產出的結果…
>   **使用 AI 輔助工作，不是增加自己的工作量，來審核確認未完成任務。**」

先前平台把**所有**寫入型產出都擋在「待人確認」清單裡 ——
那是把 2026-08-21 的裁示（只針對 Bug，理由是 ID 永不回收）過度擴大。

現在的分界，判準是「**錯了要付什麼代價**」與「**這個判定是誰做的**」：

| 產出 | 處置 |
| --- | --- |
| session 判定的缺陷（走過開單前三問） | ✅ 自動開單 |
| **run 失敗**的 Bug 草稿 | ⛔ 留草稿 —— 「測試失敗 ≠ 缺陷」，同樣那幾條會反覆失敗 |
| 交接檔附加列／機制文件附加節／驗證報告 | ✅ 自動 |
| 機制文件**整檔覆寫** | ⛔ 要人按 —— 會蓋掉別人寫的內容 |
| 案例 | ✅ 自動產碼寫檔（`--collect-only` 收不到會自動還原） |

使用方式：`pytest tests/tooling/test_platform_autofile.py -q`
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM = os.path.join(ROOT, "tools", "test_platform")


def _bd():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    from core import bug_draft
    return bug_draft


def _chat():
    if PLATFORM not in sys.path:
        sys.path.insert(0, PLATFORM)
    import web_ui.api.chat as C
    return C


# ── 誰可以自動開單 ────────────────────────────────────
def test_session判定且三問已答的可以自動開單():
    ok, why = _bd().is_auto_fileable({
        "source": {"kind": "session", "id": "s1"},
        "prechecks": {"is_spec": "不是規格，無變更聲明",
                      "already_known": "非重複",
                      "sample_power": "有鑑別力"},
    })
    assert ok, why


def test_run失敗的一律留草稿():
    """★ 2026-08-21 裁示的原意就是這個：**測試失敗 ≠ 缺陷**，
    同樣那 14 條會反覆失敗，自動開單會洗出一堆假單。"""
    ok, why = _bd().is_auto_fileable({
        "source": {"kind": "run", "id": "20260823_x"},
        "prechecks": {"is_spec": "a", "already_known": "b", "sample_power": "c"},
    })
    assert not ok and "測試失敗" in why


def test_三問沒答完的留給人看():
    """三問是「為什麼判定該開」的唯一佐證 —— 沒答就沒有判斷可言。"""
    ok, why = _bd().is_auto_fileable({
        "source": {"kind": "session", "id": "s1"},
        "prechecks": {"is_spec": "不是規格"},
    })
    assert not ok and "三問" in why


def test_三問是清單形狀也認得():
    """`/api/bug-drafts` 回的是 `[{key,label,answer}]`。"""
    ok, _ = _bd().is_auto_fileable({
        "source": {"kind": "session", "id": "s1"},
        "prechecks": [{"key": "is_spec", "answer": "不是規格"},
                      {"key": "already_known", "answer": "非重複"},
                      {"key": "sample_power", "answer": ""}],
    })
    assert ok, u"答了兩題就夠 —— 第三題常是「不適用」"


# ── 落檔之後要讓人知道「有東西可看」────────────────────
# 📝 2026-08-24 移除三支「播報」測試：使用者裁示「請移除播報，用途不大」，
#    `chat._narrate()` 與 `/api/narration` 整條鏈已拆掉。
#    這件事的需求（**人得先知道有東西可看**）沒有消失 —— 它現在由對話串流的
#    `drafts` 事件回答（`streamReply` 的 `ev.type === 'drafts'` 分支），
#    那裡列的就是同樣幾行「已開單 CRUX-xxx → 到產品頁的 Bug 分頁看」。
