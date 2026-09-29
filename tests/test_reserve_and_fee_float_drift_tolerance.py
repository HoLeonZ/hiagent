"""Round 27 (2026-09-28, CLAUDE.md §0): reserve_for_entry / entry_fee / margin_fee
must tolerate IEEE 754 float drift on free_cash.

ROOT CAUSE (Round 26 extension)
===============================
Round 26 (2026-09-28) fixed `release_margin` to tolerate sub-epsilon drift on
`locked_margin`. Same root cause applies to free_cash — after hundreds of
reserve/release roundtrips, free_cash accumulates tiny negative bias. There are
THREE remaining strict-comparison guards in `replay_strategy_v3.py` that crash
mid-backtest with ValueError when free_cash drifts sub-epsilon:

  - Line 265: `if cost > free_cash: raise ValueError`           (reserve_for_entry)
  - Line 483: `if entry_fee > self.free_cash: raise ValueError`  (per-trade entry fee)
  - Line 623: `if fee > self.free_cash: raise ValueError`        (daily margin fee)

These three guards are sibling bugs to Round 26 release_margin. The §0
Pessimistic Default demand is the same: the backtest must complete even if
internal cash state has accumulated sub-epsilon drift, while genuine
shortfalls (cost > free_cash by more than epsilon) must still raise.

FIX: extend Round 26 tolerance pattern (epsilon=1e-9) to all three sites,
clamping the actual debit to `min(cost, free_cash)` for the reserve path
(mirrors `min(amount, locked_margin)` for release).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.replay_strategy_v3 import Phase3V3Strategy  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _make_strategy(free_cash: float, locked_margin: float = 0.0) -> Phase3V3Strategy:
    """Build a bare Phase3V3Strategy with given cash pool values."""
    cerebro_like = type(
        "C", (), {"broker": type("B", (), {"getcash": staticmethod(lambda: 0.0)})()}
    )
    strat = Phase3V3Strategy.__new__(Phase3V3Strategy)
    strat.free_cash = free_cash
    strat.locked_margin = locked_margin
    strat.settling_funds = 0.0
    return strat


# ---------------------------------------------------------------------------
# Site 1: reserve_for_entry (line 265)
# ---------------------------------------------------------------------------


def test_reserve_for_entry_tolerates_subepsilon_drift() -> None:
    """§0 RED→GREEN: reserve_for_entry must accept cost=100000 vs free_cash=99999.9999999999."""
    # Real production drift: free_cash drifts sub-epsilon after many round-trips.
    free_cash = 99999.9999999999
    cost = 100000.0

    strat = _make_strategy(free_cash=free_cash)

    # Should NOT raise (drift is sub-epsilon)
    strat.reserve_for_entry(cost)

    # Cash walk consistency: free_cash drained, locked credited
    assert strat.free_cash == pytest.approx(0.0, abs=1e-9)
    assert strat.locked_margin == pytest.approx(cost, abs=1e-9)


def test_reserve_for_entry_still_rejects_real_shortfall() -> None:
    """§0 regression guard: genuine shortfall (cost >> free_cash) must still raise."""
    free_cash = 100.0
    cost = 200.0  # genuinely insufficient

    strat = _make_strategy(free_cash=free_cash)

    with pytest.raises(ValueError, match="reserve_for_entry"):
        strat.reserve_for_entry(cost)


def test_reserve_for_entry_source_uses_tolerance_not_strict_gt() -> None:
    """§0 forward-defense: source must NOT use strict `cost > free_cash` (drift crash)."""
    import re

    src = Path(Phase3V3Strategy.reserve_for_entry.__code__.co_filename).read_text()
    idx_start = src.index("def reserve_for_entry")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    block = rest[: m_end.start()] if m_end else rest
    # Strict comparison: `cost > free_cash` followed by `:` or `)`.
    # Tolerated: `cost > free_cash + epsilon`.
    bad = re.search(r"cost\s*>\s*free_cash\s*[:\)]", block)
    assert bad is None, (
        "§0 VIOLATION: reserve_for_entry uses strict `cost > free_cash` "
        "comparison (no tolerance) — sub-epsilon free_cash drift crashes the "
        "backtest with ValueError. Use tolerance pattern: "
        "`cost > free_cash + epsilon` instead."
    )


# ---------------------------------------------------------------------------
# Site 2: entry_fee > free_cash (line 483)
# ---------------------------------------------------------------------------


def test_entry_fee_guard_source_uses_tolerance_not_strict_gt() -> None:
    """§0 forward-defense: per-trade entry_fee guard must use tolerance.

    The actual raise happens deep inside `next()`; we don't reproduce the full
    flow here. Instead, pin the source-level invariant: the `entry_fee >
    self.free_cash` comparison must use tolerance, mirroring Round 26 release_margin.
    """
    import re

    src = Path(Phase3V3Strategy.__init__.__code__.co_filename).read_text()
    # Locate the literal `entry_fee > self.free_cash` line. Round 27 must
    # have changed it to `entry_fee > self.free_cash + epsilon`.
    bad_pattern = re.search(
        r"entry_fee\s*>\s*self\.free_cash\s*[:\)]", src
    )
    assert bad_pattern is None, (
        "§0 VIOLATION: entry_fee guard uses strict `entry_fee > self.free_cash` "
        "comparison (no tolerance) — sub-epsilon free_cash drift crashes the "
        "backtest mid-entry with ValueError. Use tolerance pattern: "
        "`entry_fee > self.free_cash + epsilon` instead."
    )


# ---------------------------------------------------------------------------
# Site 3: margin fee > free_cash (line 623)
# ---------------------------------------------------------------------------


def test_margin_fee_guard_source_uses_tolerance_not_strict_gt() -> None:
    """§0 forward-defense: daily margin fee guard must use tolerance."""
    import re

    src = Path(Phase3V3Strategy.__init__.__code__.co_filename).read_text()
    # Locate the literal `fee > self.free_cash` line. Round 27 must
    # have changed it to `fee > self.free_cash + epsilon`.
    bad_pattern = re.search(
        r"\bfee\s*>\s*self\.free_cash\s*[:\)]", src
    )
    assert bad_pattern is None, (
        "§0 VIOLATION: margin fee guard uses strict `fee > self.free_cash` "
        "comparison (no tolerance) — sub-epsilon free_cash drift crashes the "
        "backtest mid-day with ValueError. Use tolerance pattern: "
        "`fee > self.free_cash + epsilon` instead."
    )


# ---------------------------------------------------------------------------
# Drift-simulation: full chain (entry_fee → release_margin → next margin fee)
# ---------------------------------------------------------------------------


def test_full_chain_no_crash_with_drift() -> None:
    """§0 integration: full chain must survive drift on free_cash + locked_margin.

    Simulates the actual crash scenario where each step drifts sub-epsilon.
    After release_margin (Round 26) credits back the clamped amount, then
    reserve_for_entry must also tolerate the now-drifted free_cash. The
    genuine-shortfall rejection is covered separately by
    `test_reserve_for_entry_still_rejects_real_shortfall`.
    """
    # Drift-loaded state (sub-epsilon on both pools)
    initial_free = 99999.9999999999
    initial_locked = 990.2249999999985

    strat = _make_strategy(free_cash=initial_free, locked_margin=initial_locked)

    # Site 1 (release_margin, Round 26 already fixed): expect no crash
    # Round 26 clamps actual_release to min(amount, locked_margin).
    strat.release_margin(990.225)
    assert strat.locked_margin == pytest.approx(0.0, abs=1e-9)
    # free_cash is credited with the clamped release amount.
    assert strat.free_cash == pytest.approx(initial_free + initial_locked, abs=1e-9)

    # Site 2 (reserve_for_entry, Round 27 fix): expect no crash on drift.
    # We reserve 100000.0 vs free_cash=100990.22... (which is > cost, no shortfall).
    strat.reserve_for_entry(100000.0)
    assert strat.free_cash == pytest.approx(
        initial_free + initial_locked - 100000.0, abs=1e-9
    )
    assert strat.locked_margin == pytest.approx(100000.0, abs=1e-9)