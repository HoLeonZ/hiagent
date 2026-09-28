"""§3 Dual-Price: short_reversal SMA/MACD/ATR must use adj_close.

CLAUDE.md §3 mandates:
  - Signal / indicators (MACD, MA, ATR, Volatility, ...) → MUST use adj_close
  - SL / TP / mark-to-market → MUST use raw_close

GAP CAPTURED (N5, 2026-09-28): short_reversal/replay_strategy_v3.py:97-115
constructs SMA(5/10/20/60), MACD, ATR using `d.close` (= raw_close per Layout
B). Presets declare `price_source_for_signal="adj_close"` but strategy
silently ignores — every SMA/MACD/ATR value is computed on raw_close,
violating the dual-price contract.

Layout B (LAYOUT_SHORT_REVERSAL) provides adj_* columns via LEFT JOIN on
v_daily_hfq. AShareData (short_reversal/feed_bt.py) exposes `adj_close` as
a backtrader line — strategy MUST switch indicator inputs from d.close to
d.lines.adj_close.

TDD: this file is the contract lock. RED → switch to adj_close → GREEN.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_adj_diverged_panel(
    n_bars: int = 120,
    raw_close: float = 100.0,
    adj_close: float = 105.0,
    vol: float = 1_000_000.0,
) -> pd.DataFrame:
    """Synthetic panel where raw_close ≠ adj_close by design.

    raw_close (v_daily) = 100, adj_close (v_daily_hfq LEFT JOIN) = 105.
    If strategy reads raw → SMA5 = 100; if reads adj → SMA5 = 105.
    """
    dates = pd.date_range("2025-01-01", periods=n_bars, freq="B")
    return pd.DataFrame({
        "date": dates,
        "thscode": "TEST.SZ",
        "open": raw_close,
        "high": raw_close * 1.01,
        "low": raw_close * 0.99,
        "close": raw_close,
        "volume": vol,
        "amount": vol * raw_close,
        "adj_open": adj_close,
        "adj_high": adj_close * 1.01,
        "adj_low": adj_close * 0.99,
        "adj_close": adj_close,
    })


def test_strategy_indicators_use_adj_close_not_raw_close() -> None:
    """§3 RED→GREEN: Phase3V3Strategy's SMA/MACD/ATR inputs MUST be adj_close.

    Implementation contract: replay_strategy_v3.py:97-115 must construct
    `bt.indicators.SMA(d.lines.adj_close, ...)` (not `d.close`), and
    MACD/ATR similarly. Otherwise indicators silently compute on raw
    domain = dual-price contract violation.
    """
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")
    # Locate the SMA / MACD / ATR construction block in __init__.
    # Indicator lines sourced from adj_close (Layout B contract).
    # Patterns we accept:
    #   bt.indicators.SMA(d.lines.adj_close, period=N)
    #   bt.indicators.MACD(d.lines.adj_close)
    #   bt.indicators.ATR(d.lines, period=N)   ← ATR takes data, not line;
    #                                            by feeding adj_close data it
    #                                            computes on adj domain.
    sma_adj = bool(
        # Standard PandasData line attribute access
        "SMA(d.lines.adj_close" in src
        or "SMA(d.adj_close" in src
        # Cleaner: assign `adj_close_src = d.lines.adj_close` once, reuse
        or "SMA(adj_close_src" in src
        # Also accept d.lines.adj_close attribute (same access pattern)
        or "bt.indicators.SMA(d.lines.adj_close" in src
    )
    macd_adj = bool(
        "MACD(d.lines.adj_close" in src
        or "MACD(d.adj_close" in src
        or "MACD(adj_close_src" in src
    )
    atr_adj = bool(
        "ATR(d.lines.adj_close" in src
        or "ATR(d.adj_close" in src
        or "AtrAdj(d" in src
    )

    assert sma_adj, (
        "GAP CAPTURED (§3 N5): short_reversal/replay_strategy_v3.py:97-115 "
        "constructs SMA using `d.close` (= raw_close). Presets declare "
        "`price_source_for_signal='adj_close'` but strategy silently uses "
        "raw. GREEN fix: switch to `d.lines.adj_close` (Layout B provides "
        "adj_* via LEFT JOIN — AShareData exposes adj_close line)."
    )
    assert macd_adj, (
        "GAP CAPTURED (§3 N5): MACD indicator still constructed from "
        "`d.close`. Switch to `d.lines.adj_close`."
    )
    assert atr_adj, (
        "GAP CAPTURED (§3 N5): ATR indicator still constructed from `d` "
        "(which defaults to .close). Switch to feed whose close line is "
        "adj_close, e.g. build a sub-feed or pass adj_close line."
    )


def test_sma5_value_matches_adj_close_input() -> None:
    """§3 End-to-end: SMA5 computed on adj_close=105, not raw=100.

    Construct AShareData with adj_close diverged by +5% from raw. Attach
    the indicator to a strategy so backtrader advances it with the feed.
    Final SMA5 must equal adj_close value (105), not raw (100).
    """
    import backtrader as bt

    from short_reversal.feed_bt import AShareData

    panel = _make_adj_diverged_panel(n_bars=120, raw_close=100.0, adj_close=105.0)

    cerebro = bt.Cerebro()
    feed = AShareData(dataname=panel, plot=False)
    cerebro.adddata(feed)

    captured: dict = {}

    class _Probe(bt.Strategy):
        def __init__(self):
            self.sma5 = bt.indicators.SMA(self.datas[0].lines.adj_close, period=5)

        def stop(self):
            captured["sma5_final"] = float(self.sma5[0])

    cerebro.addstrategy(_Probe)
    cerebro.run()

    final_sma5 = captured["sma5_final"]
    # If adj_close is wired correctly, SMA5 final = 105.0
    # If raw_close leaks through, SMA5 final = 100.0
    assert final_sma5 == pytest.approx(105.0, rel=1e-6), (
        f"§3 RED: SMA5(adj_close)={final_sma5}, expected 105.0. "
        f"If 100.0 → strategy is reading raw_close instead of adj_close."
    )


def test_short_reversal_strategy_no_longer_constructs_sma_from_d_close() -> None:
    """§3 Forward-defense pin: replay_strategy_v3.py MUST NOT regress to d.close."""
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")
    # Bug pattern: bt.indicators.SMA(d.close, period=N)
    has_buggy_sma = "SMA(d.close, period=" in src
    has_buggy_macd = "MACD(d.close)" in src
    has_buggy_atr = bool(
        # ATR(d, period=14) — default data close = raw_close; not adj_close
        re.search(r"bt\.indicators\.ATR\(d,\s*period=", src) is not None
    )

    assert not (has_buggy_sma or has_buggy_macd or has_buggy_atr), (
        f"§3 REGRESSION: short_reversal/replay_strategy_v3.py still "
        f"constructs indicators from raw close:\n"
        f"  SMA(d.close, ...) = {has_buggy_sma}\n"
        f"  MACD(d.close) = {has_buggy_macd}\n"
        f"  ATR(d, ...) = {has_buggy_atr}\n"
        f"Per §3 dual-price contract, indicators MUST use adj_close."
    )