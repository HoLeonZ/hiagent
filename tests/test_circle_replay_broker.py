from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from circle_price_action.replay_broker import ReplayBroker


@pytest.fixture
def broker_db(tmp_path):
    db = tmp_path / "b.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE,"
        "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
        "amount DOUBLE, volume DOUBLE)"
    )
    dates = pd.date_range("2024-06-03", periods=10, freq="B")
    for d in dates:
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["600000.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e7, 1e6],
        )
    con.close()
    yield db
    db.unlink(missing_ok=True)


def test_buy_fills_on_next_open(broker_db):
    b = ReplayBroker(str(broker_db))
    fill = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))
    assert fill is not None
    assert fill.date == date(2024, 6, 4)
    assert fill.price == 10.0


def test_sell_fills_on_next_open(broker_db):
    b = ReplayBroker(str(broker_db))
    f1 = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))
    b.record_fill(f1)
    f2 = b.submit_sell("600000.SH", 100, decision_date=date(2024, 6, 5))
    assert f2 is not None
    assert f2.date == date(2024, 6, 6)
