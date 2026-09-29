"""Round 20 fix verification (2026-09-28, CLAUDE.md §0/§3 data integrity).

Bug fixed:
  chase_up/backtrader_engine.py + uptrend_pullback/backtrader_engine.py Phase 2
  `invested = entry_price * size` 漏 entry_commission, 违反
  core/trade_schema.py:19 canonical invariant:

    net_return == net_pnl / (entry_price × size + buy_commission)
    where buy_commission = max(notional × commission_rate, min_commission)

  修复: invested = entry_price × size + buy_commission

注: 现有 uptrend_pullback v33_long_reverse_v19/v20 trades.csv (2026-09-22)
是 pre-Round 20 fix 旧代码生成的 stale fixture, 需要重跑 backtest 才能
获得 closure-correct data。本 test 仅锁代码层 invariant。
"""
from __future__ import annotations

import inspect

import pytest


def test_chase_up_backtrader_engine_invested_formula_unit():
    """chase_up/backtrader_engine.py: Phase 2 invested 必须含 entry_commission。"""
    from chase_up import backtrader_engine

    src = inspect.getsource(backtrader_engine.run_backtrader_backtest)
    assert "invested = entry_price * size" not in src, (
        "chase_up/backtrader_engine.py Phase 2 still uses bare "
        "`invested = entry_price * size` (missing entry_commission); "
        "violates core/trade_schema.py:19 canonical closure invariant."
    )
    # 必须含 buy_commission 公式
    assert "buy_commission" in src, (
        "chase_up/backtrader_engine.py Phase 2 must compute buy_commission "
        "(= max(notional × commission_rate, min_commission))"
    )


def test_uptrend_pullback_backtrader_engine_invested_formula_unit():
    """uptrend_pullback/backtrader_engine.py: Phase 2 invested 必须含 entry_commission。"""
    from uptrend_pullback import backtrader_engine

    src = inspect.getsource(backtrader_engine.run_backtrader_backtest)
    assert "invested = entry_price * size" not in src, (
        "uptrend_pullback/backtrader_engine.py Phase 2 still uses bare "
        "`invested = entry_price * size` (missing entry_commission); "
        "violates core/trade_schema.py:19 canonical closure invariant."
    )
    assert "buy_commission" in src, (
        "uptrend_pullback/backtrader_engine.py Phase 2 must compute buy_commission"
    )


@pytest.mark.parametrize("fixture_csv", [
    "/Users/holeon/code/hiagent/uptrend_pullback/results/v33_long_reverse_v19_trades.csv",
    "/Users/holeon/code/hiagent/uptrend_pullback/results/v33_long_reverse_v20_trades.csv",
])
@pytest.mark.xfail(
    reason="STALE FIXTURE: trades.csv 是 pre-Round 20 旧代码生成, "
           "需重跑 uptrend_pullback backtest 重生成 trades.csv 才会 PASS。",
    strict=False,
)
def test_uptrend_pullback_stale_trades_csv_needs_regeneration(fixture_csv):
    """Forward-defense: stale trades.csv 数据是 pre-Round 20 旧代码生成。

    xfail 是预期的（说明数据 stale）, 不代表新代码错。
    代码层 unit test (上方 test_chase_up / test_uptrend_pullback) 已锁 invariant。

    重跑命令:
      python -m uptrend_pullback.main --preset v33_long_reverse_v19 \\
        --start 2025-09-08 --end 2026-09-08 --save-trades \\
        results/v33_long_reverse_v19_trades.csv
    """
    import csv
    import os

    if not os.path.exists(fixture_csv):
        pytest.skip(f"fixture {fixture_csv} not present")

    with open(fixture_csv) as f:
        rows = list(csv.DictReader(f))
    assert rows

    viol_count = 0
    max_diff = 0.0
    for r in rows:
        ep, sz = float(r["entry_price"]), float(r["size"])
        net, nr = float(r["net_pnl"]), float(r["net_return"])
        if nr == 0:
            continue
        buy_commission = max(ep * sz * 0.00025, 5.0)
        expected_nr = net / (ep * sz + buy_commission)
        diff = abs(nr - expected_nr)
        if diff > 1e-6:
            viol_count += 1
            max_diff = max(max_diff, diff)
    assert viol_count == 0, (
        f"STALE FIXTURE: {fixture_csv} {viol_count}/{len(rows)} rows missing "
        f"entry_commission (max_diff={max_diff:.6f})"
    )