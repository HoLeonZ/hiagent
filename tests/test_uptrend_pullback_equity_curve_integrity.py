"""uptrend_pullback equity 曲线完整性 (§2 双分录 / §5 指标可信度)。

背景 (2026-10-13 实测):
  simulate_portfolio 记录的 equity 行是 `total_cash + Σ(close × size)`, 而
  `total_cash` 是一个「已实现盈亏账本」而非现金账户 —— 买入时**不扣减** cash,
  只有平仓时把 net_pnl 计入。于是持仓期内**建仓名义金额被计入两次**:
  持仓一出现, equity 就凭空跳增约一个名义金额, 平仓时再跳回去。

  实测后果: 单日 equity 收益出现 -52% / +110% 这种物理上不可能的跳变
  (长仓、max_positions=1、A 股 ±10% 涨跌停 ⇒ 单日对权益影响应约 ±10%)。
  由于 compute_metrics 的 sharpe = mean(日收益)/std × √252 正是从这条曲线算出,
  所有窗口的 sharpe / max_dd / exposure —— 以及建立在其上的 DSR/Bonferroni
  —— 全部无效 (CLAUDE.md §5 要求 DSR, 但 DSR 的输入不可信)。

正确的 equity = cash + 未实现盈亏 = total_cash + Σ(close − entry_price) × size。
"""
from __future__ import annotations

import pandas as pd
import pytest

from uptrend_pullback.portfolio import simulate_portfolio


def _panel(prices: list[float], code: str = "EQ.SZ") -> pd.DataFrame:
    days = pd.date_range("2025-09-01", periods=len(prices), freq="B")
    return pd.DataFrame([
        {"date": d, "thscode": code, "open": p, "high": p * 1.01, "low": p * 0.99,
         "close": p, "volume": 1e6, "amount": 1e7, "atr_pct": 0.05}
        for d, p in zip(days, prices)
    ])


def _run(prices: list[float]):
    panel = _panel(prices)
    entries = pd.DataFrame([
        {"date": panel["date"].iloc[0], "thscode": "EQ.SZ", "score": 1.0, "atr_pct": 0.05},
    ])
    trades, equity = simulate_portfolio(
        entries, panel,
        tp_pct=10.0, sl_pct=10.0, max_hold=99, max_positions=1,
        start_date=str(panel["date"].iloc[0].date()),
        end_date=str(panel["date"].iloc[-1].date()),
        initial_capital=10_000.0, position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )
    return trades, equity


def test_equity_row_does_not_double_count_position_notional() -> None:
    """持仓期内 equity 必须 = cash + 未实现盈亏, 不得把建仓名义金额算两次。"""
    prices = [10.0, 10.0, 10.1, 10.2, 10.3, 10.3]
    trades, equity = _run(prices)
    assert len(trades) == 1, f"fixture 应产生 1 笔, 实际 {len(trades)}"
    size = int(trades.iloc[0]["size"])
    notional = size * 10.0

    held = equity.iloc[1:5]                      # 入场后、eod 平仓前
    assert (held["holdings"] > 0).all(), "fixture 应在这些 bar 上持仓"

    # 价格 10.0 那根 bar: 未实现盈亏 = 0 ⇒ equity 必须等于 cash (旧实现会 +一个名义金额)
    flat = held.iloc[0]
    assert abs(flat["equity"] - flat["cash"]) < 1e-6, (
        f"建仓当日价格未变, equity 应等于 cash: equity={flat['equity']:,.2f} "
        f"cash={flat['cash']:,.2f} 差={flat['equity']-flat['cash']:,.2f} "
        f"(持仓名义金额={notional:,.0f}) —— 差额≈名义金额即为双重计数。"
    )

    # 价格 10.1 那根 bar: 未实现 = size × 0.1
    up = held.iloc[1]
    expect_unreal = size * (10.1 - 10.0)
    assert abs((up["equity"] - up["cash"]) - expect_unreal) < 1e-6, (
        f"未实现盈亏应为 {expect_unreal:,.2f}, 实际 "
        f"{up['equity']-up['cash']:,.2f}"
    )


def test_daily_equity_change_tracks_price_move_not_notional() -> None:
    """单日 equity 变化应约等于「价格变动 × 股数」, 而不是整个名义金额。"""
    prices = [10.0, 10.0, 10.1, 10.2, 10.3, 10.3]
    trades, equity = _run(prices)
    size = int(trades.iloc[0]["size"])
    notional = size * 10.0

    d = equity["equity"].diff()
    # 持仓期内最不利的一日跳变: 10.0 → 10.1 只应带来 size × 0.1
    worst_abs = float(d.iloc[1:5].abs().max())
    assert worst_abs < notional * 0.5, (
        f"持仓期内单日 equity 跳变 {worst_abs:,.2f}, 已达名义金额 "
        f"{notional:,.0f} 的 {worst_abs/notional:.0%} —— 物理上不可能 "
        f"(价格日变动仅 1%)。equity 曲线把建仓名义金额计入了。"
    )
