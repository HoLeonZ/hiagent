"""V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — Deflated Sharpe Ratio + Bonferroni。

Implements two corrections for multi-parameter-sweep backtest result reporting:

1. **Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado (2014).
   Adjusts observed Sharpe for:
     - Non-Normality (skewness, kurtosis) of returns
     - Autocorrelation (lag-1) of returns
     - Number of trials (k) the strategy was selected from
   When Sharpe looks high but the strategy was cherry-picked from k=1000
   trials, DSR collapses the apparent edge.

2. **Bonferroni Correction** — for multiple hypothesis testing.
   Adjusted p-value = min(p × n_comparisons, 1.0). When the workflow
   compares N parameter configurations, the family-wise error rate is
   preserved by multiplying per-test p-values.

Reference: Bailey, D. & López de Prado, M. (2014). "The Deflated Sharpe
Ratio: Correcting for Selection Bias, Backtest Overfitting, and
Non-Normality." Journal of Portfolio Management 40(5).

Used by walkforward.py for every multi-parameter sweep. Outputs:
  deflated_sharpe_ratio  — adjusted Sharpe accounting for selection bias
  bonferroni_p_value     — adjusted p-value for Sharpe significance
  n_comparisons          — number of configurations tested
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Standard normal inverse CDF (Beasley-Springer-Moro approximation).
    Avoids scipy.stats dependency. Accurate to ~1e-9.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"p must be in (0, 1), got {p}")
    # Beasley-Springer-Moro algorithm
    a = [
        -3.969683028665376e+01, 2.209460984245205e+02,
        -2.759285104469687e+02, 1.383577518672690e+02,
        -3.066479806614716e+01, 2.506628277459239e+00,
    ]
    b = [
        -5.447609879822406e+01, 1.615858368580409e+02,
        -1.556989798598866e+02, 6.680131188771972e+01,
        -1.328068155288572e+01,
    ]
    c = [
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
        4.374664141464968e+00, 2.938163982698783e+00,
    ]
    d = [
        7.784695709041462e-03, 3.224671290700398e-01,
        2.445134137142996e+00, 3.754408661907416e+00,
    ]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


def annualized_sharpe(
    daily_returns: pd.Series | np.ndarray,
    trading_days_per_year: int = 252,
) -> float:
    """Compute annualized Sharpe (no risk-free rate assumed = 0).

    Returns NaN when std is effectively zero (< 1e-12) since Sharpe is
    undefined for constant returns. This guards against numerical noise
    from constant arrays (std ≈ 2e-19 in float64).
    """
    arr = np.asarray(daily_returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return float("nan")
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    if not math.isfinite(std) or std < 1e-12:
        return float("nan")
    return mean / std * math.sqrt(trading_days_per_year)


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    *,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    autocorr_lag1: float = 0.0,
    n_returns: int | None = None,
    trading_days_per_year: int = 252,
) -> dict:
    """V7 (CLAUDE.md §5): Deflated Sharpe Ratio.

    Args:
        observed_sharpe:  Annualized Sharpe from backtest (mean/std × sqrt(252)).
        n_trials:         Number of independent strategy configurations tested.
                          This is the "selection bias" correction — selecting
                          the best Sharpe from k trials inflates the apparent
                          edge by E[max(Z_1, ..., Z_k)] ≈ (1 - γ)Φ⁻¹(1-1/k) +
                          γΦ⁻¹(1-1/(ke)) where γ ≈ 0.5772 (Euler-Mascheroni).
        skewness:         Return distribution skewness (default 0 = normal).
        kurtosis:         Return distribution excess kurtosis (default 3 = normal).
                          Note: scipy uses Fisher (excess); Bailey uses raw kurtosis
                          which equals excess + 3. We accept excess here.
        autocorr_lag1:    Lag-1 autocorrelation of returns (default 0).
                          Positive autocorrelation inflates Sharpe; correction
                          deflates it.
        n_returns:        Number of return observations used to compute Sharpe.
                          Used for SE adjustment.
        trading_days_per_year: 252 for daily bars.

    Returns:
        dict with:
          observed_sharpe:  Input echo
          expected_max_sharpe: E[max(Z_1..Z_k)] under H0
          deflated_sharpe:  PSR(test_sharpe) — probability that true Sharpe
                            exceeds the expected max under null
          dsr_p_value:      1 - dsr (probability that observed is luck)
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")

    # 1) Expected maximum Sharpe under H0 (all true Sharpe = 0) for k trials.
    #    E[max(Z_1..Z_k)] ≈ (1 - γ) Φ⁻¹(1 - 1/k) + γ Φ⁻¹(1 - 1/(ke))
    #    where γ = 0.57721566 (Euler-Mascheroni).
    euler_gamma = 0.5772156649015329
    if n_trials == 1:
        expected_max = 0.0
    else:
        try:
            z1 = _norm_ppf(1 - 1.0 / n_trials)
            z2 = _norm_ppf(1 - 1.0 / (n_trials * math.e))
            expected_max = (1 - euler_gamma) * z1 + euler_gamma * z2
        except (ValueError, ZeroDivisionError, OverflowError):
            expected_max = float("nan")

    # 2026-10-13 (§5 单位一致性修复): observed_sharpe 按本函数约定是**年化**值
    # (见 docstring: mean/std × sqrt(252)), 而下面的 σ̂ 与 expected_max 都是
    # **逐期**量。两者必须换算到同一频率, 否则相当于拿年化 Sharpe 去比逐期阈值,
    # 对中等 Sharpe 会系统性过度折减 (实测: 年化 Sharpe=0.84 / k=19 / T=1071 被
    # 判成 DSR=0.000, 而正确值约 0.44 —— 把「有边际优势」误读成「毫无优势」;
    # 年化 3.0 这种高 Sharpe 反而两法都接近 1, 所以该 bug 长期未被发现)。
    sr = observed_sharpe / math.sqrt(trading_days_per_year)

    # 2) PSR (Probabilistic Sharpe Ratio) — Bailey & López de Prado eq. (4)
    #    PSR(observed) = Φ[(observed - SR*) / σ̂]
    #    where σ̂ adjusts for non-normality and autocorrelation:
    #      σ̂² = (1 - γ3·S + (γ4-1)/4·K²) / (T-1)  (γ3=skewness, γ4=kurtosis)
    #    plus autocorrelation penalty:
    #      σ̂² × (1 + 2·Σρᵢ/(1-ρᵢ))  — for lag-1 this becomes 1+2ρ/(1-ρ)
    if n_returns is None or n_returns < 2:
        # Without T, fall back to plain PSR with no finite-sample correction.
        se = 1.0
    else:
        # Variance from non-normality (Bailey eq. 5, simplified for SR=0)
        nonnorm_var = (1.0 - skewness * sr
                       + (kurtosis - 1.0) / 4.0 * sr ** 2) / (n_returns - 1)
        # Autocorrelation penalty: var × (1 + 2ρ/(1-ρ)) — Bailey eq. (6) lag-1 form
        autocorr_mult = (1.0 + 2.0 * autocorr_lag1 / (1.0 - autocorr_lag1)
                         if abs(autocorr_lag1) < 1.0 else 1.0)
        se = math.sqrt(max(nonnorm_var * autocorr_mult, 1e-12))

    # 3) PSR vs expected_max → DSR
    #    DSR = Φ[(SR_per - E[max]·σ̂) / σ̂] = Φ(SR_per/σ̂ - E[max])
    #    expected_max 已是「以 σ̂ 为单位」的期望最大, 故除以 σ̂ 后直接相减。
    if not math.isfinite(expected_max) or se <= 0:
        dsr = float("nan")
        dsr_p = float("nan")
    else:
        z = sr / se - expected_max
        dsr = _norm_cdf(z)
        dsr_p = 1.0 - dsr

    return dict(
        observed_sharpe=float(observed_sharpe),
        expected_max_sharpe=float(expected_max),
        deflated_sharpe=dsr,
        dsr_p_value=dsr_p,
        n_trials=int(n_trials),
    )


def bonferroni_correct(
    p_values: list[float] | np.ndarray,
    n_comparisons: int,
) -> np.ndarray:
    """V7 (CLAUDE.md §5): Bonferroni-correct p-values for family-wise error.

    Adjusted p = min(p × n_comparisons, 1.0). If original p was already
    significant at α=0.05, the corrected p must also be < 0.05 to reject
    the null hypothesis family-wise.

    Args:
        p_values: per-test p-values (e.g., per-parameter-sweep).
        n_comparisons: total number of comparisons in the family.

    Returns:
        np.ndarray of corrected p-values, same shape as input.
    """
    arr = np.asarray(p_values, dtype=float)
    corrected = np.minimum(arr * n_comparisons, 1.0)
    return corrected


def sharpe_significance_pvalue(
    observed_sharpe: float,
    n_returns: int,
    *,
    trading_days_per_year: int = 252,
) -> float:
    """V7: one-sided p-value for Sharpe ≠ 0 under normality assumption.

    H0: true Sharpe = 0. H1: true Sharpe > 0. Tests observed / SE where
    SE = 1/sqrt(T-1) for daily returns. Returns one-sided p-value.

    ⚠️⚠️ **2026-10-19 (§13.99) 单位口径修正 —— 本函数此前与本模块的兄弟函数不一致。**
    约定与 `deflated_sharpe_ratio` **对齐**: `observed_sharpe` 是**年化**值
    (mean/std × √252), 故先换算回**逐期**再比逐期标准误 `1/√(T−1)`。
    旧实现**直接拿年化值除逐期标准误** ⇒ `z` 被放大 √252 ≈ **15.9 倍**
    ⇒ p 恒 ≈ 0 ⇒ `format_walkforward_stats` 里
    `bonferroni_p = min(sharpe_p × n_comparisons, 1.0)` **恒 ≈ 0**
    ⇒ **§5 的族级校正实际上是空的 (它永远不会拒绝任何东西)。**

    **判据 (为什么这是 bug 而不是"另一种口径")**: `deflated_sharpe_ratio` 在
    `n_trials=1` 时退化成一个纯 PSR 单侧 p 值, **必须**等于本函数的结果。
    实测 (年化 Sharpe 0.6208, T=1386): 前者 **0.0729**, 后者 **0.0000**
    (差约 118 个数量级)。**两个相邻函数、同一个入参、同一个模块 —— 必须相等而差了 118 个数量级。**
    这正与 `deflated_sharpe_ratio` 注释里记的**同一次**单位事故同类
    ("年化 Sharpe=0.84 / k=19 / T=1071 被判成 DSR=0.000, 而正确值约 0.44") ——
    那一次修了它自己, **漏了本函数** (族内不对称, 在 `dna_stats/` 内部)。
    """
    if n_returns < 2:
        return float("nan")
    sr = observed_sharpe / math.sqrt(trading_days_per_year)   # 年化 → 逐期 (§13.99)
    se = 1.0 / math.sqrt(n_returns - 1)
    z = sr / se
    return 1.0 - _norm_cdf(z)
