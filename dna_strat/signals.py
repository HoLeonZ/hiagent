"""MACD / EMA 计算 + 信号打分。"""
from __future__ import annotations

import pandas as pd


def compute_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """按 close 序列算 DIF/DEA。返回 DataFrame[dif, dea]，index 与输入一致。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"dif": dif, "dea": dea})


def compute_panel_indicators(panel: pd.DataFrame) -> pd.DataFrame:
    """为 panel（thscode, date, close, prev_close）增加指标列。
    输入按 (thscode, date) 排序。返回带 ma20/ma60/up_3/down_days_100/today_ret 的 DataFrame。

    注：DIF/DEA 列已移除（cond_e 删除后无下游消费者）。
    """
    df = panel.copy()
    df = df.sort_values(["thscode", "date"]).reset_index(drop=True)
    g = df.groupby("thscode", group_keys=False)

    # MA20 / MA60：基于 close，需 60 日窗口 → 前 59 行为 NaN
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    # close_lag1..3
    df["close_lag1"] = g["close"].shift(1)
    df["close_lag2"] = g["close"].shift(2)
    df["close_lag3"] = g["close"].shift(3)

    # 涨跌布尔
    df["down_today"] = df["close"] < df["prev_close"]
    df["up_today"] = df["close"] > df["prev_close"]
    df["up_lag1"] = df["close_lag1"] > df["close_lag2"]
    df["up_lag2"] = df["close_lag2"] > df["close_lag3"]

    # 近 100 日下跌日数（不含今日）
    df["down_days_100"] = g["down_today"].transform(
        lambda s: s.shift(1).rolling(100, min_periods=100).sum()
    )
    # 今日涨幅
    df["today_ret"] = df["close"] / df["prev_close"] - 1

    return df


def select_entries(panel_ind: pd.DataFrame) -> pd.DataFrame:
    """按 A∧B∧C 三条件命中，每日 thscode 字典序取 1 行。返回 columns=[date, thscode, score]。"""
    df = panel_ind.copy()
    df["cond_a"] = df["down_days_100"] >= 50
    df["cond_b"] = (df["ma60"] > df["ma20"]) & (df["ma20"] > df["close_lag1"])
    df["cond_c"] = df["up_today"] & df["up_lag1"] & df["up_lag2"]
    # cond_d 移除（与反弹 3 日冗余），cond_e 移除（与 cond_b 数学互斥）—— 详见 spec §2

    df["pass"] = df["cond_a"] & df["cond_b"] & df["cond_c"]
    df["score"] = 0  # 无 MACD 打分

    hits = df[df["pass"]].copy()
    if hits.empty:
        return pd.DataFrame(columns=["date", "thscode", "score"])

    # 每日取 thscode 字典序最小的第 1 行
    hits = hits.sort_values(["date", "thscode"], ascending=[True, True])
    top = hits.groupby("date", as_index=False).first()
    return top[["date", "thscode", "score"]].reset_index(drop=True)
