"""§2 守卫:`sharpe` 在不同引擎里**不是同一个量** —— 定义必须随产物发布。

| 引擎 | `sharpe` 实际是什么 |
|---|---|
| `chase_up` / `uptrend_pullback` | **日收益序列**的 Sharpe:`mean(daily_rets)/std(daily_rets) × √243` |
| `short_reversal` | **逐笔 net** 的 `mean/std × √(min(n_trades, 250))` —— 交易级比率 |
| `cycle_price_action` | `None`(横截面研究,无法定义 —— 诚实地不算) |

同名不同量,而仓库里的 sweep 脚本会**按 `sharpe` 排序**(如 `sorted_by_sharpe`)。
跨引擎把这两个数字放在一起比较是**无意义**的 —— 但仅看键名 `sharpe` 完全看不出来,
caveat 只埋在 `_approx_sharpe` 的 docstring 里。

这与附八(`total_pnl` 缺分母)、附十(CAGR 口径)同一条原则:
**一个数字的含义依赖未被说明的模型时,就不能只让模型活在 docstring 里。**
故在产物里显式给出 `sharpe_kind`。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

DAILY = "daily_returns_annualized"
PER_TRADE = "per_trade_ratio_approx"

PUBLISHING_ENGINES = {
    "chase_up": REPO_ROOT / "chase_up" / "backtest.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "backtest.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "engine.py",
}


def _equity(n: int = 30) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="B"),
        "equity": np.linspace(1_000_000.0, 1_100_000.0, n),
        "holdings": np.full(n, 500_000.0),
    })


def test_the_two_sharpe_kinds_are_actually_different() -> None:
    """标注必须真的区分两者 —— 否则它只是多了一个不起作用的键。"""
    assert DAILY != PER_TRADE


@pytest.mark.parametrize("module_path", ["chase_up.backtest", "uptrend_pullback.backtest"])
def test_daily_return_engines_label_their_sharpe(module_path: str) -> None:
    import importlib

    from core.trade_schema import TRADING_DAYS_PER_YEAR  # noqa: F401  (口径同源)

    compute_metrics = importlib.import_module(module_path).compute_metrics
    trades = pd.DataFrame({
        "net_pnl": [12_000.0, -3_000.0], "net_return": [0.012, -0.003],
        "hold_days": [5, 3], "exit_reason": ["TP", "SL"],
    })
    for m in (compute_metrics(trades, _equity()), compute_metrics(trades.iloc[0:0], _equity())):
        assert m["sharpe_kind"] == DAILY, (
            f"{module_path}: `sharpe` 是日收益年化,必须标 {DAILY!r}"
        )


def test_short_reversal_labels_its_sharpe_as_a_per_trade_ratio() -> None:
    """short_reversal 的 `sharpe` 是**逐笔比率**,不能与日收益 Sharpe 相提并论。"""
    from short_reversal.engine import INITIAL_CAPITAL, _metrics_from_holder

    holder = {
        "cash": INITIAL_CAPITAL * 1.05,
        # §2: 合成 holder 也要带 final_nav(无未平仓 → nav == cash)
        "final_nav": INITIAL_CAPITAL * 1.05,
        "max_dd": 0.01,
        "trades": [{"net": 0.01, "hold_days": 3, "exit_reason": "TP"},
                   {"net": -0.004, "hold_days": 2, "exit_reason": "SL"}],
    }
    m = _metrics_from_holder(
        holder, "2025-01-01", "2025-02-01", {"_name": "synthetic"}, n_trading_days=20
    )
    assert m["sharpe_kind"] == PER_TRADE


@pytest.mark.parametrize("engine,path", sorted(PUBLISHING_ENGINES.items()))
def test_every_engine_publishing_sharpe_also_publishes_its_kind(
    engine: str, path: Path,
) -> None:
    """凡发布 `sharpe` 的文件,都必须同时发布 `sharpe_kind`(不得只留 docstring)。"""
    src = path.read_text(encoding="utf-8")
    sharpe_lines = [ln for ln in src.splitlines() if '"sharpe":' in ln]
    assert sharpe_lines, f"{engine}: 预期发布 `sharpe`"
    assert '"sharpe_kind"' in src, (
        f"§2 VIOLATION: {engine} 发布 `sharpe` 却不说明它是哪一种 —— "
        "跨引擎比较会得到错误结论。"
    )
