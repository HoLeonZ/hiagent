"""§6 守卫：展示工具的汇总指标必须与引擎规范实现**同口径**。

审计 §6 第 6 条点名 `tools/render_top5_presets_html.py`（1162 行，**无任何测试**）
"重新实现了两个引擎的指标与 A/B/C 判定，并带着自己的第三个 metrics 函数"。

**本轮查证后的准确结论**（原表述过重）：
  - 它**调用真的引擎**跑回测（`chase_up.backtest.run_backtest` /
    `short_reversal.engine.run_backtest_v3`），并复用 `load_universe` /
    `compute_indicators` —— 回测本身**没有**被重实现；
  - 重复的是**展示层**：`_compute_short_indicators` 重述逐 bar 指标序列、
    `_build_entry_reasons_*` 重述 A/B/C 文案。消解它需要引擎暴露逐 bar 指标
    序列，属重构而非顺手改 —— 已登记，不在此处假装解决；
  - 但 `_summary_metrics` 的 CAGR 口径确实与引擎**不同**：它用**日历日**
    (`(last-first).days / 365.25`)，引擎用**交易日** (`len(equity) / TRADING_DAYS`)。
    同一次回测于是有两个 CAGR（220 根 bar 下 years≈0.843 vs ≈0.905），页首数字
    与 metrics 对不上，而两边看起来都"很合理"。**已修**为与引擎同口径。

本文件钉住"两处口径一致"，同时也给这个此前**零测试**的 1162 行工具补上第一道
可证伪的守卫。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "render_top5_presets_html.py"

#: 与规范实现重叠的键 —— 这些数字在 HTML 页首与引擎 metrics 里是**同一个**指标，
#: 因此必须逐位一致(1e-12 相对容差)。
OVERLAPPING_KEYS = ("trades", "win_rate", "cagr", "total_return", "final_equity")

_TRADING_DAYS = 220  # 与下面的 equity 行数一致


def _load_tool():
    spec = importlib.util.spec_from_file_location("render_top5", TOOL_PATH)
    assert spec and spec.loader, f"无法加载 {TOOL_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2025-01-01", periods=_TRADING_DAYS, freq="B")
    equity = pd.DataFrame({
        "date": dates,
        "equity": np.linspace(1_000_000.0, 1_150_000.0, _TRADING_DAYS),
        "holdings": np.full(_TRADING_DAYS, 500_000.0),
    })
    trades = pd.DataFrame({
        "net_pnl": [12_000.0, -3_000.0, 8_000.0, 1_500.0],
        "net_return": [0.012, -0.003, 0.008, 0.0015],
        "hold_days": [5, 3, 7, 2],
        "exit_reason": ["TP", "SL", "time", "eod"],
    })
    return trades, equity


def test_tool_module_imports() -> None:
    """零测试的 1162 行工具至少必须能被导入(冒烟)。"""
    mod = _load_tool()
    assert callable(mod._summary_metrics)


@pytest.mark.parametrize("key", OVERLAPPING_KEYS)
def test_tool_summary_matches_canonical_metric(key: str) -> None:
    """同一指标不得有两处定义：展示工具必须与引擎规范实现逐位一致。"""
    from chase_up.backtest import compute_metrics

    trades, equity = _frames()
    canonical = compute_metrics(trades, equity)
    tool = _load_tool()._summary_metrics(trades, equity)

    assert key in tool, f"展示工具缺少指标 {key!r}"
    assert tool[key] == pytest.approx(canonical[key], rel=1e-12), (
        f"§6 VIOLATION: {key} 在展示工具与引擎规范实现之间不一致 —— "
        f"工具={tool[key]!r} 引擎={canonical[key]!r}。"
        "典型成因是年化口径不同(日历日 vs 交易日)。"
    )


def test_cagr_uses_trading_days_not_calendar_days() -> None:
    """钉住口径本身：年数必须按**交易日**计，而不是日历日跨度。

    这条是上面那条的"为什么"：两种口径在 220 根 bar 下给出 years≈0.905 vs ≈0.843,
    CAGR 因此可差数百个基点 —— 两边都"看起来合理",正是最难发现的一类漂移。
    """
    from chase_up.backtest import TRADING_DAYS

    trades, equity = _frames()
    final = float(equity["equity"].iloc[-1])
    expected = (final / 1_000_000.0) ** (1.0 / (len(equity) / TRADING_DAYS)) - 1.0

    calendar_span = (equity["date"].iloc[-1] - equity["date"].iloc[0]).days
    calendar_cagr = (final / 1_000_000.0) ** (1.0 / (calendar_span / 365.25)) - 1.0

    tool = _load_tool()._summary_metrics(trades, equity)
    assert tool["cagr"] == pytest.approx(expected, rel=1e-12)
    assert abs(expected - calendar_cagr) > 1e-4, (
        "夹具没有区分出两种口径 —— 这条断言就失去了意义(换个更长的窗口)"
    )
