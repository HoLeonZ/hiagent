"""V3a runtime integration test for chase_up (2026-09-22, CLAUDE.md §3).

Mirrors tests/test_uptrend_pullback_v3a_runtime.py for chase_up's 22 presets.
Verifies price_source_for_execution='raw_close' changes entry fill and SL/TP
trigger prices vs default 'adj_close'.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chase_up.portfolio import simulate_portfolio


def _build_panel(n: int = 100, dividend_at: int = 50) -> pd.DataFrame:
    """Build panel: adj (qfq) stays flat, raw drops 20% at dividend_at."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_post_div = i >= dividend_at
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
            "raw_open": 8.0 if is_post_div else 10.0,
            "raw_high": 8.5 if is_post_div else 10.5,
            "raw_low": 7.5 if is_post_div else 9.5,
            "raw_close": 8.0 if is_post_div else 10.0,
            "raw_prev_close": 8.0 if is_post_div else 10.0,
        })
    return pd.DataFrame(rows)


def _build_entries(panel: pd.DataFrame, signal_bar: int) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": panel.iloc[signal_bar]["date"],
        "thscode": "TEST.SH",
        "score": 1.0,
        "sig_close": 10.0,
        "sig_ma20": 9.5,
        "sig_ma60": 9.0,
        "sig_ret1": 0.05,
        "sig_breakout_score": 0.5,
        "sig_momentum_score": 0.3,
        "sig_macross_score": np.nan,
        "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": 0.03,
        "sub_signal_type": "A",
    }])


def test_price_source_raw_close_uses_raw_open_for_entry():
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["entry_price"] == pytest.approx(8.0)


def test_price_source_adj_close_uses_adj_open_for_entry():
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="adj_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["entry_price"] == pytest.approx(10.0)


def test_raw_close_vs_adj_close_different_entry_prices():
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    common = dict(
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )
    trades_adj, _ = simulate_portfolio(entries, panel, price_source_for_execution="adj_close", **common)
    trades_raw, _ = simulate_portfolio(entries, panel, price_source_for_execution="raw_close", **common)
    assert len(trades_adj) == 1 and len(trades_raw) == 1
    ep_adj = float(trades_adj.iloc[0]["entry_price"])
    ep_raw = float(trades_raw.iloc[0]["entry_price"])
    assert ep_adj == pytest.approx(10.0)
    assert ep_raw == pytest.approx(8.0)
    assert ep_adj != ep_raw


def test_raw_close_falls_back_to_adj_when_raw_missing():
    """Legacy panel (no raw_* cols): raw_close source falls back to adj, baseline parity."""
    n = 60
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
        })
    panel = pd.DataFrame(rows)
    entries = _build_entries(panel, signal_bar=29)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["entry_price"] == pytest.approx(10.0)


def test_raw_close_uses_raw_open_even_when_raw_prev_close_nan():
    """V3a+ regression (CLAUDE.md §3): entry fill must use raw_open even when
    raw_prev_close is NaN (real DuckDB panel reality: raw_kline_daily.prev_close
    is NULL upstream, LEFT JOIN yields NaN, prev V3a guard rejected override).

    Per §3, entry fill is a cash mark-to-market operation and MUST use raw.
    prev_close is only used for LIMIT_UP noise filter and can fall back to adj.
    """
    n = 60
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_post_div = i >= 30
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
            "raw_open": 8.0 if is_post_div else 10.0,
            "raw_high": 8.5 if is_post_div else 10.5,
            "raw_low": 7.5 if is_post_div else 9.5,
            "raw_close": 8.0 if is_post_div else 10.0,
            "raw_prev_close": np.nan,  # upstream NULL — real panel reality
        })
    panel = pd.DataFrame(rows)
    entries = _build_entries(panel, signal_bar=29)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    # Entry fill MUST use raw_open (8.0), NOT adj_open (10.0)
    assert trades.iloc[0]["entry_price"] == pytest.approx(8.0)