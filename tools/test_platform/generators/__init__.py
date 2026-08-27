"""案例生成器：可替換的供應者。

Demo 掛 `rulebased`（規則式＋範本驅動）；M6 換 `claude`（真的呼叫 Claude）時
**web_ui 與 core/case_writer 一行都不用改** —— 這就是留這層介面的用意。
"""
from __future__ import annotations

from core.config import load_config


def get_generator(name: str | None = None):
    name = name or (load_config().get("generator") or "rulebased")
    if name == "rulebased":
        from generators.rulebased import RuleBasedGenerator
        return RuleBasedGenerator()
    if name == "claude":                       # M6
        from generators.claude import ClaudeGenerator
        return ClaudeGenerator()
    raise ValueError(f"未知的生成器：{name}")
