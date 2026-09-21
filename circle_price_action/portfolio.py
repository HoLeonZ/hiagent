"""Single-position state machine for cycle_price_action.

Hard P3 contract:
    try_exit raises if the exit date equals the entry date — same-day exit
    is forbidden under A-share T+1 settlement, no matter what the price is.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class PositionState:
    thscode: str
    shares: int
    entry_price: float
    entry_date: date
    decision_meta: Mapping[str, Any]


class Portfolio:
    """Single-position book-keeping. Lot size = 100 shares. ¥5 commission floor.

    Position sizing: max 10% of cash per position (single-name concentration
    guard for fast-turn cycle strategy). Cash gate: never let `cost > cash`
    (no borrowing / no leverage).
    """

    COMMISSION_RATE = 0.00025
    MIN_COMMISSION = 5.0
    STAMP_TAX_SELL = 0.001
    MAX_POSITION_PCT = 0.10

    def __init__(self, cash: float) -> None:
        self.cash = float(cash)
        self._pos: PositionState | None = None

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
    ) -> PositionState | None:
        if self._pos is not None:
            return None
        if price <= 0:
            return None
        lots = int((self.cash * self.MAX_POSITION_PCT) // (price * 100))
        if lots < 1:
            return None
        shares = lots * 100
        cost = self._buy_cost(price, shares)
        if cost > self.cash:        # no-leverage guard
            return None
        self.cash -= cost
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
        proceeds = self._sell_proceeds(fill_price, self._pos.shares)
        self.cash += proceeds
        self._pos = None
        return proceeds