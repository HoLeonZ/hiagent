"""P0–P8 no-look-ahead helpers — central enforcement for cycle_price_action."""
from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd


def bars_up_to(df: pd.DataFrame, decision_date: date) -> pd.DataFrame:
    """Return only rows with date ≤ decision_date. Defensive copy."""
    mask = pd.to_datetime(df["date"]).dt.date <= decision_date
    return df.loc[mask].copy()


def group_by_stock(df: pd.DataFrame) -> pd.core.groupby.DataFrameGroupBy:
    """P7 helper: enforce per-stock grouping for any rolling ops."""
    if "thscode" not in df.columns:
        raise ValueError("df missing 'thscode' column")
    return df.groupby("thscode")


def delivery_date_check(decision_date: date, fill_date: date) -> None:
    """P3 + P1 helper: A-share T+1 means fill must be at least one bar after
    the decision date. Same-day and reverse-time fills rejected."""
    if fill_date <= decision_date:
        raise ValueError(
            f"fill_date {fill_date} must be strictly after decision_date {decision_date}"
        )


def assert_exit_priority(picks: list[tuple[str, float]]) -> None:
    """P5 helper: enforce 5-segment priority ordering at debug time.

    `picks` is a list of (label, price) where label ∈ {sl_open, tp_open,
    sl_intra, tp_intra, time_stop}.
    """
    order = {"sl_open": 0, "tp_open": 1, "sl_intra": 2, "tp_intra": 3, "time_stop": 4}
    indices = [order.get(label, -1) for label, _ in picks]
    if sorted(indices) != indices:
        raise ValueError(f"exit priority out of order: {picks}")
