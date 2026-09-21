"""Tests for universe.py main-board + liquidity + status filter."""
from __future__ import annotations

import pandas as pd
import pytest

from circle_price_action.universe import (
    is_main_board,
    apply_liquidity_filter,
    is_excluded_status,
)


@pytest.mark.parametrize(
    "code, expect",
    [
        ("600000.SH", True),
        ("601318.SH", True),
        ("000001.SZ", True),
        ("002415.SZ", True),  # 深圳主板历史延伸
        ("300750.SZ", False),  # 创业板
        ("688981.SH", False),  # 科创板
        ("830799.BJ", False),  # 北交所
        ("123456.SH", False),  # 非法前缀
    ],
)
def test_is_main_board(code, expect):
    assert is_main_board(code) == expect


def test_apply_liquidity_filter_drops_low_turnover():
    dates = pd.date_range("2024-06-01", periods=25, freq="B")
    rows = []
    for code, amt in [("600000.SH", 1e8), ("603000.SH", 1e6)]:
        for d in dates:
            rows.append((code, d, amt))
    df = pd.DataFrame(rows, columns=["thscode", "date", "amount"])
    out = apply_liquidity_filter(df, min_avg_turnover=5e7, lookback=20)
    assert "600000.SH" in out
    assert "603000.SH" not in out


def test_apply_liquidity_filter_default_excludes_sub_60d_ipo():
    """Recent IPOs (< 60 trading days history) must not be selected."""
    dates = pd.date_range("2024-06-01", periods=30, freq="B")
    df = pd.DataFrame(
        [("600000.SH", d, 1e8) for d in dates], columns=["thscode", "date", "amount"]
    )
    out = apply_liquidity_filter(df)
    assert "600000.SH" not in out


def test_is_excluded_status_uses_excluded_list():
    excluded = {"ST/*", "600000.SH"}
    assert is_excluded_status("600000.SH", excluded)
    assert not is_excluded_status("000001.SZ", excluded)
