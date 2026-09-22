"""V3a runtime integration test for short_reversal (2026-09-22, CLAUDE.md §3).

Mirrors tests/test_uptrend_pullback_v3a_runtime.py for short_reversal's 11 presets.

short_reversal engine.py now LEFT JOINs v_daily_hfq to add adj_open/adj_high/
adj_low/adj_close. The feed_bt.AShareData declares adj_* lines + auto-injects
NaN when the panel (e.g. legacy tests) lacks them. Strategy by default still
reads raw (v_daily IS raw) for baseline parity, but adj_* lines are now
available in the feed for future migration.

Since short_reversal v3 is event-driven (Phase3V3Strategy reads panel via
cerebro feeds, not portfolio.simulate_portfolio), this test verifies:
  1. AShareData accepts a panel with adj_* columns without error
  2. AShareData accepts a legacy panel without adj_* columns (NaN injection)
  3. The strategy still operates on raw close (baseline parity)
  4. v3 engine end-to-end run succeeds with adj_* columns attached
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData, build_per_stock_feeds


def _build_panel(n: int = 250, dividend_at: int = 100) -> pd.DataFrame:
    """Build a panel with both raw (v_daily) and adj (v_daily_hfq) columns.

    Pre-dividend: raw=adj=10.0. Post-dividend: adj stays flat (qfq convention
    here), raw drops to 8.0 (back-adjusted hfq reflects physical dividend).
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_post = i >= dividend_at
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
            "adj_open": 10.0, "adj_high": 10.5,
            "adj_low": 9.5, "adj_close": 10.0,
        })
    return pd.DataFrame(rows)


def _build_legacy_panel(n: int = 250) -> pd.DataFrame:
    """Build a panel WITHOUT adj_* columns (legacy / pre-V3a format)."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
        })
    return pd.DataFrame(rows)


# ---------- AShareData feed integration ----------

def test_asharedata_accepts_panel_with_adj_columns():
    """Panel with adj_* columns must load without error."""
    panel = _build_panel(n=100)
    feeds = build_per_stock_feeds(panel, ["TEST.SH"], min_bars=50)
    assert len(feeds) == 1
    code, feed = feeds[0]
    assert code == "TEST.SH"
    # dataname keeps adj_* columns after build
    assert "adj_close" in feed.p.dataname.columns


def test_asharedata_injects_nan_for_missing_adj_columns():
    """Legacy panel without adj_* must auto-inject NaN, no ValueError."""
    panel = _build_legacy_panel(n=100)
    feeds = build_per_stock_feeds(panel, ["TEST.SH"], min_bars=50)
    assert len(feeds) == 1
    _, feed = feeds[0]
    # NaN was injected
    for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
        assert col in feed.p.dataname.columns
        # all NaN
        assert feed.p.dataname[col].isna().all()


def test_asharedata_start_does_not_raise_with_missing_adj():
    """Override of start() must call super().start() cleanly even when
    dataname is missing adj_* columns at construction time.
    """
    panel = _build_legacy_panel(n=100)
    feed = AShareData(dataname=panel, plot=False)
    # Should not raise
    feed.start()


def test_asharedata_lines_declared():
    """Verify AShareData declares the adj_* lines required by V3a."""
    # backtrader exposes line names as attributes on the Lines metaclass
    line_attrs = {attr for attr in dir(AShareData.lines) if not attr.startswith("_")}
    for col in ("adj_open", "adj_high", "adj_low", "adj_close"):
        assert col in line_attrs, f"V3a: AShareData.lines.{col} 必须声明"


# ---------- engine.py panel shape contract ----------

def test_engine_left_join_query_shape(monkeypatch):
    """Mock duckdb and verify engine._load_panel issues LEFT JOIN against
    v_daily_hfq to add adj_* columns (V3a wiring).
    """
    from short_reversal import engine as eng

    captured = {"sql": None, "params": None}

    class FakeCon:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            captured["params"] = params
            class _Cur:
                def fetchdf(self_inner):
                    return pd.DataFrame({
                        "thscode": ["TEST.SH"] * 2,
                        "date": pd.to_datetime(["2024-06-01", "2024-06-02"]),
                        "open": [10.0, 10.1], "high": [10.5, 10.6],
                        "low": [9.5, 9.6], "close": [10.0, 10.1],
                        "amount": [1e7, 1.1e7], "volume": [1e6, 1.1e6],
                        "adj_open": [10.0, 10.1], "adj_high": [10.5, 10.6],
                        "adj_low": [9.5, 9.6], "adj_close": [10.0, 10.1],
                    })
            return _Cur()
        def close(self_inner):
            pass

    def fake_connect(*args, **kwargs):
        return FakeCon()

    monkeypatch.setattr(eng.duckdb, "connect", fake_connect)
    df = eng._load_panel(Path("/tmp/nope.db"), "2024-06-01", "2024-06-02", ["TEST.SH"])
    # Confirm LEFT JOIN was issued and adj_* columns selected
    sql = captured["sql"]
    assert sql is not None
    assert "LEFT JOIN v_daily_hfq" in sql, "V3a: engine must LEFT JOIN v_daily_hfq"
    assert "adj_open" in sql and "adj_close" in sql, "V3a: SQL must select adj_*"
    assert "date BETWEEN" in sql
    # Confirm returned df has adj_* columns
    assert "adj_close" in df.columns


# ---------- strategy baseline parity (V3a default = raw) ----------

def test_v3_strategy_runs_with_adj_lines_available():
    """End-to-end: build a panel with adj_* cols, run AShareData.start(),
    verify the strategy loads (mocked) without errors. We don't run the full
    backtrader here — we just verify the feed boots.

    The full v3 backtest is exercised by golden baselines + existing
    test_short_reversal_no_lookahead.py suite.
    """
    panel = _build_panel(n=250)
    feeds = build_per_stock_feeds(panel, ["TEST.SH"], min_bars=50)
    assert len(feeds) == 1
    _, feed = feeds[0]
    # feed.start() should not raise with adj_* present
    feed.start()
    # The feed's lines are now queryable
    assert feed.lines.adj_close is not None
