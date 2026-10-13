"""DSR 单位一致性 (§5): observed_sharpe 是年化值, 但 PSR 的分母与 expected_max
都是**逐期(per-period)**量, 两者必须换算到同一频率。

Bailey & López de Prado 的 DSR:
    DSR = Φ[ (SR_per − E[max]·σ) / σ ],   σ = sqrt((1 − γ3·SR + (γ4−1)/4·SR²)/(T−1))
其中 E[max] = (1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(N·e)) 是「k 次试验下 H0 的最大 Sharpe」
以 **σ 为单位**的期望, 所以必须乘 σ 才能与 Sharpe 同量纲。

原实现直接比较 `observed_sharpe`(年化) 与 `expected_max`(逐期), 相当于把年化
Sharpe 和逐期阈值混用 —— 对中等 Sharpe 会系统性过度折减 (把有边际的策略判成
「毫无优势」)。本文件用 stdlib 的 NormalDist **独立**复算, 与实现对比。
"""
from __future__ import annotations

import math
from statistics import NormalDist

import pytest

from dna_stats.deflated import deflated_sharpe_ratio

_ND = NormalDist()


def _reference_dsr(sr_annual: float, n_trials: int, n_returns: int,
                   trading_days: int = 252) -> float:
    """独立参考实现 (Bailey & López de Prado), 全部在逐期单位下计算。"""
    sr = sr_annual / math.sqrt(trading_days)          # 年化 → 逐期
    gamma = 0.5772156649015329
    if n_trials == 1:
        e_max = 0.0                                    # 与实现一致: 单次试验无选择偏差
    else:
        z1 = _ND.inv_cdf(1 - 1.0 / n_trials)
        z2 = _ND.inv_cdf(1 - 1.0 / (n_trials * math.e))
        e_max = (1 - gamma) * z1 + gamma * z2          # 以 σ 为单位的期望最大
    se = math.sqrt((1.0 + 0.5 * sr ** 2) / (n_returns - 1))   # skew=0, kurt=3
    return _ND.cdf(sr / se - e_max)


@pytest.mark.parametrize("sr_annual,n_trials", [
    (0.84, 19),      # 本轮 uptrend v19 实测: 原实现给 0.000
    (1.50, 19),
    (3.00, 19),
    (0.84, 1),
    (0.50, 100),
    (2.00, 100),
])
def test_dsr_matches_bailey_reference(sr_annual: float, n_trials: int) -> None:
    """实现必须与独立参考实现一致 (同一单位口径)。"""
    n_returns = 1071          # 17 窗口 × 63 交易日, 与 walkforward_report 口径一致
    got = deflated_sharpe_ratio(
        observed_sharpe=sr_annual, n_trials=n_trials, n_returns=n_returns,
    )["deflated_sharpe"]
    expect = _reference_dsr(sr_annual, n_trials, n_returns)
    assert got == pytest.approx(expect, abs=0.02), (
        f"DSR 单位口径不一致: SR_annual={sr_annual}, k={n_trials}\n"
        f"  实现 = {got:.4f}\n  参考 = {expect:.4f}"
    )


def test_dsr_is_monotone_in_observed_sharpe() -> None:
    """陷阱式回归: 中等 Sharpe 不得被判成 DSR≈0 (否则「有边际优势」会被读成「毫无优势」)。"""
    vals = [deflated_sharpe_ratio(observed_sharpe=s, n_trials=19,
                                  n_returns=1071)["deflated_sharpe"]
            for s in (0.2, 0.5, 0.84, 1.2, 2.0)]
    assert vals == sorted(vals), f"DSR 应对 Sharpe 单调递增, 实际 {vals}"
    assert vals[2] > 0.1, (
        f"年化 Sharpe=0.84 / k=19 / T=1071 的 DSR 不应被折减到 ~0 "
        f"(参考值 ≈ {_reference_dsr(0.84, 19, 1071):.2f}), 实际 {vals[2]:.4f}"
    )
