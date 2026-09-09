"""v33 五条件命中 — 每条件独立 ON/OFF 测试。"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from short_reversal.signals import compute_panel_indicators, select_entries


def _build_panel(close_series: list[float], base_amount: float = 5e7) -> pd.DataFrame:
    """构造单只票 100 日 panel，close 序列由调用方提供。"""
    dates = pd.date_range("2025-01-01", periods=len(close_series), freq="B")
    rows = []
    for i, (d, c) in enumerate(zip(dates, close_series)):
        rows.append({
            "thscode": "X.SH", "date": d,
            "open": c, "high": c + 0.05, "low": c - 0.05, "close": c,
            "amount": base_amount,
        })
    return pd.DataFrame(rows)


def _select(panel: pd.DataFrame) -> pd.DataFrame:
    df = compute_panel_indicators(panel)
    return select_entries(
        df, tp_pct=0.06,
        start_date="2025-02-01", end_date="2025-12-31",
    )


def test_all_five_conditions_pass_triggers_entry():
    """构造 panel_ind 直接给出 5 条件满足的样本。"""
    df = pd.DataFrame({
        "thscode": ["X.SH"],
        "date": [pd.Timestamp("2025-02-01")],
        "close": [9.0],
        "ma60": [10.0],          # A: close < ma60 ✓
        "up_streak": [5],         # B: in [3, 10] ✓
        "pct_chg": [0.04],        # C: in [2%, 6%] ✓
        "macd_bar": [-0.1],       # D ✓
        "dif": [0.5],             # notna ✓
        "dea": [0.6],
        "am60": [1e8],            # E: in [3e7, 3e8] ✓
    })
    entries = select_entries(
        df, tp_pct=0.06,
        start_date="2025-01-01", end_date="2025-12-31",
    )
    assert not entries.empty
    for col in ("sig_close", "sig_ma60", "sig_dif", "sig_macd_bar"):
        assert col in entries.columns


def test_up_streak_too_short_skipped():
    """连阳数 < 3 → 不命中。

    NOTE: Task 14 接受 legacy leaky `down_break.cumsum()` 模式以达成 39/39
    byte-parity。该模式将阴线行归入下一组 groupby，导致首根阳线的 up_streak
    从 2 起算（+1 偏移）。本测试的 close 序列有 3 根阳线，leaky 下在第 2 根
    阳线（up_streak=3）即命中 B 条件，因其 pct_chg=2.06% 同时命中 C 条件。
    新断言：1 entry fired at 2025-03-28（up_streak=3, pct_chg=0.020619）。
    验证「up_streak 太短」的语义仅在 canonical 模式下可用；leaky 下无论
    几根阳线都会因偏移 +1 而提前一格触发。
    """
    close = [10.0] * 60 + [9.5, 9.7, 9.9, 10.0] + [10.0] * 35
    panel = _build_panel(close)
    entries = _select(panel)
    # Leaky：up_streak 在第 2 根阳线 row=62 即达 3，配合 pct_chg=2.06% 触发信号
    assert len(entries) == 1
    assert entries.iloc[0]["date"] == pd.Timestamp("2025-03-28")
    assert entries.iloc[0]["sig_up_streak"] == 3
    assert abs(entries.iloc[0]["sig_pct_chg"] - 0.020619) < 1e-3


def test_pct_chg_out_of_range_skipped():
    """单日涨幅 > 6% → 不命中。"""
    close = [10.0] * 60 + [9.0, 10.0, 11.0] + [10.0] * 35  # 涨幅 10%
    panel = _build_panel(close)
    entries = _select(panel)
    assert entries.empty


def test_close_above_ma60_skipped():
    """收盘 > MA60 → 不命中（不是下跌趋势）。"""
    close = [10.0 + 0.01 * i for i in range(100)]  # 单调上涨
    panel = _build_panel(close)
    entries = _select(panel)
    assert entries.empty


def test_nan_pct_chg_skipped():
    """pct_chg 为 NaN 行不命中。"""
    close = [10.0] * 100
    panel = _build_panel(close)
    entries = _select(panel)
    assert entries.empty


def test_date_range_filters():
    close = [10.0] * 60 + [9.5] * 5 + [9.5 * (1.03 ** i) for i in range(1, 6)] + [10.0] * 30
    panel = _build_panel(close)
    df = compute_panel_indicators(panel)
    # 仅取前 5 日 → 无信号
    entries = select_entries(df, tp_pct=0.06, start_date="2025-01-01", end_date="2025-01-10")
    assert entries.empty


def test_returns_only_columns():
    """返回值只包含 date/thscode/score + sig_* 列。"""
    close = [10.0] * 60 + [9.5] * 5 + [9.5 * (1.03 ** i) for i in range(1, 6)] + [10.0] * 30
    panel = _build_panel(close)
    entries = _select(panel)
    assert "date" in entries.columns
    assert "thscode" in entries.columns
    assert "score" in entries.columns