"""uptrend_pullback — A 股上升趋势回调做多策略。

分层架构：
  universe → data → signals → portfolio（多头组合模拟）→ backtest（指标）

与 short_reversal 的区别：
  - 方向为多（买入持有后卖出），无融券费，卖出侧扣印花税
  - 组合式持仓（最多 N 只并行），而非全局单只锁
  - 使用前复权价 v_daily_qfq，避免除权日制造假跌幅
"""
from __future__ import annotations

__all__ = ["UptrendPullbackError"]


class UptrendPullbackError(Exception):
    """uptrend_pullback 包级异常基类。"""
