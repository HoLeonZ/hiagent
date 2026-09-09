"""feed.build_synthetic_feed 持仓日真实 OHLC + 未持仓日 prev_close 占位。"""
from __future__ import annotations

import pandas as pd

from short_reversal.replay_feed import build_synthetic_feed


def test_held_day_uses_real_ohlcv():
    trades = pd.DataFrame([{
        "entry_date": pd.Timestamp("2025-01-01"),
        "thscode": "X.SH",
        "exit_date": pd.Timestamp("2025-01-03"),
        "exit_reason": "TP",
        "entry_price": 10.0, "exit_price": 9.4, "hold_days": 3,
    }])
    panel = pd.DataFrame([
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-01"),
         "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000.0},
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-02"),
         "open": 10.1, "high": 10.3, "low": 9.5, "close": 9.6, "volume": 1500.0},
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-03"),
         "open": 9.6, "high": 9.7, "low": 9.4, "close": 9.5, "volume": 2000.0},
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-06"),
         "open": 9.5, "high": 9.8, "low": 9.4, "close": 9.7, "volume": 1800.0},
    ])
    feed = build_synthetic_feed(trades, panel)
    # 持仓日 01-02 的 close = 9.6
    assert abs(feed.loc[pd.Timestamp("2025-01-02"), "close"] - 9.6) < 1e-9


def test_unheld_day_uses_prev_close():
    trades = pd.DataFrame([{
        "entry_date": pd.Timestamp("2025-01-01"),
        "thscode": "X.SH",
        "exit_date": pd.Timestamp("2025-01-02"),
        "exit_reason": "TP",
        "entry_price": 10.0, "exit_price": 9.4, "hold_days": 2,
    }])
    panel = pd.DataFrame([
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-01"),
         "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000.0},
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-02"),
         "open": 10.1, "high": 10.3, "low": 9.5, "close": 9.6, "volume": 1500.0},
        {"thscode": "X.SH", "date": pd.Timestamp("2025-01-06"),
         "open": 9.5, "high": 9.8, "low": 9.4, "close": 9.7, "volume": 1800.0},
    ])
    feed = build_synthetic_feed(trades, panel)
    # 01-06 未持仓 → close = prev_close = 9.6
    assert abs(feed.loc[pd.Timestamp("2025-01-06"), "close"] - 9.6) < 1e-9
    assert feed.loc[pd.Timestamp("2025-01-06"), "volume"] == 0.0
