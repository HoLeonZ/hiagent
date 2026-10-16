from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from cycle_price_action.data_feed import ReplayDataProvider
from cycle_price_action.replay_broker import ReplayBroker


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
    # Tick 49 (CLAUDE.md §6): Broker receives data_provider, not db_path.
    provider = ReplayDataProvider(str(broker_db))
    b = ReplayBroker(provider)
    fill = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))
    assert fill is not None
    assert fill.date == date(2024, 6, 4)
    assert fill.price == 10.0


def test_sell_fills_on_next_open(broker_db):
    # Tick 49 (CLAUDE.md §6): Broker receives data_provider, not db_path.
    provider = ReplayDataProvider(str(broker_db))
    b = ReplayBroker(provider)
    f1 = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))
    b.record_fill(f1)
    f2 = b.submit_sell("600000.SH", 100, decision_date=date(2024, 6, 5))
    assert f2 is not None
    assert f2.date == date(2024, 6, 6)


# ---------------------------------------------------------------------------
# §1 停牌语义: 成交顺延到该股复牌首日, 不合成 bar、不崩溃
# ---------------------------------------------------------------------------


@pytest.fixture
def suspension_db(tmp_path):
    """两支票: 600000.SH 在 6/5~6/7 停牌 (无 bar), 600001.SH 全程正常交易。

    全市场日历因此与个股 bar 序列不一致 —— 这正是旧实现踩空的地方:
    next_trading_date(6/4) = 6/5, 而 600000.SH 当天没有 bar。
    """
    db = tmp_path / "suspend.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE,"
        "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
        "amount DOUBLE, volume DOUBLE)"
    )
    all_days = [d.date() for d in pd.date_range("2024-06-03", periods=10, freq="B")]
    suspended = {date(2024, 6, 5), date(2024, 6, 6), date(2024, 6, 7)}
    for d in all_days:
        # 600000.SH: 向 6/10 复牌, 复牌首日开盘价刻意区别于停牌前 (10.0)
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["600001.SH", d, 10.0, 10.5, 9.8, 10.2, 1e7, 1e6],
        )
        if d not in suspended:
            op = 12.0 if d == date(2024, 6, 10) else 10.0
            con.execute(
                "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
                ["600000.SH", d, op, op + 0.5, op - 0.2, op, 1e7, 1e6],
            )
    con.close()
    yield db
    db.unlink(missing_ok=True)


def test_buy_fill_defers_to_resumption_bar_not_market_calendar(suspension_db):
    """§1: 决策日次一「市场」交易日该股停牌 → 成交顺延到复牌首日开盘。

    旧实现按全市场日历取 fill_date=6/5, 该股当天无 bar → RuntimeError,
    整个回测被打断。修正后 fill_date = 该股自身下一根 bar = 6/10。
    """
    provider = ReplayDataProvider(str(suspension_db))
    b = ReplayBroker(provider)
    fill = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 4))
    assert fill is not None
    assert fill.date == date(2024, 6, 10), (
        f"成交必须落在复牌首日 (6/10), 实际 {fill.date}"
    )
    # 成交价必须取自那一根真实 bar 的开盘, 不得合成
    assert fill.price == 12.0


def test_sell_fill_defers_to_resumption_bar(suspension_db):
    """§1: 卖出同理 —— 停牌期间不得成交, 复牌首日开盘才成交。"""
    provider = ReplayDataProvider(str(suspension_db))
    b = ReplayBroker(provider)
    b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))
    fill = b.submit_sell("600000.SH", 100, decision_date=date(2024, 6, 4))
    assert fill is not None
    assert fill.date == date(2024, 6, 10)
    assert fill.price == 12.0


def test_fill_date_never_fabricated_beyond_data(suspension_db):
    """§0 Fail-Fast: 数据**尾部之外**(非停牌)仍然是缺口, 不得静默成交。

    600000.SH 最后一根 bar 在 6/14; 以 6/14 为决策日时其"下一根 bar"不存在,
    这是数据覆盖缺口而不是停牌, 必须显式失败。
    """
    provider = ReplayDataProvider(str(suspension_db))
    b = ReplayBroker(provider)
    with pytest.raises(RuntimeError, match="coverage gap"):
        b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 14))