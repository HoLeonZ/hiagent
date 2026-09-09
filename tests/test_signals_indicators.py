"""compute_panel_indicators 行为正确性 + 无未来泄露。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from short_reversal.signals import compute_panel_indicators


def test_indicators_columns_present(synthetic_panel: pd.DataFrame):
    df = compute_panel_indicators(synthetic_panel)
    expected = {"ma20", "ma60", "ema12", "ema26", "dif", "dea",
                "macd_bar", "pct_chg", "am60", "up_streak"}
    assert expected.issubset(set(df.columns))


def test_ma20_first_19_rows_are_nan(synthetic_panel: pd.DataFrame):
    df = compute_panel_indicators(synthetic_panel)
    # 每只股票的前 19 行 ma20 为 NaN
    for code, sub in df.groupby("thscode"):
        assert sub["ma20"].iloc[:19].isna().all()
        assert not sub["ma20"].iloc[19:].isna().any()


def test_ma60_first_59_rows_are_nan(synthetic_panel: pd.DataFrame):
    df = compute_panel_indicators(synthetic_panel)
    for code, sub in df.groupby("thscode"):
        assert sub["ma60"].iloc[:59].isna().all()
        assert not sub["ma60"].iloc[59:].isna().any()


def test_pct_chg_uses_prev_close_not_future(synthetic_panel: pd.DataFrame):
    df = compute_panel_indicators(synthetic_panel)
    # pct_chg[0] 应为 NaN（无前一交易日）
    first = df.groupby("thscode").head(1).iloc[0]
    assert pd.isna(first["pct_chg"])
    # pct_chg[1] = (close[1] - close[0]) / close[0]
    second = df.groupby("thscode").nth(1).iloc[0]
    expected = (second["close"] - first["close"]) / first["close"]
    assert abs(second["pct_chg"] - expected) < 1e-9


def test_macd_bar_formula(synthetic_panel: pd.DataFrame):
    df = compute_panel_indicators(synthetic_panel)
    # macd_bar = 2 * (dif - dea)
    valid = df.dropna(subset=["macd_bar"])
    diff = (valid["macd_bar"] - 2 * (valid["dif"] - valid["dea"])).abs()
    assert diff.max() < 1e-9


def test_up_streak_resets_on_down_day():
    """构造一个 3 连阳后 1 根阴线的序列，验证 up_streak 在阴线后归零。"""
    import pandas as pd
    df = pd.DataFrame({
        "thscode": ["X.SH"] * 6,
        "date": pd.date_range("2025-01-01", periods=6, freq="B"),
        "open":  [10, 11, 12, 13, 12, 13],  # 阴线在 i=4
        "high":  [10, 11, 12, 13, 12, 13],
        "low":   [10, 11, 12, 13, 12, 13],
        "close": [10, 11, 12, 13, 12, 13],  # close[4]=12 < close[3]=13 阴线
        "amount": [1e7] * 6,
    })
    out = compute_panel_indicators(df)
    streaks = out["up_streak"].tolist()
    assert streaks[0] == 0  # pct_chg=NaN, up_day=False → streak=0
    assert streaks[1] == 1  # 第一根阳线
    assert streaks[2] == 2
    assert streaks[3] == 3
    assert streaks[4] == 0  # 阴线打断
    assert streaks[5] == 1  # 新连阳开始
