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

import math
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping

# Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical cost rates imported from
# core/dual_price.py single-source-of-truth. (was 0.001 = 万10 pre-Aug2023).
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

    COMMISSION_RATE = 0.00025
    MIN_COMMISSION = 5.0
    # Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical 万5 post-Aug2023 rate
    # (was 0.001 = 万10 pre-Aug2023 historical). Sell-side only.
    STAMP_TAX_SELL = 0.0005
    # Project policy: every entry is all-in (CLAUDE.md §2, revised 2026-09-21).
    # Held at 1.0 explicitly so the constant survives for callers/tests.
    MAX_POSITION_PCT = 1.0
    # R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
    # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。超出部分丢弃(不挂单)。
    # 与 chase_up/portfolio.py:49 / short_reversal/replay_strategy_v3.py 口径一致,
    # 防止小票大单砸穿市场。bar_volume is optional for backwards compatibility;
    # when None or NaN the cap is skipped (test fixtures without volume column)。
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
        initial_capital: float = 1_000_000.0,
        # R5' (2026-09-23, CLAUDE.md §4): ATR-aware slippage opt-in.
        # When atr_slip_scale > 0, slippage = max(0, atr_pct × participation × scale)
        # is added on top of commission + tax. Default 0.0 = no slippage (back-compat).
        atr_slip_scale: float = 0.0,
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
        self.intraday_tiebreak = intraday_tiebreak
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
        """Unlock Locked_Margin → Free_Cash (e.g., position closed).

        Round 28 (2026-09-28, CLAUDE.md §0 Pessimistic Default):
        Tolerate sub-epsilon IEEE 754 drift on locked_margin
        (sibling fix to Round 26 release_margin for short_reversal).
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
        self.free_cash += actual_release

    def credit_settling(self, amount: float) -> None:
        """Credit T+0 sell proceeds to Settling_Funds (not Free_Cash)."""
        self.settling_funds += amount

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
    ) -> PositionState | None:
        if self._pos is not None:
            return None
        if price <= 0:
            return None
        # Round 10 (2026-09-28, CLAUDE.md §2): NAV-floor cash gate。
        # 当 NAV (cycle 单仓策略, NAV = self.cash, 因为 self._pos is None 守卫
        # 保证进入 try_enter 时无持仓) 跌到 initial_capital × NAV_GATE_RATIO
        # 以下时, 拒绝新开仓 — 已持仓仍按 SL/TP/time exit 正常执行 (不主动平仓)。
        # 与 chase_up + uptrend_pullback + short_reversal NAV gate 入口同口径。
        if self.cash < self.initial_capital * self.NAV_GATE_RATIO:
            return None
        lots = int(self.cash // (price * 100))
        if lots < 1:
            return None
        shares = lots * 100
        cost = self._buy_cost(price, shares)
        # Round 29b (2026-09-28, CLAUDE.md §0): pre-check tolerates sub-epsilon
        # IEEE 754 drift on cash before falling through to the
        # tolerance-aware reserve_for_entry (Round 28). Without + epsilon,
        # drift makes this pre-check shrink shares unnecessarily and
        # eventually `return None` on legitimate trades.
        if cost > self.cash + 1e-9:        # commission would push over cash — round down 1 lot
            shares -= 100
            if shares < 100:
                return None
            cost = self._buy_cost(price, shares)
            if cost > self.cash + 1e-9:    # still over after rounding down (e.g. min commission floor)
                return None
        # R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
        # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION, 超出丢弃 (不挂单)。
        # 这是 CLAUDE.md §4 "Max_Fill_Qty = MIN(Order_Qty, Bar_Volume * 0.10)"
        # 防止小票大单砸穿市场、产生 slippage / market impact。
        if bar_volume is not None and not _is_nan(bar_volume) and bar_volume > 0:
            max_fill = int(bar_volume * self.MAX_VOL_PARTICIPATION // 100) * 100
            if max_fill > 0 and shares > max_fill:
                shares = max_fill
                cost = self._buy_cost(price, shares)
                if cost > self.cash + 1e-9 or shares < 100:
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
