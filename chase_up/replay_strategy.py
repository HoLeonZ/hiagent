"""单笔交易 backtrader 策略 (沿用 uptrend_pullback/replay_strategy.py 口径)。

时序约定:
  bar 0 (signal_date)     — 下买单;当天无动作
  bar 1 (entry_date)      — 下一根 bar OPEN 成交;bars_in_pos=0 → 跳过退出判定
  bar 2..1+max_hold       — 持仓期;每日按 P5 优先级判 TP/SL/time
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd

from chase_up.portfolio import LIMIT_UP_THRESHOLD  # §2 单源:涨停阈值只有一处定义
from core.dual_price import is_limit_up


class ChaseUpTradeReplay(bt.Strategy):
    """单笔多头交易的 backtrader 重放。

    params:
        target_size: int       — 仓位股数(已由 orchestrator 算好,100 股倍数)
        tp_price:    float     — 止盈价
        sl_price:    float     — 止损价
        max_hold:    int       — 最大持仓天数
        prev_close_limit: float — 涨停阈值(取自 chase_up/portfolio.LIMIT_UP_THRESHOLD)
    """

    params = dict(
        target_size=100,
        tp_price=0.0,
        sl_price=0.0,
        max_hold=8,
        # §4/§2 (audit 2026-10-15): **引用** Phase 1 的常量,而不是再写一份字面量。
        # 此前这里是 `0.098` 加一句"与 chase_up/portfolio.LIMIT_UP_THRESHOLD 一致"
        # —— 注释保证不了任何事:两个值分处两文件,改一处不会有任何东西报错,
        # 而这条阈值决定"涨停封板时能不能买"。同值不同源就是下一次漂移的起点。
        prev_close_limit=LIMIT_UP_THRESHOLD,
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
            # bar 0 只负责下单。涨停与否要等 bar 1 的 open 才可见,在 bar 0 无法
            # 因果预判 (§1),故 skip 判定放在 bar 1(见下方 §4 分支)。
            self.buy(size=self.p.target_size)
            return

        # --- §4 涨停不成交:复核入场 bar 是否涨停开盘 ---
        # §4 (audit P1-8, 2026-10-15): 此前 `self.skipped` 字段声明了却**从未
        # 赋值 True** —— Phase-2 会在涨停封板的开盘价上照常"买入",与 Phase-1
        # (portfolio.py 的 is_limit_up 守卫)结论矛盾,同一 preset 两条入口给出
        # 相反结果。口径与 uptrend_pullback/replay_strategy 一致,共用
        # core.dual_price.is_limit_up 单一来源。
        if not self.entry_done and is_limit_up(
            float(self.data.close[-1]),
            float(self.data.open[0]),
            self.p.prev_close_limit,
        ):
            self.skipped = True
            self.exit_reason = "limit_up"
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
        # §4 (audit P1-8, 2026-10-15): SL-first —— 见下方次序。
        # CLAUDE.md §4 明令:同一根日线上 SL 与 TP **同时**被击穿时,必须按最坏
        # 情形处理(SL 先中)。本处原为 TP-first,与 Phase-1
        # (chase_up/portfolio.py,SL-first)相反 —— 同一 preset 的 Phase-1 /
        # Phase-2 因此给出互相矛盾的出场结论,而默认 CLI 走 Phase-2。
        # 口径对齐 uptrend_pullback/replay_strategy.py:126-136。
        # Gap 情形仍按跳空价优先匹配(开盘已越过哪一侧就是哪一侧),
        # 盘中双触发时取 SL。
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