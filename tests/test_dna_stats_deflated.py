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
    """⚠️ 口径是**年化** (§13.99 修正) —— 年化 2.0 / T=252 ⇒ 逐期 2.0/√252 = 0.1262,
    逐期 SE = 1/√251 = 0.0631 ⇒ z = 1.9998 ⇒ p ≈ 0.0227。

    ⚠️ **本测试此前断言的是 `p < 0.001`** —— 那个期望值**冻结了逐期口径**:
    把年化值直接除逐期标准误 ⇒ z 放大 √252 ≈ 15.9 倍。它与同模块的
    `deflated_sharpe_ratio`(显式把入参当年化)、以及**唯一的生产调用点**
    (`walkforward_report.format_walkforward_stats` 把**同一行算出的同一个** `median_sharpe`
    喂给两者)**相矛盾**。
    ⇒ 按 §13.120: 这次是**代码错**, 不是"尺子认不出新形态"; 处置是改代码 + **把口径钉死**
    (钉精确值比钉不等式更强)。
    """
    p = sharpe_significance_pvalue(observed_sharpe=2.0, n_returns=252)
    assert p == pytest.approx(0.022965, abs=2e-4), (
        f"年化 2.0 / T=252 应得 p≈0.022965, 实测 {p}. "
        f"若它变成 ~1e-100 量级 ⇒ 年化→逐期的换算被去掉了 (§13.99 的单位事故复发)。"
    )


def test_sharpe_significance_zero():
    """V7: Sharpe=0 → p ≈ 0.5 (无显著差异)。"""
    p = sharpe_significance_pvalue(observed_sharpe=0.0, n_returns=100)
    assert p == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# §13.99: 两个 Sharpe 函数**必须**用同一套单位
# ---------------------------------------------------------------------------


def test_the_two_sharpe_functions_use_the_same_units() -> None:
    """★ 跨函数恒等式 (§13.99): `deflated_sharpe_ratio` 在 `n_trials=1` 时退化成一个
    PSR 单侧 p 值, **必须**等于 `sharpe_significance_pvalue` 的返回值。

    两者在 `dna_stats/` 里**同模块**、在 `format_walkforward_stats` 里被
    **相邻两行、同一个变量** `median_sharpe` 调用 —— 所以"它们不相等"等价于
    "**至少有一个把单位搞错了**", 而不是"两种合理口径"。

    修前实测 (年化 0.6208, T=1386): 前者 **0.0729**, 后者 **0.0000** (差 ~118 个数量级)。
    """
    for sr in (0.2, 0.5, 1.0, 2.0, 3.0):
        for t in (100, 252, 1000, 1386, 2000):
            a = deflated_sharpe_ratio(observed_sharpe=sr, n_trials=1, n_returns=t)["dsr_p_value"]
            b = sharpe_significance_pvalue(observed_sharpe=sr, n_returns=t)
            assert a == pytest.approx(b, abs=5e-3), (
                f"§13.99: 年化 SR={sr}, T={t} ⇒ DSR(k=1).p={a} 而 "
                f"sharpe_significance_pvalue={b} —— 两者**必须相等**。\n"
                f"⇒ 有一个函数把 `observed_sharpe` 当成了另一种频率。"
            )
    # 反空转: 至少一格必须**不是** 0 / 1 的退化值, 否则本判据是在比对两个常数。
    mid = [
        (sr, t)
        for sr in (0.2, 0.5, 1.0, 2.0, 3.0)
        for t in (100, 252, 1000, 1386, 2000)
        if 1e-3 < sharpe_significance_pvalue(observed_sharpe=sr, n_returns=t) < 1 - 1e-3
    ]
    assert len(mid) >= 5, (
        f"§13.99: 只有 {len(mid)} 格落在 (0,1) 开区间内 ⇒ 网格几乎全在退化区, "
        f"上面的恒等式在比 0==0 或 1==1。请把网格挪到有分辨力的区间。"
    )


def test_bonferroni_can_actually_reject() -> None:
    """反空转 (§13.99): §5 的族级校正**必须能拒绝** —— 否则它是装饰品。

    修前 `sharpe_p` 恒 ≈ 0 ⇒ `bonferroni_p = min(p×k, 1)` 恒 ≈ 0
    ⇒ **对任意 k 都"通过"** ⇒ 那不是一个校正。
    本判据要求: 一个中等年化 Sharpe, 在**足够大**的 k 上必须被推过 0.05。
    """
    p0 = sharpe_significance_pvalue(observed_sharpe=0.62, n_returns=1386)
    assert p0 > 1e-4, (
        f"§13.99: 年化 SR=0.62 / T=1386 的未折减 p 只有 {p0:.2e} —— 又是被放大过的 z。"
    )
    assert min(p0 * 162, 1.0) > 0.05, (
        "§13.99: 累积 162 次比较下 Bonferroni 仍 < 0.05 ⇒ 校正没有把任何东西拒掉。"
        f"(实测 修后 = {min(p0*162,1.0):.4f})"
    )


# ---------------------------------------------------------------------------
# §13.103: `kurtosis` 的口径必须与代码一致 (raw, 不是 excess)
# ---------------------------------------------------------------------------


def test_kurtosis_default_pins_the_raw_convention() -> None:
    """★ 用"**必须相等**"钉住口径 —— 这正是 §13.99/§13.102 反复奏效的手法。

    `σ̂² = (1 − γ3·sr + (γ4−1)/4·sr²)/(T−1)` 里的 γ4 是 **raw** 峰度 (正态 = 3)。
    ⇒ 显式传 `kurtosis=3.0` 必须与**不传**逐位相同; 传 `0.0` (excess 的正态值) 必须**不同**。
    一旦有人把实现改成 excess 口径, 本条立刻红。
    """
    sr, k, t = 0.8, 20, 600
    d_default = deflated_sharpe_ratio(observed_sharpe=sr, n_trials=k, n_returns=t)
    d_raw3 = deflated_sharpe_ratio(observed_sharpe=sr, n_trials=k, n_returns=t, kurtosis=3.0)
    d_exc0 = deflated_sharpe_ratio(observed_sharpe=sr, n_trials=k, n_returns=t, kurtosis=0.0)
    assert d_default == d_raw3, (
        "§13.103: 默认值不是 raw-正态(3) —— 口径变了, 所有历史 DSR 的含义跟着变。"
    )
    assert d_exc0 != d_default, (
        "§13.103: 传 excess 的正态值(0) 与默认(3) 结果相同 ⇒ 两者已不可区分, "
        "本判据失效 (要么实现改了, 要么该参数不再被使用)。"
    )


def test_following_the_old_wording_would_be_optimistic() -> None:
    """旧措辞邀请调用方传 **excess**; 那会把 DSR 往**高**处推 (危险方向)。

    本条把这个方向**钉住**: 传比 raw 小的数 ⇒ `(γ4−1)/4` 小 ⇒ 方差小 ⇒ `se` 小
    ⇒ `z` 大 ⇒ **DSR 高**。
    """
    sr, k, t, raw = 1.5, 20, 600, 18.0
    d_raw = deflated_sharpe_ratio(observed_sharpe=sr, n_trials=k, n_returns=t, kurtosis=raw)
    d_exc = deflated_sharpe_ratio(observed_sharpe=sr, n_trials=k, n_returns=t, kurtosis=raw - 3.0)
    assert d_exc["deflated_sharpe"] > d_raw["deflated_sharpe"], (
        "§13.103: 传 excess(比 raw 小 3) 应当把 DSR **推高** (方差被低估)。"
        f"实测 raw={d_raw['deflated_sharpe']:.6f} vs excess={d_exc['deflated_sharpe']:.6f}"
    )


def test_the_docstring_states_the_raw_convention() -> None:
    """文档必须说清口径 —— 这是一条**文档级**判据 (代码级判据见上面两条)。

    ⚠️ 本册的教训: **文本判据容易被"提到"满足**。所以这里只做**存在性**声明,
    真正的承重判据是上面那两条**行为式**的。
    """
    doc = deflated_sharpe_ratio.__doc__ or ""
    assert "raw" in doc.lower(), "§13.103: docstring 没说 `kurtosis` 是 raw 口径"
    assert "excess + 3" in doc or "raw = excess + 3" in doc, (
        "§13.103: docstring 应写清 raw 与 excess 的换算关系 (raw = excess + 3)"
    )
    assert "We accept excess here" not in doc, (
        "§13.103: 那句自我矛盾的『We accept excess here』又回来了 —— "
        "它与默认值 3.0 和 `(γ4−1)/4` 的 raw 口径直接冲突。"
    )
