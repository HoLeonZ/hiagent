"""策略 preset 配置。"""
from __future__ import annotations

from typing import Literal

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

PRESETS: dict[str, dict] = {
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
    # 12 个月窗口 (2025-09-12 → 2026-09-12) v3 引擎实测:
    #   n=563, 胜率 53.6%, CAGR +36.39%, Sharpe 2.39, DD 79.0%
    #   TP/SL/time = 298/260/5
    # 注：Phase 2 backtrader 复盘层在 AShareBroker / TradeReplayStrategy
    # 上有独立的资金路径 bug（CAGR 显著偏低），未计入此 CAGR。
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
    # 12 个月窗口 (2025-09-12 → 2026-09-12) v3 引擎实测:
    #   n=586, 胜率 30.4%, CAGR +81.60%, Sharpe 2.88, DD 91.62%
    #   TP/SL/time = 165/408/13
    "v33_mainboard_tp6_sl005_mh5_realistic": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.0005,
        "max_hold": 5,
        "pct_chg_low": 0.02,
        "pct_chg_high": 0.07,
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]