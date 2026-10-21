"""Round 20 fix verification (2026-09-28, CLAUDE.md §0/§3 data integrity).

Bug fixed:
  chase_up/backtrader_engine.py + uptrend_pullback/backtrader_engine.py Phase 2
  `invested = entry_price * size` 漏 entry_commission, 违反
  core/trade_schema.py:19 canonical invariant:

    net_return == net_pnl / (entry_price × size + buy_commission)
    where buy_commission = max(notional × commission_rate, min_commission)

  修复: invested = entry_price × size + buy_commission

注: `uptrend_pullback` 的 `v33_long_reverse_v19/v20` **结果产物当前不在库里**
(实测 2026-10-21;此前这里写的"存在但 stale"是**错的** —— 那两个文件根本没生成)。
要拿到 closure-correct 的产物:

    python -m uptrend_pullback.main --preset v33_long_reverse_v19 \
      --start 2025-09-08 --end 2026-09-08 --save-trades \
      results/v33_long_reverse_v19_trades.csv

本文件只锁**代码层** invariant:产物是 gitignored 的,**不在本机遗留文件上断言**
(那会让"干净克隆通过、脏工作区报红",本身不可复现)。
"""
from __future__ import annotations

import inspect


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


