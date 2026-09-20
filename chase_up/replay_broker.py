"""A 股 broker:万 2.5 佣金双边 + 最低 ¥5 + 万 5 印花税卖出单边 (沿用 uptrend_pullback/replay_broker.py 口径)。"""
from __future__ import annotations

import backtrader as bt


class AStockCommInfo(bt.CommInfoBase):
    """A 股佣金信息:万 2.5 双边 + 最低 ¥5。"""

    params = (
        ("commission", 0.00025),
        ("min_commission", 5.0),
        ("stamp_duty", 0.0005),
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
        commission: float = 0.00025,
        stamp_duty: float = 0.0005,
        min_commission: float = 5.0,
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