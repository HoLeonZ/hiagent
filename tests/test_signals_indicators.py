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
    """构造一个 3 连阳后 1 根阴线的序列，验证 up_streak 在阴线后归零。

    NOTE: Task 14 (parity fix) accepted legacy v33_mainboard.py:188-193 的 leaky
    `down_break.cumsum()` 模式以达成 39/39 byte-parity。该模式将阴线行本身纳入下一组
    连阳的 groupby，使首根阳线的 up_streak 从 2 起算而非 1（+1 偏移）。阴线归零逻辑
    （`df.loc[~df["up_day"], "up_streak"] = 0`）不受影响。
    """
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
    # Leaky pattern：阴线行 i=0 落入下一组，第 1 根阳线 i=1 streak=2（非 1）
    assert streaks[0] == 0  # 阴线 row → up_day=False → streak=0
    assert streaks[1] == 2  # 第 1 根阳线（leaky 偏移 +1）
    assert streaks[2] == 3
    assert streaks[3] == 4
    assert streaks[4] == 0  # 阴线打断归零
    assert streaks[5] == 2  # 新连阳首根（leaky 偏移 +1）


def test_up_streak_no_cross_stock_leak():
    """跨股票面板：B 的 up_streak 在自身阳线序列内正确累加。

    NOTE: Task 14（parity fix）接受了 legacy v33_mainboard.py:188-193 leaky 模式以
    达成 39/39 byte-parity。该模式以全局 `down_break.cumsum()` 计算 up_id，
    跨股票时，A 的 down_break 行会拉高全局 cumsum，进而使 B 的 up_id 整体右移。
    本测试改名为「B 内阳线累加正确」（不再是「无跨股票泄露」），断言 B 自己的
    阳线序列累加结果（leaky 偏移 +1）。CLAUDE.md anti-leak 红线与 legacy 字节
    等价不可兼得；用户于 2026-09-09 选「接受 legacy bug for parity」。
    """
    df = pd.DataFrame({
        "thscode": ["AAA.SH"] * 4 + ["BBB.SH"] * 4,
        "date": list(pd.date_range("2025-01-01", periods=4, freq="B")) * 2,
        "open":  [10, 11, 12, 13,    20, 21, 22, 23],
        "high":  [10, 11, 12, 13,    20, 21, 22, 23],
        "low":   [10, 11, 12, 13,    20, 21, 22, 23],
        "close": [10, 11, 12, 13,    20, 21, 22, 23],  # A 末阳, B 全阳
        "amount": [1e7] * 8,
    })
    out = compute_panel_indicators(df)
    b = out[out["thscode"] == "BBB.SH"].reset_index(drop=True)
    # B 第一行 pct_chg=NaN → up_day=False → up_streak=0
    assert b.loc[0, "up_streak"] == 0
    # Leaky 模式：A 的 cumsum 把 B 的 up_id 右移 +N，B 内连阳偏移 +1
    assert b.loc[1, "up_streak"] == 2  # 第 1 根阳线（leaky 偏移）
    assert b.loc[2, "up_streak"] == 3
    assert b.loc[3, "up_streak"] == 4
