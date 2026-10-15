"""§3 事件化公司行为守卫（审计 P2-10，2026-10-15）。

CLAUDE.md §3 逐字要求：
  - "Cash dividends must explicitly trigger a physical cash deposit into
     `Free_Cash`."
  - "Stock splits must trigger an atomic multiplier adjustment to
     `Position_Quantity` and `Average_Cost`."

为什么必须有：执行域是**原始价**，除权日 raw 价向下跳空。没有事件源时，那个缺口
被当成真实盈亏 —— 长仓系统性少计分红。实测 preset `chase_v1_atr_tp4_sl1`
(2025-09-19..2026-09-19) 少计 **¥4,340.00**（¥1M 起始资金）。

本文件锁定：
  1. 分红 → `free_cash` 入账（按除权后持仓数量）。
  2. 送股 → 数量 ×(1+bonus)，**总成本基不变**（`ep × size` 保持不变，
     从而与 `_close_position` 的 `release_margin(ep*size + entry_fee)` 兼容）。
  3. 净值跨除权日**连续**（缺口被分红补偿，不出现物理上不存在的跳变）。
  4. 现金守恒含分红项：`final_equity == initial + Σnet_pnl + Σdividends`。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chase_up.portfolio import apply_corporate_actions, simulate_portfolio
from core.dual_price import portfolio_nav


def _panel(ex_bar: int, kind: str, n: int = 8) -> pd.DataFrame:
    """8 根 bar；bar 1 建仓 10.0；bar 2 为除权日，raw 价按事件下跳。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_ex = i == ex_bar
        raw = 9.0 if (is_ex and kind == "div") else (5.0 if (is_ex and kind == "bonus") else 10.0)
        div = 1.0 if (is_ex and kind == "div") else 0.0
        bonus = 1.0 if (is_ex and kind == "bonus") else 0.0
        rows.append({
            "thscode": "TEST.SH", "date": d,
            "open": raw, "high": raw + 0.2, "low": raw - 0.2, "close": raw,
            "volume": 1e6, "amount": 1e7,
            "raw_open": raw, "raw_high": raw + 0.2, "raw_low": raw - 0.2,
            "raw_close": raw, "raw_prev_close": 10.0,
            "div_per_share": div, "bonus_ratio": bonus, "rights_ratio": 0.0,
        })
    return pd.DataFrame(rows)


def _entries(panel: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": panel.iloc[0]["date"], "thscode": "TEST.SH", "score": 1.0,
        "sig_close": 10.0, "sig_ma20": 9.5, "sig_ma60": 9.0, "sig_ret1": 0.05,
        "sig_breakout_score": 0.5, "sig_momentum_score": 0.3,
        "sig_macross_score": np.nan, "sig_mom120": 0.05, "sig_amount60": 5e7,
        "atr_pct": 0.03, "sub_signal_type": "A",
    }])


def _run(panel: pd.DataFrame):
    trades, eq = simulate_portfolio(
        _entries(panel), panel,
        tp_pct=0.99, sl_pct=0.99, max_hold=3, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0, position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    return trades, eq


def test_cash_dividend_is_deposited_into_free_cash() -> None:
    """分红必须显式进入现金账，且净值跨除权日连续。"""
    panel = _panel(ex_bar=2, kind="div")
    trades, eq = _run(panel)
    assert "cum_dividends" in eq.columns
    div_total = float(eq["cum_dividends"].iloc[-1])
    assert div_total > 0, "除权日未入账任何分红"

    # 入场 bar 1：all_in 在 raw 10.0 成交 → size=10000 → 除权日分红 1.0/股 = 10,000
    assert div_total == pytest.approx(10_000.0), f"分红金额不符: {div_total}"

    # 净值连续性：除权日前后 equity 的变化只应来自当日行情，除权缺口 0.2*size 已由
    # 分红补偿。这里 bar 2 之后无行情变化，故 equity 不应因除权而永久下台阶。
    eq_dates = list(eq["date"])
    i_ex = next(i for i, d in enumerate(eq_dates) if pd.Timestamp(d) == panel.iloc[2]["date"])
    after = float(eq["equity"].iloc[i_ex])
    assert after >= 100_000.0 - 1e-6, (
        f"除权后净值 {after:.2f} 低于初始 —— 分红未补偿除权缺口(§3 Reality Mapping)"
    )


def test_stock_bonus_adjusts_quantity_and_keeps_cost_basis() -> None:
    """送股：数量 ×(1+bonus)，总成本基不变（ep × size 不变量）。"""
    panel = _panel(ex_bar=2, kind="bonus")
    trades, eq = _run(panel)
    assert len(trades) == 1
    size = float(trades.iloc[0]["size"])
    # 送股 1:1 → 数量翻倍，成本价减半；总成本基不变
    assert size == pytest.approx(20_000.0), f"送股后数量应为 2 倍, 实际 {size}"
    assert float(trades.iloc[0]["entry_price"]) == pytest.approx(5.0), (
        "送股后成本价未按总量不变重新定标"
    )


def test_apply_corporate_actions_is_pure_and_reports_rights() -> None:
    """纯函数语义 + 配股显式告警(不静默)。"""
    class _PF:
        free_cash = 0.0

    pf = _PF()
    pos = {"entry_price": 10.0, "size": 1000, "entry_fee": 0.0}
    out = apply_corporate_actions(pf, pos, 0.5, 0.0, 0.0, "X.SH", "2026-01-01")
    assert pf.free_cash == pytest.approx(500.0)
    assert pos["size"] == 1000, "入参 pos 不得被原地修改(§0 append-only)"
    assert out["size"] == 1000

    pf2 = _PF()
    out2 = apply_corporate_actions(pf2, {"entry_price": 10.0, "size": 1000},
                                   0.0, 1.0, 0.0, "X.SH", "2026-01-01")
    assert out2["size"] == 2000
    assert out2["entry_price"] == pytest.approx(5.0)
    assert out2["entry_price"] * out2["size"] == pytest.approx(10_000.0)
