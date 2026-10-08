"""策略 preset 配置。"""
from __future__ import annotations

from typing import Literal

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

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
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]