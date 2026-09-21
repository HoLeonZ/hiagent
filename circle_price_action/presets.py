"""Default parameter presets for cycle_price_action v1."""
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
