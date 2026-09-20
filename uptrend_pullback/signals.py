"""指标计算 + 上升趋势回调做多入场信号。

compute_indicators — 全部基于历史窗口，信号日 T 收盘后即可算出，无未来函数。
select_entries     — 趋势 ∧ 回调 ∧ 反转确认 ∧ 未破位 ∧ 流动性 ∧ 大盘择时。

信号语义：
  T 日收盘满足全部条件 → T+1 开盘买入（由 portfolio.py 执行）。

entry_mode:
  "dip"      — 回调途中直接买（接刀，基线用）
  "reversal" — 回调后出现第一根阳线再买（默认，等反转确认）
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ENTRY_COLS = [
    "date", "thscode", "score",
    "sig_close", "sig_ma20", "sig_ma60", "sig_down_streak",
    "sig_pullback", "sig_mom120", "sig_amount60", "atr_pct",
]


def compute_indicators(panel: pd.DataFrame) -> pd.DataFrame:
    """追加均线/回调/动量/波动/流动性列。

    输入需含 [thscode, date, open, high, low, close, volume, amount]。
    所有 rolling/shift 均按 thscode 分组，不存在跨股票泄露。
    """
    df = panel.copy()
    df = df.sort_values(["thscode", "date"]).reset_index(drop=True)
    g = df.groupby("thscode", group_keys=False)

    # --- 均线 ---
    for w in (5, 10, 20, 60, 120):
        df[f"ma{w}"] = g["close"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).mean()
        )
    df["above_ma20"] = (df["close"] > df["ma20"]).astype(float)

    # --- 日收益（基于前一根 K 线收盘）---
    prev_close = g["close"].shift(1)
    df["prev_close"] = prev_close
    df["ret1"] = (df["close"] - prev_close) / prev_close

    # --- 趋势持续性：过去 60 日中 close > MA60 的占比 ---
    df["above_ma60"] = (df["close"] > df["ma60"]).astype(float)
    df["above_ma60_ratio"] = g["above_ma60"].transform(
        lambda s: s.rolling(60, min_periods=60).mean()
    )

    # --- 连阴计数：cumsum 按 thscode 分组，避免跨股票串联 ---
    df["down_day"] = df["ret1"] < 0          # NaN 比较结果为 False
    df["up_break"] = (~df["down_day"]).astype(int)
    df["down_id"] = df.groupby("thscode")["up_break"].cumsum()
    df["down_streak"] = df.groupby(["thscode", "down_id"]).cumcount() + 1
    df.loc[~df["down_day"], "down_streak"] = 0
    df["prev_down_streak"] = g["down_streak"].shift(1)

    # --- 回调深度：距近 20 日最高价的跌幅（负值）---
    df["high20"] = g["high"].transform(
        lambda s: s.rolling(20, min_periods=20).max()
    )
    df["pullback"] = df["close"] / df["high20"] - 1.0

    # --- 中期动量（排序分）：120 日涨幅 ---
    df["mom120"] = df["close"] / g["close"].shift(120) - 1.0

    # --- 流动性：60 日均成交额 ---
    df["amount60"] = g["amount"].transform(
        lambda s: s.rolling(60, min_periods=60).mean()
    )

    # --- 量能：当日量 / 20 日均量 ---
    df["vol_ma20"] = g["volume"].transform(
        lambda s: s.rolling(20, min_periods=20).mean()
    )
    df["vol_ratio"] = df["volume"] / df["vol_ma20"]

    # --- ATR14（真实波幅）→ 自适应止损用 ---
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            (df["high"] - df["prev_close"]).abs(),
            (df["low"] - df["prev_close"]).abs(),
        ),
    )
    df["tr"] = tr
    df["atr14"] = g["tr"].transform(lambda s: s.rolling(14, min_periods=14).mean())
    df["atr_pct"] = df["atr14"] / df["close"]

    # --- MACD（12/26/9 EMA, mirror of short_reversal v33 D 条件）---
    # 严格按 thscode 分组,避免跨股票泄漏
    df["ema12"] = g["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    df["ema26"] = g["close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())
    df["macd_dif"] = df["ema12"] - df["ema26"]
    df["macd_dea"] = g["macd_dif"].transform(lambda s: s.ewm(span=9, adjust=False).mean())
    df["macd_bar"] = df["macd_dif"] - df["macd_dea"]
    df["macd_bar_prev"] = g["macd_bar"].shift(1)

    return df


def select_entries(
    panel_ind: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    entry_mode: str = "reversal",
    min_down_streak: int = 2,
    max_down_streak: int = 5,
    min_pullback: float = 0.03,
    max_pullback: float = 0.14,
    ma20_tol: float = 0.04,
    min_amount: float = 3e7,
    max_amount: float = 3e8,
    min_above_ma60_ratio: float = 0.6,
    min_mom120: float = 0.0,
    max_vol_ratio: float = 2.0,
    max_atr_pct: float = 0.10,
    # 趋势质量增强：解决"贴着均线、MA60 平走"等伪趋势
    close_ma60_buffer: float = 0.0,
    ma60_rising_lookback: int = 0,
    regime_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """上升趋势回调做多信号。

    A. 趋势在上：close > MA60、MA20 > MA60、过去 60 日 close>MA60 占比 ≥ 阈值、
                 120 日动量 ≥ 阈值
       （可选）close ≥ MA60 × (1 + close_ma60_buffer)，
       （可选）MA60 在 ma60_rising_lookback 日内上行
    B. 回调到位：连阴 ∈ [min, max]（reversal 模式看前一日连阴，当日收阳）
    C. 回调可控：距 20 日高点跌幅 ∈ [min_pullback, max_pullback]
    D. 未破位　：close ≥ MA20 × (1 - ma20_tol)，量能 ≤ max_vol_ratio，
                 ATR% ≤ max_atr_pct
    E. 流动性　：60 日均成交额 ∈ [min_amount, max_amount]
    F. 大盘择时：regime_df.regime_ok 为真（可选）

    排序分 score = mom120，portfolio 按分数降序抢占仓位。
    """
    if entry_mode not in ("dip", "reversal"):
        raise ValueError(f"entry_mode must be 'dip' or 'reversal', got {entry_mode!r}")

    df = panel_ind

    if entry_mode == "reversal":
        # 前一日处于连阴，当日收阳 → 反转确认
        streak_ok = (
            (df["prev_down_streak"] >= min_down_streak)
            & (df["prev_down_streak"] <= max_down_streak)
            & (df["ret1"] > 0)
        )
    else:
        streak_ok = (
            (df["down_streak"] >= min_down_streak)
            & (df["down_streak"] <= max_down_streak)
        )

    mask = (
        # A —— 上升趋势
        (df["close"] > df["ma60"])
        & (df["ma20"] > df["ma60"])
        & (df["above_ma60_ratio"] >= min_above_ma60_ratio)
        & (df["mom120"] >= min_mom120)
    )
    # A' —— 趋势质量增强（可选）
    if close_ma60_buffer > 0:
        mask = mask & (df["close"] >= df["ma60"] * (1 + close_ma60_buffer))
    if ma60_rising_lookback > 0:
        # 用 transform shift 比较严格按组，避免跨股票泄漏
        ma60_now = df["ma60"]
        ma60_prev = df.groupby("thscode")["ma60"].shift(ma60_rising_lookback)
        mask = mask & (ma60_now > ma60_prev)
    mask = mask & (
        # B —— 回调 / 反转
        streak_ok
        # C —— 回调幅度可控
        & (df["pullback"] <= -min_pullback)
        & (df["pullback"] >= -max_pullback)
        # D —— 趋势未破 + 量能 + 波动
        & (df["close"] >= df["ma20"] * (1 - ma20_tol))
        & (df["vol_ratio"] <= max_vol_ratio)
        & (df["atr_pct"] <= max_atr_pct)
        # E —— 流动性
        & (df["amount60"] >= min_amount)
        & (df["amount60"] <= max_amount)
        # 指标就绪
        & df["ma120"].notna()
        & df["mom120"].notna()
        & df["amount60"].notna()
        & df["vol_ratio"].notna()
        & df["atr_pct"].notna()
        # 信号窗口
        & (df["date"] >= pd.Timestamp(start_date))
        & (df["date"] <= pd.Timestamp(end_date))
    )

    hits = df[mask].copy()

    # F —— 大盘择时
    if regime_df is not None and not hits.empty:
        ok_days = set(
            pd.to_datetime(regime_df.loc[regime_df["regime_ok"], "date"]).tolist()
        )
        hits = hits[hits["date"].isin(ok_days)]

    if hits.empty:
        return pd.DataFrame(columns=ENTRY_COLS)

    hits["score"] = hits["mom120"]
    hits["sig_close"] = hits["close"]
    hits["sig_ma20"] = hits["ma20"]
    hits["sig_ma60"] = hits["ma60"]
    hits["sig_down_streak"] = hits["down_streak"]
    hits["sig_pullback"] = hits["pullback"]
    hits["sig_mom120"] = hits["mom120"]
    hits["sig_amount60"] = hits["amount60"]

    out = hits[ENTRY_COLS].sort_values(
        ["date", "score"], ascending=[True, False]
    ).reset_index(drop=True)
    logger.info("select_entries: %d 个候选信号", len(out))
    return out


def select_entries_v33_long_mirror(
    panel_ind: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    min_down_streak: int = 3,
    max_down_streak: int = 10,
    pct_chg_low: float = -0.07,
    pct_chg_high: float = -0.02,
    min_amount: float = 3e7,
    max_amount: float = 3e8,
    min_above_ma60_ratio: float = 0.6,
    regime_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """做多镜像信号 — 与 short_reversal v33 mainboard tp6 的5条件严格对应。

    short_reversal v33 (做空):
      A: close < MA60  ∧ below_ma60_ratio_60 ≥ 60%
      B: up_streak ∈ [3, 10]
      C: ret1 ∈ [+2%, +7%]
      D: MACD dif<0 ∧ dea<0 ∧ |bar| < |prev_bar|
      E: am60 ∈ [3e7, 3e8]

    mirror (本函数):
      A: close > MA60  ∧ above_ma60_ratio   ≥ 60%
      B: down_streak ∈ [3, 10]
      C: ret1 ∈ [-7%, -2%]
      D: MACD dif>0 ∧ dea>0 ∧ |bar| > |prev_bar|
      E: amount60 ∈ [3e7, 3e8]
    """
    df = panel_ind
    mask = (
        # A —— 上升趋势
        (df["close"] > df["ma60"])
        & (df["above_ma60_ratio"] >= min_above_ma60_ratio)
        # B —— 连阴 (pullback within uptrend)
        & (df["down_streak"] >= min_down_streak)
        & (df["down_streak"] <= max_down_streak)
        # C —— 今日跌幅 (rip-down after run-up)
        & (df["ret1"] >= pct_chg_low)
        & (df["ret1"] <= pct_chg_high)
        # D —— MACD 动能上升 (在上升趋势中意味着加速)
        & (df["macd_dif"] > 0)
        & (df["macd_dea"] > 0)
        & (df["macd_bar"].abs() > df["macd_bar_prev"].abs())
        # E —— 流动性
        & (df["amount60"] >= min_amount)
        & (df["amount60"] <= max_amount)
        # 指标就绪
        & df["ma60"].notna()
        & df["above_ma60_ratio"].notna()
        & df["amount60"].notna()
        & df["macd_bar"].notna()
        & df["macd_bar_prev"].notna()
        # 信号窗口
        & (df["date"] >= pd.Timestamp(start_date))
        & (df["date"] <= pd.Timestamp(end_date))
    )

    hits = df[mask].copy()

    # 大盘择时 (与 select_entries 同口径, regime_df 非空时过滤)
    if regime_df is not None and not hits.empty:
        ok_days = set(
            pd.to_datetime(regime_df.loc[regime_df["regime_ok"], "date"]).tolist()
        )
        hits = hits[hits["date"].isin(ok_days)]

    if hits.empty:
        return pd.DataFrame(columns=ENTRY_COLS)

    # score = mom120 (与 v6 一致,portfolio 按分数降序抢占仓位)
    hits["score"] = hits["mom120"]
    hits["sig_close"] = hits["close"]
    hits["sig_ma20"] = hits["ma20"]
    hits["sig_ma60"] = hits["ma60"]
    hits["sig_down_streak"] = hits["down_streak"]
    hits["sig_pullback"] = hits["pullback"]
    hits["sig_mom120"] = hits["mom120"]
    hits["sig_amount60"] = hits["amount60"]

    out = hits[ENTRY_COLS].sort_values(
        ["date", "score"], ascending=[True, False]
    ).reset_index(drop=True)
    logger.info("select_entries_v33_long_mirror: %d 个候选信号", len(out))
    return out
