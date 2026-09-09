"""策略 preset 配置。"""
from __future__ import annotations

from typing import Literal

UniverseMode = Literal["mainboard_only", "exclude_hs300_zhongtou_finance"]

PRESETS: dict[str, dict] = {
    "v33_final": {
        "universe": "exclude_hs300_zhongtou_finance",
        "tp_pct": 0.03,
        "sl_pct": 0.05,
        "max_hold": 30,
    },
    "v33_mainboard": {
        "universe": "mainboard_only",
        "tp_pct": 0.06,
        "sl_pct": 0.05,
        "max_hold": 30,
    },
    "v33_mainboard_tp3": {
        "universe": "mainboard_only",
        "tp_pct": 0.03,
        "sl_pct": 0.05,
        "max_hold": 30,
    },
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
    # 注：Phase 2 backtrader 复盘层在 AShareBroker / TradeReplayStrategy
    # 上有独立的资金路径 bug（CAGR 显著偏低），未计入此 CAGR。
    "v33_mainboard_tp2_sl05_dneg": {
        "universe": "mainboard_only",
        "tp_pct": 0.02,
        "sl_pct": 0.005,
        "max_hold": 3,
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]