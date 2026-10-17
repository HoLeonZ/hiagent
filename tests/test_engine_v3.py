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
        "v35_agg_pctchg_04_09", "2025-09-12", "2026-09-12", db
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
    """v35_agg_pctchg_04_09 preset 应触发交易且 CAGR 为正。"""
    db = _real_db()
    assert db is not None
    m = run_backtest_v3(
        "v35_agg_pctchg_04_09", "2025-09-12", "2026-09-12", db
    )
    # 高 CAGR preset 在 12 个月窗口下应有交易且总收益为正
    assert m["trades_count"] > 0
    assert m["final_capital"] > 1_000_000.0


def test_short_window_raises_instead_of_silently_returning_empty():
    """窗口短于 min_bars → 抛 ValueError，而不是返回一个空结果。

    F-01 (2026-10-17, CLAUDE.md §0 fail-fast): 面板窗口是 [start-180d, end+60d]。
    原来 len(sub) < min_bars 时静默 continue, 于是短窗口把**整个 universe**
    丢空, run_backtest_v3 返回格式完好、trades=0 / final_capital=initial 的
    结果 —— 与「市场当天没信号」在输出上完全不可区分。

    公共契约变更: 结构上不可能完成的窗口现在是 ValueError, 不是空结果。
    实机来源: end=2026-10-16 时 start=2026-07-01 的面板只有 188 bars,
    min_bars=200 把 3190 只全丢, 5.9 秒跑完、0 笔交易。
    """
    db = _real_db()
    assert db is not None
    with pytest.raises(ValueError, match="min_bars"):
        run_backtest_v3(
            "v35_agg_pctchg_04_09", "2025-09-12", "2025-09-19", db
        )


def test_short_window_raises_and_names_the_observed_bar_count():
    """错误信息必须给出实际 bar 数, 好让运维区分「配置错」与「行情静」。"""
    db = _real_db()
    assert db is not None
    with pytest.raises(ValueError) as ei:
        run_backtest_v3(
            "v35_agg_pctchg_04_09", "2025-09-12", "2025-09-19", db
        )
    msg = str(ei.value)
    assert "min_bars=200" in msg
    assert "max observed bars=" in msg
    assert "widen" in msg or "lower min_bars" in msg


def test_empty_universe_raises_named_error():
    """空 universe 必须具名抛错, 不得静默返回 0 笔 (§0, F-01 的近亲, R10)。

    load_universe_asof 用「首现日 ≤ as-of」做代理; as-of 早于数据地板
    (raw_kline_daily min(date)=2016-10-10) 时返回 []。空 universe → panel 无行
    → build_per_stock_feeds 的 `if codes and not feeds` 守卫不触发 (codes 为空)
    → cerebro 无 feed → next() 从不执行 → _metrics_from_holder 直接索引
    holder["equity_curve"] 抛裸 KeyError。该输出与「市场当天没信号」不可区分,
    故现在必须在 universe 解析后立刻具名抛错。
    """
    db = _real_db()
    assert db is not None
    with pytest.raises(ValueError, match="EMPTY universe"):
        run_backtest_v3("v50_slope", "2016-01-05", "2016-02-05", db, min_bars=150)


def test_metrics_from_holder_raises_when_equity_curve_key_missing():
    """Minor 29 (R10 的另一半): `holder["equity_curve"]` 的直接索引必须对缺键抛错。

    纯单元测试 (无需 DB 也无 backtest)。直接索引是本轮改动之一, 若被改回
    `.get("equity_curve", [])`, 缺键会静默退化成一条空曲线 —— 正是 R10 描述的
    静默失效 (`_weighted_equity_curve` 会把空曲线当成「每根 bar 都还没跑」)。
    """
    from short_reversal.engine import _metrics_from_holder

    holder = {"cash": 1_000_000.0, "trades": [], "max_dd": 0.0}
    with pytest.raises(KeyError, match="equity_curve"):
        _metrics_from_holder(holder, "2025-09-12", "2026-09-12", {"_name": "v50_slope"})
