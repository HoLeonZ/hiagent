from __future__ import annotations

import pandas as pd
import pytest

from cycle_price_action.time_windows import calendar_score


def test_calendar_score_treats_month_end_with_positive_weight():
    # Slice must span a real calendar month-end: Jan 22 – Feb 2 covers the
    # last 3 BDays of Jan AND the first 2 BDays of Feb, so calendar-anchored
    # end-of-month / turn-of-month activations land on the slice endpoints.
    dates = pd.Series(pd.date_range("2024-01-22", periods=10, freq="B"))
    out = calendar_score(dates)
    assert out.iloc[-1] > out.iloc[0]


def test_calendar_score_zero_for_neutral_dates():
    """A mid-month mid-week date should score 0."""
    dates = pd.Series(pd.date_range("2024-03-12", periods=5, freq="B"))
    out = calendar_score(dates)
    assert (out == 0.0).all()


def test_calendar_score_spring_festival_window_positive():
    """Holiday-aware: pass a fake 'holiday' date to bypass public calendar."""
    fake_holiday = pd.Timestamp("2024-02-10")
    dates = pd.Series(pd.date_range("2024-02-05", periods=15, freq="B"))
    out = calendar_score(dates, holidays={fake_holiday})
    assert out.max() > 0