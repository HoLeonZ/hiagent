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

# Canonical equity_curve.csv 的 5 列。
#
# ⚠️ 2026-10-19 之前, 这**同一个元组字面量被抄了三份**
# (`cycle_price_action/main.py` / `uptrend_pullback/main.py` / `short_reversal/main.py`),
# 三份**逐字节相同**, 但**没有单一来源**。实测确认相同后才上收 —— 所以本改动**零结果漂移**。
#
# 为什么必须上收 (而不是"能跑就别动"):
# 本循环已证 `core/` **有** `trade_schema.py` 却**没有指标层** —— 而那正是四引擎
# 六处定义分岔的成因 (见 docs/strategy_mining_log.md §13.12/§13.13)。
# 同一个"同名 + 多份拷贝 + 无单一来源"的形状出现在 equity_curve 上,
# **下一次分岔只差一次编辑**, 且没有任何东西会拦住它。
# ⇒ 把**已经相同**的东西上收, 是**零成本的防分岔**;
#   而把**已经不同**的东西上收 (如 `cagr`/`sharpe`) 属**结果变更**, 本循环明确不做。
EQUITY_CURVE_COLS: tuple[str, ...] = (
    "date",
    "cash",
    "position_value",
    "total_equity",
    "drawdown",
)

# Canonical cash_walk.csv 的 6 列 —— 与上面同一个理由, 同样是被抄了三份之后上收的。
CASH_WALK_COLS: tuple[str, ...] = (
    "date",
    "free_cash",
    "locked_margin",
    "settling_funds",
    "nav",
    "total_equity",
)