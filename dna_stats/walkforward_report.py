"""V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — Walkforward DSR/Bonferroni report.

Wraps dna_stats.deflated to format walkforward results with statistical
corrections for multi-parameter sweeps.

Usage:
    from dna_stats.walkforward_report import format_walkforward_stats

    df = walkforward_run(...)         # columns: total_return, sharpe, ...
    n_comparisons = 50                # from preset grid size
    text = format_walkforward_stats(df, n_comparisons=n_comparisons)
    print(text)

Output includes:
  - Window count, win-rate, median/mean/min Sharpe
  - Deflated Sharpe Ratio (DSR) using the cross-window **mean** Sharpe vs k trials
    (T from the run — see 附六十四)
  - Bonferroni-corrected p-value for Sharpe ≠ 0
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# §2/§5 (audit 2026-10-16): 年化常量单源 —— 与四个引擎同源(见 deflated.py 的说明)。
from core.trade_schema import TRADING_DAYS_PER_YEAR

from dna_stats.deflated import (
    _norm_cdf,                 # internal but acceptable; same module
    deflated_sharpe_ratio,
    sharpe_significance_pvalue,
)


def format_walkforward_stats(
    df: pd.DataFrame,
    *,
    n_comparisons: int = 1,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
    #: 观察数 T(Sharpe 用了多少个收益观测)。**不传**时从 df 的
    #: `n_daily_returns` 列取各窗口均值;两者都没有 ⇒ 抛错(不猜)。
    n_returns: int | None = None,
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
    mean_sharpe = float(df[sharpe_col].mean()) if sharpe_col else float("nan")
    worst_dd = float(df["max_dd"].min()) if "max_dd" in df.columns else float("nan")

    # §5 (附六十四): 观察数 T 必须来自**本次运行** —— 不许猜。
    #
    # 此前这里是 `n_returns=max(n_windows * 63, 100)`,注释自认 "rough estimate:
    # ~63 trading days/month"。实测该口径在**已接线**的调用点上错得很大:
    # `uptrend_pullback/wfv_eval.py` 跑的是 **23 个 2 个月窗口** ⇒ 该式给 1,449,
    # 而一个窗口的实际观察数是 **~42**(引擎发布的 `n_daily_returns`)——
    # T 被高估约 **34 倍**,`sqrt(T-1)` 随之放大 ~5.9 倍 ⇒ **DSR 系统性偏乐观**。
    # 更讽刺的是:引擎**早就**为这个参数发布了观察数(附三十二 那次的修复),
    # 只是这条链路没把它带上来。
    #
    # 口径(与附六十 在 wf 脚本上的处置一致):取各窗口观察数的**均值**,即
    # 「一个窗口的观测数」;不把各窗口相加 —— test 窗口之间**重叠**
    # (2 月窗 / 1 月步),相加会把不独立的东西当独立,反而低估标准误。
    # 取单窗口径在方向上也是**保守**的(SE 更大 ⇒ DSR 更小),符合 §0。
    if n_returns is None:
        if "n_daily_returns" not in df.columns:
            raise ValueError(
                "§5: 无法取得观察数 T —— 需要 df 的 `n_daily_returns` 列(引擎已发布)"
                "或显式传入 n_returns=。**不许用 `n_windows × 常数` 之类的估计兜底**:"
                "那正是本项要修的缺陷(实测能偏乐观 34 倍)。"
            )
        _t = pd.to_numeric(df["n_daily_returns"], errors="coerce").dropna()
        if _t.empty:
            raise ValueError("§5: df['n_daily_returns'] 全为空 —— 取不到 T")
        n_returns = int(round(float(_t.mean())))

    # §5 (附六十四): `observed` 用**跨窗口均值**。
    # 此前用中位数:而本仓库另外两条路径(附五十九 的 wf 脚本、附六十 的 cycle sweep)
    # 定的都是"跨窗口均值 = WFV 的无偏汇总",n_trials 取配置数 ——
    # 同一次选择由同一个 header 描述。三处口径此前互不相同,现统一到均值。
    observed_sharpe = mean_sharpe
    dsr = deflated_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        n_trials=n_comparisons,
        n_returns=n_returns,
        trading_days_per_year=trading_days_per_year,
    )
    sharpe_p = sharpe_significance_pvalue(
        observed_sharpe=observed_sharpe,
        n_returns=n_returns,
        trading_days_per_year=trading_days_per_year,
    )
    bonferroni_p = min(sharpe_p * n_comparisons, 1.0)

    parts = [
        f"窗口 {n_windows} | 盈利 {n_profitable}/{n_windows}",
        f"中位收益 {median_ret*100:+.2f}% | 均值 {mean_ret*100:+.2f}%",
        f"最差 {worst_ret*100:+.2f}% | 最好 {best_ret*100:+.2f}%",
        f"中位Sharpe {median_sharpe:.2f} | 最差DD {worst_dd*100:+.2f}%",
        f"DSR(obs={observed_sharpe:.2f}[跨窗均值], k={n_comparisons}, T={n_returns}) "
        f"= {dsr['deflated_sharpe']:.3f}",
        f"Bonferroni p(Sharpe≠0) = {bonferroni_p:.4f}",
    ]
    return " | ".join(parts)
