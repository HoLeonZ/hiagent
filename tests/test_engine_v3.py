"""engine.run_backtest_v3 端到端测试（真实 DuckDB）。

跳过条件：环境变量 DNA_STRAT_DB 未设 或 DB 文件不存在。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from short_reversal.engine import run_backtest_v3

from hiagent_config import get_db_path

REAL_DB = get_db_path()
SKIP_REASON = "需要 DNA_STRAT_DB 或 hiagent_config.DEFAULT_DB_PATH"


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
    m = run_backtest_v3(
        "v33_mainboard_tp6_sl005_mh5_realistic", "2025-09-12", "2026-09-12", db
    )
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
    # 数值合理：保留的 preset 在 12 个月窗口下应盈利。
    # 注：realistic preset 用 position_fraction=1.0 + TP/SL=6%/0.05% 满仓复利，
    # 12 个月 CAGR 可远超 100%，故不上限卡死（仍保留 ≥0 防止符号错位）。
    assert m["final_capital"] > 0
    assert 0.0 <= m["cagr"] < 1000.0
    assert 0.0 <= m["max_dd"] <= 1.0
    assert 0.0 <= m["win_rate"] <= 1.0


def test_high_cagr_preset_profitable():
    """tp6_sl005_mh5_realistic preset 应触发交易且 CAGR 为正。"""
    db = _real_db()
    assert db is not None
    m = run_backtest_v3(
        "v33_mainboard_tp6_sl005_mh5_realistic", "2025-09-12", "2026-09-12", db
    )
    # 高 CAGR preset 在 12 个月窗口下应有交易且总收益为正
    assert m["trades_count"] > 0
    assert m["final_capital"] > 1_000_000.0


def test_short_window_returns_empty():
    """窗口太短（5 天）→ 不会有交易（MA60 warmup 都不够）。"""
    db = _real_db()
    assert db is not None
    m = run_backtest_v3(
        "v33_mainboard_tp6_sl005_mh5_realistic", "2025-09-12", "2025-09-19", db
    )
    assert m["trades_count"] == 0
    assert m["final_capital"] == pytest.approx(1_000_000.0, abs=1.0)
