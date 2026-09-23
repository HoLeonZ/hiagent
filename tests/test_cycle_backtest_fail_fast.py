"""§0 Fail-Fast audit: run_backtest must propagate cerebro.run() exceptions.

CLAUDE.md §0: 'Fail-Fast: If a state transition violates physical market laws,
throw an exception immediately. Do not silently bypass.'

The current implementation at cycle_price_action/backtest.py:86-88 catches
`Exception` from `cerebro.run()` and silently `continue` — masking engine
failures as empty backtests. This test pins the contract: hot-path exceptions
must propagate.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from cycle_price_action import backtest as bt_mod


@pytest.fixture
def mixed_db(tmp_path):
    """2 stocks: 1 healthy, 1 with NaN values that will corrupt cerebro.run()."""
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
        rows: list[tuple] = []
        # Healthy stock: monotonic uptrend
        for i, d in enumerate(dates):
            close = 10.0 + i * 0.05
            rows.append(("600000.SH", d.date(), close - 0.1, close + 0.2,
                         close - 0.2, close, 1e6, 1e8))
        # Corrupt stock: ALL NaN close (backtrader will choke on indicator compute)
        for d in dates:
            rows.append(("600999.SH", d.date(), None, None, None, None, None, None))
        con.executemany("INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)", rows)
    finally:
        con.close()
    return db


def test_run_backtest_propagates_engine_exceptions(mixed_db, monkeypatch, caplog):
    """When cerebro.run() raises, run_backtest MUST propagate (FAIL-FAST, §0).

    The corrupt stock 600999.SH will cause backtrader to raise during
    indicator computation. The healthy stock 600000.SH is also present so we
    can prove the loop does NOT silently swallow the error and return
    partial results.
    """
    import logging
    caplog.set_level(logging.WARNING)

    # Force cerebro.run() to raise deterministically (regardless of backtrader's
    # tolerance for NaN) — proves the except clause fails open.
    def boom(self):  # noqa: ARG001 — patch Cerebro.run
        raise RuntimeError("simulated engine failure (RED test injection)")

    monkeypatch.setattr(bt_mod.bt.Cerebro, "run", boom)

    with pytest.raises(RuntimeError, match="simulated engine failure"):
        bt_mod.run_backtest(
            db_path=str(mixed_db),
            start=date(2025, 3, 1),
            end=date(2025, 9, 30),
            cash=1_000_000,
        )

    # §0: errors must NOT be downgraded to log warnings. If a logger.warning
    # was emitted AND we silently returned, that proves the anti-pattern.
    assert not any("backtest failed" in r.message for r in caplog.records), (
        "FAIL-FAST violation: backtest.py swallowed the exception and "
        "logged a warning instead of propagating (§0)."
    )


def test_run_backtest_no_bare_continue_in_hot_path():
    """Static guard: ensure no silent `continue` after `except Exception`.

    Cycle's backtest loop must not silently skip a stock on error. Pinned here
    so the anti-pattern cannot be re-introduced without a failing test.
    """
    import inspect

    source = inspect.getsource(bt_mod.run_backtest)
    # Pattern: except ... continue — every occurrence is a Fail-Fast violation
    # in this loop because each `code` represents one stock's full backtest.
    assert "except Exception" not in source or "continue" not in source.split(
        "except Exception", 1
    )[-1], (
        "FAIL-FAST violation: run_backtest contains `except Exception ... "
        "continue` — §0 requires hot-path exceptions to propagate, not be "
        "swallowed."
    )
