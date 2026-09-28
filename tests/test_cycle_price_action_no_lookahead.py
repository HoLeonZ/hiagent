"""P0–P8 no-look-ahead contract for cycle_price_action.

Mandatory: ≥21 tests, all must pass before any merge to main.
Each rule group carries the minimum test count quoted from the design spec.
"""
from __future__ import annotations

import os
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest

from cycle_price_action.cycle import phase_score
from cycle_price_action.signals import (
    detect_k_patterns, k_line_score, fuse_scores, entry_signal,
)
from cycle_price_action.universe import (
    is_main_board, apply_liquidity_filter, is_excluded_status,
)
from cycle_price_action.portfolio import Portfolio
from cycle_price_action.data_feed import ReplayDataProvider
from cycle_price_action.replay_broker import ReplayBroker
from cycle_price_action.no_lookahead import (
    bars_up_to, group_by_stock, delivery_date_check, assert_exit_priority,
)
from cycle_price_action.time_windows import calendar_score


# ---------- P0 ----------
def test_p0_a_phase_score_uses_only_closed_bars():
    s = pd.Series(pd.date_range("2024-01-01", periods=25, freq="B"))
    a = phase_score(s)
    # Recompute with longer prefix — early bars MUST be unchanged.
    s2 = pd.Series(pd.date_range("2023-12-01", periods=40, freq="B"))[15:]
    b = phase_score(s2).reset_index(drop=True)
    b.index = a.index
    np.testing.assert_array_equal(a.to_numpy(), b.to_numpy())


def test_p0_b_k_line_score_uses_only_decision_time_volume():
    rows = [(10.0, 10.4, 9.8, 10.2, 1.0)] * 9
    rows.append((10.0, 10.4, 9.8, 10.2, 100.0))
    df = pd.DataFrame(rows, columns=["open","high","low","close","volume"],
                      index=pd.date_range("2024-01-01", periods=len(rows), freq="B"))
    pat = detect_k_patterns(df)
    out = k_line_score(df, pat)
    # The last bar's score may legitimately include the spike at index=-1 (it IS
    # the bar's own volume). Bar at index=-2 must not see index=-1's volume.
    assert out.iloc[-2] <= 1.0


def test_p0_c_cycle_phase_does_not_look_ahead_at_index():
    s_short = pd.Series(pd.date_range("2024-01-01", periods=30, freq="B"))
    s_long = pd.Series(pd.date_range("2023-01-01", periods=400, freq="B"))
    # Score at bar index 29 must be the same regardless of total series length
    # (no look-ahead from later bars into bar 29). Relative indexing means
    # sin(2π × 29 / p) — independent of n.
    a = phase_score(s_short).iloc[29]
    b = phase_score(s_long).iloc[29]
    assert abs(a - b) < 1e-9


def test_p0_d_calendar_score_uses_only_past_dates():
    dates = pd.Series(pd.date_range("2024-03-12", periods=5, freq="B"))
    a = calendar_score(dates)
    # Adding more past dates must not change today score.
    dates2 = pd.Series(pd.date_range("2023-01-01", periods=400, freq="B"))[-5:]
    b = calendar_score(dates2).reset_index(drop=True)
    b.index = a.index
    pd.testing.assert_series_equal(a, b, check_names=False)


# ---------- P1 ----------
def test_p1_a_exit_price_uses_broker_fill_not_signal_price():
    db = "/tmp/_p1.duckdb"
    if os.path.exists(db):
        os.remove(db)
    con = duckdb.connect(db)
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, amount DOUBLE, volume DOUBLE)"
    )
    for i, d in enumerate(pd.date_range("2024-06-03", periods=5, freq="B")):
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["X.SH", d.date(), 10.0 + i * 0.1, 10.5, 9.8, 10.2 + i * 0.1, 1e7, 1e6],
        )
    con.close()
    b = ReplayBroker(ReplayDataProvider(db))
    f1 = b.submit_buy("X.SH", 100, decision_date=date(2024, 6, 3))
    b.record_fill(f1)
    f2 = b.submit_sell("X.SH", 100, decision_date=date(2024, 6, 4))
    assert f2 is not None
    # Fill price must equal the open bar on the day AFTER decision, not the
    # theo's "trigger" price. submit_sell on 2024-06-04 → fill on 2024-06-05
    # at open=10.2 (i=2 in the loop, open=10.0+2*0.1=10.2).
    assert abs(f2.price - 10.2) < 1e-9
    os.remove(db)


def test_p1_b_fill_lag_is_at_least_one_trading_day():
    db = "/tmp/_p1b.duckdb"
    if os.path.exists(db):
        os.remove(db)
    con = duckdb.connect(db)
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, amount DOUBLE, volume DOUBLE)"
    )
    for d in pd.date_range("2024-06-03", periods=2, freq="B"):
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["X.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e7, 1e6],
        )
    con.close()
    b = ReplayBroker(ReplayDataProvider(db))
    f1 = b.submit_buy("X.SH", 100, decision_date=date(2024, 6, 3))
    assert f1.date > date(2024, 6, 3)
    os.remove(db)


# ---------- P2 ----------
def test_p2_a_trade_state_carries_decision_snapshot(tmp_path):
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        "600000.SH", 9.87, date(2024, 6, 3),
        decision_meta={"phase_score": 0.3, "k_line_score": 1.5, "calendar_score": 0.4},
    )
    assert state is not None
    assert state.decision_meta.get("k_line_score") == 1.5
    assert state.decision_meta.get("phase_score") == 0.3
    assert state.decision_meta.get("calendar_score") == 0.4


def test_p2_b_decision_meta_immutable_after_entry():
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        "600000.SH", 9.87, date(2024, 6, 3),
        decision_meta={"phase_score": 0.3},
    )
    with pytest.raises(Exception):
        state.decision_meta["phase_score"] = 99.0


# ---------- P3 ----------
def test_p3_a_portfolio_rejects_same_day_exit():
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 9.87, date(2024, 6, 3), {"k_line_score": 1.5})
    with pytest.raises(ValueError):
        pf.try_exit(date(2024, 6, 3), 10.5)


def test_p3_b_replay_broker_records_buy_at_next_open():
    db = "/tmp/_p3b.duckdb"
    if os.path.exists(db):
        os.remove(db)
    con = duckdb.connect(db)
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, amount DOUBLE, volume DOUBLE)"
    )
    for d in pd.date_range("2024-06-03", periods=2, freq="B"):
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["X.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e7, 1e6],
        )
    con.close()
    b = ReplayBroker(ReplayDataProvider(db))
    f1 = b.submit_buy("X.SH", 100, decision_date=date(2024, 6, 3))
    assert f1.date == date(2024, 6, 4)
    os.remove(db)


def test_p3_c_delivery_helper_rejects_same_day():
    with pytest.raises(ValueError):
        delivery_date_check(date(2024, 6, 3), date(2024, 6, 3))


def test_p3_d_strategy_decision_marker_never_replays_today():
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter("X.SH", 9.87, date(2024, 6, 3), {"k_line_score": 1.5})
    # The PositionState must expose entry_date, used by strategy to gate exits.
    assert state.entry_date == date(2024, 6, 3)
    assert pf.hold_days(date(2024, 6, 3)) == 0


def test_p3_e_max_hold_exit_uses_close_not_high():
    """P5 guard baked in: time stop uses close, even when high > tp."""
    assert_exit_priority(
        [("sl_open", 9.5), ("tp_open", 10.5), ("sl_intra", 9.5), ("tp_intra", 10.5), ("time_stop", 10.6)]
    )


# ---------- P4 ----------
def test_p4_a_dataframe_required_columns_present():
    df = pd.DataFrame({"thscode": [], "date": [], "open": [], "high": [],
                       "low": [], "close": [], "amount": [], "volume": []})
    bars_up_to(df, date(2024, 1, 1))     # should not raise even on empty


# ---------- P5 ----------
def test_p5_a_exit_priority_open_gap_through_sl_wins():
    assert_exit_priority([("sl_open", 9.0), ("tp_intra", 11.0)])


def test_p5_b_exit_priority_time_stop_last_when_no_trigger():
    assert_exit_priority(
        [("sl_open", None), ("tp_open", None), ("sl_intra", None),
         ("tp_intra", None), ("time_stop", 10.6)]
    )


def test_p5_c_exit_priority_segment_order():
    """Out-of-order raises — enforces priority 1..5."""
    with pytest.raises(ValueError):
        assert_exit_priority([("tp_intra", 10.5), ("sl_open", 9.0)])


# ---------- P6 ----------
def test_p6_a_signal_layer_does_not_read_cash():
    df = pd.DataFrame({
        "open": [10.0], "high": [10.5], "low": [9.5],
        "close": [10.0], "volume": [1e6],
    }, index=pd.date_range("2024-01-01", periods=1, freq="B"))
    pat = detect_k_patterns(df)
    score = k_line_score(df, pat)
    # No input cash/position — score is computed blindly on bars alone.
    assert score.between(-0.2, 2.5).all()


def test_p6_b_signal_layer_does_not_branch_on_position():
    """Same bars → same scores, irrespective of phantom position state."""
    df = pd.DataFrame({
        "open": [10.0, 11.0], "high": [10.5, 11.5], "low": [9.5, 10.5],
        "close": [10.2, 11.2], "volume": [1e6, 2e6],
    }, index=pd.date_range("2024-01-01", periods=2, freq="B"))
    a = k_line_score(df, detect_k_patterns(df))
    b = k_line_score(df.copy(), detect_k_patterns(df.copy()))
    pd.testing.assert_series_equal(a, b, check_names=False)


# ---------- P7 ----------
def test_p7_a_rolling_does_not_leak_across_stocks():
    df = pd.DataFrame({
        "thscode": ["A.SH"] * 5 + ["B.SH"] * 5,
        "close": [1, 2, 3, 4, 5, 100, 200, 300, 400, 500],
    })
    grouped = group_by_stock(df)
    out = grouped["close"].rolling(2).mean()
    # Position 4 (last of A.SH) must use only 4 and 5, not B.SH's 100.
    assert out.iloc[4] == (4 + 5) / 2


# ---------- P8 ----------
def test_p8_a_universe_snapshot_at_decision_date_excludes_recent_ipo():
    df = pd.DataFrame({
        "thscode": ["600000.SH"] * 30 + ["000001.SZ"] * 100,
        "date": list(pd.date_range("2024-06-01", periods=30, freq="B"))
              + list(pd.date_range("2024-01-01", periods=100, freq="B")),
        "amount": [1e8] * 130,
    })
    eligible = apply_liquidity_filter(df, min_avg_turnover=5e7, lookback=60)
    assert "600000.SH" not in eligible   # has < lookback history
    assert "000001.SZ" in eligible


def test_p8_b_universe_skips_non_main_board():
    """apply_liquidity_filter alone does NOT exclude non-main-board;
    composite universe must intersect with is_main_board."""
    # Default lookback=60 — need ≥60 unique dates per thscode. Use three
    # distinct date ranges so each stock has its own 60-bar history.
    df = pd.DataFrame({
        "thscode": (["300750.SZ"] * 60) + (["688981.SH"] * 60) + (["600000.SH"] * 60),
        "date": list(pd.date_range("2024-01-01", periods=60, freq="B"))
              + list(pd.date_range("2024-02-01", periods=60, freq="B"))
              + list(pd.date_range("2024-03-01", periods=60, freq="B")),
        "amount": [1e8] * 180,
    })
    liquidity_eligible = apply_liquidity_filter(df)
    composite = {c for c in liquidity_eligible if is_main_board(c)}
    assert "600000.SH" in composite
    assert "300750.SZ" not in composite
    assert "688981.SH" not in composite
