"""V3a (2026-09-22, CLAUDE.md §3): Dual-Price System runtime resolver tests.

Locks the contract that:
  - price_source_for_signal="adj_close"  → signal_close() reads adj_close
  - price_source_for_execution="raw_close" → execution_close()/open() reads raw_*
  - Signal and execution get DIFFERENT prices on a dual panel where adj/raw diverge
  - Legacy single-close panel falls back to 'close' column
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from dna_data.dual_price_resolver import (
    execution_close,
    execution_open,
    signal_close,
)


# ---------- happy path: dual panel ----------

def test_signal_uses_adj_close_when_declared():
    """signal_close with price_source_for_signal='adj_close' must return adj_close."""
    row = pd.Series({
        "adj_close": 10.50,
        "raw_close": 11.20,
        "adj_open": 10.40,
        "raw_open": 11.10,
    })
    val = signal_close(row, "adj_close")
    assert val == pytest.approx(10.50), f"signal_close 应读 adj_close=10.50, got {val}"


def test_execution_uses_raw_close_when_declared():
    """execution_close with price_source_for_execution='raw_close' must return raw_close."""
    row = pd.Series({
        "adj_close": 10.50,
        "raw_close": 11.20,
    })
    val = execution_close(row, "raw_close")
    assert val == pytest.approx(11.20), f"execution_close 应读 raw_close=11.20, got {val}"


def test_execution_uses_raw_open_when_declared():
    """execution_open must mirror execution_close logic but for open column."""
    row = pd.Series({
        "adj_close": 10.50,
        "raw_close": 11.20,
        "adj_open": 10.40,
        "raw_open": 11.10,
    })
    val = execution_open(row, "raw_close")
    assert val == pytest.approx(11.10), f"execution_open 应读 raw_open=11.10, got {val}"


# ---------- dual-price divergence enforcement ----------

def test_signal_and_execution_get_different_prices_on_dual_panel():
    """V3a core invariant: signal uses adj, execution uses raw, they MUST diverge.

    这是 CLAUDE.md §3 的关键: "ALWAYS use Forward-Adjusted Prices for
    indicators, ALWAYS use Raw Prices for triggers". 当 adj=10, raw=15 (前复权
    去除一次分红), signal 必须读 10 (指标用), execution 必须读 15 (实际成交)。
    """
    row = pd.Series({
        "adj_close": 10.00,  # 前复权, 反映分红后的真实可比价格
        "raw_close": 15.00,  # raw, 实际市场成交价
        "raw_prev_close": 14.50,
    })
    sig = signal_close(row, "adj_close")
    exe = execution_close(row, "raw_close")
    assert sig == pytest.approx(10.00), f"signal 应 = 10.00 (adj), got {sig}"
    assert exe == pytest.approx(15.00), f"execution 应 = 15.00 (raw), got {exe}"
    assert math.isclose(sig, exe) is False, (
        "adj 和 raw 应不同 — 这才是 dual-price 的意义。如果相等, 复权处理未生效"
    )


# ---------- backwards compatibility: legacy panel ----------

def test_legacy_panel_falls_back_to_close_column():
    """当 panel 只有单一 close 列时, resolver 必须退回 close, 不报错。

    这是迁移期允许旧 strategy 继续运行的关键。
    """
    row = pd.Series({
        "close": 12.34,
        "open": 12.20,
    })
    sig = signal_close(row, "adj_close")  # declared adj_close 但 panel 只有 close
    exe = execution_close(row, "raw_close")  # declared raw_close 但 panel 只有 close
    assert sig == pytest.approx(12.34)
    assert exe == pytest.approx(12.34)


def test_legacy_open_fallback():
    row = pd.Series({"open": 12.20, "close": 12.34})
    val = execution_open(row, "raw_close")
    assert val == pytest.approx(12.20)


# ---------- invalid source → close fallback ----------

def test_unknown_source_falls_back_to_close():
    """未知 source (typo 等) 时不抛错, 回退到 close 列。"""
    row = pd.Series({"close": 9.99})
    val = signal_close(row, "garbage_value")
    assert val == pytest.approx(9.99)


# ---------- partial dual: adj present but raw missing ----------

def test_partial_dual_panel_execution_falls_back_to_close():
    """只有 adj_close 没有 raw_close 时, execution 回退到 close (或 adj_close)。"""
    row = pd.Series({
        "adj_close": 10.0,
        "close": 11.0,  # 假设这就是 raw
    })
    sig = signal_close(row, "adj_close")
    exe = execution_close(row, "raw_close")
    assert sig == pytest.approx(10.0)
    # raw_close 不可用 → fallback chain: raw_close (skip), close (hit)
    assert exe == pytest.approx(11.0)


def test_partial_dual_panel_signal_falls_back_to_close():
    """只有 close 没有 adj_close 时, signal 回退到 close。"""
    row = pd.Series({
        "close": 11.0,
        "raw_close": 15.0,
    })
    sig = signal_close(row, "adj_close")
    exe = execution_close(row, "raw_close")
    assert sig == pytest.approx(11.0), "adj_close 不可用 → fallback 到 close"
    assert exe == pytest.approx(15.0)


# ---------- signal-only signal source ----------

def test_signal_close_with_raw_close_source_uses_raw_close():
    """显式声明 signal_source='raw_close' (非默认) 时也正确解析。"""
    row = pd.Series({"adj_close": 10.0, "raw_close": 15.0})
    sig = signal_close(row, "raw_close")
    assert sig == pytest.approx(15.0)


# ---------- integration: real DuckDB v_daily_dual view ----------

def test_real_dual_panel_adj_raw_divergence_enforced():
    """Real DuckDB v_daily_dual: adj_close 与 raw_close 必须真实发散。

    CLAUDE.md §3 要求 indicator 用 adj, trigger 用 raw — 这意味着对
    真实 A 股历史数据, signal_close() 和 execution_close() 必须返回
    不同值。这是 runtime integration 的 smoke test。
    """
    from hiagent_config import DB_PATH
    if not DB_PATH.exists():
        pytest.skip("需要 hiagent_config.DB_PATH (real DuckDB)")
    from dna_data.dual_price import load_dual_price_panel
    panel = load_dual_price_panel("2025-09-01", "2025-09-05")
    if panel.empty:
        pytest.skip("v_daily_dual 返回空")
    # 至少一行 adj_close 与 raw_close 不同
    diff_rows = panel[
        (panel["adj_close"].notna())
        & (panel["raw_close"].notna())
        & (panel["adj_close"] != panel["raw_close"])
    ]
    assert len(diff_rows) > 0, (
        "v_daily_dual 数据似乎没有真实复权调整 — 违反 CLAUDE.md §3 reality mapping"
    )
    # 验证 resolver 真实读到不同价格
    sample = diff_rows.iloc[0]
    sig = signal_close(sample, "adj_close")
    exe = execution_close(sample, "raw_close")
    assert sig != exe, (
        f"resolver 应读到不同值 (adj={sig}, raw={exe}), 但 {sig} == {exe}"
    )
    # adj 必须等于 row.adj_close, raw 必须等于 row.raw_close
    assert sig == pytest.approx(float(sample["adj_close"]))
    assert exe == pytest.approx(float(sample["raw_close"]))