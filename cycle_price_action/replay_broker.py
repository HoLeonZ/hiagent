"""T+1 next-bar-matching broker for cycle_price_action.

Order semantics:
    - Order is queued at decision_date close.
    - Fill occurs on the next trading day's open price.
    - P3 guard: same-day exits are rejected at queue time.

§6 architecture (Tick 49, 2026-09-28): Execution Broker is DB-free.
ReplayBroker receives a `ReplayDataProvider` (from Control Plane
`cycle_price_action.data_feed`) and delegates all per-fill PIT lookups
to it. This broker contains zero `duckdb.connect` calls — pure
slippage / cost / position bookkeeping.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from core.dual_price import (
    STAMP_DUTY_RATE,  # Round 9 (2026-09-28): canonical 万5 sell-only stamp duty
)


@dataclass(frozen=True)
class TradeFill:
    date: date
    thscode: str
    side: str         # "buy" | "sell"
    qty: int
    price: float
    fee: float


class ReplayBroker:
    def __init__(
        self,
        data_provider,  # cycle_price_action.data_feed.ReplayDataProvider
        # R5' (2026-09-23, CLAUDE.md §4): ATR-aware slippage opt-in.
        # atr_slip_scale = 0.0 (default) → no slippage applied (back-compat).
        # atr_slip_scale > 0 → slippage = max(static_slip, atr_pct × participation × scale).
        atr_slip_scale: float = 0.0,
    ) -> None:
        self._data_provider = data_provider
        self.atr_slip_scale = atr_slip_scale
        self._open_positions: dict[str, int] = {}

    def _next_trading_date(self, after: date) -> date:
        # Tick 49: delegate to Control Plane data_provider (DB-free broker).
        return self._data_provider.next_trading_date(after)

    def _open_price(self, thscode: str, on_date: date) -> float:
        # Tick 49 + N3: delegate to data_provider.open_price which routes
        # through extract_execution_bar to enforce partial-NaN guard
        # (open>0 + close=NaN raises ValueError).
        return self._data_provider.open_price(thscode, on_date)

    def _fee(
        self,
        side: str,
        qty: int,
        price: float,
        atr_pct: float | None = None,
        participation: float = 0.0,
        static_slip: float = 0.0,
    ) -> float:
        notional = qty * price
        commission = max(5.0, notional * 0.00025)
        # Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical STAMP_DUTY_RATE (万5
        # post-Aug2023); was 0.001 = 万10 pre-Aug2023 historical.
        tax = notional * STAMP_DUTY_RATE if side == "sell" else 0.0
        # R5' (2026-09-23, CLAUDE.md §4): ATR-aware slippage.
        # Effective slip = max(static_slip, atr_pct × participation × scale) when scale > 0
        # and atr_pct provided; else static_slip only.
        if (
            self.atr_slip_scale > 0
            and atr_pct is not None
            and not _is_nan(atr_pct)
        ):
            atr_slip = atr_pct * participation * self.atr_slip_scale
            slip_eff = max(static_slip, atr_slip)
        else:
            slip_eff = static_slip
        return commission + tax + notional * slip_eff

    def submit_buy(
        self,
        thscode: str,
        qty: int,
        decision_date: date,
        atr_pct: float | None = None,
        participation: float = 0.0,
    ) -> Optional[TradeFill]:
        if qty <= 0 or qty % 100 != 0:
            raise ValueError("qty must be positive multiple of 100")
        fill_date = self._next_trading_date(decision_date)
        price = self._open_price(thscode, fill_date)
        fee = self._fee("buy", qty, price, atr_pct=atr_pct, participation=participation)
        self._open_positions[thscode] = self._open_positions.get(thscode, 0) + qty
        return TradeFill(fill_date, thscode, "buy", qty, price, fee)

    def record_fill(self, fill: TradeFill) -> None:
        pass  # for future instrumentation

    def submit_sell(
        self,
        thscode: str,
        qty: int,
        decision_date: date,
        atr_pct: float | None = None,
        participation: float = 0.0,
    ) -> Optional[TradeFill]:
        # P3: same-day exit forbidden.
        held = self._open_positions.get(thscode, 0)
        if held < qty:
            raise ValueError("cannot sell more than held")
        if qty <= 0 or qty % 100 != 0:
            raise ValueError("qty must be positive multiple of 100")
        fill_date = self._next_trading_date(decision_date)
        price = self._open_price(thscode, fill_date)
        fee = self._fee("sell", qty, price, atr_pct=atr_pct, participation=participation)
        self._open_positions[thscode] -= qty
        if self._open_positions[thscode] == 0:
            del self._open_positions[thscode]
        return TradeFill(fill_date, thscode, "sell", qty, price, fee)


def _is_nan(x: float) -> bool:
    return x != x