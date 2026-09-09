"""策略 preset 配置。

max_hold 一律 ≤ 20（需求硬约束：每只个股持有不超过 20 个交易日）。

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
    # 基线：回调途中直接买 + 固定止损 + 无择时（用于对照，已知亏损）
    "baseline": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.05,
        "max_hold": 20,
        "max_positions": 5,
        "atr_tp_mult": None,
        "atr_sl_mult": None,
        "regime": None,
        "signal": {
            "entry_mode": "dip",
            "min_down_streak": 2,
            "max_down_streak": 5,
            "min_pullback": 0.03,
            "max_pullback": 0.14,
            "ma20_tol": 0.04,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
            "min_mom120": 0.0,
            "max_vol_ratio": 1.5,
            "max_atr_pct": 0.10,
        },
    },
    # v2：基于 v1 + stage-1 调参锁定的最强 regime（样本内 8 年中位 +3.10%）
    # v5：收紧持仓时间 + 高动量筛选 + 提高成交额门槛
# 目标年（2025-09..2026-09）+85.47%，avg_hold 7.5 天
# 样本内 8 年中位 +3.66% / 5/8 盈利年
# 主要变化：max_hold 20→8，atr_tp 3→8，max_pullback 0.18→0.10，
#          min_mom120 0→0.50，min_amount 3e7→5e7
"v5": {
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
        },
    },
    "v4": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.05,
        "max_hold": 20,
        "max_positions": 5,
        "atr_tp_mult": 3.0,
        "atr_sl_mult": 2.5,
        "regime": {"ma_window": 60, "breadth_window": 20, "min_breadth": 0.40,
                   "require_rising": True, "rising_lookback": 5},
        "signal": {
            "entry_mode": "reversal",
            "min_down_streak": 2,
            "max_down_streak": 5,
            "min_pullback": 0.03,
            "max_pullback": 0.18,
            "ma20_tol": 0.04,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
            "min_mom120": 0.0,
            "max_vol_ratio": 2.0,
            "max_atr_pct": 0.10,
        },
    },
    "v3": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.05,
        "max_hold": 20,
        "max_positions": 5,
        "atr_tp_mult": 3.0,
        "atr_sl_mult": 2.5,
        "regime": {"ma_window": 60, "breadth_window": 20, "min_breadth": 0.40,
                   "require_rising": True, "rising_lookback": 5},
        "signal": {
            "entry_mode": "reversal",
            "min_down_streak": 2,
            "max_down_streak": 5,
            "min_pullback": 0.03,
            "max_pullback": 0.14,
            "ma20_tol": 0.04,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
            "min_mom120": 0.0,
            "max_vol_ratio": 2.0,
            "max_atr_pct": 0.10,
        },
    },
    "v2": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.05,
        "max_hold": 20,
        "max_positions": 5,
        "atr_tp_mult": 3.0,
        "atr_sl_mult": 2.0,
        "regime": {"ma_window": 60, "breadth_window": 20, "min_breadth": 0.40,
                   "require_rising": True, "rising_lookback": 5},
        "signal": {
            "entry_mode": "reversal",
            "min_down_streak": 2,
            "max_down_streak": 5,
            "min_pullback": 0.03,
            "max_pullback": 0.14,
            "ma20_tol": 0.04,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
            "min_mom120": 0.0,
            "max_vol_ratio": 2.0,
            "max_atr_pct": 0.10,
        },
    },
    # v1：等反转确认 + ATR 自适应止损 + 大盘择时（基线对比用）
    "v1": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.05,
        "max_hold": 20,
        "max_positions": 5,
        "atr_tp_mult": 3.0,
        "atr_sl_mult": 2.0,
        "regime": {"ma_window": 20, "breadth_window": 20, "min_breadth": 0.45},
        "signal": {
            "entry_mode": "reversal",
            "min_down_streak": 2,
            "max_down_streak": 5,
            "min_pullback": 0.03,
            "max_pullback": 0.14,
            "ma20_tol": 0.04,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6,
            "min_mom120": 0.0,
            "max_vol_ratio": 2.0,
            "max_atr_pct": 0.10,
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
