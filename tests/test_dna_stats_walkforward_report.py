"""Tests for V7 walkforward_report DSR/Bonferroni formatting."""
from __future__ import annotations

import pandas as pd
import pytest

from dna_stats.walkforward_report import format_walkforward_stats


def test_format_empty_returns_marker():
    """V7: 空 DataFrame 返回 marker。"""
    out = format_walkforward_stats(pd.DataFrame(), n_comparisons=10)
    assert "(empty" in out


def test_format_basic_columns():
    """V7: 必有窗口数 + Sharpe DSR + Bonferroni 字段。"""
    df = pd.DataFrame({
        "total_return": [0.10, 0.20, -0.05, 0.15, 0.25],
        "sharpe": [1.5, 2.0, 0.5, 1.8, 2.3],
        "max_dd": [-0.10, -0.15, -0.20, -0.12, -0.08],
        "trades": [10, 12, 8, 11, 13],
    })
    out = format_walkforward_stats(df, n_comparisons=50)
    assert "窗口 5" in out
    assert "DSR" in out
    assert "Bonferroni" in out
    assert "k=50" in out


def test_format_more_trials_lower_dsr():
    """V7: n_comparisons 越大, DSR 越低 (selection bias 严)。"""
    df = pd.DataFrame({
        "total_return": [0.10] * 12,
        "sharpe": [2.0] * 12,
    })
    out_1 = format_walkforward_stats(df, n_comparisons=1)
    out_1000 = format_walkforward_stats(df, n_comparisons=1000)
    # Extract DSR from output strings
    import re
    def extract_dsr(s):
        m = re.search(r"DSR\([^)]+\)\s*=\s*([\d.]+)", s)
        return float(m.group(1)) if m else None
    assert extract_dsr(out_1) > extract_dsr(out_1000)


def test_format_missing_columns_no_crash():
    """V7: 缺列时优雅降级。"""
    df = pd.DataFrame({"total_return": [0.10, 0.20]})    # 缺 sharpe/max_dd
    out = format_walkforward_stats(df, n_comparisons=10)
    assert "窗口 2" in out
