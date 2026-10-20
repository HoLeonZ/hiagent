"""TradeRecord + compute_metrics tests."""
from __future__ import annotations

from datetime import date

import pytest

from cycle_price_action.metrics import TradeRecord, compute_metrics


def _t(pnl: float, hold: int = 5) -> TradeRecord:
    return TradeRecord(
        thscode="600000.SH",
        entry_date=date(2025, 1, 1),
        exit_date=date(2025, 1, 1 + hold),
        entry_price=10.0,
        exit_price=11.0 if pnl > 0 else 9.0,
        shares=100,
        pnl=pnl,
        hold_days=hold,
        k_line_score=1.5,
        phase_score=0.3,
        calendar_score=0.8,
    )


def test_compute_metrics_basic():
    trades = [_t(100.0), _t(-50.0), _t(200.0)]
    m = compute_metrics(trades, cash_per_account=1_000_000.0, n_accounts=472)
    assert m["n_trades"] == 3
    assert m["n_wins"] == 2
    assert m["total_pnl"] == pytest.approx(250.0)
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["avg_hold_days"] == pytest.approx(5.0)
    assert m["n_stocks"] == 1


def test_compute_metrics_empty_no_crash():
    m = compute_metrics([], cash_per_account=1_000_000.0, n_accounts=472)
    assert m["n_trades"] == 0
    assert m["total_pnl"] == 0
    assert m["win_rate"] == 0
    assert m["cagr"] is None
    assert m["sharpe"] is None
    assert m["max_dd"] is None


def test_metrics_carry_the_account_model_so_total_pnl_has_a_denominator():
    """§2: `total_pnl` 是 **N 个独立账户的合计**,其分母必须随产物一起发布。

    本引擎对 universe 每个成员各建一个账户(各自 100 万)。实测 2026-04 窗口:
    492 笔成交分布在 **472** 只股票上,`total_pnl=-776,948` —— 若读者按
    chase_up 那种"一个 100 万组合"去理解,会差两个数量级。cagr/max_dd/sharpe
    已诚实地返回 None;唯一没有分母的就是 total_pnl,故必须显式标注。
    """
    m = compute_metrics([_t(100.0)], cash_per_account=1_000_000.0, n_accounts=472)
    assert m["account_model"] == "per_stock_independent"
    assert m["capital_per_account"] == pytest.approx(1_000_000.0)
    assert m["n_accounts"] == 472
    assert m["notional_capital"] == pytest.approx(472_000_000.0), (
        "notional_capital 必须 = 账户数 × 每账户资金 —— 它就是 total_pnl 的分母"
    )
    # 「算不出」必须诚实地是 None,不得用横截面合计冒充组合指标
    assert m["cagr"] is None and m["sharpe"] is None and m["max_dd"] is None


def test_account_model_cannot_be_omitted():
    """§0 fail-fast:产出不带口径的 total_pnl 必须在**调用点**就失败。

    两个参数是必填的 —— 否则新调用方会悄悄发布一个含义不明的合计数字。
    """
    with pytest.raises(TypeError):
        compute_metrics([_t(100.0)])  # type: ignore[call-arg]
