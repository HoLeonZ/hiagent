"""指标计算 + 追涨入场信号(平台突破 + 动量加速 + 均线金叉 OR 融合)。

compute_indicators — 全部基于历史窗口,信号日 T 收盘后即可算出,无未来函数。
select_entries     — 任一子信号触发即入选;score = max(子信号强度)。

信号语义:
  T 日收盘满足任一子信号 → T+1 开盘买入(由 portfolio.py 执行)。

三个子信号:
  A 平台突破 (breakout)  — close > 20 日新高 + 量比 ≥ 1.5 + close > MA60
  B 动量加速 (momentum)  — ret1 ∈ [+3%, +8%] + MACD 柱状扩张 + DIF/DEA > 0 + 量比 ≥ 1.3
  C 均线金叉 (ma_cross)  — 近 5 日内 MA20 上穿 MA60 + close > MA20 × 1.02 + 量比 ≥ 1.2

信号级硬过滤:
  mom120 ≥ 0.05            — 中期动量,过滤弱势股
  amount60 ∈ [3e7, 3e8]    — 流动性沿用 v33 经验
  atr_pct ∈ [0.03, 0.10]   — 排除僵死或过激
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ENTRY_COLS = [
    "date", "thscode", "score", "sub_signal_type",
    "sig_close", "sig_ma20", "sig_ma60", "sig_ret1",
    "sig_breakout_score", "sig_momentum_score", "sig_macross_score",
    "sig_mom120", "sig_amount60", "atr_pct",
]


def compute_indicators(panel: pd.DataFrame) -> pd.DataFrame:
    """追加均线/动量/波动/流动性/平台突破/MACD 等指标列。

    输入需含 [thscode, date, open, high, low, close, volume, amount]。
    所有 rolling/shift 均按 thscode 分组,不存在跨股票泄露 (P7)。
    """
    df = panel.copy()
    df = df.sort_values(["thscode", "date"]).reset_index(drop=True)
    g = df.groupby("thscode", group_keys=False)

    # --- 均线 ---
    for w in (5, 10, 20, 60, 120):
        df[f"ma{w}"] = g["close"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).mean()
        )

    # --- 日收益 ---
    prev_close = g["close"].shift(1)
    df["prev_close"] = prev_close
    df["ret1"] = (df["close"] - prev_close) / prev_close

    # --- 中期动量 ---
    df["mom120"] = df["close"] / g["close"].shift(120) - 1.0

    # --- 流动性:60 日均成交额 ---
    df["amount60"] = g["amount"].transform(
        lambda s: s.rolling(60, min_periods=60).mean()
    )

    # --- 量能:当日量 / 20 日均量 ---
    df["vol_ma20"] = g["volume"].transform(
        lambda s: s.rolling(20, min_periods=20).mean()
    )
    df["vol_ratio"] = df["volume"] / df["vol_ma20"]

    # --- 平台突破:近 20 日最高价 ---
    df["high20"] = g["high"].transform(
        lambda s, w=20: s.rolling(w, min_periods=w).max()
    )
    # 排除当日自身,用 shift(1) 取前 19 日 max
    df["high20_prev"] = g["high"].transform(
        lambda s: s.rolling(20, min_periods=20).max()
    ).groupby(df["thscode"]).shift(1)
    df["breakout_amount"] = (df["close"] > df["high20_prev"]).astype(float)

    # --- ATR14 ---
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

    # --- MACD(12/26/9 EMA) ---
    df["ema12"] = g["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    df["ema26"] = g["close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())
    df["macd_dif"] = df["ema12"] - df["ema26"]
    df["macd_dea"] = g["macd_dif"].transform(lambda s: s.ewm(span=9, adjust=False).mean())
    df["macd_bar"] = df["macd_dif"] - df["macd_dea"]
    df["macd_bar_prev"] = g["macd_bar"].shift(1)

    # --- MA20/MA60 近 5 日金叉判定 ---
    # ma_cross_recent = 今天或近 5 日 (T-4..T) 存在 ma20 <= ma60,今天 ma20 > ma60
    # 用 rolling 5 日的 min/max 来快速判定
    df["ma20_minus_ma60"] = df["ma20"] - df["ma60"]
    df["ma20_minus_ma60_prev5_min"] = (
        g["ma20_minus_ma60"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).min())
    )
    df["ma_cross_recent"] = (
        (df["ma20_minus_ma60"] > 0) & (df["ma20_minus_ma60_prev5_min"] <= 0)
    ).astype(float)

    return df


def _safe_signal_score(
    df: pd.DataFrame,
    *,
    breakout_a: bool,
    momentum_b: bool,
    macross_c: bool,
    min_mom120: float,
    min_amount: float,
    max_amount: float,
    atr_pct_low: float,
    atr_pct_high: float,
    ma20_gt_ma60: bool,
    pct_chg_low: float,
    pct_chg_high: float,
    breakout_vol_min: float,
    momentum_vol_min: float,
    macross_vol_min: float,
    start_date: str,
    end_date: str,
    close_ma60_buffer: float,
    # 强化版可选 filter(默认 False 保持向后兼容)
    require_ma60_gt_ma120: bool = False,
    require_ma60_rising: bool = False,
    ma60_slope_window: int = 20,
    # 信号强度阈值(默认 0.0 关闭,>0 过滤掉弱信号)
    # score 公式见下:子信号强度的 max,>= 此阈值的信号才入选
    min_score: float = 0.0,
    # close 持续在 MA20 上方 N 日(默认 0 = 关闭)。
    # 用法:过滤掉"刚站上 MA20 一天"的假突破,要求 trend 已经持续 N 日。
    # no-lookahead 安全:T 日用的 streak 数到 T-1 收盘为止。
    close_above_ma20_streak: int = 0,
    # 全部子信号都必须满足才入选(默认 False = OR 模式)
    # True = AND 模式:每个 ENABLED 子信号都需通过,disabled 视作 trivially true
    require_all_sub_signals: bool = False,
) -> pd.DataFrame:
    """3 子信号 OR 融合 + 信号级硬过滤,返回 hits DataFrame。"""
    # 信号级硬过滤(P0/P7/P8 不变量)
    base = (
        # mom120 ≥ min_mom120(中期动量)
        (df["mom120"] >= min_mom120)
        # ma20 > ma60(全局趋势必要 — 子信号隐含但显式声明)
        & (df["ma20"] > df["ma60"])
        # 流动性
        & (df["amount60"] >= min_amount)
        & (df["amount60"] <= max_amount)
        # 波动合理
        & (df["atr_pct"] >= atr_pct_low)
        & (df["atr_pct"] <= atr_pct_high)
        # 指标就绪
        & df["ma60"].notna()
        & df["mom120"].notna()
        & df["amount60"].notna()
        & df["atr_pct"].notna()
        & df["vol_ratio"].notna()
        & df["high20_prev"].notna()
        & df["macd_bar_prev"].notna()
        # 信号窗口
        & (df["date"] >= pd.Timestamp(start_date))
        & (df["date"] <= pd.Timestamp(end_date))
    )
    if close_ma60_buffer > 0:
        base = base & (df["close"] >= df["ma60"] * (1 + close_ma60_buffer))
    # 中长期趋势过滤:MA60 必须站在 MA120 之上 + MA60 必须上行
    # 这两个 filter 把熊市 / 弱势股里的假突破挡掉,
    # 是 chase_up 12m walkforward 2/9 → 7/9 的关键开关。
    if require_ma60_gt_ma120 and "ma120" in df.columns:
        base = base & (df["ma60"] > df["ma120"]) & df["ma120"].notna()
    if require_ma60_rising and "ma60" in df.columns:
        g = df.groupby("thscode", group_keys=False)
        ma60_prev = g["ma60"].shift(ma60_slope_window)
        base = base & (df["ma60"] > ma60_prev) & ma60_prev.notna()
    # close 持续在 MA20 上方 N 日(no-lookahead 安全:T 日用的 streak 截至 T-1)
    if close_above_ma20_streak > 0 and "ma20" in df.columns:
        above = (df["close"] > df["ma20"]).astype(int)
        # block id = 连续 above 的会话(只在 group 内部连续)
        prev_above = above.groupby(df["thscode"]).shift(1).fillna(0).astype(int)
        block = (above != prev_above).groupby(df["thscode"]).cumsum()
        # streak within each (thscode, block): cumcount + 1
        streak = above.groupby([df["thscode"], block]).cumcount() + 1
        # 取 T-1 时的 streak(shift(1))
        prev_streak = streak.groupby(df["thscode"]).shift(1)
        base = base & (prev_streak >= close_above_ma20_streak) & prev_streak.notna()

    # 子信号 A:平台突破
    sig_a = base & breakout_a & (
        (df["close"] > df["high20_prev"])  # 突破前 20 日新高(用 shift(1) 排除自身)
        & (df["close"] > df["ma60"])
        & (df["vol_ratio"] >= breakout_vol_min)
    )

    # 子信号 B:动量加速
    sig_b = base & momentum_b & (
        (df["ret1"] >= pct_chg_low)
        & (df["ret1"] <= pct_chg_high)
        & (df["macd_dif"] > 0)
        & (df["macd_dea"] > 0)
        & (df["macd_bar"].abs() > df["macd_bar_prev"].abs())  # 柱状扩张(动能增加)
        & (df["vol_ratio"] >= momentum_vol_min)
    )

    # 子信号 C:均线金叉
    sig_c = base & macross_c & (
        (df["ma_cross_recent"] == 1.0)
        & (df["close"] >= df["ma20"] * 1.02)
        & (df["vol_ratio"] >= macross_vol_min)
    )

    # 安全兜底:没有任何子信号启用 → 不入选(OR/AND 一致)
    if not any([breakout_a, momentum_b, macross_c]):
        return pd.DataFrame(columns=ENTRY_COLS)

    # 入选逻辑:
    #   默认 OR 模式      — 任一子信号触发即入选
    #   require_all=True — AND 模式:每个 ENABLED 子信号都必须通过
    #                       disabled 子信号视作 trivially true (不参与 AND 判定)
    #   例:v4 (macross_c=False) + AND 模式 → A AND B 即可 (C 关闭,不要求)
    if require_all_sub_signals:
        mask = (
            (sig_a | (not breakout_a))
            & (sig_b | (not momentum_b))
            & (sig_c | (not macross_c))
        )
    else:
        mask = sig_a | sig_b | sig_c

    if not mask.any():
        return pd.DataFrame(columns=ENTRY_COLS)

    hits = df[mask].copy()

    # 子信号分数(用 NaN 标记未触发)
    hits["sig_breakout_score"] = np.where(
        sig_a[mask],
        hits["mom120"] * 1.0 + hits["vol_ratio"] * 0.3,
        np.nan,
    )
    hits["sig_momentum_score"] = np.where(
        sig_b[mask],
        hits["ret1"] * 2.0 + hits["mom120"] * 0.5,
        np.nan,
    )
    hits["sig_macross_score"] = np.where(
        sig_c[mask],
        hits["mom120"] * 1.5 + (hits["ma20"] - hits["ma60"]) / hits["ma60"] * 5.0,
        np.nan,
    )

    # score = max(子信号分数)
    score_mat = hits[["sig_breakout_score", "sig_momentum_score", "sig_macross_score"]].to_numpy()
    hits["score"] = np.nanmax(score_mat, axis=1)

    # sub_signal_type = 命中的子信号集合("A"/"B"/"C" 拼接)
    # 必须先于 min_score 过滤,否则长度不匹配
    sub_a = sig_a[mask].to_numpy()
    sub_b = sig_b[mask].to_numpy()
    sub_c = sig_c[mask].to_numpy()
    parts = np.where(sub_a, "A", "") + np.where(sub_b, "B", "") + np.where(sub_c, "C", "")
    hits["sub_signal_type"] = parts

    # 信号强度阈值(默认 0.0 不过滤)
    if min_score > 0:
        before = len(hits)
        hits = hits[hits["score"] >= min_score].copy()
        if len(hits) < before:
            logger.info(
                "select_entries: min_score=%.2f 过滤掉 %d 个弱信号,剩 %d",
                min_score, before - len(hits), len(hits),
            )

    # 信号日快照字段
    hits["sig_close"] = hits["close"]
    hits["sig_ma20"] = hits["ma20"]
    hits["sig_ma60"] = hits["ma60"]
    hits["sig_ret1"] = hits["ret1"]
    hits["sig_mom120"] = hits["mom120"]
    hits["sig_amount60"] = hits["amount60"]

    out = hits[ENTRY_COLS].sort_values(
        ["date", "score"], ascending=[True, False]
    ).reset_index(drop=True)
    logger.info(
        "select_entries: %d 个候选信号 (A=%d B=%d C=%d)",
        len(out),
        int(sub_a.sum()), int(sub_b.sum()), int(sub_c.sum()),
    )
    return out


def select_entries(
    panel_ind: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    min_mom120: float = 0.05,
    min_amount: float = 3e7,
    max_amount: float = 3e8,
    atr_pct_low: float = 0.03,
    atr_pct_high: float = 0.10,
    close_ma60_buffer: float = 0.0,
    # 子信号 A 参数
    breakout_a: bool = True,
    breakout_vol_min: float = 1.5,
    # 子信号 B 参数
    momentum_b: bool = True,
    pct_chg_low: float = 0.03,
    pct_chg_high: float = 0.08,
    momentum_vol_min: float = 1.3,
    # 子信号 C 参数
    macross_c: bool = True,
    macross_vol_min: float = 1.2,
    # 强化版可选 filter(默认关闭)
    require_ma60_gt_ma120: bool = False,
    require_ma60_rising: bool = False,
    ma60_slope_window: int = 20,
    min_score: float = 0.0,
    close_above_ma20_streak: int = 0,
    # 全部子信号都必须满足才入选(默认 False = OR 模式)
    # True = AND 模式:每个 ENABLED 子信号都需通过
    require_all_sub_signals: bool = False,
) -> pd.DataFrame:
    """追涨 OR 融合信号 (3 子信号 + 信号级硬过滤)。

    排序分 score = max(子信号强度),portfolio 按分数降序抢占仓位。

    require_all_sub_signals=True 时切换为 AND 模式:
    所有 ENABLED 子信号 (A/B/C) 都必须通过,disabled 子信号视作 trivially true。
    例:v4 (macross_c=False) + AND → A AND B 即可 (C 关闭不参与判定)。
    """
    return _safe_signal_score(
        panel_ind,
        breakout_a=breakout_a,
        momentum_b=momentum_b,
        macross_c=macross_c,
        min_mom120=min_mom120,
        min_amount=min_amount,
        max_amount=max_amount,
        atr_pct_low=atr_pct_low,
        atr_pct_high=atr_pct_high,
        ma20_gt_ma60=True,
        pct_chg_low=pct_chg_low,
        pct_chg_high=pct_chg_high,
        breakout_vol_min=breakout_vol_min,
        momentum_vol_min=momentum_vol_min,
        macross_vol_min=macross_vol_min,
        start_date=start_date,
        end_date=end_date,
        close_ma60_buffer=close_ma60_buffer,
        require_ma60_gt_ma120=require_ma60_gt_ma120,
        require_ma60_rising=require_ma60_rising,
        ma60_slope_window=ma60_slope_window,
        min_score=min_score,
        close_above_ma20_streak=close_above_ma20_streak,
        require_all_sub_signals=require_all_sub_signals,
    )