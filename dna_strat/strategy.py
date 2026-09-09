"""Phase 2: 按 trades.parquet 重放入场/出场，backtrader 负责记账与手续费。"""
from __future__ import annotations

import backtrader as bt
import pandas as pd


class TradeReplayStrategy(bt.Strategy):
    """按 trades.parquet 重放入场/出场，持仓期按日扣融券年化费。

    params:
        trades_df:    pd.DataFrame — 列: entry_date, thscode, exit_date, exit_reason,
                      entry_price, exit_price, hold_days
        margin_rate:  float        — 年化融券费率（默认 8.6%）

    next() 顺序：
      1) 持仓期按日扣融券费（broker.cash -= |size| * price * rate / 365）
      2) 查今天是否有 ENTRY/EXIT action，触发 buy/sell/close
    """

    params = dict(
        trades_df=None,     # pandas DataFrame
        margin_rate=0.086,  # 8.6% 年化融券
    )

    def __init__(self):
        df = self.p.trades_df
        # 按 date → action 索引；同日多笔以字典后写覆盖前写（trades 已 deduped）
        self.actions: dict = {}
        if df is not None and not df.empty:
            for _, t in df.iterrows():
                self.actions[pd.Timestamp(t["entry_date"])] = ("ENTRY", t)
                self.actions[pd.Timestamp(t["exit_date"])] = ("EXIT", t)

    def next(self):
        today = pd.Timestamp(self.data.datetime.date(0))
        pos = self.getposition()

        # 1. 持仓期按日扣融券费
        if pos.size < 0 and not pd.isna(pos.price):
            day_fee = abs(pos.size) * pos.price * self.p.margin_rate / 365
            self.broker.cash -= day_fee

        # 2. 查今天是否有 action
        action = self.actions.get(today)
        if action is None:
            return

        kind, t = action
        if kind == "ENTRY" and pos.size == 0:
            cash = self.broker.getcash()
            price = self.data.close[0]
            size = int(cash / price / 100) * 100  # 100 股一手
            if size >= 100:
                self.sell(size=size)  # 开空
        elif kind == "EXIT" and pos.size < 0:
            self.close()  # 平空（buy to cover）
