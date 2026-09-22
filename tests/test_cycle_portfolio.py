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
    # All-in sizing (CLAUDE.md §2, revised 2026-09-21): uses 100% of cash,
    # rounded down to integer lots, with a 1-lot round-down fallback when
    # commission would push cost over cash.
    state = pf.try_enter(
        thscode="600000.SH",
        price=9.87,
        entry_date=date(2024, 6, 3),
        decision_meta={"phase_score": 0.3, "k_line_score": 1.5, "calendar_score": 0.4},
    )
    assert state is not None
    assert state.shares == 100_000 // 9.87 // 100 * 100   # all-in, round down to 100s


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


def test_try_enter_volume_participation_cap_enforced_r8():
    """R8 (2026-09-21, CLAUDE.md §4): Volume Participation Limit.
    单笔最大成交量 = Bar_Volume × 0.10. 超出部分丢弃。
    cash=100_000, price=10 → 10_000 shares pre-cap. bar_volume=50_000 shares →
    cap = 50_000 × 0.10 = 5_000 shares. result.shares 必须 ≤ 5_000。
    """
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        thscode="600000.SH",
        price=10.0,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        bar_volume=50_000,  # cap = 50_000 × 0.10 = 5_000 shares
    )
    assert state is not None
    assert state.shares <= 5_000


def test_try_enter_volume_cap_backcompat_no_bar_volume():
    """R8 back-compat: 不传 bar_volume 时, 不应用 cap, 沿用 all-in 计算。
    cash=100_000, price=10 → 10_000 shares pre-cost. cost = 100_000 + 25
    commission > cash → round down 1 lot → 9_900 shares。
    """
    pf = Portfolio(cash=100_000.0)
    state = pf.try_enter(
        thscode="600000.SH",
        price=10.0,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
    )
    assert state is not None
    # 100_000 // 10 // 100 * 100 = 10_000; cost round-down 1 lot → 9_900
    assert state.shares == 9_900


def test_try_enter_volume_cap_none_nan_skipped():
    """R8 edge case: bar_volume=None 或 NaN 时, 跳过 cap。
    cash=100_000, price=10 → 10_000 shares → 9_900 (commission round-down)。
    """
    pf_none = Portfolio(cash=100_000.0)
    s1 = pf_none.try_enter(
        thscode="600000.SH", price=10.0,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        bar_volume=None,
    )
    assert s1 is not None and s1.shares == 9_900

    pf_nan = Portfolio(cash=100_000.0)
    s2 = pf_nan.try_enter(
        thscode="600000.SH", price=10.0,
        entry_date=date(2024, 6, 3),
        decision_meta={"k_line_score": 1.5},
        bar_volume=float("nan"),
    )
    assert s2 is not None and s2.shares == 9_900


# ---- V6'' (2026-09-22, CLAUDE.md §4) Intraday SL-first tiebreak ----

def test_intraday_check_gap_down_sl_first():
    """V6'': open ≤ sl_p → SL @ open (gap-down through stop)."""
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    # entry=10, tp_pct=0.06 → tp_p=10.60, sl_pct=0.05 → sl_p=9.50
    # open=9.00 ≤ sl_p=9.50 → SL @ open
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=9.00,
        high=10.50,
        low=8.80,
        close=9.10,
        tp_pct=0.06,
        sl_pct=0.05,
    )
    assert reason == "SL"
    assert fill == 9.00


def test_intraday_check_gap_up_tp_first():
    """V6'': open ≥ tp_p → TP @ open (gap-up through target)."""
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    # entry=10, tp_pct=0.06 → tp_p=10.60, sl_pct=0.05 → sl_p=9.50
    # open=11.00 ≥ tp_p=10.60 → TP @ open
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=11.00,
        high=11.50,
        low=10.50,
        close=10.80,
        tp_pct=0.06,
        sl_pct=0.05,
    )
    assert reason == "TP"
    assert fill == 11.00


def test_intraday_check_intraday_sl_only():
    """V6'': low ≤ sl_p (open 没破), high 没破 tp → SL @ sl_p."""
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    # open=10.10 (no gap), low=9.30 ≤ sl_p=9.50, high=10.40 ≤ tp_p=10.60
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10,
        high=10.40,
        low=9.30,
        close=9.80,
        tp_pct=0.06,
        sl_pct=0.05,
    )
    assert reason == "SL"
    assert fill == 9.50    # exit @ sl_p (not @ low)


def test_intraday_check_intraday_tp_only():
    """V6'': high ≥ tp_p (open 没破), low 没破 sl → TP @ tp_p."""
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    # open=10.10 (no gap), high=10.80 ≥ tp_p=10.60, low=9.80 ≥ sl_p=9.50
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10,
        high=10.80,
        low=9.80,
        close=10.70,
        tp_pct=0.06,
        sl_pct=0.05,
    )
    assert reason == "TP"
    assert fill == pytest.approx(10.60)    # exit @ tp_p (not @ high)


def test_intraday_check_sl_first_tiebreak():
    """V6'': 同 bar SL+TP 双触发 → 假设 SL 命中 (CLAUDE.md §4 worst-case)。
    open 没破, low ≤ sl_p AND high ≥ tp_p 同时发生 → SL @ sl_p。
    """
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    # open=10.10 (no gap, 但紧贴)
    # low=9.40 ≤ sl_p=9.50 (intraday stop hit)
    # high=10.70 ≥ tp_p=10.60 (intraday target hit)
    # → SL-first → exit @ sl_p
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10,
        high=10.70,
        low=9.40,
        close=10.05,
        tp_pct=0.06,
        sl_pct=0.05,
    )
    assert reason == "SL"
    assert fill == 9.50


def test_intraday_check_no_trigger_time_exit():
    """V6'': open/low/high 都不破 → time exit @ close."""
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    fill, reason = pf.try_exit_with_intraday_check(
        exit_date=date(2024, 6, 4),
        open_price=10.10,
        high=10.30,
        low=9.90,
        close=10.20,
        tp_pct=0.06,    # tp_p = 10.60
        sl_pct=0.05,    # sl_p = 9.50
    )
    assert reason == "time"
    assert fill == 10.20


def test_intraday_check_p3_no_same_day_exit():
    """V6'' + P3: exit_date == entry_date → raise ValueError."""
    pf = Portfolio(cash=100_000.0)
    pf.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"k_line_score": 1.5})
    with pytest.raises(ValueError):
        pf.try_exit_with_intraday_check(
            exit_date=date(2024, 6, 3),
            open_price=10.10,
            high=10.30,
            low=9.90,
            close=10.20,
            tp_pct=0.06,
            sl_pct=0.05,
        )
