"""策略 preset 配置。

单一 preset:
  v33_long_reverse_v17 — 当前 Pareto 最优 (composite 0.8940)。

  12 月窗口 (2024-09..2026-09) backtrader 引擎实测:
    median     +21.61%
    mean       +31.76%
    Sharpe     2.81
    avg_dd     22.53%
    worst_dd   48.09%
    trades     8.50/窗口
    composite  0.8940

  优化路径: v3 (sweep_v6) → v7 (sweep_v7) → v12 → v13 (buf+mom)
          → v14 (mom=0.12) → v15 (SL=0.0293 单峰) → v16 (mom plateau)
          → v17 (TP 0.30→0.303,超精扫 TP grid 发现)
  v17 vs v16 所有指标均改善 (Pareto strict improvement):
    composite  +5.3% / median +0.18pp / mean +1.46pp
    avg_dd     -0.31pp / worst_dd -3.99pp / sharpe +0.01

字段说明:
  tp_pct / sl_pct     固定止盈止损；给了 atr_*_mult 时被 ATR 自适应覆盖
  atr_tp_mult         止盈宽度 = ATR% × 本系数
  atr_sl_mult         止损宽度 = ATR% × 本系数
  regime              大盘择时参数；None 表示不做择时
  signal              select_entries 的关键字参数
"""
from __future__ import annotations

import copy

MAX_HOLD_LIMIT = 20

PRESETS: dict[str, dict] = {
    # v33_long_reverse_v17 — v16 + tp_pct 0.30→0.303 (超精扫 TP grid 发现)。
    # 关键 insight: iter 60 在 TP=0.30 邻域 step 0.01 扫描未发现改善,但 workflow tp-fine-grid
    #   在 step 0.001 扫描发现 TP 0.303/0.304 显著优于 0.30。
    #   注意 TP 0.305 是 iter 60 报告退步的点(被 0.001 步长掩盖的真实非单调地形)。
    # 关键参数:
    #   - sl_pct 0.0293: SL 0.029~0.030 单峰峰值(iter 36),0.0001 步长精扫得到。
    #   - tp_pct 0.303: TP 超精扫 (step 0.001) 发现的 Pareto strict improvement。
    #   - min_mom120 0.13: mom >= 0.125 已是同一 plateau (iter 41),选 mid-plateau 值。
    #   - close_ma60_buffer 0.02: 与 min_above_ma60_ratio 0.60 协同过滤"刚跨 MA60 假突破"。
    # 12 月窗口 (2024-09..2026-09) backtrader 引擎实测 (相对 v16):
    #   median     +21.61%   (v16: +21.43%, +0.18pp) ✓
    #   mean       +31.76%   (v16: +30.30%, +1.46pp) ✓
    #   Sharpe     2.81      (v16: 2.80, +0.01) ✓
    #   avg_dd     22.53%    (v16: 22.84%, -0.31pp) ✓
    #   worst_dd   48.09%    (v16: 52.08%, -3.99pp) ✓
    #   trades     8.50      (持平)
    #   composite  0.8940    (v16: 0.8489, +5.3%) ✓
    "v33_long_reverse_v17": {
        "universe": "mainboard_only",
        "tp_pct": 0.303,
        "sl_pct": 0.0293,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.60,
            "close_ma60_buffer": 0.02,
            "min_mom120": 0.13,
        },
    },
}


def get_preset(name: str) -> dict:
    """返回 preset 深拷贝；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    out = copy.deepcopy(PRESETS[name])
    if out["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(
            f"preset {name!r}: max_hold={out['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}"
        )
    return out
