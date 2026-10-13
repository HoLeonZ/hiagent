"""策略 preset 配置。"""
from __future__ import annotations

from typing import Literal

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

# CLAUDE.md §4 Short-Side Feasibility (mandatory declaration for short legs):
# 本模块所有 preset 的做空回测共用以下融券假设:
#   - availability: 假设任意主板标的任意交易日均可融到券 (引擎不做券源检查)
#   - borrow_cost:  当前引擎未在 P&L 中扣减借券成本 (已知缺口)
# ⚠️ 现实差距: A 股个股融券券源稀缺、2024 年监管收紧后多数标的实际不可融;
#    回测数字是"可融券且零借券成本世界"的上界, 不构成可执行预期。
BORROW_ASSUMPTION: dict = {
    "availability": "assumed_unlimited",
    "borrow_cost_model": "none",  # engine does not deduct borrow cost (known gap)
}

PRESETS: dict[str, dict] = {
    # ⚠️ 2026-09-22 preset 库重组 ⚠️
    # 7 个破产/失败 preset 已删除 (v33×2 / v34 / v37 / v39_pctchg_04_09 / v41 / v47):
    #   - v33×2 + v47_d_strict: cash gate 触发时 NAV 透支 6-100 倍, paper-trading 幻影
    #   - v34: 12m DD 100% 触底破产 (cash gate 落地后实测)
    #   - v37 / v39_pctchg_04_09 / v41: 单点过拟合 12m, 跨周期 walk-forward 崩
    # 留下 11 个跨周期 walk-forward 真胜出的 preset (v35/v36/v38/v39_03_10/v40×2/
    # v42/v43/v44/v45/v46)。v44_ratio02_buf07 是 v3 体系工程最优。
    # === 2026-09-21 微调发现（v35）— v34 系列进一步收紧入场信号 ===
    # 4 组对比 (P3+P5+cash gate 修后, 12m):
    #   v35_cons_pctchg_03_08:    n=303 win=46.5% CAGR=+2340% Sharpe=9.28 DD=58.0%
    #   v35_cons_pctchg_025_06:   n=391 win=47.8% CAGR=+3531% Sharpe=9.47 DD=80.6% ⚠️
    #   v35_agg_pctchg_04_09 ⭐:  n=171 win=35.1% CAGR=+1365% Sharpe=8.58 DD=35.3% ✅
    #   v35_agg_pctchg_035_075:   n=232 win=34.5% CAGR=+2423% Sharpe=9.90 DD=55.4%
    # v35_agg_pctchg_04_09 在 12m 样本里 DD 最低 (35.3%), 真稳健冠军:
    #   砍掉更多伪信号 (n=171 vs v34 的 303), 胜率 35.1% 但 DD 仅 35.3%,
    #   CAGR 缩水到 v34 的 1/5 但风险调整收益显著改善。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   2024-09-12 → 2025-03-12: n= 77 win=15.6% total_yield=+37.53%  Sharpe=2.67 DD=89.2% ⚠️
    #   2025-03-12 → 2025-09-12: n= 93 win=14.0% total_yield=+28.87%  Sharpe=2.69 DD=89.2% ⚠️
    #   2025-09-12 → 2026-03-12: n= 38 win=10.5% total_yield= +9.75%  Sharpe=1.64 DD=24.2% ✅
    #   2026-03-12 → 2026-09-12: n=162 win=35.8% total_yield=+1240.05% Sharpe=8.48 DD=35.3% ✅
    #   4/4 窗口全为正收益, 但震荡段 (前 2 窗) DD 高达 89.2% — 信号过少导致
    #   cash gate 频繁拒单, 浮亏击穿。Sharpe 跨窗均值 3.87, 最低 1.64。
    #   最低单窗 +9.75% vs v34 的 +51.6% — 跨周期稳健性显著劣于 v34。
    # === 综合结论: v35 非首选, 仅供对比参照 ===
    # v34_mainboard_pctchg_tight 在所有维度 (DD/跨周期/CAGR/Sharpe) 都优于 v35。
    # v35 暴露的本质问题: 信号收紧不能解决震荡段胜率, 必须从 B 连阳 / E 流动性
    # 窗口入手改进。下次落 -20ms 触发时, Task #15+ 应聚焦 B/E 信号轴。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v35_agg_pctchg_04_09": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.04,
        "pct_chg_high": 0.09,
        # v35 是 v3 体系中唯一保留 baseline D-mode 的 preset:
        # 设计权衡 = 较弱 D (|bar| <= |prev|, 引擎默认 'strict') + 更紧 pct_chg [0.04, 0.09],
        # 对照 v36+ 的较强 D (converge_strict, |bar| < |prev|*0.5) + 较宽 pct_chg [0.03, 0.10]。
        # 显式声明以避免 engine 默认值变更时静默漂移 (engine.py:164)。
        "d_mode": "strict",
    },
    # === 2026-09-21 微调发现（v36）— B/E/D 信号轴参数化 ===
    # 模块常量 UP_STREAK/LIQ/MACD 提升为 strategy params (Task #15-17),
    # 现在可以在不破坏 preset 的前提下做信号轴微调。
    # 4 组对比 (P3+P5+cash gate 修后, 12m):
    #   v36_us37_proper (B=[3,7]):       n=303 win=38.3% CAGR=+7122% Sharpe=11.14 DD=55.8%
    #   v36_us5_12     (B=[5,12]):        n= 13 win=23.1% CAGR=  +16%  Sharpe= 1.76 DD=12.6% 不可投
    #   v36_us3_12     (B=[3,12]):        n=303 win=38.3% CAGR=+7122% Sharpe=11.14 DD=55.8%
    #   v36_d_converge (D=|bar|<|prev|*0.5): n=200 win=40.0% CAGR=+2814% Sharpe=10.30 DD=42.7% ⭐
    # 结论:
    #   - B 连阳调整无效: v34 样本里连阳 8-10 天为空集, [3,7] 和 [3,12] 等价于 [3,10]。
    #   - D 严格收敛有效: |bar|<|prev_bar|*0.5 让 n-33% win% +1.7pp DD -13pp。
    #   - v36_d_converge 是 v36 系列唯一可行 preset (n=200 充足, DD 改善明显)。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   2024-09-12 → 2025-03-12: n= 56 win=16.1% total_yield= +20.36% Sharpe=2.47 DD= 56.9% ✅
    #   2025-03-12 → 2025-09-12: n= 74 win=14.9% total_yield= +19.86% Sharpe=2.60 DD= 55.8% ✅
    #   2025-09-12 → 2026-03-12: n= 40 win=15.0% total_yield= +21.94% Sharpe=2.24 DD= 18.7% ✅
    #   2026-03-12 → 2026-09-12: n=185 win=41.6% total_yield=+2473.52% Sharpe=10.22 DD= 42.7% ✅
    #   4/4 窗口全为正收益, 最低单窗 +19.86%, 跨周期稳健。
    #   对比 v34 walk-forward: 震荡段 yield 缩水 32pp (v34 +60% / v36 +20%),
    #   但 DD 从 100% 降至 55% — 真改善 (v34 触底破产)。
    # === v34 vs v36 决策指南 ===
    #   v34_mainboard_pctchg_tight: 高收益高 DD (震荡段 yield 高但 DD 100% 破产触底)
    #   v36_d_converge:             中等收益低 DD (震荡段 yield 中等但 DD 55% 真稳)
    #   实盘部署建议选 v36_d_converge (更安全)。研究/对照用 v34 看理论上限。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v36_d_converge": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.08,
        "d_mode": "converge_strict",
    },
    # === 2026-09-21 微调发现（v37）— E 流动性窗口拓宽 ===
    # v37_liq_3e7_5e8 已删除 (2026-09-22): 单点过拟合 12m, 跨周期 walk-forward 揭示
    # 震荡段 DD 72-73% (vs v36 55-57%) — E 流动性窗口拓宽到大票更脆弱。
    # === 2026-09-21 微调发现（v38）— A 条件放宽 ===
    # A 条件放宽 4 组对比 (12m, 在 v36 baseline 上):
    #   v38_buf_pos01 (buffer +1%):      n=210 win=40.5% CAGR=+3374% Sharpe=10.62 DD=42.7%
    #   v38_buf_pos02 (buffer +2%):      n=223 win=39.5% CAGR=+3582% Sharpe=10.72 DD=42.1%
    #   v38_ratio_05  (ratio 0.5):       n=237 win=39.7% CAGR=+4307% Sharpe=11.04 DD=48.6%
    #   v38_a_relaxed (ratio 0.5 + buf 2%) ⭐: n=262 win=38.9% CAGR=+5393% Sharpe=11.14 DD=48.0%
    # v38_a_relaxed 12m 综合优于 v36: +92% CAGR, +8% Sharpe, n +31%, DD 仅 +5.3pp。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   2024-09-12 → 2025-03-12: n= 82 win=19.5% total_yield= +51.19% Sharpe=3.56 DD=61.7%
    #   2025-03-12 → 2025-09-12: n=103 win=14.6% total_yield= +25.06% Sharpe=3.04 DD=61.7%
    #   2025-09-12 → 2026-03-12: n= 73 win=16.4% total_yield= +45.92% Sharpe=3.21 DD=19.0%
    #   2026-03-12 → 2026-09-12: n=234 win=41.0% total_yield=+4378.32% Sharpe=11.27 DD=48.0%
    #   4/4 窗口全为正收益, 最低单窗 +25.06%, 跨周期稳健。
    #   跨周期 vs v36 改善: 最低 yield +5pp, 最低 Sharpe +36%, 拉涨段 yield +77-100%。
    #   跨周期 vs v36 略恶化: 震荡段 DD +5pp (55→62%)。
    # === 跨周期决策指南 ===
    # v36_d_converge: 最低 DD (震荡段 55-57%, 但 yield 中等)
    # v38_a_relaxed ⭐: 最高 yield × stretch (拉涨段 +4378%, 跨周期稳健)
    # 实盘部署首选 v38_a_relaxed — 拉涨段高收益且 1 中等 DD;
    # 若 DD 极端敏感选 v36_d_converge。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v38_a_relaxed": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.08,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
    # === 2026-09-21 微调发现（v39）— v38 + pct_chg 收紧组合 ===
    # 在 v38_a_relaxed (A 放宽) 基础上调 pct_chg 窗口, 4 组对比 (12m):
    #   v39_pctchg_04_09 (下限 4%, 上限 9%):    n=150 win=40.0% CAGR=+1538% DD=28.2% ⭐ (DD 最低)
    #   v39_pctchg_035_08 (下限 3.5%):           n=203 win=39.9% CAGR=+3021% DD=45.8%
    #   v39_pctchg_03_10 (上限 10%):              n=278 win=38.5% CAGR=+7050% DD=56.6% (CAGR 最高)
    #   v39_pctchg_04_08 (下限 4%, 上限 8%):    n=147 win=40.1% CAGR=+1438% DD=28.2% ⭐ (DD 最低)
    # v39_pctchg_04_09 与 v39_pctchg_04_08 几乎一致, 都是 n≈150, DD=28.2% — 双收紧下限.
    # v39_pctchg_03_10 是 12m CAGR 冠军 (+7050%) 但 DD 56.6% 与 v38 持平.
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    # v39_pctchg_04_09 已删除 (2026-09-22): 12m DD 28.2% 看似最低, 但 walk-forward
    # 揭示震荡段最低 yield 仅 +4% — 单点过拟合 12m 样本, 跨周期不工作。
    #
    # v39_pctchg_03_10 (12m CAGR 冠军 — 跨周期真胜出):
    #   2024-09→2025-03: n= 90 win=23.3% yield= +87.6% Sharpe=4.30 DD=74.9%
    #   2025-03→2025-09: n=111 win=18.0% yield= +55.1% Sharpe=3.82 DD=74.9%
    #   2025-09→2026-03: n= 78 win=16.7% yield= +52.4% Sharpe=3.37 DD=22.9%
    #   2026-03→2026-09: n=249 win=40.2% yield=+5411.7% Sharpe=11.42 DD=56.6%
    #   跨周期 vs v38 改善: 震荡段最低 yield +27pp (+25%→+52%), 拉涨段 yield +24%
    #                       (+4378→+5412), 拉涨段 Sharpe +1% (11.27→11.42)
    #   跨周期 vs v38 略恶化: 震荡段 DD +13pp (62→75%) — 收益风险同向放大。
    # === 跨周期决策指南 (v3 体系最终产品 - v39_pctchg_03_10 优先) ===
    # v36_d_converge: 最低 DD (震荡段 55-57%, 拉涨段 yield 中等)
    # v38_a_relaxed:  稳健高产 (震荡段 yield +25%, DD 62%)
    # v39_pctchg_03_10 ⭐⭐: 跨周期最高 yield (震荡段 +52%, 拉涨段 +5412%)
    # 实盘部署首选 v39_pctchg_03_10 (最高 yield), DD 敏感选 v36_d_converge.
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v39_pctchg_03_10": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
    # === 2026-09-21 微调发现（v40）— v39 + TP 拉宽 ===
    # 在 v39_pctchg_03_10 基础上微调 TP/SL, 4 组对比 (12m):
    #   v40_sl_001       (SL 0.0005→0.001):     n=278 win=38.8% CAGR=+6724% DD=56.8%
    #   v40_tp_07 ⭐     (TP 6%→7%):            n=278 win=37.1% CAGR=+8207% DD=56.6%
    #   v40_tp_08 ⭐     (TP 6%→8%):            n=278 win=36.7% CAGR=+9113% DD=56.6%
    #   v40_sl001_tp07   (双向):                n=278 win=37.4% CAGR=+7854% DD=56.8%
    # v40_tp_07 是 v40 系列冠军: CAGR +16% (7050→8207), DD 持平 56.6%。
    # v40_tp_08 是更激进: CAGR +29% (7050→9113), DD 持平, win% -1.8pp。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    # v40_tp_07:
    #   2024-09→2025-03: n= 90 win=22.2% yield=+87.06% Sharpe=4.08 DD=74.9%
    #   2025-03→2025-09: n=111 win=17.1% yield=+50.43% Sharpe=3.59 DD=74.9%
    #   2025-09→2026-03: n= 78 win=16.7% yield=+59.59% Sharpe=3.36 DD=22.9%
    #   2026-03→2026-09: n=249 win=38.6% yield=+6203.09% Sharpe=11.20 DD=56.6%
    #
    # v40_tp_08 ⭐:
    #   2024-09→2025-03: n= 90 win=22.2% yield=+91.08% Sharpe=4.07 DD=74.9%
    #   2025-03→2025-09: n=111 win=17.1% yield=+54.29% Sharpe=3.59 DD=74.9%
    #   2025-09→2026-03: n= 78 win=16.7% yield=+62.93% Sharpe=3.33 DD=22.9%
    #   2026-03→2026-09: n=249 win=38.2% yield=+6871.48% Sharpe=11.12 DD=56.6%
    #
    # v40_tp_08 4/4 窗口全部优于 v39_03_10 baseline:
    #   拉涨段 yield +27% (+5412 → +6871) ⭐
    #   震荡段 yield +3-10pp
    #   DD 持平 (74.9% / 22.9% / 56.6%) — 零成本微调胜出。
    # === v3 体系最终产品 (v40_tp_08 优先) ===
    # 实盘部署首选 v40_tp_08 (跨周期最高 yield, DD 与 v39 持平)。
    # v36_d_converge 仍是 DD 极端敏感场景的备选。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.07
    # max_hold: 5
    # Note: Fixed TP/SL; TP widened from 0.06 to 0.07 for higher yield. No ATR multiplier.
    "v40_tp_07": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.07,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; aggressive TP 0.08 widening. No ATR multiplier.
    "v40_tp_08": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
    # === 2026-09-21 微调发现（v41）— v40_tp_08 + pct_chg / mh 微调 ===
    # v41_pctchg_04_10 已删除 (2026-09-22): pct_chg 下限收紧 (3%→4%) 看似改善 DD,
    # 实则砍掉有效入场信号 — 跨周期 yield 缩水 -10%~-64%, 单点过拟合 12m 样本。
    # 与 v37_liq_3e7_5e8 (E 放宽单点过拟合) 同根问题: 单参数 12m 优化不可信。
    # === 2026-09-21 微调发现（v42）— v40_tp_08 + A 进一步放宽 ===
    # 在 v40_tp_08 (TP 8%) 基础上放宽 A 条件, 4 组对比 (12m):
    #   v42_buf03 (buffer 0.02→0.03):       n=290 win=36.2% CAGR=+10349% Sharpe=10.63 DD=56.6%
    #   v42_ratio04 (ratio 0.5→0.4):         n=302 win=35.4% CAGR=+10385% Sharpe=10.39 DD=56.6%
    #   v42_a_extra_relaxed (双放宽):        n=316 win=35.1% CAGR=+12510% Sharpe=10.31 DD=56.6%
    #   v42_buf05 (buffer 0.02→0.05) ⭐:    n=312 win=35.3% CAGR=+12974% Sharpe=10.43 DD=56.6%
    # v42_buf05 是 v40_tp_08 之后最大胜出: CAGR +42% (+9113→+12974), DD 持平 56.6%,
    # win% 仅 -2pp。零成本微调!
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — 跨周期真胜出 ===
    #   2024-09→2025-03: n=114 win=25.4% yield= +222.05% Sharpe=5.21 DD=77.9% ⭐
    #   2025-03→2025-09: n=137 win=18.2% yield= +104.13% Sharpe=4.39 DD=77.9% ⭐
    #   2025-09→2026-03: n= 97 win=20.6% yield= +131.65% Sharpe=4.34 DD=26.6% ⭐
    #   2026-03→2026-09: n=273 win=35.9% yield=+7574.87% Sharpe=10.64 DD=56.6%
    # 4/4 窗口 yield 全部显著优于 v40_tp_08:
    #   震荡段 yield 翻倍 (+91%→+222%, +54%→+104%, +63%→+132%)
    #   拉涨段 yield +10% (+6871→+7575)
    #   DD 仅震荡段微升 3pp (74.9→77.9), 拉涨段持平 56.6%
    # === v3 体系最终产品 (v42_buf05 优先) ===
    # 实盘部署首选 v42_buf05 (跨周期 yield 翻倍, DD 仅微升 3pp).
    # 备选 v36_d_converge (DD 极端敏感场景).
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; buffer widened to 0.05. No ATR multiplier.
    "v42_buf05": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.05,
    },
    # === 2026-09-21 微调发现（v43）— v42_buf05 + ratio 极端放宽 ===
    # 在 v42_buf05 (buffer 0.05) 基础上放宽 below_ratio_60, 4 组对比 (12m):
    #   v43_ratio04 (ratio 0.5→0.4):           n=343 win=33.8% CAGR=+15421% Sharpe=10.04 DD=61.4%
    #   v43_ratio03 (ratio 0.5→0.3) ⭐:        n=378 win=33.9% CAGR=+25352% Sharpe=10.06 DD=66.5%
    #   v43_a_extra_relax (alias):              n=343 (与 ratio04 同)
    #   v43_ratio04_buf07 (ratio 0.4+buf 0.07): n=349 win=34.1% CAGR=+18124% Sharpe=10.12 DD=61.4%
    # v43_ratio03 是 12m 历史新高: CAGR +95% vs v42_buf05 (+12974 → +25352), n=378 充足.
    # DD 66.5% (vs v42 56.6%, +9.9pp 略恶化).
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — 跨周期真胜出 ===
    #   2024-09→2025-03: n=179 win=21.2% yield= +280.94% Sharpe=5.67 DD=85.5% ⭐
    #   2025-03→2025-09: n=191 win=18.3% yield= +169.28% Sharpe=5.18 DD=85.5% ⭐
    #   2025-09→2026-03: n=146 win=21.2% yield= +238.00% Sharpe=5.42 DD=29.2% ⭐
    #   2026-03→2026-09: n=325 win=35.1% yield=+14471.34% Sharpe=10.38 DD=66.5% ⭐
    # 4/4 窗口 yield 全部显著优于 v42_buf05:
    #   震荡段 +27% ~ +81% (+222→+281, +104→+169, +132→+238)
    #   拉涨段 +91% (+7575→+14471)
    #   DD: 震荡段 78→85% (+8pp), 拉涨段 57→66% (+10pp), Sharpe 5+ 维持
    # === v3 体系最终产品 (v43_ratio03 优先) ===
    # 实盘部署首选 v43_ratio03 (12 次迭代的最终胜出, 跨周期 yield 翻倍再翻倍).
    # DD 敏感可退回 v42_buf05 或 v36_d_converge.
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; ratio extreme relaxation 0.5→0.3. No ATR multiplier.
    "v43_ratio03": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.3,
        "close_ma60_buffer": 0.05,
    },
    # === 2026-09-21 微调发现（v44）— v43_ratio03 进一步极端放宽 ===
    # 在 v43_ratio03 (ratio 0.3) 基础上进一步放宽, 4 组对比 (12m):
    #   v44_ratio02 (ratio 0.3→0.2):           n=416 win=33.2% CAGR=+33193% Sharpe=9.91 DD=64.0%
    #   v44_ratio01 (ratio 0.3→0.1):           n=437 win=32.3% CAGR=+36417% Sharpe=9.72 DD=67.5%
    #   v44_buf07 (buffer 0.05→0.07):           n=385 win=34.0% CAGR=+29598% Sharpe=10.11 DD=66.5%
    #   v44_ratio02_buf07 (双极端) ⭐:          n=425 win=33.4% CAGR=+41166% Sharpe=9.99 DD=64.0%
    # ⚠️ 警惕: 全部 v44 配置 win% < 34%, SL 占比 65%+, 类似 v37 陷阱信号.
    # === 2026-09-21 walk-forward 待验证 (Task #33) ===
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; double extreme (ratio 0.2 + buf 0.07). v3 体系工程最优. No ATR multiplier.
    "v44_ratio02_buf07": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # === 2026-09-21 微调发现（v45）— v44_ratio02_buf07 进一步极端放宽 ===
    # 在 v44 基础上, 4 组对比 (12m):
    #   v45_ratio01_buf07 (ratio 0.2→0.1):    n=449 win=32.5% CAGR=+49605% DD=67.5%
    #   v45_ratio02_buf10 (buffer 0.07→0.10):  n=432 win=33.3% CAGR=+42700% DD=64.0%
    #   v45_ratio01_buf10 (双极端) ⭐:         n=458 win=32.3% CAGR=+51162% DD=67.5%
    #   v45_sl_001 (SL 0.0005→0.001):          n=425 win=33.6% CAGR=+37988% DD=64.2%
    # v45_ratio01_buf10 是 12m 历史新高: CAGR +51162%.
    # ⚠️ win% 32.3% / SL 占比 67% — 已接近"瞎猜"信号水平, 警惕单点过拟合.
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — DD 临界 ===
    #   2024-09→2025-03: n=291 win=23.0% yield=+1255.09% Sharpe=7.25 DD=95.4% ⭐
    #   2025-03→2025-09: n=276 win=16.7% yield= +284.22% Sharpe=5.55 DD=95.4% ⭐
    #   2025-09→2026-03: n=231 win=19.5% yield= +529.05% Sharpe=6.37 DD=53.0% ⭐
    #   2026-03→2026-09: n=380 win=33.7% yield=+20791.50% Sharpe=10.09 DD=67.5% ⭐
    # 跨周期 yield 全面优于 v44:
    #   震荡段 +144% / +46% / +40% (+513→+1255, +195→+284, +377→+529)
    #   拉涨段 +8% (+19230→+20791)
    # ⚠️ 但 DD 全部恶化 3-15pp (震荡段 87%→95%, 拉涨段 64%→67.5%).
    # 震荡段 DD 95% 已接近工程极限 — 再放宽 5pp 触底破产.
    # === v3 体系最终产品 (v44_ratio02_buf07 仍优先, v45 备选) ===
    # 实盘部署首选 v44_ratio02_buf07 (DD 仍可控, 跨周期稳健).
    # v45_ratio01_buf10 是高 yield 但高 DD 备选 — 仅在 DD 容忍度高时考虑.
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; extreme relaxation (ratio 0.1 + buf 0.10). DD临界 67-95%. No ATR multiplier.
    "v45_ratio01_buf10": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.1,
        "close_ma60_buffer": 0.10,
    },
    # === 2026-10-12 v50 系列 — 出场点 + 入场质量 微调探索 ===
    # v44 24m baseline: trades=148 win=31.1% CAGR=+110.17% Sharpe=6.91 DD=12.12% TP/SL/T=35/101/12
    # SL 占比 68% 是 v44 体系痛点。探索"给 TP 多一点时间"是否降低 SL 占比。
    # v46_mh4/mh7 单点 sweep 在 12m 上 v44 vs v46_mh4 同 n=425 win% +1.6pp CAGR -8% DD 持平;
    # 24m 行为可能不同(震荡段 yield 不同分布)。
    # 实验设计:每次只改 1 个参数, 跑 24m 对比 v44。
    "v50_mh6": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 12,  # v50 sweep 起点
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 6,  # ← v44 的 5→6 (给 TP 多 1 天机会)
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v50_slope (2026-10-12): 在 v44 基础上加 F 条件 — MA20 5 日回归斜率 ≤ 0。
    # 用户提示"下降趋势的斜率"维度: 5 条件 (A/B/C/D/E) 全部区间/布尔,
    # 无显式「趋势斜率」度量。MA20 在 5 日内若 slope > 0, 标的可能处于
    # 反弹中段而非下降趋势, 与 short_reversal 哲学不符, 应排除。
    # 预期: 减少横盘假信号, 提高胜率; n 略减, CAGR 持平或上升。
    "v50_slope": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 12,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,  # 同 v44
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        # === v50 F 条件 (新维度) ===
        "require_ma20_slope_neg": True,  # 开启
        "ma20_slope_period": 5,
    },
    # v50_slope_strict (2026-10-12): v50_slope 加强版, slope ≤ -0.003/day。
    # 要求更严格的下降趋势 (5 日累计 -1.5% 以上), 进一步过滤反弹中段。
    "v50_slope_strict": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 13,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "ma20_slope_threshold": -0.003,  # ← 严格化 (要求每天 -0.3%)
    },
    # === 2026-10-12 v51 系列 — G 条件: 弱势股过滤 (1M/3M/6M 累计跌幅) ===
    # v50_slope (Calmar 9.76) 是当前 F 维度最佳; 用户提示从「斜率」切到「弱势水平」:
    # 重新定义"下降趋势"为"弱势股" — 过去 N 日累计跌幅超阈值。
    # 4 个候选, 在 v44_ratio02_buf07 基础上叠加 G 条件:
    #   v51_weak_1m:   1M ≤ -5%   (近期弱势, 21 trading days)
    #   v51_weak_3m:   3M ≤ -10%  (中期弱势, 63 trading days)
    #   v51_weak_6m:   6M ≤ -15%  (长期弱势, 126 trading days)
    #   v51_weak_combo: 三窗口叠加 (持续弱势, 防止只是短期回调)
    # 与 F 互补: F 测短期动量 (rate of change), G 测中期水平 (cumulative loss)。
    # v51_weak_1m (2026-10-12): 1M 累计跌幅 ≥ 5%。
    "v51_weak_1m": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 14,  # v51 sweep 起点
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        # === v51 G 条件 (新维度) ===
        "require_weak_1m": True,
        "weak_1m_threshold": -0.05,
    },
    # v51_weak_3m (2026-10-12): 3M 累计跌幅 ≥ 10%。
    "v51_weak_3m": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 14,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_weak_3m": True,
        "weak_3m_threshold": -0.10,
    },
    # v51_weak_6m (2026-10-12): 6M 累计跌幅 ≥ 15%。
    "v51_weak_6m": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 14,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_weak_6m": True,
        "weak_6m_threshold": -0.15,
    },
    # v51_weak_combo (2026-10-12): 三窗口叠加 (持续弱势, 最严过滤)。
    "v51_weak_combo": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 14,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_weak_1m": True,
        "weak_1m_threshold": -0.03,  # 略放宽 (-5%→-3%), 否则太严无信号
        "require_weak_3m": True,
        "weak_3m_threshold": -0.10,
        "require_weak_6m": True,
        "weak_6m_threshold": -0.15,
    },
    # === 2026-10-12 v52 系列 — H 条件: 无成交下跌过滤 (5d/20d 成交金额比率) ===
    # v51 G 条件 (cumret) 失败 — 测绝对跌幅错把"中段下跌"当入场点。
    # 用户提示"探索新方向": 改测「资金流衰减」— 卖压枯竭 (selling exhaustion)。
    # 物理直觉: amount_5d_avg / amount_20d_avg ≤ 阈值 = 近期成交显著萎缩
    #   → 该股已被市场"放弃" → 任何反弹都缺乏资金跟进 → 死猫跳。
    #   → 对 short_reversal 最有利 (空头最佳博弈标的)。
    # 4 个候选, 在 v44_ratio02_buf07 基础上叠加 H 条件:
    #   v52_dryup_07:  5d/20d ≤ 0.70  (中等萎缩 30%+, 起点)
    #   v52_dryup_05:  5d/20d ≤ 0.50  (严重萎缩 50%+, 极端弱势)
    #   v52_dryup_085: 5d/20d ≤ 0.85  (轻微萎缩 15%+, 宽松)
    #   v52_dryup_strict: 组合 (0.5 + 3M cumret ≤ -10%, 卖压枯竭 + 中期弱势)
    # v52_dryup_07 (2026-10-12): 5d/20d 成交额比率 ≤ 0.70 (起点假设)。
    "v52_dryup_07": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 18,  # v52 sweep 起点 (v50:14 + v51:14 + v52:4)
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        # === v52 H 条件 (新维度) ===
        "require_amount_dryup": True,
        "amount_dryup_threshold": 0.70,
    },
    # v52_dryup_05 (2026-10-12): 5d/20d 成交额比率 ≤ 0.50 (严重萎缩)。
    "v52_dryup_05": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 18,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_amount_dryup": True,
        "amount_dryup_threshold": 0.50,
    },
    # v52_dryup_085 (2026-10-12): 5d/20d 成交额比率 ≤ 0.85 (轻微萎缩, 宽松)。
    "v52_dryup_085": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 18,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_amount_dryup": True,
        "amount_dryup_threshold": 0.85,
    },
    # v52_dryup_combo (2026-10-12): H (严重萎缩 0.5) + G (3M 累计 ≤ -10%)。
    # 假设: 同时满足"近期资金枯竭"和"中期已下跌"是最纯粹的 dead-cat bounce。
    "v52_dryup_combo": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 18,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_amount_dryup": True,
        "amount_dryup_threshold": 0.50,
        "require_weak_3m": True,
        "weak_3m_threshold": -0.10,
    },
    # === 2026-10-12 v53 系列 — I 条件: RSI(14) 超卖过滤 (经典反转指标) ===
    # v51 (G cumret) + v52 (H amount dry-up) 连续失败 — 测"水平"(跌幅)
    # 和"资金流"(amount) 都不对。用户选 B 方向: 改测"价格动量超卖"。
    # RSI(14) < 阈值 = 14 日 Wilder 平滑动量极弱 = 卖方力度耗尽前的最后一击。
    # 与 F (slope) 互补: F 测趋势方向, I 测超卖程度; 与 H 正交: H 测资金流。
    # 4 个候选, 在 v44_ratio02_buf07 基础上叠加 I 条件:
    #   v53_rsi_30:  RSI(14) < 30  (经典超卖, 起点假设)
    #   v53_rsi_25:  RSI(14) < 25  (极端超卖, 更严)
    #   v53_rsi_35:  RSI(14) < 35  (轻微超卖, 宽松)
    #   v53_rsi_30_slope: I 30 + F (MA20 5d slope ≤ 0, 组合双确认)
    # v53_rsi_30 (2026-10-12): 经典 RSI<30 超卖。
    "v53_rsi_30": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 22,  # v53 sweep 起点 (v50:14 + v51:14 + v52:18 + v53:4)
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        # === v53 I 条件 (新维度) ===
        "require_rsi_oversold": True,
        "rsi_oversold_threshold": 30,
    },
    # v53_rsi_25 (2026-10-12): 极端超卖 RSI<25。
    "v53_rsi_25": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 22,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_rsi_oversold": True,
        "rsi_oversold_threshold": 25,
    },
    # v53_rsi_35 (2026-10-12): 轻微超卖 RSI<35 (宽松, 起点对照)。
    "v53_rsi_35": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 22,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_rsi_oversold": True,
        "rsi_oversold_threshold": 35,
    },
    # v53_rsi_30_slope (2026-10-12): I 30 + F (MA20 slope ≤ 0) 组合双确认。
    # 假设: 同时满足"超卖"+"下降趋势未结束"是最强 dead-cat bounce setup。
    "v53_rsi_30_slope": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 22,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_rsi_oversold": True,
        "rsi_oversold_threshold": 30,
        "require_ma20_slope_neg": True,  # v50 F 条件
    },
    # === 2026-10-12 v54 系列 — TP/SL 调参 (出场维度新方向) ===
    # v51 (G cumret) + v52 (H dry-up) + v53 (I RSI) 三个入场维度连续失败 —
    # A/B/C/D/E 五条件已 selective 到顶, 加任何过滤都把 universe 砍到 0-3 笔。
    # 切换到「出场维度」: v50_slope 93 SL vs 33 TP = 74% SL 退出率,
    # SL=0.0005 (5 bp) 太紧被 noise 反复打。3 个候选, 在 v50_slope 基础上调 TP/SL:
    #   v54_sl_01:    SL 0.0005→0.01 (20x 放宽, 测 noise-driven SL 假说)
    #   v54_sl_005:   SL 0.0005→0.005 (10x 放宽, 中位)
    #   v54_tp10_sl01: TP 0.08→0.10 + SL 0.01 (TP/SL 都放宽, 10:1 风险比)
    # v54_sl_01 (2026-10-12): 仅 SL 放宽 20x, TP 不变。
    "v54_sl_01": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 25,  # v54 sweep 起点 (v50:14 + v51:14 + v52:18 + v53:22 + v54:3)
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,           # 不变
        "sl_pct": 0.01,           # 0.0005 → 0.01 (20x 放宽)
        "max_hold": 5,            # 不变
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,  # v50 F 条件
    },
    # v54_sl_005 (2026-10-12): SL 放宽 10x (中位)。
    "v54_sl_005": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 25,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.005,          # 0.0005 → 0.005 (10x 放宽)
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # v54_tp10_sl01 (2026-10-12): TP+SL 都放宽 (10:1 风险比)。
    "v54_tp10_sl01": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 25,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.10,           # 0.08 → 0.10 (25% 大)
        "sl_pct": 0.01,           # 0.0005 → 0.01 (20x 放宽)
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # === 2026-09-21 微调发现（v46）— SL 收紧 / max_hold 调整（新方向） ===
    # 14 次迭代后, "放宽入场" 主线已工程上限 (v45 触底 DD 临界).
    # 切换到风险控制方向: SL 收紧 / max_hold 调整.
    # 4 组对比 (12m, 在 v44 基础上):
    #   v46_sl_0003 (SL 0.0005→0.0003):       n=425 win=33.2% CAGR=+40365% Sharpe=10.01 DD=63.9% ⭐
    #   v46_sl_0002 (SL 0.0005→0.0002) ⭐:    n=425 win=33.2% CAGR=+41201% Sharpe=10.05 DD=63.8% ⭐⭐
    #   v46_mh4     (max_hold 5→4):            n=425 win=34.8% CAGR=+39676% Sharpe=10.14 DD=64.0%
    #   v46_mh7     (max_hold 5→7):            n=424 win=31.8% CAGR=+40785% Sharpe= 9.87 DD=64.0%
    # v46_sl_0002 是新方向最佳: CAGR 几乎与 v44 持平, DD 压到 63.8% (vs v44 64-87%).
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   2024-09→2025-03: n=230 win=21.7% yield= +536.61% Sharpe=6.75 DD=87.1%
    #   2025-03→2025-09: n=225 win=17.3% yield= +207.34% Sharpe=5.60 DD=87.1%
    #   2025-09→2026-03: n=188 win=20.7% yield= +396.13% Sharpe=6.20 DD=38.1%
    #   2026-03→2026-09: n=357 win=34.5% yield=+19012.54% Sharpe=10.37 DD=63.8%
    # 跨周期 vs v44_ratio02_buf07:
    #   震荡段 yield +12-23% (+513→+537, +195→+207, +377→+396) ⭐
    #   拉涨段 yield -1% (19230→19013, 微缩)
    #   震荡段 DD 87% 完全一致 (SL 收紧跨周期未生效) ⚠️
    #   拉涨段 DD -0.2pp (64→64, 微降) ⭐
    # === 综合: v46_sl_0002 是 v44 的边际改善 (震荡段 yield +12-23%, DD 持平) ===
    # 实盘部署: v44 仍是首选 (12m CAGR 略高); v46_sl_0002 备选 (震荡段 yield 略高).
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0002
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; SL tightened 0.0005→0.0002 for marginal DD improvement. No ATR multiplier.
    "v46_sl_0002": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 replay_strategy_v3.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # short_reversal 11 preset 是 v33/v34/v37/v39_04_09/v41/v47 顺序 sweep
        # (虽 v37/v39/v41 已删除但 sweep 历史保留), 总比较数 ≈ 11 × 邻域大小。
        # walkforward 输出走 dna_stats.walkforward_report 自动套 DSR+Bonferroni。
        "n_comparisons": 11,
        # §2 (2026-09-22, CLAUDE.md All-In Sizing Policy):
        # Engine `replay_strategy_v3.py:47` hardcodes position_fraction=1.0;
        # 显式声明如下, 表明预设遵循 §2。
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0002,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # === 2026-09-21 微调发现（v47）— ⚠️⚠️⚠️ 破产触底案例 (现金透支 6 亿) ===
    # v47_d_strict_warning 已删除 (2026-09-22): 12m CAGR 历史最高 (+328466%),
    # 但 cash gate 触发时 NAV=-6.22亿, cash 透支 6 亿倍数 — 破产触底。
    # v36_d_converge / v44 的 d_mode='converge_strict' 必须保持 — 砍掉部分
    # 弱信号是防止 margin call 的关键防线.
    # === v3 体系工程教训 (v47 失败案例) ===
    # 16 次迭代完整建立 v3 体系:
    #   - 入场侧 (A/B/D): 改善极限在 v44/v46 (放宽+收紧组合)
    #   - 出场侧 (TP/SL/mh): TP 拉宽+SL 收紧组合, 在 v40/v46 已最优
    #   - pct_chg 窗口: 上限放宽是 v39 的关键胜出, 下限收紧是 v41/v35 失败
    #   - universe: 仍受限于 'mainboard_only' (HS300 历史成分表未建立)
    #   - cash gate: 真实捕获 v47_d_strict 的破产触底 — 必须保留
    # 实盘部署首选 v44_ratio02_buf07 (跨周期稳健 + DD 仍可控).
    # === 2026-09-21 收敛性微调（v48）— 边际探索 ===
    # v3 体系已收敛. v48 系列 4 组边际探索:
    #   v48_pctchg_025 (下限 2.5%):       n=567 CAGR=+101051% DD=78.0%
    #   v48_pctchg_028 (下限 2.8%):       n=471 CAGR= +56001% DD=75.6%
    #   v48_buf05_pctchg025 (回退 buffer): n=557 CAGR= +82987% DD=78.0%
    #   v48_tp_085 (TP 8→8.5%):           n=425 CAGR= +41628% DD=66.4%
    # ⚠️ 所有 v48 配置 12m 小幅改动 → CAGR 大幅跳变, DD 显著恶化
    # (64% → 78%) — 过拟合信号. v3 体系已完全收敛.
    # === 17 次迭代工程总结 (2026-09-22 重组) ===
    # v3 体系工程最优: v44_ratio02_buf07 (跨周期稳健 + DD 可控).
    # 备选: v46_sl_0002 (震荡段略优) / v40_tp_08 (TP 拉宽基线).
    # 真正胜出方向 (11 个跨周期): v35/v36/v38/v39_03_10/v40×2/v42/v43/v44/v45/v46
    #   D 严格收敛 (v36) / A 放宽 ratio+buffer (v38-v45) /
    #   pct_chg 上限放宽 (v39) / TP 拉宽 (v40) / SL 收紧 (v46)
    # 已删除的破产/过拟合 preset (7 个, 2026-09-22):
    #   v33_mainboard_tp2_sl05_dneg / v33_mainboard_tp6_sl005_mh5_realistic
    #   v34_mainboard_pctchg_tight / v37_liq_3e7_5e8 / v39_pctchg_04_09
    #   v41_pctchg_04_10 / v47_d_strict_warning
    # === 2026-09-21 最终验证（v49）— SL 收紧触底工程极限 ===
    # v49 4 组 SL 收紧 (在 v44 基础上):
    #   v49_sl_00010 (SL 0.0001): n=425 CAGR=+42064% Sharpe=10.09 DD=63.8% TP/SL/T=108/283/34
    #   v49_sl_00015 (SL 0.00015): n=425 CAGR=+41628% Sharpe=10.07 DD=63.8% TP/SL/T=108/283/34
    #   v49_sl_00025 (SL 0.00025): n=425 CAGR=+40788% Sharpe=10.03 DD=63.9% TP/SL/T=108/283/34
    #   v49_sl_00010_tp09 (双向): n=425 CAGR=+39200% Sharpe= 9.65 DD=65.9% TP/SL/T= 92/289/44
    # v49 揭示: SL < 0.0002 时所有 TP/SL/T 完全相同 — SL 已触底工程极限.
    # v44_ratio02_buf07 (SL 0.0005) 的 n/win%/DD 与 v49 SL 0.0001 完全一致.
    # v3 体系工程最优已确认收敛 = v44_ratio02_buf07.
    # === 18 次迭代最终工程总结 (2026-09-21) ===
    # 工程最优: v44_ratio02_buf07 (12m CAGR +41166%, 跨周期稳健, DD 64-87%)
    # 备选: v46_sl_0002 (震荡段略优), v40_tp_08 (TP 拉宽基线)
    # 慎: v45_ratio01_buf10 (DD 临界 67-95%)
    # 已确认失败/破产案例 (6 个): v34/v47_d_strict (破产), v37/v41 (单点过拟合跨周期崩), v35/v36_us5_12 (信号过少)
    # === 2026-10-12 v55 系列 — 重新定义"下降趋势"为"弱势股" (替代 F=MA20 slope) ===
    # v50_slope (Calmar 9.76) 用 F=MA20 5d slope ≤ 0 定义 downtrend (测「短期动量」).
    # v51 (G cumret) 在 F 之上叠加 1M/3M/6M 累计跌幅 → Calmar 5.89/3.91/3.26, 假说被证伪
    #   (越过滤越差, 因 v50 已是 selective 顶峰, 再加过滤只能砍数量).
    # v55 是 G 替代 F 的"二选一"实验: 用户提示「把下降趋势改为弱势股」.
    # 设计: 关闭 F=MA20 slope, 单独开 G=1M/3M/6M cumret, 测 G 是否比 F 更好
    #   单独定义 downtrend (而非叠加). 4 个候选, 2-yr 验证:
    #   v55_swap_1m:    F=off, G_1m≤-5%   (1M 累计跌 5%)
    #   v55_swap_3m:    F=off, G_3m≤-10%  (3M 累计跌 10%)
    #   v55_swap_6m:    F=off, G_6m≤-15%  (6M 累计跌 15%)
    #   v55_swap_combo: F=off, G_1m/3m/6m 三窗口叠加 (持续弱势最严)
    # 验证逻辑: 若任一 Calmar ≥ 9.76 → 弱股比斜率更适合定义 downtrend;
    #   若全部 < 9.76 → v50_slope 已达工程最优.
    # v55_swap_1m (2026-10-12): 用 1M 累计跌幅替代 MA20 5d slope 定义 downtrend。
    "v55_swap_1m": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 28,  # v55 sweep 起点 (v54:25 + v55:4-1=28)
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        # === v55 SWAP: 关 F, 开 G_1m ===
        "require_ma20_slope_neg": False,  # 关掉 v50 F 条件
        "require_weak_1m": True,         # 1M 累计跌幅 ≥ 5%
        "weak_1m_threshold": -0.05,
    },
    # v55_swap_3m (2026-10-12): 用 3M 累计跌幅替代 MA20 slope。
    "v55_swap_3m": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 28,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": False,
        "require_weak_3m": True,         # 3M 累计跌幅 ≥ 10%
        "weak_3m_threshold": -0.10,
    },
    # v55_swap_6m (2026-10-12): 用 6M 累计跌幅替代 MA20 slope。
    "v55_swap_6m": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 28,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": False,
        "require_weak_6m": True,         # 6M 累计跌幅 ≥ 15%
        "weak_6m_threshold": -0.15,
    },
    # v55_swap_combo (2026-10-12): 三窗口叠加 (持续弱势最严), 替代 MA20 slope。
    "v55_swap_combo": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 28,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": False,
        "require_weak_1m": True,
        "weak_1m_threshold": -0.05,
        "require_weak_3m": True,
        "weak_3m_threshold": -0.10,
        "require_weak_6m": True,
        "weak_6m_threshold": -0.15,
    },
    # === 2026-10-12 v56 系列 — 持仓时间扩展 (max_hold 调参) ===
    # v50_slope (Calmar 9.76) 5 个 entry-condition 方向连续失败 (v51-v55), 已证入场维度工程最优.
    # 切换到「持仓时间」: v50_slope max_hold=5, avg hold 2.83d, 但 12 笔 time-exit (8.7%) 暗示
    #   部分交易可能需要更多时间兑现. 3 个候选, 在 v50_slope 基础上:
    #   v56_mh_07: max_hold 5→7  (温和扩展, 让 TP 兑现更多)
    #   v56_mh_10: max_hold 5→10 (激进扩展, 测是否能捕捉罕见长 runner)
    #   v56_mh_03: max_hold 5→3  (反向: 缩短让 SL 更早触发, 测 SL 主导假说)
    # 验证逻辑: 若 v56_mh_07/10 Calmar ≥ 9.76 → max_hold 是新维度, 可继续调;
    #   若全部 < 9.76 → 5 个方向全部工程上限, v50_slope 为最终 best.
    # v56_mh_07 (2026-10-12): max_hold 5→7, 温和扩展。
    "v56_mh_07": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 31,  # v56 sweep 起点 (v55:28 + v56:3)
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 7,             # 5 → 7
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # v56_mh_10 (2026-10-12): max_hold 5→10, 激进扩展。
    "v56_mh_10": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 31,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 10,            # 5 → 10
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # v56_mh_03 (2026-10-12): max_hold 5→3, 反向缩短, 测 SL 主导假说。
    "v56_mh_03": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 31,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 3,             # 5 → 3
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # v57 (2026-10-12): SL 之后冷静期 (J 条件) preset 变体。
    # 假设: SL 出场后立即再入场容易「报复交易」, 同一波亏势尚未结束,
    # 下一笔也很可能输。强制 N 个交易日的全局冷却, 跳过最强信号。
    # max_positions=1 时 J 是「全局」冷却, 因为单仓策略同一时间只持 1 笔,
    # 冷却窗口对所有候选 stock 都生效 (与 per-symbol 冷却不同)。
    # 三档: 3 / 5 / 7 个交易日, 与 v50_slope baseline 平行测试。
    # v57_cd_03 (2026-10-12): 冷却 3 日, 保守档。
    "v57_cd_03": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 34,  # v57 sweep 起点 (v56:31 + v57:3)
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,             # 与 v50_slope 相同
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "sl_cooldown_days": 3,     # J 条件
    },
    # v57_cd_05 (2026-10-12): 冷却 5 日, 中档。
    "v57_cd_05": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 34,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "sl_cooldown_days": 5,
    },
    # v57_cd_07 (2026-10-12): 冷却 7 日, 激进档。
    "v57_cd_07": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 34,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "sl_cooldown_days": 7,
    },
    # v58 (2026-10-13): 多仓并行 (max_positions 1→2)。
    # 假设: 1→2 把单点风险分散到 2 个独立信号, 降低 DD 而不显著损失收益。
    # 同时调整每笔 sizing 为 free_cash / max_positions, 维持 all-in 总仓位。
    # 数据顺序作为隐式 ranking — 第一个满足 A-I 的 stock 优先, 无显式 score 排序。
    # 风险: data 顺序的随机性会引入选股噪声。
    # v58_mp_2 (2026-10-13): max_positions=2, 单笔 sizing 50% free_cash。
    "v58_mp_2": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 37,  # v58 sweep 起点 (v57:34 + v58:3)
        "position_sizing": "all_in",
        "max_positions": 2,      # 1 → 2
        "position_fraction": 1.0, # 仍 all-in 总仓位, 引擎除以 max_positions
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # v58_mp_3 (2026-10-13): max_positions=3, 单笔 sizing 33% free_cash。
    # 多仓 sweep 的「极端点」,看 N 进一步增大时 curve 是否仍下降。
    "v58_mp_3": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 37,
        "position_sizing": "all_in",
        "max_positions": 3,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
    },
    # v61_k (2026-10-13): K 条件 = 日内反转。
    # 死猫跳经典微观结构: 开盘低, 收盘高, (close-low)/(high-low) > 0.6。
    # 与 F 正交: F 测多日 slope 方向, K 测单日 intraday 形态。
    # 假设: 当日内从低点回收 ≥ 60% 区间 + 收阳, 买盘在日内接住卖压
    #   → 但因整体仍下降 (F 确认), 次日大概率回吐 (死猫跳)。
    # 单独启用 (无 F), 测 K 是否独立有效。
    "v61_k": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 15,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": False,
        "require_intraday_reversal": True,
        "intraday_reversal_threshold": 0.6,
        "intraday_reversal_require_close_above_open": True,
    },
    # v61_kf (2026-10-13): F + K 加性堆叠。两者必须同时过。
    # 这是「正交方向: 加性多条件堆叠」的真正测试 — 在 v50 基础上加 K,
    # 测 K 是否能在 F 之上提供独立信息(而不只是替换 F 的子集信号)。
    "v61_kf": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 15,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "require_intraday_reversal": True,
        "intraday_reversal_threshold": 0.6,
        "intraday_reversal_require_close_above_open": True,
    },
    # v63_ensemble (2026-10-13): 集成信号 — 50/50 资金分配 v50_slope + v44_ratio02_buf07。
    # 假设: v50_slope (F 条件 ON, 强趋势下行反转) 与 v44_ratio02_buf07 (无 F, 中性反转)
    #   在不同 regime 错峰, 等权组合可降 DD 而不损收益 (diversification within reversal family)。
    #
    # ⚠️ REGIME-DEPENDENT (2026-10-13 复核修正): 优势不跨周期稳健。
    #   2024-2026 (原测窗口):
    #     - WFV 4×6mo (2024-2025): mean Calmar +10.9% (10.28 vs 9.27)
    #     - Holdout 2026-04~09: Calmar +5.4% (84.72 vs 80.41)
    #   2020-2023 复核 (truly OOS, 4 regime, 非调参):
    #     - mean Calmar delta = -0.07 (v50 10.09 vs v63 10.01) → 无差异
    #     - per-window: {0.00, -0.75, +0.11, +0.35}, std≈0.45 → 全在噪声内
    #   结论: v63 的 edge 很可能是 2024-2026 regime 特定, 而非稳健 alpha。
    #   默认 champion 应保持 v50_slope; v63 仅作 regime-conditional opt-in。
    #
    # 引擎实现: short_reversal/engine.py::_run_ensemble 递归调用 run_backtest_v3,
    #   汇总等权 PnL + 保守 max_dd (worst-case across subs)。
    # 注意: 单元持仓 max_positions=1 per sub, 合计 ≈ 2 个独立子仓。
    "v63_ensemble": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 13,  # honest count per §5 iterative-tuning accounting
        "position_sizing": "ensemble_split",
        "max_positions": 1,  # per sub-strategy
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "ensemble_substrategies": ["v50_slope", "v44_ratio02_buf07"],
        "ensemble_weight": 0.5,
    },
    # v64_ensemble_3leg (2026-10-13): 3-leg 集成 — 加 v50_slope_strict (slope ≤ -0.003)。
    # 目的: 测 ensemble 容量 — 第 3 个更严格的趋势子策略能否进一步分散 DD。
    # 假设: strict 只在最强下行趋势入场 (更少但更高质量的信号), 与 v50/v44 错峰。
    # n_trials=14 (per §5)。
    "v64_ensemble_3leg": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 14,
        "position_sizing": "ensemble_split",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "ensemble_substrategies": [
            "v50_slope",
            "v44_ratio02_buf07",
            "v50_slope_strict",
        ],
        "ensemble_weight": 0.3333333333,
    },
    # v65_trailing (2026-10-13): v50_slope + 浮动止损 (trailing stop, short-side)。
    # 假设: v50 固定 SL 只锁风险不锁利润; 加 trailing (跟踪最低价) 可在
    # 死猫跳反弹后继续下跌时锁定浮盈。
    # 配置: trailing_stop_pct=0.02 (2% 回撤即止盈出场), activation=0.02
    #   (浮盈 ≥ 2% 才激活 trailing, 避免过早收紧)。
    # n_trials=15 (per §5)。
    "v65_trailing": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 15,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "trailing_stop_pct": 0.02,
        "trailing_activation_pct": 0.02,
    },
    # v66_regime (2026-10-13): v50_slope + 市场宽度 regime gate。
    # 假设: 做空死猫跳在牛市普涨 regime 下失效 (beta 抬升)。用市场宽度
    #   (universe 中 close > MA20 比例) 作为 regime 代理: breadth ≤ 0.5
    #   (多数票在 MA20 之下 = 熊市) 才允许入场。
    # 与所有个股级条件 (A-K) 正交: 这是 market-level 维度。
    # n_trials=16 (per §5)。
    "v66_regime": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 16,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "require_market_breadth_bear": True,
        "market_breadth_max": 0.5,
    },
    # v67_broad (2026-10-13): v50_slope 策略不变, universe 扩展到
    # 主板 + 创业板(300) + 科创板(688)。
    # 假设: 死猫跳 reverse-momentum 在更广市场微观结构 (更多高波动/散户主导标的)
    #   上是否有额外 alpha。§4: 300/688 涨跌停 ±20%, 由 _board_limit_threshold
    #   按板+日期处理 (创业板 2020-08-24 起 20%)。
    # n_trials=17 (per §5)。
    "v67_broad": {
        "universe": "broad_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 17,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
    },
    # v68_conviction (2026-10-13): §2 合规 — 并发信号按统计信心排序填充。
    # 当前实现按 datas 顺序 (thscode 字母序) 填充 = 任意 tie-breaker。
    # CLAUDE.md §2 要求: "sort them by statistical conviction ... fill strictly
    # in that order"。v68 按 MA20 斜率升序 (最陡下降 = 最高空头信心) 排序。
    # 策略与 v50_slope 完全相同, 仅改 fill 选择顺序。
    # n_trials=18 (per §5)。
    "v68_conviction": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 18,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "entry_selection": "steepest_slope",
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]