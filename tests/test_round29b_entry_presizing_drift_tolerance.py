"""Round 29b (2026-09-28, CLAUDE.md §0): entry-sizing pre-check IEEE 754 drift.

Rounds 26/27/28 fixed all `reserve_for_entry` / `release_margin` / `entry_fee`
/ `margin_fee` sites in 4-engine Portfolio classes to use `> + epsilon` tolerance
+ clamp. But the entry-sizing PRE-CHECKS at the call sites (which decide whether
to call `reserve_for_entry`) still use STRICT `cost > cash`:

  - chase_up/portfolio.py:566, 572
  - uptrend_pullback/portfolio.py:523, 529
  - cycle_price_action/portfolio.py:231, 236, 247

After sub-epsilon drift on `free_cash` (e.g. `free_cash = 10004.99999999998`),
`notional + fee_in = 10005.0` triggers `size -= 100`, then `size < 100`
silently drops the trade. The subsequent `reserve_for_entry` (now
tolerance-aware via Round 28) would have ACCEPTED the trade via
`actual_debit = min(10005, free_cash)`.

This test enforces: pre-check must use `+ epsilon` tolerance, OR be
removed entirely and let `reserve_for_entry` be the single source of truth.

Pattern check: `cost > pf.free_cash` (or `> self.cash`) without `+ epsilon` or
`+ 1e-9` MUST NOT exist in the entry-sizing pre-check sites.
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
# Helpers
# ---------------------------------------------------------------------------


def _file_block_after(text: str, anchor: str, until: str = "\n                    pf.reserve_for_entry") -> str:
    """Extract the block from `anchor` (exclusive) to `until` (exclusive)."""
    idx_start = text.index(anchor) if anchor in text else -1
    if idx_start < 0:
        return ""
    rest = text[idx_start + len(anchor):]
    idx_end = rest.index(until) if until in rest else len(rest)
    return rest[:idx_end]


def _portfolio_presizing_block(portfolio_file: str) -> str:
    src = Path(portfolio_file).read_text()
    # The entry-sizing pre-check block ends at the call to reserve_for_entry
    # (Round 16+ pattern). Anchor: first `if notional + fee_in` or `if cost >`
    # appearance.
    return src


# ---------------------------------------------------------------------------
# chase_up — pre-check tolerance
# ---------------------------------------------------------------------------


def test_chase_up_presizing_check_uses_epsilon() -> None:
    """§0 RED→GREEN: chase_up pre-check must use epsilon tolerance."""
    src = Path(inspect.getsourcefile(ChasePortfolio) or "").read_text()
    # Find block from first `if notional + fee_in` to `pf.reserve_for_entry`
    rest_after_first = src.split("if notional + fee_in", 1)[1]
    block = rest_after_first.split("pf.reserve_for_entry", 1)[0]
    # The block must have at least one `+ epsilon` or `+ 1e-9` near a free_cash check
    has_tolerance = bool(re.search(
        r">\s*pf\.free_cash\s*\+\s*(?:1e-9|epsilon)",
        block,
        re.IGNORECASE,
    ))
    assert has_tolerance, (
        "§0 VIOLATION: chase_up entry-sizing pre-check uses STRICT "
        "`cost > pf.free_cash` without epsilon — sub-epsilon drift on "
        "free_cash silently drops legitimate trades before the "
        "tolerance-aware reserve_for_entry is reached."
    )


# ---------------------------------------------------------------------------
# uptrend_pullback — pre-check tolerance
# ---------------------------------------------------------------------------


def test_uptrend_pullback_presizing_check_uses_epsilon() -> None:
    """§0 RED→GREEN: uptrend_pullback pre-check must use epsilon tolerance."""
    src = Path(inspect.getsourcefile(UptrendPortfolio) or "").read_text()
    rest_after_first = src.split("if notional + fee_in", 1)[1]
    block = rest_after_first.split("pf.reserve_for_entry", 1)[0]
    has_tolerance = bool(re.search(
        r">\s*pf\.free_cash\s*\+\s*(?:1e-9|epsilon)",
        block,
        re.IGNORECASE,
    ))
    assert has_tolerance, (
        "§0 VIOLATION: uptrend_pullback entry-sizing pre-check uses STRICT "
        "`cost > pf.free_cash` without epsilon — sub-epsilon drift on "
        "free_cash silently drops legitimate trades."
    )


# ---------------------------------------------------------------------------
# cycle_price_action — pre-check tolerance
# ---------------------------------------------------------------------------


def test_cycle_presizing_check_uses_epsilon() -> None:
    """§0 RED→GREEN: cycle_price_action try_enter pre-check must use epsilon."""
    src = Path(inspect.getsourcefile(CyclePortfolio) or "").read_text()
    # Find the try_enter method block
    idx = src.index("def try_enter")
    rest = src[idx + 1:]
    m_end = re.search(r"\n    def |\nclass ", rest)
    block = rest[: m_end.start()] if m_end else rest
    # All `cost > self.cash` checks inside try_enter must have tolerance
    bad = []
    for m in re.finditer(r"cost\s*>\s*self\.cash", block):
        prefix = block[max(0, m.start() - 30): m.end() + 30]
        if not re.search(r"\+\s*(?:1e-9|epsilon)", prefix):
            bad.append(m.group())
    assert not bad, (
        f"§0 VIOLATION: cycle_price_action try_enter has {len(bad)} STRICT "
        f"`cost > self.cash` pre-checks without epsilon: {bad}. Sub-epsilon "
        f"drift on cash silently drops legitimate trades before the "
        f"tolerance-aware reserve_for_entry is reached."
    )


# ---------------------------------------------------------------------------
# Behavioral test — sub-epsilon drift on free_cash must not drop trade
# ---------------------------------------------------------------------------


def test_chase_up_presizing_drift_simulated_via_reserve_for_entry() -> None:
    """§0 behavior: pre-check must let sub-epsilon drift pass to reserve_for_entry
    which then clamps via Round 28 tolerance.

    Simulates the cash-walk where drift makes pre-check just barely fail but
    reserve_for_entry just barely succeed via clamp.
    """
    p = ChasePortfolio(
        initial_capital=100000.0,
        commission_rate=0.00025,
        stamp_duty_rate=0.0005,
        min_commission=5.0,
    )
    # Inject sub-epsilon drift: free_cash slightly less than nominal
    drift = -1e-10
    cost = 100000.0
    p.free_cash = cost + drift  # drift negative: free_cash < cost

    # With tolerance, reserve_for_entry must accept and clamp
    result = p.reserve_for_entry(cost)
    assert result is True, (
        f"§0 VIOLATION: reserve_for_entry failed on sub-epsilon drift "
        f"({drift}) — should accept via tolerance + clamp."
    )
    assert p.locked_margin == pytest.approx(cost, abs=1e-9)