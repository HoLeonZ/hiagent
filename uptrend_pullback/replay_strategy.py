"""Phase 2: 单笔交易 backtrader 策略。

时序约定（与 portfolio.py:simulate_portfolio 一致）：
  bar 0 (signal_date)     — 下买单；当天无动作
  bar 1 (entry_date)      — backtrader 默认在 bar 1 开盘成交
                            → 此时 self.position.size > 0
                            → 跳过当日退出判定（入场当日不判）
  bar 2..1+max_hold       — 持仓期；每日按 o/lo/h/c 优先级判 TP/SL/time

退出优先级（与 portfolio.py 完全一致）：
  1. o <= sl_p → SL @ open
  2. o >= tp_p → TP @ open
  3. lo <= sl_p → SL @ sl_p
  4. h >= tp_p → TP @ tp_p
  5. bars_in_pos >= max_hold → time @ close

注：backtrader 的市价单在下一根 bar 开盘成交，故 sell() 的实际 fill 价格
    会比决策日晚一日开盘。orchestrator 在合并结果时按"目标退出价"重算 PnL，
    backtrader 仅用于佣金/印花税/现金流的精确记账。
"""
from __future__ import annotations

import backtrader as bt


class UpullbackTradeReplay(bt.Strategy):
    """单笔多头交易的 backtrader 重放。

    params:
        target_size: int       — 仓位股数（已由 orchestrator 算好，100 股倍数）
        tp_price:    float     — 止盈价（已按 ATR 自适应算出）
        sl_price:    float     — 止损价（已按 ATR 自适应算出）
        max_hold:    int       — 最大持仓天数
        prev_close_limit: float — 涨停阈值（默认 0.098）

    状态字段（供 orchestrator 读取）：
        entry_bar_idx      entry 当天的 bar 索引（0-based）
        skipped            涨停跳空导致无法买入
        exit_reason        "TP" / "SL" / "time" / "limit_up"
        target_exit_price  策略决定的退出价（bar N 的触发价，不一定是实际成交价）
        actual_exit_price  backtrader 实际成交价（bar N+1 OPEN），通过 notify_order 抓取；
                          若订单尚未成交则为 None。orchestrator 必须用此字段作为 exit_price。
    """

    params = dict(
        target_size=100,
        tp_price=0.0,
        sl_price=0.0,
        max_hold=8,
        prev_close_limit=0.098,
    )

    def __init__(self):
        self.entry_bar_idx: int | None = None
        self.skipped: bool = False
        self.exit_reason: str | None = None
        self.target_exit_price: float | None = None
        # 实际成交价（下一根 bar OPEN）；由 notify_order 在成交时回填
        self.actual_exit_price: float | None = None
        self.entry_done: bool = False
        self.exit_done: bool = False
        self._entry_price_actual: float | None = None
        # 跟踪当前挂起的卖出单（用于在 notify_order 中识别"目标 sell 单"）
        self._pending_exit_order = None

    def next(self):
        if self.skipped or self.exit_done:
            return
        bar_idx = len(self) - 1  # 0-based，当前已处理的 bar 数减 1

        # --- bar 0: signal_date，下买单，并预检涨停 ---
        if bar_idx == 0:
            # 预检：明天（bar 1）开盘是否涨停。Bar 0 收盘已知，
            # 但 bar 1 的开盘要等运行到 bar 1 才能看到。简单做法：
            # 若 bar 0 收盘已涨停 + 大涨幅，明日开盘几乎必涨停 → 直接 skip。
            close0 = float(self.data.close[0])
            # 这里只能做粗判（用 bar 0 自身的高涨幅），真正的 skip 校验交给
            # orchestrator 在合并 trades 时用 bar 1 的 open 复核。
            self.buy(size=self.p.target_size)
            return

        # --- 买单已成交（bar 1 起），记录入场 ---
        if not self.entry_done and self.position and self.position.size > 0:
            self.entry_bar_idx = bar_idx
            self._entry_price_actual = float(self.position.price)
            self.entry_done = True
            return

        # --- 已有仓位，判退出 ---
        if not self.position or self.position.size <= 0:
            return
        if self.entry_bar_idx is None:
            return

        bars_in_pos = bar_idx - self.entry_bar_idx
        if bars_in_pos < 1:
            # 入场当日不判退出
            return

        o = float(self.data.open[0])
        h = float(self.data.high[0])
        lo = float(self.data.low[0])
        c = float(self.data.close[0])
        tp_p = float(self.p.tp_price)
        sl_p = float(self.p.sl_price)

        exit_price: float | None = None
        reason: str | None = None
        if o <= sl_p:
            exit_price, reason = o, "SL"
        elif o >= tp_p:
            exit_price, reason = o, "TP"
        elif lo <= sl_p:
            exit_price, reason = sl_p, "SL"
        elif h >= tp_p:
            exit_price, reason = tp_p, "TP"
        elif bars_in_pos >= self.p.max_hold:
            exit_price, reason = c, "time"

        if exit_price is not None:
            self.target_exit_price = exit_price
            self.exit_reason = reason
            order = self.close()  # 市价单，下一根 bar 开盘成交
            self._pending_exit_order = order
            # 注意：不在这里 set exit_done，要等 notify_order 确认成交后再 set

    def notify_order(self, order):
        """卖出单实际成交时回填 actual_exit_price。

        backtrader 的市价单在 next() 调用后还需再等一根 bar 才成交；成交价
        是 bar N+1 OPEN，不等于决策时看到的 bar N 触发价（target_exit_price）。
        必须在 notify_order 里捕获真实成交价，否则 exit_price 与 net_pnl
        会出现 1 根 bar 的口径不一致。
        """
        if order is None:
            return
        # 只关心我们挂的目标 sell 单
        if self._pending_exit_order is None or order.ref != self._pending_exit_order.ref:
            return
        if order.status == order.Completed:
            self.actual_exit_price = float(order.executed.price)
            self.exit_done = True
            self._pending_exit_order = None
        elif order.status in (order.Canceled, order.Rejected, order.Margin):
            # 撤单/拒单：标记 done 防止 next() 反复尝试；actual_exit_price 留 None
            self.exit_done = True
            self._pending_exit_order = None
