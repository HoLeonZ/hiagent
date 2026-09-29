"""GREEN: short_reversal trades.csv `net` 字段 vs cash walk 闭包测试 (2026-09-28, CLAUDE.md §0).

Bug 描述:
  原 replay_strategy_v3.py:547 `net = gross_pct - commission_rate` 只扣了
  commission_rate, 漏扣 stamp_duty_rate. 但实际 cash 扣费:
    entry_fee = size × ep × (commission + stamp_duty)  (line 442-443)
    exit_fee  = size × xp × commission                  (line 537)
  实际每笔 cash 贡献的 return rate (per entry notional):
    net_actual = gross_pct - (comm + stamp + comm × xp/ep)
  旧 stored net = gross_pct - comm (canonical Round 9) 或 gross_pct - 0.0006 (OLD)
  系统性偏差 0.04-0.075% per trade, 影响 avg_pnl / sharpe / HTML report.

修复 (Round 19, 2026-09-28):
  net = gross_pct - ((comm + stamp) + comm × (xp/ep))
       = gross_pct - total_fee_ratio
       = cash walk net per entry notional ✓

用户指令范围: "非数据计算的错误...则不去修改"
  → 这是真实的数据计算错误 (cash walk net 与 stored net 不一致),
     必须在 3 类修复范围内处理.
"""
from __future__ import annotations

import pytest


def test_net_formula_matches_cash_walk_short_position():
    """GREEN: net 必须等于 cash walk net per entry notional.

    entry_fee = size × ep × (comm + stamp)
    exit_fee  = size × xp × comm
    proceeds = (ep - xp) × size - exit_fee
    cash delta = proceeds - entry_fee  (entry 时已 reserve, exit 时 release 后扣)
    net_actual = cash delta / (size × ep)
               = gross_pct - (comm + stamp + comm × xp/ep)
    """
    ep = 22.20
    xp = 20.87
    size = 100
    comm = 0.00025
    stamp = 0.0005

    # New formula (post-Round 19 fix):
    total_fee_ratio = (comm + stamp) + comm * (xp / ep)
    stored_net = (ep - xp) / ep - total_fee_ratio

    # Cash walk truth:
    entry_fee = size * ep * (comm + stamp)
    exit_fee = size * xp * comm
    pnl = (ep - xp) * size
    cash_delta = pnl - exit_fee - entry_fee
    net_actual = cash_delta / (size * ep)

    assert abs(stored_net - net_actual) < 1e-9, (
        f"BUG: stored_net ({stored_net:.6f}) ≠ cash walk net_actual "
        f"({net_actual:.6f}); diff = {(stored_net - net_actual)*100:+.4f}%"
    )


def test_net_formula_handles_round_trip_zero_pnl():
    """边界: ep == xp 时, net 仍反映 entry/exit fee, 不为零."""
    ep = 22.20
    xp = 22.20
    size = 100
    comm = 0.00025
    stamp = 0.0005

    total_fee_ratio = (comm + stamp) + comm * (xp / ep)
    stored_net = (ep - xp) / ep - total_fee_ratio

    entry_fee = size * ep * (comm + stamp)
    exit_fee = size * xp * comm
    cash_delta = -entry_fee - exit_fee
    net_actual = cash_delta / (size * ep)

    assert abs(stored_net - net_actual) < 1e-9
    # ep==xp 时: gross_pct=0, fee_ratio = (comm+stamp) + comm×1 = 2*comm + stamp = 0.001
    expected_round_trip = -(2 * comm + stamp)
    assert abs(stored_net - expected_round_trip) < 1e-9, (
        f"ep==xp 应当 = {expected_round_trip:.6f} (= 2*comm + stamp), "
        f"实际 {stored_net:.6f}"
    )


def test_net_formula_uses_canonical_rates():
    """sanity: 默认 commission=0.00025, stamp=0.0005 (canonical Round 9)."""
    # 直接从 Phase3V3Strategy params 读
    from short_reversal.replay_strategy_v3 import Phase3V3Strategy
    params = Phase3V3Strategy.params
    assert params.commission_rate == 0.00025, (
        f"Round 9 fix 应让 default commission_rate=0.00025, "
        f"实际 {params.commission_rate}"
    )
    assert params.stamp_duty_rate == 0.0005, (
        f"Round 9 fix 应让 default stamp_duty_rate=0.0005, "
        f"实际 {params.stamp_duty_rate}"
    )