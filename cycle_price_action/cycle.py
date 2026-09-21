"""Fibonacci cycle phase scoring — pure function, no future data.

Per-cycle contribution: weight_p × sin(2π × t / p)
where t is bar index (0, 1, …, n-1) relative to start of input series.
Zero-padded until t ≥ max(periods) so that no phase signal is computed before
the longest cycle has had time to complete (anti-leakage).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_PERIODS = (3, 5, 8, 13, 21)


def phase_score(
    series: pd.Series,
    periods: list[int] | tuple[int, ...] | None = None,
) -> pd.Series:
    if periods is None:
        periods = DEFAULT_PERIODS
    periods = sorted(periods)
    if any(p <= 0 for p in periods):
        raise ValueError("periods must be positive ints")

    n = len(series)
    max_p = max(periods)
    out = np.zeros(n, dtype=float)
    if n < max_p:
        return pd.Series(out, index=series.index)

    weights = np.array([1.0 / p for p in periods])
    weights = weights / weights.sum()

    t = np.arange(n)
    weighted = np.zeros(n)
    for w, p in zip(weights, periods):
        weighted += w * np.sin(2 * np.pi * t / p)
    weighted /= max(len(periods), 1)
    weighted = np.clip(weighted, -1.0, 1.0)

    out[:] = weighted
    return pd.Series(out, index=series.index)
