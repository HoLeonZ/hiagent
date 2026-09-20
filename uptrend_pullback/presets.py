"""策略 preset 配置。

单一 preset:
  v33_long_reverse_v3 — v33_long_reverse 的 TP/SL 二维网格精扫 (sweep_v6) Pareto 最优点。

字段说明：
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
    # v33_long_reverse_v3 — v33_long_reverse 的 TP/SL 二维 5×5 网格精扫 (sweep_v6) Pareto 最优点。
    # 关键参数:
    #   - sl_pct 0.021: sweep_v6 5×5 grid 单峰,(tp=0.30, sl=0.021) CAGR 最大,无更优组合。
    #   - signal.min_above_ma60_ratio 0.55: 趋势持续性过滤,弱势趋势的回调不上车。
    # 12 月窗口 (2025-09-16 .. 2026-09-16) v3 引擎实测:
    #   CAGR       488.84% / Sharpe 2.941 / max_dd 27.65% / win_rate 28.85%
    #   profit_fac 2.311 / trades 52 (≥ 40 阈值)
    # 4 个指标 Pareto 改善 (CAGR/Sharpe/Win/PF), DD 在风险预算 35% 内。
    # 注意:all_in 模式 + 高 CAGR 必然伴随较高 DD 风险;样本外表现需另行评估。
    "v33_long_reverse_v3": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.021,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
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
