"""尾部感知的目标函数 —— 用于评估「宽 TP / 紧 SL」这类尾部收割型策略。

为什么不能继续用 Sharpe / 窗口均值收益
-------------------------------------
实测该策略的盈亏由**右尾**驱动:79% 止损出场、盈亏比 5.42、前 10% 交易贡献
297% 的净盈亏(见 results/PRESET_SEARCH.md §7)。在这种分布下:

* Sharpe = mean(日收益)/std × √252 —— **除以总波动率**,而波动率恰恰由那条
  创造边缘的右尾贡献;于是它系统性惩罚真正赚钱的形态。
* 窗口均值收益 —— 每 2 个月窗口只有 ~10 笔交易,均值噪声极大。
* 均值 IC —— 测的是分布一阶矩,而盈亏在四阶矩(实测:均值 IC 为负,
  但把排序反转会毁掉策略)。

用什么替代: **R-multiple 期望值**
--------------------------------
该策略在**入场时就固定了每笔的风险**(紧 SL,`atr_sl_mult=None`),所以每笔的
计划风险是一个常数:

    R_trade = sl_pct × entry_price × size        (计划风险, 单位: 货币)
    R_mult  = net_pnl / R_trade                  (每单位风险的收益)

    J = mean(R_mult)                             ← 主目标

归一化的三个好处: (1) 可跨不同 `sl_pct` 宽度比较(否则放宽止损会自动显得更好);
(2) 不惩罚右尾; (3) 直接读作「每 1 元风险预算换回多少」, 与仓位管理语言一致。

配套必须一起报的分布量: win%、avgWinR、avgLossR、P(R≥5)、尾十分位贡献。
单纯追 J 会被「一次超大 R」带跑, 所以分布量不是装饰而是判据的一部分。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def r_multiples(trades: pd.DataFrame, sl_pct: float) -> pd.Series:
    """每笔交易的 R 倍数 = net_pnl / (sl_pct × entry_price × size)。

    R_trade 是**入场时**的计划风险(止损距离 × 股数), 与实际出场无关 —— 这样
    R 才反映「风险预算」而不是事后结果。
    """
    if sl_pct <= 0:
        raise ValueError(f"sl_pct must be > 0, got {sl_pct}")
    risk = sl_pct * trades["entry_price"].astype(float) * trades["size"].astype(float)
    if (risk <= 0).any():
        raise ValueError("发现非正的 R_trade(entry_price 或 size 为 0)")
    return trades["net_pnl"].astype(float) / risk


def tail_stats(trades: pd.DataFrame, sl_pct: float) -> dict:
    """R 分布的核心统计量。

    `expectancy_r` 是主目标;其余为分布/尾部判据。
    `t_expectancy` 用**逐窗口**的均值 R 计算(窗口互不重叠)以避免同窗口内
    交易的相关性高估显著性。
    """
    if trades.empty:
        return {"n": 0, "expectancy_r": float("nan"), "t_expectancy": float("nan")}

    r = r_multiples(trades, sl_pct)
    wins, losses = r[r > 0], r[r < 0]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())

    # 逐窗口期望 → 用窗口均值算 t(窗口互不重叠; 同窗口内交易相关)
    per_win = trades.assign(_r=r).groupby("exit_date")["_r"].mean()
    n_w = len(per_win)
    t = (per_win.mean() / (per_win.std(ddof=1) / math.sqrt(n_w))
         if n_w > 2 and per_win.std(ddof=1) > 0 else float("nan"))

    top_decile = r.nlargest(max(len(r) // 10, 1))
    return {
        "n": int(len(r)),
        "expectancy_r": float(r.mean()),
        "median_r": float(r.median()),
        "t_expectancy": float(t),
        "win_pct": float((r > 0).mean()),
        "avg_win_r": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss_r": float(losses.mean()) if len(losses) else float("nan"),
        "payoff": float(wins.mean() / abs(losses.mean()))
                   if len(wins) and len(losses) else float("nan"),
        "p_r_ge_5": float((r >= 5).mean()),
        "p_r_le_minus_1": float((r <= -1).mean()),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "top_decile_share": float(top_decile.sum() / r.sum()) if r.sum() != 0 else float("nan"),
        "worst_r": float(r.min()),
        "best_r": float(r.max()),
    }
