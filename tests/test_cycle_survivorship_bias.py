"""§3 Survivorship bias audit: cycle_price_action must NOT silently drop
stocks that traded within the [start, end] window but delisted before
ref_end (Tick N4).

CLAUDE.md §3 (PIT Mandate): 'Delisted assets must remain in the simulation
until their physical delisting date.' universe filtering should be based on
whether a stock has data within the requested backtest window, not on whether
it still trades on or after `ref_end`.

Production bug at cycle_price_action/data_feed.py:35:
    listed = {r[0] for r in listed_rows if r[1] is not None and r[1] >= ref_end}

This drops stocks that have data within [start, end] but whose MAX(date) < ref_end
(e.g. a stock delisted in March 2025 when end=July 2025). The drawdown incurred
during its trading window is silently lost — survivorship bias.

Fix: include any stock whose MAX(date) >= start (i.e. had at least one trading
day in the requested window). Liquidity filter (60d rolling mean of amount)
further narrows the universe downstream; this test pins the inclusion semantics.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from cycle_price_action.data_feed import load_universe_data


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def survivorship_db(tmp_path):
    """3 stocks:
    - A (600000.SH): delisted mid-window (data 2025-01-02 .. 2025-04-01, then gone).
      MUST be included (data within [start, end]).
    - B (600001.SH): never traded in window (data outside [start, end]).
      MUST be excluded (no data in window).
    - C (600002.SH): still trading through end (data 2025-01-02 .. 2025-09-21).
      MUST be included (data within [start, end]).
    """
    db = tmp_path / "survivorship.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""
        CREATE TABLE v_daily (
            thscode VARCHAR, date DATE,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            volume DOUBLE, amount DOUBLE
        )
    """)

    # Need >= 60 unique trading days of liquidity (min_avg_turnover=5e7 default
    # lookback=60) for any stock to survive apply_liquidity_filter. Pad each
    # stock's window with 60 BD of high-amount data.
    pad_dates = pd.date_range("2024-08-01", "2024-12-31", freq="B")  # 107 BD
    a_dates = pd.date_range("2024-11-01", "2025-04-01", freq="B")     # ~110 BD
    c_dates = pd.date_range("2025-01-02", "2025-09-21", freq="B")     # ~187 BD

    rows = []
    # Stock A: 60+ BD pad (pre-window) + ~110 BD in-window → delisted 2025-04-01
    for d in pad_dates:
        rows.append(("600000.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e6, 1e8))
    for d in a_dates:
        rows.append(("600000.SH", d.date(), 11.0, 11.5, 10.8, 11.2, 1e6, 1e8))

    # Stock B: only pre-window data, nothing in [start, end]
    for d in pad_dates:
        rows.append(("600001.SH", d.date(), 20.0, 20.5, 19.8, 20.2, 1e6, 1e8))

    # Stock C: in-window + still listed at end
    for d in pad_dates:
        rows.append(("600002.SH", d.date(), 30.0, 30.5, 29.8, 30.2, 1e6, 1e8))
    for d in c_dates:
        rows.append(("600002.SH", d.date(), 31.0, 31.5, 30.8, 31.2, 1e6, 1e8))

    con.executemany(
        "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)", rows
    )
    con.close()
    return db


# ---------------------------------------------------------------- tests


def test_includes_delisted_stocks_with_data_in_window(survivorship_db):
    """N4.1: stock with MAX(date) < ref_end but data within [start, end]
    MUST be included in the universe (no survivorship bias)."""
    universe = load_universe_data(
        str(survivorship_db), start=date(2025, 1, 1), end=date(2025, 9, 21),
    )
    codes = set(universe.keys())
    assert "600000.SH" in codes, (
        f"N4.1 FAIL: delisted-mid-window stock 600000.SH must be in "
        f"universe (data spans [2025-01-02, 2025-04-01]). Got: {sorted(codes)}"
    )


def test_excludes_stocks_never_traded_in_window(survivorship_db):
    """N4.2: stock with NO data within [start, end] MUST be excluded.
    600001.SH only has pre-window rows; its MAX(date) < start."""
    universe = load_universe_data(
        str(survivorship_db), start=date(2025, 1, 1), end=date(2025, 9, 21),
    )
    codes = set(universe.keys())
    assert "600001.SH" not in codes, (
        f"N4.2 FAIL: stock with no data in [start, end] must be excluded. "
        f"Got: {sorted(codes)}"
    )


def test_includes_stock_trading_through_end(survivorship_db):
    """Sanity: stock with data in window AND still listed at end stays in universe."""
    universe = load_universe_data(
        str(survivorship_db), start=date(2025, 1, 1), end=date(2025, 9, 21),
    )
    codes = set(universe.keys())
    assert "600002.SH" in codes, (
        f"N4.3 FAIL: continuously-listed stock 600002.SH must be in universe. "
        f"Got: {sorted(codes)}"
    )


def test_universe_includes_delisted_with_padded_pre_window_liquidity(tmp_path):
    """§3 PIT Mandate end-to-end: delisted stock with sufficient in-window
    data (and pre-window liquidity history for the 60d rolling mean) MUST
    survive BOTH the delisting filter AND the liquidity filter, even when
    OTHER stocks in the DB push db_last beyond the delisted stock's
    MAX(date) (so ref_end > MAX(date) for the delisted stock)."""
    db = tmp_path / "pit.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""
        CREATE TABLE v_daily (
            thscode VARCHAR, date DATE,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            volume DOUBLE, amount DOUBLE
        )
    """)
    # Pad dates for BOTH stocks (pre-window liquidity history).
    pad_dates = pd.date_range("2024-08-01", "2024-12-31", freq="B")
    # Delisted stock 600000.SH: in-window only through 2025-04-01.
    in_window_a = pd.date_range("2025-01-02", "2025-04-01", freq="B")
    # Still-listed stock 600002.SH: in-window through 2025-09-21.
    in_window_c = pd.date_range("2025-01-02", "2025-09-21", freq="B")
    rows = []
    for d in pad_dates:
        rows.append(("600000.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e6, 1e8))
    for d in in_window_a:
        rows.append(("600000.SH", d.date(), 11.0, 11.5, 10.8, 11.2, 1e6, 1e8))
    for d in pad_dates:
        rows.append(("600002.SH", d.date(), 30.0, 30.5, 29.8, 30.2, 1e6, 1e8))
    for d in in_window_c:
        rows.append(("600002.SH", d.date(), 31.0, 31.5, 30.8, 31.2, 1e6, 1e8))
    con.executemany("INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)", rows)
    con.close()

    universe = load_universe_data(
        str(db), start=date(2025, 1, 1), end=date(2025, 9, 21),
    )
    codes = set(universe.keys())
    # Pre-fix (MAX(date) >= ref_end): ref_end = min(end, db_last) = 2025-09-21
    # (driven by 600002.SH). 600000.SH MAX(date)=2025-04-01 < ref_end → DROPPED.
    # Post-fix (MAX(date) >= start): 600000.SH MAX(date) >= 2025-01-01 → KEPT.
    assert "600000.SH" in codes, (
        "N4.4 FAIL: delisted stock 600000.SH (MAX(date)=2025-04-01, "
        "with data within [2025-01-01, 2025-09-21]) must survive BOTH the "
        "delisting filter and the liquidity filter. Survivorship bias: "
        f"got {sorted(codes)}."
    )
    assert "600002.SH" in codes, (
        f"N4.4 FAIL: still-listed 600002.SH must be in universe. "
        f"Got: {sorted(codes)}."
    )