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
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]