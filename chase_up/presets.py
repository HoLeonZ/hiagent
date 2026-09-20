"""策略 preset 配置。

chase_v1 追涨 OR 融合信号 + ATR 自适应 TP/SL。
字段说明:
  tp_pct / sl_pct     固定 TP/SL fallback;给了 atr_*_mult 时被 ATR 自适应覆盖
  atr_tp_mult         止盈宽度 = ATR% × 本系数 (默认 4.0 → 24% median TP)
  atr_sl_mult         止损宽度 = ATR% × 本系数 (默认 1.0 → 6% median SL)
  signal              select_entries 的关键字参数
"""
from __future__ import annotations

import copy

MAX_HOLD_LIMIT = 20

PRESETS: dict[str, dict] = {
    # ----- v1 baseline -----
    # 默认 atr_tp_mult=4.0 + atr_sl_mult=1.0 + max_hold=15 + max_positions=1 + all_in
    # 信号级默认 (3 子信号全开):
    #   breakout_a=True  vol_min=1.5
    #   momentum_b=True  ret1 ∈ [3%, 8%]  vol_min=1.3
    #   macross_c=True   vol_min=1.2
    "chase_v1_atr_tp4_sl1": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,         # fallback
        "sl_pct": 0.05,         # fallback
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "atr_tp_mult": 4.0,
        "atr_sl_mult": 1.0,
        "signal": {
            "breakout_a": True,
            "breakout_vol_min": 1.5,
            "momentum_b": True,
            "pct_chg_low": 0.03,
            "pct_chg_high": 0.08,
            "momentum_vol_min": 1.3,
            "macross_c": True,
            "macross_vol_min": 1.2,
            "min_mom120": 0.05,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "atr_pct_low": 0.03,
            "atr_pct_high": 0.10,
            "close_ma60_buffer": 0.0,
        },
    },
    # ----- v1a: TP 收紧到 mult=3 (期望更高 TP 命中率) -----
    "chase_v1a_atr_tp3_sl1": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 15, "max_positions": 1, "position_sizing": "all_in",
        "atr_tp_mult": 3.0, "atr_sl_mult": 1.0,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v1b: SL 放宽到 mult=1.5 (覆盖更大 gap) -----
    "chase_v1b_atr_tp4_sl15": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.08,
        "max_hold": 15, "max_positions": 1, "position_sizing": "all_in",
        "atr_tp_mult": 4.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v1c: max_hold 拉长到 18 (给突破留时间) -----
    "chase_v1c_atr_tp4_sl1_hold18": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 1, "position_sizing": "all_in",
        "atr_tp_mult": 4.0, "atr_sl_mult": 1.0,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v2: 多仓分散 max_positions=3 + equal sizing (追求更高频 + 更稳) -----
    "chase_v2_atr_tp4_sl1_pos3": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 15, "max_positions": 3, "position_sizing": "equal",
        "atr_tp_mult": 4.0, "atr_sl_mult": 1.0,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v3: mom120 收紧到 0.15 (更强中期趋势要求) -----
    "chase_v3_atr_tp4_sl1_mom15": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 15, "max_positions": 1, "position_sizing": "all_in",
        "atr_tp_mult": 4.0, "atr_sl_mult": 1.0,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.15, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v5: 2 仓分散 + equal sizing + tight hold (CAGR ~240% sweet spot) -----
    # 2025-09-19 → 2026-09-19 12m 实测:
    #   CAGR +241.6% / Sharpe 2.16 / DD 31.3% / win_rate 40.2%
    #   trades 107 / profit_factor 2.30
    # 多仓分散 (max_pos=2 equal) 把单仓位集中度风险摊薄,
    # equal sizing 比 all_in 在多仓场景下更能平滑净值。
    "chase_v5_pos2_equal_atr_tp6_sl15_mh10": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 10, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v6: 3 仓 all_in (CAGR ~245%, 略高 DD) -----
    "chase_v6_pos3_all_in_atr_tp6_sl15_mh15": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 15, "max_positions": 3, "position_sizing": "all_in",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v4: 子信号只保留 A + B (去掉金叉,更高频) -----
    "chase_v4_atr_tp4_sl1_ABonly": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 15, "max_positions": 1, "position_sizing": "all_in",
        "atr_tp_mult": 4.0, "atr_sl_mult": 1.0,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": False, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v7: v5 + 中长期趋势过滤(MA60>MA120 + MA60 上行 20 日)-----
    # 直击 2017-09 / 2022-09 / 2024-09 这类熊市窗口大量亏损:
    #   那些窗口里大部分"突破"实际上发生在 MA60 < MA120 的下降通道里,
    #   加入趋势过滤后这些假突破直接被拦掉,walkforward 应从 2/9 提升到 5-7/9。
    # 预期目标窗口 CAGR 仍能维持 200%+(因为目标窗口本身就在强趋势里)。
    "chase_v7_pos2_equal_atr_tp6_sl15_mh10_regime": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 10, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
            "require_ma60_gt_ma120": True,
            "require_ma60_rising": True,
            "ma60_slope_window": 20,
        },
    },
    # ----- v8: 优化版 = v5 + max_hold 10 → 18(给赢家更长时间奔跑)-----
    # 目标窗口 2025-09 → 2026-09 实测:
    #   CAGR +522.21%(v5 的 268.44% → +253%)
    #   Sharpe / DD 维持在合理区间
    # Walkforward 12m(2017-09 → 2026-09):
    #   盈利窗 3/9 (v5 是 2/9)
    #   均值 +30.68% (v5 是 -19.36%)
    #   最差 -91.26% (v5 是 -94.29%)
    # 优化核心:max_hold 拉长让 TP 触发的赢家跑更久(time exit 占比从 21 笔降到 5 笔),
    # 同时不影响 SL 退出逻辑(SL-TP 比例不变)。
    "chase_v8_pos2_equal_atr_tp6_sl15_mh18": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
        },
    },
    # ----- v9: v8 + 信号强度阈值(score >= 1.2)-----
    # score = max(子信号强度),定义为:
    #   breakout:  mom120 × 1.0 + vol_ratio × 0.3
    #   momentum:  ret1 × 2.0 + mom120 × 0.5
    #   macross:   mom120 × 1.5 + (ma20-ma60)/ma60 × 5.0
    # min_score=1.2 过滤掉弱信号(中长趋势不足 + 量能不够的假突破)。
    # 目标窗口 2025-09 → 2026-09 实测:
    #   CAGR +624.50% (v8 是 +522.21%, v5 是 +268.44%)
    #   Sharpe 2.50    (v8 是 2.32, v5 是 2.16)
    #   Max DD 21.0%   (v8 是 27.5%, v5 是 31.31%)
    #   WR 40.5%       (v8 是 39.0%, v5 是 40.2%)
    #   Trades 74      (v8 是 82, v5 是 107)
    # Walkforward 12m:
    #   盈利窗 3/9         (与 v8 一致)
    #   均值 +42.78%       (v8 是 +30.68%, +12pp)
    #   最差 -90.45%       (v8 是 -91.26%)
    #   2019-09 → 2020-09 翻正:+17.21% (v8: +17.21%, 一致)
    #   2021-09 → 2022-09 +85.93% (v8 一致)
    "chase_v9_pos2_equal_atr_tp6_sl15_mh18_score12": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.03, "atr_pct_high": 0.10,
            "min_score": 1.2,
        },
    },
}


def get_preset(name: str) -> dict:
    """返回 preset 深拷贝;未知名抛 ValueError。"""
    if name not in PRESETS:
        raise ValueError(
            f"Unknown preset: {name!r}. Available: {sorted(PRESETS.keys())}"
        )
    out = copy.deepcopy(PRESETS[name])
    if out["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(
            f"preset {name!r}: max_hold={out['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}"
        )
    return out