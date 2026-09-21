"""compute_n_way_ranking 单测。"""
from __future__ import annotations

import pandas as pd

from tools.compare_rolling_24m import compute_n_way_ranking


def _make_long() -> pd.DataFrame:
    return pd.DataFrame({
        "start": ["2024-09-18", "2024-09-18", "2024-09-18",
                  "2024-11-18", "2024-11-18", "2024-11-18"],
        "end":   ["2024-11-18", "2024-11-18", "2024-11-18",
                  "2025-01-18", "2025-01-18", "2025-01-18"],
        "preset": ["p_a", "p_b", "p_c", "p_a", "p_b", "p_c"],
        "total_yield": [0.10, 0.05, 0.20, 0.15, 0.25, 0.05],
    })


def test_ranking_picks_winner_per_window():
    df = _make_long()
    out = compute_n_way_ranking(df, ["p_a", "p_b", "p_c"])
    # 窗 1: p_c=0.20 最高; 窗 2: p_b=0.25 最高
    assert list(out["winner"]) == ["p_c", "p_b"]


def test_ranking_columns_match_presets():
    df = _make_long()
    out = compute_n_way_ranking(df, ["p_a", "p_b", "p_c"])
    for p in ("p_a", "p_b", "p_c"):
        assert f"total_yield_{p}" in out.columns
        assert f"rank_{p}" in out.columns
    assert len(out) == 2  # 2 windows
    # rank 用 dense: p_c=0.20 → 1, p_a=0.10 → 2, p_b=0.05 → 3 (窗 1)
    row0 = out.iloc[0]
    assert row0["rank_p_c"] == 1
    assert row0["rank_p_a"] == 2
    assert row0["rank_p_b"] == 3


def test_ranking_ties_handled():
    df = pd.DataFrame({
        "start": ["2024-09-18"] * 3,
        "end":   ["2024-11-18"] * 3,
        "preset": ["p_a", "p_b", "p_c"],
        "total_yield": [0.10, 0.10, 0.05],  # a/b 持平
    })
    out = compute_n_way_ranking(df, ["p_a", "p_b", "p_c"])
    # 持平 winner 取 lexicographically 最前 (p_a 在 p_b 前面)
    assert out.iloc[0]["winner"] == "p_a"
    assert out.iloc[0]["rank_p_a"] == 1
    assert out.iloc[0]["rank_p_b"] == 1
    assert out.iloc[0]["rank_p_c"] == 3
