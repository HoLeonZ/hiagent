"""策略 preset 配置。

单一 preset:
  v33_long_reverse_v16 — 当前 Pareto 最优 (composite 0.8489)。

  12 月窗口 (2024-09..2026-09) backtrader 引擎实测:
    median     +21.43%
    mean       +30.30%
    Sharpe     2.80
    avg_dd     22.84%
    worst_dd   52.08%
    trades     8.50/窗口
    composite  0.8489

  优化路径: v3 (sweep_v6) → v7 (sweep_v7) → v12 → v13 (buf+mom)
          → v14 (mom=0.12) → v15 (SL=0.0293 单峰) → v16 (mom plateau)
  iter 42-53 在 v16 邻域全面搜索 (TP/SL/mom/buf/streak/pct_chg/amount/
  ma60_ratio/MACD/max_positions/position_sizing/regime/universe)
  全部退步,确认 v16 为局部 Pareto 最优。

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
    # v33_long_reverse_v16 — 上升趋势回调做多,12 月窗口 composite 0.8489 (current Pareto optimum)。
    # 关键参数:
    #   - sl_pct 0.0293: SL 0.029~0.030 单峰峰值(iter 36),0.0001 步长精扫得到。
    #   - min_mom120 0.13: mom >= 0.125 已是同一 plateau (iter 41),选 mid-plateau 值。
    #   - close_ma60_buffer 0.02: 与 min_above_ma60_ratio 0.60 协同过滤"刚跨 MA60 假突破"。
    # 12 月窗口 (2024-09..2026-09) backtrader 引擎实测:
    #   median     +21.43%
    #   mean       +30.30%
    #   Sharpe     2.80
    #   avg_dd     22.84%
    #   worst_dd   52.08%
    #   trades     8.50
    #   composite  0.8489
    "v33_long_reverse_v16": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
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
