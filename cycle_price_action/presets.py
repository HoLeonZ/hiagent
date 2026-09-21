"""Default parameter presets for cycle_price_action v1.

Compliance declaration (CLAUDE.md audit 2026-09-22):
  V5 (R8, 2026-09-21, CLAUDE.md §4) — Volume Participation Limit:
    Portfolio.try_enter accepts bar_volume; cap shares at Bar_Volume × 0.10.
    backtrader_engine.py:107-113 passes bar["volume"]. 单笔最大成交量 = Bar_Vol × 0.10。
  V6'' (2026-09-22, CLAUDE.md §4) — Intraday SL-first tiebreak:
    Portfolio.try_exit_with_intraday_check 落地 SL-first 优先级 (gap-down SL,
    gap-up TP, intraday SL-first, TP fallback, time fallback). 7 个 regression
    tests 覆盖全部 5 个分支 + P3 same-day guard。
    backtrader_engine.py:66-89 在持仓每个 bar 调用 intraday check, exit 触发
    reason ∈ {"SL", "TP", "time"}。max_hold time exit 保留为 P7 fallback。
"""
from __future__ import annotations

PRESET_V1 = dict(
    threshold=2.0,
    min_dim=1.0,
    max_hold=5,
    atr_period=14,
    atr_sl_mult=1.5,
    tp_pct=0.06,
    # V6'' (2026-09-22, CLAUDE.md §4): SL fraction for intraday tiebreak.
    # Used by backtrader_engine to compute sl_p = entry × (1 - sl_pct)。
    # 0.05 = 5% stop, conservative for cycle strategy (vs chase_up 1.5-2.5%)。
    sl_pct=0.05,
    # V5 (R8, 2026-09-21, CLAUDE.md §4): Volume Participation Limit declaration。
    max_volume_participation=0.10,
    # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
    # 当前 cycle 仍读 v_daily (单 close) 作为信号+执行共用价。
    # 完整 V3a 落地需: data_feed.py 改读 v_daily_dual (含 adj_*/raw_*),
    # k_line / phase / cycle score 用 adj_close, SL/TP+exit 用 raw_close。
    price_source_for_signal="adj_close",
    price_source_for_execution="raw_close",
    # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor 声明。
    # cycle 单一 preset, 无 sweep; n_comparisons=1 (DSR→PSR)。
    # walkforward 输出走 dna_stats.walkforward_report.format_walkforward_stats
    # 自动套 DSR + Bonferroni 校正。
    n_comparisons=1,
    weight_kline=1.0,
    weight_cycle=0.7,
    weight_calendar=0.5,
    periods=(3, 5, 8, 13, 21),
)
