"""P8 + liquidity filtering tests for data_feed.load_universe_data."""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from cycle_price_action.data_feed import load_universe_data


@pytest.fixture
def temp_db(tmp_path):
    db = tmp_path / "market.duckdb"
    con = duckdb.connect(str(db))
    try:
        # v_daily 视图(项目约定的唯一数据入口,P4 防御)
        con.execute("""
            CREATE TABLE v_daily (
                thscode VARCHAR, date DATE,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                volume DOUBLE, amount DOUBLE
            )
        """)
        # 在市股:600000.SH,2025-09-21 当日有数据。
        # 需 ≥60 唯一交易日才能通过 apply_liquidity_filter 默认 lookback=60。
        dates_600 = pd.date_range("2024-09-21", "2025-09-19", freq="B")
        rows_600 = [
            ("600000.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1000.0, 1e8)
            for d in dates_600
        ]
        # 2025-09-21 是周日,不在 B 日历里;手工补一行以满足 P8 的 last_date >= end。
        rows_600.append(("600000.SH", date(2025, 9, 21), 12.0, 12.5, 11.8, 12.2, 1500.0, 1.5e8))
        con.executemany("INSERT INTO v_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows_600)
        # 已退市股:600001.SH,最后数据停在 2025-03-01(P8 应排除)
        con.execute("""
            INSERT INTO v_daily VALUES
            ('600001.SH','2024-09-21',5.0,5.5,4.8,5.2,800.0,8e7),
            ('600001.SH','2025-03-01',6.0,6.5,5.8,6.2,900.0,9e7)
        """)
        # ChiNext 股:P8 + main-board 都应排除(300xxx.SZ)
        con.execute("""
            INSERT INTO v_daily VALUES
            ('300750.SZ','2025-09-21',100.0,101.0,99.0,100.5,500.0,5e7)
        """)
    finally:
        con.close()
    return db


def test_p8_excludes_delisted(temp_db):
    end = date(2025, 9, 21)
    start = date(2025, 1, 1)
    universe = load_universe_data(str(temp_db), start, end)
    codes = set(universe.keys())
    assert "600000.SH" in codes
    assert "600001.SH" not in codes, "delisted must be excluded by P8"
    assert "300750.SZ" not in codes, "ChiNext must be excluded by is_main_board"


def test_main_board_only_returns_main_board_data(temp_db):
    universe = load_universe_data(
        str(temp_db), date(2025, 1, 1), date(2025, 9, 21),
    )
    for code, slice in universe.items():
        assert isinstance(slice.df, pd.DataFrame)
        assert {"date", "open", "high", "low", "close", "volume", "amount"} <= set(slice.df.columns)
