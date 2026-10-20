"""Tests for V7 walkforward_report DSR/Bonferroni formatting."""
from __future__ import annotations

import pandas as pd
import pytest

from dna_stats.walkforward_report import format_walkforward_stats


def test_format_empty_returns_marker():
    """V7: 空 DataFrame 返回 marker。"""
    out = format_walkforward_stats(pd.DataFrame(), n_comparisons=10)
    assert "(empty" in out


def test_format_basic_columns():
    """V7: 必有窗口数 + Sharpe DSR + Bonferroni 字段。"""
    df = pd.DataFrame({
        "total_return": [0.10, 0.20, -0.05, 0.15, 0.25],
        "sharpe": [1.5, 2.0, 0.5, 1.8, 2.3],
        "max_dd": [-0.10, -0.15, -0.20, -0.12, -0.08],
        "trades": [10, 12, 8, 11, 13],
        # 附六十四: DSR 的观察数必须来自运行 —— 2 个月窗口 ≈ 42 个收益观测。
        "n_daily_returns": [42, 42, 41, 42, 43],
    })
    out = format_walkforward_stats(df, n_comparisons=50)
    assert "窗口 5" in out
    assert "DSR" in out
    assert "Bonferroni" in out
    assert "k=50" in out


def test_format_more_trials_lower_dsr():
    """V7: n_comparisons 越大, DSR 越低 (selection bias 严)。"""
    df = pd.DataFrame({
        "total_return": [0.10] * 12,
        "sharpe": [2.0] * 12,
        "n_daily_returns": [42] * 12,   # 附六十四: T 来自运行(不再有 n_windows×63 的估计)
    })
    out_1 = format_walkforward_stats(df, n_comparisons=1)
    out_1000 = format_walkforward_stats(df, n_comparisons=1000)
    # Extract DSR from output strings
    import re
    def extract_dsr(s):
        m = re.search(r"DSR\([^)]+\)\s*=\s*([\d.]+)", s)
        return float(m.group(1)) if m else None
    assert extract_dsr(out_1) > extract_dsr(out_1000)


def test_format_missing_columns_no_crash():
    """V7: 缺列时优雅降级。"""
    df = pd.DataFrame({"total_return": [0.10, 0.20],
                       "n_daily_returns": [42, 42]})   # 缺 sharpe/max_dd
    out = format_walkforward_stats(df, n_comparisons=10)
    assert "窗口 2" in out


# ---------------------------------------------------------------------------
# 附六十四 —— DSR 的观察数 T 必须来自**运行**,不许"n_windows × 常数"地猜
# ---------------------------------------------------------------------------
#
# 原实现:`n_returns=max(n_windows * 63, 100)`,注释自认 "rough estimate:
# ~63 trading days/month"。而**已接线**的调用点是 `uptrend_pullback/wfv_eval.py`
# 的 **23 个 2 个月窗口** ⇒ 该式给 1,449,一个窗口实际只有 **~42** 个观测
# ⇒ T 被高估约 **34 倍**,`sqrt(T-1)` 放大 ~5.9 倍 ⇒ **DSR 系统性偏乐观**。
# 更讽刺的是引擎**早就**为这个参数发布了观察数(`n_daily_returns`,
# 见 uptrend_pullback/backtest.py),只是这条链路没把它带上来。


def test_T_must_come_from_the_run_not_from_a_guess() -> None:
    """缺 `n_daily_returns` 且未显式传 `n_returns` ⇒ **抛错**(不许猜)。"""
    df = pd.DataFrame({"total_return": [0.10, 0.20], "sharpe": [1.0, 2.0]})
    with pytest.raises(ValueError):
        format_walkforward_stats(df, n_comparisons=10)


def test_T_is_taken_from_the_run_column() -> None:
    """T 取自 df 的 `n_daily_returns` 列(各窗口均值),且打印出来可核。"""
    from dna_stats.deflated import deflated_sharpe_ratio

    df = pd.DataFrame({
        "total_return": [0.10, 0.20, -0.05],
        "sharpe": [1.0, 2.0, 3.0],
        "n_daily_returns": [42, 42, 42],
    })
    out = format_walkforward_stats(df, n_comparisons=7)
    assert "T=42" in out, f"T 未取自运行:{out}"
    # 与直接用同一个 T 调用底层 DSR 的结果逐位一致(证明确实用了它)
    import re

    got = float(re.search(r"\)\s*=\s*([\d.]+)", out[out.index("DSR("):]).group(1))
    # 打印保留 3 位小数,故用 1e-3 容差;并且**必须**看得出与"旧猜法"不同 ——
    # 否则这条断言无法区分"用了真实 T"与"用了 n_windows×63 的估计"。
    at_42 = deflated_sharpe_ratio(
        observed_sharpe=2.0, n_trials=7, n_returns=42,
    )["deflated_sharpe"]
    at_guess = deflated_sharpe_ratio(
        observed_sharpe=2.0, n_trials=7, n_returns=3 * 63,
    )["deflated_sharpe"]
    assert abs(got - at_42) < 1e-3, f"未用运行里的 T=42:{got} vs {at_42}"
    assert abs(got - at_guess) > 1e-3, (
        f"打印值 {got} 与「旧猜法」(n_windows×63={3*63})的结果 {at_guess} 不可区分 —— "
        f"这条断言没有判别力"
    )


def test_observed_sharpe_is_the_cross_window_mean() -> None:
    """`observed` 用**跨窗口均值**(与附五十九/六十 的两条路径同口径),不是中位数。"""
    import re

    df = pd.DataFrame({
        "total_return": [0.1, 0.2, 0.3, 0.4, 1.0],
        "sharpe": [1.0, 1.0, 1.0, 1.0, 6.0],     # 均值 2.0,中位 1.0
        "n_daily_returns": [42] * 5,
    })
    out = format_walkforward_stats(df, n_comparisons=3)
    obs = float(re.search(r"obs=([-\d.]+)", out).group(1))
    assert obs == pytest.approx(2.0), (
        f"observed 应为跨窗均值 2.0,实际 {obs}(中位数是 1.0 —— 口径又分叉了)"
    )
