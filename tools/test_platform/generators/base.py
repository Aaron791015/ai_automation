"""生成器介面：兩格可替換的能力。

    需求 ──①propose_cases──▶ 案例清單 ──②人工檢視/調整──▶ ③write_code ──▶ ④寫檔・驗證
           ★可替換                        純 UI            ★可替換      純程式

②④ 不因供應者而異，所以只有 ①③ 在這個介面上。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class CaseGenerator(ABC):
    name: str = ""
    #: 給 UI 顯示的誠實標示 —— 規則式的產出必須被檢視，不能當成可以直接送出的東西
    disclaimer: str = ""

    @abstractmethod
    def propose_cases(self, requirement: str, context: dict) -> list[dict]:
        """需求文字 → 案例 draft 清單（結構見 core/spec_draft.py）。

        context 至少含：{product, existing_cases（既有案例的 flat 索引）, pom（該產品的方法清單）}
        """

    @abstractmethod
    def write_code(self, case: dict, context: dict) -> str:
        """一條案例 → 一段 Python 測試碼（單一 test function，含中文 docstring 與 marker）。

        ⛔ 只能呼叫 context["pom"] 裡真的存在的方法。
        """

    def module_header(self, draft: dict) -> str:
        """檔頭註解（CLAUDE.md §6：每個測試腳本開頭要說明用途、使用方式、前置條件）。"""
        return ""
