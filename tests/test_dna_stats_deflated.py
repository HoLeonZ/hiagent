"""Tests for V7 (CLAUDE.md §5) Deflated Sharpe Ratio + Bonferroni."""
from __future__ import annotations

import numpy as np
import pytest

from dna_stats.deflated import (
    annualized_sharpe,
    bonferroni_correct,
    deflated_sharpe_ratio,
    sharpe_significance_pvalue,
)


def test_annualized_sharpe_basic():
    """V7: annualized_sharpe with known returns."""
    # mean=0.001, std=0.01 → Sharpe_daily ≈ 0.1 → annualized ≈ 1.58
    rng = np.random.default_rng(42)
    daily = rng.normal(0.001, 0.01, size=252)
    s = annualized_sharpe(daily)
    assert 0.5 < s < 3.0    # sanity bound


def test_annualized_sharpe_constant_returns_zero():
    """V7: 0 std → NaN (Sharpe undefined)."""
    arr = np.full(100, 0.001)
    # constant returns with ddof=1 std returns NaN, mean/std = NaN
    assert not np.isfinite(annualized_sharpe(arr))


def test_deflated_sharpe_zero_trials_raises():
    """V7: n_trials must be >= 1."""
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(observed_sharpe=2.0, n_trials=0)


def test_deflated_sharpe_single_trial_equals_observed():
    """V7: n_trials=1 → expected_max=0, DSR ≈ PSR(observed)。

    2026-10-13 修正: `observed_sharpe` 是**年化**值 —— 见 deflated_sharpe_ratio 的
    docstring ("Annualized Sharpe ... mean/std × sqrt(252)") 以及实际调用方
    walkforward_report.format_walkforward_stats(传的是 metrics 里的年化 median_sharpe)。

    年化 2.0 在 T=252 下的 PSR = Φ(SR_per·√(T-1)/√(1+SR_per²/2)) ≈ Φ(1.99) ≈ 0.977。
    原断言 >0.99 的注释写的是 `z = 2 / sqrt(252-1) ≈ 31.6` —— 那是把 2.0 当成**逐期**
    Sharpe 才成立的算法, 与函数文档和所有调用口径都不一致 (该单位混用已由
    tests/test_deflated_sharpe_units.py 的独立 stdlib 复算证伪)。
    """
    res = deflated_sharpe_ratio(observed_sharpe=2.0, n_trials=1, n_returns=252)
    assert res["expected_max_sharpe"] == 0.0
    assert res["deflated_sharpe"] == pytest.approx(0.977, abs=0.01)


def test_deflated_sharpe_more_trials_lower():
    """V7: n_trials 越大, expected_max 越大 → DSR 越小 (selection bias 严)。"""
    r1 = deflated_sharpe_ratio(2.0, n_trials=1, n_returns=252)
    r1000 = deflated_sharpe_ratio(2.0, n_trials=1000, n_returns=252)
    assert r1000["expected_max_sharpe"] > r1["expected_max_sharpe"]
    assert r1000["deflated_sharpe"] < r1["deflated_sharpe"]


def test_deflated_sharpe_negative_observed_low_dsr():
    """V7: 负 observed Sharpe → DSR 接近 0 (确实差)。"""
    res = deflated_sharpe_ratio(-2.0, n_trials=10, n_returns=252)
    assert res["deflated_sharpe"] < 0.05


def test_deflated_sharpe_skewness_kurtosis_input():
    """V7: 接受 skewness/kurtosis/autocorr_lag1 参数, 不报错。
    这覆盖了 non-normality correction 路径。
    """
    res = deflated_sharpe_ratio(
        observed_sharpe=1.5, n_trials=50,
        skewness=-0.5, kurtosis=5.0,
        autocorr_lag1=0.1, n_returns=252,
    )
    assert "deflated_sharpe" in res
    assert 0.0 <= res["deflated_sharpe"] <= 1.0


def test_bonferroni_basic():
    """V7: Bonferroni 把 p × n_comparisons, 上限 1.0。"""
    pvals = [0.01, 0.04, 0.03]
    corrected = bonferroni_correct(pvals, n_comparisons=10)
    assert corrected[0] == pytest.approx(0.10)
    assert corrected[1] == pytest.approx(0.40)
    assert corrected[2] == pytest.approx(0.30)


def test_bonferroni_caps_at_one():
    """V7: Bonferroni correction 上限为 1.0。"""
    pvals = [0.5, 0.99]
    corrected = bonferroni_correct(pvals, n_comparisons=10)
    assert corrected[0] == pytest.approx(1.0)
    assert corrected[1] == pytest.approx(1.0)


def test_bonferroni_significant_preserved():
    """V7: 若单测 p < α/n, Bonferroni 后仍 < α。"""
    # 20 comparisons, α=0.05 → threshold 0.0025
    pvals = [0.001]
    corrected = bonferroni_correct(pvals, n_comparisons=20)
    assert corrected[0] == pytest.approx(0.02)
    assert corrected[0] < 0.05    # family-wise significant


def test_sharpe_significance_basic():
    """V7: 高 Sharpe + 大样本 → 极低 p-value。"""
    p = sharpe_significance_pvalue(observed_sharpe=2.0, n_returns=252)
    assert p < 0.001


def test_sharpe_significance_zero():
    """V7: Sharpe=0 → p ≈ 0.5 (无显著差异)。"""
    p = sharpe_significance_pvalue(observed_sharpe=0.0, n_returns=100)
    assert p == pytest.approx(0.5, abs=0.01)
