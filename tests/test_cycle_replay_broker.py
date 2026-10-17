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
# 附五十五 —— 送股把持仓变成**非整手**,而 broker 的整手断言把整轮回测崩掉
# ---------------------------------------------------------------------------
#
# 实测(活库):000793.SZ 于 2026-06-22 除权,`per_share_bonus = 0.0478`,
# `apply_corporate_action` 按 §3 把数量调成 330,800 × 1.0478 = **346,612** 股
# (非 100 的整数倍)。随后时间出场调用 `submit_sell(qty=346612)`,而这里此前
# 断言 `qty % 100 == 0` ⇒ `ValueError`,被 `backtest.run_backtest` 包成
# `RuntimeError: backtest failed for 000793.SZ` ⇒ **整轮 backtest 中止**。
#
# A 股规则:买入必须是 100 股整数倍;**卖出不必** —— 持股因送股变成零股时,
# 必须以**一笔**全部卖出。故这里要同时钉住两件事:
#   * 含零股的全仓卖出**允许**;
#   * 买入的整手约束**仍然生效**(不能把不变量一起删掉)。


def test_odd_lot_full_liquidation_is_allowed(broker_db):
    """送股产生的零股必须能**整笔**卖出(A 股规则)。"""
    provider = ReplayDataProvider(str(broker_db))
    b = ReplayBroker(provider)
    # 330,800 股(整手)→ 10送0.478 ⇒ 346,612 股
    assert b.submit_buy("600000.SH", 330_800, decision_date=date(2024, 6, 3)) is not None
    qty = 346_612                      # = round(330800 * 1.0478)
    assert qty % 100 != 0, "夹具前提:该数量必须是**非整手**,否则测不到这条路径"
    fill = b.submit_sell("600000.SH", qty, decision_date=date(2024, 6, 5))
    assert fill is not None, "含零股的全仓卖出被拒绝 —— 送股日会把整轮回测崩掉"
    assert fill.qty == qty


def test_buy_lot_constraint_is_still_enforced(broker_db):
    """对照组:买入的整手约束**不得**被上一处修复一起删掉。"""
    provider = ReplayDataProvider(str(broker_db))
    b = ReplayBroker(provider)
    assert b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3)) is not None
    with pytest.raises(ValueError):
        b.submit_buy("600000.SH", 346_612, decision_date=date(2024, 6, 3))


def test_shadow_position_divergence_does_not_abort_the_run(broker_db):
    """影子账落后于组合账本时必须**告警**而不是中止整轮回测。

    两条合法分叉路径:
      (a) 送股把组合持股放大,而 broker 在买入时只记了除权前的数量;
      (b) SL/TP 出场走 `Portfolio.try_exit_with_intraday_check`,不经过
          `submit_sell` ⇒ 那些平仓从不减少影子账(实测累积到 1,050,900)。
    此前 `raise ValueError("cannot sell more than held")` 会在 (a) 上把一次
    **合法**的全仓平仓变成整轮中止。
    """
    provider = ReplayDataProvider(str(broker_db))
    b = ReplayBroker(provider)
    assert b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3)) is not None
    fill = b.submit_sell("600000.SH", 120, decision_date=date(2024, 6, 5))
    assert fill is not None, "影子账落后就拒绝卖出 —— 会把整轮回测中止"
    assert fill.qty == 120
    # 清空而不是留一个负数
    assert b._open_positions.get("600000.SH", 0) == 0


def test_bonus_adjusted_position_can_be_liquidated_end_to_end(broker_db):
    """**崩溃链条的集成版**:建仓 → 送股 → 平仓,整条链必须走通。

    对应实测事故:`Portfolio.try_enter` 建仓(整手)→ 除权日
    `apply_corporate_action` 按 §3 把数量调成非整手 → 引擎时间出场
    `broker.submit_sell(position.shares)` → 旧实现在此抛 ValueError,
    被包成 `RuntimeError: backtest failed for 000793.SZ`,**整轮回测中止**。
    """
    from cycle_price_action.portfolio import Portfolio

    provider = ReplayDataProvider(str(broker_db))
    b = ReplayBroker(provider)
    p = Portfolio(cash=1_000_000.0)

    pos = p.try_enter("600000.SH", 10.0, date(2024, 6, 3), {"probe": True})
    assert pos is not None, "夹具未建仓"
    assert pos.shares % 100 == 0, "建仓数量应是整手"
    assert b.submit_buy("600000.SH", pos.shares, decision_date=date(2024, 6, 3)) is not None

    p.apply_corporate_action(bonus_ratio=0.0478)   # 10送0.478(实测事件比率)
    after = p.position.shares
    assert after != pos.shares, "送股未调整数量 —— §3 未生效"
    assert after % 100 != 0, "夹具前提:调整后必须是**非整手**"

    # 影子账只记了除权前的数量 ⇒ 同时覆盖"影子账分叉"那条路径
    fill = b.submit_sell("600000.SH", after, decision_date=date(2024, 6, 5))
    assert fill is not None and fill.qty == after, (
        "送股调整后的全仓平仓被拒 —— 这正是 000793.SZ 崩溃链条"
    )
    assert p.try_exit(fill.date, fill.price) is not None
    assert p.position is None
