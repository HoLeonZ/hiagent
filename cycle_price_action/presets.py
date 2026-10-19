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

# §4 TP/SL: **固定百分比** —— 出场完全由 `tp_pct` / `sl_pct` 决定
# (exit 路径见 cycle_price_action/portfolio.py:377-378: tp_p = entry×(1+tp_pct),
#  sl_p = entry×(1−sl_pct); intraday tiebreak 走 sl_first)。
# ⚠️ **2026-10-20 (§13.175) 更正**: 本行此前写的是
#   「hybrid —— tp_pct/sl_pct 为固定基准, **atr_sl_mult 提供 ATR 自适应**」
#   —— **那是错的**: `atr_sl_mult` 在本族**从来没有被读过**
#   (`grep -rn "self.p.atr_sl_mult" cycle_price_action/*.py` ⇒ **一处也没有**)。
#   ⇒ 本族的止损**不 ATR 自适应**。该键已按 §13.145① 登记为惰性键;
#   **接不接它属结果变更** ⇒ 只登记, 不擅改。
# §13.75: 这一行此前缺失, 而守卫查不到它 —— 因为该族的 preset 是**调用形态**,
# 而旧扫描器只遍历字面量 dict ⇒ 那条守卫结构上不可能失败。
PRESET_V1 = dict(
    threshold=2.0,
    min_dim=1.0,
    max_hold=5,
    atr_period=14,
    atr_sl_mult=1.5,
    # V3a (2026-09-22, CLAUDE.md §3): PIT universe declaration.
    # data_feed.py:140-225 load_universe_data hardcodes P8 + main-board
    # + liquidity filter. Declared here for compliance consistency with
    # chase_up / short_reversal / uptrend_pullback presets.
    universe="mainboard_only",
    tp_pct=0.06,
    # V6'' (2026-09-22, CLAUDE.md §4): SL fraction for intraday tiebreak.
    # Used by backtrader_engine to compute sl_p = entry × (1 - sl_pct)。
    # 0.05 = 5% stop, conservative for cycle strategy (vs chase_up 1.5-2.5%)。
    sl_pct=0.05,
    # V5 (R8, 2026-09-21, CLAUDE.md §4): Volume Participation Limit declaration。
    max_volume_participation=0.10,
    # V8 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday 声明。
    # cycle_price_action/portfolio.py:209-216 已落地 (open<=sl_p 优先于 open>=tp_p,
    # lo<=sl_p 优先于 h>=tp_p)。
    intraday_tiebreak="sl_first",
    # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
    # 当前 cycle 仍读 v_daily (单 close) 作为信号+执行共用价。
    # 完整 V3a 落地需: data_feed.py 改读 v_daily_dual (含 adj_*/raw_*),
    # k_line / phase / cycle score 用 adj_close, SL/TP+exit 用 raw_close。
    price_source_for_signal="adj_close",
    price_source_for_execution="raw_close",
    # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor 声明。
    # cycle 单一 preset, 无 sweep; n_comparisons=1 (DSR→PSR)。
    # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats。
    # ⚠️ §13.83: 此处原写 "walkforward 输出走 … 自动套 DSR + Bonferroni 校正" —— **那是假的**:
    # 全仓**只有** uptrend_pullback/wfv_eval.py 调用它, 本族 walkforward.py **0 处引用**。
    # 本族真正的 §5 惩罚在 sweep_thresholds.py / main.py 的 deflated_sharpe_ratio 调用里。
    n_comparisons=1,
    # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
    # Engine `portfolio.py:65` hardcodes MAX_POSITION_PCT=1.0; 显式声明如下。
    position_sizing="all_in",
    max_positions=1,
    position_fraction=1.0,
    MAX_POSITION_PCT=1.0,
    weight_kline=1.0,
    weight_cycle=0.7,
    weight_calendar=0.5,
    periods=(3, 5, 8, 13, 21),
)
