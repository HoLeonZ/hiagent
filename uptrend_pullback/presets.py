"""策略 preset 配置。

当前 Pareto 最优:
  v33_long_reverse_v20 — Monte-Carlo reverse iter (100 perturbations) 选出的 v19 邻域新最优点。

  23 个 2m walk-forward 窗口 (2024-09..2026-09, 1m 步) simulate 引擎实测:
    median     +158.95%   (v19: +21.72%, +137 pp)
    mean       +175.56%   (v19: +32.22%, +143 pp)
    Sharpe     3.64       (v19: 2.96, +0.68)
    avg_dd     20.86%     (v19: 21.0%, tied)
    worst_dd   35.93%     (v19: 48.1%, -12.2 pp) ✓
    n_pos      20/23
    avg_trades 12.78      (v19: 8.30, +4.5)
    composite  1.7449     (v19: 0.9550, +82.7%) ✓ (按 median+0.1·sharpe−avg_dd)

  关键变化 vs v19 (6 个字段):
    tp_pct                0.305   → 0.2628   (更低 TP, 锁定更小利润)
    sl_pct                0.0293  → 0.021    (更紧 SL)
    max_hold              15      → 18       (允许更久)
    signal.pct_chg_low    -0.065  → -0.088   (要求更深回调才入场)
    signal.min_above_ma60 0.65    → 0.6693
    signal.close_ma60_buf 0.02    → 0.0121
  方向解读: 更严的回调过滤 + 更紧 SL + 更低 TP = "更多小胜 + 更少大亏",
    与 CLAUDE.md §4 SL-first worst-case 政策契合。

历史版本:
  v33_long_reverse_v19 — reverse iter 起点。2026-09-21 v18 邻域联合搜索 Pareto strict
    improvement (composite 0.9550)。

优化路径:
  v3 (sweep_v6) → v7 (sweep_v7) → v12 → v13 (buf+mom)
  → v14 (mom=0.12) → v15 (SL=0.0293 单峰) → v16 (mom plateau)
  → v17 (TP 0.30→0.303,超精扫 TP grid 发现)
  → v18 (mom 0.13→0.16 + ma60_ratio 0.60→0.65,paradigm-axis 联合搜索)
  → v19 (TP 0.303→0.305 + mom 0.16→0.18,v18 邻域 联合搜索)
  → v20 (Monte-Carlo reverse iter 100 次扰动 v19 邻域,新范式:更深回调+更紧 SL+更低 TP)

字段说明:
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
    # ⛔ 2026-10-18: **本族全部 preset 已判定不可用** (见 docs/strategy_mining_log.md
    #    §4 与 §6.3)。下面注释里散布的**历史扫描数字** (CAGR / Sharpe / DD / win% 等)
    #    是**修正前**的引擎跑出来的, 至少有两处系统性虚增已被推翻:
    #      * §4 跳空穿越止损的成交价用了 sl_p —— 修正后一个变体由 +180% 掉到 -0.6%;
    #      * CAGR 分母用了请求窗而非实测期。
    #    ⇒ 这些数字**无法用当前代码复现** (CLAUDE.md §7: 不能复现的数字按陈旧处理),
    #      **不要引用、不要据此选 preset**。保留它们只为留档"试过哪些变体"。
    # v33_long_reverse_v19 — v18 + tp_pct 0.303→0.305 + min_mom120 0.16→0.18
    # (workflow v18-neighborhood 联合搜索发现)。
    # 关键参数变更:
    #   - sl_pct 0.0293: v15 精扫得到的 SL 单峰,保留。
    #   - tp_pct 0.303→0.305: v18 邻域 TP 精扫发现。
    #   - min_mom120 0.16→0.18: 与 min_above_ma60_ratio=0.65 协同。
    #   - min_above_ma60_ratio 0.65: v18 关键维度,保留。
    #   - close_ma60_buffer 0.02: buf∈[0.01,0.02] 等价。
    # 注: 历史实测数字不入注释 (CLAUDE.md §7), 重跑验证见 commit log。
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.0293
    # tp_pct: 0.305
    # max_hold: 15
    # Note: Fixed TP/SL; no ATR multiplier. Pessimistic Default = 2.93% stop / 30.5% TP.
    "v33_long_reverse_v19": {
        "universe": "mainboard_only",
        # V6 (2026-09-22, CLAUDE.md §4): SL-first tiebreak intraday — 已在 portfolio.py 落地
        "intraday_tiebreak": "sl_first",
        # V5 (R8, 2026-09-21, CLAUDE.md §4): 单笔成交量 ≤ Bar_Volume × 0.10
        "max_volume_participation": 0.10,
        # V7 (2026-09-22, CLAUDE.md §5): Statistical Rigor — sweep size。
        # v33_long_reverse_v19 是 v3→v19 顺序 sweep (每版扩展前一版邻域),
        # 总比较数 ≈ 19 版本 × 邻域 ≈ n_comparisons。
        "n_comparisons": 19,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System 声明。
        # 当前 strategy 仍读 v_daily (单 close = forward-adjusted) 作为信号+执行共用价。
        # 完整 V3a 落地需: panel 改读 v_daily_dual (含 adj_*/raw_* 列),
        # 信号用 adj_close, SL/TP+mark-to-market 用 raw_close。
        # 当前 preset 声明未来切到 dual loader 时使用的字段。
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "tp_pct": 0.305,
        "sl_pct": 0.0293,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "position_fraction": 1.0,    # §2 (CLAUDE.md All-In Sizing Policy 2026-09-22)
        "MAX_POSITION_PCT": 1.0,    # §2
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.65,
            "close_ma60_buffer": 0.02,
            "min_mom120": 0.18,
        },
    },
    # v33_long_reverse_v20 — Monte-Carlo reverse iter (100 perturbations) v19 邻域新最优。
    # iter=97 / seed=42 (Monte-Carlo reverse iter 产出; 历史实测数字不入注释, 见 §7)。
    # 关键 insight (vs v19):
    #   - pct_chg_low -0.065 → -0.088: 要求更深回调才入场 (过滤掉浅回调假突破)
    #   - sl_pct 0.0293 → 0.021: 更紧 SL,坏单更早止损
    #   - tp_pct 0.305 → 0.2628: 更低 TP,落袋为安 (与更深回调筛选的高质量信号协同)
    #   - max_hold 15 → 18: 给更深回调的反弹留更多时间
    #   - ma60_ratio 0.65 → 0.6693,close_ma60_buf 0.02 → 0.0121: 与新 tp/sl 微调
    # n_comparisons=100: iter_reverse sweep size (100 次随机扰动,CLAUDE.md §5 DSR/Bonferroni)
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.021
    # tp_pct: 0.2628
    # max_hold: 18
    # Note: Fixed TP/SL; no ATR multiplier. Pessimistic Default = 2.1% stop / 26.28% TP.
    "v33_long_reverse_v20": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 100,
        "tp_pct": 0.2628,
        "sl_pct": 0.021,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "position_fraction": 1.0,    # §2 (CLAUDE.md All-In Sizing Policy 2026-09-22)
        "MAX_POSITION_PCT": 1.0,    # §2
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.088,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6693,
            "close_ma60_buffer": 0.0121,
            "min_mom120": 0.18,
        },
    },
    # v33_long_reverse_v21 — v20 + 市场级 regime gate (2026-10-14, 修正评估链后重估)
    #
    # 由来: 用修正后的评估链重估全部候选(见 uptrend_pullback/results/PRESET_SEARCH.md §14)。
    # 当时修正了三把尺子:
    #   ① equity 曲线把建仓名义额计入两次 -> sharpe/max_dd/exposure 全部失真
    #   ② DSR 拿年化 Sharpe 比逐期阈值 -> 中等 Sharpe 被系统性折减到 0
    #   ③ 目标函数: 该策略盈亏由**右尾**驱动(79% 止损、盈亏比 5.42、前 10% 交易
    #      贡献 297% 净盈亏),而 Sharpe 会用波动率惩罚这条尾巴
    #      => 改用 R-multiple 期望 E[R] (R_trade = sl_pct × entry_price × size)
    #
    # 为什么是 regime gate: 在**三个样本**上它都是最好的那一个 ——
    #   train  2024-09..2026-03 : E[R] +1.164 vs v20 +0.650 (PF 1.94 vs 1.41)
    #   holdout 2026-03..2026-09: E[R] +2.622 vs v20 +0.359 (但仅 14 笔, t=1.62, 不显著)
    #   独立期 2020-01..2024-09: E[R] -0.329 vs v20 -0.625 (两者均为负, 见下)
    # 且它的**尾部依赖最低**: 尾十分位占毛盈利 111% vs v20 191% —— 收益最不依赖少数几笔。
    # regime gate 用 compute_regime 的**默认参数**(不做调参), 避免在 gate 上过拟合。
    #
    # ⚠️ 必须同时记录的负面证据(不得只报好的一面):
    #   * 独立时期 2020-2024: 本 preset E[R] = **-0.329** (t=-1.03); v20 = -0.625
    #     (t=-2.73, 681 笔, 签名显著为负)。即**这个族在非趋势市里是亏钱的**;
    #     2024-09 之后的正值来自当时的牛市 regime(策略 ≈ 市场 × 1.6 beta)。
    #   * 因此本 preset **没有可证实的正 alpha** (§5)。它只是「亏得最少、最不依赖
    #     少数几笔」的那一个, 不是「更赚钱」的那一个。
    #   * 代价: 参与度大幅下降(train 122 vs 176 笔; holdout 14 vs 63 笔), 样本量小。
    #
    # §5 Iterative-Tuning Accounting: n_comparisons = 121
    #   = v20 自报的 100 + 本次搜索 21 次试验 (k=101..121: 6 消融 + 3 信号候选 +
    #     5 执行层候选 + 3 regime 候选 + 1 universe + 1 反转排序 + 2 重复基线)
    # CLAUDE.md §4 TP/SL compliance header
    # exit_policy: fixed
    # sl_pct: 0.021
    # tp_pct: 0.2628
    # max_hold: 18
    "v33_long_reverse_v21": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        "n_comparisons": 121,
        "tp_pct": 0.2628,
        "sl_pct": 0.021,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "position_fraction": 1.0,    # §2 (CLAUDE.md All-In Sizing Policy 2026-09-22)
        "MAX_POSITION_PCT": 1.0,     # §2
        # 市场级择时 (compute_regime 默认参数; 无未来函数, 只用 ≤T 数据)
        "regime": {
            "ma_window": 20,
            "breadth_window": 20,
            "min_breadth": 0.45,
            "require_rising": False,
        },
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.088,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.6693,
            "close_ma60_buffer": 0.0121,
            "min_mom120": 0.18,
        },
    },
    # v33_long_reverse_v22 (2026-10-17): v21 + signal.max_amount 3e8 → 1e9。
    #
    # 由来: 短侧的 v68 发现"流动性**上界** 3e8 把日成交额 3 亿以上的票整类排除,
    # 而那批并不更差"。`max_amount = 3e8` 这个常量在**四个引擎里各写了一遍**
    # (族内不对称), 短侧撤掉后收益显著改善, 长侧从未试过 —— 本条把它平移过来。
    #
    # 五个窗口 (W2 / IND / IS1 / IS2 + 全新 holdout 2019-10-01..2021-09-30):
    #   Calmar: 4/5 更高 (W2 / IND / IS2 / HOLD), 幅度大; IS1 更低
    #   CAGR  : 4/5 更高 (同上)
    #   MaxDD : 3/5 更低
    #   Sharpe: 2/5 更高
    #
    # ⚠️ 必须同时记下否定的一半: **本 preset 并没有让这个族变得可用** ——
    # IND (-33%) / IS1 (-31%) / IS2 (-20%) 三个窗口的年化收益**仍然全部为负**,
    # 与 §6 已写下的"该族在非趋势市里期望为负"一致。它只是"亏得更少/赚得更多
    # 的那一个", 不是可用策略。
    #
    # 另: 逐笔 E[R] 口径下 `min_mom120` 覆盖**不生效** (改回 0.0 结果逐位相同),
    # 已在本轮记录; 该覆盖保留, 不追究。
    #
    # §5 n_comparisons = 121 + 5 (= v21 自报 121 + 本轮该改动在五个窗口上的评估)
    # 本节不记数字 (§7)。
    "v33_long_reverse_v22": {
        "universe": "mainboard_only",
        "intraday_tiebreak": "sl_first",
        "max_volume_participation": 0.10,
        "price_source_for_signal": "adj_close",
        "price_source_for_execution": "raw_close",
        # §5 试验记账 (2026-10-17, Iteration 82): +10。
        # 本轮沿 max_hold 轴对**本 preset** 在 IND/W2 各评估 5 个取值 (18/5/3/2/1) = 10 次
        # —— 即使结论是"该轴无稳定结构、不改动预设", **看过了就要计**:
        # §5 明文「Every iteration — including changes to the evaluation window itself —
        # increments n_trials for DSR/Bonferroni purposes」。
        # (更早还有几轮对本 preset 的评估 —— Iteration 78 的滑点开关对比 (2 窗口 × 2 设置)
        #  等 —— 尚未计入; 属**已知欠账**, 记在此处待补齐, 不假装它不存在。)
        "n_comparisons": 136,
        "tp_pct": 0.2628,
        "sl_pct": 0.021,
        "max_hold": 18,
        "max_positions": 1,
        "position_sizing": "all_in",
        "position_fraction": 1.0,
        "MAX_POSITION_PCT": 1.0,
        "regime": {
            "ma_window": 20,
            "breadth_window": 20,
            "min_breadth": 0.45,
            "require_rising": False,
        },
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.088,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 1e9,
            "min_above_ma60_ratio": 0.6693,
            "close_ma60_buffer": 0.0121,
            "min_mom120": 0.18,
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
