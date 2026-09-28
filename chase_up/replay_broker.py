"""A 股 broker:万 2.5 佣金双边 + 最低 ¥5 + 万 5 印花税卖出单边 (沿用 uptrend_pullback/replay_broker.py 口径)。"""
from __future__ import annotations

import backtrader as bt

# Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical cost rates imported from
# core/dual_price.py single-source-of-truth. Previously each engine maintained
# its own copy → drift risk. Values match canonical (万2.5 commission, 万5
# sell-only stamp duty, ¥5 floor).
from core.dual_price import (
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,
)


class AStockCommInfo(bt.CommInfoBase):
    """A 股佣金信息:万 2.5 双边 + 最低 ¥5。"""

    params = (
        ("commission", COMMISSION_RATE),
        ("min_commission", MIN_COMMISSION),
        ("stamp_duty", STAMP_DUTY_RATE),
        ("stocklike", True),
    )

    def _getcommission(self, size, price, pseudoexec):
        notional = abs(float(size)) * float(price)
        return max(notional * float(self.p.commission), float(self.p.min_commission))


class AStockBroker(bt.brokers.BackBroker):
    """继承 BackBroker,注入 AStockCommInfo + sell 方向印花税。"""

    def __init__(
        self,
        *args,
        commission: float = COMMISSION_RATE,
        stamp_duty: float = STAMP_DUTY_RATE,
        min_commission: float = MIN_COMMISSION,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._comminfo = AStockCommInfo(
            commission=commission,
            min_commission=min_commission,
            stamp_duty=stamp_duty,
            stocklike=True,
        )
        self.addcommissioninfo(self._comminfo, name=None)
        self.STAMP_DUTY = stamp_duty

    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        if position is None:
            position = self.positions[order.data]
        if cash is None:
            cash = self.cash
        result = super()._execute(
            order, ago=ago, price=price, cash=cash,
            position=position, dtcoc=dtcoc,
        )
        if order.issell() and order.executed.size:
            notional = abs(order.executed.size) * order.executed.price
            self.cash -= notional * self.STAMP_DUTY
        return result