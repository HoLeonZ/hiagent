"""F-01 regression: build_per_stock_feeds must not silently drop the whole universe.

Root cause (2026-10-17, found while validating the live-deployment baseline):

  short_reversal/feed_bt.py:96-97 did `if len(sub) < min_bars: continue` with no
  warning and no return count. engine.run_backtest_v3 then built a Cerebro with
  zero data feeds and returned a well-formed metrics dict reporting
  trades=0 / final_capital=initial / max_dd=0.

Reproduced on the real DB with end=2026-10-16:
  start=2026-07-01  -> panel spans 2026-01-05..2026-10-16 = 188 trading days
  min_bars=200      -> 0 of 3190 stocks qualify -> 0 trades (run took 5.9s)
  min_bars=100      -> 14 trades
  min_bars=60       ->  5 trades

  start=2025-09-12  -> panel spans 2025-03-17..2026-10-16 = 385 trading days
  min_bars=200      -> 3161 of 3161 qualify -> 80 trades

CLAUDE.md §0 Fail-Fast: "If a state transition violates physical market laws,
throw an exception immediately. Do not silently bypass."

For the live monitor this is the #1 silent-failure mode: the monitor would report
"no signal today" every day while the engine had actually discarded the entire
universe. A zero-trade result must therefore be distinguishable from an
empty-feed result.

These tests are pure (no DuckDB, no network) and always run.
"""
from __future__ import annotations

import logging

import pandas as pd
import pytest

from short_reversal.feed_bt import build_per_stock_feeds


def _panel(codes_bars: dict[str, int]) -> pd.DataFrame:
    """Build a minimal v_daily-shaped panel; code -> number of daily bars."""
    rows = []
    for code, n in codes_bars.items():
        for d in pd.date_range("2025-01-01", periods=n, freq="B"):
            rows.append({
                "thscode": code, "date": d,
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
                "amount": 5e7, "volume": 1e6,
                "adj_open": 10.0, "adj_high": 10.5,
                "adj_low": 9.5, "adj_close": 10.0,
            })
    return pd.DataFrame(rows)


class TestEmptyUniverseIsAnError:
    """Every requested code was dropped -> fail fast, do not return []. """

    def test_all_codes_dropped_raises(self):
        panel = _panel({"600000.SH": 200, "000001.SZ": 200})
        with pytest.raises(ValueError, match="min_bars"):
            build_per_stock_feeds(panel, ["600000.SH", "000001.SZ"], min_bars=201)

    def test_all_codes_dropped_raises_and_names_the_gate(self):
        """The error must name min_bars and report the observed bar counts
        so an operator can tell a config error from a quiet market."""
        panel = _panel({"600000.SH": 188})
        with pytest.raises(ValueError) as ei:
            build_per_stock_feeds(panel, ["600000.SH"], min_bars=200)
        msg = str(ei.value)
        assert "min_bars=200" in msg
        assert "188" in msg
        assert "1" in msg  # requested code count

    def test_codes_absent_from_panel_entirely_also_raises(self):
        """Universe resolved but panel has no rows for those codes."""
        panel = _panel({"600000.SH": 300})
        with pytest.raises(ValueError, match="min_bars"):
            build_per_stock_feeds(panel, ["999999.SZ"], min_bars=200)


class TestEmptyUniverseInputIsFine:
    """An empty codes list is a legitimate outcome (e.g. universe filter
    returned nothing) and must NOT be conflated with the all-dropped case."""

    def test_empty_codes_returns_empty_without_raising(self):
        panel = _panel({"600000.SH": 300})
        assert build_per_stock_feeds(panel, [], min_bars=200) == []


class TestPartialDropIsLoud:
    """Some codes dropped is normal, but must be observable."""

    def test_partial_drop_logs_warning_with_counts(self, caplog):
        panel = _panel({"600000.SH": 300, "000001.SZ": 50})
        with caplog.at_level(logging.WARNING, logger="short_reversal.feed_bt"):
            feeds = build_per_stock_feeds(
                panel, ["600000.SH", "000001.SZ"], min_bars=200
            )
        assert len(feeds) == 1
        assert feeds[0][0] == "600000.SH"
        text = caplog.text
        assert "000001.SZ" in text
        assert "min_bars=200" in text
        assert "1/2" in text

    def test_no_warning_when_nothing_dropped(self, caplog):
        panel = _panel({"600000.SH": 300, "000001.SZ": 300})
        with caplog.at_level(logging.WARNING, logger="short_reversal.feed_bt"):
            feeds = build_per_stock_feeds(
                panel, ["600000.SH", "000001.SZ"], min_bars=200
            )
        assert len(feeds) == 2
        assert caplog.text == ""
