"""§0/§3 Net Field Closure for short_reversal/lookahead_trade_trace.py (Round 24).

CLAUDE.md §0 (Pessimistic Default) + §3 (Data Integrity):
  - Per-trade `net` must reflect full cash walk: entry_fee (commission + stamp)
    on SELL entry + exit_fee (commission) on BUY exit.
  - `notional_pnl` must reflect gross_pnl − entry_fee − exit_fee (NOT just
    gross_pnl − exit_fee).

Round 19 (2026-09-28) fixed the canonical formula in
`short_reversal.replay_strategy_v3._close`:
    total_fee_ratio = (comm + stamp) + comm × (price / ep)
    net = gross_pct − total_fee_ratio

The trace subclass `TraceStrategy._close` in `lookahead_trade_trace.py`
inherited the same logic but the fix was NOT propagated (Round 24 finding):
    net = gross − commission_rate         ← only one commission, no stamp
    notional_pnl = pnl − exit_fee         ← no entry_fee subtraction

Impact:
  - `traces[].net_per_share` overstated by ~0.07%/trade
    (stamp_duty_rate 0.0005 ≈ 7.5bp per share per round-trip).
  - `traces[].notional_pnl` overstated by entry_fee per trade
    (~5bp × size). For ~425 trades (v46) ≈ 21bp of overstated PnL.
  - `pre_window_pnl_contribution_pct` and `win_rate` (derived via
    `trades[].net > 0`) drift correspondingly.

This test file pins the canonical formula on the trace subclass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.lookahead_trade_trace import TraceStrategy  # noqa: E402


# ---------------------------------------------------------------------------
# Static source RED: must mirror Round 19 canonical formula
# ---------------------------------------------------------------------------


def _src() -> str:
    return Path(TraceStrategy._close.__code__.co_filename).read_text()


def test_trace_close_uses_total_fee_ratio_not_single_commission() -> None:
    """§0/§3 RED→GREEN: net must use total_fee_ratio (comm+stamp+exit comm)."""
    src = _src()
    assert "total_fee_ratio" in src, (
        "§0/§3: TraceStrategy._close must compute total_fee_ratio "
        "(commission + stamp_duty + exit commission) per Round 19 fix. "
        "Current code uses `gross - commission_rate` which only subtracts "
        "ONE commission and drops stamp_duty + exit_fee entirely."
    )
    # And the legacy single-line bug must be gone.
    assert "net = gross - self.p.commission_rate" not in src, (
        "§0/§3: legacy `net = gross - self.p.commission_rate` formula "
        "still present — drops stamp_duty on entry (5bp) and exit "
        "commission (~2.5bp). Systematically overstates per-trade net."
    )


def test_trace_close_notional_pnl_includes_entry_fee() -> None:
    """§0/§3 RED→GREEN: notional_pnl = (ep-price)×size − entry_fee − exit_fee."""
    src = _src()
    # The trace record uses `notional_pnl`. Round 24 fix must include entry_fee.
    assert "notional_pnl" in src, (
        "§0/§3: TraceStrategy must emit notional_pnl with entry_fee subtracted. "
        "Current code computes `pnl − exit_fee` only, missing entry_fee."
    )
    # Look at the calculation line that builds the value emitted under
    # "notional_pnl": variable assignment must reference entry_fee.
    # Pattern: notional_pnl = float(pnl − exit_fee − entry_fee) per Round 19 canonical.
    import re
    m = re.search(r"notional_pnl\s*=\s*float\([^)]*entry_fee[^)]*\)", src)
    assert m is not None, (
        "§0/§3: notional_pnl value must subtract entry_fee. Round 19 canonical "
        "pattern: `notional_pnl = float(pnl − exit_fee − entry_fee)`. "
        "Currently the calculation only subtracts exit_fee, overstating "
        "per-trade PnL by ~5bp (stamp_duty on SELL entry)."
    )