"""A 股 broker：在 BackBroker 基础上，加双边万 0.6 佣金 + 卖出/开空万 1 印花税。"""
from __future__ import annotations

import backtrader as bt


class AShareBroker(bt.brokers.BackBroker):
    """继承 BackBroker，加 A 股双边交易成本。

    成本结构（A 股融券做空）：
      - 佣金  commission   0.0006 万 0.6 双边
      - 印花税 stamp_duty  0.001  万 1 单边（仅卖出方向，开空=卖出 / 平空=买入 to cover）

    佣金由 backtrader 内置 commission 体系承担（每笔成交按 notional * commission 扣 cash），
    印花税在 `_execute` 里 sell 方向额外扣。
    """

    def __init__(
        self,
        *args,
        commission: float = 0.0006,
        stamp_duty: float = 0.001,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # 双边佣金：buy 和 sell 都按 notional * commission 扣 cash
        self.setcommission(commission=commission, stocklike=True)
        self.STAMP_DUTY = stamp_duty

    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        """让 BackBroker 完成成交（内置 commission 已扣），再从卖出方向现金中扣印花税。"""
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
