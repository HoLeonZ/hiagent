"""End-to-end backtest test using fixture DuckDB."""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from cycle_price_action.backtest import run_backtest


@pytest.fixture
def bullish_db(tmp_path):
    """3 只 main-board 股,涨幅足以触发 cycle_price_action 策略信号。"""
    db = tmp_path / "market.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE v_daily (
                thscode VARCHAR, date DATE,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                volume DOUBLE, amount DOUBLE
            )
        """)
        dates = pd.date_range("2025-01-01", "2025-09-30", freq="B")
        for code, base in [("600000.SH", 10.0), ("600001.SH", 20.0), ("600002.SH", 30.0)]:
            rows = []
            for i, d in enumerate(dates):
                close = base + i * 0.05   # 单调上升
                rows.append((code, d.date(), close - 0.1, close + 0.2, close - 0.2, close, 1e6, 1e8))
            con.executemany("INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)", rows)
    finally:
        con.close()
    return db


def test_run_backtest_produces_trades(bullish_db):
    result = run_backtest(
        db_path=str(bullish_db),
        start=date(2025, 3, 1),
        end=date(2025, 9, 30),
        cash=1_000_000,
    )
    assert result.metrics["n_trades"] >= 1
    for t in result.trades:
        assert t.exit_date > t.entry_date, "P3: exit must be after entry"
        assert t.hold_days >= 1, "P3: hold_days >= 1"
        # P2: decision meta present
        assert isinstance(t.k_line_score, float)
        assert isinstance(t.phase_score, float)
        assert isinstance(t.calendar_score, float)
