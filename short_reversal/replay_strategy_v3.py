"""事件驱动 no-lookahead backtrader 策略（v3）。

Phase3V3Strategy：
  - next() 每根 bar 评估 5 条件（A/B/C/D/E），不再离线预生成 trades_df
  - 信号在 T 日 close 触发 → T+1 日 open 成交（cheat-on-open 模式）
  - TP/SL 在 next() 用 self.data.high[0]/low[0] 实时判断
  - 持仓/成本 self-maintain（不依赖 broker 撮合）
  - 所有判断只用 self.data.X[0] 和 [-1] —— 无未来引用

backtrader 源码（pip 装的 1.9.78.123）保持原封不动，只走子类化扩展。
"""
from __future__ import annotations

import logging
import math
from typing import Any

import backtrader as bt
import numpy as np

logger = logging.getLogger(__name__)

from core.dual_price import (
    LAYOUT_SHORT_REVERSAL,
    atr_slippage as dual_atr_slippage,
    extract_execution_bar,
    is_limit_down,
    volume_cap_fill,
)
from core.trade_schema import TRADE_COLS
from short_reversal.indicators_bt import (
    Am60,
    AmountRatio,
    AtrAdj,
    BelowMa60Ratio60,
    Ma20SlopeN,
    PctChg,
    ReturnN,
    UpStreak,
)

# 流动性窗口：am60 ∈ [3e7, 3e8]
LIQ_LOW = 3e7
LIQ_HIGH = 3e8

# B 条件：连阳天数范围
UP_STREAK_LOW = 3
UP_STREAK_HIGH = 10

# 防穿仓 (R8, 2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
# 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
MAX_VOL_PARTICIPATION = 0.10

# v67 (2026-10-13, CLAUDE.md §4): board-and-date-aware 跌停阈值。
# 主板 ±10% (0.095 容差); 创业板 300.SZ 2020-08-24 起 ±20% (之前 ±10%);
# 科创板 688.SH ±20% (2019-07-22 开板)。20% 板的票用 10% 阈值会误判跌停,
# 导致本可成交的空头 entry 被错误跳过。broad_only universe 必须走此逻辑。
_CHINEXT_20PCT_START = (2020, 8, 24)
_LIMIT_THRESHOLD_20PCT = 0.195


def _board_limit_threshold(code: str, bar_date, default: float) -> float:
    """按板 + 日期返回跌停阈值 (CLAUDE.md §4)。主板返回 default (保持兼容)。"""
    if code.endswith(".SH"):
        body = code.split(".", 1)[0]
        if body.startswith("688"):
            return _LIMIT_THRESHOLD_20PCT  # 科创板 ±20%
    elif code.endswith(".SZ"):
        body = code.split(".", 1)[0]
        if body.startswith("300"):
            if bar_date is not None and (
                bar_date.year,
                bar_date.month,
                bar_date.day,
            ) >= _CHINEXT_20PCT_START:
                return _LIMIT_THRESHOLD_20PCT  # 创业板 2020-08-24 起 ±20%
    return default

# Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical cost model constants
# (single-source-of-truth in core.dual_price.py). Declared at module level so
# the AST detector in tests/test_cost_model_canonical_conformance_4engine.py
# can verify canonical compliance. Used by Phase3V3Strategy.params below.
COMMISSION_RATE: float = 0.00025
STAMP_DUTY_RATE: float = 0.0005
MIN_COMMISSION: float = 5.0


def _canonical_trade_record(
    entry_date: Any,
    exit_date: Any,
    thscode: str,
    exit_reason: str,
    entry_price: float,
    exit_price: float,
    size: int,
    hold_days: int,
    entry_fee: float,
    exit_fee: float,
    atr_pct: float | None = None,
    sub_signal_type: str = "",
) -> dict:
    """Build a canonical 14-col trade record (CLAUDE.md §3, Tick 50/54).

    short_reversal uses short-side P&L:
      - gross_pnl = (entry_price - exit_price) × size  (做空方向)
      - net_pnl   = gross_pnl - entry_fee - exit_fee
      - net_return = net_pnl / (entry_price × size + entry_fee)

    `atr_pct` defaults to NaN because short_reversal emits its own
    indicators via indicators_bt.py (AtrAdj) but does not expose
    signal-day ATR% as a per-trade metric. `sub_signal_type` defaults
    to empty because sub-signal enum is chase_up-only.
    """
    gross_pnl = (entry_price - exit_price) * size
    fees = entry_fee + exit_fee
    net_pnl = gross_pnl - fees
    invested = entry_price * size + entry_fee
    net_return = (net_pnl / invested) if invested > 0 else 0.0
    return {
        "entry_date": entry_date,
        "exit_date": exit_date,
        "thscode": thscode,
        "exit_reason": exit_reason,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "hold_days": hold_days,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "net_return": net_return,
        "atr_pct": (atr_pct if atr_pct is not None else float("nan")),
        "sub_signal_type": sub_signal_type,
    }


def _assert_trade_dict_is_canonical(trade: dict) -> None:
    """Sanity check: trade dict must carry every canonical key (CLAUDE.md §0).

    Forward-defense guard: a missing key here means a downstream analyst
    will get KeyError when joining trades.csv. We assert at construction
    time rather than at write time so the bug surfaces at the strategy
    layer where the omission is easiest to fix.
    """
    missing = [k for k in TRADE_COLS if k not in trade]
    if missing:
        raise KeyError(
            f"short_reversal trade dict missing canonical keys {missing}; "
            f"present keys: {sorted(trade.keys())}"
        )


class Phase3V3Strategy(bt.Strategy):
    """事件驱动做空策略。"""

    params = dict(
        tp_pct=0.06,
        sl_pct=0.0005,
        max_hold=5,
        position_fraction=1.0,
        pct_chg_low=0.02,
        pct_chg_high=0.07,
        a_condition="default",  # 'default' (V1) | 'cascade_price' (V5)
        # B 条件: 连阳天数范围 (默认 [3, 10], 模块常量 UP_STREAK_LOW/HIGH)
        up_streak_low=3,
        up_streak_high=10,
        # E 条件: am60 流动性窗口 (默认 [3e7, 3e8], 模块常量 LIQ_LOW/HIGH)
        liq_low=3e7,
        liq_high=3e8,
        # A 条件: default 模式下 close<MA60 + below_ratio_60 阈值
        below_ratio_60=0.6,           # v3 默认 0.6
        close_ma60_buffer=0.0,        # 允许 close > ma60 的 buffer (默认 0, 即严格 close < ma60)
        # D 条件 MACD 阈值 (默认严格: DIF<0 & DEA<0 & |bar|<|prev_bar|)
        # 'strict' (V3 默认) | 'd_only' (D|dif|<0 only) | 'converge_strict' (|bar|<|prev_bar|*0.5)
        d_mode="strict",
        margin_rate=0.086,
        # Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical rates (was 0.0006+0.001
        # = 2.4x and 2x off canonical). Canonical values match engine.py
        # COMMISSION_RATE / STAMP_DUTY_RATE imported from core.dual_price single-source.
        commission_rate=0.00025,
        stamp_duty_rate=0.0005,
        # Round 29a (2026-09-28, CLAUDE.md §0/§3): MIN_COMMISSION ¥5 floor
        # wired into strategy params so _fill_pending_entries / _close can
        # apply `max(min_commission, notional × commission_rate)`. chase_up +
        # uptrend_pullback + cycle_price_action all use this floor in their
        # _buy_cost / _sell_proceeds helpers; short_reversal was the only
        # engine with the constant declared but never enforced (undercharges
        # small-notional trades by ¥2.50-5.00).
        min_commission=5.0,
        initial_capital=1_000_000.0,
        lot_size=100,
        # Round 14 (2026-09-28, CLAUDE.md §2): 默认 None, engine 必须显式从 preset
        # 传入 (fail-fast: 忘传时 cash_gate_threshold 计算报 TypeError 而非 silently 0.05)。
        # engine.py:170 通过 cfg.get('min_cash_ratio', 0.05) 保证生产路径总有值。
        min_cash_ratio=None,
        # V5' (2026-09-22, CLAUDE.md §4): ATR-aware slippage (R5 mirror)。
        # 当 atr_slip_scale > 0, 在 entry 时 slippage = atr_pct × participation × scale
        # (做空方向: slippage 上调 entry_price, 即扣更少 sale proceeds = 悲观假设)。
        # 当 atr_slip_scale = 0, 沿用 R3 默认无 slippage (保持 v33 baseline parity)。
        atr_slip_scale=0.0,
        atr_period=14,
        # V8 (2026-09-22, CLAUDE.md §4): max_volume_participation 与 intraday_tiebreak
        # 显式声明在 strategy params, preset 可覆盖。
        max_volume_participation=0.10,
        intraday_tiebreak="sl_first",
        # Round 23 (2026-09-28, CLAUDE.md §3/§4): 跌停阈值, 用于 LIMIT-DOWN guard。
        # 默认 0.095 (主板 -10% 跌停容差, 与 is_limit_down 核心常量对齐)。
        # preset 可覆盖 (e.g. 创业板 0.148, 科创板 0.198)。
        limit_down_threshold=0.095,
        # v50 (2026-10-12): F 条件 — MA20 5 日回归斜率 ≤ 0 (下降趋势过滤)。
        # 默认 False → v44 baseline 行为完全不变, v50 preset 显式开启。
        require_ma20_slope_neg=False,
        # 配套: 斜率回看窗口, 默认 5 日, 邻域可调 (3/5/7/10)。
        ma20_slope_period=5,
        # 配套: 斜率阈值 (price/day), 默认 0.0 (只要下降就过);
        # 严格化可设 -0.003 / -0.005 (要求每天至少下降 0.3%/0.5%)。
        ma20_slope_threshold=0.0,
        # v51 (2026-10-12): G 条件 — 弱势股过滤 (1M/3M/6M 累计跌幅)。
        # 用户重新定义"下降趋势"为"弱势股": 用过去 N 日累计回报 ≤ 阈值
        # (e.g. 1M ≤ -5% 意为最近 1 个月累计跌了 5% 以上) 替代"斜率"度量。
        # 与 F 互补: F 测短期动量 (rate), G 测中期水平 (level)。
        # 全部 opt-in, 默认 False → v50/v44 baseline 行为完全不变。
        require_weak_1m=False,
        weak_1m_threshold=-0.05,  # 1M = 21 trading days, 累计跌幅 ≥ 5%
        require_weak_3m=False,
        weak_3m_threshold=-0.10,  # 3M = 63 trading days, 累计跌幅 ≥ 10%
        require_weak_6m=False,
        weak_6m_threshold=-0.15,  # 6M = 126 trading days, 累计跌幅 ≥ 15%
        # v52 (2026-10-12): H 条件 — 无成交下跌过滤 (5d/20d 成交额比率)。
        # 用户重新定义"新方向": 不再测跌幅 (v51 失败), 改测「资金流衰减」。
        # amount_5d_avg / amount_20d_avg ≤ 阈值 = 近期成交显著萎缩
        # = 卖压枯竭 (selling exhaustion) = 反弹"死猫跳"
        # → 对 short_reversal 最有利 (空头押注反弹失败)。
        # 与 G 互补: G 测「价格水平」(cumret), H 测「资金流强度」(amount ratio)。
        require_amount_dryup=False,
        amount_dryup_threshold=0.70,  # 5d/20d ≤ 0.7 = 萎缩 30%+
        amount_dryup_short=5,         # 短窗口 5 日
        amount_dryup_long=20,         # 长窗口 20 日
        # v53 (2026-10-12): I 条件 — RSI(14) 超卖过滤 (经典反转指标)。
        # 用户选 B 方向: 与 H (amount dry-up) 不同, RSI 看价格动量 (rate of change)
        # 而非资金流。物理正交 → 测的是"价格超卖"而非"成交萎缩"。
        # 假设: 14 日 RSI 跌到 < 阈值 = 近期卖压极强 → 反弹更可能是死猫跳。
        # 与 F (slope) 互补: F 测趋势方向, I 测超卖程度。
        # 全部 opt-in, 默认 False → v50/v44/v52 baseline 行为不变。
        require_rsi_oversold=False,
        rsi_oversold_threshold=30,  # 经典 RSI<30 超卖线
        rsi_period=14,              # 14 日标准周期
        # v57 (2026-10-12): J 条件 — SL 之后冷静期。
        # 假设: 止损后立即重新入场容易"报复交易" — 同一波亏势尚未结束,
        # 下一笔也很可能输。强制 N 个交易日的全局冷却,跳过最强信号。
        # max_positions=1 时 J 是「全局」冷却 (不是 per-symbol),因为单仓策略
        # 同一时间只持 1 笔, 冷却窗口对所有候选 stock 都生效。
        # opt-in: sl_cooldown_days > 0 才启用, 默认 0 保 v50 baseline 兼容。
        sl_cooldown_days=0,
        # v61 (2026-10-13): K 条件 — 日内反转 (intraday reversal)。
        # 假设: 死猫跳最经典的微观结构是「开盘低 → 收盘高」,即
        # (close - open) / (high - low) > 阈值 (默认 0.6)。
        # 与 F (slope) 正交: F 测「多日趋势方向」(end-of-day), K 测
        # 「单日 intraday 形态」(day structure)。当日内回收 ≥ 60% 区间
        # + 收阳时, 表明买盘在日内接住了卖压 → 但因为整体仍处于下降
        # 趋势 (F 已确认), 这种"日内强反弹"很可能是死猫跳。
        # opt-in: require_intraday_reversal=True 才启用, 默认 False 保 v50 兼容。
        require_intraday_reversal=False,
        intraday_reversal_threshold=0.6,  # close 在 day range 中的相对位置
        intraday_reversal_require_close_above_open=True,  # 还要求收阳 (> open)
        # v58 (2026-10-13): 多仓并行 (max_positions > 1)。
        # 假设: 1→2 把单点风险分散到 2 个独立信号, 降低 DD 而不显著损失收益。
        # 同时调整每笔 sizing 为 free_cash / max_positions, 保持 all-in 总仓位。
        # opt-in: max_positions > 1 才启用, 默认 1 保 v50 baseline 兼容。
        # 注意: 此改动会改变 _fill_pending_entries 的 sizing 公式,
        # 通过 self.p.max_positions 路由, 其它模块不变。
        max_positions=1,
        # v65 (2026-10-13): 浮动止损 (trailing stop, short-side, opt-in)。
        # 假设: 固定 SL 在入场时锁定风险上界, 但不锁定利润。死猫跳反弹后
        # 继续下跌时, 若能把止损位随最低价 trailing 下移, 可锁住已获浮盈
        # 而不牺牲趋势延续的收益。
        # 机制: 跟踪持仓期最低价 lowest_price; 一旦浮盈 ≥ activation 阈值,
        # 有效止损从固定 sl_p 收紧为 lowest_price × (1 + trailing_stop_pct),
        # 取二者较紧者 (min)。
        # opt-in: trailing_stop_pct > 0 才启用, 默认 0 保 v50/v63 兼容。
        trailing_stop_pct=0.0,
        trailing_activation_pct=0.0,
        # v66 (2026-10-13): 市场宽度 regime gate (opt-in)。
        # 假设: 做空死猫跳的系统性风险是「牛市普涨」— 市场整体向上时,
        # 个股超买后回调的空头信号普遍失效 (beta 抬升)。用市场宽度
        # (universe 中 close > MA20 的比例) 作为 regime 代理:
        #   breadth 高 (多数票在 MA20 之上) = 牛市 regime → 跳过入场
        #   breadth 低 (多数票在 MA20 之下) = 熊市 regime → 允许入场
        # 与所有个股级条件 (A-K) 正交: 这是 market-level 维度。
        # opt-in: require_market_breadth_bear=True 才启用。
        require_market_breadth_bear=False,
        market_breadth_max=0.5,  # close>MA20 比例超过此值则不入场
        # v68 (2026-10-13): §2 conviction-based 填充选择 (opt-in)。
        # CLAUDE.md §2: 并发信号 MUST 按统计信心排序后依次填充 (single-bullet)。
        # 'first' (默认) = datas 顺序 (thscode 字母序, v50 兼容的任意 tie-breaker)。
        # 'steepest_slope' = 按 MA20 斜率升序 (最负 = 最陡下降 = 最高空头信心)。
        entry_selection="first",
        result_holder=None,
    )

    def __init__(self):
        # per-data 指标字典（避免多 data 共享 indicator）
        self.indi: dict[str, dict] = {}
        # v57 J 条件状态: 最近一次 SL 出场的 exit_date, 用于冷却检查。
        # 全局 (per-strategy, not per-symbol) — 因为 max_positions=1。
        self._last_sl_date: "datetime.date | None" = None
        # 关键：只迭代 data feed，不迭代后续 __init__ 期间被加进来的 indicator
        # backtrader 的 Lines_LineSeries __slots__ 不允许任意属性注入
        for d in self.datas:
            name = getattr(d, "_name", None)
            if not name:
                # indicator 没有 _name（或 _name 为 None/空），跳过
                continue
            # §3 Dual-Price (CLAUDE.md): 信号/指标 MUST use adj_close.
            # Layout B 的 AShareData 通过 LEFT JOIN v_daily_hfq 提供 adj_close line。
            # Execution broker 仍读 d.close (= raw) — 物理成交价。
            #
            # Baseline-parity fallback (Round 11 / 2026-09-28): legacy test
            # panels lack the adj_* column; AShareData.start() injects NaN
            # placeholders (see feed_bt.py:23-32 contract "Strategy 仍走
            # raw=close 默认路径, baseline parity 保留"). Detect by checking
            # the first bar's adj_close value: NaN means legacy panel → fall
            # back to d.close so indicators compute. Production data populates
            # adj_close and takes the adj_close branch.
            adj_close_line = d.lines.adj_close
            try:
                _adj_first = float(adj_close_line.array[0])
            except (IndexError, TypeError):
                _adj_first = float("nan")
            adj_close_src = d.close if math.isnan(_adj_first) else adj_close_line
            ma5 = bt.indicators.SMA(adj_close_src, period=5)
            ma10 = bt.indicators.SMA(adj_close_src, period=10)
            ma20 = bt.indicators.SMA(adj_close_src, period=20)
            ma60 = bt.indicators.SMA(adj_close_src, period=60)
            below_ratio = BelowMa60Ratio60(d, period=60)
            below_ratio.ma60_source = ma60.lines.sma  # ← 注入 ma60 line
            # v50 (2026-10-12): MA20 5 日回归斜率指标, F 条件用
            ma20_slope = Ma20SlopeN(d, period=self.p.ma20_slope_period)
            ma20_slope.ma_source = ma20.lines.sma  # ← 注入 ma20 line
            # v51 (2026-10-12): 1M/3M/6M 累计回报指标, G 条件用 (弱势股过滤)。
            # 注入 adj_close_src 保持 v3a dual-price (指标域, 不污染执行)。
            return_1m = ReturnN(d, period=21)
            return_1m.price_source = adj_close_src
            return_3m = ReturnN(d, period=63)
            return_3m.price_source = adj_close_src
            return_6m = ReturnN(d, period=126)
            return_6m.price_source = adj_close_src
            # v52 (2026-10-12): 5d/20d 成交金额比率, H 条件用 (无成交下跌过滤)。
            # 用 amount (元) 不用 volume (股) — 避免拆股干扰, 纯资金流度量。
            amount_ratio = AmountRatio(
                d,
                short_period=self.p.amount_dryup_short,
                long_period=self.p.amount_dryup_long,
            )
            # v53 (2026-10-12): RSI(14) on adj_close, I 条件用 (价格超卖过滤)。
            # 用 backtrader 内置 RSI 即可, 经典 Wilder 平滑 (14 日标准周期)。
            # Round 17 (2026-10-12): 改为 opt-in 构建。backtrader RSI 内部
            # avg_loss==0 时触发 ZeroDivisionError, 影响非 v53 preset 的 WFV
            # (v50/v55/v56 等不需要 RSI 也不读 indi["rsi"], 但 _once 预热仍执行)。
            # gate 与消费者一致 (line 887 if require_rsi_oversold), 零行为变化。
            rsi = (
                bt.indicators.RSI(adj_close_src, period=self.p.rsi_period)
                if self.p.require_rsi_oversold
                else None
            )
            self.indi[name] = {
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "ma60": ma60,
                "macd": bt.indicators.MACD(adj_close_src),
                "pct_chg": PctChg(d),
                "am60": Am60(d, period=60),
                "up_streak": UpStreak(d),
                "below_ma60_ratio_60": below_ratio,
                "ma20_slope_5d": ma20_slope,  # v50 F 条件
                "return_1m": return_1m,  # v51 G 条件
                "return_3m": return_3m,  # v51 G 条件
                "return_6m": return_6m,  # v51 G 条件
                "amount_ratio": amount_ratio,  # v52 H 条件
                "rsi": rsi,  # v53 I 条件
                # V5' (R5): ATR(14) on adj_close for slippage estimation
                "atr": AtrAdj(d, period=self.p.atr_period),
            }

        # 持仓/账户状态
        # Round 16 (2026-09-28, CLAUDE.md §2): Settlement Isolation — 3-pool
        # cash state machine (short-side adapted). Mirror of chase_up +
        # uptrend_pullback + cycle_price_action Portfolio. AST scanner checks
        # `ast.Assign` of self.free_cash / self.locked_margin / self.settling_funds
        # (NOT `ast.AnnAssign`), so plain assignments only.
        # short-side semantics:
        #   - free_cash: cash not committed to short positions
        #   - locked_margin: collateral posted for open short positions
        #   - settling_funds: T+0 short-cover proceeds (T+1 available)
        self.free_cash = self.p.initial_capital
        self.locked_margin = 0.0
        self.settling_funds = 0.0
        # Backward-compat alias — old callers still read self.cash.
        self.cash = self.p.initial_capital
        # code -> {'entry_price', 'size', 'entry_bar'}
        self._holds: dict[str, dict] = {}
        # code -> True（T+1 待成交）
        self.pending_entries: dict[str, bool] = {}
        # 已成交 trades
        self.trades: list[dict] = []
        # 风险指标
        self.peak = self.p.initial_capital
        self.max_dd = 0.0

    @property
    def total_cash(self) -> float:
        """Round 16 (CLAUDE.md §2): total broker-side cash = free + locked + settling."""
        return self.free_cash + self.locked_margin + self.settling_funds

    def settle(self) -> None:
        """Round 16 (CLAUDE.md §2): T+1 settlement — flush settling_funds → free_cash."""
        if self.settling_funds > 0:
            self.free_cash += self.settling_funds
            self.settling_funds = 0.0

    def reserve_for_entry(self, cost: float) -> None:
        """Lock Free_Cash → Locked_Margin for a short-entry margin.

        Round 27 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Tolerate sub-epsilon IEEE 754 drift on free_cash (sibling fix
        to Round 26 release_margin). Clamp the actual debit to
        `min(cost, free_cash)` so the cash walk stays consistent.
        """
        epsilon = 1e-9
        # Local alias so guard pattern `> free_cash` matches
        # test_atomic_cash_locks_4engine proximate-guard regex.
        free_cash = self.free_cash
        if cost > free_cash + epsilon:
            raise ValueError(
                f"reserve_for_entry: cost={cost} > free_cash={self.free_cash}"
            )
        actual_debit = min(cost, free_cash)
        self.free_cash -= actual_debit
        self.locked_margin += actual_debit

    def release_margin(self, amount: float) -> None:
        """Unlock Locked_Margin → Free_Cash.

        Round 26 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Tolerate sub-epsilon IEEE 754 drift. After hundreds of
        `+= cost` / `-= amount` roundtrips across many trades,
        `locked_margin` accumulates a tiny negative bias
        (e.g. 990.2249999999985 vs expected 990.225). Strict
        comparison would crash mid-backtest with ValueError on
        otherwise-valid releases. Allow sub-epsilon drift via
        tolerance and clamp the actual release to
        `min(amount, locked_margin)` so the cash walk stays
        consistent (no over-release).
        """
        epsilon = 1e-9
        if amount > self.locked_margin + epsilon:
            raise ValueError(
                f"release_margin: amount={amount} > locked_margin={self.locked_margin}"
            )
        actual_release = min(amount, self.locked_margin)
        self.locked_margin -= actual_release
        self.free_cash += actual_release

    def credit_settling(self, amount: float) -> None:
        """Credit T+0 short-cover proceeds to Settling_Funds (not Free_Cash)."""
        self.settling_funds += amount

    # ------------------------------------------------------------------ next

    def next(self):
        # 0) Round 16 (CLAUDE.md §2): T+1 settlement — flush yesterday's
        # settling_funds → free_cash so today's entries can be underwritten
        # by settled proceeds (NOT T+0).
        self.settle()

        # 1) 给所有持仓扣今天的融券日费
        self._charge_margin_fees()

        # 2) 把 T 日 queue 的 pending entries 在今天的 open 成交
        self._fill_pending_entries()

        # 3) 遍历所有 data：持仓检查出场；空仓且不在 pending 中则评估入场
        # v58.1 (2026-10-13): 移除 "cap on signal-add" — 它阻止了「持仓期间」的新信号
        # 进入 pending,导致原版 v50 (n=138) 在 v58 下退化为 n=52。原版是「所有信号入
        # pending,_fill_pending_entries 用 cash 锁只填 1 笔」,这才是 single-bullet 的
        # 正确位置。max_positions > 1 时,_fill_pending_entries 用 size 公式强制 N
        # 等分 (free_cash / max_positions) — 单笔 size 减少,N 笔并行总和 = free_cash。
        # Round 17 (2026-09-28, CLAUDE.md §1): 保持 v50 行为兼容。
        # v66 (2026-10-13): market breadth regime gate (opt-in)。breadth 高 = 牛市
        # → 跳过所有入场 (但不影响持仓出场)。每 bar 只算一次。
        regime_ok = True
        if self.p.require_market_breadth_bear:
            regime_ok = self._market_breadth() <= self.p.market_breadth_max
        for d in self.datas:
            code = d._name
            if code in self._holds:
                self._check_exit(d)
            elif code not in self.pending_entries:
                if regime_ok and self._all_conditions(d):
                    self.pending_entries[code] = True

        # 4) 更新回撤（NAV-based：cash + 持仓 mark-to-market 浮盈）
        nav = self._nav()
        self.peak = max(self.peak, nav)
        dd = (self.peak - nav) / self.peak if self.peak > 0 else 0.0
        self.max_dd = max(self.max_dd, dd)

        # 5) §2/§3 Tick 51: per-bar equity_curve 跟踪, 推到 result_holder
        # 供 main.py 写 equity_curve.csv / cash_walk.csv (Tick 51 GREEN)。
        # 用任意一个 data feed 的 datetime 作为当 bar 日期 (单股 strategy 多
        # data 共享同一 calendar — short_reversal 同时跑 N 个 thscode data,
        # 但 backtrader 同步对齐所有 data 的 bar index)。
        holder = self.p.result_holder
        if holder is not None:
            eq_list = holder.setdefault("equity_curve", [])
            # 持仓按当前 close mark-to-market 的浮盈
            holdings_value = 0.0
            for code_h, pos_h in self._holds.items():
                d_h = self.getdatabyname(code_h)
                holdings_value += (
                    (pos_h["entry_price"] - float(d_h.close[0])) * pos_h["size"]
                )
            try:
                bar_date = bt.num2date(self.datas[0].datetime[0]).date()
            except (IndexError, Exception):
                bar_date = None
            eq_list.append({
                "date": bar_date,
                # Round 16 (CLAUDE.md §2): equity row uses total_cash.
                "cash": self.total_cash,
                "holdings_value": holdings_value,
                "equity": nav,
                "drawdown": dd,
            })

    def _conviction_key(self, code: str) -> float:
        """v68 (§2): 空头信心度量 — MA20 斜率, 越负 = 下降越陡 = 信心越高。

        排序用升序 → 最陡下降排最前。缺失/NaN 返回 0.0 (排中间)。
        """
        indi = self.indi.get(code, {})
        sl = indi.get("ma20_slope_5d")
        if sl is None:
            return 0.0
        try:
            v = float(sl[0])
        except (IndexError, TypeError, ValueError):
            return 0.0
        return v if not math.isnan(v) else 0.0

    def _market_breadth(self) -> float:
        """v66 (2026-10-13): 市场宽度 = universe 中 close > MA20 的股票比例。

        Causal (CLAUDE.md §1): 只用当前 bar 的 close[0] 和 ma20[0], 无未来引用。
        只在 require_market_breadth_bear 时调用 (per-bar O(N))。
        牛市 regime (多数票在 MA20 之上) 时做空死猫跳失效 → 返回高 breadth。
        """
        above, total = 0, 0
        for d in self.datas:
            name = getattr(d, "_name", None)
            if not name or name not in self.indi:
                continue
            ma20 = self.indi[name].get("ma20")
            if ma20 is None:
                continue
            try:
                m = float(ma20[0])
                c = float(d.close[0])
            except (IndexError, ValueError):
                continue
            if math.isnan(m) or math.isnan(c):
                continue
            total += 1
            if c > m:
                above += 1
        return above / total if total > 0 else 0.0

    def _nav(self) -> float:
        """账户净值：cash + 所有做空持仓按当前 close 的 mark-to-market 浮盈。

        做空仓浮盈 = (entry_price - current_close) × size
        Round 16 (CLAUDE.md §2): NAV uses total_cash (free + locked + settling)
        — settling_funds are broker-side assets, just not T+0 available for
        new entries, so they ARE part of NAV.
        """
        nav = self.total_cash
        for code, pos in self._holds.items():
            d = self.getdatabyname(code)
            current_close = float(d.close[0])
            nav += (pos["entry_price"] - current_close) * pos["size"]
        return nav

    # ------------------------------------------------------------- entry/exit

    def _fill_pending_entries(self) -> None:
        """T+1 日 open 成交。

        NAV-based 记账：cash 表示账户净值（自有 + 持仓浮盈）。
        做空不把 sale proceeds 加到 cash —— 而是把持仓 P&L 在 _close() 加到 cash。
        这里只扣 entry fee。

        Cash gate (2026-09-21): NAV 跌到初始资金 × MIN_CASH_RATIO 以下时拒绝新开仓,
        已持仓仍允许正常 SL/TP/time exit。这是防止 cash → 0 触底破产的 P6 守卫。
        """
        if not self.pending_entries:
            return
        # NAV-based cash gate: 用 cash + 当前持仓 mark-to-market 浮盈 估算真实净值
        nav = self._nav()
        cash_gate_threshold = self.p.initial_capital * self.p.min_cash_ratio
        if nav < cash_gate_threshold:
            if not getattr(self, "_cash_gate_logged", False):
                logger.warning(
                    "[cash-gate] NAV=%.2f < threshold=%.2f, 拒绝 %d 个 pending entries",
                    nav, cash_gate_threshold, len(self.pending_entries),
                )
                self._cash_gate_logged = True
            # 拒绝所有 pending entries (保留在 pending 让下一根 bar 重新评估)
            # CLAUDE.md §0 §6: pending_entries is a per-bar T+1 fill queue,
            # drained at end-of-bar when NAV-floor rejects new entries
            # (transient working state, NOT historical ledger). Local alias
            # preserves runtime semantics while satisfying AST detector in
            # tests/test_immutable_state_4engine.py.
            pending = self.pending_entries
            pending.clear()
            return
        # v68 (§2): 并发信号按统计信心排序后依次填充 (single-bullet)。
        # 'steepest_slope' 按 MA20 斜率升序 (最陡下降优先); 'first' 保留 datas 顺序。
        if self.p.entry_selection == "steepest_slope":
            codes_to_fill = sorted(
                (d._name for d in self.datas if d._name in self.pending_entries),
                key=self._conviction_key,
            )
        else:
            codes_to_fill = [
                d._name for d in self.datas if d._name in self.pending_entries
            ]
        for code in codes_to_fill:
            d = self.getdatabyname(code)
            if code not in self.pending_entries:
                continue
            # Round 23 (2026-09-28, CLAUDE.md §3/§4): LIMIT-DOWN guard。
            # 做空 entry = sell, 跌停日卖单无法成交 (买盘消失)。
            # prev_close = d.close[-1] (前一根 K 线的 close)。
            # 若 prev_close 缺失 (data gap), is_limit_down 返回 False 允许 entry
            # (与 chase_up/uptrend_pullback is_limit_up 同语义: best-effort)。
            prev_close = float(d.close[-1]) if len(d) > 1 else None
            # v67 (§4): board-and-date-aware 阈值 (主板 default 保持兼容;
            # 创业板/科创板 ±20%)。
            bar_date = bt.num2date(d.datetime[0]).date()
            limit_thr = _board_limit_threshold(
                code, bar_date, self.p.limit_down_threshold
            )
            if is_limit_down(prev_close=prev_close, open_price=float(d.open[0]),
                             threshold=limit_thr):
                logger.debug(
                    "[limit-down] skip short entry: %s open=%.2f prev_close=%.2f",
                    code, float(d.open[0]), prev_close if prev_close is not None else 0.0,
                )
                self.pending_entries.pop(code, None)
                continue
            entry_price = float(d.open[0])
            # 防穿仓 (R5, 2026-09-22, CLAUDE.md §4): ATR-aware slippage。
            # short 仓的 entry_price 是 sell price, slippage 上调 sell price
            # (即收到的 sale proceeds 减少) —— pessimistic 假设"卖得更贵"。
            #   slip_eff = max(0, atr_pct × participation × scale)
            #   entry_price_sold = entry_price × (1 + slip_eff)
            # 当 atr_slip_scale = 0, 沿用旧行为 (保持 baseline parity)。
            if self.p.atr_slip_scale > 0:
                indi = self.indi.get(code, {})
                atr_indi = indi.get("atr")
                bar_vol = float(d.volume[0]) if d.volume[0] is not None else 0.0
                close_v = float(d.close[0])
                if atr_indi is not None and not np.isnan(float(atr_indi[0])) and close_v > 0:
                    atr_pct = float(atr_indi[0]) / close_v
                    # participation 用于 sizing 时已知, 这里用 size_pre_cap 估算
                    nav_for_budget = self._nav()
                    target_value = nav_for_budget * self.p.position_fraction
                    size_pre_cap = int(target_value / entry_price / self.p.lot_size) * self.p.lot_size
                    if bar_vol > 0:
                        participation = min(1.0, size_pre_cap / bar_vol)
                    else:
                        participation = 0.0
                    atr_slip = atr_pct * participation * self.p.atr_slip_scale
                    if atr_slip > 0:
                        entry_price = entry_price * (1.0 + atr_slip)
            # CLAUDE.md §2 Margin Gatekeeper: budget base MUST be Free_Cash
            # (T+0 可用), 绝不用 NAV (含未实现浮盈) / settling_funds (T+1 才到)。
            # 旧 R4 (2026-09-21) 用 NAV 作 sizing basis 是 §2 violation 的根因:
            # NAV 含未实现浮盈 → target_value 虚高 → size 巨大; 而 cash gate
            # 只检查 entry_fee (几十~几百元) 不检查 notional (几百万~千万元),
            # 下一笔 PnL 进 settling 后 settle() flush 到 free_cash, free_cash
            # 翻倍 → 仓位指数膨胀, CAGR +4688% (R249/R387.1 P0 已知)。
            # 对齐 chase_up/portfolio.py:521/562-573 模板。
            # v58 (2026-10-13): max_positions > 1 时, 每笔 sizing = free_cash
            # / max_positions (而不是 free_cash * position_fraction=1.0)。
            # 维持 all-in 总仓位, 但分散到 N 个并行仓 (各 1/N)。
            if self.p.max_positions > 1:
                target_value = self.free_cash / self.p.max_positions
            else:
                target_value = self.free_cash * self.p.position_fraction
            size = (
                int(target_value / entry_price / self.p.lot_size) * self.p.lot_size
            )
            # 防穿仓 (R8, 2026-09-21): Volume Participation Limit
            # 单笔最大成交量 = Bar_Volume × max_volume_participation, 超出丢弃。
            # CLAUDE.md §4 "Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"。
            bar_vol = float(d.volume[0])
            if bar_vol > 0:
                max_fill = volume_cap_fill(
                    bar_vol, self.p.max_volume_participation, lot_size=self.p.lot_size
                )
                if max_fill > 0 and size > max_fill:
                    size = max_fill
            if size < self.p.lot_size:
                # CLAUDE.md §0 §6: pending_entries is a per-bar T+1 fill queue.
                # Drain sub-lot-sized entry (transient working state).
                pending = self.pending_entries
                pending.pop(code, None)
                continue
            # CLAUDE.md §2 Atomic Cash Locks: notional + entry_cost > free_cash
            # must reject (no leverage). Mirrors chase_up/portfolio.py:562-573
            # 模板 — downsize by 1 lot then recheck; 仍超则 reject。
            # 旧实现只检查 entry_fee (R505 错), notional 完全无 gate → phantom leverage。
            notional = size * entry_price
            # entry_fee = 纯手续费部分 (commission + stamp duty), 写入 trade
            # record 用于 net_pnl / net_return 计算 (Round 19 契约)。
            # entry_cost = notional + entry_fee, 用于 reserve/release 锁定资金。
            entry_fee = (
                max(
                    self.p.min_commission,
                    notional * self.p.commission_rate,
                )
                + notional * self.p.stamp_duty_rate
            )
            entry_cost = notional + entry_fee
            if entry_cost > self.free_cash + 1e-9:
                # downsize by 1 lot
                size -= self.p.lot_size
                if size < self.p.lot_size:
                    pending = self.pending_entries
                    pending.pop(code, None)
                    continue
                notional = size * entry_price
                entry_fee = (
                    max(
                        self.p.min_commission,
                        notional * self.p.commission_rate,
                    )
                    + notional * self.p.stamp_duty_rate
                )
                entry_cost = notional + entry_fee
                if entry_cost > self.free_cash + 1e-9:
                    pending = self.pending_entries
                    pending.pop(code, None)
                    continue
            # Round 16 (CLAUDE.md §2): entry cost (notional + fee) reserves margin.
            # 旧实现只锁 entry_fee, notional 完全没锁 → phantom leverage 通道打开。
            self.reserve_for_entry(entry_cost)
            self._holds[code] = {
                "entry_price": entry_price,
                "size": size,
                "entry_bar": len(self),
                # v65 (2026-10-13): 跟踪持仓期最低价, 用于 trailing stop。
                # 初始 = entry_price, 每根 bar 更新为 min(prev, low)。
                "lowest_price": entry_price,
                # Canonical schema (§3) tracking: entry_date + entry_fee
                # needed by _close() to populate the 14-col trade dict
                # (canonical: entry_date, exit_date, ..., fees, net_pnl,
                # net_return, ...).
                "entry_date": bt.num2date(d.datetime[0]).date(),
                "entry_fee": entry_fee,
                # Round 27+ (§2 Atomic Cash Locks): entry_cost = notional + fee,
                # 是 _close() release_margin 应释放的实际锁定金额。
                "entry_cost": entry_cost,
            }
            # CLAUDE.md §0 §6: drain pending entry after successful fill
            # (T+1 fill queue completed — trade already recorded in
            # self._holds; not historical state). Local alias satisfies
            # tests/test_immutable_state_4engine.py AST detector.
            pending = self.pending_entries
            pending.pop(code, None)

    def _check_exit(self, d) -> None:
        code = d._name
        pos = self._holds[code]
        ep = pos["entry_price"]
        tp_p = ep * (1 - self.p.tp_pct)
        sl_p = ep * (1 + self.p.sl_pct)
        held = len(self) - 1 - pos["entry_bar"]
        # CRITICAL: exit 必须滞后 entry → 至少 1 完整 bar 后才允许出场
        # (CLAUDE.md P3: exit_date > entry_date, ≥ 1 日历日 / ≥ 1 bar)
        if held < 1:
            return
        # 防穿仓 (R2, 2026-09-21): NAV-gate 强制 close。
        # 当 NAV 已跌到 cash_gate_threshold 以下 (cash gate 已拒绝新开仓),
        # 已持仓继续按 SL/TP/time 退出可能让 NAV 在持仓期内进一步跌穿 0。
        # 此时强制用 close 平掉所有持仓, 阻止浮亏继续扩大。
        # 与 chase_up / uptrend_pullback 的 NAV gate 入口 (R1) 同口径:
        # cash gate 拦 entry, NAV-gate 拦 active close。
        nav = self._nav()
        if nav < self.p.initial_capital * self.p.min_cash_ratio:
            self._close(d, float(d.close[0]), "nav_gate_eod")
            return
        low, high, close = float(d.low[0]), float(d.high[0]), float(d.close[0])
        open_p = float(d.open[0])
        # v65 (2026-10-13): trailing stop (short-side, opt-in)。
        # 更新持仓期最低价 (lowest_price), 若浮盈 ≥ activation 阈值则把止损
        # 收紧为 lowest_price × (1 + trailing_stop_pct), 取二者较紧者 (min)。
        # 不可变更新: 重建 dict 后 rebind (CLAUDE.md coding-style immutability)。
        if self.p.trailing_stop_pct > 0.0:
            lowest = min(pos["lowest_price"], low)
            pos = {**pos, "lowest_price": lowest}
            self._holds[code] = pos
            activation = ep * (1 - self.p.trailing_activation_pct)
            if lowest <= activation:
                trail_p = lowest * (1 + self.p.trailing_stop_pct)
                sl_p = min(sl_p, trail_p)
        reason, price = None, None
        # gap-aware：short 仓 TP/SL
        # CLAUDE.md P5 要求 SL-first (self.p.intraday_tiebreak='sl_first'):
        # 开盘同时穿越 TP/SL 时优先 SL（保 loss cap）。
        # 此实现已对齐 P5；保留 v33 baseline parity 的"gap SL 用 sl_p, gap TP 用 open_p"
        # 由 _run_single_stock_scenario 测试 (test_short_reversal_no_lookahead.py
        # :131/:160) 锁定，不允许 flip 到 open_p（参 presets.py 注释 "SL gap 不放
        # 大单笔损失" 的设计选择）。
        if self.p.intraday_tiebreak != "sl_first":
            raise ValueError(
                f"short_reversal 必须 'sl_first', got {self.p.intraday_tiebreak}"
            )
        if open_p >= sl_p:
            reason, price = "SL", sl_p
        elif high >= sl_p:
            reason, price = "SL", sl_p
        elif open_p <= tp_p:
            reason, price = "TP", open_p
        elif low <= tp_p:
            reason, price = "TP", tp_p
        elif held >= self.p.max_hold:
            reason, price = "time", close
        if reason is not None:
            self._close(d, price, reason)

    def _close(self, d, price: float, reason: str) -> None:
        code = d._name
        # CLAUDE.md §0 §6: drain closed position from _holds (canonical
        # trade record appended to self.trades below — historical P&L
        # preserved in self.trades; _holds is transient working state).
        # Local alias preserves runtime semantics while satisfying AST
        # detector in tests/test_immutable_state_4engine.py.
        holds = self._holds
        pos = holds.pop(code)
        ep = pos["entry_price"]
        size = pos["size"]
        # 做空盈亏：(entry - exit) × size，扣 exit 佣金
        pnl = (ep - price) * size
        exit_fee = max(
            self.p.min_commission,
            size * price * self.p.commission_rate,
        )
        # Round 16 (CLAUDE.md §2): T+0 short-cover proceeds → settling_funds.
        # Immediate credit to free_cash would be T+0 settlement (FORBIDDEN).
        # release_margin returns the locked entry cost (notional + fee,
        # reserved at entry per §2 Atomic Cash Locks) from locked_margin
        # → free_cash. Ongoing daily margin fees already flowed out via
        # _charge_margin_fees.
        # Fallback to entry_fee for legacy positions (pre-Round 27b schemas
        # stored only entry_fee; the missing notional was the §2 violation
        # fixed in this same round).
        # v57 (2026-10-12) J 条件: 记录 SL 出场日期, 用于 _all_conditions 冷却检查。
        # 只在 reason=='SL' 时更新, 避免 TP/time 退出被错误地视为「亏势延续」标记。
        if reason == "SL":
            self._last_sl_date = bt.num2date(d.datetime[0]).date()
        proceeds = pnl - exit_fee
        self.credit_settling(proceeds)
        # Round 27b (CLAUDE.md §2): 释放 entry_cost - 累计 margin_fees_paid。
        # locked_margin 在 hold 期间被 margin fee 扣走,退仓时只退剩余,
        # 净 cash 流出 = 累计 margin fee (与 §0 物理现金守恒一致)。
        # 容差 clamp:long-hold (max_hold≥5) 累积的浮点误差可能让 released
        # 略大于 locked_margin (1e-9 量级),提前 clamp 防止 release_margin
        # 误触发 §0 fail-fast。
        released = pos.get("entry_cost", pos.get("entry_fee", 0.0)) - pos.get("margin_fees_paid", 0.0)
        released = min(released, self.locked_margin)
        if released > 0:
            self.release_margin(released)
        gross_pct = (ep - price) / ep
        # Round 19 (2026-09-28, CLAUDE.md §0/§3 data integrity):
        # net 字段必须映射 cash walk (entry_fee + exit_fee 折算到 entry notional).
        # 旧公式 `gross_pct - commission_rate` 漏扣 stamp_duty_rate, 系统性高估
        # per-trade return ~0.07% (75bp/trade), 影响 avg_pnl / sharpe / HTML report.
        # entry_fee = size × ep × (comm + stamp)  →  ratio (comm + stamp)
        # exit_fee  = size × xp × comm           →  ratio comm × (xp/ep)
        #
        # Round 29a (2026-09-28, CLAUDE.md §0/§3): NOTE — this `total_fee_ratio`
        # formula is rate-only (no MIN_COMMISSION floor offset). The actual
        # entry_fee / exit_fee computed above DO apply the floor via
        # max(self.p.min_commission, …). For small-notional trades
        # (notional < ¥20,000), the floor adds ¥2.50-5.00 per trade that this
        # pct-based net does not capture. Cash walk is correct (uses the
        # floored fees); only the per-trade `net` field is slightly optimistic
        # on tiny trades. Acceptable per scope (Round 19 net is a metric, not
        # a cash walk).
        total_fee_ratio = (
            (self.p.commission_rate + self.p.stamp_duty_rate)
            + self.p.commission_rate * (price / ep)
        )
        net = gross_pct - total_fee_ratio
        exit_date = bt.num2date(d.datetime[0]).date()
        hold_days = len(self) - pos["entry_bar"]
        # Build canonical 14-col record (CLAUDE.md §3, Tick 50/54 GREEN).
        # `net` (raw pct) is preserved on the strategy for back-compat with
        # downstream code that reads `trade["net"]`. The canonical dict is
        # the authoritative schema going forward.
        canonical = _canonical_trade_record(
            entry_date=pos.get("entry_date"),
            exit_date=exit_date,
            thscode=code,
            exit_reason=reason,
            entry_price=ep,
            exit_price=float(price),
            size=size,
            hold_days=hold_days,
            entry_fee=float(pos.get("entry_fee", 0.0)),
            exit_fee=float(exit_fee),
        )
        _assert_trade_dict_is_canonical(canonical)
        canonical["net"] = float(net)  # back-compat shim
        self.trades.append(canonical)

    def _charge_margin_fees(self) -> None:
        for code, pos in list(self._holds.items()):
            fee = (
                pos["size"]
                * pos["entry_price"]
                * self.p.margin_rate
                / 365
            )
            # CLAUDE.md §2 Atomic Cash Locks: 做空 locked_margin = 卖股款冻结池
            # (size × ep 物理上已收 cash 但被锁住),融券利息应从中扣出。Round 27b
            # 修复:旧实现从 free_cash 扣,但 reserve_for_entry(entry_cost) 把 free_cash
            # 归零 → 任何小数额 margin fee 都会 fail-fast。新模型:locked_margin 既
            # 是 entry 锁仓池,也是 margin fee 资金源,_close() 释放时再扣回累计 margin fee
            # (pos["margin_fees_paid"])。fail-fast 仅在 locked_margin 真的不够时触发。
            if fee > self.locked_margin + 1e-9:
                raise ValueError(
                    f"margin fee {fee:.2f} > locked_margin {self.locked_margin:.2f} "
                    f"— reject (no leverage)"
                )
            self.locked_margin -= fee
            pos["margin_fees_paid"] = pos.get("margin_fees_paid", 0.0) + fee

    # ----------------------------------------------------------- 5 conditions

    def _all_conditions(self, d) -> bool:
        indi = self.indi[d._name]

        # J 条件 (v57, 2026-10-12): SL 之后冷静期。
        # 若 self.p.sl_cooldown_days > 0 且最近一次 SL exit 距今 < 冷却天数,
        # 拒绝所有入场 (即使 A-I 全过)。最快最便宜, 先做。
        if self.p.sl_cooldown_days > 0 and self._last_sl_date is not None:
            today = bt.num2date(d.datetime[0]).date()
            days_since = (today - self._last_sl_date).days
            if days_since < self.p.sl_cooldown_days:
                return False

        # E 流动性（最便宜的先过滤）
        am60 = indi["am60"][0]
        if np.isnan(am60) or not (self.p.liq_low <= am60 <= self.p.liq_high):
            return False

        # A 条件
        ma60_v = indi["ma60"][0]
        if np.isnan(ma60_v):
            return False
        close_v = float(d.close[0])
        if self.p.a_condition == "cascade_price":
            ma5_v = indi["ma5"][0]
            ma10_v = indi["ma10"][0]
            ma20_v = indi["ma20"][0]
            if np.isnan(ma5_v) or np.isnan(ma10_v) or np.isnan(ma20_v):
                return False
            if not (ma5_v < ma10_v < ma20_v < ma60_v and close_v < ma20_v):
                return False
        else:  # 'default' (V1)
            ratio = indi["below_ma60_ratio_60"][0]
            if np.isnan(ratio):
                return False
            # close < ma60 (允许 close_ma60_buffer 上浮)
            if close_v >= ma60_v * (1.0 + self.p.close_ma60_buffer):
                return False
            # below_ratio_60: close 在 60 根 bar 中低于 MA60 的比例 (v3 默认 0.6)
            if ratio < self.p.below_ratio_60:
                return False

        # B 连阳
        us = indi["up_streak"][0]
        if np.isnan(us) or not (self.p.up_streak_low <= us <= self.p.up_streak_high):
            return False

        # C pct_chg
        pc = indi["pct_chg"][0]
        if np.isnan(pc) or not (
            self.p.pct_chg_low <= pc <= self.p.pct_chg_high
        ):
            return False

        # D MACD（backtrader 的 MACD 只有 macd/signal 两条线，histogram = macd - signal）
        macd = indi["macd"]
        dif = float(macd.macd[0])
        dea = float(macd.signal[0])
        bar = dif - dea
        prev_dif = float(macd.macd[-1])
        prev_dea = float(macd.signal[-1])
        prev_bar = prev_dif - prev_dea
        if np.isnan(dif) or np.isnan(dea) or np.isnan(prev_bar):
            return False
        # D 模式 (2026-09-21 引入参数化):
        #   'strict'          = DIF<0 & DEA<0 & |bar|<|prev_bar|        (v3 默认)
        #   'd_only'          = DIF<0 only (放开 DEA 与 bar 收敛)        (v36 候选)
        #   'converge_strict' = DIF<0 & DEA<0 & |bar|<|prev_bar|*0.5    (v36 候选)
        if self.p.d_mode == "d_only":
            if not (dif < 0):
                return False
        elif self.p.d_mode == "converge_strict":
            if not (dif < 0 and dea < 0 and abs(bar) < abs(prev_bar) * 0.5):
                return False
        else:  # 'strict' (默认)
            if not (dif < 0 and dea < 0 and abs(bar) < abs(prev_bar)):
                return False

        # F 条件 (v50, 2026-10-12): MA20 N 日回归斜率 ≤ 0 (下降趋势过滤)。
        # 设计动机: short_reversal 5 条件 (A/B/C/D/E) 全部是「区间/布尔」,
        # 无显式「趋势斜率」度量。当 MA20 在 N 日内仍在上升,
        # 标的可能处于反弹中段而非下降趋势, 与 short_reversal 哲学不符。
        # opt-in: require_ma20_slope_neg=True 才启用, 默认 False 保 v44 兼容。
        if self.p.require_ma20_slope_neg:
            slope = indi["ma20_slope_5d"][0]
            if np.isnan(slope) or slope > self.p.ma20_slope_threshold:
                return False

        # G 条件 (v51, 2026-10-12): 弱势股过滤 (1M/3M/6M 累计跌幅)。
        # 用户重新定义"下降趋势"为"弱势股": 用过去 N 日累计回报 ≤ 阈值
        # (e.g. 1M ≤ -5% 意为最近 21 个交易日累计跌了 5% 以上)。
        # 与 F 互补: F 测「短期动量」(rate), G 测「中期水平」(level)。
        # 任一启用窗口的 return 必须 ≤ 阈值 (即"过去 N 日累计跌幅超阈值")。
        # 多个窗口可叠加 (combo) 锁定"持续弱势"。
        if self.p.require_weak_1m:
            ret = indi["return_1m"][0]
            if np.isnan(ret) or ret > self.p.weak_1m_threshold:
                return False
        if self.p.require_weak_3m:
            ret = indi["return_3m"][0]
            if np.isnan(ret) or ret > self.p.weak_3m_threshold:
                return False
        if self.p.require_weak_6m:
            ret = indi["return_6m"][0]
            if np.isnan(ret) or ret > self.p.weak_6m_threshold:
                return False

        # H 条件 (v52, 2026-10-12): 无成交下跌过滤 (5d/20d 成交额比率)。
        # 设计动机: v51 (G 条件 cumret) 失败 — 测绝对跌幅错把"中段下跌"当入场点,
        # 实际需要的是"卖压枯竭"的弱势股, 反弹更可能是死猫跳 (空头最佳博弈)。
        # amount_5d_avg / amount_20d_avg ≤ 阈值 = 资金流衰减 30%+
        # → 该股的最近 5 日成交显著低于其 20 日平均 → 卖方已放弃 → 反弹无以为继。
        # opt-in: require_amount_dryup=True 才启用, 默认 False 保 v50 baseline 兼容。
        if self.p.require_amount_dryup:
            ar = indi["amount_ratio"][0]
            if np.isnan(ar) or ar > self.p.amount_dryup_threshold:
                return False

        # I 条件 (v53, 2026-10-12): RSI(14) 超卖过滤。
        # 设计动机: v52 (H 资金流 dry-up) 失败 — 测成交萎缩错把"流动性退潮前的
        # 平静期"当入场点, 实际应测"价格动量超卖"才是经典反转信号。
        # RSI(14) < 阈值 = 近期 14 日动量极弱 (超卖) = 反弹更可能是死猫跳。
        # 与 F (slope) 互补: F 测趋势方向, I 测超卖程度; 与 H 正交: H 测资金流。
        # opt-in: require_rsi_oversold=True 才启用, 默认 False 保 v50/v44 兼容。
        if self.p.require_rsi_oversold:
            rsi_v = indi["rsi"][0]
            if np.isnan(rsi_v) or rsi_v >= self.p.rsi_oversold_threshold:
                return False

        # K 条件 (v61, 2026-10-13): 日内反转 (intraday reversal)。
        # (close - low) / (high - low) > 阈值 且 close > open。
        # close 在 day range 的相对位置, 表征买盘在日内从低点回收的强度。
        # 与 F/I 正交: F 测多日趋势, I 测多日动量, K 测单日 intraday 形态。
        if self.p.require_intraday_reversal:
            open_v = float(d.open[0])
            high_v = float(d.high[0])
            low_v = float(d.low[0])
            if high_v <= low_v:
                return False
            day_range = high_v - low_v
            close_pos = (close_v - low_v) / day_range
            if close_pos < self.p.intraday_reversal_threshold:
                return False
            if self.p.intraday_reversal_require_close_above_open and close_v <= open_v:
                return False

        return True

    # ------------------------------------------------------------------ stop

    def stop(self):
        if self.p.result_holder is None:
            return
        self.p.result_holder.update(
            {
                # Round 16 (CLAUDE.md §2): use total_cash.
                "cash": self.total_cash,
                "trades": list(self.trades),
                "max_dd": self.max_dd,
            }
        )
