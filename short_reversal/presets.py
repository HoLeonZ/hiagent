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
    # D 条件改为 DIF/DEA<0 后的推荐 preset：
    # 2018-2025 实测 (Phase 1 trades 层, entry=T+1 open, TP/SL from T+2):
    #   n=455, 胜率 43.5%, avg_pnl +0.717%, 平均持仓 1.44 天 (≤ 3 月)
    #   8 年累计复利 +152% → CAGR ≈ +12.4%
    #   比 v33 原版 -8% CAGR 改善 +20 个百分点。
    # 注：Phase 2 backtrader 复盘层在 AShareBroker / TradeReplayStrategy
    # 上有独立的资金路径 bug（CAGR -1.87%），未计入此 CAGR。
    # 80% 目标不可达：D 修正后数学上限约 +15%，融券 + 印花税 +
    # 频繁 SL 的成本结构封顶了复利速率。
    "v33_mainboard_tp3_sl1_dneg": {
        "universe": "mainboard_only",
        "tp_pct": 0.03,
        "sl_pct": 0.01,
        "max_hold": 5,
    },
}


def get_preset(name: str) -> dict:
    """返回指定 preset 配置；未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    return PRESETS[name]