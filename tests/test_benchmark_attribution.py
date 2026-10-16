"""§5 守卫:Attribution Mandate —— 头条收益必须与**基准相对超额**同时报告。

## 本项是"补空缺",不是"修缺陷"

CLAUDE.md §5 原文:

    **Attribution Mandate:** Headline returns MUST be reported alongside
    benchmark-relative excess return (index or style basket). Pure style-beta
    replication (e.g. size/momentum factor exposure) MUST NOT be presented as alpha.

审计时**全库无实现**(`core/trade_schema.py` / `chase_up/backtest.py` /
`cycle_price_action/metrics.py` / `tools/render_top5_presets_html.py` 都只报裸收益,
`tests/` 中 `benchmark|excess` 零命中),只在报告里打过一个"未归因"标签。
2026-10-16 补齐:基准 = 该窗口 **PIT 宇宙的等权买入持有**(§5 允许 index **or style
basket**;本机活库**没有指数数据**,实测 `v_daily` 只有 SZ/SH/BJ 个股)。

## 为什么要钉"数字的含义"

`excess_return = +3%` 在没说明基准是什么之前**不是一个可引用的结论** ——
与 `sharpe_kind`(附十)、`n_daily_returns`(附三十二)是同一条原则:
一个数字的含义依赖未说明的模型时,就不能只让模型活在 docstring 里。
故 `benchmark_kind` 与它一起发布。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from core.benchmark import (  # noqa: E402
    BENCHMARK_KIND_EQUAL_WEIGHT,
    equal_weight_basket_return,
)


def _panel(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"thscode": c, "date": pd.Timestamp(d), "close": p} for c, d, p in rows]
    )


# ---------------------------------------------------------------------------
# 核心口径(确定性,无 DB)—— 写死/算错的实现必然失败
# ---------------------------------------------------------------------------


def test_equal_weight_basket_return_is_the_mean_of_member_returns() -> None:
    """等权买入持有 = 各标的收益的等权平均。

    夹具:A +10%、B +20%、C 只有一根 bar(无法构成买入持有 ⇒ 排除)
    ⇒ 期望 (0.10 + 0.20)/2 = 0.15,成员数 2。把 C 当成 0 收益会得到 0.10,
    写死 0.0 或常数也都会失败。
    """
    panel = _panel([
        ("600001.SH", "2025-01-02", 100.0), ("600001.SH", "2025-06-30", 110.0),
        ("600002.SH", "2025-01-02", 100.0), ("600002.SH", "2025-06-30", 120.0),
        ("600003.SH", "2025-03-03", 50.0),
    ])
    ret, members = equal_weight_basket_return(panel)
    assert ret == pytest.approx(0.15), (
        f"基准收益 {ret} != 0.15 —— 等权平均口径被破坏(把只有一根 bar 的标的"
        "算成 0 收益会得到 0.10)"
    )
    assert members == 2, "只有一根 bar 的标的必须被排除,且成员数必须如实带出"


def test_basket_uses_first_and_last_available_bar() -> None:
    """标的在窗口内中途才有行情 ⇒ 从它的第一根 bar 起算(不能假装窗口初就持有)。"""
    panel = _panel([
        ("600001.SH", "2025-03-03", 100.0), ("600001.SH", "2025-06-30", 150.0),
    ])
    ret, members = equal_weight_basket_return(panel)
    assert ret == pytest.approx(0.50)
    assert members == 1


def test_empty_panel_is_zero_with_no_members() -> None:
    assert equal_weight_basket_return(pd.DataFrame(columns=["thscode", "date", "close"])) == (0.0, 0)


def test_the_kind_constant_says_what_it_is() -> None:
    """基准的种类必须是**自述**的字符串(读者不该去翻代码才知道拿了什么当基准)。"""
    assert BENCHMARK_KIND_EQUAL_WEIGHT == "equal_weight_pit_universe_buy_and_hold"


# ---------------------------------------------------------------------------
# 引擎层:数字之间必须自洽
# ---------------------------------------------------------------------------

_DB = None


def _db():
    global _DB
    if _DB is None:
        from hiagent_config import get_db_path

        _DB = Path(get_db_path())
    return _DB


_NEEDS_DB = pytest.mark.skipif(
    not _db().exists() or _db().stat().st_size == 0,
    reason=f"local DuckDB 不可用 ({_db()}) — 按 CLAUDE.md §6 skip 而非 error",
)

_START, _END = "2026-03-01", "2026-08-31"


@_NEEDS_DB
def test_chase_up_publishes_benchmark_and_excess() -> None:
    from chase_up.backtest import run_backtest

    m = run_backtest("chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16", _START, _END, _db())["metrics"]
    assert m["benchmark_kind"] == BENCHMARK_KIND_EQUAL_WEIGHT
    assert m["benchmark_members"] > 100, "PIT 宇宙的成员数不可能这么少"
    assert m["excess_return"] == pytest.approx(m["total_return"] - m["benchmark_return"])


@_NEEDS_DB
def test_short_reversal_publishes_benchmark_and_excess() -> None:
    from short_reversal.engine import run_backtest_v3

    m = run_backtest_v3("v50_slope", _START, _END, _db())
    assert m["benchmark_kind"] == BENCHMARK_KIND_EQUAL_WEIGHT
    assert m["benchmark_members"] > 100
    # 注意键名与 chase/uptrend 不同(total_yield vs total_return)—— 这里按本引擎的键断言
    assert m["excess_return"] == pytest.approx(m["total_yield"] - m["benchmark_return"])


# ---------------------------------------------------------------------------
# 结构层:三个引擎都必须发布"基准是什么"
# ---------------------------------------------------------------------------

_ENGINE_FILES = {
    "chase_up": REPO_ROOT / "chase_up" / "backtest.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "backtest.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "engine.py",
}


@pytest.mark.parametrize("engine,path", sorted(_ENGINE_FILES.items()))
def test_engine_publishes_the_benchmark_kind(engine: str, path: Path) -> None:
    """凡发布 `excess_return` 的文件,必须同时发布 `benchmark_kind`。"""
    src = path.read_text(encoding="utf-8")
    assert "excess_return" in src, f"{engine}: 预期发布超额收益"
    assert "benchmark_kind" in src, (
        f"§5 VIOLATION: {engine} 发布超额收益却不说明基准是什么 —— "
        "「+3% 超额」在没有基准定义之前不是可引用的结论"
    )
