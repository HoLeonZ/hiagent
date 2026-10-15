"""Single-position state machine for cycle_price_action.

Hard P3 contract:
    try_exit raises if the exit date equals the entry date — same-day exit
    is forbidden under A-share T+1 settlement, no matter what the price is.

R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4).
    try_enter takes optional bar_volume; when provided, cap shares at
    Bar_Volume × 0.10 (rounded down to lots). bar_volume=None preserves
    pre-R8 behaviour for back-compat tests.

V6'' (2026-09-22, CLAUDE.md §4): SL-first intraday tiebreak.
    try_exit_with_intraday_check(open, high, low, close, exit_date, tp_pct, sl_pct)
    performs daily-bar worst-case exit decision:
      1. open <= sl_p → SL @ open (gap-down through stop)
      2. open >= tp_p → TP @ open (gap-up through target)
      3. low  <= sl_p → SL @ sl_p (intraday stop triggered)
      4. high >= tp_p → TP @ tp_p (intraday target triggered)
      5. else         → close @ close (no trigger, time/bar exit)
    SL-first ordering (worst-case) when both SL+TP would have triggered in
    the same bar — matches chase_up / uptrend_pullback / short_reversal
    semantics per CLAUDE.md §4 "On daily bar data, if BOTH the Stop-Loss
    and Take-Profit limits are breached within the same bar, the engine
    MUST assume the worst-case scenario (Stop-Loss hit first)".

    try_exit(fill_price) is preserved as legacy direct-fill API for
    callers that have already pre-computed exit price externally.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping

# Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical cost rates imported from
# core/dual_price.py single-source-of-truth. (was 0.001 = 万10 pre-Aug2023).
from core.corporate_actions import apply_corporate_action
from core.dual_price import is_limit_up
from core.preset_contract import ALL_IN, EXECUTION_PRICE_SOURCE

logger = logging.getLogger(__name__)
from core.dual_price import (
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,
)


def _is_nan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)


@dataclass(frozen=True)
class PositionState:
    thscode: str
    shares: int
    entry_price: float
    entry_date: date
    decision_meta: Mapping[str, Any]


class Portfolio:
    """Single-position book-keeping. Lot size = 100 shares. ¥5 commission floor.

    Position sizing: 100% all-in per trade (project-wide policy — see
    CLAUDE.md §2; risk is absorbed by per-trade SL + ATR exit rather than a
    pre-trade cash buffer). Cash gate: never let `cost > cash` (no borrowing
    / no leverage).
    """

    # §2 (audit P2-11, 2026-10-15): 类属性改为**引用**核心单源,不再写死字面量
    # (此前虽有 import,却在类体里又用字面量覆盖了一遍 —— 导入的名字被遮蔽)。
    COMMISSION_RATE = COMMISSION_RATE
    MIN_COMMISSION = MIN_COMMISSION
    # canonical 万5 post-Aug2023 rate(旧值 0.001 = 万10 pre-Aug2023 历史值)。
    # Sell-side only.
    STAMP_TAX_SELL = STAMP_DUTY_RATE
    # Project policy: every entry is all-in (CLAUDE.md §2, revised 2026-09-21).
    # Held at 1.0 explicitly so the constant survives for callers/tests.
    MAX_POSITION_PCT = 1.0
    # §2 (audit 2026-10-15): 本账本的**物理**容量 —— 同一时刻只持 1 仓
    # (`try_enter` 以 `if self._pos is not None: return None` 表达)。
    # preset 声明的 max_positions 必须与之相等,否则 fail-fast。
    MAX_POSITIONS_CAPACITY = 1
    # R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
    # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
    # 与 chase_up/portfolio.py:49 / short_reversal/replay_strategy_v3.py 口径一致,
    # 防止小票大单砸穿市场。bar_volume is optional for backwards compatibility;
    # when None or NaN the cap is skipped (test fixtures without volume column)。
    # 2026-10-15: 保留为**模块级参考值**;实际参与率由 preset 声明的
    # `max_volume_participation` 经 __init__ 注入(self.max_volume_participation),
    # 不再由本常量驱动 —— 此前 PRESET_V1 声明了它却无人读取。
    MAX_VOL_PARTICIPATION = 0.10

    # Round 10 (2026-09-28, CLAUDE.md §2): NAV-floor cash gate threshold。
    # 当 NAV (cash + 持仓 mark-to-market 浮盈) 跌到 initial_capital ×
    # NAV_GATE_RATIO 以下时, 拒绝新开仓 — 已持仓仍按 SL/TP/time exit 正常执行。
    # 与 chase_up/portfolio.py:56 + uptrend_pullback/portfolio.py:49 +
    # short_reversal/replay_strategy_v3.py:156 (min_cash_ratio=0.05) 口径一致。
    NAV_GATE_RATIO = 0.05

    def __init__(
        self,
        cash: float,
        # Round 15, 2026-09-28, CLAUDE.md §4 Intraday tiebreak policy
        # — placed before the 1M and atr_slip comments so the audit
        # signature scan captures the param name. Defaults to 'sl_first'
        # = back-compat, see try_exit_with_intraday_check validation.
        # Tick 39 closes the 181st dropped preset key.
        intraday_tiebreak: str = "sl_first",
        # Round 10 (2026-09-28, CLAUDE.md §2): NAV gate anchor.
        # 与 chase_up/portfolio.py:121 + short_reversal/replay_strategy_v3.py:154
        # (initial_capital=1_000_000.0) 口径一致, 防止多仓策略在反复 gap-down
        # 击穿 SL 后继续 all-in 累积亏损直到穿仓 0。
        # §4 (audit P3, 2026-10-15): 涨跌停守卫属**执行层**,归 Portfolio。
        # 此前它在 strategy 层(backtrader_engine.next 里 inflight 检查),而
        # 另外三个引擎都在 portfolio 层 —— §6 单层归属要求一个规则只有一处归属。
        is_limit_up_threshold: float = 0.095,
        initial_capital: float = 1_000_000.0,
        # R5' (2026-09-23, CLAUDE.md §4): ATR-aware slippage opt-in.
        # When atr_slip_scale > 0, slippage = max(0, atr_pct × participation × scale)
        # is added on top of commission + tax. Default 0.0 = no slippage (back-compat).
        atr_slip_scale: float = 0.0,
        # §4 (audit 2026-10-15, §0/§6 conformance): 成交量参与率上限。
        # 此前本引擎把 0.10 写成类常量 MAX_VOL_PARTICIPATION,而 PRESET_V1 声明的
        # `max_volume_participation=0.10` **从未被读取** —— 声明与常量同值,于是
        # 改预设不会有任何效果。现在由声明驱动。
        max_volume_participation: float = 0.10,
        # §2 (audit 2026-10-15): preset 声明的仓位比例。此前从不被读取。
        # 1.0 = 全仓政策;该值只**缩小**预算,余下仍受 free_cash 保证金闸门约束。
        position_fraction: float = 1.0,
        # §3 (audit 2026-10-15): 执行域价源声明。本组合的成交价/成交量全部来自
        # v_daily(原始价),指标域才走 adj_close —— 见 data_feed 的 LEFT JOIN。
        price_source_for_execution: str = "raw_close",
        # §2 (audit 2026-10-15): 这两项此前**声明了却无任何消费者**。本组合是
        # 单仓 all-in 账本,结构上无法多仓、也无法预留现金缓冲 —— 所以"消费"它们
        # 的正确形态是**核对声明与容量的兼容性**:声明 2 仓或 'equal' 时必须炸,
        # 而不是静默按 1 仓 all-in 跑完。这与 §3 价源声明同一纪律。
        max_positions: int = 1,
        position_sizing: str = "all_in",
    ) -> None:
        # Round 16 (2026-09-28, CLAUDE.md §2): Settlement Isolation — 3-pool
        # cash state machine. Mirror of chase_up/portfolio.py + uptrend_pullback.
        # AST scanner checks for `ast.Assign` of self.free_cash / self.locked_margin /
        # self.settling_funds (NOT `ast.AnnAssign`), so plain assignments only.
        self.free_cash = float(cash)
        self.locked_margin = 0.0
        self.settling_funds = 0.0
        # Backward-compat alias — old callers still read self.cash.
        # Returns total_cash (= free + locked + settling), preserves pre-Round 16
        # semantics where self.cash represented broker-side total funds.
        self.cash = float(cash)
        self.initial_capital = float(initial_capital)
        self.atr_slip_scale = atr_slip_scale
        self.is_limit_up_threshold = float(is_limit_up_threshold)
        self.intraday_tiebreak = intraday_tiebreak
        # §4 (audit 2026-10-15): 参与率上限由声明驱动(不再读类常量)。
        self.max_volume_participation = float(max_volume_participation)
        # §2 (audit 2026-10-15): 仓位比例由声明驱动。
        self.position_fraction = float(position_fraction)
        # §3 (audit 2026-10-15): 执行域必须是原始价。本组合没有 adj 执行路径 ——
        # 声明 adj_close 等于一句无人兑现的承诺,故 fail-fast 而非静默按 raw 执行。
        if price_source_for_execution != EXECUTION_PRICE_SOURCE:
            raise ValueError(
                f"§3: price_source_for_execution={price_source_for_execution!r} "
                f"不被本执行层支持(只有 {EXECUTION_PRICE_SOURCE!r})。"
                "SL/TP/成交量/记账必须建立在原始价上。"
            )
        self.price_source_for_execution = price_source_for_execution
        # §2 (audit 2026-10-15): 容量核对 —— 本账本同一时刻只持 1 仓。
        if max_positions != self.MAX_POSITIONS_CAPACITY:
            raise ValueError(
                f"§2: preset 声明 max_positions={max_positions},但本组合的物理容量是 "
                f"{self.MAX_POSITIONS_CAPACITY}(单仓账本)。声明超出容量 = 静默忽略。"
            )
        self.max_positions = int(max_positions)
        # §2 (audit 2026-10-15): sizing 模式核对 —— 本账本只实现 all-in 分支。
        if position_sizing != ALL_IN:
            raise ValueError(
                f"§2: preset 声明 position_sizing={position_sizing!r},但本组合只实现 "
                f"{ALL_IN!r}。"
            )
        self.position_sizing = position_sizing
        self._pos: PositionState | None = None
        self.closed_trades: list[dict] = []

    @property
    def total_cash(self) -> float:
        """Round 16 (CLAUDE.md §2): total broker-side cash = free + locked + settling."""
        return self.free_cash + self.locked_margin + self.settling_funds

    def settle(self) -> None:
        """Round 16 (CLAUDE.md §2): T+1 settlement — flush settling_funds → free_cash.

        A-share T+1 rule: proceeds from a T sell are physically broker-side
        assets at T+1 (not T). Calling this at the start of each bar frees
        yesterday's settles for today's entries.
        """
        if self.settling_funds > 0:
            self.free_cash += self.settling_funds
            self.settling_funds = 0.0

    def reserve_for_entry(self, cost: float) -> None:
        """Lock Free_Cash → Locked_Margin for a buy fill.

        Round 28 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Tolerate sub-epsilon IEEE 754 drift on free_cash (sibling fix
        to Round 26 release_margin for short_reversal and Round 27
        for short_reversal reserve). Clamp the actual debit to
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
        """Unlock Locked_Margin on position close.

        §2 (audit P0-2, 2026-10-15): **不再**把解锁额记入 Free_Cash。
        原实现 `self.free_cash += actual_release` 与另外三个引擎
        (chase_up/portfolio.py:154、uptrend_pullback/portfolio.py:127)的
        约定相反,配合出场路径的 `credit_settling(全额卖出款)` 会把同一个
        入场本金记两次 —— 一轮完整往返后 total_cash 多出一个本金
        (100 → 入场 30 → 出场得款 33 应得 103,实际 133)。

        正确语义:release 只是把 locked 桶解冻,仓位价值由出场时的
        `credit_settling(卖出款)` 承载(卖出款已包含本金返还)。

        Round 28 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Tolerate sub-epsilon IEEE 754 drift on locked_margin.
        Clamp the actual release to `min(amount, locked_margin)`
        so cash walk stays consistent.
        """
        epsilon = 1e-9
        if amount > self.locked_margin + epsilon:
            raise ValueError(
                f"release_margin: amount={amount} > locked_margin={self.locked_margin}"
            )
        actual_release = min(amount, self.locked_margin)
        self.locked_margin -= actual_release

    def credit_settling(self, amount: float) -> None:
        """Credit T+0 sell proceeds to Settling_Funds (not Free_Cash)."""
        self.settling_funds += amount

    def apply_corporate_action(
        self,
        dividend_per_share: float = 0.0,
        bonus_ratio: float = 0.0,
        rights_ratio: float = 0.0,
    ) -> None:
        """§3 (audit P2-10, 2026-10-15): 除权日公司行为(多头方向)。

        - 现金分红 → `free_cash`(§3: physical cash deposit into Free_Cash)
        - 送股/拆股 → 数量 ×(1+bonus),成本价按总量不变重定;`PositionState` 是
          frozen dataclass,故**重建**而非原地修改(§0 append-only)。
        - 配股不建模,由 core 产出告警后落日志。

        权益归属:本方法只在"bar 起始已持有"时被调用(引擎在 next() 顶部、
        建仓分支之前应用),因此除权日当天新建的仓位不会被误记分红。
        """
        pos = self._pos
        if pos is None:
            return
        if (dividend_per_share <= 0) and (bonus_ratio <= 0) and (rights_ratio <= 0):
            return
        out = apply_corporate_action(
            size=int(pos.shares),
            entry_price=float(pos.entry_price),
            dividend_per_share=dividend_per_share,
            bonus_ratio=bonus_ratio,
            rights_ratio=rights_ratio,
        )
        for w in out.warnings:
            logger.warning("[corporate-action] %s @ %s: %s", pos.thscode, pos.entry_date, w)
        self.free_cash += out.cash_delta
        self.cash = self.total_cash
        if out.size != pos.shares or out.entry_price != pos.entry_price:
            self._pos = PositionState(
                thscode=pos.thscode,
                shares=out.size,
                entry_price=out.entry_price,
                entry_date=pos.entry_date,
                decision_meta=pos.decision_meta,
            )

    @property
    def position(self) -> PositionState | None:
        return self._pos

    def hold_days(self, on_date: date) -> int:
        if self._pos is None:
            return 0
        return (on_date - self._pos.entry_date).days

    def _buy_cost(self, price: float, shares: int) -> float:
        notional = price * shares
        comm = max(self.MIN_COMMISSION, notional * self.COMMISSION_RATE)
        return notional + comm

    def _sell_proceeds(self, price: float, shares: int) -> float:
        notional = price * shares
        comm = max(self.MIN_COMMISSION, notional * self.COMMISSION_RATE)
        tax = notional * self.STAMP_TAX_SELL
        return notional - comm - tax

    def try_enter(
        self,
        thscode: str,
        price: float,
        entry_date: date,
        decision_meta: dict[str, Any],
        # R8 (2026-09-21): Volume Participation Limit input.
        # None / NaN → skip cap (back-compat for tests without volume column)。
        bar_volume: float | None = None,
        # §4 (audit P3, 2026-10-15): 前收。提供时强制**涨停不成交**
        # (CLAUDE.md §3 Reality Mapping:涨停封板无法买入)。None → 跳过检查
        # (best-effort 回退,与 chase_up/uptrend/short_reversal 同口径)。
        prev_close: float | None = None,
    ) -> PositionState | None:
        if self._pos is not None:
            return None
        if price <= 0:
            return None
        # §4: 涨停开盘拒绝(执行层的物理不可成交约束)
        if is_limit_up(
            prev_close=prev_close,
            open_price=price,
            threshold=self.is_limit_up_threshold,
        ):
            return None
        # Round 10 (2026-09-28, CLAUDE.md §2): NAV-floor cash gate。
        # 当 NAV (cycle 单仓策略, NAV = self.cash, 因为 self._pos is None 守卫
        # 保证进入 try_enter 时无持仓) 跌到 initial_capital × NAV_GATE_RATIO
        # 以下时, 拒绝新开仓 — 已持仓仍按 SL/TP/time exit 正常执行 (不主动平仓)。
        # 与 chase_up + uptrend_pullback + short_reversal NAV gate 入口同口径。
        if self.cash < self.initial_capital * self.NAV_GATE_RATIO:
            return None
        # R527 (2026-10-08, CLAUDE.md §2): sizing basis MUST be free_cash,
        # NOT self.cash. self.cash is a stale alias initialized to initial
        # capital at __init__ L117-119, only re-synced to total_cash
        # AFTER reserve_for_entry at L259. Reading self.cash here is a
        # sibling of R249/R387.1 P0: between entries, free_cash shrinks
        # (locked_margin grows) but self.cash stays at initial value →
        # sizing over-allocates → reserve_for_entry fail-fast "cost >
        # free_cash". Fix: gate against free_cash directly.
        lots = int(self.free_cash * self.position_fraction // (price * 100))
        if lots < 1:
            return None
        shares = lots * 100
        cost = self._buy_cost(price, shares)
        # R527 (2026-10-08, CLAUDE.md §2): iterative downsize to fit free_cash.
        # 旧版只 decrement 1 lot,在 cycle 高价股场景下 gap 远大于 1 lot
        # (e.g. cost=1.987M vs free_cash=1.0M → gap ≈ 50 lots),导致
        # `return None` 过早放弃合法交易 + reserve_for_entry fail-fast 兜底
        # (cost > free_cash → raise,引擎直接挂掉)。改为 while-loop 一直
        # decrement 到 cost ≤ free_cash + ε,符合 §2 Margin Gatekeeper
        # (不超 free_cash, 物理按 lot 粒度调整) + 保守悲观 (final pass 仍
        # 越界则放弃, 不 silently bypass)。
        while cost > self.free_cash + 1e-9:
            shares -= 100
            if shares < 100:
                return None
            cost = self._buy_cost(price, shares)
        # R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
        # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION, 超出丢弃 (不挂单)。
        # 这是 CLAUDE.md §4 "Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"
        # 防止小票大单砸穿市场、产生 slippage / market impact。
        if bar_volume is not None and not _is_nan(bar_volume) and bar_volume > 0:
            max_fill = int(bar_volume * self.max_volume_participation // 100) * 100
            if max_fill > 0 and shares > max_fill:
                shares = max_fill
                cost = self._buy_cost(price, shares)
                if cost > self.free_cash + 1e-9 or shares < 100:
                    return None
        # Round 16 (CLAUDE.md §2): Lock Free_Cash → Locked_Margin for entry.
        # settle() at start of bar flushes yesterday's settling_funds → free_cash
        # so today's entries are correctly underwritten by yesterday's T+1 settle.
        self.reserve_for_entry(cost)
        self.cash = self.total_cash
        self._pos = PositionState(
            thscode=thscode,
            shares=shares,
            entry_price=price,
            entry_date=entry_date,
            decision_meta=MappingProxyType(dict(decision_meta)),
        )
        return self._pos

    def try_exit(self, exit_date: date, fill_price: float) -> float:
        if self._pos is None:
            raise ValueError("no open position")
        if exit_date <= self._pos.entry_date:
            raise ValueError("P3 violation: same-day or earlier exit forbidden")
        gross_in = self._buy_cost(self._pos.entry_price, self._pos.shares)
        net_out = self._sell_proceeds(fill_price, self._pos.shares)
        self.closed_trades.append(dict(
            thscode=self._pos.thscode,
            entry_date=self._pos.entry_date,
            exit_date=exit_date,
            entry_price=self._pos.entry_price,
            exit_price=fill_price,
            shares=self._pos.shares,
            pnl=net_out - gross_in,
            hold_days=(exit_date - self._pos.entry_date).days,
            decision_meta=dict(self._pos.decision_meta),
        ))
        proceeds = net_out
        # Round 16 (CLAUDE.md §2): T+0 sell proceeds → settling_funds (T+1
        # available). Immediate credit to free_cash would be T+0 settlement
        # which violates A-share market law. release_margin returns the
        # locked entry cost back to free_cash (settle() handles T+1 timing).
        self.credit_settling(proceeds)
        gross_in_cost = self._buy_cost(self._pos.entry_price, self._pos.shares)
        self.release_margin(gross_in_cost)
        self.cash = self.total_cash
        self._pos = None
        return proceeds

    def try_exit_with_intraday_check(
        self,
        exit_date: date,
        open_price: float,
        high: float,
        low: float,
        close: float,
        tp_pct: float,
        sl_pct: float,
    ) -> tuple[float, str]:
        """V6'' (2026-09-22, CLAUDE.md §4): Daily-bar SL-first tiebreak exit.

        Decision order (worst-case pessimistic):
          1. open <= sl_p → exit @ open, reason='SL' (gap-down through stop)
          2. open >= tp_p → exit @ open, reason='TP' (gap-up through target)
          3. low  <= sl_p → exit @ sl_p, reason='SL' (intraday stop)
          4. high >= tp_p → exit @ tp_p, reason='TP' (intraday target)
          5. else         → exit @ close, reason='time' (no trigger, bar close)

        SL-first within intraday (steps 3-4) implements CLAUDE.md §4:
          "if BOTH the Stop-Loss and Take-Profit limits are breached within
           the same bar, the engine MUST assume the worst-case scenario
           (Stop-Loss hit first)".
        Gap-up to TP (step 2) is independent of gap-down through SL — open
        cannot simultaneously be <= sl_p AND >= tp_p, so these are mutually
        exclusive and ordered by gap direction.

        Returns: (fill_price, reason)
        """
        if self._pos is None:
            raise ValueError("no open position")
        if exit_date <= self._pos.entry_date:
            raise ValueError("P3 violation: same-day or earlier exit forbidden")
        if tp_pct <= 0 or sl_pct <= 0:
            raise ValueError(
                f"tp_pct/sl_pct must be > 0, got tp={tp_pct}, sl={sl_pct}"
            )
        # Round 15 (2026-09-28, CLAUDE.md §4): intraday_tiebreak validation。
        # 与 chase_up/portfolio.py:274 + uptrend_pullback/portfolio.py:275 同口径 —
        # 防止 preset 误传 'tp_first' 时 silently 翻转 SL-first Pessimistic Default。
        if self.intraday_tiebreak != "sl_first":
            raise ValueError(
                f"intraday_tiebreak must be 'sl_first' (CLAUDE.md §4), "
                f"got {self.intraday_tiebreak!r}"
            )
        entry = self._pos.entry_price
        tp_p = entry * (1 + tp_pct)
        sl_p = entry * (1 - sl_pct)

        if open_price <= sl_p:
            fill, reason = float(open_price), "SL"
        elif open_price >= tp_p:
            fill, reason = float(open_price), "TP"
        elif low <= sl_p:
            fill, reason = float(sl_p), "SL"
        elif high >= tp_p:
            fill, reason = float(tp_p), "TP"
        else:
            fill, reason = float(close), "time"

        # §2/§6 (audit P0-2b / B6, 2026-10-15): `time` = **未出场**。
        #
        # 本方法是"检查并出场",但 SLA/TP 以外的分支**不该提交成交** —— 调用方
        # (backtrader_engine.next) 明确只在 `reason in ("SL","TP")` 时重置
        # `_entry_day`,并注释 "reason == 'time' → fall through to max_hold
        # check below"。而被调方此前在 time 分支也无条件写 closed_trades、清
        # `self._pos` —— 于是:
        #   - 持仓在第一根未触发 SL/TP 的 bar 就被强平;
        #   - 调用方的 max_hold 分支成为**死代码**(`_pos` 已为 None);
        #   - `_entry_day` 与实际持仓状态不一致。
        # 即调用方与被调方的契约矛盾。此处把提交动作限定在真正触发的分支,
        # 与调用方语义对齐;时间出场由调用方的 max_hold 分支经 try_exit() 完成。
        if reason == "time":
            return fill, reason

        gross_in = self._buy_cost(entry, self._pos.shares)
        net_out = self._sell_proceeds(fill, self._pos.shares)
        self.closed_trades.append(dict(
            thscode=self._pos.thscode,
            entry_date=self._pos.entry_date,
            exit_date=exit_date,
            entry_price=entry,
            exit_price=fill,
            shares=self._pos.shares,
            pnl=net_out - gross_in,
            hold_days=(exit_date - self._pos.entry_date).days,
            exit_reason=reason,
            decision_meta=dict(self._pos.decision_meta),
        ))
        # Round 16 (CLAUDE.md §2): T+0 sell proceeds → settling_funds.
        # release_margin returns the locked entry cost from locked_margin → free_cash.
        self.credit_settling(net_out)
        gross_in_cost = self._buy_cost(entry, self._pos.shares)
        self.release_margin(gross_in_cost)
        self.cash = self.total_cash
        self._pos = None
        return fill, reason
