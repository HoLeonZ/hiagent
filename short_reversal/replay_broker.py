"""A 股 broker：在 BackBroker 基础上，卖出/开空加万 1 印花税。"""
from __future__ import annotations

import backtrader as bt


class AShareBroker(bt.brokers.BackBroker):
    """继承 BackBroker，覆盖 `_execute`，在卖出方向扣单边印花税。"""

    STAMP_DUTY = 0.001  # 万 1（卖出/开空单边）

    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        """让 BackBroker 完成成交，再从卖出方向现金中扣印花税。"""
        if position is None:
            position = self.positions[order.data]
        if cash is None:
            cash = self.cash
        result = super()._execute(
            order,
            ago=ago,
            price=price,
            cash=cash,
            position=position,
            dtcoc=dtcoc,
        )
        if order.issell() and order.executed.size:
            notional = abs(order.executed.size) * order.executed.price
            self.cash -= notional * self.STAMP_DUTY
        return result
