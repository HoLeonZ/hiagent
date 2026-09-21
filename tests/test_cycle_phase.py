"""Tests for cycle.py Fibonacci phase scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cycle_price_action.cycle import phase_score


def test_phase_score_constant_zero_when_length_below_max_period():
    """phase_score returns 0.0 for any series shorter than 21 bars (no leakage)."""
    s = pd.Series(pd.date_range("2024-01-01", periods=10, freq="B"))
    result = phase_score(s)
    assert (result == 0.0).all()


def test_phase_score_deterministic_for_same_input():
    s = pd.Series(pd.date_range("2024-01-01", periods=100, freq="B"))
    a = phase_score(s).to_numpy()
    b = phase_score(s).to_numpy()
    np.testing.assert_array_equal(a, b)


def test_phase_score_bounded_in_minus_one_one():
    s = pd.Series(pd.date_range("2024-01-01", periods=200, freq="B"))
    out = phase_score(s)
    assert out.between(-1.0, 1.0).all()


def test_phase_score_accepts_custom_periods():
    s = pd.Series(pd.date_range("2024-01-01", periods=50, freq="B"))
    a = phase_score(s, periods=[3, 5])
    b = phase_score(s, periods=[3])
    assert not a.equals(b)
