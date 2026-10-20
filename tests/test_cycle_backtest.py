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
        # §1 (audit P1-C2, 2026-10-15): 数据起点前移,使 `start=2025-03-01`
        # 之前有 >=60 个交易日的历史。流动性门 (lookback=60) 的均值只允许
        # 用 as_of(=start) 之前的成交额 —— 这是 §1 AsOf 规则的要求,也是本
        # 仓库的既定设计(见 test_cycle_survivorship_bias 的 pre-window pad)。
        # 原 fixture 从 2025-01-01 起,因果窗口内仅约 42 个交易日,不满足
        # 该门的既有前置条件,会被全部剔除 → 宇宙为空。
        dates = pd.date_range("2024-06-03", "2025-09-30", freq="B")
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


def test_metrics_are_labeled_with_the_account_model(bullish_db):
    """§2: `total_pnl` 的分母必须随产物发布 —— 引擎是**每股一个独立账户**。

    接线验证(不是 compute_metrics 的单测):`run_backtest` 必须把
    **universe 成员数**作为账户数传下去。注意是成员数、不是成交过的股票数 ——
    每个成员都开了一个账户,即使一笔未成交。

    为什么这条重要:`cash=1_000_000` 是**每账户**资金,所以 total_pnl 的真实分母
    是 `n_accounts × 100 万`。实测全主板 2953 个成员时该分母约 29.5 亿 ——
    若读者按 chase_up 那种"一个 100 万组合"去理解,会差三个数量级。
    """
    from cycle_price_action.backtest import load_universe_data

    start, end, cash = date(2025, 3, 1), date(2025, 9, 30), 1_000_000
    result = run_backtest(db_path=str(bullish_db), start=start, end=end, cash=cash)
    m = result.metrics

    universe = load_universe_data(str(bullish_db), start, end, asof_date=start)
    assert m["account_model"] == "per_stock_independent"
    assert m["capital_per_account"] == pytest.approx(float(cash))
    assert m["n_accounts"] == len(universe), (
        "账户数必须是 universe 成员数,而不是成交过的股票数(n_stocks)"
    )
    assert m["notional_capital"] == pytest.approx(float(cash) * len(universe))
    # "算不出"必须诚实地是 None —— 不得用横截面合计冒充组合指标
    assert m["cagr"] is None and m["sharpe"] is None and m["max_dd"] is None
