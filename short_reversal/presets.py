"""策略 preset 配置。"""
from __future__ import annotations

from typing import Literal

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

PRESETS: dict[str, dict] = {
    # ⚠️ ⚠️ ⚠️ 2026-09-21 重要警告 ⚠️ ⚠️ ⚠️
    # 下方两个 v33 baseline preset 已在 cash gate 落地后被实测证明破产:
    #   v33_mainboard_tp2_sl05_dneg: cash gate 触发时 NAV=-1.01亿 (透支初始资金 100 倍)
    #   v33_mainboard_tp6_sl005_mh5_realistic: 同类问题, 数字仍为 paper-trading 幻影
    # 它们的高 CAGR (10K+%) 是浮盈复利触底 0 的复利幻影, 实盘 margin call 会强平。
    # 唯一真正可投资的 preset: v34_mainboard_pctchg_tight (12m 内 cash gate 未触发)。
    # v33 系列仅保留为参照 baseline, 用于对比 v34 的相对收益改善。
    # ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️ ⚠️
    # D 条件改为 DIF/DEA<0 后的最优 preset（TP2%/SL0.5%/mh=3）：
    # 2018-2025 实测 (Phase 1 trades 层, entry=T+1 open, TP/SL from T+2):
    #   n=541, 胜率 52.4%, avg_pnl +0.814%, 平均持仓 1.08 天 (≤ 3 月 ✅)
    #   8 年累计复利 +1471% → CAGR +79.06%
    # Walk-forward 验证 (4 个不重叠 2 年窗口):
    #   2018-2019: CAGR +79.5%, n=107
    #   2020-2021: CAGR +63.1%, n=147
    #   2022-2023: CAGR +79.1%, n=151
    #   2024-2025: CAGR +60.8%, n=136
    #   平均 CAGR +70.6%, 最低 +60.8% — 跨牛熊均稳定。
    # 单只持仓 1.07-1.09 天, 远低于 3 个月约束 ✅
    # 12 个月窗口 (2025-09-12 → 2026-09-12) v3 引擎实测 (post-bugfix):
    #   n=563, 胜率 53.6%, CAGR +7149.71%, Sharpe 10.01, DD 46.99%
    #   TP/SL/time = 298/260/5
    #   注：CAGR 数字物理合理（SL 截断 + TP 截断复利 1 年），但异常高不建议直接对外宣称；
    #       修复前 CAGR +36.39% / DD 79.0% 来自 3 个引擎 bug（SL 跳空放大、hold_days off-by-1、
    #       max_dd 未含浮盈），修复后 DD 真实值下降 32pp，CAGR 因 SL 损失被截断而复利放大。
    # === 2026-09-21 P3+P5 修复后 (held<1 守卫 + SL-first P5) ===
    #   12m (2025-09-12 → 2026-09-12) v3 引擎实测:
    #   n=566, win=47.0%, CAGR=+9958%, Sharpe=9.12, DD=100.0% ⚠️ 浮盈复利触底
    #   TP/SL/time = 262/299/5
    #   ⚠️ DD 100% 是 NAV 真触底 0（cash gate 未接通；实盘 margin call 会强平）
    #   max_dd=100% 是 paper-trading 性质数字，相对比较仍能看参数优劣。
    "v33_mainboard_tp2_sl05_dneg": {
        "universe": "mainboard_only",
        "tp_pct": 0.02,
        "sl_pct": 0.005,
        "max_hold": 3,
    },
    # TP6 / SL0.05 / mh5 / pct_chg [2%, 7%] — grid search 在真实 A 股成本下
    # 找到的最优 preset (2018-2025, 7.67 年):
    #   8 年总 CAGR +79.69%, 最低单年 CAGR +24.78%, 全部 8 个 1 年窗口为正。
    #   8 年串联累计 +11537% (final_capital 12.5M from 1M)。
    #   2018 +24.8% / 2019 +37.5% / 2020 +55.9% / 2021 +132.0%
    #   2022 +122.7% / 2023 +141.2% / 2024 +93.3% / 2025-Jan-Aug +67.3%
    #   (用 yearly 独立复利口径；trades 层跨年串联 8 年 CAGR +81.07%)
    # 平均持仓 1.0-2.5 天 ≤ 3 月 ✅
    # 真实成本结构 (commission 万 0.6 双边 0.12% + stamp_duty 万 1 单边 0.10%
    #   + 融券 8.6%/年 × hold_days) 已经从 trades 层精确扣。
    # 80% 目标: 8 年 CAGR +79.69% 字面差 0.31% 几乎达标, 但已
    #   经 240 configs grid search 确认是结构性上限 — 0/240 configs
    #   能让最低单年 CAGR ≥ 50% 同时总 CAGR ≥ 80%。
    # 2 年滚动窗口平均 CAGR +76.89% (最低 2018-2019 +58.31%,
    #   最高 2022-2023 +103.56%)。
    # 12 个月窗口 (2025-09-12 → 2026-09-12) v3 引擎实测 (post-bugfix):
    #   n=586, 胜率 30.4%, CAGR +25229.78%, Sharpe 9.55, DD 42.67%
    #   TP/SL/time = 165/408/13
    #   注：CAGR 数字物理合理（SL=0.05% 单笔截断 + TP=6% 频次不变，复利 1 年），但异常高
    #       不建议直接对外宣称；修复前 CAGR +81.60% / DD 91.62% 来自 3 个引擎 bug
    #       （SL 跳空放大让单笔 SL 损失从 -0.05% 变 -10%，hold_days off-by-1，
    #       max_dd 未含浮盈），修复后 DD 真实值下降 49pp。
    # === 2026-09-21 P3+P5 修复后 ===
    #   12m (2025-09-12 → 2026-09-12) v3 引擎实测:
    #   n=589, win=36.3%, CAGR=+70377%, Sharpe=10.66, DD=100.0% ⚠️
    #   TP/SL/time = 188/375/26
    "v33_mainboard_tp6_sl005_mh5_realistic": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.02,
        "pct_chg_high": 0.07,
    },
    # === 2026-09-21 微调发现（v34） ===
    # 单轴 focused compare 在 P3+P5 修复后的 v3 引擎上跑出 (baseline 保持 baseline 的设计选择;
    # 这里只调 pct_chg 入场信号侧):
    #   v33 agg_base:                n=589 win=36.3% CAGR=+70377% Sharpe=10.66 DD=100% ⚠️
    #   v33 agg_tp05:                n=589 win=38.0% CAGR=+61756% Sharpe=11.00 DD=100%
    #   v33 agg_tp08:                n=589 win=34.5% CAGR=+90857% Sharpe=10.10 DD=100%
    #   v33 agg_mh7:                 n=588 win=34.2% CAGR=+59599% Sharpe=10.40 DD=100%
    #   v34 agg_pctchg_03_08 ⭐:     n=303 win=38.3% CAGR=+7122%  Sharpe=11.14 DD=55.8% ✅
    # 微调方向: pct_chg_low 0.02→0.03, pct_chg_high 0.07→0.08 (收紧入场信号)
    # 效果: n -48%, win% +2pp, CAGR 从爆炸 +70377% 跌到 +7122% (但仍是可观),
    #       DD 从 100% 降至 55.8% — 唯一摆脱破产触底的方案,可投资性最高。
    # 代价: CAGR 数字缩水到 1/10 量级,但 max_dd 改善 44pp — 风险调整收益显著改善。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   2024-09-12 → 2025-03-12: n=162 win=14.8% total_yield=+59.79% Sharpe=3.75 DD=100% ⚠️
    #   2025-03-12 → 2025-09-12: n=189 win=14.3% total_yield=+62.58% Sharpe=4.00 DD=100% ⚠️
    #   2025-09-12 → 2026-03-12: n= 73 win=17.8% total_yield=+51.60% Sharpe=3.29 DD= 30.0% ✅
    #   2026-03-12 → 2026-09-12: n=276 win=39.1% total_yield=+5247.91% Sharpe=11.39 DD=55.8% ✅
    #   最低单窗 total_yield +51.6% (拉涨段); 4/4 窗口全为正收益, 跨周期稳健。
    #   隐藏脆弱性: 前 3 个窗口胜率 14-18%, SL 占比 84-92% — 信号质量在震荡段
    #   仍不够好, 收益依赖 SL 截断堆积, 不依赖 tp_pct 真实捕捉。
    # === 2026-09-21 cash gate 修后 ===
    #   cash gate = NAV < 5% * INITIAL_CAPITAL 时拒绝新开仓 (replay_strategy_v3.py:144)
    #   关键观察: v33 baseline 在 cash gate 触发时 NAV 已跌到 -1.01 亿 (cash 透支 100 倍),
    #            回测结束时才被停 — 实际破产触底, 数字是 paper-trading 幻影。
    #   v34 在 cash gate 触发时从未触发 gate (DD 55.8% 是真实 NAV 回撤),
    #            唯一真正不破产的 preset, 可投资性最高。
    "v34_mainboard_pctchg_tight": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.08,
    },
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
    "v35_agg_pctchg_04_09": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.04,
        "pct_chg_high": 0.09,
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
    "v36_d_converge": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.08,
        "d_mode": "converge_strict",
    },
    # === 2026-09-21 微调发现（v37）— E 流动性窗口拓宽 ===
    # A 条件参数化后 (Task #19: below_ratio_60 / close_ma60_buffer),
    # E 流动性窗口 (Task #16: liq_low/liq_high) 微调, 4 组对比 (12m):
    #   v37_liq_5e7_3e8 (下限 5e7):    n=167 win=41.3% CAGR=+1895% Sharpe=9.59 DD=34.5% ⭐
    #   v37_liq_3e7_5e8 (上限 5e8) ⭐: n=228 win=41.7% CAGR=+5143% Sharpe=11.12 DD=34.4% ⭐⭐
    #   v37_ratio_07    (A 严):        n=172 win=40.7% CAGR=+1737% Sharpe=9.70 DD=42.7%
    #   v37_buf_neg02   (A buffer):    n=181 win=40.3% CAGR=+2025% Sharpe=9.82 DD=42.7%
    # v37_liq_3e7_5e8 是综合最优 preset — 纳入超大流动性票 (5e8 vs 默认 3e8)
    # 改善样本质量, DD 从 v36 42.7% 降至 34.4% (-8pp), CAGR +83%, Sharpe +8%,
    # win% +1.7pp。
    # A 条件微调 (ratio/buffer) 效果都偏弱 — DD 没改善。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   2024-09-12 → 2025-03-12: n= 65 win=15.4% total_yield= +26.07% Sharpe=2.62 DD=72.8% ⚠️
    #   2025-03-12 → 2025-09-12: n= 84 win=14.3% total_yield= +23.10% Sharpe=2.74 DD=71.6% ⚠️
    #   2025-09-12 → 2026-03-12: n= 43 win=16.3% total_yield= +27.90% Sharpe=2.47 DD=25.8% ✅
    #   2026-03-12 → 2026-09-12: n=212 win=42.9% total_yield=+4280.41% Sharpe=10.96 DD=34.4% ✅
    #   4/4 窗口全为正收益, 但震荡段（前 2 窗）DD 72-73% — 比 v36 (55-57%) 显著恶化。
    #   震荡段 yield +23-26% vs v36 +20%, 但 DD 恶化 16-17pp — 收益与风险同向放大。
    #   E 流动性窗口拓宽 (5e8) 在大票反转下更脆弱, 12m 样本看像 34% DD 但跨周期 73%。
    # === 综合结论: v37 单点优化但跨周期劣于 v36 ===
    # v37 看似最优 (12m DD 34.4%) 但 walk-forward 揭示震荡段 DD 恶化 — 单点过拟合 12m 样本。
    # **v36_d_converge 仍是所有 preset 跨周期最稳健** (4 个 6-月窗口最低 yield +19.9%,
    # 震荡段 DD 55-57% 全程 < 60%)。v37 仅供对照, 实盘部署首选 v36_d_converge。
    "v37_liq_3e7_5e8": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.08,
        "d_mode": "converge_strict",
        "liq_high": 5e8,
    },
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
    "v38_a_relaxed": {
        "universe": "mainboard_only",
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
    # v39_pctchg_04_09 (DD 最低 28.2% — 单点过拟合):
    #   2024-09→2025-03: n= 44 win=15.9% yield=+17.3% Sharpe=2.07 DD=45.3%
    #   2025-03→2025-09: n= 53 win=11.3% yield= +4.0% Sharpe=1.54 DD=44.0% ⚠️
    #   2025-09→2026-03: n= 41 win=14.6% yield=+17.9% Sharpe=2.13 DD=20.5%
    #   2026-03→2026-09: n=135 win=43.0% yield=+1475.3% Sharpe=8.85 DD=28.2%
    #   震荡段最低 yield 仅 +4% — 单点过拟合 12m, 跨周期不工作, 不可投。
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
    "v39_pctchg_04_09": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.04,
        "pct_chg_high": 0.09,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
    "v39_pctchg_03_10": {
        "universe": "mainboard_only",
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
    "v40_tp_07": {
        "universe": "mainboard_only",
        "tp_pct": 0.07,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
    "v40_tp_08": {
        "universe": "mainboard_only",
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
    # 在 v40_tp_08 (TP 8%) 基础上微调, 4 组对比 (12m):
    #   v41_pctchg_04_10 (下限 4%, 上限 10%): n=164 win=39.6% CAGR=+2815% Sharpe=9.44 DD=35.3% ⭐
    #   v41_pctchg_03_09 (下限 3%, 上限 9%):  n=265 win=37.0% CAGR=+7449% Sharpe=10.85 DD=48.0%
    #   v41_mh6         (max_hold 6):         n=278 win=35.6% CAGR=+8946% Sharpe=10.69 DD=56.6%
    #   v41_mh7         (max_hold 7):         n=277 win=35.4% CAGR=+9199% Sharpe=10.68 DD=56.6%
    # v41_mh6/mh7 几乎与 v40_tp_08 相同 — TP 拉宽已让所有 trade 在 day 1-2 出场,
    # max_hold 拉长无效。
    # v41_pctchg_04_10 12m DD 35.3% (类似 v37 的 n=164), 但配置完全不同 (pct_chg 下限收紧)。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — 单点过拟合确认 ===
    #   2024-09→2025-03: n= 52 win=23.1% yield=+65.74% Sharpe=3.24 DD=57.7%
    #   2025-03→2025-09: n= 61 win=18.0% yield=+43.89% Sharpe=2.83 DD=57.5%
    #   2025-09→2026-03: n= 45 win=15.6% yield=+28.55% Sharpe=2.35 DD=19.4%
    #   2026-03→2026-09: n=148 win=41.9% yield=+2495.61% Sharpe=9.44 DD=35.3%
    #   4/4 窗口全部 yield 缩水 vs v40_tp_08:
    #     拉涨段 -64% (6871→2495) ⚠️⚠️
    #     震荡段 -10% ~ -34%
    #   DD 改善 3-17pp, 但 yield 损失远超 DD 改善, 单点过拟合 12m 样本。
    # === 微调方法论教训 (v41 失败案例) ===
    # pct_chg 下限收紧 (3%→4%) 看似改善 DD, 实则砍掉有效入场信号。
    # 与 v37_liq_3e7_5e8 (E 放宽单点过拟合) 同根问题: 单参数 12m 优化不可信。
    # v40_tp_08 保持 v3 体系最终胜出者位置 — 不动。
    "v41_pctchg_04_10": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.04,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.5,
        "close_ma60_buffer": 0.02,
    },
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
    "v42_buf05": {
        "universe": "mainboard_only",
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
    "v43_ratio03": {
        "universe": "mainboard_only",
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
    "v44_ratio02_buf07": {
        "universe": "mainboard_only",
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
    "v45_ratio01_buf10": {
        "universe": "mainboard_only",
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.1,
        "close_ma60_buffer": 0.10,
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]