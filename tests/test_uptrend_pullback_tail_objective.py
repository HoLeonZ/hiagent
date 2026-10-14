"""R-multiple 目标函数的公式与统计口径 (本轮已两次栽在单位/口径上, 故必须钉住)。"""
from __future__ import annotations

import pandas as pd
import pytest

from uptrend_pullback.tail_objective import r_multiples, tail_stats


def _trades(rows: list[tuple[float, float, float, str]]) -> pd.DataFrame:
    """rows: (net_pnl, entry_price, size, exit_date)"""
    return pd.DataFrame([
        {"net_pnl": n, "entry_price": p, "size": s, "exit_date": d}
        for n, p, s, d in rows
    ])


def test_r_trade_is_planned_risk_not_realized() -> None:
    """R_trade = sl_pct × entry_price × size —— 入场时即固定, 与实际出场无关。"""
    t = _trades([(100.0, 10.0, 1000.0, "2025-01-01")])
    r = r_multiples(t, sl_pct=0.02)
    # 计划风险 = 0.02 × 10 × 1000 = 200 → R = 100/200 = 0.5
    assert r.iloc[0] == pytest.approx(0.5)


def test_r_equals_minus_one_at_stop() -> None:
    """止损出场时 R 应约为 -1 (这是 R 归一的意义: 所有止损都在同一标尺上)。"""
    t = _trades([(-200.0, 10.0, 1000.0, "2025-01-01")])
    assert r_multiples(t, sl_pct=0.02).iloc[0] == pytest.approx(-1.0)


def test_r_scales_with_sl_pct_so_candidates_are_comparable() -> None:
    """同一个 net_pnl 在更宽的 sl_pct 下 R 更小 —— 这正是要跨止损宽度比较的原因。"""
    t = _trades([(100.0, 10.0, 1000.0, "2025-01-01")])
    assert r_multiples(t, 0.02).iloc[0] == pytest.approx(0.5)
    assert r_multiples(t, 0.04).iloc[0] == pytest.approx(0.25)


def test_tail_stats_core_quantities() -> None:
    rows = [
        (1000.0, 10.0, 1000.0, "2025-01-01"),   # R = +5.0
        (200.0, 10.0, 1000.0, "2025-01-02"),    # R = +1.0
        (-200.0, 10.0, 1000.0, "2025-01-03"),   # R = -1.0
        (-200.0, 10.0, 1000.0, "2025-01-04"),   # R = -1.0
    ]
    s = tail_stats(_trades(rows), sl_pct=0.02)
    assert s["n"] == 4
    assert s["expectancy_r"] == pytest.approx((5.0 + 1.0 - 1.0 - 1.0) / 4)
    assert s["win_pct"] == pytest.approx(0.5)
    assert s["avg_win_r"] == pytest.approx(3.0)
    assert s["avg_loss_r"] == pytest.approx(-1.0)
    assert s["payoff"] == pytest.approx(3.0)
    assert s["p_r_ge_5"] == pytest.approx(0.25)
    assert s["p_r_le_minus_1"] == pytest.approx(0.5)
    assert s["worst_r"] == pytest.approx(-1.0)
    assert s["best_r"] == pytest.approx(5.0)


def test_tail_stats_handles_empty() -> None:
    s = tail_stats(pd.DataFrame(columns=["net_pnl", "entry_price", "size", "exit_date"]), 0.02)
    assert s["n"] == 0


def test_r_multiples_rejects_bad_sl_pct() -> None:
    with pytest.raises(ValueError):
        r_multiples(_trades([(1.0, 10.0, 100.0, "2025-01-01")]), sl_pct=0.0)


def test_r_multiples_rejects_zero_risk() -> None:
    with pytest.raises(ValueError):
        r_multiples(_trades([(1.0, 0.0, 100.0, "2025-01-01")]), sl_pct=0.02)
