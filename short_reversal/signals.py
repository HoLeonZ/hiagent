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
    df["am60"] = g["turnover"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    # 趋势持续性辅助：A 条件要求过去 60 日中 close < MA60 的占比 ≥ 60%
    # 前 60 行 NaN（rolling 需满窗口），信号日 MA60 已就绪时本列也已就绪
    df["below_ma60"] = (df["close"] < df["ma60"]).astype(float)
    df["below_ma60_ratio_60"] = g["below_ma60"].transform(
        lambda s: s.rolling(60, min_periods=60).mean()
    )

    # 连阳计数：up_day=True 时累加，遇到阴线/NaN 重置
    df["up_day"] = (df["pct_chg"] > 0).fillna(False)
    # Task 14 R1 — match legacy v33_mainboard.py:188-193 cumsum of down_break
    df["down_break"] = (~df["up_day"]).astype(int)
    df["up_id"] = df["down_break"].cumsum()
    df["up_streak"] = df.groupby(["thscode", "up_id"]).cumcount() + 1
    df.loc[~df["up_day"], "up_streak"] = 0

    return df


def select_entries(
    panel_ind: pd.DataFrame,
    *,
    tp_pct: float,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """v33 五条件命中。

    A. close < MA60                       （下跌趋势 + 100 日数据确认：
                                            过去 60 日中 close < MA60 的天数占比 ≥ 60%）
    B. up_streak ∈ [3, 10]                （连阳）
    C. pct_chg ∈ [2%, 6%]                 （反弹幅度）
    D. DIF < 0 & DEA < 0 & |macd_bar| 缩  （空头区域反弹衰竭：MACD 在零轴下方，
                                            柱绝对值缩短 — 反弹开始衰减）
    E. am60 ∈ [3e7, 3e8]                  （流动性）

    历史：D 条件原为 DIF/DEA > 0（在多头区域做空），回测 CAGR = -8%；
    改为 DIF/DEA < 0 后 CAGR 反转到 +52%（2018-2025，TP4%/SL2%/mh=8）。

    返回 columns=[date, thscode, score, sig_close, sig_ma60, sig_dif, sig_dea,
                   sig_macd_bar, sig_up_streak, sig_pct_chg, sig_max_dt]
    """
    df = panel_ind.copy().reset_index(drop=True)

    # D 条件方向性：DIF/DEA 在零轴上方 + MACD 柱绝对值在缩小
    df["prev_bar_abs"] = df.groupby("thscode")["macd_bar"].shift(1).abs()

    # 流动性窗口预过滤
    df = df[(df["am60"] >= 3e7) & (df["am60"] <= 3e8)]

    # 五条件命中
    hits = df[
        (df["close"] < df["ma60"])
        & (df["below_ma60_ratio_60"] >= 0.6)
        & (df["up_streak"] >= 3)
        & (df["up_streak"] <= 10)
        & (df["pct_chg"] >= 0.02)
        & (df["pct_chg"] <= 0.06)
        & (df["dif"] < 0)
        & (df["dea"] < 0)
        & (df["macd_bar"].abs() < df["prev_bar_abs"])
        & df["pct_chg"].notna()
        & df["dif"].notna()
        & df["prev_bar_abs"].notna()
        & (df["date"] >= pd.Timestamp(start_date))
        & (df["date"] <= pd.Timestamp(end_date))
    ].copy()

    if hits.empty:
        return pd.DataFrame(columns=[
            "date", "thscode", "score",
            "sig_close", "sig_ma60", "sig_dif", "sig_dea",
            "sig_macd_bar", "sig_up_streak", "sig_pct_chg", "sig_max_dt",
        ])

    # 携带 sig_* 快照（便于审计）
    hits["sig_close"] = hits["close"]
    hits["sig_ma60"] = hits["ma60"]
    hits["sig_dif"] = hits["dif"]
    hits["sig_dea"] = hits["dea"]
    hits["sig_macd_bar"] = hits["macd_bar"]
    hits["sig_up_streak"] = hits["up_streak"]
    hits["sig_pct_chg"] = hits["pct_chg"]
    hits["sig_max_dt"] = 0.0  # v33 不依赖 max_dt 阈值；保留列位以兼容审计
    hits["score"] = 0  # 无打分

    return hits[[
        "date", "thscode", "score",
        "sig_close", "sig_ma60", "sig_dif", "sig_dea",
        "sig_macd_bar", "sig_up_streak", "sig_pct_chg", "sig_max_dt",
    ]].reset_index(drop=True)
