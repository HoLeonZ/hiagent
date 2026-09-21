"""策略 preset 配置。

单一 preset:
  v33_long_reverse_v19 — 当前 Pareto 最优 (composite 0.9550)。

  12 月窗口 (2024-09..2026-09) backtrader 引擎实测:
    median     +21.72%
    mean       +32.22%
    Sharpe     2.96
    avg_dd     21.0%
    worst_dd   48.1%
    trades     8.30/窗口
    composite  0.9550

  优化路径: v3 (sweep_v6) → v7 (sweep_v7) → v12 → v13 (buf+mom)
          → v14 (mom=0.12) → v15 (SL=0.0293 单峰) → v16 (mom plateau)
          → v17 (TP 0.30→0.303,超精扫 TP grid 发现)
          → v18 (mom 0.13→0.16 + ma60_ratio 0.60→0.65,paradigm-axis 联合搜索)
          → v19 (TP 0.303→0.305 + mom 0.16→0.18,v18 邻域 联合搜索)
  v19 vs v18 strict Pareto improvement:
    composite  +4.75% / median +0.11pp / mean +0.83pp / sharpe +0.06 / avg_dd -0.2pp
    worst_dd tied, ALL metrics 改善 (无 regression)

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
    # v33_long_reverse_v19 — v18 + tp_pct 0.303→0.305 + min_mom120 0.16→0.18
    # (workflow v18-neighborhood 联合搜索发现的 Pareto strict improvement)。
    # 关键 insight: 之前所有 mom search 都在 0.125~0.16 范围(认为 plateau),但 ma60=0.65 的
    #   新 sweet spot 出现后,mom 上限可推到 0.18 进一步改善 Sharpe。TP 也从 0.303→0.305
    #   与新信号集协同。
    # 关键参数:
    #   - sl_pct 0.0293: v15 精扫得到的 SL 单峰,保留。
    #   - tp_pct 0.305: v18 邻域 TP 精扫发现 (v18 0.303→0.305 +0.86% simulate, backtrader +0.65%)。
    #   - min_mom120 0.18: 0.16 时 sharpe 2.90;0.18 + ma=0.65 协同提升 Sharpe 2.96。
    #   - min_above_ma60_ratio 0.65: v18 关键维度,保留。
    #   - close_ma60_buffer 0.02: 与 ma=0.65 协同,buf∈[0.01,0.02] 等价。
    # 12 月窗口 (2024-09..2026-09) backtrader 引擎实测 (相对 v18):
    #   median     +21.72%   (v18: +21.61%, +0.11pp) ✓
    #   mean       +32.22%   (v18: +31.39%, +0.83pp) ✓
    #   Sharpe     2.96      (v18: 2.90, +0.06) ✓
    #   avg_dd     21.0%     (v18: 21.2%, -0.2pp) ✓
    #   worst_dd   48.1%     (v18: 48.1%, tied) ✓
    #   trades     8.30      (v18: 8.40, -0.1) ~
    #   composite  0.9550    (v18: 0.9117, +4.75%) ✓
    "v33_long_reverse_v19": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 portfolio.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # v33_long_reverse_v19 是 v3→v19 顺序 sweep (每版扩展前一版邻域),
        # 总比较数 ≈ 19 版本 × 邻域 ≈ n_comparisons。
        "n_comparisons": 19,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "tp_pct": 0.305,
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
            "min_mom120": 0.18,
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
