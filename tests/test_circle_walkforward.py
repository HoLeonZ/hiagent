from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from circle_price_action.walkforward import walkforward_windows


def test_walkforward_windows_basic():
    windows = walkforward_windows(
        start=date(2020, 1, 1),
        end=date(2024, 1, 1),
        train_months=12,
        test_months=12,
        roll_months=6,
    )
    assert len(windows) >= 4
    for w in windows:
        assert w["train_end"] < w["test_start"]


def test_walkforward_windows_rejects_invalid_horizon():
    with pytest.raises(ValueError):
        walkforward_windows(date(2024, 1, 1), date(2024, 6, 1), 12, 12)