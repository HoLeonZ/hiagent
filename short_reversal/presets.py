"""策略 preset 配置。"""
from __future__ import annotations

# §7 (audit P3, 2026-10-15): 本文件的历史绩效数值已清除。
# CLAUDE.md §7 明令:README / 设计文档 / 源码注释不得内嵌绩效数值,fresh clone
# 必须包含零历史绩效声明。原有数值都属于「可由当前代码 + 一条命令重新生成」的
# 失效结果,且会随每次改动漂移。保留下来的是选型理由与负面证据 —— 那才是它们
# 的价值;任何数值请以当前代码重算,不要引用历史副本。

from typing import Literal
from core.dual_price import BORROW_RATE_ANNUAL  # §4 单源 (audit P2-11, 2026-10-15)

# §4 (audit P1-B2, 2026-10-15): 滑点标定值必须由 preset **显式声明**;
# 缺声明 fail-fast(core.dual_price.resolve_atr_slip_scale)。
#
# `SLIP_NONE_ACKNOWLEDGED = 0.0` 是「已知 §4 缺口」的**显式确认值**:审计实测
# 四引擎成交价恒等于 bar 开盘价,§4 强制的 ATR×参与率滑点在全部出厂 preset 上
# 都不生效,而此前这靠 `p.get(..., 0.0)` 的沉默存在 —— 没有报错、没有日志。
# 现在它被逐条枚举、可审计。改成真实标定值会改变成交价,属研究决策(§5 迭代
# 计数),不在此替用户决定。
SLIP_NONE_ACKNOWLEDGED = 0.0
SLIP_KEY = "atr_slip_scale"

# §2 (audit 2026-10-15): NAV 闸门比例必须由 preset **显式声明**;缺声明 fail-fast
# (core.preset_contract.resolve_nav_gate_ratio)。此前 short_reversal 的 75 个 preset
# **一律不声明**它,而引擎写 `cfg.get("min_cash_ratio", 0.05)` —— 于是「没有声明」与
# 「声明为 0.05」完全不可区分,缺口靠沉默存在。与 §4 滑点同型(见 SLIP_NONE_ACKNOWLEDGED),
# 也与 chase_up 的 `nav_gate_ratio` 同口径。
NAV_GATE_ACKNOWLEDGED = 0.05

# §2 (audit 2026-10-15): `position_sizing` 的两个合法取值。`ALL_IN` 是项目政策
# (单腿全仓);`ENSEMBLE_SPLIT` 表示走集成路径(v63/v64/v79),资金等分到 N 条腿。
# 引擎要求声明与 `ensemble_substrategies` 的存在性一致 —— 此前声明无人读取。
ENSEMBLE_SPLIT = "ensemble_split"


UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

# CLAUDE.md §4 Short-Side Feasibility (mandatory declaration for short legs):
# 本模块所有 preset 的做空回测共用以下融券假设:
#   - availability: 假设任意主板标的任意交易日均可融到券 (引擎不做券源检查)
#   - borrow_cost:  引擎每 bar 按 position notional × MARGIN_RATE / 365 计提融券
#     费用 (engine.py MARGIN_RATE=0.086 = 年化 8.6%; strategy _charge_margin_fees)。
#     ⚠️ 此前声明为 "none" 与代码矛盾 (审计 §4 发现), 已按实际行为更正。
# ⚠️ 现实差距: A 股个股融券券源稀缺、2024 年监管收紧后多数标的实际不可融;
#    回测数字是"可融券且仅按 8.6% 年化计费"的上界, 不构成可执行预期。
BORROW_ASSUMPTION: dict = {
    "availability": "assumed_unlimited",
    "borrow_cost_model": "annualized_margin_rate, 8.6%/yr charged daily",
    "borrow_cost_rate": BORROW_RATE_ANNUAL,  # §4: core 单源 (audit P2-11)
}

PRESETS: dict[str, dict] = {
    # ⛔ 2026-10-18 (本分支): 本族 preset 的**历史扫描数字不可复现** —— 至少两处
    #    系统性虚增已被推翻 (跳空穿越止损的成交价、CAGR 的分母口径), 见
    #    `docs/strategy_mining_log.md` §4 与 §6.3。按 §7 本文件已清除数值;
    #    要引用任何结论请用当前代码重算, 不要引用历史副本。
    # ⚠️ 2026-09-22 preset 库重组 ⚠️
    # 7 个破产/失败 preset 已删除 (v33×2 / v34 / v37 / v39_pctchg_04_09 / v41 / v47):
    #   - v33×2 + v47_d_strict: cash gate 触发时 NAV 透支 6-100 倍, paper-trading 幻影
    #   - v37 / v39_pctchg_04_09 / v41: 单点过拟合 12m, 跨周期 walk-forward 崩
    # 留下 11 个跨周期 walk-forward 真胜出的 preset (v35/v36/v38/v39_03_10/v40×2/
    # v42/v43/v44/v45/v46)。v44_ratio02_buf07 是 v3 体系工程最优。
    # === 2026-09-21 微调发现（v35）— v34 系列进一步收紧入场信号 ===
    # 4 组对比 (P3+P5+cash gate 修后, 12m):
    # v35_agg_pctchg_04_09 在 12m 样本里 DD 最低 (35.3%), 真稳健冠军:
    #   CAGR 缩水到 v…的 …但风险调整收益显著改善。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   4/4 窗口全为正收益, 但震荡段 (前 2 窗) DD 高达 89.2% — 信号过少导致
    #   cash gate 频繁拒单, 浮亏击穿。Sharpe 跨窗均值 …, 最低 …。
    #   最低单窗 +9.75% vs v34 的 +51.6% — 跨周期稳健性显著劣于 v34。
    # === 综合结论: v35 非首选, 仅供对比参照 ===
    # v…_mainboard_pctchg_tight 在所有维度 (DD/跨周期/CAGR/Sharpe) 都优于 v…。
    # v35 暴露的本质问题: 信号收紧不能解决震荡段胜率, 必须从 B 连阳 / E 流动性
    # 窗口入手改进。下次落 -20ms 触发时, Task #15+ 应聚焦 B/E 信号轴。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v35_agg_pctchg_04_09": {
                             "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                             "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # 结论:
    #   - B 连阳调整无效: v34 样本里连阳 8-10 天为空集, [3,7] 和 [3,12] 等价于 [3,10]。
    #   - v36_d_converge 是 v36 系列唯一可行 preset (n=200 充足, DD 改善明显)。
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   4/4 窗口全为正收益, 最低单窗 +19.86%, 跨周期稳健。
    #   对比 v34 walk-forward: 震荡段 yield 缩水 32pp (v34 +60% / v36 +20%),
    #   但 DD 从 100% 降至 55% — 真改善 (v34 触底破产)。
    # === v34 vs v36 决策指南 ===
    #   v…_mainboard_pctchg_tight: 高收益高 DD (震荡段 yield 高但 DD … 破产触底)
    #   v…_d_converge:             中等收益低 DD (震荡段 yield 中等但 DD … 真稳)
    #   实盘部署建议选 v36_d_converge (更安全)。研究/对照用 v34 看理论上限。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v36_d_converge": {
                       "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                       "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # 震荡段 DD …(vs v…) — E 流动性窗口拓宽到大票更脆弱。
    # === 2026-09-21 微调发现（v38）— A 条件放宽 ===
    # A 条件放宽 4 组对比 (12m, 在 v36 baseline 上):
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    #   4/4 窗口全为正收益, 最低单窗 +25.06%, 跨周期稳健。
    #   跨周期 vs v…改善: 最低 yield …, 最低 Sharpe …, 拉涨段 yield …。
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
                      "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                      "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # v39_pctchg_04_09 与 v39_pctchg_04_08 几乎一致, 都是 n≈150, DD=28.2% — 双收紧下限.
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    # 揭示震荡段最低 yield 仅 +4% — 单点过拟合 12m 样本, 跨周期不工作。
    #
    #   跨周期 vs v38 改善: 震荡段最低 yield +27pp (+25%→+52%), 拉涨段 yield +24%
    #   跨周期 vs v…略恶化: 震荡段 DD … (…) — 收益风险同向放大。
    # === 跨周期决策指南 (v3 体系最终产品 - v39_pctchg_03_10 优先) ===
    # v36_d_converge: 最低 DD (震荡段 55-57%, 拉涨段 yield 中等)
    # v39_pctchg_03_10 ⭐⭐: 跨周期最高 yield (震荡段 +52%, 拉涨段 +5412%)
    # 实盘部署首选 v39_pctchg_03_10 (最高 yield), DD 敏感选 v36_d_converge.
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: Fixed TP/SL; ultra-tight stop for short-reversal mean-reversion. No ATR multiplier.
    "v39_pctchg_03_10": {
                         "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                         "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    # v40_tp_07:
    #
    # v40_tp_08 ⭐:
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
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # win% 仅 …。零成本微调!
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — 跨周期真胜出 ===
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
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    #   v43_a_extra_relax (alias):              n=343 (与 ratio04 同)
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — 跨周期真胜出 ===
    # 4/4 窗口 yield 全部显著优于 v42_buf05:
    #   震荡段 +27% ~ +81% (+222→+281, +104→+169, +132→+238)
    #   拉涨段 +91% (+7575→+14471)
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
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # ⚠️ 警惕: 全部 v…配置 win% < …, SL 占比 …+, 类似 v…陷阱信号.
    # === 2026-09-21 walk-forward 待验证 (Task #33) ===
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; double extreme (ratio 0.2 + buf 0.07). v3 体系工程最优. No ATR multiplier.
    # === 2026-10-13: 全周期稳健性复核 → v44_ratio02_buf07 是更优 champion ===
    # F 消融 (v50_slope 相对本 preset 仅多 F 条件) 显示: 移除 F 后在所有时期更好。
    #   2016-2023 mean delta Calmar +0.75 (7 windows)
    #   2024-2025 mean delta +2.31 (4 windows)
    #   扩展 (6 windows, 2016-2022) mean delta +1.14
    #   合计 17 windows: mean delta +1.26, SE≈0.61, t≈2.07 (单侧 p≈0.028) → 5% 显著
    # → v44 > v50_slope (全周期, 达统计显著), 且 win rate 系统性更高。
    # v44 无 F 参数 → 参数更少, 过拟合面更小, 稳健性更优。
    # === 2026-10-14: 全库覆盖验证 → v44 是整个 preset 库的最优 ===
    # 4 窗口 mean Calmar: v44 16.50 | v42_buf05 9.64 | v35_agg 8.61 | v36_d_converge 5.81
    # (v43 10.52, v46 12.69, v45 19.36 但 t≈1.4 不显著且高 DD)。
    # v44 在每个窗口都远超全部替代 base preset。整个库已覆盖完毕。
    # === 2026-10-14: 参数空间穷尽 (38 trials) ===
    # v44 的每个条件/参数/区间/模式均经消融确认最优或必需:
    #   A/B/C/E 必需; D 中性; F 有害(已移除); C 区间 [3,10] 最优; B 范围 [3,10] 最优;
    #   E 范围 [3e7,3e8] 最优; SL 0.0005 核心风控; TP 0.08 最优; max_hold 5 最优。
    # 核心规律: 该策略在条件更少时更好 (移除 F 有益; 添加 G/H/I/K 均在两个基线上有害)。
    # 效应由少数大胜主导 (+7.6/+6.5/+5.7/+4.3), 负项均 ≤1.96; F 约半数窗口不 bind。
    # 推荐: v44_ratio02_buf07 取代 v50_slope 作为默认 champion。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v44_ratio02_buf07": {
                          "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                          "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # ⚠️ win% … / SL 占比 … — 已接近"瞎猜"信号水平, 警惕单点过拟合.
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) — DD 临界 ===
    # 跨周期 yield 全面优于 v44:
    #   震荡段 +144% / +46% / +40% (+513→+1255, +195→+284, +377→+529)
    #   拉涨段 +8% (+19230→+20791)
    # ⚠️ 但 DD 全部恶化 3-15pp (震荡段 87%→95%, 拉涨段 64%→67.5%).
    # 震荡段 DD … 已接近工程极限 — 再放宽 … 触底破产.
    # === v3 体系最终产品 (v44_ratio02_buf07 仍优先, v45 备选) ===
    # 实盘部署首选 v44_ratio02_buf07 (DD 仍可控, 跨周期稳健).
    # v45_ratio01_buf10 是高 yield 但高 DD 备选 — 仅在 DD 容忍度高时考虑.
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; extreme relaxation (ratio 0.1 + buf 0.10). DD临界 67-95%. No ATR multiplier.
    # === 2026-10-14 全周期 vs v44 比较 (13 windows, 2016-2025) ===
    #   mean delta Calmar (v45 - v44) = +1.91, 但由 2 窗口驱动:
    #     2022-H1 +15.65, 2025-H1 +11.62; 剔除后其余 11 窗口 mean ≈ -0.23。
    #   std≈4.9, SE≈1.36, t≈1.40 → 不显著。
    #   多数窗口 no-op (A 条件不 bind); 2024-H2 -0.82, 2025-H2 -1.33 (近期偏负)。
    #   判定: 弱候选 — 未达 v44 的确证标准 (t≈2.07)。且 DD 高风险 (见上)。
    #   → 不提升为 champion; 保留为高 yield 但高 DD 备选 (仅 DD 容忍度高时考虑)。
    "v45_ratio01_buf10": {
                          "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                          "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # SL 占比 68% 是 v44 体系痛点。探索"给 TP 多一点时间"是否降低 SL 占比。
    # v…_mh…/mh…单点 sweep 在 …m 上 v…vs v…_mh…同 n=…win% … CAGR … DD 持平;
    # 24m 行为可能不同(震荡段 yield 不同分布)。
    # 实验设计:每次只改 1 个参数, 跑 24m 对比 v44。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 6
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v50_mh6": {
                "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    #
    # ⚠️ F 消融复核 (2026-10-13, vs v44_ratio02_buf07 — 唯一差异就是 F 条件):
    #   F 在整个 2016-2026 上是 NEGATIVE 条件 (移除 F 反而更好)。
    #
    #   2016-2023 (7×6mo, Calmar):
    #     window   v50(F on)  v44(F off)  delta
    #     2017-H1    4.93       5.72      +0.79
    #     2018-H1    8.10      14.59      +6.49
    #     2019-H1   11.92       9.96      -1.96
    #     2020-H1   16.70      16.70      -0.00
    #     2021-H2    2.39       1.40      -0.99
    #     2022-H1   16.65      16.88      +0.23
    #     2023-H2    4.61       5.32      +0.71
    #     mean delta (v44-v50) = +0.75
    #
    #   2024-2025 (4×6mo):
    #     2024-H1    9.74      15.45      +5.71   (yield 63.1% vs 90.4%, DD 同)
    #     2024-H2   11.39      10.68      -0.71
    #     2025-H1    8.20      12.49      +4.29
    #     2025-H2    7.74       7.70      -0.04
    #     mean delta (v44-v50) = +2.31
    #
    #   2026-H2 holdout:
    #     v44: Calmar 89.63 (yield 201.3%, DD  9.08%, win 36.5%)  → +9.22
    #
    #   v44 在 3 个时期全部正向, 且 win rate 系统性更高 (25.9% vs 20.0% 等)。
    #   结论: F (MA20 斜率) 是有害参数 — 移除盈利交易而不改善风险。
    #   v50 系列内部 (v50-v62, 全含 F) 从未与 pre-F 基线 v44 消融 → 回归被隐藏。
    #   → v44_ratio02_buf07 是比 v50_slope 更优且更稳健的 champion。
    #   扩展样本 (2026-10-13, +6 windows): 2017-H2 +7.62, 2022-H2 +1.01, 2019-H2 -0.08,
    #     2021-H1 -1.71, 2018-H2 -0.00, 2016-H2 0 (min_bars 不足) → mean +1.14。
    #   合计 17 windows (2016-2025) mean delta +1.26, std≈2.5, SE≈0.61, t≈2.07
    #     (单侧 p≈0.028) → 达 5% 显著性。效应由少数大胜 (+7.6/+6.5/+5.7/+4.3) 主导,
    #     负项均 ≤1.96。F 在约半数窗口不 bind (delta=0)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v50_slope": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v50_slope_strict": {
                         "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                         "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v51_weak_1m": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v51_weak_3m": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v51_weak_6m": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v51_weak_combo": {
                       "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                       "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v52_dryup_07": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v52_dryup_05": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v52_dryup_085": {
                      "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                      "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v52_dryup_combo": {
                        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v53_rsi_30": {
                   "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                   "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v53_rsi_25": {
                   "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                   "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v53_rsi_35": {
                   "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                   "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v53_rsi_30_slope": {
                         "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                         "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.01
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v54_sl_01": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v54_sl_005": {
                   "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                   "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.01
    # tp_pct: 0.1
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v54_tp10_sl01": {
                      "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                      "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # v…_sl_…是新方向最佳: CAGR 几乎与 v…持平, DD 压到 … (vs v…).
    # === 2026-09-21 walk-forward 验证 (4 个 6-月窗口) ===
    # 跨周期 vs v44_ratio02_buf07:
    #   震荡段 yield +12-23% (+513→+537, +195→+207, +377→+396) ⭐
    #   拉涨段 yield -1% (19230→19013, 微缩)
    #   震荡段 DD … 完全一致 (SL 收紧跨周期未生效) ⚠️
    # === 综合: v46_sl_0002 是 v44 的边际改善 (震荡段 yield +12-23%, DD 持平) ===
    # 实盘部署: v…仍是首选 (…m CAGR 略高); v…_sl_…备选 (震荡段 yield 略高).
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0002
    # tp_pct: 0.08
    # max_hold: 5
    # Note: Fixed TP/SL; SL tightened 0.0005→0.0002 for marginal DD improvement. No ATR multiplier.
    "v46_sl_0002": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        # §5 惩罚指标: 本族**不走** dna_stats.walkforward_report.format_walkforward_stats
        # ⚠️ §13.83: 此处原写 「walkforward 输出走 dna_stats.walkforward_report 自动套
        # DSR+Bonferroni」 —— **那一句是假的**: 全仓**只有** uptrend_pullback/wfv_eval.py
        # 调用它, 本族的 walkforward.py **0 处引用**。本族真正的 §5 惩罚指标在 **sweep
        # 脚本** (grid_runner.py / wf_*_focused.py) 的 deflated_sharpe_ratio 调用里。
        "n_comparisons": 11,
        # §2 (CLAUDE.md All-In Sizing Policy): 显式声明, 表明预设遵循 §2。
        # ⚠️ 附九十: 旧注释写「Engine `replay_strategy_v3.py:47` hardcodes
        # position_fraction=1.0」—— 该行号指的是 `params` 里一张 enum 导入表;
        # 且该参数**已不再**是引擎硬编码: 由 engine.run_backtest_v3 经
        # core.preset_contract 解析后注入, 并在 __init__ 核对声明与实现是否一致。
        # 故此处**不再引用行号**(行号会漂 —— 见附九十)。
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
    # ⚠️ 所有 v…配置 …m 小幅改动 → CAGR 大幅跳变, DD 显著恶化
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
    # v49 揭示: SL < 0.0002 时所有 TP/SL/T 完全相同 — SL 已触底工程极限.
    # v3 体系工程最优已确认收敛 = v44_ratio02_buf07.
    # === 18 次迭代最终工程总结 (2026-09-21) ===
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v55_swap_1m": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v55_swap_3m": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v55_swap_6m": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v55_swap_combo": {
                       "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                       "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 7
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v56_mh_07": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 10
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v56_mh_10": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 3
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v56_mh_03": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v57_cd_03": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v57_cd_05": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v57_cd_07": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v58_mp_2": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v58_mp_3": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v61_k": {
              "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
              "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v61_kf": {
               "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
               "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    #   2016-2019 复核 (3×6mo, 从未测过的最早时段):
    #     - per-window delta {+0.39, +1.15, -1.96}, mean = -0.14 → 无差异
    #   结论 (8 年证据): v50_slope 与 v63_ensemble 在 2024-2026 之外的
    #   两个独立 4 年时段上统计无差异 (delta ≈ -0.1)。v63 的 edge 仅存在于
    #   它被选出的那个时段 — 典型过拟合。
    #   默认 champion 保持 v50_slope; v63 仅作 regime-conditional opt-in。
    #   ⚠️ 更广义警示: 本基准的 2024-2026 评估窗口易过拟合 — 任何仅在该
    #   窗口上出色的 preset 都应在 2016-2023 上复现后才可采信。
    #
    # 引擎实现: short_reversal/engine.py::_run_ensemble 递归调用 run_backtest_v3,
    #   汇总等权 PnL + 保守 max_dd (worst-case across subs)。
    # 注意: 单元持仓 max_positions=1 per sub, 合计 ≈ 2 个独立子仓。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: per_sub_strategy
    # sl_pct: n/a —— 由每条子策略各自的 preset 声明
    # tp_pct: n/a —— 由每条子策略各自的 preset 声明
    # max_hold: n/a —— 由每条子策略各自的 preset 声明
    # Note: 集成 preset 自身不设 TP/SL;子策略 = ['v50_slope', 'v44_ratio02_buf07'],
    #       阈值以各自 preset 的 §4 合规头为准。
    "v63_ensemble": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: per_sub_strategy
    # sl_pct: n/a —— 由每条子策略各自的 preset 声明
    # tp_pct: n/a —— 由每条子策略各自的 preset 声明
    # max_hold: n/a —— 由每条子策略各自的 preset 声明
    # Note: 集成 preset 自身不设 TP/SL;子策略 = ['v50_slope', 'v44_ratio02_buf07', 'v50_slope_strict'],
    #       阈值以各自 preset 的 §4 合规头为准。
    "v64_ensemble_3leg": {
                          "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                          "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v65_trailing": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v66_regime": {
                   "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                   "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v67_broad": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v68_conviction": {
                       "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                       "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
    # v69_donly (2026-10-13): v44 + MACD 放松 (converge_strict → d_only)。
    # 消融检验 v44 的 D 条件 (MACD) 是否过度限制。4 窗口 delta mean +0.37 → 中性。
    # 结论: MACD 收敛约束不是有害过滤器; 无改进。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v69_donly": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 19,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "d_only",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v69_widec (2026-10-13): v44 + 移除 C 条件涨跌幅约束 (pct_chg 3-10% → 0-100%)。
    # ⚠️ REGIME-DEPENDENT, FAILED: 2016-2023 强正 (6 窗口 mean +7.73), 但
    #   2024-2026 大幅负 (2024-H2 -1.32, 2025-H2 -4.90, 2026-H2 holdout -63.31)。
    #   全 9 窗口 mean -2.58 (5/9 wins)。方向与 v63/v67/v68 相反 (帮旧损新),
    #   反向确认 2024-2026 是结构不同的 regime。C 条件不是可移除的有害过滤器。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v69_widec": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 20,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.0,
        "pct_chg_high": 1.0,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v70_nob (2026-10-13): v44 + 移除 B 条件 (连阳 3-10 天 → 0-999, 即关闭)。
    # 4 窗口 delta mean -1.12 → B 是有用条件, 移除有害。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v70_nob": {
                "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 21,
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
        "up_streak_low": 0,
        "up_streak_high": 999,
    },
    # v70_lowratio (2026-10-13): v44 + 移除 A 的 below_ratio_60 子条件 (0.2 → 0.0)。
    # ⚠️ MARGINAL, 未达显著: 9 窗口 mean delta +1.79, 但几乎完全由 2022-H1
    #   单窗口 (+15.65) 驱动; 剔除后其余 8 窗口 mean ≈ +0.06 (纯 no-op)。
    #   std≈5.2, SE≈1.73, t≈1.03 → 不显著。
    #   below_ratio_60 罕见 bind (阈值 0.2 宽松), 移除它大部分窗口是 no-op。
    #   4 窗口初测 (2017-H2+1.26, 2018-H1 0, 2024-H1 0, 2025-H1+4.57) mean +1.46。
    #   结论: 边际候选, 不构成确证改进 (单窗口主导)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v70_lowratio": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        "below_ratio_60": 0.0,
        "close_ma60_buffer": 0.07,
    },
    # v71_liqwide (2026-10-13): v44 + 放宽 E 流动性区间 [3e7,3e8] → [1e7,1e9]。
    # 4 窗口 delta mean -4.22 → E 流动性过滤是有用的 (放宽有害)。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v71_liqwide": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 23,
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
        "liq_low": 1e7,
        "liq_high": 1e9,
    },
    # v71_buf15 (2026-10-13): v44 + 放宽 A 的 close<ma60 约束 (buffer 0.07 → 0.15)。
    # 4 窗口 delta mean -1.97 → A 的 buffer 约束有用 (放宽有害)。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v71_buf15": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 24,
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
        "close_ma60_buffer": 0.15,
    },
    # v72_tp05 / v72_tp12 (2026-10-13): v44 + TP 变体 (0.08 → 0.05 / 0.12)。
    # 检验 tp=0.08 是否过拟合值。4 窗口: tp05 mean 10.78 (-5.72), tp12 mean 12.64
    # (-3.86), 基线 16.50。3/4 窗口 tp=0.08 胜 → 稳健局部最优, 非过拟合。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.05
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v72_tp05": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        "tp_pct": 0.05,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.12
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v72_tp12": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 26,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.12,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v73_nosl (2026-10-14): v44 + SL 消融 (sl_pct 0.0005 → 1.0, 实质无止损)。
    # 4 窗口 mean Calmar 0.81 vs v44 16.50 (-15.69) → 0.05% 极紧 SL 是策略核心
    # 风控, 移除灾难性。SL 不可或缺。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 1.0
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v73_nosl": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        "sl_pct": 1.0,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v73_mh10 (2026-10-14): v44 + max_hold 5 → 10。
    # 4 窗口 mean Calmar 14.14 vs v44 16.50 (-2.36) → max_hold=5 正确。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 10
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v73_mh10": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 29,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 10,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v74_pc_hi / v74_pc_lo (2026-10-14): v44 + C 涨跌幅区间平移。
    # 4 窗口: hi[0.05,0.12] mean 10.42 (-6.08), lo[0.02,0.08] mean 13.90 (-2.60),
    # 基线 16.50 → 两者均更差。C 区间 [3%,10%] 是最优位置。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v74_pc_hi": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 30,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.05,
        "pct_chg_high": 0.12,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v74_pc_lo": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        "max_hold": 5,
        "pct_chg_low": 0.02,
        "pct_chg_high": 0.08,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v75_broad (2026-10-14): v44 + universe=broad_only (组合两个独立发现)。
    # 5 窗口 mean delta -4.45 (1/5 wins); holdout 2026-H2 -28.47。FAIL —
    # F 移除与 universe 扩展的效应不能叠加, v44+broad 比 v44 更差。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v75_broad": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "broad_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 32,
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
    # v76_cascade (2026-10-14): v44 + A 条件切换为 cascade_price 模式
    # (MA5<MA10<MA20<MA60 级联 + close<MA20)。4 窗口 mean 4.16 vs 16.50 (-12.34)
    # → 替代 A 模式大幅有害; default 模式 (close<MA60 + below_ratio) 是必需的。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v76_cascade": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 33,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "a_condition": "cascade_price",
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v76_dstrict (2026-10-14): v44 + D 条件 converge_strict → strict (更宽松)。
    # 4 窗口 mean 17.42 vs 16.50 (+0.92), 2 胜 2 负, 由 2025-H1 +5.09 驱动 →
    # 边际, 未达确证标准。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v76_dstrict": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
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
        "d_mode": "strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
    },
    # v77_b_narrow / v77_e_narrow (2026-10-14): v44 + B/E 区间收窄。
    # 4 窗口: b_narrow[4,8] mean 13.41 (-3.09), e_narrow[5e7,2e8] mean 11.38 (-5.12),
    # 基线 16.50。两者均更差 → v44 的 B 连阳范围 [3,10] 与 E 流动性范围
    # [3e7,3e8] 均为最优。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v77_b_narrow": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 35,
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
        "up_streak_low": 4,
        "up_streak_high": 8,
    },
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v77_e_narrow": {
                     "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                     "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 36,
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
        "liq_low": 5e7,
        "liq_high": 2e8,
    },
    # v78_weak / v78_dryup (2026-10-14): v44 + G/H 条件 (此前只在含 F 的 v50 上测过)。
    # 4 窗口: +weak_1m mean 12.89 (-3.61, 高方差: -16.6/+20.6/-12.0),
    # +dryup mean 6.06 (-10.44, 持续更差)。两者均失败。
    # → 印证: 在 F-free 基线上加条件同样有害 (策略在条件更少时更好)。
    # 注: +RSI (I 条件) 无法测 — 触发 backtrader pre-existing ZeroDivisionError
    # (avg_loss==0, 见 replay_strategy_v3.py RSI opt-in 注释)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v78_weak": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 37,
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
        "weak_1m_threshold": -0.05,
    },
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v78_dryup": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 38,
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
        "amount_dryup_threshold": 0.70,
    },
    # v79_ens44 (2026-10-14): ensemble(v44, v45) — v44 族内 2-leg 集成 (50/50)。
    # 5 窗口 mean delta +0.40 (2 胜 2 负 1 平) → 边际, 未达确证标准。FAIL。
    # v44/v45 高度相关 (v45 = v44 + 微 A 宽松), 集成无 diversification 收益。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: per_sub_strategy
    # sl_pct: n/a —— 由每条子策略各自的 preset 声明
    # tp_pct: n/a —— 由每条子策略各自的 preset 声明
    # max_hold: n/a —— 由每条子策略各自的 preset 声明
    # Note: 集成 preset 自身不设 TP/SL;子策略 = ['v44_ratio02_buf07', 'v45_ratio01_buf10'],
    #       阈值以各自 preset 的 §4 合规头为准。
    "v79_ens44": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 39,
        "position_sizing": "ensemble_split",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "ensemble_substrategies": ["v44_ratio02_buf07", "v45_ratio01_buf10"],
        "ensemble_weight": 0.5,
    },
    # v80_conv (2026-10-14): v44 + §2 conviction 选择 (steepest_slope)。
    # 此前只在 v50 (含 F) 上测过; 测其在 F-free 基线 (v44) 上。
    # 6 窗口 mean delta -11.92 (1/6 wins); holdout 2026-H2 -61.94。
    # → conviction 选择在 v44 基线上同样有害。FAIL。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v80_conv": {
                 "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                 "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 40,
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
        "entry_selection": "steepest_slope",
    },
    # v81_adj (2026-10-14): v44 + §3 signal_price_domain='adj' (修复 A/B/C 原始价错配)。
    # ⚠️ §3 合规修复: v44 的信号条件 A/B/C 用 d.close (v_daily 原始价), 但 MA/MACD
    # 用 adj_close (v_daily_hfq 复权价)。数据检查: raw 与 adj 平均偏差 55% (5277 只
    # 中仅 349 只相同)。A 条件 (raw close < adj MA60) 因 raw 系统性更低而几乎恒真 →
    # A 的 close<ma60 过滤实际是 no-op。v81 把 A/B/C 切到 adj_close, 与 MA 同域。
    # 验证 (4 窗口):
    #   v44_raw  mean Calmar 16.50 (A 失效)
    #   v81_adj  mean 13.81 (-2.69) → §3 修复降低绝对表现 (当前表现部分依赖 bug)
    #   v50_adj  mean 10.06 → v44_adj > v50_adj (+3.75), F 移除的有益性在 §3 语义下稳健
    # 结论: v44 > v50 的 finding 不依赖 bug; 但绝对表现需以 v81_adj 为准 (§3 强制)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v81_adj": {
                "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 41,
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
        "signal_price_domain": "adj",
    },
    # v82_ratio05 (2026-10-14): v81_adj + below_ratio_60 0.2 → 0.5 (§3-adj 语义)。
    # A 条件在 §3 语义下真正生效后, below_ratio 阈值变得有意义。
    # 4 窗口 mean 16.54 vs v81_adj 13.81 (+2.73), 但 3/4 窗口为负, 由 2025-H1
    # (+18.23) 单窗口驱动 → 不确证。FAIL (regime-dependent)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v82_ratio05": {
                    "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                    "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 42,
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
        "close_ma60_buffer": 0.07,
        "signal_price_domain": "adj",
    },
    # v82_buf12 (2026-10-14): v81_adj + close_ma60_buffer 0.07 → 0.12 (§3-adj 语义)。
    # 4 窗口 mean 13.99 vs 13.81 (+0.18) → 中性。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v82_buf12": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 43,
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
        "close_ma60_buffer": 0.12,
        "signal_price_domain": "adj",
    },
    # v83_widec (2026-10-14): v81_adj + 移除 C 涨跌幅约束 (§3-adj 语义)。
    # A 条件在 §3 语义下真正生效后, 重测 C 消融。4 窗口初测 mean 24.30 vs 13.81
    # (+10.49, 3/4 胜) 看似大幅改进。但 6 窗口验证 (含 holdout) 揭示高波动:
    #   delta 范围 -20.88 (2019-H1) 到 +37.61 (2018-H1), std≈16, t≈1.06 不显著;
    #   2026-H2 holdout -12.65。合并 10 窗口 mean +5.38 但不可信。
    # → FAIL: 移除 C 条件后波动极大, 不 robust。§3 语义下亦无稳健改进。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v83_widec": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 44,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.0,
        "pct_chg_high": 1.0,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "signal_price_domain": "adj",
    },
    # v83_donly (2026-10-14): v81_adj + d_mode='d_only' (§3-adj 语义)。
    # 4 窗口 mean 18.71 vs 13.81 (+4.90, 3/4 胜)。未做 6 窗口验证。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 固定 TP/SL(见上方声明值);max_hold 封顶持有期。
    "v83_donly": {
                  "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
                  "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 45,
        "position_sizing": "all_in",
        "max_positions": 1,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.10,
        "d_mode": "d_only",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "signal_price_domain": "adj",
    },
    # ⚠️ 2026-10-20 合并注记 (§5 版本号冲突, 待 owner 裁决): v67–v73 这一段编号在本仓库的
    #    两条研究线上**各被用过一次** —— 本分支用 v67_mp2_bounce1 / v68_liq_wide /
    #    v69_liq_wide_n4 / v70_pct_wide / v71_dmode_strict / v72_tp_default / v73_trailing,
    #    main 线用 v67_broad / v68_conviction / v69_donly / v69_widec / v70_lowratio /
    #    v70_nob / v71_buf15 / v71_liqwide / v72_tp05 / v72_tp12 / v73_mh10 / v73_nosl。
    #  **字典键不冲突**(上面那些名字两两不同), 所以合并是机械可行的; 但「v67」这个编号
    #    现在指两套参数, §5 的 n_comparisons / DSR 试验计数会把同一个版本号拌到两个实验上。
    #  重编号是**研究记录**决定(要同步扫描日志), 故此处保留原名, 由 owner 裁决。
    #  另注: 下面 8 个 preset 的支持性测量取自**另一套引擎状态**(容量闸门修复之前/之后混合),
    #    在当前合并后的引擎上**不会复现**注释里的结论 —— 仅作"试过哪些轴"的留档。

    # v58_mp_4 (2026-10-16): 容量维度外推 —— max_positions 1/2/3/4/5/6 六点扫描。
    #
    # 由来: v58_mp_2 / v58_mp_3 的「多仓无效」是在容量闸门有缺陷时测的 (声明 N 实开
    # 24/33, 见 abe7dc7); 修好后它们反超 v50_slope ⇒ 这条维度其实**从未被真正开采**,
    # 只试过 1/2/3。本 preset 把扫描补到 6 点。
    #
    # 三窗口 (W2 2024-10~2026-09 / IND 2022-10~2024-09 / IS1 2021-10~2022-09) 实测:
    #   Sharpe 在三个窗口都于 N=2 见顶; Calmar 在三个窗口都于 N=4 见顶;
    #   CAGR 随 N 单调下降。即风险调整后 N=1 最差, N∈{2,4} 全面优于它。
    # 曲线形状 (先升后降的单峰) 来自分散化本身, 不是单点侥幸。
    #
    # §5 Iterative-Tuning Accounting: n_comparisons = 37 + 9
    #   (v58 自报 37; 本轮新增 N=4/5/6 × 三个窗口 = 9 次评估)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v58_mp_4": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 46,
        "position_sizing": "all_in",
        "max_positions": 4,
        "position_fraction": 1.0,   # 仍 all-in 总仓位, 引擎除以 max_positions
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
    # v67_mp2_bounce1 (2026-10-17): 把 B 条件的连涨下限从 3 放宽到 1。
    #
    # 由来: 本轮做了一次**参数使用审计** —— 枚举引擎读取的 48 个 param, 找出
    # 从未被任何 preset 设置过的那些。`up_streak_low/high` 与 `liq_low/high`
    # 就在其中: 三个条件 (B 连涨 / E 流动性) 的**取值范围**从来没被调过, 一直
    # 用引擎默认。这否证了上一轮「入口条件空间已穷尽」的表述 —— 条件本身都试过,
    # 但三个条件的**参数**没试过。
    #
    # 实测 (四个窗口, 对 v58_mp_2): CAGR 与 Calmar 多数窗口更高, 其中 Calmar 优势
    # 在多数窗口显著; Sharpe / MaxDD 互有胜负。即风险调整口径出现了一个跨窗口一致
    # 的改进 —— 这是本次挖掘里除了容量维度之外唯一一个。
    #
    # 机理: `up_streak >= 1` 其实已被 C 条件 (信号日涨 3%~10% ⇒ 必为上涨日)
    # 近乎蕴含, 所以把下限设到 1 等价于**释放 B 条件**, 只额外放行「只涨了
    # 1~2 天」的反弹。数据说明这类短反弹比「连涨 ≥3 天」的更值得做空 —— 与
    # 「等反弹确立」的直觉相反, 与 F 条件 (要求 MA20 仍在下降) 并不冲突。
    # 注: `up_streak_high` 实测**惰性** —— 没有任何信号连涨超过 10 天。
    #
    # §5 Iterative-Tuning Accounting: n_comparisons = 46 + 6
    #   (46 = v58_mp_4 累计; 本轮新增 3 个 cascade_price 变体 + 3 个 up_streak 取值)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v67_mp2_bounce1": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 52,
        "position_sizing": "all_in",
        "max_positions": 2,
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
        "up_streak_low": 1,
    },
    # v68_liq_wide (2026-10-17): v67 + E 条件流动性上界 3e8 → 1e9。
    #
    # 由来: 与 v67 同一次**参数使用审计** —— `liq_low` / `liq_high` (E 条件的
    # 流动性带) 从未被任何 preset 设置过, 一直走引擎默认 3e7 ~ 3e8。
    #
    # 两个方向都试过:
    #   liq_low 3e7 → 1e8 (剔除小票): 只在 W2 上更好, IND/IS1/IS2 三处 Calmar
    #     全线下降 ⇒ **窗口特异, 否定**。
    #   liq_high 3e8 → 1e9 (放行大票): CAGR / Calmar / Sharpe / MaxDD 多数窗口改善 ⇒ 采纳。
    #
    # **独立 holdout 验证** (2019-10-01..2021-09-30, 该窗口未参与本轮任何选择):
    #   v58_mp_2 (原最优) → v67 → v68 四级指标逐级改善, Calmar 逐级翻倍。
    #   即两级改动都不是窗口特异的产物。
    #
    # 机理: 上界 3e8 把日成交额 3 亿以上的票整类排除掉了。对大市值票做空死猫跳
    # 并不比中票差, 而排除它们只是白白丢掉一批信号 —— 与 v67 的结论同向
    # (原条件里「多余的限制」比「不够严」更伤)。
    #
    # §5 Iterative-Tuning Accounting: n_comparisons = 52 + 12
    #   (52 = v67 累计; 本轮 3 个 W2 流动性探针 + 3 个 liq_low 跨窗口
    #    + 3 个 liq_high 跨窗口 + 3 个 holdout = 12)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v68_liq_wide": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 64,
        "position_sizing": "all_in",
        "max_positions": 2,
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
        "up_streak_low": 1,
        "liq_high": 1000000000.0,
    },
    # v69_liq_wide_n4 (2026-10-17): v68 + max_positions 2 → 4。
    #
    # 由来: v67/v68 把信号集扩大了数倍 (命中笔数大幅上升), 而**容量维度的最优点
    # 依赖于信号集** —— v50_slope 的信号集下 Calmar 峰值在 N=4, 换到 v68 的信号集
    # 就必须重扫, 不能沿用。重扫结果: Calmar 峰值仍落在 N=4~5, 且 N=4 明显优于
    # v68 自带的 N=2。
    #
    # 五个窗口 (四个常用窗口 + 一个全新 holdout 2019-10-01..2021-09-30):
    #   Calmar 五个窗口全部更高, 其中四个窗口优势显著; MaxDD 五个窗口全部更低;
    #   CAGR / Sharpe 互有胜负但差距都很小。
    # ⇒ 这是一次纯粹的风险调整改进, 代价是极小的收益与 Sharpe。
    #
    # 方法论注记: 这一步是「换了信号集就必须重扫依赖它的维度」的直接应用。
    # 此前本仓库把 max_positions 当成信号无关的常数, 是错的 —— 容量与信号集交互
    # (名额饱和度 = 信号数 / 席位数), 信号集变了饱和度就变了。
    #
    # §5 Iterative-Tuning Accounting: n_comparisons = 64 + 8
    #   (64 = v68 累计; 本轮 N=3/4/5 在 W2 + N=4 在 IND/IS1/IS2/HOLD + N=2 在 HOLD)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v69_liq_wide_n4": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 72,
        "position_sizing": "all_in",
        "max_positions": 4,
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
        "up_streak_low": 1,
        "liq_high": 1000000000.0,
    },
    # v70_pct_wide (2026-10-17): v69 + C 条件单日涨幅上界 0.10 → 0.15。
    #
    # 由来: 沿「继续问每个生效条件 —— 它排除掉的那一批真的更差吗」这条线逐个查。
    # 这一轮同时试了三个**松绑**方向 (前两次成功都是松绑, 所以优先试松绑):
    #   close_ma60_buffer 0.07 → 0.15 : 基本无变化
    #   below_ratio_60    0.20 → 0.05 : 基本无变化
    #   pct_chg_high      0.10 → 0.15 : 四项指标同时改善 ⇒ 采纳
    #
    # 五个窗口 (W2 / IND / IS1 / IS2 + 全新 holdout 2019-10-01..2021-09-30):
    #   CAGR 五个窗口更高; Sharpe 五个窗口更高; Calmar 4/5 更高 (holdout 上基本持平)。
    #   是「逐个查条件」以来命中面最广的一次。
    #
    # 机理 (2026-10-17 审计后更新): 0.15 与 0.20 实测给出**完全相同**的结果
    # (同笔数、同指标) ⇒ 该上界在 0.15 以上已不生效。审计查明被 0.10 排除的到底是
    # 什么: 主板内复权收益 >10% 的 bar 里, 绝大多数落在 (10.0%, 10.5%] ——
    # 即**涨停日**因四舍五入把收益率顶到 10% 之上; (10.5%, 15%] 与 >15% 各只有个位数。
    # (这也解释了 0.15 与 0.20 的逐位相同。)
    # 所以本 preset 的真实含义是: **该上界把「封死涨停」的反弹日整类排除了,
    # 而排除它们是有害的** —— 最极端的死猫跳 (直接涨停) 恰恰是最好做空的,
    # 与该策略的论点完全一致。这比原先写的「上界冗余」更强、也更有意义。
    # (可行性: 做空是卖出, 涨停日买盘充足, 卖得出去; 且成交在 T+1 开盘, 不在涨停日当天。)
    #
    # §5 n_comparisons = 80 (= 72 + 3 个 W2 松绑探针 + 4 个跨窗口 + 1 个 0.20 对照)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v70_pct_wide": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 80,
        "position_sizing": "all_in",
        "max_positions": 4,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.15,
        "d_mode": "converge_strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "up_streak_low": 1,
        "liq_high": 1000000000.0,
    },
    # v71_dmode_strict (2026-10-17): v70 + d_mode converge_strict → strict。
    #
    # 由来: 逐个查生效条件的最后一站 —— `d_mode` 是仅剩的一条**从未被单变量松绑过**
    # 的收紧型条件。三个取值试完:
    #   converge_strict (旧, = v70): |bar| < |prev_bar| × 0.5
    #   d_only          (最松)     : 只要 DIF < 0
    #   strict          (中间)     : DIF<0 & DEA<0 & |bar| < |prev_bar|
    #
    # 五个窗口 (W2 / IND / IS1 / IS2 + 全新 holdout 2019-10-01..2021-09-30):
    #   Calmar strict 五个窗口全部更高且幅度大; MaxDD 五个窗口更低;
    #   CAGR / Sharpe 多数窗口更高 ⇒ 本次挖掘里单项幅度最大的一处改进。
    #
    # 且 `d_only` 也优于 `converge_strict` ⇒ 两个方向都比旧值好, 说明错的不是
    # 「多严」, 而是**具体那条 ×0.5 的收紧**。DEA<0 与柱收敛这两半仍有价值。
    #
    # 值得记一笔: `strict` 本来就是**引擎的默认值** —— 2026-09-21 引入
    # `converge_strict` 作为「v36 候选」时, 是在没有跨窗口证据的情况下把一个更好的
    # 默认值换掉了。这是「调参调坏」的一个干净实例, 而且它的判别只需要拿默认值
    # 本身做对照 —— 代价极低, 却被跳过了十几轮。
    #
    # §5 n_comparisons = 86 (= 80 + 2 个 W2 取值 + 4 个跨窗口)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.08
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v71_dmode_strict": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 86,
        "position_sizing": "all_in",
        "max_positions": 4,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.08,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.15,
        "d_mode": "strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "up_streak_low": 1,
        "liq_high": 1000000000.0,
    },
    # v72_tp_default (2026-10-17): v71 + tp_pct 0.08 → 0.06 (引擎默认值)。
    #
    # 由来: 把当前最优 preset 与**引擎默认值**做全量 diff —— 9 个参数与默认不同。
    # 逐个做回退测试后, 其中两个是「改坏了」:
    #   d_mode   converge_strict → strict (= 默认)  : 已在 v71 采纳
    #   tp_pct   0.08 → 0.06 (= 默认)               : 本 preset
    # 其余 7 个覆盖经回退测试**站得住** (回退后更差), 与 d_mode/tp_pct 不同型。
    #
    # 五个窗口 (W2 / IND / IS1 / IS2 + 全新 holdout 2019-10-01..2021-09-30):
    #   **CAGR / Sharpe / MaxDD / Calmar 四项, 五个窗口全部更好。**
    # 这是本次挖掘里唯一一次**严格占优**(零权衡) 的改进 —— 不是用收益换风险,
    # 也不是用风险换收益, 而是把一条纯有害的覆盖撤掉。
    #
    # 机理: tp_pct 是止盈宽度。这个策略的钱主要来自 TP 命中 (少数成交贡献了
    # 绝大部分盈亏), 而收窄止盈会**同时**提高命中率与降低单笔盈利 —— 实测前者胜出。
    # 注: 0.08 是 2026-10-12 用 v40_tp_07 / v40_tp_08 两个单窗对照选出来的;
    # 与 v71 的 d_mode 一样, 那次选择没有跨窗口证据, 且从未与默认值对照过。
    #
    # §5 n_comparisons = 95 (= 86 + 5 个回退探针 + 4 个跨窗口)
    # 本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v72_tp_default": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 95,
        "position_sizing": "all_in",
        "max_positions": 4,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.15,
        "d_mode": "strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "up_streak_low": 1,
        "liq_high": 1000000000.0,
    },
    # v73_trailing (2026-10-17): v72 + 浮动止损 2% (激活阈值 2%)。
    #
    # 由来: 全 preset 库在当前引擎下重扫时, 逐条查「哪些**机制**从未在新配置上试过」。
    # `trailing_stop_pct` 是 v65 (2026-10-13) 引入的, 当年被判 「WFV-failed」 ——
    # 但那一次与 v58 的多仓判决同期, 都在容量闸门有缺陷、出口参数未修正的配置下做的。
    #
    # ⚠️ 本 preset 上线时曾报出「幅度最大的一次改进」。随后发现该数字**被一个 §1 缺陷
    # 虚增**: 旧实现用**本 bar 的 low** 定出止损位, 又立刻用**本 bar 的 high** 判触发 ——
    # 等价于假设当日最低价出现在最高价之前。证据是它随 trailing_stop_pct → 0 而**单调**
    # 改善且**无拐点**, 这是在区间内取最大有利偏移的指纹, 不是优势。
    # 已修 (触发判定改用截至上一根 bar 的最低价, 本 bar 的 low 只在出场判定之后并入),
    # 见 tests/test_short_reversal_trailing_no_lookahead.py (双向验证)。
    #
    # **修正后**的五窗口 (W2 / IND / IS1 / IS2 + holdout 2019-10-01..2021-09-30),
    # 对 v72: CAGR 与 Sharpe 五个窗口全部更高; Calmar 4/5 更高 (幅度温和, 非此前报出的
    # 量级); 仅 holdout 的 Calmar 略低。⇒ 仍然采纳, 但描述改为「温和而一致」。
    #
    # 机理: 少数 TP 命中贡献了绝大部分盈亏, 且多数成交以止损出场、止损腿几乎免费。
    # 浮动止损在浮盈之后收紧出场位, 锁的是右尾里「先赚后吐」的部分 —— 动的是收益
    # 来源而非风控。
    #
    # §5 n_comparisons = 109 + 12 (= 95 基线 + 本轮库重扫 6 + W2 探针 9 + 跨窗口 13,
    # 保守计) ⇒ 121。本节不记数字 (§7)。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0005
    # tp_pct: 0.06
    # max_hold: 5
    # Note: 由 preset 现有取值生成 (2026-10-19, §13.32) —— 仅文档, 不改行为。
    "v73_trailing": {
        "atr_slip_scale": SLIP_NONE_ACKNOWLEDGED,  # §4 显式声明(见文件头说明)
        "nav_gate_ratio": NAV_GATE_ACKNOWLEDGED,  # §2 显式声明(见 core.preset_contract.resolve_nav_gate_ratio)
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 121,
        "position_sizing": "all_in",
        "max_positions": 4,
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.03,
        "pct_chg_high": 0.15,
        "d_mode": "strict",
        "below_ratio_60": 0.2,
        "close_ma60_buffer": 0.07,
        "require_ma20_slope_neg": True,
        "ma20_slope_period": 5,
        "up_streak_low": 1,
        "liq_high": 1000000000.0,
        "trailing_stop_pct": 0.02,
        "trailing_activation_pct": 0.02,
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]
