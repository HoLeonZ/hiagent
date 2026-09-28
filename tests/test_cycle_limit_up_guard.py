"""§4 Limit-Up Guard for cycle_price_action Portfolio (Tick N3).

CLAUDE.md §3 Reality Mapping + §4 Microstructure:
- Limit-up opens (+10%) cannot be transacted (order queue locked).
- cycle_price_action Portfolio.try_enter() MUST reject limit-up opens.

Pre-fix: 0 limit-up references in cycle_price_action/ (per [[limit-up-guard-cross-engine-gap]]).
GREEN: Portfolio.try_enter rejects +10% opens when prev_close is provided.

Pattern (chase_up/portfolio.py:384-386):
    if is_limit_up(pc, o, threshold=LIMIT_UP_THRESHOLD): continue

API contract:
    try_enter(prev_close=None, ...)  # when prev_close provided, limit-up is enforced
    __init__(is_limit_up_threshold=0.095, prev_close_at_entry=None, ...)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycle_price_action.portfolio import Portfolio


# ---------------------------------------------------------------------------
# RED: cycle_price_action try_enter must reject limit-up opens
# ---------------------------------------------------------------------------


def test_cycle_try_enter_rejects_limit_up_open() -> None:
    """§4 RED→GREEN: cycle Portfolio rejects limit-up +10% open.

    Fixture: prev_close=10.0, open=11.0 (+10% exact limit-up).
    try_enter MUST return None (no position opened) and pf.position is None.

    Per [[limit-up-guard-cross-engine-gap]] + CLAUDE.md §3 Reality Mapping.
    """
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        thscode="600000.SH",
        price=11.0,  # = 10.0 × 1.10 — at limit-up
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        prev_close=10.0,
    )
    assert state is None, (
        "§4 LIMIT-UP VIOLATION: cycle_price_action Portfolio accepted "
        "+10% open (prev_close=10.0, price=11.0). Limit-up opens cannot "
        "be transacted per CLAUDE.md §3. try_enter must return None."
    )
    assert pf.position is None, (
        "§4 LIMIT-UP VIOLATION: Portfolio.position was set despite "
        "limit-up guard firing."
    )


def test_cycle_try_enter_accepts_normal_open() -> None:
    """§4 GREEN: cycle Portfolio accepts normal +5% open (sanity, no false-positive).

    Fixture: prev_close=10.0, open=10.5 (+5%) — well below 0.095 threshold.
    try_enter MUST accept entry.
    """
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        thscode="600000.SH",
        price=10.5,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        prev_close=10.0,
    )
    assert state is not None, (
        "Sanity check: cycle Portfolio rejected a normal +5% open. "
        "Limit-up guard must NOT false-positive (threshold=0.095)."
    )
    assert pf.position is not None


def test_cycle_try_enter_backcompat_no_prev_close() -> None:
    """§4 back-compat: prev_close=None → limit-up check skipped.

    Pre-fix Portfolio.try_enter has no prev_close param. After fix, callers
    that don't pass prev_close (e.g. legacy tests in test_cycle_portfolio.py)
    must still work — limit-up check is opt-in via prev_close param.
    """
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        thscode="600000.SH",
        price=11.0,  # +10% but no prev_close provided
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
    )
    # Without prev_close, the limit-up check is skipped — entry proceeds.
    assert state is not None, (
        "Back-compat regression: Portfolio rejected +10% open when "
        "prev_close was not provided. Limit-up guard is opt-in via "
        "prev_close parameter (skipped when None)."
    )


def test_cycle_try_enter_threshold_override() -> None:
    """§4 GREEN: is_limit_up_threshold can be customized per Portfolio.

    Fixture: Portfolio with threshold=0.05 (5%) — strict preset override.
    prev_close=10.0, open=10.6 (+6%) → limit-up at threshold=0.05.
    """
    pf = Portfolio(cash=100_000.0, is_limit_up_threshold=0.05)
    state = pf.try_enter(
        thscode="600000.SH",
        price=10.6,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        prev_close=10.0,
    )
    assert state is None, (
        "§4 limit-up threshold override not honored: Portfolio accepted "
        "+6% open when threshold=0.05 (custom override). is_limit_up_threshold "
        "constructor param must take effect."
    )


def test_cycle_try_enter_default_threshold_is_095() -> None:
    """§4 GREEN: default is_limit_up_threshold = 0.095 (CLAUDE.md §3 standard).

    Fixture: prev_close=10.0, open=10.94 (+9.4%) — below default threshold.
    Should accept (not yet at limit-up).
    prev_close=10.0, open=10.951 (+9.51%) — above default threshold.
    Should reject.
    """
    pf_accept = Portfolio(cash=100_000.0)
    s_accept = pf_accept.try_enter(
        thscode="600000.SH",
        price=10.94,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        prev_close=10.0,
    )
    assert s_accept is not None, (
        "Default threshold 0.095 must accept +9.4% open (below threshold)."
    )

    pf_reject = Portfolio(cash=100_000.0)
    s_reject = pf_reject.try_enter(
        thscode="600000.SH",
        price=10.951,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        prev_close=10.0,
    )
    assert s_reject is None, (
        "Default threshold 0.095 must reject +9.51% open (above threshold)."
    )