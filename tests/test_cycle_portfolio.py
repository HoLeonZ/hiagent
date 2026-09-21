"""Tests for portfolio.py single-position state machine."""
from __future__ import annotations

from datetime import date

import pytest

from cycle_price_action.portfolio import Portfolio, PositionState


def test_portfolio_starts_empty():
    pf = Portfolio(cash=100_000.0)
    assert pf.position is None
    assert pf.cash == 100_000.0


def test_try_enter_respects_lot_constraint():
    pf = Portfolio(cash=100_000.0)
    # 600000.SH at 9.87 → 100 shares = 987 + fee — fits.
    state = pf.try_enter(
        thscode="600000.SH",
        price=9.87,
        entry_date=date(2024, 6, 3),
        decision_meta={"phase_score": 0.3, "k_line_score": 1.5, "calendar_score": 0.4},
    )
    assert state is not None
    assert state.shares == 10_000 // 9.87 // 100 * 100   # round down to 100s


def test_try_enter_rejected_when_already_in_position():
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 9.87, date(2024, 6, 3), {"k_line_score": 1.5})
    second = pf.try_enter("000001.SZ", 12.0, date(2024, 6, 4), {"k_line_score": 1.5})
    assert second is None


def test_try_exit_forbidden_on_entry_day_p3():
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 9.87, date(2024, 6, 3), {"k_line_score": 1.5})
    with pytest.raises(ValueError):
        pf.try_exit(date(2024, 6, 3), fill_price=10.5)
    assert pf.position is not None   # still open


def test_try_exit_after_hold_day_passes():
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 9.87, date(2024, 6, 3), {"k_line_score": 1.5})
    pf.try_exit(date(2024, 6, 4), fill_price=10.5)
    assert pf.position is None
    assert pf.cash > 100_000.0


def test_hold_days_tracks_calendar_days():
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 9.87, date(2024, 6, 3), {"k_line_score": 1.5})
    assert pf.hold_days(date(2024, 6, 5)) == 2


def test_portfolio_records_closed_trade():
    p = Portfolio(cash=1_000_000)
    state = p.try_enter("600000.SH", 10.0, date(2025, 1, 1), {"k_line_score": 1.0})
    assert state is not None
    p.try_exit(date(2025, 1, 6), 11.0)
    assert len(p.closed_trades) == 1
    rec = p.closed_trades[0]
    assert rec["thscode"] == "600000.SH"
    assert rec["exit_date"] == date(2025, 1, 6)
    assert rec["pnl"] > 0
    assert rec["hold_days"] == 5