"""adapter 工廠：依 `spec.kind` 挑實作。

    cli    → CliAdapter      跑一支命令列程式（同步命令與長時 run 都支援）
    pytest → PytestAdapter   跑測試案例
    http   → HttpAdapter     代理既有的 HTTP 服務

📝 2026-08-23 移除 FakeAdapter 與 demo 分支。
   先前這裡是「唯一的真假切換點」：`spec.live` 覆蓋全域 demo、`spec.demo` 讓個別工具
   先假後真，那是 M1～M4 逐工具遷移期間的過渡設計。遷移完成後它只剩下一個作用 ——
   **讓每個落點都要記得「這裡有兩條路」**，而這一輪已經因此踩到兩個缺陷。
"""
from __future__ import annotations


def get_adapter(spec, ctx: dict | None = None):
    kind = spec.kind
    if kind == "cli":
        from adapters.cli import CliAdapter
        return CliAdapter(spec, ctx)
    if kind == "pytest":
        from adapters.pytest_ import PytestAdapter
        return PytestAdapter(spec, ctx)
    if kind == "http":
        from adapters.http import HttpAdapter
        return HttpAdapter(spec, ctx)
    raise ValueError(f"未知的 adapter kind：{kind}")
