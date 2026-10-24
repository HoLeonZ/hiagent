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
# 停牌：没有 bar ⇒ 不成交（§1）
# ---------------------------------------------------------------------------

def _broker_with_gap(tmp_path) -> ReplayBroker:
    """600000.SH 在 2024-06-04 **停牌**（那天没有 bar），前后都有。

    ⚠️ **必须再放一只 06-04 正常交易的票**：`next_trading_date` 取的是**全市场**
    交易日历（`SELECT MIN(date) FROM v_daily WHERE date > ?`）。只有一只票时，
    停牌那天根本不在日历里，引擎会直接跳到复牌日 —— **复现不出真实缺陷**。
    真实库里永远有别的票在交易，所以 000908.SZ 停牌那天仍然是一个交易日。
    """
    db = tmp_path / "gap.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE,"
        "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
        "amount DOUBLE, volume DOUBLE)"
    )
    for d in pd.date_range("2024-06-03", periods=6, freq="B"):
        # 填充票：每个交易日都交易 —— 它撑起"全市场日历"
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["600001.SH", d.date(), 20.0, 21.0, 19.5, 20.2, 1e7, 1e6],
        )
        if d.date() == date(2024, 6, 4):
            continue                      # 600000.SH 停牌那一天：没有它的 bar
        con.execute(
            "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
            ["600000.SH", d.date(), 10.0, 10.5, 9.8, 10.2, 1e7, 1e6],
        )
    con.close()
    return ReplayBroker(ReplayDataProvider(str(db)))


def test_a_buy_into_a_suspension_does_not_fill(tmp_path):
    """**停牌 ⇒ 不得有成交**（§1：停牌产生缺失 bar，复牌前不得成交）。

    原实现直接 `raise RuntimeError`，于是**一只票停牌一天，整个回测崩掉**
    （实测 2026-10-24：起点 2025-06-01 的 cycle 回测因 `000908.SZ`
    当天停牌而挂掉）。`submit_buy` 的返回类型本来就是 `Optional[TradeFill]`。
    """
    b = _broker_with_gap(tmp_path)
    fill = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))
    assert fill is None, "停牌那天不该有成交"
    # 没有成交 ⇒ 持仓簿里也不该有它
    assert b._open_positions.get("600000.SH", 0) == 0


def test_a_sell_into_a_suspension_keeps_the_position(tmp_path):
    """停牌时卖不掉 ⇒ 仓位留着，等复牌（**不要**编一笔成交）。

    强行"按上一个收盘价卖掉"是在造一笔市场上不存在的成交。
    """
    b = _broker_with_gap(tmp_path)
    fill = b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 2))   # 6-03 成交
    assert fill is not None
    out = b.submit_sell("600000.SH", 100, decision_date=date(2024, 6, 3))   # 6-04 停牌
    assert out is None, "停牌那天卖不掉"
    assert b._open_positions["600000.SH"] == 100, "仓位必须留着"


def test_a_code_the_database_never_heard_of_still_fails_fast(tmp_path):
    """**真正的数据缺口仍然 fail-fast**（§0）。

    停牌是"这只票今天没有 bar"，而"库里根本没有这只票"是 universe 与数据不一致
    —— 后者不该被当成停牌悄悄跳过，那是把配置错误伪装成市场行为。
    """
    b = _broker_with_gap(tmp_path)
    with pytest.raises(RuntimeError, match="no data at all"):
        b.submit_buy("999999.SH", 100, decision_date=date(2024, 6, 3))
