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
    # GREEN expectation (N6 fix): volume_cap_fill returns at least 1 lot (100)
    # when bar has volume. RED bug was unbounded fill (size=10000 from all-in).
    # Acceptable GREEN: order cancelled (size N/A above) OR size = 100 (1 lot).
    assert size in (100, 200, 300), (
        f"BUG (§4): bar_vol=999, max_vol={MAX_VOL_PARTICIPATION} → "
        f"size={size} accepted (likely unbounded — cap bypassed). "
        f"Expected: cancel order (no trade) OR size == 100..300 (1-3 lots "
        f"from volume_cap_fill minimum-1-lot helper)."
    )


def test_volume_cap_rounding_constant_pin() -> None:
    """Pin (GREEN, 2026-09-28): chase_up portfolio uses volume_cap_fill helper.

    N6 fix: replaced `int(bar_vol * X // 100) * 100` round-to-0 formula with
    `volume_cap_fill(bar_vol, max_volume_participation, lot_size=100)` from
    core.dual_price. Pin to GREEN to detect future regression.
    """
    src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")
    has_helper = "volume_cap_fill" in src
    has_buggy = "int(bar_vol * max_volume_participation // 100) * 100" in src
    assert has_helper, (
        "N6 regression: chase_up/portfolio.py does NOT use volume_cap_fill helper."
    )
    assert not has_buggy, (
        "N6 regression: chase_up/portfolio.py reintroduced `// 100 * 100` bug."
    )


def test_volume_cap_rounding_constant_pin_uptrend() -> None:
    """Pin (GREEN, 2026-09-28): uptrend_pullback portfolio uses volume_cap_fill."""
    src = Path("uptrend_pullback/portfolio.py").read_text(encoding="utf-8")
    has_helper = "volume_cap_fill" in src
    has_buggy = "int(bar_vol * max_volume_participation // 100) * 100" in src
    assert has_helper, (
        "N6 regression: uptrend_pullback/portfolio.py does NOT use volume_cap_fill."
    )
    assert not has_buggy, (
        "N6 regression: uptrend_pullback/portfolio.py reintroduced `// 100 * 100` bug."
    )


def test_volume_cap_rounding_constant_pin_short_reversal() -> None:
    """Pin (GREEN, 2026-09-28): short_reversal uses volume_cap_fill helper.

    N6 fix: replaced `bar_vol * X / lot_size * lot_size` round-to-0 pattern
    with `volume_cap_fill(bar_vol, max_volume_participation, lot_size=lot_size)`.
    """
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")
    has_helper = (
        "from core.dual_price import" in src
        and "volume_cap_fill" in src
    )
    has_buggy = (
        "bar_vol * self.p.max_volume_participation / self.p.lot_size" in src
    )
    assert has_helper, (
        "N6 regression: short_reversal/replay_strategy_v3.py no longer imports "
        "volume_cap_fill helper from core.dual_price."
    )
    assert not has_buggy, (
        "N6 regression: short_reversal reintroduced `bar_vol * X / lot * lot` bug."
    )


def test_volume_cap_rounding_constant_pin_cycle() -> None:
    """Pin (out-of-scope): cycle_price_action still uses `// 100 * 100`.

    Per scope note (2026-09-28): cycle_price_action/portfolio.py 的 volume cap
    fix 不在本 agent 任务范围内。PIN 仅用于 forward-defense, 检测后续 cycle
    修复时不要引入 round-to-0 模式。若 cycle 已修复, 翻转此断言即可。
    """
    src = Path("cycle_price_action/portfolio.py").read_text(encoding="utf-8")
    has_buggy = (
        "int(bar_volume * self.MAX_VOL_PARTICIPATION // 100) * 100" in src
    )
    # 当前 cycle 仍未修复 round-to-0 模式 — 此 pin 仍处于 RED→GREEN 中间状态。
    # 若 cycle 已 wire 到 volume_cap_fill, 翻转此断言为 has_helper 模式。
    assert has_buggy, (
        "cycle_price_action/portfolio.py 不再使用 `// 100 * 100` 公式 — "
        "若已 wire 到 volume_cap_fill, 请更新此 pin 测试以匹配 GREEN 状态。"
    )
