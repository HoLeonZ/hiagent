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
    # 附七十八 自查:这里原本是 `approx(0.021, abs=0.003)` —— 一个**魔法数 + 宽容差**。
    # 它够用来抓单位 bug(那个会把 p 压到 ~0),但沿用了"当年那版实现"的期望值写法;
    # 改为**独立复算**(stdlib NormalDist,与 test_deflated_sharpe_units.py 同法),
    # 容差随之收紧到 1e-12 —— 于是"实现变了多少"这件事由复算本身约束,不靠人记住一个数。
    from statistics import NormalDist

    from core.trade_schema import TRADING_DAYS_PER_YEAR

    z = (2.0 / (TRADING_DAYS_PER_YEAR ** 0.5)) * ((252 - 1) ** 0.5)
    expect = 1.0 - NormalDist().cdf(z)
    p = sharpe_significance_pvalue(observed_sharpe=2.0, n_returns=252)
    assert p == pytest.approx(expect, abs=1e-12), (
        f"年化 SR=2.0 / T=252 的单侧 p 应为 {expect:.6f}(约 2σ),实际 {p}"
    )
    assert p > 0.01, f"p={p:.3e} 不像「约 2σ」该给的量级(单位混用会给 ~0)"


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
#
# 本册 §13.103 在此处原本钉的是"默认值 == 显式 raw 3.0 且 != excess 0.0"。合并后
# 引擎对 `kurtosis < 1` 直接 fail-fast(见下方附六十九),那条用例里 `kurtosis=0.0`
# 会抛 ValueError ⇒ **判据已被引擎自己淘汰**,不再是"两值可比"。同等强度的替代:
# 附六十九的 `test_default_kurtosis_is_raw_normal_not_excess`(默认 == 换算入口给的
# 原始 3.0) + `test_excess_kurtosis_is_rejected_loudly`(excess 直接报错)。


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
    assert "raw_kurtosis_from_excess" in doc, (
        "§13.103: docstring 应写清 raw 与 excess 的换算入口 "
        "(raw = excess + 3, 规范入口 `raw_kurtosis_from_excess`)"
    )
    assert "We accept excess here" not in doc, (
        "§13.103: 那句自我矛盾的『We accept excess here』又回来了 —— "
        "它与默认值 3.0 和 `(γ4−1)/4` 的 raw 口径直接冲突。"
    )


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
