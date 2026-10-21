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

# ---------------------------------------------------------------------------
# 年化口径 —— §2 单源 (audit 2026-10-15)
# ---------------------------------------------------------------------------
#: A 股**交易日/年**。
#:
#: 日历日 ≠ 交易日。用 `calendar_days / 365` 年化日收益序列,与用
#: `trading_bars / 243` 年化,会给出**不同**的 CAGR —— 而两边都"看起来合理"。
#: 实测(同一窗口、同一 10% 总收益):
#:
#: | 窗口 | 交易日 / 日历日 | 交易日口径 CAGR | 日历日口径 CAGR |
#: |---|---|---|---|
#: | 2026-04-01→05-01 | 23 / 30   | 173.7% | 218.9% |
#: | 2026-01-20→03-01 | 29 / 40   | 122.3% | 138.6% |
#: | 2025 全年         | 261 / 364 |  9.28% | 10.03% |
#:
#: 本仓库此前有**三处**不同口径:chase_up / uptrend_pullback = 243(交易日)、
#: short_reversal = 365(日历日)、dna_stats 默认 = 252。本常量是**引擎侧**的单源。
#: `dna_stats` 的 252 属 §5 统计口径(改动会影响 DSR / Bonferroni 结论),
#: 仍另行登记,不在此处一并改。
TRADING_DAYS_PER_YEAR: int = 243


def annualized_years(n_trading_days: int) -> float:
    """交易日数 → 年数(下限一个交易日,避免除零)。

    日收益序列的年化**必须**用交易日数,不得用日历日跨度。
    """
    return max(
        n_trading_days / TRADING_DAYS_PER_YEAR, 1.0 / TRADING_DAYS_PER_YEAR
    )


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

# §2 (audit P0-1, 2026-10-15): per-bar 权益账本列契约（single source）。
# 前四列是既有读者依赖的兼容列；后三列是真实三池，供 cash_walk.csv 如实
# 落盘 —— 旧实现在各 main.py 里把 locked_margin / settling_funds 硬编码为
# 0，三池隔离在产物层完全不可见，任何基于 cash_walk 的对账都退化为单池。
EQUITY_COLS: tuple[str, ...] = (
    "date",
    "cash",            # total_cash（券商侧总现金，兼容列）
    "holdings",        # 持仓市值 Σ size × mark_price
    "equity",          # canonical NAV == core.dual_price.portfolio_nav(...)
    "free_cash",
    "locked_margin",
    "settling_funds",
    # §3 (audit P2-10, 2026-10-15): 累计已入账的现金分红。分红是**独立于
    # 逐笔 P&L 的现金流**,因此现金守恒必须写成
    #   final_equity == initial + Σnet_pnl + Σcum_dividends
    # 把它作为列落盘,便于产物层直接对账。
    "cum_dividends",
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