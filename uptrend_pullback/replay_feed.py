"""Phase 2: 单笔交易 backtrader feed。

每笔入场信号对应一个 backtrader 独立运行，feed 从 panel 中截取该股
[signal_date, signal_date + max_hold + buffer] 区间的真实 OHLCV。

时序约定（与 portfolio.py 一致）：
  T 日（bar 0）= signal_date，无动作（信号日当日不能成交）
  T+1 日（bar 1）= entry_date，策略在开盘买入
  T+2..T+1+max_hold（bar 2..）= 持仓期，每日判 TP/SL/time
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def build_feed_for_trade(
    panel_df: pd.DataFrame,
    thscode: str,
    signal_date: pd.Timestamp,
    max_hold: int,
) -> pd.DataFrame:
    """为单笔交易构造 backtrader 用的 K 线 feed。

    Args:
      panel_df: load_panel() 返回的全市场面板
      thscode:  标的 thscode
      signal_date: T 日信号日期（pd.Timestamp 或可解析字符串）
      max_hold:   最大持仓天数

    Returns:
      DataFrame，index=DatetimeIndex(name='date')，
      列 [open, high, low, close, volume]
      至少包含 max_hold + 2 根 bar（含 signal_date + entry_date + 持仓期）。
    """
    sig = pd.Timestamp(signal_date)
    code_data = panel_df[panel_df["thscode"] == thscode].sort_values("date")
    if code_data.empty:
        raise ValueError(f"build_feed_for_trade: thscode={thscode} 在 panel 中无数据")

    # 从 signal_date 起（含）取 max_hold+5 根作为 buffer（停牌/节假日容错）
    window = code_data[code_data["date"] >= sig].head(max_hold + 5)
    if window.empty:
        raise ValueError(
            f"build_feed_for_trade: thscode={thscode} signal_date={sig.date()} "
            f"无后续 K 线"
        )

    out = window[["date", "open", "high", "low", "close", "volume"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date").sort_index()
    out = out.astype(float)
    return out


def code_bar_count(panel_df: pd.DataFrame, thscode: str) -> int:
    """返回该 thscode 在 panel 中的 bar 数（用于快速判断可用数据长度）。"""
    return int((panel_df["thscode"] == thscode).sum())
