"""§4 卖方跌停 no-fill 守卫（审计 P1-9，2026-10-15）。

CLAUDE.md §4（逐字）："a sell/cover on a limit-down-sealed bar MUST be rejected
(no fill)"。

长仓出场是一次 SELL。若出场那根 bar 跌停封板，物理上卖不出去 —— 成交不能凭空
发生，持仓必须顺延到下一根可成交 bar（time / max_hold 出场一并顺延：时间在流逝，
但成交不能假装发生）。方向是保守的：跳过 SL 出场意味着亏损可能继续扩大，符合
§0 Pessimistic Default。这与买方涨停跳过入场（`is_limit_up`）互为镜像。

审计发现：买方涨停守卫在三个引擎都有，**卖方跌停侧一个都没有** —— 出场阶梯会
在跌停开盘价上照常"卖出"。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chase_up.portfolio import LIMIT_DOWN_THRESHOLD, simulate_portfolio


def _panel(exit_open: float) -> pd.DataFrame:
    """8 根 bar；entry 在 bar 1 以 10.0 成交；bar 2 的 open 由参数指定。"""
    n = 8
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        o = exit_open if i == 2 else 10.0
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": o,
            "high": max(o, 10.2),
            "low": min(o, 9.8),
            "close": o if i == 2 else 10.0,
            "volume": 1e6,
            "amount": 1e7,
        })
    return pd.DataFrame(rows)


def _entries(panel: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": panel.iloc[0]["date"],
        "thscode": "TEST.SH",
        "score": 1.0,
        "sig_close": 10.0,
        "sig_ma20": 9.5,
        "sig_ma60": 9.0,
        "sig_ret1": 0.05,
        "sig_breakout_score": 0.5,
        "sig_momentum_score": 0.3,
        "sig_macross_score": np.nan,
        "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": 0.03,
        "sub_signal_type": "A",
    }])


def _run(exit_open: float):
    panel = _panel(exit_open)
    trades, _ = simulate_portfolio(
        _entries(panel), panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=3, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )
    assert len(trades) == 1, f"应恰有 1 笔成交,实际 {len(trades)}"
    return trades.iloc[0], panel.iloc[2]["date"]


def test_limit_down_sealed_exit_bar_is_not_filled() -> None:
    """bar 2 跌停封板(-10%)→ 不得在该 bar 卖出,持仓顺延。"""
    # exit_open = 9.0 → 相对 prev_close 10.0 为 -10%,超过 9.8% 阈值 = 跌停封板
    assert abs(9.0 / 10.0 - 1.0) >= LIMIT_DOWN_THRESHOLD
    t, ld_date = _run(exit_open=9.0)

    assert t["exit_date"] != ld_date, (
        f"§4 VIOLATION: 在跌停封板 bar({ld_date}) 上发生了卖出成交 —— "
        "封板时物理上卖不出去,必须顺延到下一根可成交 bar"
    )
    # 顺延后由时间出场了结(bar 2 之后价格回到 10.0,不再触发 SL/TP)
    assert t["exit_reason"] == "time", (
        f"跌停封板跳过后应由 time 出场,实际 {t['exit_reason']!r}"
    )
    assert t["exit_date"] > ld_date, "出场必须晚于跌停封板 bar"


def test_non_limit_down_exit_bar_still_triggers_sl() -> None:
    """反向对照:bar 2 仅 -5%(非封板)→ SL 照常触发。

    这条证明上一条确实是**跌停守卫**在起作用,而不是别的因素让出场推迟。
    """
    # exit_open = 9.5 → -5%,低于 9.8% 阈值 → 非封板;而 sl_p = 10.0×0.95 = 9.5
    assert abs(9.5 / 10.0 - 1.0) < LIMIT_DOWN_THRESHOLD
    t, ld_date = _run(exit_open=9.5)

    assert t["exit_date"] == ld_date, "非封板时应照常在当日止损出场"
    assert t["exit_reason"] == "SL", f"应为 SL,实际 {t['exit_reason']!r}"
    assert t["exit_price"] == pytest.approx(9.5)
