"""§2/§0: equity 曲线不得出现负现金 / 非正权益。

背景 —— chase_up 与 uptrend_pullback 的 Phase 2 都是这样造曲线的:

    equity_p2 = equity_p1 + Σ (net_pnl_bt − net_pnl_p1)

delta 是按 Phase-1 的**逐笔固定规模**算出的绝对金额, 而 Phase-1 曲线本身是
**复利**的 (all-in 逐笔重算规模)。量纲不匹配 ⇒ 当 Σ delta 超过曲线当前权益时,
"权益"就变成负数。实测 chase_up / chase_v1_atr_tp4_sl1 / 2022-10-03..2024-09-30:

    Phase 1 simulate  : final_equity =  604,221, exposure =  0.263
    Phase 2 backtrader: final_equity = -423,402, exposure = -0.963

同 76 笔成交、同一窗口。负权益与负敞口在物理上不可能 (§2「Capital is physical
and finite」), 因此 Phase 2 必须拒绝发布这条曲线 —— 而不是照抄成 headline 数字。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.equity_invariants import (
    EquityCurveViolationError,
    assert_equity_curve_is_physical,
)


def _curve(cash: float, equity: float) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "cash": [1_000_000.0, cash, cash],
        "holdings": [0.0, 0.0, 0.0],
        "equity": [1_000_000.0, equity, equity],
    })


def test_negative_equity_is_rejected() -> None:
    # cash 保持非负, 单独把权益压到负数 —— 隔离出 equity 这一条分支
    with pytest.raises(EquityCurveViolationError, match="非正权益"):
        assert_equity_curve_is_physical(
            _curve(cash=0.0, equity=-423_402.0), engine="test", preset="p"
        )


def test_negative_cash_is_rejected() -> None:
    with pytest.raises(EquityCurveViolationError, match="负现金"):
        assert_equity_curve_is_physical(
            _curve(cash=-1.0, equity=500_000.0), engine="test", preset="p"
        )


def test_zero_equity_is_rejected() -> None:
    with pytest.raises(EquityCurveViolationError, match="非正权益"):
        assert_equity_curve_is_physical(
            _curve(cash=0.0, equity=0.0), engine="test", preset="p"
        )


def test_deep_drawdown_is_not_an_error() -> None:
    """大回撤本身不是错误 —— 只有物理上不可能才拒绝。

    99% 回撤的曲线必须放行, 否则这个守卫会退化成"不许亏钱"的过滤器。
    """
    assert_equity_curve_is_physical(
        _curve(cash=10_000.0, equity=10_000.0), engine="test", preset="p"
    )


def test_empty_curve_is_noop() -> None:
    assert_equity_curve_is_physical(
        pd.DataFrame(columns=["date", "cash", "holdings", "equity"]),
        engine="test", preset="p",
    )


@pytest.mark.parametrize(
    "engine_path",
    ["chase_up/backtrader_engine.py", "uptrend_pullback/backtrader_engine.py"],
)
def test_both_phase2_engines_call_the_guard(engine_path: str) -> None:
    """族内不对称守卫: 两个 Phase-2 引擎都必须调用同一个不变量检查。

    这条刻意做成结构断言 —— 本仓库已经因为"一条规则只写在 3-4 个引擎中的
    一个里"反复踩坑, 而这里恰恰是那种规则。
    """
    text = (Path(__file__).parent.parent / engine_path).read_text(encoding="utf-8")
    assert "assert_equity_curve_is_physical" in text, (
        f"{engine_path} 必须调用 core.equity_invariants.assert_equity_curve_is_physical"
    )
