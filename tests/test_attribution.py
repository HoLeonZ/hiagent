"""§5 Attribution Mandate 守卫（审计 P3，2026-10-15）。

CLAUDE.md §5:"Headline returns MUST be reported alongside benchmark-relative
excess return (index or style basket). Pure style-beta replication MUST NOT be
presented as alpha."

本文件锁定归因机制本身(复利区间收益、超额、beta、以及"无法计算时不伪造")。
**注意:机制正确 ≠ §5 已满足** —— 本地行情库没有任何指数序列,故归因当前无法真正
计算;该数据缺口由 `test_benchmark_data_gap_is_registered` 显式登记,避免它再次
退化为"没人提起所以不存在"。
"""
from __future__ import annotations

import math
from pathlib import Path
from statistics import NormalDist

import pytest

from dna_stats.attribution import (
    BENCHMARK_NONE_ACKNOWLEDGED,
    BenchmarkUnavailable,
    attribute,
    compound_return,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 机制
# ---------------------------------------------------------------------------


def test_compound_return_matches_manual_product() -> None:
    assert compound_return([0.1, -0.1]) == pytest.approx(1.1 * 0.9 - 1.0)
    assert compound_return([]) == 0.0


def test_excess_return_is_strategy_minus_benchmark_in_compound_terms() -> None:
    s = [0.02, 0.01, -0.005, 0.03]
    b = [0.01, 0.01, 0.0, 0.01]
    a = attribute(s, b, benchmark_id="000300.SH")
    assert a.strategy_return == pytest.approx(compound_return(s))
    assert a.benchmark_return == pytest.approx(compound_return(b))
    assert a.excess_return == pytest.approx(a.strategy_return - a.benchmark_return)
    assert a.n_periods == 4


def test_beta_matches_an_independent_ols_computation() -> None:
    """beta = cov/var 与独立复算一致(不依赖 numpy)。"""
    s = [0.02, -0.01, 0.015, 0.03, -0.005]
    b = [0.01, -0.005, 0.008, 0.012, 0.0]
    n = len(s)
    ms, mb = sum(s) / n, sum(b) / n
    cov = sum((x - ms) * (y - mb) for x, y in zip(s, b)) / (n - 1)
    var = sum((y - mb) ** 2 for y in b) / (n - 1)
    a = attribute(s, b, benchmark_id="000300.SH")
    assert a.beta == pytest.approx(cov / var)


def test_beta_is_none_when_benchmark_has_zero_variance() -> None:
    """常量基准无法定义 beta —— 必须返回 None,不得伪造成 0。

    静默给 0 会把「无法计算」伪装成「无市场暴露」,而后者是一个**结论**。
    """
    a = attribute([0.02, 0.01, -0.01], [0.01, 0.01, 0.01], benchmark_id="const")
    assert a.beta is None
    assert a.excess_return == pytest.approx(a.strategy_return - a.benchmark_return)


def test_beta_adjusted_alpha_separates_replication_from_skill() -> None:
    """§5 的真正判据:**beta 调整后**的 alpha。

    原始超额(excess)不足以区分"有技术"与"只是承担了更多市场暴露" —— 纯 2× beta
    复制的原始超额可以显著为正(复利效应下 2× 逐期不等于 2× 区间)。把基准按 beta
    缩放后再比,才得到 §5 所指的 alpha:
        alpha_period = (r_s - r_b) - (beta - 1) * r_b        # 逐期
    纯 beta 复制下它恒为 0;真有技术时为正。
    """
    b = [0.01, -0.02, 0.03, 0.005, -0.01]

    # (a) 纯 2× beta → beta 调整后 alpha 应为 0
    s_pure = [2 * x for x in b]
    a = attribute(s_pure, b, benchmark_id="000300.SH")
    assert a.beta == pytest.approx(2.0)
    alpha_pure = [(x - y) - (a.beta - 1) * y for x, y in zip(s_pure, b)]
    assert max(abs(v) for v in alpha_pure) < 1e-12, (
        f"纯 beta 复制的 beta 调整后 alpha 应为 0,实际 {alpha_pure}"
    )

    # (b) 真有技术(基准 + 1%/期)→ beta 调整后 alpha 恒为 +1%/期
    s_skill = [x + 0.01 for x in b]
    a2 = attribute(s_skill, b, benchmark_id="000300.SH")
    assert a2.beta == pytest.approx(1.0)
    alpha_skill = [(x - y) - (a2.beta - 1) * y for x, y in zip(s_skill, b)]
    assert all(abs(v - 0.01) < 1e-12 for v in alpha_skill)

    # 这正是 §5 要防的:纯 beta 复制的**原始**超额为正,却毫无 alpha
    assert a.excess_return > 0.0


# ---------------------------------------------------------------------------
# fail-fast:无法计算时不得返回残缺结果
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kwargs", [
    {"strategy_returns": [], "benchmark_returns": []},
    {"strategy_returns": [0.1], "benchmark_returns": []},
    {"strategy_returns": [0.1, 0.2], "benchmark_returns": [0.1]},
])
def test_missing_or_misaligned_inputs_fail_fast(kwargs) -> None:
    with pytest.raises(BenchmarkUnavailable):
        attribute(benchmark_id="000300.SH", **kwargs)


def test_acknowledged_absence_is_explicit_and_fails_fast() -> None:
    """显式登记「无基准」也不能蒙混过关 —— 它必须让调用方知道结论未归因。"""
    assert BENCHMARK_NONE_ACKNOWLEDGED != ""
    with pytest.raises(BenchmarkUnavailable):
        attribute([0.1], [0.05], benchmark_id=BENCHMARK_NONE_ACKNOWLEDGED)
    with pytest.raises(BenchmarkUnavailable):
        attribute([0.1], [0.05], benchmark_id="")


# ---------------------------------------------------------------------------
# 数据缺口登记(§5 在当前数据条件下无法满足)
# ---------------------------------------------------------------------------


def test_benchmark_data_gap_is_registered() -> None:
    """本地行情库没有指数序列 → §5 归因当前无法计算。此测试**登记**该缺口。

    登记而非跳过:一个"没人提起所以不存在"的缺口,会在下一次汇报里重新变成
    「绝对收益很好看」。基准可经 CLI 取得(`hithink-finance index history`),但
    取数属联网 + 写入行情库的动作,且**选哪个基准是研究决策**。
    """
    import duckdb

    from hiagent_config import get_db_path

    db = get_db_path()
    if not Path(db).exists() or Path(db).stat().st_size == 0:
        pytest.skip(f"§6: 本地 DuckDB 不可用({db})")

    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT asset_type FROM dim_symbol ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    types = {r[0] for r in rows}
    assert types, "dim_symbol 为空 —— 数据层异常"
    if types == {"a-share"}:
        pytest.skip(
            "§5 GAP REGISTERED: 行情库只有个股(asset_type 全为 a-share),无任何指数"
            "序列 → 归因无法计算。补齐:`hithink-finance index history --code <index>`;"
            "选哪个基准是研究决策。在补齐之前,只报绝对收益的结论必须标注为『未归因』。"
        )
    # 若将来引入了指数,本测试自然转为检查基准可用
    assert any("index" in str(t) for t in types), (
        f"asset_type 出现了非个股类别但不像指数:{types} —— 请更新本登记"
    )
