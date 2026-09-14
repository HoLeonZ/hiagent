"""策略 preset 配置。

当前唯一 preset: v6 — close_ma60_buffer=0.03 趋势质量增强版。

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
    # v6：v5 + 趋势质量增强 (close ≥ ma60×1.03 强制价格远离均线)
    # 目标年 +86.66% (vs v5 +85.47%)，样本内 8 年中位 +5.31% (vs v5 +3.66%)
    "v6": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.05,
        "max_hold": 8,
        "max_positions": 5,
        "atr_tp_mult": 8.0,
        "atr_sl_mult": 2.5,
        "regime": {"ma_window": 60, "breadth_window": 20, "min_breadth": 0.40,
                   "require_rising": True, "rising_lookback": 5},
        "signal": {
            "entry_mode": "reversal",
            "min_down_streak": 2,
            "max_down_streak": 5,
            "min_pullback": 0.03,
            "max_pullback": 0.10,
            "ma20_tol": 0.04,
            "min_amount": 5e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
            "min_mom120": 0.50,
            "max_vol_ratio": 2.0,
            "max_atr_pct": 0.10,
            "close_ma60_buffer": 0.03,
            "ma60_rising_lookback": 0,
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
