"""cycle_price_action 的 backtrader 数据源(§3 公司行为事件列)。

为什么需要自定义 feed:策略只能通过 backtrader 的 line 读取数据,`bt.feeds.PandasData`
无法直接携带额外列 —— 必须声明 lines/params 子类。这与 short_reversal/feed_bt.py
同构。

§3 (audit P2-10, 2026-10-15): 除权日事件(分红 / 送股 / 配股)由此进入策略,
使执行域为原始价时「除权缺口不补偿分红」这一系统性偏差得以消除。
"""
from __future__ import annotations

import backtrader as bt

#: 事件列名(缺失时由 build 侧补 0.0 —— 0.0 = 无事件,NaN 会让判定失真)
EVENT_COLS = ("div_per_share", "bonus_ratio", "rights_ratio")


class CyclePandasData(bt.feeds.PandasData):
    """PandasData + §3 公司行为事件 lines。"""

    lines = EVENT_COLS
    params = (
        ("div_per_share", "div_per_share"),
        ("bonus_ratio", "bonus_ratio"),
        ("rights_ratio", "rights_ratio"),
    )

    def start(self):
        """旧 panel 缺事件列时补 0.0 占位,避免 super().start() 因列缺失报错。"""
        dn = getattr(self.p, "dataname", None)
        if dn is not None:
            for col in EVENT_COLS:
                if col not in dn.columns:
                    dn[col] = 0.0
        super().start()
