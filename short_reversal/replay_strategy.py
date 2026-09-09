"""Phase 2: 按 trades.parquet 重放入场/出场，backtrader 负责记账与手续费。"""
from __future__ import annotations

import backtrader as bt
import pandas as pd


class TradeReplayStrategy(bt.Strategy):
    """按 trades.parquet 重放入场/出场，持仓期按日扣融券年化费。

    params:
        trades_df:        pd.DataFrame — 列: entry_date, thscode, exit_date, exit_reason,
                          entry_price, exit_price, hold_days
        margin_rate:      float        — 年化融券费率（默认 8.6%）
        initial_capital:  float        — 初始本金，用于 fixed fractional 仓位（默认 1_000_000）
        position_fraction: float       — 单笔占用本金比例（默认 1.0 = 全仓单票）

    next() 顺序：
      1) 持仓期按日扣融券费（broker.add_cash(-|size| * price * rate / 365)）
      2) 查今天是否有 ENTRY/EXIT action，触发 sell / buy to cover

    仓位计算关键修复（v1 资金路径 bug）：
      - 旧版用 `broker.getcash()` 算 size。开空后 cash 增加（proceeds 计入 cash），
        导致下一笔 size 越来越大 → 仓位爆炸。
      - 新版用 `initial_capital * position_fraction` 作为固定基数，与 broker.cash 解耦，
        实现 fixed fractional position sizing。
    """

    params = dict(
        trades_df=None,         # pandas DataFrame
        margin_rate=0.086,      # 8.6% 年化融券
        initial_capital=1_000_000.0,
        position_fraction=1.0,
    )

    def __init__(self):
        df = self.p.trades_df
        # 按 date → action 列表；同日多笔并存（hold=1 时 entry/exit 在同一日，
        # 必须用 list 而非 dict，否则后写覆盖前写）
        self.actions: dict = {}
        if df is not None and not df.empty:
            for _, t in df.iterrows():
                entry_d = pd.Timestamp(t["entry_date"])
                exit_d = pd.Timestamp(t["exit_date"])
                self.actions.setdefault(entry_d, []).append(("ENTRY", t))
                self.actions.setdefault(exit_d, []).append(("EXIT", t))

    def next(self):
        today = pd.Timestamp(self.data.datetime.date(0))
        pos = self.getposition()

        # 1. 持仓期按日扣融券费（走 broker.add_cash API，不直接改 broker.cash）
        if pos.size < 0 and not pd.isna(pos.price):
            day_fee = abs(pos.size) * pos.price * self.p.margin_rate / 365
            self.broker.add_cash(-day_fee)

        # 2. 查今天是否有 action（同日多条都执行）
        day_actions = self.actions.get(today)
        if day_actions is None:
            return

        for kind, t in day_actions:
            if kind == "ENTRY" and pos.size == 0:
                price = self.data.close[0]
                # Fixed fractional: 用 initial_capital * position_fraction 作为基数
                target_value = self.p.initial_capital * self.p.position_fraction
                size = int(target_value / price / 100) * 100  # 100 股一手
                if size >= 100:
                    self.sell(size=size)  # 开空
            elif kind == "EXIT" and pos.size < 0:
                self.close()  # 平空（buy to cover）
