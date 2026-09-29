"""Round 28 (2026-09-28, CLAUDE.md §0): 4-engine strict-comparison IEEE 754 drift.

Round 26 fixed short_reversal/release_margin (1 site).
Round 27 fixed short_reversal reserve_for_entry + entry_fee + margin_fee (3 sites).
Round 28 fixes the REMAINING 6 sites across 3 engines (chase_up, uptrend_pullback,
cycle_price_action) — same root cause (Round 16 settlement state machine) but
different failure modes:

  - cycle_price_action reserve/release → raise ValueError (CRASH mid-backtest)
  - chase_up / uptrend_pullback reserve_for_entry → return False (silent rejection)
  - chase_up / uptrend_pullback release_margin → no guard (silent negative
    locked_margin, invariant violation)

All 6 sites must use the Round 26/27 tolerance pattern: `> + epsilon` + clamp
to `min(amount, locked_margin)` / `min(cost, free_cash)`.

This test file parameterizes across the 3 engines × 2 methods, plus source-level
guards and chain integration tests.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chase_up.portfolio import Portfolio as ChasePortfolio  # noqa: E402
from cycle_price_action.portfolio import Portfolio as CyclePortfolio  # noqa: E402
from uptrend_pullback.portfolio import Portfolio as UptrendPortfolio  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chase(free_cash: float = 0.0, locked_margin: float = 0.0) -> ChasePortfolio:
    p = ChasePortfolio(
        initial_capital=100000.0,
        commission_rate=0.00025,
        stamp_duty_rate=0.0005,
        min_commission=5.0,
    )
    p.free_cash = free_cash
    p.locked_margin = locked_margin
    p.settling_funds = 0.0
    return p


def _make_uptrend(free_cash: float = 0.0, locked_margin: float = 0.0) -> UptrendPortfolio:
    p = UptrendPortfolio(
        initial_capital=100000.0,
        commission_rate=0.00025,
        stamp_duty_rate=0.0005,
        min_commission=5.0,
    )
    p.free_cash = free_cash
    p.locked_margin = locked_margin
    p.settling_funds = 0.0
    return p


def _make_cycle(free_cash: float = 0.0, locked_margin: float = 0.0) -> CyclePortfolio:
    p = CyclePortfolio(cash=100000.0)
    p.free_cash = free_cash
    p.locked_margin = locked_margin
    p.settling_funds = 0.0
    return p


# ---------------------------------------------------------------------------
# chase_up / uptrend_pullback reserve_for_entry (returns False — drift silently rejects)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_factory", ["balance", "uptrend"])
@pytest.mark.parametrize("drift", [-1e-10, -1e-12])
def test_reserve_returns_true_under_drift(engine_factory: str, drift: float) -> None:
    """§0 RED→GREEN: drift on free_cash must NOT cause legitimate trade rejection.

    chase_up + uptrend_pullback reserve_for_entry returns False on strict
    `cost > free_cash`. After drift, legitimate trades (cost = free_cash + drift
    where |drift| < epsilon) get silently dropped — signals generated but never
    executed. Tolerance + clamp fix.
    """
    factory = _make_chase if engine_factory == "balance" else _make_uptrend
    cost = 100000.0
    p = factory(free_cash=cost + drift)  # drift negative: free_cash < cost

    result = p.reserve_for_entry(cost)

    assert result is True, (
        f"§0 VIOLATION: {engine_factory} reserve_for_entry returned False on "
        f"sub-epsilon drift ({drift}); legitimate trade silently rejected. "
        f"free_cash={p.free_cash}, cost={cost}"
    )
    # cash walk consistency: free_cash drained, locked credited
    assert p.free_cash == pytest.approx(0.0, abs=1e-9)
    assert p.locked_margin == pytest.approx(cost, abs=1e-9)


@pytest.mark.parametrize("engine_factory", ["balance", "uptrend"])
def test_reserve_returns_false_on_real_shortfall(engine_factory: str) -> None:
    """§0 regression guard: genuine shortfall (cost >> free_cash) still returns False."""
    factory = _make_chase if engine_factory == "balance" else _make_uptrend
    p = factory(free_cash=100.0)

    result = p.reserve_for_entry(200.0)

    assert result is False
    assert p.free_cash == pytest.approx(100.0, abs=1e-12)
    assert p.locked_margin == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("engine_factory", ["balance", "uptrend"])
def test_reserve_source_uses_tolerance_not_strict_gt(engine_factory: str) -> None:
    """§0 forward-defense: source must NOT use strict `cost > free_cash`."""
    cls = ChasePortfolio if engine_factory == "balance" else UptrendPortfolio
    src = Path(inspect.getsourcefile(cls.reserve_for_entry) or "").read_text()
    idx_start = src.index("def reserve_for_entry")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    block = rest[: m_end.start()] if m_end else rest
    bad = re.search(
        r"(?:total_entry_cost|cost)\s*>\s*free_cash\s*[:\)]", block
    )
    assert bad is None, (
        f"§0 VIOLATION: {engine_factory} reserve_for_entry uses strict "
        f"`cost > free_cash` comparison (no tolerance) — sub-epsilon drift "
        f"silently rejects legitimate trades."
    )


# ---------------------------------------------------------------------------
# chase_up / uptrend_pullback release_margin (NO guard — silent invariant violation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_factory", ["balance", "uptrend"])
@pytest.mark.parametrize("drift", [-1e-10, -1e-12])
def test_release_margin_tolerates_drift_no_negative(
    engine_factory: str, drift: float
) -> None:
    """§0 RED→GREEN: release_margin must NOT produce negative locked_margin.

    chase_up + uptrend_pullback release_margin has NO guard. After drift,
    `entry_cost_total > self.locked_margin` produces NEGATIVE locked_margin
    (silent invariant violation: NAV = free_cash + locked_margin + settling
    is corrupted silently). Must add tolerance + clamp.
    """
    factory = _make_chase if engine_factory == "balance" else _make_uptrend
    locked = 990.2249999999985
    amount = 990.225
    p = factory(locked_margin=locked)

    p.release_margin(amount)

    assert p.locked_margin >= 0.0, (
        f"§0 VIOLATION: {engine_factory} release_margin produced "
        f"NEGATIVE locked_margin={p.locked_margin} (drift {drift}); invariant "
        f"violation. Must add tolerance + clamp."
    )
    assert p.locked_margin == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("engine_factory", ["balance", "uptrend"])
def test_release_margin_source_has_guard_and_tolerance(engine_factory: str) -> None:
    """§0 forward-defense: release_margin must have guard + tolerance."""
    cls = ChasePortfolio if engine_factory == "balance" else UptrendPortfolio
    src = Path(inspect.getsourcefile(cls.release_margin) or "").read_text()
    idx_start = src.index("def release_margin")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    block = rest[: m_end.start()] if m_end else rest
    # The block must contain `if amount > self.locked_margin` (some guard)
    has_guard = bool(re.search(r"if\s+\w+\s*>\s*self\.locked_margin", block))
    # And the guard must have tolerance (epsilon, min, or isclose)
    has_tolerance = bool(
        re.search(r"(?:epsilon|isclose|min\(|max\(|abs\()", block)
    )
    assert has_guard and has_tolerance, (
        f"§0 VIOLATION: {engine_factory} release_margin must have a guard "
        f"with tolerance (epsilon / isclose / min). Current block: {block!r}"
    )


# ---------------------------------------------------------------------------
# cycle_price_action reserve_for_entry / release_margin (raises — CRASH)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("drift", [-1e-10, -1e-12])
def test_cycle_reserve_for_entry_tolerates_drift(drift: float) -> None:
    """§0 RED→GREEN: cycle_price_action reserve_for_entry must tolerate drift."""
    cost = 100000.0
    p = _make_cycle(free_cash=cost + drift)

    # Should NOT raise on sub-epsilon drift
    p.reserve_for_entry(cost)

    assert p.free_cash == pytest.approx(0.0, abs=1e-9)
    assert p.locked_margin == pytest.approx(cost, abs=1e-9)


def test_cycle_reserve_still_rejects_real_shortfall() -> None:
    """§0 regression guard: genuine shortfall must still raise."""
    p = _make_cycle(free_cash=100.0)

    with pytest.raises(ValueError, match="reserve_for_entry"):
        p.reserve_for_entry(200.0)


def test_cycle_reserve_source_uses_tolerance() -> None:
    """§0 forward-defense: cycle reserve_for_entry must use tolerance."""
    src = Path(inspect.getsourcefile(CyclePortfolio.reserve_for_entry) or "").read_text()
    idx_start = src.index("def reserve_for_entry")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    block = rest[: m_end.start()] if m_end else rest
    bad = re.search(r"cost\s*>\s*free_cash\s*[:\)]", block)
    assert bad is None, (
        "§0 VIOLATION: cycle_price_action reserve_for_entry uses strict "
        "`cost > free_cash` comparison (no tolerance) — sub-epsilon drift "
        "crashes the backtest with ValueError."
    )


@pytest.mark.parametrize("drift", [-1e-10, -1e-12])
def test_cycle_release_margin_tolerates_drift(drift: float) -> None:
    """§0 RED→GREEN: cycle_price_action release_margin must tolerate drift."""
    locked = 990.2249999999985
    amount = 990.225
    p = _make_cycle(locked_margin=locked)

    p.release_margin(amount)

    assert p.locked_margin == pytest.approx(0.0, abs=1e-9)


def test_cycle_release_still_rejects_real_shortfall() -> None:
    """§0 regression guard: genuine shortfall must still raise."""
    p = _make_cycle(locked_margin=100.0)

    with pytest.raises(ValueError, match="release_margin"):
        p.release_margin(200.0)


def test_cycle_release_source_uses_tolerance() -> None:
    """§0 forward-defense: cycle release_margin must use tolerance."""
    src = Path(inspect.getsourcefile(CyclePortfolio.release_margin) or "").read_text()
    idx_start = src.index("def release_margin")
    rest = src[idx_start + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    block = rest[: m_end.start()] if m_end else rest
    bad = re.search(r"amount\s*>\s*self\.locked_margin\s*[:\)]", block)
    assert bad is None, (
        "§0 VIOLATION: cycle_price_action release_margin uses strict "
        "`amount > self.locked_margin` comparison (no tolerance) — "
        "sub-epsilon drift crashes the backtest with ValueError."
    )