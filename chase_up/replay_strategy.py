"""单笔交易 backtrader 策略 (沿用 uptrend_pullback/replay_strategy.py 口径)。

时序约定:
  bar 0 (signal_date)     — 下买单;当天无动作
  bar 1 (entry_date)      — 下一根 bar OPEN 成交;bars_in_pos=0 → 跳过退出判定
  bar 2..1+max_hold       — 持仓期;每日按 P5 优先级判 TP/SL/time
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd


class ChaseUpTradeReplay(bt.Strategy):
    """单笔多头交易的 backtrader 重放。

    params:
        target_size: int       — 仓位股数(已由 orchestrator 算好,100 股倍数)
        tp_price:    float     — 止盈价
        sl_price:    float     — 止损价
        max_hold:    int       — 最大持仓天数
    """

    params = dict(
        target_size=100,
        tp_price=0.0,
        sl_price=0.0,
        max_hold=8,
    )

    def __init__(self):
        self.entry_bar_idx: int | None = None
        self.skipped: bool = False
        self.exit_reason: str | None = None
        self.target_exit_price: float | None = None
        self.actual_exit_price: float | None = None
        self.actual_exit_date: pd.Timestamp | None = None
        self.entry_done: bool = False
        self.exit_done: bool = False
        self._entry_price_actual: float | None = None
        self._pending_exit_order = None

    def next(self):
        if self.skipped or self.exit_done:
            return
        bar_idx = len(self) - 1

        # bar 0: signal_date,下买单
        if bar_idx == 0:
            self.buy(size=self.p.target_size)
            return

        # 买单已成交 (bar 1 起)
        if not self.entry_done and self.position and self.position.size > 0:
            self.entry_bar_idx = bar_idx
            self._entry_price_actual = float(self.position.price)
            self.entry_done = True
            return

        if not self.position or self.position.size <= 0:
            return
        if self.entry_bar_idx is None:
            return

        bars_in_pos = bar_idx - self.entry_bar_idx
        if bars_in_pos < 1:
            # 入场当日不判退出 (P3)
            return

        o = float(self.data.open[0])
        h = float(self.data.high[0])
        lo = float(self.data.low[0])
        c = float(self.data.close[0])
        tp_p = float(self.p.tp_price)
        sl_p = float(self.p.sl_price)

        exit_price: float | None = None
        reason: str | None = None
        # P5 优先级: TP-first (开盘跳空破止盈优先), SL, 盘中 TP, 盘中 SL, time
        if o >= tp_p:
            exit_price, reason = o, "TP"
        elif o <= sl_p:
            exit_price, reason = o, "SL"
        elif h >= tp_p:
            exit_price, reason = tp_p, "TP"
        elif lo <= sl_p:
            exit_price, reason = sl_p, "SL"
        elif bars_in_pos >= self.p.max_hold:
            exit_price, reason = c, "time"

        if exit_price is not None:
            self.target_exit_price = exit_price
            self.exit_reason = reason
            order = self.close()
            self._pending_exit_order = order

    def notify_order(self, order):
        """卖出单实际成交时回填 actual_exit_price (bar N+1 OPEN)。"""
        if order is None:
            return
        if self._pending_exit_order is None or order.ref != self._pending_exit_order.ref:
            return
        if order.status == order.Completed:
            self.actual_exit_price = float(order.executed.price)
            self.actual_exit_date = pd.Timestamp(bt.num2date(order.executed.dt).date())
            self.exit_done = True
            self._pending_exit_order = None
        elif order.status in (order.Canceled, order.Rejected, order.Margin):
            self.exit_done = True
            self._pending_exit_order = None