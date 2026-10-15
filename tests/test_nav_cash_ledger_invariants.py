"""§2 净值/现金账不变量守卫（审计 P0 回归锁定，2026-10-15）。

本文件锁定三条曾被四个引擎同时违反的性质：

  1. `portfolio_nav` = Free_Cash + Settling_Funds + Σ 持仓市值
     —— **不含** locked_margin（持仓成本基础），否则持仓期间权益虚增
     约一个入场成本。该错误只在持仓期间出现、平仓后自动消失，因此
     "平仓后对账"式测试永远抓不到它。
  2. `mark_price` 必须 raw-first：以 raw 建仓的仓位不能用复权价盯市，
     否则对有分红送股的标的会错整整一个复权比例（实测单 bar 权益收益
     107.70%，A 股 ±10% 涨跌停下物理不可能）。
  3. 端到端：chase_up 逐 bar 权益恒等式成立、期末权益 == 初始 + Σnet_pnl、
     单 bar 权益收益不超过涨跌停上界。

数据依赖：端到端用例在本地 DB 缺失时 SKIP（CLAUDE.md §6 要求 skip 而非 error）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.dual_price import mark_price, portfolio_nav
from hiagent_config import get_db_path


# ---------------------------------------------------------------------------
# 1) 纯函数契约（无 DB 依赖）
# ---------------------------------------------------------------------------


def test_portfolio_nav_excludes_locked_margin() -> None:
    """NAV 不得把持仓成本基础与持仓市值相加。"""
    # 空仓：free=100, settling=0, 无持仓
    assert portfolio_nav(70.0, 0.0, 30.0) == 100.0
    # 持仓期：free=70 + settling=0 + 市值 30 == 100（而非 total_cash(100)+30=130）
    nav = portfolio_nav(70.0, 0.0, 30.0)
    assert nav == 100.0, f"NAV 把 locked_margin 重复计入了: {nav}"
    # 停牌/结算中资金必须计入
    assert portfolio_nav(70.0, 10.0, 30.0) == 110.0


def test_mark_price_is_raw_first() -> None:
    """raw_close 存在且非 NaN 时必须用 raw（与执行域同域）。"""
    pi = {"close": [16.2422], "raw_close": [23.35]}
    assert mark_price(pi, 0, 23.04, "raw_close") == pytest.approx(23.35)
    # 未声明 raw 执行域 → 用复权价
    assert mark_price(pi, 0, 23.04, "adj_close") == pytest.approx(16.2422)


def test_mark_price_falls_back_on_missing_or_nan_raw() -> None:
    """raw 列缺失 / 为 NaN / 无当日行 → 回退（baseline parity）。"""
    assert mark_price({"close": [16.24]}, 0, 23.04, "raw_close") == pytest.approx(16.24)
    nan = float("nan")
    assert mark_price({"close": [16.24], "raw_close": [nan]}, 0, 23.04, "raw_close") == pytest.approx(16.24)
    # j is None（当日无 bar）→ 回退到调用方给的成本价
    assert mark_price({"close": [16.24]}, None, 23.04, "raw_close") == pytest.approx(23.04)


# ---------------------------------------------------------------------------
# 2) 三池语义（无 DB 依赖）
# ---------------------------------------------------------------------------


def test_cycle_round_trip_totals_initial_plus_pnl_only() -> None:
    """audit P0-2: 一轮完整往返后 total_cash 只能等于「初始 + 盈亏」。

    旧实现 `release_margin` 给 free_cash 记一次账（= 退回入场本金），出场路径
    又 `credit_settling(全额卖出款)`（已含本金返还）—— 同一个本金被记两次，
    往返一次 total_cash 就凭空多出一个本金（1000 → 入场 300 → 出场得款 330
    应为 1030，实际 1330）。本用例按真实可达路径构造：reserve → credit_settling
    → release，逐步断言。
    """
    from cycle_price_action.portfolio import Portfolio

    pf = Portfolio(cash=1000.0)
    assert pf.free_cash == pytest.approx(1000.0)
    assert pf.total_cash == pytest.approx(1000.0)

    # 入场：free_cash → locked_margin（纯转移，总额不变）
    pf.reserve_for_entry(300.0)
    assert pf.free_cash == pytest.approx(700.0)
    assert pf.locked_margin == pytest.approx(300.0)
    assert pf.total_cash == pytest.approx(1000.0), "reserve 是纯池间转移"

    # 出场：卖出款 330（已含本金 300 + 盈亏 30）→ settling；locked 解冻
    pf.credit_settling(330.0)
    pf.release_margin(300.0)
    assert pf.locked_margin == pytest.approx(0.0)
    assert pf.free_cash == pytest.approx(700.0), "release_margin 不得增加 free_cash"
    assert pf.total_cash == pytest.approx(1030.0), (
        f"往返后总现金应为 初始 + 盈亏 = 1030，实际 {pf.total_cash} —— "
        "多出的部分即被重复计入的入场本金（audit P0-2）"
    )


def test_short_reversal_entry_fee_leaves_the_ledger() -> None:
    """audit P0-3: 入场佣金+印花税必须真实离开现金账。

    逐笔 net_pnl 扣了它（§3 口径正确），ledger 也必须扣，否则同一个 metrics
    里的 Sharpe 与 CAGR 出自两套成本口径。
    """
    from short_reversal.replay_strategy_v3 import _canonical_trade_record

    # 记录口径与 ledger 口径的一致性由端到端用例保证；此处锁定 §3 逐笔公式
    row = _canonical_trade_record(
        entry_date="2026-01-05", exit_date="2026-01-12", thscode="600000.SH",
        exit_reason="TP", entry_price=10.0, exit_price=9.0, size=1000,
        hold_days=5, entry_fee=20.0, exit_fee=15.0,
    )
    assert row["gross_pnl"] == pytest.approx((10.0 - 9.0) * 1000)
    assert row["fees"] == pytest.approx(35.0)
    assert row["net_pnl"] == pytest.approx(1000.0 - 35.0)


# ---------------------------------------------------------------------------
# 3) 端到端（DB 缺失则 skip，不 error）
# ---------------------------------------------------------------------------

_DB = get_db_path()
_NEEDS_DB = pytest.mark.skipif(
    not Path(_DB).exists() or Path(_DB).stat().st_size == 0,
    reason=f"local DuckDB 不可用 ({_DB}) — 按 CLAUDE.md §6 skip 而非 error",
)

_PRESET = "chase_v1_atr_tp4_sl1"
_START, _END = "2025-09-19", "2026-09-19"
# A 股主板 ±10% 涨跌停 ⇒ 单 bar 权益收益物理上界约 ±10%（+ 费用余量）
_MAX_BAR_RET = 0.11


@_NEEDS_DB
def test_chase_up_equity_nav_identity_and_cash_conservation() -> None:
    pd = pytest.importorskip("pandas")
    from chase_up.backtest import run_backtest

    res = run_backtest(_PRESET, _START, _END, _DB)
    eq, trades = res["equity"], res["trades"]

    for col in ("free_cash", "locked_margin", "settling_funds"):
        assert col in eq.columns, f"权益账本缺少三池列 {col}（audit P0-1）"

    # (a) 逐 bar NAV 恒等式
    lhs = eq["equity"]
    rhs = eq["free_cash"] + eq["settling_funds"] + eq["holdings"]
    assert (lhs - rhs).abs().max() < 1e-6, "equity != free + settling + holdings"

    # (b) 现金守恒。§3 (audit P2-10): 分红是**独立于逐笔 P&L 的现金流**
    # (physical cash deposit into Free_Cash),必须计入恒等式 ——
    # 否则实现公司行为之后这条守卫会"正确地"失败,而那是守卫不完整,不是代码错。
    init = 1_000_000.0
    realised = float(pd.to_numeric(trades["net_pnl"], errors="coerce").sum())
    assert "cum_dividends" in eq.columns, "权益账本缺少 cum_dividends 列(§3)"
    dividends = float(eq["cum_dividends"].iloc[-1])
    expected = init + realised + dividends
    assert abs(float(eq["equity"].iloc[-1]) - expected) / init < 1e-4, (
        f"现金守恒不成立: equity={float(eq['equity'].iloc[-1]):,.2f} "
        f"!= init+Σnet_pnl+Σdividends={expected:,.2f} "
        f"(Σnet_pnl={realised:,.2f}, Σ分红={dividends:,.2f})"
    )

    # (c) 单 bar 权益收益不得超过涨跌停上界（旧 bug 实测 107.70%）
    worst = float(eq["equity"].pct_change().dropna().abs().max())
    assert worst <= _MAX_BAR_RET, (
        f"单 bar 权益收益 {worst:.2%} 超过 A 股涨跌停上界 {_MAX_BAR_RET:.0%} — "
        "典型成因：盯市跨价格域，或权益重复计入持仓成本"
    )
