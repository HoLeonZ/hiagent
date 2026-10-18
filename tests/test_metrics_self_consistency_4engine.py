"""§2/§3: 每个引擎的 `cagr` 必须能由**它自己的权益曲线**复现 (自洽性)。

## 为什么是"自洽"而不是"跨引擎同名同义" (§13.15 → §13.16)
§13.15 曾说"跨引擎同名同义"的一致性测试**建不起来** ——
因为四个量的定义确实不同, 要先对齐定义, 而那是结果变更 ⇒ **循环**。

**但那个结论只对"同一性"成立。** 有一个**更弱、且不循环**的性质:

> **引擎报的 `cagr` 必须等于"用它自己的权益曲线 + 它自己声明的年化口径"复算出来的值。**

它**不需要任何跨引擎对齐**, 因此**不循环**; 而且它**已经抓住了真 bug**:
历史上 `53d3ab5` 修的就是自洽性失败 (short_reversal 的 `cagr` 用了**请求窗**当分母,
而不是它自己权益曲线的跨度), 而本轮 (§13.16) 又抓住了第二处:
`cagr` 用**已实现现金**当终值, 而 `max_dd` 用 **NAV** —— 同一个 dict 里的两个量
描述的是**两个不同的组合**。

## 本测试的判据 (§6: 必须能失败)
对每个引擎: 跑一次回测 → 取其权益曲线 → 用**它自己的行数**与 **243 或 252** (二者皆合规)
复算 `cagr` → 必须与报告值吻合。**不规定用哪个常数** (那是各引擎的声明自由),
只规定"**必须能用其中一个复现**"。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
# 短窗口: 本测试的价值在"自洽性", 不在样本量; 短窗能让它便宜到能常驻套件。
WINDOW = ("2025-07-01", "2025-09-30")
INITIAL = 1_000_000.0


def _db():
    try:
        from hiagent_config import DB_PATH

        return Path(DB_PATH)
    except Exception:
        return None


def _self_consistent(cagr: float, nav_series, init: float) -> tuple[bool, str]:
    """cagr 能否由 (权益曲线行数, 243 或 252) 复现?"""
    n = len(nav_series)
    if n == 0 or nav_series[-1] <= 0:
        return False, "空/非正权益曲线"
    tot = nav_series[-1] / init
    hits = [
        T
        for T in (243, 252)
        if abs(tot ** (1.0 / max(n / T, 1e-9)) - 1.0 - cagr) < 1e-6
    ]
    if hits:
        return True, f"T={hits[0]}"
    return False, f"n_days={n} 终值={nav_series[-1]:,.2f}"


def _check_all(eng: str, m: dict, nav, trades_net, *, tr_key: str) -> None:
    """把 §13.16 的自洽性方法施于**其余指标** (§13.17)。

    对每个指标只用**引擎自己的输出**复算 —— **不需要跨引擎对齐** ⇒ 不循环。
    这四条一起在一处断言, 因为**跑一次回测就能全查** (零额外运行时成本)。
    """
    nav = [float(x) for x in nav]
    assert nav and nav[-1] > 0, f"{eng}: 权益曲线为空/非正"

    # ① total_return
    tr = m.get(tr_key)
    assert tr is not None and abs(tr - (nav[-1] / INITIAL - 1.0)) < 1e-9, (
        f"{eng}: total_return 报 {tr} 与它自己权益曲线的 {nav[-1] / INITIAL - 1.0:.10f} 不符"
    )

    # ② max_dd —— 必须等于**它自己那条** NAV 序列的最大回撤
    peak, dd = nav[0], 0.0
    for v in nav:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, 1.0 - v / peak)
    assert m.get("max_dd") is not None and abs(m["max_dd"] - dd) < 1e-9, (
        f"{eng}: max_dd 报 {m.get('max_dd')} 与它自己权益曲线的 {dd:.10f} 不符"
    )

    # ③ win_rate —— 必须等于**它自己那些成交**里净利为正的比例
    if trades_net is not None and len(trades_net) > 0:
        wr = float(sum(1 for x in trades_net if x > 0) / len(trades_net))
        assert m.get("win_rate") is not None and abs(m["win_rate"] - wr) < 1e-9, (
            f"{eng}: win_rate 报 {m.get('win_rate')} 与它自己成交的 {wr:.10f} 不符"
        )


@pytest.mark.skipif(_db() is None, reason="需要本地 DB (§6: 缺产物时 skip, 不 error)")
def test_short_reversal_cagr_is_self_consistent() -> None:
    from hiagent_config import DB_PATH
    from short_reversal.engine import run_backtest_v3

    m = run_backtest_v3("v58_mp_2", *WINDOW, Path(DB_PATH))
    nav = [r["equity"] for r in m["equity_curve"] if r.get("equity") is not None]
    # ⚠️ 键名**不跨引擎统一** —— short_reversal 用的是 `total_yield`, 另三个才是 `total_return`。
    # (本节初稿把 short_reversal 也写成 `total_return` ⇒ 读到 None ⇒ 断言红。
    #  这正是 §13.13 那条"同名不是一致性的证据"的**反面**: 这里连名字都不相同,
    #  而我**先入为主地假设了它们相同**。是"跑一遍"把它抓出来的。)
    _check_all("short_reversal", m, nav, [t["net_pnl"] for t in m["trades"]],
               tr_key="total_yield")
    ok, why = _self_consistent(m["cagr"], nav, INITIAL)
    assert ok, (
        f"short_reversal 的 cagr={m['cagr']:+.8f} **无法由它自己的权益曲线复现** ({why})。\n"
        f"历史形态两种: 分母用了请求窗 (53d3ab5), 或终值用了已实现现金而非 NAV (§13.16)。"
    )


@pytest.mark.skipif(_db() is None, reason="需要本地 DB (§6: 缺产物时 skip, 不 error)")
def test_chase_up_cagr_is_self_consistent() -> None:
    from hiagent_config import DB_PATH
    from chase_up.backtest import run_backtest

    r = run_backtest("chase_v5_pos2_equal_atr_tp6_sl15_mh10", *WINDOW, DB_PATH)
    _check_all("chase_up", r["metrics"], r["equity"]["equity"].to_numpy(),
               r["trades"]["net_pnl"].to_numpy() if len(r["trades"]) else None,
               tr_key="total_return")
    ok, why = _self_consistent(
        r["metrics"]["cagr"], r["equity"]["equity"].to_numpy(), INITIAL
    )
    assert ok, f"chase_up 的 cagr 无法由它自己的权益曲线复现 ({why})"


@pytest.mark.skipif(_db() is None, reason="需要本地 DB (§6: 缺产物时 skip, 不 error)")
def test_uptrend_pullback_cagr_is_self_consistent() -> None:
    from hiagent_config import DB_PATH
    from uptrend_pullback.backtest import run_backtest

    r = run_backtest("v33_long_reverse_v22", *WINDOW, DB_PATH)
    _check_all("uptrend_pullback", r["metrics"], r["equity"]["equity"].to_numpy(),
               r["trades"]["net_pnl"].to_numpy() if len(r["trades"]) else None,
               tr_key="total_return")
    ok, why = _self_consistent(
        r["metrics"]["cagr"], r["equity"]["equity"].to_numpy(), INITIAL
    )
    assert ok, f"uptrend_pullback 的 cagr 无法由它自己的权益曲线复现 ({why})"


def test_cycle_price_action_cagr_is_self_consistent() -> None:
    """cycle 的 `portfolio_metrics` 是纯函数 ⇒ 用合成权益曲线测, 不需要 DB。"""
    from cycle_price_action.allocator import (
        TRADING_DAYS_PER_YEAR,
        AllocationResult,
        portfolio_metrics,
    )

    eq = [INITIAL * (1 + 0.001 * i) for i in range(100)]
    res = AllocationResult(
        trading_days=list(range(100)),
        equity=eq,
        taken=[],
        n_signals=0,
        n_rejected_capacity=0,
        exposure=0.0,
        initial_capital=INITIAL,
        final_equity=eq[-1],
    )
    m = portfolio_metrics(res)
    _check_all("cycle_price_action", m, eq, None, tr_key="total_return")
    expect = (eq[-1] / INITIAL) ** (1.0 / (len(eq) / TRADING_DAYS_PER_YEAR)) - 1.0
    assert abs(m["cagr"] - expect) < 1e-12, "cycle 的 cagr 无法由它自己的权益曲线复现"
