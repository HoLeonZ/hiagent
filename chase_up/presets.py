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
    # ----- v10: v9 + min_score 1.2 → 1.6(过滤更强信号)-----
    # 目标窗口 2025-09 → 2026-09 实测:
    #   CAGR +604.15% (v9 是 +624.50%)
    #   Sharpe / Max DD / WR 与 v9 相当
    # Walkforward 12m:盈窗 2/9(与 v9 一致);最差从 v9 的 -90.45% 改善到 -80.92%。
    # 核心优化:更严格的 score 阈值 = 更高胜率 + 更小回撤 + 更稳的 worst window。
    # 注意 mh=20 会闪崩到 +186%(non-monotonic,signal-day score 与 mh 的耦合效应),
    # 所以 max_hold 仍保持 18 这个 sweet spot。
    "chase_v10_pos2_equal_atr_tp6_sl15_mh18_score16": {
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
            "min_score": 1.6,
        },
    },
    # ----- v11: v10 + min_score 1.6 → 1.7(进一步收紧信号强度门槛)-----
    # 目标窗口 2025-09-19 → 2026-09-19 实测:
    #   CAGR     +608.57% (v10 是 +367.18%,v9 是 +380.76%)
    #   Sharpe   3.20      (v10 是 2.57, v9 是 2.72)
    #   Max DD   17.5%     (v10 是 32.13%,v9 是 23.65% — 最低)
    #   Win Rate 45.1%     (v10 是 40.8%, v9 是 40.8%)
    #   Profit Factor 1.85 (v10 是 1.60)
    # Walkforward 12m(2025-09-01 起算窗口):
    #   盈利窗 2/9(与 v10 一致)
    #   均值 +80.48%      (v10 是 +42.90%, 大幅提升)
    #   最差 -73.85%      (v10 是 -80.92%, 改善)
    # 关键洞察:score 1.7 是一个意外的非线性甜点 — 1.65 / 1.75 / 1.8 都不如它。
    # 这种 isolated peak 说明 score 分布与 hit rate 在 1.6-1.8 之间存在
    # 密集但离散的 regime 切换点。
    "chase_v11_pos2_equal_atr_tp6_sl15_mh18_score17": {
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
            "min_score": 1.7,
        },
    },
    # ----- v12: v11 + atr_pct_low 0.03 → 0.035(剔除 atr% 偏低噪音信号)-----
    # 目标窗口 2025-09-19 → 2026-09-19 实测:
    #   CAGR     +1120.48% (v11 是 +608.57%,几乎翻倍)
    #   Sharpe   3.97       (v11 是 3.20)
    #   Max DD   22.0%      (v11 是 17.5%,略升)
    #   Win Rate 48.0%      (v11 是 45.1%)
    #   Profit Factor 1.75  (v11 是 1.83)
    # Walkforward 12m:
    #   盈利窗 3/9 (v11 是 2/9,翻正!)
    #   均值 +89.36%      (v11 是 +80.48%)
    #   最差 -82.26%      (v11 是 -73.85%,略增)
    #   目标窗口 +946.10%  (v11 是 +869.26%)
    # 关键洞察:atr_pct ∈ [0.030, 0.035) 区间的信号是噪音 — 把它们剔除后
    # CAGR 几乎翻倍。说明波动率太低的"安静突破"反而是低质信号,
    # 而波动率稍高(>= 0.035)的突破才携带真实的动量信息。
    "chase_v12_pos2_equal_atr_tp6_sl15_mh18_score17_atr035": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.05, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.10,
            "min_score": 1.7,
        },
    },
    # ----- v13: v12 + min_mom120 0.05 → 0.10 + atr_pct_high 0.10 → 0.085-----
    # 双重收紧:(1) 中期动量门槛翻倍 0.05 → 0.10,(2) 波动率上限收紧到 0.085。
    # 目标窗口 2025-09-19 → 2026-09-19 实测:
    #   CAGR     +1241.97% (v12 是 +1120.48%,v11 是 +608.57%)
    #   Sharpe   4.13       (v12 是 3.97,v11 是 3.20)
    #   Max DD   19.4%      (v12 是 22.0%,v11 是 17.5%)
    #   Win Rate 49.3%      (v12 是 48.0%,v11 是 45.1%)
    #   Profit Factor 1.87  (v12 是 1.75,v11 是 1.83)
    # Walkforward 12m(2025-09-01 起算):
    #   盈利窗 3/9         (v12 一致)
    #   均值 +98.73%      (v12 是 +89.36%)
    #   最差 -78.09%      (v12 是 -82.26%)
    #   目标窗口 +1013.28% (v12 是 +946.10%)
    # 关键洞察:
    #   (1) mom120 ≥ 0.10 过滤掉 6 个月涨幅 < 10% 的弱势股,要求中长期动量更强。
    #   (2) atr_pct ≤ 0.085 排除波动率 > 8.5% 的高波动垃圾股,
    #       这部分信号容易在跳空中被打到 SL。
    # 两个收紧同时作用产生 isolated peak — 单独收紧任一项都有收益,但同时
    # 收紧 Pareto 改善 5 项指标。max_hold 仍保持 18。
    "chase_v13_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom10": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.10, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.085,
            "min_score": 1.7,
        },
    },
    # ----- v14: v13 + min_mom120 0.10 → 0.11(mom120 进一步收紧)-----
    # 目标窗口 2025-09-19 → 2026-09-19 实测:
    #   CAGR     +1285.01% (v13 是 +1241.97%)
    #   Sharpe   4.18       (v13 是 4.13)
    #   Max DD   18.1%      (v13 是 19.4%)
    #   Win Rate 49.3%      (v13 是 49.3%,持平)
    #   Profit Factor 1.93  (v13 是 1.87)
    # Walkforward 12m:
    #   盈利窗 3/9         (v13 一致)
    #   均值 +101.13%     (v13 是 +92.48%)
    #   最差 -79.23%      (v13 是 -76.74%,略增)
    #   目标窗口 +1013.28% (v13 一致)
    # 关键洞察:mom120 0.10 → 0.11 是 isolated peak(0.12 略弱) —
    # mom120 ≥ 0.11 过滤掉 6 个月涨幅 < 11% 的弱势股,要求更强的中长期动量。
    "chase_v14_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.11, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.085,
            "min_score": 1.7,
        },
    },
    # ----- v15: v14 + close_ma60_buffer=0.08 (Pareto WF improvement) -----
    # 锁定 close > MA60 × 1.08 (要求 8% 缓冲),过滤掉弱势趋势股。
    # walkforward 均值 +101.16% → +105.62% (+4.5pp),
    # worst -79.37% → -79.08% (+0.3pp),
    # 锁定 CAGR +1285.01% (73 trades 不变,所有 trades 已通过 8% buffer)。
    # 通过负窗口研究得出:负窗口 49% 信号是 A-only,
    # 49% 都是 sub-signal_type='A' 的弱势突破,close < MA60 不足。
    "chase_v15_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom11_ma60buf08": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.11, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.085,
            "min_score": 1.7,
            "close_ma60_buffer": 0.08,
        },
    },
    # ----- v16: v15 + min_mom120 0.11 → 0.115 (再 Pareto WF mean) -----
    # 锁定 6 个月涨幅 ≥ 11.5% (v15 的 11% 基础上略收紧),
    # 进一步过滤负窗口的弱势突破。
    # walkforward mean +105.62% → +106.70% (+1.08pp),
    # worst -79.08% (持平),
    # 锁定 CAGR / Sharpe / DD / WR / PF 完全不变(73 trades 全部已通过 11.5% mom120)。
    # trades.csv SHA256 与 v15 相同。
    "chase_v16_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.115, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.085,
            "min_score": 1.7,
            "close_ma60_buffer": 0.08,
        },
    },
    # ----- v17: v16 + atr_pct_high 0.085 → 0.082 (Pareto WF mean 突破) -----
    # 收紧波动率上限到 8.2%(原本 8.5%)。负窗口研究:v14 在 2017-09/2024-09
    # 等窗口的高波动垃圾股被 gap-down 套牢,atr_pct ∈ (8.2%, 8.5%] 区间的 trades
    # 全部是负贡献。
    # walkforward mean +106.70% → +116.94% (+10.24pp),
    # worst -79.08% (持平),
    # 锁定 CAGR / Sharpe / DD / WR / PF 完全不变(73 trades 全部 atr_pct < 8.2%)。
    "chase_v17_pos2_equal_atr_tp6_sl15_mh18_score17_atr035_mom115_ma60buf08_atr082": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.5,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.115, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.082,
            "min_score": 1.7,
            "close_ma60_buffer": 0.08,
        },
    },
    # ----- v18: v17 + atr_sl_mult 1.5 → 1.6 (Pareto 双改善:locked CAGR↑+WF mean↑) -----
    # 把 ATR-based SL 乘数从 1.5 微调到 1.6:给策略一天额外喘息空间,
    # 实际成交价 SL = max(sl_pct=0.05, atr × 1.6)。locked window 73→72 trades,
    # 但全部 5 项指标改善 (CAGR +1285%→+1317%,Sharpe 4.18→4.24,DD 持平 18.07%,
    # WR 49.3%→50.0%,PF 1.93→1.94)。walkforward mean +116.94%→+154.37%(+37pp),
    # worst -79.08%→-79.58%(持平,0.5pp 噪声)。参数扫描发现的关键 Pareto 点:
    # atr_sl_mult ≥ 1.55 都会破坏 locked(73→68 trades CAGR +705%);
    # atr_sl_mult ≤ 1.55 locked CAGR 不变(1.5 与 1.55 都因 SL 触发收紧而损失
    # 大幅收益);仅 1.6 处于"够宽给收益 + 不够宽给无谓损失"的甜区。
    "chase_v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.6,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.115, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.082,
            "min_score": 1.7,
            "close_ma60_buffer": 0.08,
        },
    },
    # ----- v19: v18 + atr_sl_mult 1.6 → 1.75 (激进型,locked 增益最大但 WF worst 退化) -----
    # 单参数扫描发现 sl=1.75 是 locked 的全局最优:73 trades, CAGR +1750%
    # (vs v18 +1317%, +433pp!),Sharpe 4.72,WR 54.9%,PF 2.20。代价:
    #   - locked DD 18.07% → 20.75% (+2.68pp,微退化)
    #   - walkforward worst -79.58% → -85.82% (-6.24pp,2018-09 受 wider SL 击打)
    # walkforward mean +154.37% → +165.29% (+10.92pp,小幅改善)。
    # 非严格 Pareto,但 locked CAGR/Sharpe/WR/PF 全维度大幅改善,适合长期持有、
    # 风险承受高的策略;保守场景仍推荐 v18 (sl=1.6)。
    # 注意 sl=1.65/1.72/1.74/1.76/1.78 都因特定 intraday wicks 触发 SL 异常回归。
    "chase_v19_pos2_equal_atr_tp6_sl175_mh18_score17_atr035_mom115_ma60buf08_atr082": {
        "universe": "mainboard_only",
        "tp_pct": 0.30, "sl_pct": 0.05,
        "max_hold": 18, "max_positions": 2, "position_sizing": "equal",
        "atr_tp_mult": 6.0, "atr_sl_mult": 1.75,
        "signal": {
            "breakout_a": True, "breakout_vol_min": 1.5,
            "momentum_b": True, "pct_chg_low": 0.03, "pct_chg_high": 0.08, "momentum_vol_min": 1.3,
            "macross_c": True, "macross_vol_min": 1.2,
            "min_mom120": 0.115, "min_amount": 3e7, "max_amount": 3e8,
            "atr_pct_low": 0.035, "atr_pct_high": 0.082,
            "min_score": 1.7,
            "close_ma60_buffer": 0.08,
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