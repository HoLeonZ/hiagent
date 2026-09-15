"""回归测试：修复后的事件驱动引擎关键行为。

覆盖 3 个 bug fix：
  - Bug 1: SL gap-aware exit price 必须用 sl_p，不能用 open_p（避免单笔 SL 损失被跳空放大）
  - Bug 2: hold_days = len(self) - pos["entry_bar"]（bar 跨度，不是 bar 数 -1）
  - Bug 3: NAV-based max_dd（cash + 做空持仓 mark-to-market 浮盈）
"""
from __future__ import annotations

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData
from short_reversal.replay_strategy_v3 import Phase3V3Strategy


def _run_strategy(panel: pd.DataFrame, **kwargs) -> dict:
    """跑 Phase3V3Strategy on 1 stock panel。"""
    initial_capital = kwargs.pop("initial_capital", 1_000_000.0)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_capital)
    cerebro.broker.setcommission(commission=0.0)
    feed = AShareData(dataname=panel, plot=False)
    cerebro.adddata(feed, name=panel["thscode"].iloc[0])
    holder: dict = {"cash": initial_capital, "trades": [], "max_dd": 0.0}
    # 默认 pct_chg_low=0.0 让我们合成的 0.2% UP bars 能触发 C 条件
    kwargs.setdefault("pct_chg_low", 0.0)
    kwargs.setdefault("pct_chg_high", 0.10)
    cerebro.addstrategy(
        Phase3V3Strategy,
        initial_capital=initial_capital,
        lot_size=100,
        result_holder=holder,
        **kwargs,
    )
    cerebro.run()
    return holder


def _build_cascade_entry_panel(n: int = 220) -> pd.DataFrame:
    """构造 cascade 触发场景（同 test_phase3_v3_strategy._build_monotonic_down_panel）。

    - bar 195: DROP（22.0）→ 凑 ma5 << ma10
    - bar 196-199: 4 根小幅 UP → 凑 up_streak=4 + pct_chg>0
    - bar 200: close=22.20（与入场所需 close < ma20 一致）
    - bar 200+ 默认保持 22.20（避免 TP/SL 触发）
    """
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        if i < 130:
            p = 20.0 + 0.05 * i
        elif i < 195:
            p = 20.0 + 0.05 * 130 - 0.05 * (i - 130)
        elif i == 195:
            p = 22.0
        elif i < 200:
            p = 22.0 + 0.05 * (i - 195)
        else:
            p = 22.20  # 默认保持稳定
        rows.append({
            "thscode": "600000.SH",
            "date": d,
            "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    return pd.DataFrame(rows)


# ====================================================================
# Bug 1: SL gap-aware exit price — 必须用 sl_p 而不是 open_p
# ====================================================================

def test_sl_exit_uses_sl_price_not_open_when_gap_up():
    """开盘跳空穿过 SL → exit_price 必须 = sl_p, 不能用 open_p。

    Bug 修复前：open_p 远高于 sl_p → exit_price = open_p → 单笔 SL 损失被跳空放大数倍。
    Bug 修复后：exit_price = sl_p → SL 损失上限严格 = sl_pct。
    """
    n = 220
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    # 前 200 根用 cascade shape（确保 bar=200 触发信号，bar=201 fill）
    for i in range(201):
        if i < 130:
            p = 20.0 + 0.05 * i
        elif i < 195:
            p = 20.0 + 0.05 * 130 - 0.05 * (i - 130)
        elif i == 195:
            p = 22.0
        else:
            p = 22.0 + 0.05 * (i - 195)
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    # bar 201（entry bar = fill pending）→ 让 open 跳空穿过 SL
    # entry_price (bar=200 close) ≈ 22.20
    # sl_pct=0.10 → sl_p = 22.20 * 1.10 = 24.42
    # 让 open_p=25.0 远高于 sl_p，且 low=24.5 ≥ sl_p → 必须 SL @ sl_p
    rows.append({
        "thscode": "600000.SH", "date": dates[201],
        "open": 25.0, "high": 25.0, "low": 24.5, "close": 25.0,
        "amount": 5e7, "volume": 1e6,
    })
    for i in range(202, n):
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": 25.0, "high": 25.0, "low": 24.9, "close": 25.0,
            "amount": 5e7, "volume": 1e6,
        })
    panel = pd.DataFrame(rows)

    h = _run_strategy(
        panel,
        tp_pct=0.06,
        sl_pct=0.10,        # 10% → 远大于跳空幅度，sl_p 仍可作为 price 上限
        max_hold=20,
        a_condition="cascade_price",
        position_fraction=1.0,
    )
    assert len(h["trades"]) >= 1, f"未触发入场, trades={h['trades']}"
    sl_trade = next((t for t in h["trades"] if t["exit_reason"] == "SL"), None)
    assert sl_trade is not None, f"未触发 SL 出场, trades={h['trades']}"

    ep = sl_trade["entry_price"]
    sl_p_expected = ep * 1.10
    # Bug 修复前：exit_price = open_p = 25.0 → net = (25.0 - ep)/ep - 0.06% ≈ -12.6%
    # Bug 修复后：exit_price = sl_p = 24.42 → net = (ep - sl_p)/ep - 0.06% ≈ -10.06%
    #   (做空仓，价格涨到 sl_p → 损失 = sl_pct = 10%)
    assert sl_trade["exit_price"] == pytest.approx(sl_p_expected, rel=1e-6), (
        f"SL exit_price 应 = sl_p={sl_p_expected:.4f}, 实际={sl_trade['exit_price']:.4f} "
        f"(Bug 1 修复验证：跳空穿过时不能用 open_p=25.0)"
    )
    # SL 损失上限严格 = sl_pct（不能再被 open_p 放大）
    assert sl_trade["net"] == pytest.approx(-0.10 - 0.0006, rel=1e-3)


# ====================================================================
# Bug 2: hold_days 正确性 = len(self) - entry_bar（bar 跨度）
# ====================================================================

def test_hold_days_is_bar_span_not_bar_count_minus_one():
    """time exit 时 hold_days 应等于 entry bar 到 exit bar 的 bar 跨度。

    Bug 修复前：hold_days = len(self) - 1 - entry_bar = bar_count - 1（off-by-1）
    Bug 修复后：hold_days = len(self) - entry_bar = bar_span

    scenario: max_hold=3 → 在 entry bar + 3 触发 time exit，跨度 = 4
    """
    n = 220
    panel = _build_cascade_entry_panel(n=n)

    h = _run_strategy(
        panel,
        tp_pct=0.0001,      # 极小 → 永不触发 TP
        sl_pct=10.0,        # 极大 → 永不触发 SL
        max_hold=3,
        a_condition="cascade_price",
        position_fraction=1.0,
    )
    assert len(h["trades"]) >= 1, f"未触发入场, trades={h['trades']}"
    t = h["trades"][0]
    assert t["exit_reason"] == "time"
    # hold_days 应 = exit bar - entry bar = 200 + 3 + 1 - 200 = 4 (max_hold 触发后 bar +1)
    # Bug 修复前：hold_days=3；Bug 修复后：hold_days=4
    assert t["hold_days"] == 4, (
        f"hold_days 应=4 (entry bar 200, max_hold=3 触发 time exit, 跨度=4), "
        f"实际={t['hold_days']} (Bug 2 修复验证)"
    )


# ====================================================================
# Bug 3: NAV-based max_dd — 必须包含做空持仓 mark-to-market 浮盈
# ====================================================================

def test_max_dd_includes_short_position_unrealized_pnl():
    """持仓浮盈/浮亏必须计入 max_dd（NAV-based），不能用纯 cash。

    Bug 修复前：max_dd 用 cash，浮亏不被记录 → max_dd 虚低。
    Bug 修复后：max_dd 用 NAV（含 mark-to-market），浮亏正确计入。

    场景：entry 后 close 持续上涨（做空亏）→ NAV 大幅下降 → max_dd > 0
    """
    n = 230
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    # 前 201 根用 cascade shape（确保 bar=200 触发信号，bar=201 fill @ open_p）
    for i in range(201):
        if i < 130:
            p = 20.0 + 0.05 * i
        elif i < 195:
            p = 20.0 + 0.05 * 130 - 0.05 * (i - 130)
        elif i == 195:
            p = 22.0
        else:
            p = 22.0 + 0.05 * (i - 195)
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": p, "high": p + 0.0001, "low": p - 0.0001, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    # bar 201 起：close 持续大幅上涨 → 做空浮亏快速扩大
    # entry_price ≈ 22.20, bar=221 close ≈ 22.20 + 0.5*20 = 32.20
    # 浮亏 = (32.20 - 22.20) * size = 10.0 * 45000 = 450k
    for i in range(201, n):
        p = 22.20 + 0.5 * (i - 201)  # 22.20 → ~32.70
        rows.append({
            "thscode": "600000.SH", "date": dates[i],
            "open": p, "high": p + 0.1, "low": p - 0.1, "close": p,
            "amount": 5e7, "volume": 1e6,
        })
    panel = pd.DataFrame(rows)

    h = _run_strategy(
        panel,
        tp_pct=0.50,        # 极大 → 不会触发
        sl_pct=10.0,        # 极大 → 不会触发
        max_hold=20,        # 较短 → bar 201+20 = 221 触发 time exit
        a_condition="cascade_price",
        position_fraction=1.0,
    )
    assert len(h["trades"]) >= 1, f"未触发入场, trades={h['trades']}"
    # NAV-based max_dd 应显著 > 0（持仓浮亏被计入）
    # cash 路径：entry 扣 entry_fee + margin_fees
    # NAV 路径：cash + (entry_price - current_close) * size
    # peak ≈ entry 后立即 = initial_capital（不含 fee）/ 浮盈触发前
    # bottom NAV ≈ 1M - 9.0 * 44000 = 1M - 396k = 604k
    # max_dd ≈ (1M - 604k) / 1M = 39.6%
    assert h["max_dd"] > 0.05, (
        f"max_dd 应 > 5%（做空浮亏必须计入 NAV），实际={h['max_dd']:.4f} "
        f"(Bug 3 修复验证：cash-only 会让 max_dd 接近 0)"
    )
    assert h["cash"] > 0