"""§3 Dual-Price: cycle_price_action k_line_score must use adj_close.

CLAUDE.md §3 mandates:
  - Signal / indicators (MACD, MA, ATR, Volatility, ...) → MUST use adj_close
  - SL / TP / mark-to-market → MUST use raw_close

GAP CAPTURED (N5, 2026-09-28): cycle_price_action/signals.py:84-87 in
`k_line_score()` reads `df["close"]` (= raw_close per Layout C) for
MA5/MA10/MA20 computation. Preset `price_source_for_signal="adj_close"`
is silently ignored.

Layout C panel currently has only open/high/low/close (= raw). GREEN fix:
  (a) data_feed.py panel query: switch to v_daily_dual (which has adj_close)
      OR add adj_close via LEFT JOIN on v_daily_hfq
  (b) signals.py: k_line_score prefers adj_close column when present,
      falls back to close (legacy panel compatibility)

TDD: this file pins both contracts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycle_price_action.signals import detect_k_patterns, k_line_score


def _df_with_adj(rows, adj_rows=None):
    """Build a DataFrame mimicking Layout C + adj_close column.

    rows: list of (open, high, low, close, volume) tuples
    adj_rows: optional list of adj_close values (one per row). If None,
              adj_close = close (degenerate = raw-only panel).
    """
    n = len(rows)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    if adj_rows is None:
        df["adj_close"] = df["close"].values
    else:
        assert len(adj_rows) == n
        df["adj_close"] = adj_rows
    return df


def test_k_line_score_uses_adj_close_when_present() -> None:
    """§3 RED→GREEN: k_line_score MA5/MA10/MA20 use adj_close, not close.

    Build diverged panel where raw close = 100 (constant) and adj_close
    oscillates around 105. Confluence with MA5 should match close to adj
    MA5 (105) — NOT raw MA5 (100).
    """
    n = 30
    base = (10.0, 10.4, 9.8, 10.0, 1.0)
    rows = [base] * n
    # adj_close diverges by +5%; should drive MA5/10/20 ≈ 10.5
    adj_rows = [10.5] * n
    df = _df_with_adj(rows, adj_rows)

    patterns = detect_k_patterns(df)
    scored = k_line_score(df, patterns)

    # The last 20 bars (where MA20 is defined) should fire confluence:
    # close=10.0, adj_MA5/10/20 ≈ 10.5, so |10.0 - 10.5| / 10.5 ≈ 0.0476 > 0.02 → no confluence from raw
    # Wait — close = raw 10.0 vs adj MA = 10.5 → distance = 4.7% > 2% threshold → NO confluence
    # But the correct behavior is to test against adj_close (10.5) vs adj MA (10.5) → distance 0 → YES confluence
    # So if k_line_score uses adj_close properly, last ~20 bars should fire confluence.
    last_20_with_conf = scored.iloc[-20:][scored.iloc[-20:] >= 0.5].size
    # Confluence adds +0.5; if working correctly, MA-aligned bars get +0.5.
    # We just check that recent bars (where MA20 is defined) DO have confluence.
    # If reading raw close = 10.0 vs adj MA 10.5 → 4.7% > 2% → NO confluence
    # If reading adj close = 10.5 vs adj MA 10.5 → 0% → YES confluence (every bar)
    assert last_20_with_conf > 10, (
        f"§3 RED: k_line_score uses raw close (=10.0) instead of adj_close "
        f"(=10.5). Confluence threshold is ±2%, but |10.0-10.5|/10.5=4.7% "
        f"→ no confluence fired. Last 20 bars scored={scored.iloc[-20:].tolist()}"
    )


def test_k_line_score_falls_back_to_close_when_no_adj_column() -> None:
    """Legacy panel without adj_close column must still work (Layout C compat)."""
    rows = [(10.0, 10.4, 9.8, 10.2, 1.0)] * 25
    idx = pd.date_range("2024-01-01", periods=25, freq="B")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)

    patterns = detect_k_patterns(df)
    scored = k_line_score(df, patterns)

    # Should produce a finite series (no exception, no NaN crash)
    assert scored.between(-0.2, 2.5).all()
    # When close matches MA20 (all rows = 10.2), confluence fires.
    # Reasonable expected: some positive scores in last few bars.
    assert scored.iloc[-5:].sum() > 0


def test_cycle_signals_module_imports_adj_close_column() -> None:
    """§3 Contract pin: k_line_score source code references adj_close column."""
    src = Path("cycle_price_action/signals.py").read_text(encoding="utf-8")
    # GREEN expectation: k_line_score prefers adj_close column
    has_adj_close_ref = 'adj_close' in src
    assert has_adj_close_ref, (
        "GAP CAPTURED (§3 N5): cycle_price_action/signals.py never reads "
        "adj_close column. Preset `price_source_for_signal='adj_close'` "
        "is silently ignored. GREEN fix: k_line_score(df) should "
        "`cl = df['adj_close'] if 'adj_close' in df.columns else df['close']`."
    )


def test_cycle_data_feed_panel_includes_adj_close_column() -> None:
    """§3 Data-layer pin: cycle_price_action/data_feed.py SELECTs adj_close.

    Panel produced by load_universe_data must include adj_close. Currently
    Layout C panel has only open/high/low/close (= raw). GREEN fix: switch
    panel query to v_daily_dual (which exposes adj_close) or LEFT JOIN
    v_daily_hfq for adj_close column.
    """
    src = Path("cycle_price_action/data_feed.py").read_text(encoding="utf-8")
    panel_query_section = src.split("SELECT thscode, date, open, high, low, close")[0]
    # After this section, the panel query must include adj_close (or use
    # v_daily_dual which has it).
    # Look for any of:
    #   - adj_close in column list
    #   - v_daily_dual view reference (which includes adj_close)
    has_adj_close_col = "adj_close" in src
    has_v_daily_dual = "v_daily_dual" in src
    assert has_adj_close_col or has_v_daily_dual, (
        "GAP CAPTURED (§3 N5): cycle_price_action/data_feed.py panel query "
        "SELECTs only open/high/low/close (raw). Layout C has no adj_close. "
        "GREEN fix: switch to v_daily_dual view OR add adj_close via LEFT JOIN."
    )