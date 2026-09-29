"""Round 26 (2026-09-28, CLAUDE.md §0): release_margin must tolerate IEEE 754 float drift.

ROOT CAUSE
==========
`replay_strategy_v3.release_margin` uses strict `amount > self.locked_margin`
comparison. After hundreds of `+= cost` / `-= amount` roundtrips across many
trades, IEEE 754 double-precision arithmetic accumulates a tiny negative drift
on `locked_margin` (e.g. 990.2249999999985 vs expected 990.225).

Production reproduction: `tests/test_engine_v3.py::test_high_cagr_preset_profitable`
on v35_agg_pctchg_04_09 (full 12-month window, real DuckDB):
    ValueError: release_margin: amount=990.225 > locked_margin=990.2249999999985

This is a §0 Pessimistic Default violation — entire backtest crashes mid-run
instead of gracefully releasing the (effectively) full locked amount.

FIX: replace strict `>` with `math.isclose`-style tolerance (epsilon = 1e-9),
and clamp the actual release to `min(amount, locked_margin)` so cash walk stays
correct (no over-release).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.replay_strategy_v3 import Phase3V3Strategy  # noqa: E402


# ---------------------------------------------------------------------------
# Regression: release_margin must not raise on sub-epsilon drift
# ---------------------------------------------------------------------------


def _make_strategy_with_locked(locked_margin: float, amount: float) -> Phase3V3Strategy:
    """Build a bare Phase3V3Strategy with locked_margin set to a given value."""
    cerebro_like = type(
        "C", (), {"broker": type("B", (), {"getcash": staticmethod(lambda: 0.0)})()}
    )
    strat = Phase3V3Strategy.__new__(Phase3V3Strategy)
    # Skip __init__; directly set cash pools
    strat.free_cash = 0.0
    strat.locked_margin = locked_margin
    strat.settling_funds = 0.0
    return strat


def test_release_margin_tolerates_subepsilon_drift() -> None:
    """§0 RED→GREEN: release_margin must accept amount=990.225 vs locked=990.2249999999985.

    Real production drift from hundreds of trade cycles. Without tolerance,
    the strategy crashes mid-backtest with ValueError.
    """
    # Real drift from test_high_cagr_preset_profitable failure:
    locked = 990.2249999999985
    amount = 990.225

    strat = _make_strategy_with_locked(locked_margin=locked, amount=amount)

    # Should NOT raise
    strat.release_margin(amount)

    # And cash walk should be consistent: locked drained, free credited
    assert strat.locked_margin == pytest.approx(0.0, abs=1e-9), (
        f"locked_margin should be drained to ~0 (drift absorbed), got {strat.locked_margin!r}"
    )
    assert strat.free_cash == pytest.approx(amount, abs=1e-9), (
        f"free_cash should be credited with release amount, got {strat.free_cash!r}"
    )


def test_release_margin_still_rejects_real_shortfall() -> None:
    """§0 regression guard: real shortfall (not float drift) must still raise."""
    locked = 100.0
    amount = 200.0  # genuinely trying to release more than locked

    strat = _make_strategy_with_locked(locked_margin=locked, amount=amount)

    with pytest.raises(ValueError, match="release_margin"):
        strat.release_margin(amount)


def test_release_margin_exact_match_still_works() -> None:
    """§0 regression guard: exact equality path must still work (back-compat)."""
    locked = 990.225
    amount = 990.225  # exact

    strat = _make_strategy_with_locked(locked_margin=locked, amount=amount)

    strat.release_margin(amount)
    assert strat.locked_margin == pytest.approx(0.0, abs=1e-12)
    assert strat.free_cash == pytest.approx(990.225, abs=1e-12)


# ---------------------------------------------------------------------------
# Source-level guard: production hot path must use tolerance
# ---------------------------------------------------------------------------


def test_release_margin_source_uses_tolerance_not_strict_gt() -> None:
    """§0 forward-defense: source must NOT use strict `amount > locked` (drift crash)."""
    import re

    src = Path(Phase3V3Strategy.release_margin.__code__.co_filename).read_text()
    # Find the release_margin function block: anchor on `def release_margin` and
    # walk forward until the next top-level `def ` / `class ` / `@decorator`.
    idx_start = src.index("def release_margin")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    if m_end is None:
        block = rest
    else:
        block = rest[: m_end.start()]
    # Bad pattern: `amount > self.locked_margin` followed by `:` or `)` (no tolerance).
    # Tolerated: `amount > self.locked_margin + epsilon` (tolerance pattern).
    bad_pattern = re.search(r"amount\s*>\s*self\.locked_margin\s*[:\)]", block)
    assert bad_pattern is None, (
        "§0 VIOLATION: release_margin uses strict `amount > self.locked_margin` "
        "comparison (no tolerance) — any sub-epsilon float drift crashes the "
        "backtest with ValueError. Use tolerance pattern: "
        "`amount > self.locked_margin + epsilon` instead."
    )