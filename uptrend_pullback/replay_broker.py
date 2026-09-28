"""A 股 broker：万 2.5 佣金双边 + 最低 ¥5 + 万 5 印花税卖出单边。

成本结构（A 股多头，与 short_reversal 的融券做空不同）：
  - 佣金  commission   0.00025   万 2.5，buy/sell 都扣，最低 ¥5
  - 印花税 stamp_duty  0.0005    万 5，仅 sell 方向

佣金由自定义 CommInfo 处理（支持最低 ¥5 约束），
印花税在 broker._execute 里 sell 方向额外扣（与 short_reversal 一致）。
"""
from __future__ import annotations

import backtrader as bt

# Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical cost rates imported from
# core/dual_price.py single-source-of-truth.
from core.dual_price import (
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,
)


class AStockCommInfo(bt.CommInfoBase):
    """A 股佣金信息：万 2.5 双边 + 最低 ¥5。

    backtrader 默认 commission 体系不支持"按笔最低"，需要重写
    _getcommission() 在算出的百分比佣金与最低值之间取大。

    stamp_duty 字段保留在此处仅为文档/对外一致性，实际扣减由 broker._execute
    在 sell 方向上额外执行（因为 backtrader 没有原生的"单边税"概念）。
    """

    params = (
        ("commission", COMMISSION_RATE),  # 万 2.5
        ("min_commission", MIN_COMMISSION),   # ¥5
        ("stamp_duty", STAMP_DUTY_RATE),    # 万 5（仅 sell，由 broker 扣）
        ("stocklike", True),
    )

    def _getcommission(self, size, price, pseudoexec):
        notional = abs(float(size)) * float(price)
        return max(notional * float(self.p.commission), float(self.p.min_commission))


class AStockBroker(bt.brokers.BackBroker):
    """继承 BackBroker，注入 AStockCommInfo + sell 方向印花税。"""

    def __init__(
        self,
        *args,
        commission: float = COMMISSION_RATE,
        stamp_duty: float = STAMP_DUTY_RATE,
        min_commission: float = MIN_COMMISSION,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # 默认佣金体系：万 2.5 + 最低 ¥5。setcommission 不接受 comminfo 参数，
        # 用 _commissions 表保存自定义 CommInfo 实例，backtrader 会在成交时查询。
        self._comminfo = AStockCommInfo(
            commission=commission,
            min_commission=min_commission,
            stamp_duty=stamp_duty,
            stocklike=True,
        )
        # 注册为默认（不带 data 参数时作用于所有 data）
        self.addcommissioninfo(self._comminfo, name=None)
        self.STAMP_DUTY = stamp_duty

    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
        """让 BackBroker 完成成交（commission 已扣），再从 sell 方向扣印花税。"""
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
