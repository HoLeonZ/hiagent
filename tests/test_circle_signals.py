from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from circle_price_action.signals import detect_k_patterns, k_line_score


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


def test_k_line_score_uses_only_decision_time_volume(monkeypatch):
    """P0 guard: k_line_score must NEVER look at row volumes from a bar at
    or after the row being scored."""
    # Build a 10-row df with stable O/H/L/C and a single spike in volume at row 9.
    rows = [(10.0, 10.4, 9.8, 10.2, 1.0)] * 9
    rows.append((10.0, 10.4, 9.8, 10.2, 9.0))   # 9x volume spike at last bar
    df = _df(rows)
    patterns = detect_k_patterns(df)
    # Score only rows 0..8 — none of them should see the spike's volume.
    scored = k_line_score(df, patterns).iloc[:9]
    # Without the spike, the volume-confluence weight is 0 for every bar.
    assert (scored <= 1.0).all()
