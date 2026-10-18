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

from core.trade_schema import TRADING_DAYS_PER_YEAR
from dna_stats.deflated import deflated_sharpe_ratio, sharpe_significance_pvalue

_ND = NormalDist()


def _reference_dsr(sr_annual: float, n_trials: int, n_returns: int,
                   trading_days: int = TRADING_DAYS_PER_YEAR) -> float:
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
    # 附六十八: 容差从 abs=0.02 收紧到 abs=1e-9 —— 原来的 0.02 **正好用来吞掉
    # "实现用 243、参考实现用 252"这个不一致**(实测差值 0.008~0.013)。一个自称
    # 校验"单位口径"的用例,自己两边用了不同的年化常量,等于它守不住它要守的东西。
    assert got == pytest.approx(expect, abs=1e-9), (
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


# ---------------------------------------------------------------------------
# 附六十八 —— 兄弟函数的**同一处单位混用**(修前量级错约 15 个数量级)
# ---------------------------------------------------------------------------
#
# `sharpe_significance_pvalue` 此前是 `z = observed_sharpe / (1/sqrt(T-1))` ——
# 年化 Sharpe 除以**逐期**标准误,z 被放大约 sqrt(243) ≈ 15.6 倍 ⇒ p 被压到 ~0。
# 实测:年化 SR=0.3/T=243 给 1.5e-06(真值 0.382)、SR=0.5/T=250 给 1.6e-15(真值 0.306)。
# 而 `walkforward_report` 印出来的 **Bonferroni p 正是由它算** ⇒ §5 的多重比较惩罚
# 在这一行上等于不存在。
#
# `deflated_sharpe_ratio` 在 2026-10-13 已经修过**同一处**单位混用,兄弟函数没一起修。


def _reference_pvalue(sr_annual: float, n_returns: int,
                      trading_days: int = TRADING_DAYS_PER_YEAR) -> float:
    """独立参考:年化 → 逐期,再 z = SR_per·sqrt(T-1),p = 1 − Φ(z)。"""
    sr = sr_annual / math.sqrt(trading_days)
    return 1.0 - _ND.cdf(sr * math.sqrt(n_returns - 1))


@pytest.mark.parametrize("sr_annual,n_returns", [
    (0.84, 1071), (0.50, 250), (0.30, 243), (2.00, 252), (1.00, 42), (0.10, 100),
])
def test_pvalue_matches_reference(sr_annual: float, n_returns: int) -> None:
    """与独立参考实现一致(逐期口径)。"""
    got = sharpe_significance_pvalue(
        observed_sharpe=sr_annual, n_returns=n_returns,
    )
    expect = _reference_pvalue(sr_annual, n_returns)
    assert got == pytest.approx(expect, abs=1e-9), (
        f"p-value 单位口径不一致: SR_annual={sr_annual}, T={n_returns}\n"
        f"  实现 = {got:.6e}\n  参考 = {expect:.6e}"
    )


def test_pvalue_is_not_absurdly_small_for_a_modest_sharpe() -> None:
    """**非空转钳制**:年化 SR=0.5(252 个观测)是 ~1.4σ,p 必须量级正确。

    这条是对"修好了"的独立确认:一个非零但普通的 Sharpe **不该**给出 1e-15 那种
    p 值 —— 那种数量级只有在"年化被当成逐期"时才会出现。
    """
    p = sharpe_significance_pvalue(observed_sharpe=0.5, n_returns=250)
    assert 0.05 < p < 0.8, f"p={p:.3e} 不合常理(修前的单位混用会给 ~1e-15)"


def test_pvalue_actually_uses_the_annualization_parameter() -> None:
    """`trading_days_per_year` 必须**真的参与换算** —— 修前它被接受但**完全没用**。

    年化常量越大 ⇒ 逐期 Sharpe 越小 ⇒ z 越小 ⇒ p 越大。
    """
    a = sharpe_significance_pvalue(
        observed_sharpe=1.0, n_returns=250, trading_days_per_year=243,
    )
    b = sharpe_significance_pvalue(
        observed_sharpe=1.0, n_returns=250, trading_days_per_year=252,
    )
    assert b > a, "年化常量没有参与换算(修前该参数被忽略)"
    assert abs(b - a) > 1e-6
