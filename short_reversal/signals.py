"""MACD/EMA/MA 计算 + v33 五条件命中。

compute_panel_indicators — 严格基于历史数据，无未来泄露。
select_entries            — v33 五条件 A∧B∧C∧D∧E。
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def compute_panel_indicators(panel: pd.DataFrame) -> pd.DataFrame:
    """追加 ma20/ma60/ema12/ema26/dif/dea/macd_bar/pct_chg/am60/up_streak 列。

    输入必须按 (thscode, date) 排序。输出保持同样顺序。
    所有 rolling/ewm 仅用历史数据；pct_chg 基于 shift(1) close。
    """
    df = panel.copy()
    df = df.sort_values(["thscode", "date"]).reset_index(drop=True)
    g = df.groupby("thscode", group_keys=False)

    # MA20 / MA60 — 严格历史窗口
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    # EMA12 / EMA26 — 指数加权（仅用历史 close）
    df["ema12"] = g["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    df["ema26"] = g["close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())

    # DIF / DEA / MACD 柱
    df["dif"] = df["ema12"] - df["ema26"]
    df["dea"] = g["dif"].transform(lambda s: s.ewm(span=9, adjust=False).mean())
    df["macd_bar"] = 2 * (df["dif"] - df["dea"])

    # pct_chg — 基于 shift(1) close（前一根 K 线）
    prev_close = g["close"].shift(1)
    df["pct_chg"] = (df["close"] - prev_close) / prev_close

    # am60 — 历史 60 日均成交额
    df["am60"] = g["amount"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    # 连阳计数：up_day=True 时累加，遇到阴线/NaN 重置
    df["up_day"] = (df["pct_chg"] > 0).fillna(False)
    # 每段连阳的起点 = up_day 由 False/NaN → True 的过渡行
    prev_up = df["up_day"].shift(1).fillna(False).astype(bool)
    df["up_id"] = (df["up_day"] & ~prev_up).astype(int).cumsum()
    df["up_streak"] = df.groupby(["thscode", "up_id"]).cumcount() + 1
    df.loc[~df["up_day"], "up_streak"] = 0

    return df
