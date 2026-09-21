"""Default parameter presets for cycle_price_action v1.

Compliance declaration (CLAUDE.md audit 2026-09-22):
  V5 (R8, 2026-09-21, CLAUDE.md §4) — Volume Participation Limit:
    Portfolio.try_enter accepts bar_volume; cap shares at Bar_Volume × 0.10.
    backtrader_engine.py:73-79 passes bar["volume"]. 单笔最大成交量 = Bar_Vol × 0.10。
  V6 (2026-09-22, CLAUDE.md §4) — Intraday SL-first tiebreak: NOT APPLICABLE.
    cycle_price_action 只有 max_hold time-exit, 无 strategy-side TP/SL check
    (P7 不变 — next() 只在 hold_days ≥ max_hold 时平仓)。若未来增加 TP/SL,
    必须按 SL-first 优先级落地 (同 chase_up / uptrend_pullback / short_reversal)。
"""
from __future__ import annotations

PRESET_V1 = dict(
    threshold=2.0,
    min_dim=1.0,
    max_hold=5,
    atr_period=14,
    atr_sl_mult=1.5,
    tp_pct=0.06,
    weight_kline=1.0,
    weight_cycle=0.7,
    weight_calendar=0.5,
    periods=(3, 5, 8, 13, 21),
)
