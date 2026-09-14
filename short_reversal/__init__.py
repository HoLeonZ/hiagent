"""short_reversal — A 股下降趋势反弹做空策略（v3 事件驱动无 look-ahead 版）。

架构：
  presets    ─┐
  universe   ─┼→ engine.run_backtest_v3 → metrics
  indicators_bt ─┤  (bt.indicators.* + 自定义 bt.Indicator 子类)
  strategy   ─┘  (Phase3V3Strategy: next() bar-by-bar 评估 5 条件)

backtrader 源码（pip 装的 1.9.78.123）保持原封不动，只走子类化扩展。
"""
from __future__ import annotations

__all__ = ["ShortReversalError"]


class ShortReversalError(Exception):
    """short_reversal 包级异常基类。"""
