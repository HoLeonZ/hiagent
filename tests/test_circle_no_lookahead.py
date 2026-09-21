"""Tests for no_lookahead.py P0–P8 helpers."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from circle_price_action.no_lookahead import (
    bars_up_to,
    group_by_stock,
    delivery_date_check,
)


def test_bars_up_to_slices_inclusive():
    df = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=5, freq="B")}
    )
    out = bars_up_to(df, date(2024, 1, 3))
    assert len(out) == 3
    assert out["date"].max().date() == date(2024, 1, 3)


def test_group_by_stock_returns_groupby_object():
    df = pd.DataFrame({
        "thscode": ["600000.SH"] * 3 + ["000001.SZ"] * 3,
        "close": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
    })
    groups = group_by_stock(df)
    out = df.groupby("thscode")["close"].rolling(2).mean()
    # sanity: groups have correct keys
    assert set(groups.groups.keys()) == {"600000.SH", "000001.SZ"}


def test_delivery_date_check_rejects_same_day():
    with pytest.raises(ValueError):
        delivery_date_check(date(2024, 6, 3), date(2024, 6, 3))


def test_delivery_date_check_rejects_past_fill():
    with pytest.raises(ValueError):
        delivery_date_check(date(2024, 6, 5), date(2024, 6, 4))


def test_delivery_date_check_passes_for_next_bar():
    delivery_date_check(date(2024, 6, 3), date(2024, 6, 4))     # no exception
