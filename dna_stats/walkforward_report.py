"""V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — Walkforward DSR/Bonferroni report.

Wraps dna_stats.deflated to format walkforward results with statistical
corrections for multi-parameter sweeps.

Usage:
    from dna_stats.walkforward_report import format_walkforward_stats

    df = walkforward_run(...)         # columns: total_return, sharpe, ...
    n_comparisons = 50                # from preset grid size
    text = format_walkforward_stats(
        df, n_comparisons=n_comparisons,
        trading_days_per_window=40,   # §13.102: 必填, 由调用方实测
    )
    print(text)

Output includes:
  - Window count, win-rate, median/mean/min Sharpe
  - Deflated Sharpe Ratio (DSR) using observed median Sharpe vs k trials
  - Bonferroni-corrected p-value for Sharpe ≠ 0
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from dna_stats.deflated import (
    _norm_cdf,                 # internal but acceptable; same module
    deflated_sharpe_ratio,
    sharpe_significance_pvalue,
)


def format_walkforward_stats(
    df: pd.DataFrame,
    *,
    n_comparisons: int = 1,
    trading_days_per_year: int = 252,
    trading_days_per_window: int,
) -> str:
    """Format walkforward result DataFrame with DSR + Bonferroni.

    df expected columns (any subset):
      total_return: window total return (e.g. 0.21 = +21%)
      sharpe:       annualized Sharpe
      max_dd:       max drawdown (negative)
      trades:       trade count

    n_comparisons is the number of parameter configurations that were
    backtested before selecting the winner — this is the "k" in DSR's
    selection-bias correction. Set n_comparisons=1 when reporting a
    single-config walkforward (DSR degenerates to PSR).

    ⚠️⚠️ **`trading_days_per_window` 是**必填**的 (§13.102, 2026-10-19)。**
    本函数用它估 DSR 的 `n_returns`。**它无法从入参 `df` 推出** —— df 只有每窗的
    指标, 没有窗口长度 ⇒ 只能由**知道 windows 的那个调用方**给。
    此前这里写死 `n_windows * 63`, 注释还写着「rough estimate: ~63 trading days/**month**」;
    **实测一个 2 个月窗口只有 44 个交易日** (63 ≈ 3 个月, 且任何月份都没有 63 个交易日)
    ⇒ `n_returns` **被高估 43%** ⇒ SE 偏小 ⇒ **DSR 偏高 (方向: 乐观)**。
    改成必填之后, **"忘了给窗口长度"这件事在语法上就不可能**。
    """
    if df.empty:
        return "(empty walkforward)"

    sharpe_col = "sharpe" if "sharpe" in df.columns else None
    ret_col = "total_return" if "total_return" in df.columns else None
    n_windows = len(df)
    n_profitable = int((df[ret_col] > 0).sum()) if ret_col else 0

    # Aggregate stats
    median_ret = float(df[ret_col].median()) if ret_col else float("nan")
    mean_ret = float(df[ret_col].mean()) if ret_col else float("nan")
    worst_ret = float(df[ret_col].min()) if ret_col else float("nan")
    best_ret = float(df[ret_col].max()) if ret_col else float("nan")
    median_sharpe = float(df[sharpe_col].median()) if sharpe_col else float("nan")
    worst_dd = float(df["max_dd"].min()) if "max_dd" in df.columns else float("nan")

    # DSR + Bonferroni on the median observed Sharpe
    # §13.102: T = 窗口数 × **调用方给的每窗交易日数** (此前写死 63 = 高估 43%)。
    n_returns = max(n_windows * trading_days_per_window, 100)
    dsr = deflated_sharpe_ratio(
        observed_sharpe=median_sharpe,
        n_trials=n_comparisons,
        n_returns=n_returns,
        trading_days_per_year=trading_days_per_year,
    )
    sharpe_p = sharpe_significance_pvalue(
        observed_sharpe=median_sharpe,
        n_returns=n_returns,
        trading_days_per_year=trading_days_per_year,
    )
    bonferroni_p = min(sharpe_p * n_comparisons, 1.0)

    parts = [
        f"窗口 {n_windows} | 盈利 {n_profitable}/{n_windows}",
        f"中位收益 {median_ret*100:+.2f}% | 均值 {mean_ret*100:+.2f}%",
        f"最差 {worst_ret*100:+.2f}% | 最好 {best_ret*100:+.2f}%",
        f"中位Sharpe {median_sharpe:.2f} | 最差DD {worst_dd*100:+.2f}%",
        f"DSR(obs={median_sharpe:.2f}, k={n_comparisons}) "
        f"= {dsr['deflated_sharpe']:.3f}",
        f"Bonferroni p(Sharpe≠0) = {bonferroni_p:.4f}",
    ]
    return " | ".join(parts)
