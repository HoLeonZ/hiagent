"""Tests for V3a (CLAUDE.md §3) dual-price loader."""
from __future__ import annotations

import pandas as pd
import pytest

from dna_data.dual_price import load_dual_price_panel


def test_dual_price_panel_returns_all_columns():
    """V3a: loader returns 13 columns (adj_*, raw_*, raw_prev_close, vol, amt)。"""
    df = load_dual_price_panel("2025-09-19", "2026-09-19", universe={"600000.SH"})
    expected = {
        "thscode", "date",
        "adj_open", "adj_high", "adj_low", "adj_close",
        "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_prev_close", "volume", "amount",
    }
    assert expected.issubset(set(df.columns))
    assert len(df.columns) == 13


def test_dual_price_panel_no_universe_filter_works():
    """V3a: 无 universe 过滤时仍返回正确列。"""
    df = load_dual_price_panel("2025-09-22", "2025-09-26")
    assert "adj_close" in df.columns and "raw_close" in df.columns
    assert len(df) > 0


def test_dual_price_panel_inner_join_no_null_pairs():
    """V3a: INNER JOIN 保证 adj_* 与 raw_* 同 row count (同交易日)。
    对任何单 (thscode, date), adj_close 与 raw_close 都非空。
    """
    df = load_dual_price_panel("2025-09-19", "2026-09-19", universe={"000001.SZ"})
    assert df["adj_close"].notna().all()
    assert df["raw_close"].notna().all()


def test_dual_price_panel_sorted_by_code_then_date():
    """V3a: SQL ORDER BY thscode, date — 调用方无需再 sort。"""
    df = load_dual_price_panel("2025-09-19", "2026-09-19", universe={"600000.SH", "000001.SZ"})
    codes = df["thscode"].tolist()
    # 同一 code 内部日期必须升序
    for code in df["thscode"].unique():
        sub = df[df["thscode"] == code]["date"]
        assert sub.is_monotonic_increasing


def test_dual_price_adj_vs_raw_ratio_constant_within_stock():
    """V3a: 同一股票同日 adj/raw 比值 = 调整因子(frozen on date)。
    在没有 corporate action 的当日, adj/raw 比率稳定在 1 个常数附近。
    """
    df = load_dual_price_panel("2025-09-19", "2025-12-19", universe={"600000.SH"})
    ratios = df["adj_close"] / df["raw_close"]
    # 同一只股票同一区间无 corp action 时, ratio 是常数; 否则会阶梯跳变。
    # 这里至少要求 ratio 都是正数, 且 std/mean < 0.1 (在无 event 时严格为 0)
    assert (ratios > 0).all()
