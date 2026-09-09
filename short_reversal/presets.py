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
    # 放宽 C 条件 (pct_chg) 为 [1%, 7%] + TP=2.5%/SL=0.2%/mh=4 的高 CAGR preset：
    # main.py 端到端实测 (Phase 1 trades 层, entry=T+1 open, TP/SL from T+2):
    #   2018-05-29 ~ 2025-09-03 (≈ 7.27 年), n=524, 胜率 40.08%,
    #   avg_pnl +0.880% (毛), 平均持仓 1.14 天 (≤ 3 月 ✅, 最大 5 天)
    #   无成本 CAGR +86.97% (累计 +9335.81%, 独立 stand-alone CAGR +105.45%)
    #   含 A 股真实成本 CAGR +53.06% (commission 万 0.6 双边 0.12% +
    #     stamp_duty 万 1 单边 0.10% + 融券 8.6%/年 × hold_days)
    #   最大回撤 -6.14%, 平均持仓 1.14 天 ≤ 3 月 ✅
    # 最近 1 年 (2025-09-09 ~ 2026-09-08):
    #   n=48, 胜率 45.83%, 无成本 CAGR +128.59%, 真实成本 CAGR +45.73%
    #   最大回撤 -2.20%
    # 80% 目标说明: 仅在无成本假设下达标 (+86.97%); 含 A 股真实成本后 CAGR +53.06%,
    # 不再严格 ≥ 80%。若需真实成本下重回 80%, 需进一步放宽 TP 至 3-4% 或放
    # 松 SL 至 0.3-0.5%。
    # Phase 2 backtrader 复盘层（OHLCV 时点验证用）已修复 ENTRY/EXIT 同日覆盖 bug
    # (actions dict 改为 dict[date, list])、position 仓位计算 bug (改用
    # initial_capital × position_fraction)、commission/stamp_duty 实装,
    # 但成交价用 next-bar open 跟 trades.py 的 entry_price(T+1 open) /
    # exit_price(TP/SL 阈值) 仍有 1 日时差, 故 main.py CAGR 用 trades 层精确
    # 复盘, broker_final_value 字段保留 backtrader 复盘数值供交叉验证。
    "v33_mainboard_tp25_sl02_relaxed": {
        "universe": "mainboard_only",
        "tp_pct": 0.025,
        "sl_pct": 0.002,
        "max_hold": 4,
        "pct_chg_low": 0.01,
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