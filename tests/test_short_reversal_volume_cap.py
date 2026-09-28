"""§4 Volume cap RED test: short_reversal cap must not round to 0 for low-bar.

CLAUDE.md §4: 'Max_Fill_Qty = MIN(Order_Qty, Bar_Volume × 0.10). Unfilled
quantities must be explicitly canceled or queued.'

GAP CAPTURED (N6, 2026-09-28): short_reversal/replay_strategy_v3.py:257
uses `int(bar_vol * max_volume_participation / self.p.lot_size) *
self.p.lot_size` (same round-to-0 bug as chase_up:406 / uptrend:395).
When bar_vol < 1000 × 0.10 / 100 = 1 lot, max_fill → 0 and cap guard
silently bypasses → unlimited fill.

This test asserts the GREEN behavior: bar_vol=500, max_pct=0.10, lot=100
→ max_fill ≥ 100 (1 lot) — order fills at least 1 lot, OR is cancelled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.dual_price import volume_cap_fill


def test_volume_cap_fill_below_1000_does_not_round_to_zero() -> None:
    """§4 RED→GREEN: bar_vol=500, max_pct=0.10, lot_size=100 → fill ≥ 100.

    Current bug: int(500 * 0.10 / 100) * 100 = int(0.5) * 100 = 0 * 100 = 0.
    GREEN fix: volume_cap_fill returns at least 1 lot (100) when raw cap
    rounds to zero but bar has any volume, OR zero only when bar_vol ≤ 0.
    """
    fill = volume_cap_fill(bar_vol=500.0, max_pct=0.10, lot_size=100)
    assert fill >= 100, (
        f"§4 RED: bar_vol=500, max_pct=0.10, lot=100 → fill={fill} (rounded to 0). "
        f"Expected: ≥ 100 (at least 1 lot) OR 0 (cancelled, no fill)."
    )


def test_volume_cap_fill_zero_bar_returns_zero() -> None:
    """§4 Edge: bar_vol=0 → fill=0 (no volume = no fill)."""
    assert volume_cap_fill(bar_vol=0.0, max_pct=0.10, lot_size=100) == 0


def test_volume_cap_fill_negative_bar_returns_zero() -> None:
    """§4 Edge: negative bar_vol → fill=0 (data anomaly)."""
    assert volume_cap_fill(bar_vol=-100.0, max_pct=0.10, lot_size=100) == 0


def test_volume_cap_fill_zero_pct_returns_zero() -> None:
    """§4 Edge: max_pct=0 → fill=0 (no participation)."""
    assert volume_cap_fill(bar_vol=10000.0, max_pct=0.0, lot_size=100) == 0


def test_volume_cap_fill_rounds_to_lot_size() -> None:
    """§4 Helper rounds DOWN to nearest lot_size for sane cases."""
    # bar_vol=12345, max_pct=0.10 → raw=1234.5 → floor 1 lot = 1200
    assert volume_cap_fill(bar_vol=12345.0, max_pct=0.10, lot_size=100) == 1200


def test_volume_cap_fill_typical_bar() -> None:
    """§4 Typical: bar_vol=10000, max_pct=0.10 → 1000."""
    assert volume_cap_fill(bar_vol=10000.0, max_pct=0.10, lot_size=100) == 1000


def test_volume_cap_fill_high_volume_bar() -> None:
    """§4 High volume: bar_vol=1_000_000, max_pct=0.10 → 100000."""
    assert volume_cap_fill(bar_vol=1_000_000.0, max_pct=0.10, lot_size=100) == 100_000


def test_volume_cap_fill_exact_one_lot_bar() -> None:
    """§4 Boundary: bar_vol * max_pct == lot_size → exactly 1 lot."""
    # 1000 * 0.10 = 100 = 1 lot
    assert volume_cap_fill(bar_vol=1000.0, max_pct=0.10, lot_size=100) == 100


def test_short_reversal_strategy_uses_volume_cap_fill_helper() -> None:
    """§4 Pin: replay_strategy_v3.py uses core.dual_price.volume_cap_fill.

    The buggy `int(bar_vol * X / lot) * lot` pattern must be GONE.
    """
    src = Path("short_reversal/replay_strategy_v3.py").read_text(encoding="utf-8")
    has_helper_import = "from core.dual_price import" in src and "volume_cap_fill" in src
    has_buggy_pattern = (
        "bar_vol * self.p.max_volume_participation / self.p.lot_size" in src
    )
    assert has_helper_import, (
        "§4 GAP CAPTURED (N6): short_reversal strategy does NOT import "
        "volume_cap_fill helper. GREEN fix: import from core.dual_price "
        "and replace the buggy `int(bar_vol * X / lot) * lot` pattern."
    )
    assert not has_buggy_pattern, (
        "§4 GAP CAPTURED (N6): short_reversal still uses the round-to-0 "
        "pattern `bar_vol * X / lot * lot`. Replace with volume_cap_fill()."
    )


def test_chase_up_uses_volume_cap_fill_helper() -> None:
    """§4 Pin: chase_up/portfolio.py uses volume_cap_fill helper."""
    src = Path("chase_up/portfolio.py").read_text(encoding="utf-8")
    # Either the helper is imported, OR a local function with same name
    has_helper = "volume_cap_fill" in src
    has_buggy = "int(bar_vol * max_volume_participation // 100) * 100" in src
    assert has_helper, (
        "§4 GAP CAPTURED (N6): chase_up/portfolio.py does NOT use "
        "volume_cap_fill. GREEN fix: replace `// 100 * 100` pattern."
    )
    assert not has_buggy, (
        "§4 GAP CAPTURED (N6): chase_up/portfolio.py still uses "
        "`int(bar_vol * X // 100) * 100` round-to-0 pattern."
    )


def test_uptrend_pullback_uses_volume_cap_fill_helper() -> None:
    """§4 Pin: uptrend_pullback/portfolio.py uses volume_cap_fill helper."""
    src = Path("uptrend_pullback/portfolio.py").read_text(encoding="utf-8")
    has_helper = "volume_cap_fill" in src
    has_buggy = "int(bar_vol * max_volume_participation // 100) * 100" in src
    assert has_helper, (
        "§4 GAP CAPTURED (N6): uptrend_pullback/portfolio.py does NOT use "
        "volume_cap_fill. GREEN fix: replace `// 100 * 100` pattern."
    )
    assert not has_buggy, (
        "§4 GAP CAPTURED (N6): uptrend_pullback/portfolio.py still uses "
        "`int(bar_vol * X // 100) * 100` round-to-0 pattern."
    )