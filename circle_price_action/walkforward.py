"""Walk-forward validation window generator for cycle_price_action."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __getitem__(self, key: str) -> date:
        return getattr(self, key)


def walkforward_windows(
    start: date,
    end: date,
    train_months: int = 12,
    test_months: int = 12,
    roll_months: int = 6,
) -> list[WalkForwardWindow]:
    if (end.year - start.year) * 12 + (end.month - start.month) < train_months + test_months:
        raise ValueError("horizon too short for train+test windows")

    windows: list[WalkForwardWindow] = []
    train_start = start
    while True:
        train_end = _add_months(train_start, train_months) - pd.tseries.offsets.BDay(1)
        test_start = _add_months(train_start, train_months)
        test_end = _add_months(test_start, test_months) - pd.tseries.offsets.BDay(1)
        if test_end.date() > end:
            break
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end.date(),
                test_start=test_start.date(),
                test_end=test_end.date(),
            )
        )
        train_start = _add_months(train_start, roll_months)
    return windows


def _add_months(d: date, n: int) -> pd.Timestamp:
    return (pd.Timestamp(d) + pd.DateOffset(months=n)).normalize()