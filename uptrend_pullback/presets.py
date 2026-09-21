"""策略 preset 配置。

单一 preset:
  v33_long_reverse_v3 — v33_long_reverse 的 TP/SL 二维网格精扫 (sweep_v6) Pareto 最优点。

字段说明：
  tp_pct / sl_pct     固定止盈止损；给了 atr_*_mult 时被 ATR 自适应覆盖
  atr_tp_mult         止盈宽度 = ATR% × 本系数
  atr_sl_mult         止损宽度 = ATR% × 本系数
  regime              大盘择时参数；None 表示不做择时
  signal              select_entries 的关键字参数
"""
from __future__ import annotations

import copy

MAX_HOLD_LIMIT = 20

PRESETS: dict[str, dict] = {
    # v33_long_reverse_v3 — v33_long_reverse 的 TP/SL 二维 5×5 网格精扫 (sweep_v6) Pareto 最优点。
    # 关键参数:
    #   - sl_pct 0.021: sweep_v6 5×5 grid 单峰,(tp=0.30, sl=0.021) CAGR 最大,无更优组合。
    #   - signal.min_above_ma60_ratio 0.55: 趋势持续性过滤,弱势趋势的回调不上车。
    # 12 月窗口 (2025-09-16 .. 2026-09-16) v3 引擎实测:
    #   CAGR       488.84% / Sharpe 2.941 / max_dd 27.65% / win_rate 28.85%
    #   profit_fac 2.311 / trades 52 (≥ 40 阈值)
    # 4 个指标 Pareto 改善 (CAGR/Sharpe/Win/PF), DD 在风险预算 35% 内。
    # 注意:all_in 模式 + 高 CAGR 必然伴随较高 DD 风险;样本外表现需另行评估。
    "v33_long_reverse_v3": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.021,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # v33_v3_tp18_sl4 — 执行层放宽:SL 2.1%→4% 覆盖开盘跳空 gap,TP 30%→18% 更易兑现
    "v33_v3_tp18_sl4": {
        "universe": "mainboard_only",
        "tp_pct": 0.18,
        "sl_pct": 0.04,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # v33_v3_tp18_sl4_pos3 — 在 v3a 基础上分散持仓:max_positions 1→3
    "v33_v3_tp18_sl4_pos3": {
        "universe": "mainboard_only",
        "tp_pct": 0.18,
        "sl_pct": 0.04,
        "max_hold": 15,
        "max_positions": 3,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # v33_v3_tp15_sl35_pos3 — 更紧的 TP/SL + 分散持仓
    "v33_v3_tp15_sl35_pos3": {
        "universe": "mainboard_only",
        "tp_pct": 0.15,
        "sl_pct": 0.035,
        "max_hold": 15,
        "max_positions": 3,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # v3a 邻域微调 - 候选集
    "v33_v3_tp20_sl4": {  # TP 18→20,期望更高单笔收益
        "universe": "mainboard_only", "tp_pct": 0.20, "sl_pct": 0.04, "max_hold": 15,
        "max_positions": 1, "position_sizing": "all_in",
        "signal": {"entry_mode": "v33_long_mirror", "min_down_streak": 3,
                   "max_down_streak": 10, "pct_chg_low": -0.05, "pct_chg_high": -0.02,
                   "min_amount": 3e7, "max_amount": 3e8, "min_above_ma60_ratio": 0.55},
    },
    "v33_v3_tp15_sl4": {  # TP 18→15,期望更高 TP 命中率
        "universe": "mainboard_only", "tp_pct": 0.15, "sl_pct": 0.04, "max_hold": 15,
        "max_positions": 1, "position_sizing": "all_in",
        "signal": {"entry_mode": "v33_long_mirror", "min_down_streak": 3,
                   "max_down_streak": 10, "pct_chg_low": -0.05, "pct_chg_high": -0.02,
                   "min_amount": 3e7, "max_amount": 3e8, "min_above_ma60_ratio": 0.55},
    },
    "v33_v3_tp18_sl5": {  # SL 4→5,覆盖更大 gap
        "universe": "mainboard_only", "tp_pct": 0.18, "sl_pct": 0.05, "max_hold": 15,
        "max_positions": 1, "position_sizing": "all_in",
        "signal": {"entry_mode": "v33_long_mirror", "min_down_streak": 3,
                   "max_down_streak": 10, "pct_chg_low": -0.05, "pct_chg_high": -0.02,
                   "min_amount": 3e7, "max_amount": 3e8, "min_above_ma60_ratio": 0.55},
    },
    "v33_v3_tp18_sl35": {  # SL 4→3.5,稍微收紧
        "universe": "mainboard_only", "tp_pct": 0.18, "sl_pct": 0.035, "max_hold": 15,
        "max_positions": 1, "position_sizing": "all_in",
        "signal": {"entry_mode": "v33_long_mirror", "min_down_streak": 3,
                   "max_down_streak": 10, "pct_chg_low": -0.05, "pct_chg_high": -0.02,
                   "min_amount": 3e7, "max_amount": 3e8, "min_above_ma60_ratio": 0.55},
    },
    # v3a 信号层微调 - 严格的趋势过滤
    "v33_v3_tp18_sl4_ma60_60": {  # min_above_ma60_ratio 0.55→0.60
        "universe": "mainboard_only", "tp_pct": 0.18, "sl_pct": 0.04, "max_hold": 15,
        "max_positions": 1, "position_sizing": "all_in",
        "signal": {"entry_mode": "v33_long_mirror", "min_down_streak": 3,
                   "max_down_streak": 10, "pct_chg_low": -0.05, "pct_chg_high": -0.02,
                   "min_amount": 3e7, "max_amount": 3e8, "min_above_ma60_ratio": 0.60},
    },
    # ------------------------------------------------------------------
    # v4 候选 preset — 基于 12 窗口 × 1614 笔 trade 拆解反推的设计：
    #
    # 关键发现：
    #   1. SL=2.1% 在 270 笔 SL 中有 99 笔 (36.7%) 被开盘跳空击穿，
    #      切错洗盘阶段 → 放宽到 4%。
    #   2. mom120 < 0.1 的 6 笔全输（avg -116k/-44k）→ 加 mom120 >= 0.05 过滤。
    #   3. 深回调 (-0.30, -0.20] 胜率仅 10%，浅回调 (-0.05, -0.02] 胜率 50%+
    #      → 回调下限放宽到 -0.07（接收更多浅回调，去掉深回调陷阱）。
    #   4. hold_days (10,15] 胜率 70%、(15,100] 100% → 拉长 max_hold 到 18
    #      给反弹留更多时间（仍在硬约束 20 内）。
    #   5. TP 保持 30% 不变：高盈亏比是 v3 优势所在。
    #
    # 期望改进点：
    #   - SL 放宽后 SL 笔数预计 ↓30%，TP 笔胜率↑。
    #   - mom120 过滤预计去掉 5-10% 的烂单。
    #   - max_hold=18 让中等回调有时间展开。
    # ------------------------------------------------------------------
    "v33_v4_tp30_sl4_mom05_pb07_hold18": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.04,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.07,        # -0.05 → -0.07：浅回调覆盖更全
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
            "min_mom120": 0.05,          # 新增：剔除 mom120<0.05 的低位烂单
        },
    },
    # ------------------------------------------------------------------
    # v4a — 略保守：保留 v3 的 TP/SL，只动信号层 + max_hold
    # 用于验证"信号优化"和"止盈止损优化"哪个贡献更大
    # ------------------------------------------------------------------
    "v33_v4a_sl21_mom05_pb07_hold18": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.021,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.07,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
            "min_mom120": 0.05,
        },
    },
    # ------------------------------------------------------------------
    # v4b — 组合最优：SL 放宽 + 信号过滤 + 加 ma60 buffer 提升趋势质量
    # ------------------------------------------------------------------
    "v33_v4b_tp30_sl4_mom05_pb07_hold18_ma60buf2": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.04,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.07,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
            "min_mom120": 0.05,
            "close_ma60_buffer": 0.02,  # close >= MA60 * 1.02：要求明显在趋势线上方
        },
    },
    # ------------------------------------------------------------------
    # v5 — 基于 v4 walkforward 反推的精细调参：
    #
    # v4 失败在 2026-05..2026-07 窗口（-35.56%, 12 SL），原因是放宽的
    # pullback 下限 (-0.07) 让更多"假突破"单子入场。
    #
    # 修正方向：
    #   - pct_chg_low 收回到 -0.05（v3 原值）：剔除深回调陷阱
    #   - min_mom120 提到 0.10：只接受明确中期趋势
    #   - max_hold 保持 18：给反弹留时间
    #   - SL 放宽到 0.04：保留 v4 的优势（避免被开盘跳空击穿）
    #   - TP 保持 0.30：高盈亏比
    #   - 加 min_down_streak=4（v3 是 3）：剔除短期假洗盘
    # ------------------------------------------------------------------
    "v33_v5_tp30_sl4_mom10_pb05_streak4_hold18": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.04,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 4,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
            "min_mom120": 0.10,
        },
    },
    # ------------------------------------------------------------------
    # v5a — v5 进一步收紧信号：mom120>=0.15 + max_down_streak=8
    # 用于测试"更严信号 vs 更宽信号"哪个更稳
    # ------------------------------------------------------------------
    "v33_v5a_tp30_sl4_mom15_pb05_streak4_hold18": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.04,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 4,
            "max_down_streak": 8,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
            "min_mom120": 0.15,
        },
    },
    # ------------------------------------------------------------------
    # v5b — v5 但保留 v3 SL=2.1%，测试 SL 收紧时的真实影响
    # （v3 SL=2.1% 在 v3 baseline 中已是 baseline，结果已知）
    # 这里换 TP=25% 测一下：把 TP 折中
    # ------------------------------------------------------------------
    "v33_v5b_tp25_sl4_mom10_pb05_streak4_hold18": {
        "universe": "mainboard_only",
        "tp_pct": 0.25,
        "sl_pct": 0.04,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 4,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
            "min_mom120": 0.10,
        },
    },
    # ------------------------------------------------------------------
    # v6 — ATR 自适应 TP/SL（最终候选）：
    #
    # v3 信号日 atr_pct 分布（中位 6.3%, 25/75 分位 5.2%/7.7%）。
    # v3 的固定 SL=2.1% ≈ ATR × 0.33（过紧），固定 SL=4% ≈ ATR × 0.63（仍紧）。
    #
    # ATR 自适应优点：
    #   - 高波动股票自然用更宽止损（不会被洗盘）
    #   - 低波动股票保持紧凑止损（不让小波动浪费 risk budget）
    #   - 单参数控宽度，避免 v3a/v4 那种"普调 4%"的次优
    #
    # v3 信号层 100% 保留 + atr_sl_mult=1.0（≈ 6.3% median SL）+ atr_tp_mult=5.0
    # （≈ 31.5% median TP，与 v3 的固定 30% 一致）。
    # ------------------------------------------------------------------
    "v33_v6_atr_sl10_tp50_hold15": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.04,             # fallback，未启用 ATR 时使用
        "atr_tp_mult": 5.0,          # median ATR 6.3% × 5 = 31.5% ≈ v3 的 30%
        "atr_sl_mult": 1.0,          # median ATR 6.3% × 1 = 6.3% > v3 的 2.1%
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # ------------------------------------------------------------------
    # v6a — 验证 ATR 系数敏感度：SL×1.5（更宽），其余同 v6
    # ------------------------------------------------------------------
    "v33_v6a_atr_sl15_tp50_hold15": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.04,
        "atr_tp_mult": 5.0,
        "atr_sl_mult": 1.5,          # ≈ 9.5% median SL
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # v33_long_reverse_v7 — v3 的 TP/SL 6×7 精细网格精扫 (sweep_v7) 中位收益 Pareto 最优点。
    # 关键参数:
    #   - sl_pct 0.021 → 0.032: 放宽 SL 1.5pp,显著降低开盘跳空被"假止损"洗出的概率。
    #     v3 SL=2.1% 时跳空 gap-through 占比 36.7%,改 3.2% 后回落约一半,典型收益中枢抬升。
    #   - tp_pct 0.30 / max_hold 15 保持不变(经 sweep 验证为局部最优)。
    #   - 信号条件与 v3 完全一致(指标层面 v4-v6 的 mom/ma60buffer/ATR 自适应均未带来改善)。
    # 12 月窗口 (2024-09 .. 2026-09) backtrader 引擎实测:
    #   median       +27.19%   (v3: +18.60%, +46% 相对提升)
    #   mean         +16.73%   (v3: +17.60%, 略低;v7 分布更紧)
    #   win%(现)12+   66.7%    (v3: 66.7%, 一致)
    #   min/max      -34.30%/+51.92% (v3: -32.34%/+67.06%,极值略收敛)
    #   DD_avg/worst 24.42% / 45.73% (v3: 24.75% / 46.50%,几乎一致)
    #   avg_sharpe   1.28      (v3: 1.71, 反映 v7 极值收敛、风险调整后指标走弱)
    #   avg_trades   9.5       (v3: 10.8)
    #   avg_winrate  34.2%     (v3: 33.3%)
    #   avg_hold     6.1d      (v3: 5.6d,SL 放宽后持有略长)
    # 适用:追求"典型年份"收益更高的场景;若更看重 Sharpe 仍推荐 v3。
    "v33_long_reverse_v7": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.032,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.55,
        },
    },
    # v33_long_reverse_v8 — v7 信号层单维精扫 Pareto 最优点。
    # min_above_ma60_ratio 0.55 → 0.60,过滤掉"刚跨过 MA60 假突破"信号,
    # 在均值/Sharpe/DD 三个维度严格优于 v7,中位收益持平。
    # 12 月窗口 backtrader 引擎实测 (相对 v7):
    #   median +27.19% / mean +17.64% (+0.91pp) / Sharpe 1.45 (+0.17)
    #   avg_dd 24.17% (-0.25pp) / worst_dd 45.73% (持平) / trades 9.4
    "v33_long_reverse_v8": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.032,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.60,
        },
    },
    # v33_long_reverse_v9 — v8 信号层 min_above_ma60_ratio 精扫 Pareto 最优点。
    # 关键参数:
    #   - min_above_ma60_ratio 0.60 → 0.625: 进一步收紧趋势持续性过滤。
    #     在 12 窗口 backtrader 引擎实测中严格优于 v8(中位收益持平,均值/Sharpe/DD 三维度更优)。
    # 12 月窗口 backtrader 引擎实测 (相对 v8):
    #   median       +27.19%   (持平)
    #   mean         +19.30%   (v8: +17.64%, +1.66pp)
    #   Sharpe       1.60      (v8: 1.45, +0.15)
    #   avg_dd       23.39%    (v8: 24.17%, -0.78pp)
    #   worst_dd     45.73%    (持平)
    #   trades       9.2       (v8: 9.4, 微减)
    "v33_long_reverse_v9": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.032,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.625,
        },
    },
    # v33_long_reverse_v10 — v9 + pct_chg_low -0.05→-0.06 + SL 0.032→0.030。
    # 目标:拉高 Sharpe (1.60 → 2.51) 和 mean (19.30% → 25.95%)。
    # 牺牲:median (-6.19pp) 和 worst_dd (+6.43pp) 略有抬升,
    #      但复合指标 (mean × Sharpe) 提升 110%,显著优于 v9。
    # 关键参数:
    #   - pct_chg_low -0.05 → -0.06: 接收稍深的回调 (-5% ~ -6%),筛掉"刚下跌就抢反弹"的烂单
    #     (反而提升胜率,因为跌幅不够的信号带太多假突破噪音)。
    #   - SL 0.032 → 0.030: SL 略收紧,与更深的 pct_chg_low 形成"接更准的止损"组合。
    # 12 月窗口 backtrader 引擎实测 (相对 v9):
    #   median       +21.00%   (v9: +27.19%, -6.19pp)
    #   mean         +25.95%   (v9: +19.30%, +6.65pp) ✓
    #   Sharpe       2.51      (v9: 1.60, +0.91) ✓
    #   avg_dd       23.83%    (v9: 23.39%, +0.44pp)
    #   worst_dd     52.16%    (v9: 45.73%, +6.43pp) ⚠
    #   trades       9.2       (持平)
    #   winrate      38.6%     (v9: 35.5%, +3.1pp)
    "v33_long_reverse_v10": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.030,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.06,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.625,
        },
    },
    # v33_long_reverse_v11 — v10 + pct_chg_low -0.06→-0.065 + ma60_ratio 0.625→0.60。
    # 目标:拉高 composite (mean×Sharpe) 与 avg_dd。
    # 关键参数:
    #   - pct_chg_low -0.06 → -0.065: 接收更深一点的回调 (-6% ~ -6.5%)。
    #   - ma60_ratio 0.625 → 0.60: 趋势持续性略放宽,与更深的 pct_chg_low 形成"等更稳的回调再进"组合。
    # 12 月窗口 backtrader 引擎实测 (相对 v10):
    #   median       +21.16%   (v10: +21.00%, +0.16pp)
    #   mean         +26.93%   (v10: +25.95%, +0.98pp) ✓
    #   Sharpe       2.59      (v10: 2.51, +0.08) ✓
    #   avg_dd       23.39%    (v10: 23.83%, -0.44pp) ✓
    #   worst_dd     52.16%    (持平)
    #   trades       9.0       (v10: 9.2, -0.2)
    #   winrate      38.4%     (v10: 38.6%, -0.2pp)
    "v33_long_reverse_v11": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.030,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.60,
        },
    },
    # v33_long_reverse_v12 — v11 + SL 0.030→0.029。
    # 12 月窗口 backtrader 引擎实测 (相对 v11):
    #   median       +21.34%   (v11: +21.16%, +0.18pp)
    #   mean         +26.93%   (持平)
    #   Sharpe       2.66      (v11: 2.59, +0.07) ✓
    #   avg_dd       23.12%    (v11: 23.39%, -0.27pp) ✓
    #   worst_dd     52.05%    (v11: 52.16%, -0.11pp)
    #   trades       9.0       (持平)
    #   winrate      37.7%     (v11: 38.4%, -0.7pp)
    "v33_long_reverse_v12": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.029,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.60,
        },
    },
    # v33_long_reverse_v13 — v12 + close_ma60_buffer 0→0.02 + min_mom120 0→0.10。
    # 关键参数:
    #   - close_ma60_buffer 0 → 0.02: close >= MA60 × 1.02,要求明显在 MA60 上方,
    #     过滤"刚跨过 MA60 假突破"信号 — 与 min_above_ma60_ratio 形成两层叠加过滤。
    #   - min_mom120 0 → 0.10: 加入中期动量要求,只接受明确上升趋势。
    #     iter 23b 发现 mom120=0.05 单独加无效,但与 buf=0.02 协同形成 Pareto 改善。
    # 12 月窗口 (2024-09 .. 2026-09) backtrader 引擎实测 (相对 v12):
    #   median       +21.34%   (v12: +21.34%, 持平)
    #   mean         +28.40%   (v12: +26.93%, +1.47pp) ✓
    #   Sharpe       2.76      (v12: 2.66, +0.10) ✓
    #   avg_dd       22.55%    (v12: 23.12%, -0.57pp) ✓
    #   worst_dd     52.05%    (v12: 52.05%, 持平)
    #   trades       8.83      (v12: 9.0, -0.17)
    #   winrate      -         (略变)
    #   composite    0.7828    (v12: 0.7151, +9.5%) ✓
    "v33_long_reverse_v13": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.029,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.60,
            "close_ma60_buffer": 0.02,
            "min_mom120": 0.10,
        },
    },
    # v33_long_reverse_v14 — v13 + min_mom120 0.10→0.12。
    # 关键 insight: iter 26 验证 mom 在 0.11-0.14 是单峰,0.12 是最优。
    #   - mom=0.11 ≡ v13 (无改善,composite 0.7828)
    #   - mom=0.12 → +0.41pp mean, +0.03 Sharpe,composite 0.8043
    #   - mom=0.13/0.14 反而退步 (mom 收紧让部分中期上涨股被过滤掉)
    # 12 月窗口 backtrader 引擎实测 (相对 v13):
    #   median       +21.34%   (持平)
    #   mean         +28.81%   (v13: +28.40%, +0.41pp) ✓
    #   Sharpe       2.79      (v13: 2.76, +0.03) ✓
    #   avg_dd       22.56%    (v13: 22.55%, 持平)
    #   worst_dd     52.05%    (持平)
    #   trades       8.75      (v13: 8.83, -0.08)
    #   composite    0.8043    (v13: 0.7828, +2.7%) ✓
    "v33_long_reverse_v14": {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.029,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.60,
            "close_ma60_buffer": 0.02,
            "min_mom120": 0.12,
        },
    },
}


def get_preset(name: str) -> dict:
    """返回 preset 深拷贝；未知名抛 ValueError。"""
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
