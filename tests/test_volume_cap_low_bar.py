"""§4 Volume cap LOW-BAR EDGE CASE RED tests.

CLAUDE.md §4: 'Max_Fill_Qty = MIN(Order_Qty, Bar_Volume × 0.10). Unfilled
quantities must be explicitly canceled or queued.'

Pessimistic default: low-volume bars (bar_vol * 0.10 < 1 lot) should NOT
silently bypass the cap.

BUG observed (2026-09-23): chase_up/portfolio.py:406, uptrend_pullback/
portfolio.py:395, short_reversal/replay_strategy_v3.py:257, and
cycle_price_action/portfolio.py:137 all use
`int(bar_vol * X // 100) * 100` rounding. When bar_vol * 0.10 < 100,
rounded max_fill = 0, the cap guard
`if max_fill > 0 and size > max_fill: size = max_fill` is skipped —
silently allowing unlimited order size for low-volume bars.

Existing test `test_simulate_portfolio_max_volume_participation_caps_size`
(test_chase_up_no_lookahead.py:1130) uses bar_vol=1000 → max_fill=100 (1
lot), exactly at the rounding boundary. It does NOT exercise the
silent-bypass case (bar_vol < 1000).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chase_up.portfolio import MAX_VOL_PARTICIPATION, simulate_portfolio


def _build_low_vol_panel(thscodes: list[str], bar_vol: float = 999.0) -> pd.DataFrame:
    """Synthetic panel: low bar_vol, price stable."""
    dates = pd.date_range("2025-09-01", "2025-09-15", freq="B")
    rows = []
    for code in thscodes:
        for d in dates:
            rows.append({
                "date": d, "thscode": code,
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
                "volume": bar_vol, "amount": bar_vol * 10.0, "atr_pct": 0.02,
            })
    return pd.DataFrame(rows)


def _build_entries(thscodes: list[str], entry_date: str = "2025-09-01") -> pd.DataFrame:
    """Entries that signal on day 1 for each stock."""
    rows = []
    for code in thscodes:
        rows.append({
            "date": pd.Timestamp(entry_date), "thscode": code,
            "score": 1.0, "sub_signal_type": "A", "atr_pct": 0.02,
            "sig_close": 10.0, "sig_ma20": 9.5, "sig_ma60": 9.0, "sig_ret1": 0.05,
            "sig_breakout_score": 0.5, "sig_momentum_score": 0.3,
            "sig_macross_score": np.nan,
            "sig_mom120": 0.05, "sig_amount60": 5e7,
        })
    return pd.DataFrame(rows)


def test_chase_up_volume_cap_low_bar_silently_bypassed() -> None:
    """§4 RED: bar_vol=999 → max_fill=0 → cap skipped → unlimited fill BUG.

    Compare two scenarios:
      (a) bar_vol=999 (BUG case): entry should NOT fill, OR fill capped < 100
      (b) bar_vol=10000 (healthy): entry fills, capped to 1000 shares
    """
    panel_low = _build_low_vol_panel(["ILLQ.SZ"], bar_vol=999.0)
    entries = _build_entries(["ILLQ.SZ"])

    trades_low, _ = simulate_portfolio(
        entries, panel_low,
        tp_pct=0.10, sl_pct=0.05, max_hold=8, max_positions=1,
        start_date="2025-09-01", end_date="2025-09-15",
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )

    if len(trades_low) == 0:
        # GREEN behavior: order cancelled when bar too thin
        return

    size = int(trades_low.iloc[0]["size"])
    # GREEN expectation: size <= 99 (cancel or cap to < 1 lot)
    # RED actual: size may be 10000 (unlimited — cap bypassed)
    assert size <= 99, (
        f"BUG (§4): bar_vol=999, max_vol={MAX_VOL_PARTICIPATION} → "
        f"rounded max_fill = 0, cap guard skipped, "
        f"size={size} accepted (all-in unbounded). "
        f"Expected: cancel order or cap size < 100."
    )


def test_volume_cap_rounding_constant_pin() -> None:
    """Pin: chase_up portfolio uses `// 100 * 100` rounding → low-bar bypass."""
    src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")
    assert "int(bar_vol * max_volume_participation // 100) * 100" in src, (
        "Pattern mismatch — chase_up cap formula changed"
    )
    # Confirm the buggy guard is present
    assert "if max_fill > 0 and size > max_fill:" in src, (
        "Cap guard missing or restructured — re-evaluate"
    )


def test_volume_cap_rounding_constant_pin_uptrend() -> None:
    """Pin: uptrend_pullback portfolio uses identical formula."""
    src = Path("uptrend_pullback/portfolio.py").read_text(encoding="utf-8")
    assert "int(bar_vol * max_volume_participation // 100) * 100" in src, (
        "Pattern mismatch — uptrend_pullback cap formula changed"
    )
    assert "if max_fill > 0 and size > max_fill:" in src, (
        "uptrend_pullback cap guard missing"
    )


def test_volume_cap_rounding_constant_pin_short_reversal() -> None:
    """Pin: short_reversal uses / lot_size * lot_size (same edge case)."""
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")
    assert (
        "bar_vol * self.p.max_volume_participation / self.p.lot_size" in src
    ), "Pattern mismatch — short_reversal cap formula changed"


def test_volume_cap_rounding_constant_pin_cycle() -> None:
    """Pin: cycle_price_action uses identical `// 100 * 100` formula."""
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")
    assert (
        "int(bar_volume * self.MAX_VOL_PARTICIPATION // 100) * 100" in src
    ), "Pattern mismatch — cycle cap formula changed"
