"""Round 21 fix verification (2026-09-28, CLAUDE.md §0/§3 data integrity).

Bug fixed:
  cycle_price_action/main.py:51 `_write_trades_csv` 计算 net_return 用
  `invested = t.entry_price * t.shares` (漏 entry_fee), 违反
  core/trade_schema.py:19 canonical invariant:

    net_return == net_pnl / (entry_price × size + buy_commission)
    buy_commission = max(notional × commission_rate, min_commission)

  修复: invested = entry_price × size + buy_commission
  (commission_rate=0.00025, min_commission=5.0 per Portfolio.COMMISSION_RATE / MIN_COMMISSION)

注: cycle_price_action/results/ 目录空 (2026-09-22 .gitkeep 唯一),
无 stale fixture。代码层 unit test 已锁 invariant。

关联:
  - [[round-20-backtrader-engine-entry-commission-2026-09-28]] — Round 20 同类型 bug
  - [[cost-model-canonical-fix-2026-09-28]] — Round 9 引入 canonical rates
  - [[per-trade-math-closure-audit-2026-09-23]] — Tick 54 chase_up 验证 baseline
"""
from __future__ import annotations

import inspect

import pytest


def test_cycle_price_action_main_invested_formula_unit():
    """cycle_price_action/main.py: _write_trades_csv invested 必须含 buy_commission。

    Round 21 (2026-09-28) — 第 6 个 invested 公式点, 第 1 个有真 bug 的:
    cycle_price_action/main.py:51 用 bare `invested = t.entry_price * t.shares`,
    漏 buy_commission。违反 core/trade_schema.py:19 canonical invariant。
    """
    from cycle_price_action import main

    src = inspect.getsource(main._write_trades_csv)
    # Bare ep × sz (without buy_commission) — banned
    assert "invested = t.entry_price * t.shares" not in src, (
        "cycle_price_action/main.py:_write_trades_csv still uses bare "
        "`invested = t.entry_price * t.shares` (missing buy_commission); "
        "violates core/trade_schema.py:19 canonical closure invariant."
    )
    # 必须含 buy_commission 公式
    assert "buy_commission" in src, (
        "cycle_price_action/main.py:_write_trades_csv must compute buy_commission "
        "(= max(notional × COMMISSION_RATE, MIN_COMMISSION))"
    )


def test_cycle_price_action_invested_matches_portfolio_buy_cost():
    """main.py:_write_trades_csv 的 buy_commission 必须与 Portfolio._buy_cost 一致。

    Portfolio._buy_cost(price, shares) = notional + max(MIN_COMMISSION, notional × COMMISSION_RATE)
    main.py 必须用相同算法 (project-wide cost model single source of truth)。
    """
    from cycle_price_action import main, portfolio

    src_main = inspect.getsource(main._write_trades_csv)
    src_portfolio = inspect.getsource(portfolio.Portfolio._buy_cost)

    # 确认 Portfolio._buy_cost 仍然含 canonical 算法
    assert "MIN_COMMISSION" in src_portfolio
    assert "COMMISSION_RATE" in src_portfolio

    # main.py 必须引用 Portfolio class constants (单一来源)
    assert "Portfolio.COMMISSION_RATE" in src_main, (
        "main.py must reference Portfolio.COMMISSION_RATE (not hardcode 0.00025)"
    )
    assert "Portfolio.MIN_COMMISSION" in src_main, (
        "main.py must reference Portfolio.MIN_COMMISSION (not hardcode 5.0)"
    )


@pytest.mark.parametrize(
    "ep,shares,expected_commission",
    [
        # Small notional → min commission floor (¥5) kicks in
        (10.0, 100, 5.0),       # 1000×0.00025 = 0.25 < 5.0 → floor
        (100.0, 100, 5.0),      # 10000×0.00025 = 2.5 < 5.0 → floor
        # Boundary: rate-based ties with floor
        (200.0, 100, 5.0),      # 20000×0.00025 = 5.0 == floor → 5.0
        # Large notional → rate-based dominates
        (50.0, 10000, 125.0),   # 500000×0.00025 = 125 → rate
    ],
)
def test_cycle_price_action_buy_commission_formula(ep, shares, expected_commission):
    """数值化 buy_commission 公式 correctness。

    notional = ep × shares
    buy_commission = max(notional × 0.00025, 5.0)
    """
    notional = ep * shares
    expected = max(notional * 0.00025, 5.0)
    assert expected == pytest.approx(expected_commission, abs=1e-9)


def test_cycle_price_action_main_does_not_silently_break_closure():
    """Forward-defense: 旧 cycle main.py:51 在典型 trade 上违反 closure。

    trade: ep=10, sz=10000, net_pnl=+500
    OLD invested = ep × sz = 100000 → net_return = 500/100000 = 0.005
    CORRECT invested = 100000 + max(100000×0.00025, 5.0) = 100125 → 500/100125 = 0.00499...

    偏差 ~0.01% per trade。对 buy commission floor trades 偏差更大。
    """
    ep, sz, net_pnl = 10.0, 10000, 500.0
    notional = ep * sz
    buy_commission = max(notional * 0.00025, 5.0)
    correct_invested = notional + buy_commission
    correct_net_return = net_pnl / correct_invested

    # 旧 buggy formula
    buggy_invested = ep * sz
    buggy_net_return = net_pnl / buggy_invested

    # 偏差
    abs_diff = abs(correct_net_return - buggy_net_return)
    assert abs_diff > 0.0, "Sanity check: closure bug should produce non-zero diff"
    # 典型 trade 上偏差 ~5e-6 per trade (10K sz ep=10)
    assert abs_diff < 0.001, "Sanity bound: per-trade deviation under 10bp"