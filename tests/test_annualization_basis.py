"""§2/§5 守卫：年化口径必须**单源**,且必须是**交易日**口径。

本仓库此前有**三处**不同口径:

| 位置 | 口径 |
|---|---|
| `chase_up/backtest.py` | `交易日数 / 243` |
| `uptrend_pullback/backtest.py` | `交易日数 / 243`(与前一处同值但**各写一份**) |
| `short_reversal/engine.py` | `日历日跨度 / 365` |
| `dna_stats/*.py` | 默认 `252`(参数,由调用方传) |

日历日 ≠ 交易日。实测同一窗口、同一 10% 总收益下,两种引擎口径给出的 CAGR:

| 窗口 | 交易日/日历日 | 交易日口径 | 日历日口径 | 相对差 |
|---|---|---|---|---|
| 2026-04-01→05-01 | 23 / 30   | 173.7% | 218.9% | **26%** |
| 2026-01-20→03-01 | 29 / 40   | 122.3% | 138.6% | **13%** |
| 2025 全年         | 261 / 364 |  9.28% | 10.03% | **8%**  |

**两边都"看起来合理"** —— 这正是最难发现的一类漂移(同一个指标、两处定义、都自洽)。
引擎侧现统一为 `core.trade_schema.TRADING_DAYS_PER_YEAR`(=243,A 股交易日/年)。

`dna_stats` 的 252 属 §5 统计口径(改动会影响 DSR / Bonferroni 的结论),仍另行登记,
不在本文件强制范围内。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_BACKTESTS = {
    "chase_up": REPO_ROOT / "chase_up" / "backtest.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "backtest.py",
}


def test_canonical_constant_is_trading_days() -> None:
    from core.trade_schema import TRADING_DAYS_PER_YEAR, annualized_years

    assert TRADING_DAYS_PER_YEAR == 243, (
        "A 股交易日/年 ≈ 242~244。改动此值会改变**所有**引擎的年化结果 —— "
        "那是一次全局结果漂移,必须在 PR 里说明,不能顺手改。"
    )
    assert annualized_years(TRADING_DAYS_PER_YEAR) == pytest.approx(1.0)
    assert annualized_years(0) > 0, "下限必须为正(除零保护)"


@pytest.mark.parametrize("engine,path", sorted(ENGINE_BACKTESTS.items()))
def test_engines_use_the_canonical_constant(engine: str, path: Path) -> None:
    """引擎不得各写一份 243 —— 同值不同源就是下一次漂移的起点。"""
    src = path.read_text(encoding="utf-8")
    assert "TRADING_DAYS_PER_YEAR" in src and "core.trade_schema" in src, (
        f"{engine}: 年化常量必须来自 core.trade_schema(§2 单源)"
    )
    assert "TRADING_DAYS = 243" not in src, (
        f"{engine}: 又出现了本地写死的 243 —— 回到同值不同源"
    )


def test_all_engines_agree_on_the_annualization_constant() -> None:
    """三个引擎的常量必须**同一个值**(直接比对,而不是各自看源码)。"""
    from chase_up.backtest import TRADING_DAYS as chase_days
    from core.trade_schema import TRADING_DAYS_PER_YEAR
    from uptrend_pullback.backtest import TRADING_DAYS as uptrend_days

    assert chase_days == uptrend_days == TRADING_DAYS_PER_YEAR


def test_short_reversal_annualizes_on_trading_days_not_calendar_days() -> None:
    """short_reversal 必须已切到交易日口径 —— 日历日口径就是那个 26% 偏差的来源。"""
    src = (REPO_ROOT / "short_reversal" / "engine.py").read_text(encoding="utf-8")
    assert "DAYS_PER_YEAR" not in src, (
        "short_reversal 仍在用日历日年化(`DAYS_PER_YEAR = 365`)"
    )
    assert "annualized_years" in src, "短反转未使用规范的交易日年化助手"


def test_short_reversal_metrics_expose_the_annualization_denominator() -> None:
    """口径随产物发布:`cagr` 旁边必须有它的分母(交易日数)。

    与 cycle 的 `account_model` 字段同一理由 —— 一个数字的含义依赖未说明的模型时,
    就不能只让模型活在 docstring 里。
    """
    from core.trade_schema import TRADING_DAYS_PER_YEAR
    from short_reversal.engine import INITIAL_CAPITAL, _metrics_from_holder

    holder = {"cash": INITIAL_CAPITAL * 1.10, "trades": [], "max_dd": 0.0}
    cfg = {"_name": "synthetic"}
    n_days = 20
    m = _metrics_from_holder(
        holder, "2025-01-01", "2025-01-31", cfg, n_trading_days=n_days
    )

    assert m["n_trading_days"] == n_days
    # CAGR 必须按**交易日**年化;日历日年化会给出更大的值(同一收益、更短的年数)
    expected = 1.10 ** (1.0 / (n_days / TRADING_DAYS_PER_YEAR)) - 1.0
    assert m["cagr"] == pytest.approx(expected, rel=1e-12)

    calendar_years = 30 / 365.0
    calendar_cagr = 1.10 ** (1.0 / calendar_years) - 1.0
    assert abs(expected - calendar_cagr) > 1e-3, (
        "夹具没有区分出两种口径,这条断言就失去意义了(换个更短的窗口)"
    )
