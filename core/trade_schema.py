"""Canonical trades.csv schema (CLAUDE.md §3 — Data Integrity).

Single source of truth for the 14-column trades.csv layout used by all
4 engines (chase_up, uptrend_pullback, short_reversal, cycle_price_action).

Engine-specific adaptations (Tick 50 / Tick 54):
  - chase_up populates all 14 cols including `sub_signal_type` (BREAKOUT/
    MOMENTUM/MACROSS concatenation) and `atr_pct` (signal-day ATR%).
  - uptrend_pullback populates all 14 cols; `sub_signal_type` defaults
    to empty string (uptrend doesn't track a sub-signal enum).
  - short_reversal populates all 14 cols; `sub_signal_type` defaults to
    empty string and `atr_pct` defaults to NaN (short_reversal emits its
    own indicators via indicators_bt.py rather than reusing MA-based ATR).
  - cycle_price_action populates 12 cols (entry/exit dates + prices + size
    + PnL); `atr_pct` defaults to NaN, `sub_signal_type` defaults to "".

Per-trade math closure invariant (per ``test_per_trade_math_closure.py``):
  - gross - fees == net_pnl  (within 1e-6 absolute / 1e-4 relative)
  - net_return == net_pnl / (entry_price × size + buy_commission)
  - fees ≥ 0
"""
from __future__ import annotations

# Canonical 14-column order — required for downstream analysis (trade_report,
# render_html, sweep aggregation, deflated-sharpe stats). Engine modules MUST
# use this exact order when writing trades.csv.
TRADE_COLS: tuple[str, ...] = (
    "entry_date",
    "exit_date",
    "thscode",
    "exit_reason",
    "entry_price",
    "exit_price",
    "size",
    "hold_days",
    "gross_pnl",
    "fees",
    "net_pnl",
    "net_return",
    # 信号日 (entry_date - 1 个交易日) 的 atr_pct — 已按 [floor, cap] 夹紧。
    # 由各 engine 信号层在 T 日收盘时计算，Phase 1 / Phase 2 共用，避免穿越。
    "atr_pct",
    # 子信号类型 ("A"/"B"/"C" 拼接 — chase_up 专用, 其他 engine 留空)。
    "sub_signal_type",
)