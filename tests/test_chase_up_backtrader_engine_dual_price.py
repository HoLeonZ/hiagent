"""chase_up/backtrader_engine.py 必须走 Layout A 双价格域 (CLAUDE.md §3).

chase_up 22 preset 默认 price_source_for_execution="raw_close" 但 backtrader engine
直接用 span[open/high/low/close] (qfq 列),导致 Phase 2 backtrader exit 触发逻辑
跑在 qfq 价格域,与 Phase 1 entry 用 raw_open 不对齐 → phantom TP/SL。

对照 uptrend_pullback/backtrader_engine.py:115-132 的 Layout A 修复。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chase_up.backtrader_engine import _build_bt_feed


class TestChaseUpBacktraderFeedDualPrice:
    """_build_bt_feed 必须遵循 price_source_for_execution (CLAUDE.md §3)。"""

    def test_raw_close_feed_uses_raw_prices(self):
        """raw_close 价格源: feed 必须用 raw_open/high/low/close,不可用 qfq (span[*])。

        关键防护: qfq (panel['open']/'high']/'low']/'close']) 与 raw_* 显著不一致时,
        feed 不能继续用 qfq,否则 ChaseUpTradeReplay 跑在 qfq 域 → phantom SL/TP。
        复现的 bug: v3 backtrader output 出现 exit_px ≈ qfq_open (31.6478) 而 raw_open=32.0。
        """
        span = pd.DataFrame({
            "date": pd.to_datetime(["2025-10-22", "2025-10-23", "2025-10-24"]),
            "open":  [10.0, 11.0, 12.0],       # qfq (前复权), 远小于 raw
            "high":  [10.5, 11.5, 12.5],
            "low":   [9.5, 10.5, 11.5],
            "close": [10.2, 11.2, 12.2],
            "raw_open":  [32.0, 33.0, 31.0],
            "raw_high":  [32.5, 33.5, 31.5],
            "raw_low":   [31.5, 32.5, 30.5],
            "raw_close": [32.2, 33.2, 31.2],
            "raw_prev_close": [31.8, 32.2, 33.2],
            "volume": [1000, 1000, 1000],
        })
        feed = _build_bt_feed(span, "raw_close")
        # raw_* 必须胜出,qfq 不可污染 feed
        assert feed.loc["2025-10-22", "open"] == 32.0, (
            f"phantom 防护: feed.open 必须 = raw_open (32.0), 不是 qfq open (10.0)。"
            f"实际拿到 {feed.loc['2025-10-22', 'open']}"
        )
        assert feed.loc["2025-10-22", "low"] == 31.5
        assert feed.loc["2025-10-22", "high"] == 32.5
        assert feed.loc["2025-10-23", "open"] == 33.0
        assert feed.loc["2025-10-23", "low"] == 32.5

    def test_adj_close_feed_uses_qfq_prices(self):
        """adj_close (默认): feed 用 span[open/high/low/close] (qfq 列)。

        这是 chase_up 当前行为,保留作为向后兼容。
        """
        span = pd.DataFrame({
            "date": pd.to_datetime(["2025-10-22", "2025-10-23"]),
            "open":  [10.0, 11.0],
            "high":  [10.5, 11.5],
            "low":   [9.5, 10.5],
            "close": [10.2, 11.2],
            "raw_open":  [32.0, 33.0],
            "raw_high":  [32.5, 33.5],
            "raw_low":   [31.5, 32.5],
            "raw_close": [32.2, 33.2],
            "volume": [1000, 1000],
        })
        feed = _build_bt_feed(span, "adj_close")
        assert feed.loc["2025-10-22", "open"] == 10.0
        assert feed.loc["2025-10-22", "low"] == 9.5

    def test_no_raw_columns_falls_back_to_qfq(self):
        """raw_* 列缺失时: 即使声明 raw_close, 回退到 span[open/high/low/close]。

        与 portfolio.py:simulate_portfolio 的 best-effort 行为一致。
        """
        span = pd.DataFrame({
            "date": pd.to_datetime(["2025-10-22", "2025-10-23"]),
            "open":  [10.0, 11.0],
            "high":  [10.5, 11.5],
            "low":   [9.5, 10.5],
            "close": [10.2, 11.2],
            "volume": [1000, 1000],
            # 无 raw_* 列
        })
        feed = _build_bt_feed(span, "raw_close")
        assert feed.loc["2025-10-22", "open"] == 10.0
        assert feed.loc["2025-10-22", "low"] == 9.5

    def test_feed_index_is_date_typed_and_sorted(self):
        """回归保护: feed.index 必须是 datetime,且按时间升序 (backtrader 要求)。"""
        span = pd.DataFrame({
            "date": pd.to_datetime(["2025-10-22", "2025-10-23"]),
            "open":  [10.0, 11.0],
            "high":  [10.5, 11.5],
            "low":   [9.5, 10.5],
            "close": [10.2, 11.2],
            "raw_open":  [32.0, 33.0],
            "raw_high":  [32.5, 33.5],
            "raw_low":   [31.5, 32.5],
            "raw_close": [32.2, 33.2],
            "volume": [1000, 1000],
        })
        feed = _build_bt_feed(span, "raw_close")
        assert isinstance(feed.index, pd.DatetimeIndex)
        assert feed.index.is_monotonic_increasing


class TestChaseUpBacktraderFeedRawPriceAlignment:
    """raw_close 路径下, feed 必须与 entry 用 raw_open 的 portfolio.py 对齐。"""

    def test_raw_open_matches_portfolio_entry(self):
        """feed 第一根 bar 的 open 必须与 portfolio.py entry_price 同源 (raw_open)。

        防回归: portfolio.py 在 raw_close 模式下 entry_price = raw_open (commit 86832f7),
        backtrader feed 在 raw_close 模式下 open 也必须 = raw_open — 否则 Phase 1 / Phase 2
        口径不一,产生 phantom。
        """
        raw_open = 32.0
        span = pd.DataFrame({
            "date": pd.to_datetime(["2025-10-22", "2025-10-23", "2025-10-24"]),
            "open":  [10.0, 11.0, 12.0],   # qfq
            "high":  [10.5, 11.5, 12.5],
            "low":   [9.5, 10.5, 11.5],
            "close": [10.2, 11.2, 12.2],
            "raw_open":  [raw_open, 33.0, 31.0],
            "raw_high":  [32.5, 33.5, 31.5],
            "raw_low":   [31.5, 32.5, 30.5],
            "raw_close": [32.2, 33.2, 31.2],
            "volume": [1000, 1000, 1000],
        })
        feed = _build_bt_feed(span, "raw_close")
        # 假设 portfolio.py 在 entry_date 用 raw_open=32.0 (price_source=raw_close),
        # backtrader entry bar 也必须用 raw_open=32.0 — 不能用 qfq 10.0
        assert feed.iloc[0]["open"] == raw_open, (
            "backtrader feed 与 portfolio entry 必须 raw 同源 — 否则 Phase 1/2 phantom"
        )