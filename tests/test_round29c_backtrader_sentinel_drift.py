"""Round 29c (2026-09-28, CLAUDE.md §0): backtrader verify engine sentinel drift.

`chase_up/backtrader_engine.py` and `uptrend_pullback/backtrader_engine.py`
use a backtrader-based verify pipeline after Phase 1. Two STRICT comparisons
on cumulative floats cause drift-related misbehavior:

A. Sentinel check `exit_px_bt == entry_price` (line 272 / 328)
   - Detects "backtrader did NOT actually execute the order"
   - Drift on either side (broker fill price differs by 1e-10) flips to False
   - Falls through to WRONG branch: `net_pnl_bt = 0.0` instead of phase1_pnl
   - equity_curve receives phantom PnL = 0, loses phase1_pnl contribution

B. Gate check `equity_delta != 0.0` (line 319 / 372)
   - Decides whether to apply Phase-2 correction
   - equity_delta accumulates `+= net_pnl_bt - float(t.net_pnl)` across many trades
   - Sub-epsilon cancellation makes equity_delta == 0.0 even when per-bar
     corrections are non-zero
   - Phase-2 correction silently skipped — equity_p2 = equity_p1 (un-corrected)

Both checks MUST use absolute tolerance:
  - `abs(exit_px_bt - entry_price) < epsilon`
  - `abs(equity_delta) > epsilon`  (or non-empty `deltas_by_exit` check)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(file_path: str) -> str:
    return Path(file_path).read_text()


# ---------------------------------------------------------------------------
# Sentinel: exit_px_bt == entry_price must use tolerance
# ---------------------------------------------------------------------------


CHASE_ENGINE = ROOT / "chase_up" / "backtrader_engine.py"
UPTREND_ENGINE = ROOT / "uptrend_pullback" / "backtrader_engine.py"


@pytest.mark.parametrize("engine_path", [CHASE_ENGINE, UPTREND_ENGINE])
def test_sentinel_exit_px_bt_uses_tolerance(engine_path: Path) -> None:
    """§0 RED→GREEN: sentinel must use abs(...) < epsilon, not strict ==."""
    src = _read(str(engine_path))
    has_tolerance = bool(re.search(
        r"abs\s*\(\s*exit_px_bt\s*-\s*entry_price\s*\)\s*<\s*(?:epsilon|1e-9)",
        src,
    ))
    assert has_tolerance, (
        f"§0 VIOLATION: {engine_path.name} uses STRICT `exit_px_bt == entry_price` "
        f"sentinel — sub-epsilon drift on broker fill price misclassifies "
        f"unfilled orders as filled, generating phantom PnL."
    )


@pytest.mark.parametrize("engine_path", [CHASE_ENGINE, UPTREND_ENGINE])
def test_sentinel_exit_px_bt_no_strict_eq(engine_path: Path) -> None:
    """§0 source guard: forbid STRICT `exit_px_bt == entry_price`."""
    src = _read(str(engine_path))
    # Find the sentinel check; must NOT be a strict equality
    bad = re.search(
        r"exit_px_bt\s*==\s*entry_price\s*(?!.*abs\()",
        src,
    )
    assert bad is None, (
        f"§0 VIOLATION: {engine_path.name} has STRICT `exit_px_bt == entry_price` "
        f"sentinel without abs() tolerance. Drift on either side misroutes "
        f"to wrong branch."
    )


# ---------------------------------------------------------------------------
# Gate: equity_delta != 0.0 must use tolerance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_path", [CHASE_ENGINE, UPTREND_ENGINE])
def test_equity_delta_gate_uses_tolerance(engine_path: Path) -> None:
    """§0 RED→GREEN: equity_delta gate must use abs(...) > epsilon."""
    src = _read(str(engine_path))
    has_tolerance = bool(re.search(
        r"abs\s*\(\s*equity_delta\s*\)\s*>\s*(?:epsilon|1e-9)",
        src,
    ))
    assert has_tolerance, (
        f"§0 VIOLATION: {engine_path.name} uses STRICT `equity_delta != 0.0` "
        f"gate — sub-epsilon cancellation makes accumulated delta == 0.0 "
        f"even when per-bar corrections are non-zero. Phase-2 correction "
        f"silently skipped."
    )


@pytest.mark.parametrize("engine_path", [CHASE_ENGINE, UPTREND_ENGINE])
def test_equity_delta_gate_no_strict_neq(engine_path: Path) -> None:
    """§0 source guard: forbid STRICT `equity_delta != 0.0`."""
    src = _read(str(engine_path))
    # Look for the exact strict form (must be != 0.0, not != some_var)
    bad = bool(re.search(
        r"equity_delta\s*!=\s*0\.0",
        src,
    ))
    assert not bad, (
        f"§0 VIOLATION: {engine_path.name} has STRICT `equity_delta != 0.0` "
        f"gate without tolerance. Sub-epsilon cancellation drops Phase-2 "
        f"correction."
    )


# ---------------------------------------------------------------------------
# Cross-cutting: backtrader verify engine files have BOTH fixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_path", [CHASE_ENGINE, UPTREND_ENGINE])
def test_engine_has_both_tolerance_fixes(engine_path: Path) -> None:
    """§0 forward-defense: both sentinel and gate must be tolerance-aware."""
    src = _read(str(engine_path))
    has_sentinel_fix = bool(re.search(
        r"abs\s*\(\s*exit_px_bt\s*-\s*entry_price\s*\)\s*<\s*(?:epsilon|1e-9)",
        src,
    ))
    has_gate_fix = bool(re.search(
        r"abs\s*\(\s*equity_delta\s*\)\s*>\s*(?:epsilon|1e-9)",
        src,
    ))
    assert has_sentinel_fix and has_gate_fix, (
        f"§0 VIOLATION: {engine_path.name} must have BOTH sentinel and "
        f"gate tolerance fixes (Round 29c). "
        f"sentinel={has_sentinel_fix}, gate={has_gate_fix}."
    )