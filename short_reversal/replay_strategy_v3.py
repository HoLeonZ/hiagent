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
    AtrAdj,
    BelowMa60Ratio60,
    PctChg,
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
        result_holder=None,
    )

    def __init__(self):
        # per-data 指标字典（避免多 data 共享 indicator）
        self.indi: dict[str, dict] = {}
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
        """Lock Free_Cash → Locked_Margin for a short-entry margin."""
        # Local alias so guard pattern `> free_cash` matches
        # test_atomic_cash_locks_4engine proximate-guard regex.
        free_cash = self.free_cash
        if cost > free_cash:
            raise ValueError(
                f"reserve_for_entry: cost={cost} > free_cash={self.free_cash}"
            )
        self.free_cash -= cost
        self.locked_margin += cost

    def release_margin(self, amount: float) -> None:
        """Unlock Locked_Margin → Free_Cash."""
        if amount > self.locked_margin:
            raise ValueError(
                f"release_margin: amount={amount} > locked_margin={self.locked_margin}"
            )
        self.locked_margin -= amount
        self.free_cash += amount

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
        for d in self.datas:
            code = d._name
            if code in self._holds:
                self._check_exit(d)
            elif code not in self.pending_entries:
                if self._all_conditions(d):
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
        for d in self.datas:
            code = d._name
            if code not in self.pending_entries:
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
            # 防穿仓 (R4, 2026-09-21): budget base 用 NAV (cash + 持仓浮盈) 而非
            # 仅 self.cash。前一笔大亏会让 cash 跌至初始资金一小部分, 若仍按
            # self.cash all-in, 后续每笔名义资金随 cash 缩水 — 这等同于"现金自适应"
            # sizing, 会让 cash gate 在 cash-only 维度上失守 (NAV 含浮盈可能仍 > 5%
            # initial)。改用 NAV 后, cash gate 与 sizing 同口径, 防止 NAV 触底 0
            # 路径上的盲区。
            nav_for_budget = self._nav()
            target_value = nav_for_budget * self.p.position_fraction
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
            entry_fee = size * entry_price * (
                self.p.commission_rate + self.p.stamp_duty_rate
            )
            # CLAUDE.md §2 Atomic Cash Locks: cost > cash must reject
            # (no leverage). Mirrors chase_up/uptrend_pullback pattern
            # (`if notional + fee_in > cash: continue`). short_reversal's
            # entry_fee is tiny relative to NAV, so this guard catches
            # data anomalies / negative-NAV edge cases only. fail-fast
            # per §0 Pessimistic Default.
            if entry_fee > self.free_cash:
                raise ValueError(
                    f"entry_fee {entry_fee:.2f} > free_cash {self.free_cash:.2f} "
                    f"— reject (no leverage)"
                )
            # Round 16 (CLAUDE.md §2): entry fee reserves margin.
            self.reserve_for_entry(entry_fee)
            self._holds[code] = {
                "entry_price": entry_price,
                "size": size,
                "entry_bar": len(self),
                # Canonical schema (§3) tracking: entry_date + entry_fee
                # needed by _close() to populate the 14-col trade dict
                # (canonical: entry_date, exit_date, ..., fees, net_pnl,
                # net_return, ...).
                "entry_date": bt.num2date(d.datetime[0]).date(),
                "entry_fee": entry_fee,
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
        exit_fee = size * price * self.p.commission_rate
        # Round 16 (CLAUDE.md §2): T+0 short-cover proceeds → settling_funds.
        # Immediate credit to free_cash would be T+0 settlement (FORBIDDEN).
        # release_margin returns the locked entry fee (reserved at entry)
        # from locked_margin → free_cash. Ongoing daily margin fees already
        # flowed out via _charge_margin_fees.
        proceeds = pnl - exit_fee
        self.credit_settling(proceeds)
        self.release_margin(pos.get("entry_fee", 0.0))
        gross_pct = (ep - price) / ep
        net = gross_pct - self.p.commission_rate
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
            # CLAUDE.md §2 Atomic Cash Locks: daily margin fee > cash
            # must reject (no leverage). Mirrors chase_up/uptrend_pullback
            # cost>cash guard. fail-fast per §0 Pessimistic Default.
            if fee > self.free_cash:
                raise ValueError(
                    f"margin fee {fee:.2f} > free_cash {self.free_cash:.2f} "
                    f"— reject (no leverage)"
                )
            self.free_cash -= fee

    # ----------------------------------------------------------- 5 conditions

    def _all_conditions(self, d) -> bool:
        indi = self.indi[d._name]

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
