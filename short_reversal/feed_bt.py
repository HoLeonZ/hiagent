"""backtrader 数据源。

AShareData: 在 PandasData 基础上加 `amount`（成交额）line，
            供 Am60 indicator 使用。

build_per_stock_feeds: 把 DuckDB 拉出的 panel 切成 per-stock feeds 喂给 cerebro。
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd


class AShareData(bt.feeds.PandasData):
    """PandasData + amount line（A 股特有，Am60 指标要用）。"""

    lines = ("amount",)
    params = (
        ("amount", "amount"),
        ("datetime", "date"),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
    )


def build_per_stock_feeds(
    panel: pd.DataFrame, codes: list[str]
) -> list[tuple[str, AShareData]]:
    """按代码切片 panel，构建 (thscode, AShareData) 列表。

    跳过太短的序列（<200 bars）以免 MA60 永远空。
    """
    feeds: list[tuple[str, AShareData]] = []
    for code in codes:
        sub = (
            panel[panel["thscode"] == code]
            .sort_values("date")
            .reset_index(drop=True)
        )
        if len(sub) < 200:
            continue
        feed = AShareData(dataname=sub, plot=False)
        feeds.append((code, feed))
    return feeds
