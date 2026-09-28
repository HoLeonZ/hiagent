"""Control Plane panel loader for short_reversal (CLAUDE.md §6).

§6 architecture mandate:
  - Control Plane / Orchestrator owns PIT data dispatching (this module).
  - Strategy / Inference must NOT have direct DB access (no duckdb.connect
    inside scan_signals_fast._scan_preset / engine._load_panel).
  - Execution Broker must NOT have direct DB access (no per-fill DB queries).

This module is the SINGLE SOURCE for short_reversal DuckDB panel loading.
It exposes two helpers:

  load_panel_for_signal(db_path, signal_date, lookback_days=400)
    - Used by orchestrator (main loop) in scan_signals_fast.py.
    - Pulls a single rolling window (T - lookback_days → T) from v_daily.

  load_panel_for_backtest(db_path, start, end, universe)
    - Used by orchestrator (run_backtest_v3) in engine.py.
    - Pulls a per-stock panel with PANEL_FORWARD_BUFFER_DAYS pre-buffer
      (for MA60 warmup + insurance) and 60-day post-buffer (for in-flight
      closes — entries must NOT extend into post-buffer; see LAHEAD-001).

Both helpers own the duckdb.connect lifecycle internally; callers receive
a pure pd.DataFrame.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


# Pre-buffer: MA60 + 30-day insurance. Post-buffer: 60-day in-flight close.
# Buffer contract is locked by tests/test_short_reversal_no_lookahead.py
# (LAHEAD-001) + tests/golden/*. Any change must regenerate golden baselines.
PANEL_FORWARD_BUFFER_DAYS: int = 180
PANEL_POST_BUFFER_DAYS: int = 60


def load_panel_for_signal(
    db_path: Path, signal_date: str, lookback_days: int = 400,
) -> pd.DataFrame:
    """Pull panel from v_daily for [signal_date - lookback_days, signal_date].

    Used by orchestrator (scan_signals_fast.main) to load panel BEFORE
    calling the pure-compute `_scan_preset(panel, preset, signal_date)`.

    Returns: pd.DataFrame with cols thscode, date, open, high, low, close,
    amount, volume (date is pd.Timestamp).
    """
    start = (
        pd.Timestamp(signal_date) - pd.Timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT thscode, date, open, high, low, close, amount, volume "
            "FROM v_daily "
            "WHERE date BETWEEN ? AND ? "
            "ORDER BY thscode, date",
            [start, signal_date],
        ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_panel_for_backtest(
    db_path: Path, start: str, end: str, universe: list[str],
) -> pd.DataFrame:
    """Pull per-stock panel for backtest window [start, end].

    Pre/post buffers:
      - Pre (PANEL_FORWARD_BUFFER_DAYS=180): MA60 warmup + 30-day insurance
      - Post (PANEL_POST_BUFFER_DAYS=60): in-flight close buffer — exits may
        extend here, entries MUST NOT (LAHEAD-001 invariant).

    LEFT JOINs v_daily_hfq to expose adj_* columns (V3a, 2026-09-22).
    Strategy reads adj_close for indicator math, raw close for execution.

    Returns: pd.DataFrame with cols thscode, date, open, high, low, close,
    amount, volume, adj_open, adj_high, adj_low, adj_close.
    """
    panel_start = (
        pd.Timestamp(start) - pd.Timedelta(days=PANEL_FORWARD_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")
    panel_end = (
        pd.Timestamp(end) + pd.Timedelta(days=PANEL_POST_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            """
            SELECT v.thscode, v.date,
                   v.open, v.high, v.low, v.close, v.amount, v.volume,
                   h.open  AS adj_open,
                   h.high  AS adj_high,
                   h.low   AS adj_low,
                   h.close AS adj_close
            FROM v_daily v
            LEFT JOIN v_daily_hfq h
              ON v.thscode = h.thscode AND v.date = h.date
            WHERE v.date BETWEEN ? AND ? AND v.thscode = ANY(?)
            ORDER BY v.thscode, v.date
            """,
            [panel_start, panel_end, universe],
        ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df
