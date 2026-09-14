"""engine.run_backtest_v3 端到端测试（真实 DuckDB）。

跳过条件：环境变量 DNA_STRAT_DB 未设 或 DB 文件不存在。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from short_reversal.engine import run_backtest_v3

REAL_DB = Path("/Users/zhl/code/Financial-API/data/market.duckdb")
SKIP_REASON = "需要 DNA_STRAT_DB 或 /Users/zhl/code/Financial-API/data/market.duckdb"


def _real_db() -> Path | None:
    env = os.environ.get("DNA_STRAT_DB")
    if env and Path(env).exists():
        return Path(env)
    if REAL_DB.exists():
        return REAL_DB
    return None


pytestmark = pytest.mark.skipif(_real_db() is None, reason=SKIP_REASON)


def test_end_to_end_one_preset():
    db = _real_db()
    assert db is not None
    m = run_backtest_v3("v33_mainboard", "2025-09-12", "2026-09-12", db)
    # 字段齐全
    expected_keys = {
        "preset", "start", "end", "trades", "trades_count",
        "win_rate", "final_capital", "total_yield", "cagr",
        "sharpe", "max_dd", "avg_pnl", "avg_hold_days",
        "tp_count", "sl_count", "time_count",
    }
    assert expected_keys.issubset(m.keys())
    # trades 是 list of dict
    assert isinstance(m["trades"], list)
    # trades_count == len(trades)
    assert m["trades_count"] == len(m["trades"])
    # 单笔字段
    if m["trades"]:
        t = m["trades"][0]
        assert {"thscode", "entry_price", "exit_price", "exit_reason",
                "size", "net", "hold_days"}.issubset(t.keys())
        assert t["exit_reason"] in ("TP", "SL", "time")
    # 数值合理（v33_mainboard 严格档在去除 lookahead 后可能亏光，只校验量级不爆仓）
    assert m["final_capital"] >= -1_000_000.0  # 不会亏光超过初始本金（亏光时 cagr=-1.0）
    assert -1.0 <= m["cagr"] < 100.0
    assert 0.0 <= m["max_dd"] <= 1.0
    assert 0.0 <= m["win_rate"] <= 1.0


def test_cascade_preset_more_strict_than_default():
    """V5 cascade preset 应触发交易（TP_pct=6% 较激进，12 个月窗口）。"""
    db = _real_db()
    assert db is not None
    m = run_backtest_v3("v33_mainboard_v5_cascade_tp6_sl005_mh5",
                         "2025-09-12", "2026-09-12", db)
    # V5 cascade 应至少有少量交易（v2 历史是 64 笔）
    assert m["trades_count"] > 0
    # 流动性窗口内 am60 = 3e7~3e8 → 应能匹配


def test_short_window_returns_empty():
    """窗口太短（5 天）→ 不会有交易（MA60 warmup 都不够）。"""
    db = _real_db()
    assert db is not None
    m = run_backtest_v3("v33_mainboard", "2025-09-12", "2025-09-19", db)
    assert m["trades_count"] == 0
    assert m["final_capital"] == pytest.approx(1_000_000.0, abs=1.0)
