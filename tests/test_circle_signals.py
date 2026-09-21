from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from circle_price_action.signals import detect_k_patterns, k_line_score, fuse_scores, entry_signal


def _df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def test_detect_engulfing_bullish():
    rows = [
        (10.0, 10.2, 9.8, 9.9, 1.0),   # bearish prior
        (9.9, 10.5, 9.7, 10.4, 1.5),   # bullish engulfing
    ]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "engulfing_bull"


def test_detect_engulfing_bearish():
    rows = [
        (10.4, 10.5, 9.9, 10.5, 1.0),   # bullish prior (op<cl)
        (10.5, 10.6, 9.8, 9.9, 1.5),    # bearish engulfing (op>cl, op>=prev_cl)
    ]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "engulfing_bear"


def test_detect_hanging_man():
    # Long lower shadow, bearish bar (cl <= op)
    rows = [(10.0, 10.05, 9.4, 9.95, 1.0)]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "hanging_man"


def test_detect_three_black_crows():
    rows = [
        (10.5, 10.6, 9.9, 10.0, 1.0),   # bearish
        (10.2, 10.3, 9.6, 9.7, 1.0),    # bearish, declining close
        (9.9, 10.0, 9.3, 9.4, 1.0),     # bearish, declining close
    ]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "three_black_crows"


def test_detect_morning_star_3bar():
    # Bar 0: tall bearish. Bar 1: doji. Bar 2: tall bullish closing above
    # bar 1's midpoint.
    rows = [
        (10.0, 10.1, 8.9, 9.0, 1.0),    # bearish, body=1.0
        (9.5, 9.7, 9.4, 9.52, 1.0),     # doji (body=0.02, range=0.3, ratio=0.067)
        (9.6, 10.6, 9.5, 10.5, 1.0),    # bullish, close above midpoint(9.5,9.52)=9.51
    ]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "morning_star"


def test_detect_hammer():
    rows = [(10.0, 10.1, 9.5, 10.05, 1.0)]   # long lower shadow
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "hammer"


def test_detect_doji_returns_doji_for_tiny_body():
    rows = [(10.0, 10.5, 9.5, 10.05, 1.0)]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "doji"


def test_detect_three_white_soldiers():
    rows = [
        (10.0, 10.4, 10.0, 10.3, 1.0),
        (10.2, 10.6, 10.2, 10.5, 1.0),
        (10.4, 10.9, 10.4, 10.8, 1.0),
    ]
    out = detect_k_patterns(_df(rows))
    assert out.iloc[-1] == "three_white_soldiers"


def test_k_line_score_handles_no_pattern_gracefully():
    rows = [(10.0, 10.4, 9.8, 10.2, 1.0)] * 3
    out = k_line_score(_df(rows), detect_k_patterns(_df(rows)))
    assert out.between(-0.2, 2.5).all()


def test_k_line_score_uses_only_decision_time_volume():
    """P0 guard: k_line_score must NEVER look at row volumes from a bar at
    or after the row being scored.

    Strengthened: places a 9.0 spike at row 3 (in P0's window [3..7] but
    NOT in leaky's window [4..8]) and a moderate 3.0 volume at row 8
    (above the 1.5×1.0 baseline but below the inflated 1.5×2.6 spike-aware
    threshold). With correct P0 logic, row 8's ma5v includes the spike
    so volume-confluence correctly FAILS (scored[8]=0.5). A leaky
    implementation that omits shift(1) would pull the spike into row 8's
    ma5v via [4..8] = mean(1,1,1,1,3) = 1.4 and falsely fire volume
    confluence (scored[8]=1.0).
    """
    base = (10.0, 10.4, 9.8, 10.2, 1.0)
    rows = [base] * 9
    rows[3] = (10.0, 10.4, 9.8, 10.2, 9.0)   # spike inside P0's window
    rows[8] = (10.0, 10.4, 9.8, 10.2, 3.0)   # moderate vol at decision bar
    df = _df(rows)
    patterns = detect_k_patterns(df)
    scored = k_line_score(df, patterns)
    # P0-correct: scored[8] = 0.5 (no pattern + confluence only, no vol)
    # Leaky:      scored[8] = 1.0 (no pattern + confluence + vol) — caught by assertion
    assert scored.iloc[8] == 0.5


def test_fuse_scores_weighted_sum():
    a = pd.Series([1.0, 0.5, 0.0])
    b = pd.Series([0.0, 0.5, 1.0])
    c = pd.Series([0.0, 0.0, 1.0])
    out = fuse_scores(a, b, c)
    expected = a + 0.7 * b + 0.5 * c
    pd.testing.assert_series_equal(out, expected, check_names=False)


def test_entry_signal_requires_threshold():
    kline = pd.Series([1.0, 1.0, 1.5])
    cycle = pd.Series([0.0, 1.0, 1.0])
    calendar = pd.Series([0.0, 0.0, 0.0])
    sig = entry_signal(kline, cycle, calendar)
    # Bar 0: total=1.0 < 2.0 → False
    # Bar 1: total=1.7 (kline 1.0 + 0.7*1.0) → False
    # Bar 2: total=2.2 + has kline ≥ 1.0 → True
    assert sig.tolist() == [False, False, True]


def test_entry_signal_requires_at_least_one_dimension_above_min():
    kline = pd.Series([0.0, 0.0])
    cycle = pd.Series([3.0, 1.0])    # bar 0: huge cycle, but kline=0 — still gated
    calendar = pd.Series([0.0, 0.0])
    sig = entry_signal(kline, cycle, calendar)
    # total_score bar 0 = 2.1 but min_dim check fails → False
    # total_score bar 1 = 0.7 < threshold → False
    assert sig.tolist() == [False, False]
