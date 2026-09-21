"""策略 preset 配置。

单一 preset:
  v33_long_reverse_v18 — 当前 Pareto 最优 (composite 0.9117)。

  12 月窗口 (2024-09..2026-09) backtrader 引擎实测:
    median     +21.61%
    mean       +31.39%
    Sharpe     2.90
    avg_dd     21.2%
    worst_dd   48.1%
    trades     8.40/窗口
    composite  0.9117

  优化路径: v3 (sweep_v6) → v7 (sweep_v7) → v12 → v13 (buf+mom)
          → v14 (mom=0.12) → v15 (SL=0.0293 单峰) → v16 (mom plateau)
          → v17 (TP 0.30→0.303,超精扫 TP grid 发现)
          → v18 (mom 0.13→0.16 + ma60_ratio 0.60→0.65,paradigm-axis 联合搜索)
  v18 vs v17 strict Pareto improvement:
    composite  +1.98% / sharpe +0.09 / avg_dd -1.3pp
    median/worst_dd tied,mean -0.37pp (acceptable trade)

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
    # v33_long_reverse_v18 — v17 + min_mom120 0.13→0.16 + min_above_ma60_ratio 0.60→0.65
    # (workflow paradigm-axis 联合搜索发现的 Pareto strict improvement)。
    # 关键 insight: ma60_ratio 是 step-function gate (0.55→全部坏 / 0.60→baseline / 0.65→新峰)。
    #   在 ma=0.65 基础上,mom=0.16 比 mom=0.13 进一步提升 Sharpe。
    # 关键参数:
    #   - sl_pct 0.0293: v15 精扫得到的 SL 单峰,保留。
    #   - tp_pct 0.303: v17 精扫得到的 TP 改善,保留。
    #   - min_mom120 0.16: 0.13 时基础(sharpe 2.81);0.16 + ma=0.65 协同提升 Sharpe 2.90。
    #   - min_above_ma60_ratio 0.65: 0.60→0.65 是 load-bearing 维度,单独提升就改善 Sharpe。
    #   - close_ma60_buffer 0.02: 与 ma=0.65 协同,buf∈[0.01,0.02] 等价(simulate+backtrader 都证实)。
    # 12 月窗口 (2024-09..2026-09) backtrader 引擎实测 (相对 v17):
    #   median     +21.61%   (v17: +21.61%, tied) ✓
    #   mean       +31.39%   (v17: +31.76%, -0.37pp) ~
    #   Sharpe     2.90      (v17: 2.81, +0.09) ✓
    #   avg_dd     21.2%     (v17: 22.5%, -1.3pp) ✓
    #   worst_dd   48.1%     (v17: 48.1%, tied) ✓
    #   trades     8.40      (v17: 8.50, -0.1) ~
    #   composite  0.9117    (v17: 0.8940, +1.98%) ✓
    "v33_long_reverse_v18": {
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
            "min_above_ma60_ratio": 0.65,
            "close_ma60_buffer": 0.02,
            "min_mom120": 0.16,
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
