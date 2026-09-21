"""K-line pattern detection + score (pure functions)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_k_patterns(df: pd.DataFrame) -> pd.Series:
    """Label each bar with a bullish/bearish/neutral pattern name, or None.

    All computations reference only `df` columns up to the bar being labeled.
    """
    op, hi, lo, cl = df["open"], df["high"], df["low"], df["close"]
    body = (cl - op).abs()
    rng = (hi - lo).replace(0, np.nan)
    body_ratio = body / rng

    out = pd.Series([None] * len(df), index=df.index, dtype=object)

    prev_op, prev_cl = op.shift(1), cl.shift(1)

    bullish_engulfing = (
        (prev_cl < prev_op)
        & (cl > op)
        & (cl > prev_op)
        & (op <= prev_cl)
    )
    out[bullish_engulfing] = "engulfing_bull"

    bearish_engulfing = (
        (prev_cl > prev_op)
        & (cl < op)
        & (cl < prev_op)
        & (op >= prev_cl)
    )
    out[bearish_engulfing] = "engulfing_bear"

    lower_shadow = (op.combine(cl, min) - lo).fillna(0)
    upper_shadow = (hi - op.combine(cl, max)).fillna(0)
    hammer = ((lower_shadow >= 2 * body) & (upper_shadow <= body) & (body_ratio < 0.5))
    out[hammer & (cl > op)] = "hammer"
    out[hammer & (cl <= op)] = "hanging_man"

    middle = (cl.shift(1) - op.shift(1)).abs()
    morning_star = (
        (cl.shift(2) < op.shift(2))
        & (middle / rng.shift(1).fillna(1) < 0.1)
        & (cl > op)
        & (cl > (op.shift(1) + cl.shift(1)) / 2)
    )
    out[morning_star] = "morning_star"
    evening_star = (
        (cl.shift(2) > op.shift(2))
        & (middle / rng.shift(1).fillna(1) < 0.1)
        & (cl < op)
        & (cl < (op.shift(1) + cl.shift(1)) / 2)
    )
    out[evening_star] = "evening_star"

    soldier_1 = (cl.shift(2) > op.shift(2)) & (cl.shift(1) > op.shift(1)) & (cl > op)
    soldier_2 = (cl.shift(1) > cl.shift(2)) & (cl > cl.shift(1))
    out[soldier_1 & soldier_2] = "three_white_soldiers"
    crow_1 = (cl.shift(2) < op.shift(2)) & (cl.shift(1) < op.shift(1)) & (cl < op)
    crow_2 = (cl.shift(1) < cl.shift(2)) & (cl < cl.shift(1))
    out[crow_1 & crow_2] = "three_black_crows"

    doji = body_ratio < 0.10
    out[doji & out.isna()] = "doji"

    return out


def k_line_score(df: pd.DataFrame, patterns: pd.Series) -> pd.Series:
    """Convert patterns + confluence into a numeric score per bar.

    Per-bar contributions:
        pattern match                       +1.0
        confluence at MA5/MA10/MA20 ±2%      +0.5
        volume ≥ 1.5 × MA5(volume, prev bar) +0.5
    """
    out = pd.Series(0.0, index=df.index)
    out[patterns.notna()] += 1.0

    cl = df["close"]
    ma5 = cl.rolling(5).mean()
    ma10 = cl.rolling(10).mean()
    ma20 = cl.rolling(20).mean()
    confluence = ((cl.sub(ma5).abs() / ma5 < 0.02)
                  | (cl.sub(ma10).abs() / ma10 < 0.02)
                  | (cl.sub(ma20).abs() / ma20 < 0.02))
    out[confluence.fillna(False)] += 0.5

    vol = df["volume"]
    ma5v = vol.shift(1).rolling(5).mean()
    vol_conf = vol >= 1.5 * ma5v
    out[vol_conf.fillna(False)] += 0.5

    return out.clip(-0.2, 2.5)
