"""Tests for V7 (CLAUDE.md §5) Deflated Sharpe Ratio + Bonferroni."""
from __future__ import annotations

import numpy as np
import pytest

from dna_stats.deflated import (
    annualized_sharpe,
    bonferroni_correct,
    raw_kurtosis_from_excess,
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
    # 附六十九: `kurtosis` 要的是**原始**峰度(正态 = 3)。下面这个 5.0 即"超额 2"
    # 的厚尾分布 —— 写成 `raw_kurtosis_from_excess(2.0)` 是为了让口径**在调用点可见**,
    # 而不是靠读者记得"这里要不要 +3"。
    res = deflated_sharpe_ratio(
        observed_sharpe=1.5, n_trials=50,
        skewness=-0.5, kurtosis=raw_kurtosis_from_excess(2.0),
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
    """年化 Sharpe=2.0、252 个观测 ⇒ **约 2σ**,p ≈ 0.021(不是"极低")。

    附六十八 更正:本用例原断言 `p < 0.001`,原注释写"高 Sharpe + 大样本 → 极低
    p-value"。而按本模块的约定 `observed_sharpe` 是**年化**值 ⇒ 逐期 Sharpe =
    2.0/sqrt(243) ≈ 0.128,z ≈ 2.0 ⇒ 单侧 p ≈ 0.021。

    旧实现把年化 Sharpe 直接除以逐期标准误(`1/sqrt(T-1)`),z 被放大约
    `sqrt(243) ≈ 15.6` 倍 ⇒ p 被压到 ~0 —— **那条 `< 0.001` 的断言正是这个单位错误
    的另一种写法**(它把 bug 写成了期望,于是修复反而会打红它)。
    """
    p = sharpe_significance_pvalue(observed_sharpe=2.0, n_returns=252)
    assert p == pytest.approx(0.021, abs=0.003), (
        f"年化 SR=2.0 / T=252 的单侧 p 应 ≈0.021(约 2σ),实际 {p}"
    )


def test_sharpe_significance_zero():
    """V7: Sharpe=0 → p ≈ 0.5 (无显著差异)。"""
    p = sharpe_significance_pvalue(observed_sharpe=0.0, n_returns=100)
    assert p == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# 附六十九 —— `kurtosis` 的**口径合同**:docstring 曾写"We accept excess",
#              而实现按**原始**峰度用(default 3.0、公式 (γ4−1)/4)
# ---------------------------------------------------------------------------
#
# 当前**行为是对的**(与论文 eq.(5) 一致:γ4=3 时给 0.5),错的是合同:
# 参数默认 3.0 是原始峰度,而 docstring 说"接受超额"。谁按 docstring 传"超额峰度"
# (正态 = 0)就会静默算出一个错的 DSR。故:
#   1) docstring 改成明确说**原始**,并给出换算入口;
#   2) 对数学上不可能是原始峰度的值(< 1)**fail-fast**,并指出多半是传了超额;
#   3) 提供有名字的换算 `raw_kurtosis_from_excess`,免得调用方各写一个 "+3"。


def test_default_kurtosis_is_raw_normal_not_excess() -> None:
    """默认值 3.0 必须被当作**原始**峰度使用(等价于"超额 0")。"""
    a = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=10, n_returns=250)
    b = deflated_sharpe_ratio(
        observed_sharpe=1.0, n_trials=10, n_returns=250,
        kurtosis=raw_kurtosis_from_excess(0.0),      # 显式:超额 0 ⇒ 原始 3
    )
    assert a["deflated_sharpe"] == pytest.approx(b["deflated_sharpe"], abs=1e-12), (
        "默认口径与'超额 0 ⇒ 原始 3'不一致 —— docstring 与实现又分家了"
    )


def test_excess_kurtosis_is_rejected_loudly() -> None:
    """传超额峰度(正态 = 0)⇒ fail-fast,并指出该怎么办。

    原始峰度恒 ≥ 1(`E[X⁴] ≥ E[X²]²`),故 < 1 不可能是原始值。静默算错的代价是
    一个看起来正常的 DSR —— 宁可报错。
    """
    with pytest.raises(ValueError, match="raw_kurtosis_from_excess"):
        deflated_sharpe_ratio(
            observed_sharpe=1.0, n_trials=10, n_returns=250, kurtosis=0.0,
        )


def test_raw_kurtosis_helper() -> None:
    """换算纯函数:正态(超额 0)→ 3;厚尾(超额 2)→ 5。"""
    assert raw_kurtosis_from_excess(0.0) == pytest.approx(3.0)
    assert raw_kurtosis_from_excess(2.0) == pytest.approx(5.0)
    assert raw_kurtosis_from_excess(-1.0) == pytest.approx(2.0)   # 薄尾


def test_bonferroni_rejects_impossible_comparison_counts() -> None:
    """§0:`n_comparisons < 1` ⇒ fail-fast(否则会把校正整个取消掉)。

    实测(修前):`n_comparisons=0` ⇒ 所有 p 变成 **0.0**(读作"极其显著");
    `n_comparisons=-1` ⇒ 所有 p 变成**负数**(任何 `p < 0.05` 都通过)。
    即"用一个不可能的参数把多重比较校正取消掉",而输出看起来更"显著"。
    """
    for bad in (0, -1, -100):
        with pytest.raises(ValueError, match="n_comparisons"):
            bonferroni_correct([0.4], n_comparisons=bad)
    # 反向:合法输入不受影响
    assert bonferroni_correct([0.4], n_comparisons=1)[0] == pytest.approx(0.4)
    assert bonferroni_correct([0.4], n_comparisons=10)[0] == pytest.approx(1.0)
