"""v3 事件驱动 backtest 编排（唯一对外入口）。

run_backtest_v3() 跑一个 preset，返回 metrics dict。

Universe 走 load_universe_asof：剔除 asof_date 之后才上市的票，
严格消除 survivorship bias（DuckDB 无历史成分表，能做的最小代理）。
"""
from __future__ import annotations

import math
from pathlib import Path

import backtrader as bt
import duckdb
import numpy as np
import pandas as pd

from short_reversal.feed_bt import build_per_stock_feeds
from short_reversal.presets import PRESETS, get_preset
from short_reversal.replay_strategy_v3 import Phase3V3Strategy
from short_reversal.universe import load_universe_asof

INITIAL_CAPITAL = 1_000_000.0
COMMISSION_RATE = 0.0006
STAMP_DUTY_RATE = 0.001
MARGIN_RATE = 0.086
DAYS_PER_YEAR = 365

# 前向 buffer：MA60 需要 60 日 warmup，再多 30 日保险
PANEL_FORWARD_BUFFER_DAYS = 180


def _load_panel(db_path: Path, start: str, end: str, universe: list[str]) -> pd.DataFrame:
    """从 DuckDB 拉面板（含前向 buffer）。

    Buffer 约定（2026-09-20 audit-locked）：
      - 前 180 天：MA60 等指标 warmup + 30 天保险
      - 后 60 天：in-flight close 缓冲 —— 仅允许 window 内入场的 trade
        在此处 close，不允许 entry_date > end。这是 LAHEAD-001 的
        structural guarantee。
      任何修改此 buffer 大小的 PR 必须同时更新 tests/golden/ 下的 baseline
      + tests/test_short_reversal_no_lookahead.py 的 LAHEAD-001 锁。
    """
    panel_start = (pd.Timestamp(start) - pd.Timedelta(days=PANEL_FORWARD_BUFFER_DAYS)).strftime("%Y-%m-%d")
    # 60-day post-buffer 是 in-flight close 缓冲（exits may extend here,
    # entries must NOT）。违反此约定会触发 LAHEAD-001 regression test。
    panel_end = (pd.Timestamp(end) + pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        # V3a (2026-09-22, CLAUDE.md §3): LEFT JOIN v_daily_hfq (back-adjusted)
        # 增加 adj_open/adj_high/adj_low/adj_close 列, 让 strategy 可选用 adj
        # 用于指标计算, 仍用 v_daily 的 raw 列作为 execution trigger。
        # 当前 baseline parity: short_reversal 默认 price_source_for_execution
        # 走 raw 域 (v_daily IS raw), signal 也走 raw (为防止 baseline 漂移)。
        # 完整 V3a 落地 (signal 用 adj) 需要 golden baseline 重生成。
        df = con.execute(
            """
            SELECT v.thscode, v.date,
                   v.open, v.high, v.low, v.close, v.amount, v.volume,
                   h.open  AS adj_open,
                   h.high  AS adj_high,
                   h.low   AS adj_low,
                   h.close AS adj_close
            FROM v_daily v
            LEFT JOIN v_daily_hfq h
              ON v.thscode = h.thscode AND v.date = h.date
            WHERE v.date BETWEEN ? AND ? AND v.thscode = ANY(?)
            ORDER BY v.thscode, v.date
            """,
            [panel_start, panel_end, universe],
        ).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _metrics_from_holder(holder: dict, start: str, end: str, cfg: dict) -> dict:
    """从 result_holder + 区间算出最终 metrics dict。"""
    final_capital = float(holder["cash"])
    trades = holder["trades"]
    trades_count = len(trades)

    years = max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / DAYS_PER_YEAR,
        1.0 / DAYS_PER_YEAR,
    )
    total_yield = final_capital / INITIAL_CAPITAL - 1
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1 if final_capital > 0 else -1.0

    wins = sum(1 for t in trades if t["net"] > 0)
    win_rate = wins / trades_count if trades_count > 0 else 0.0
    avg_pnl = float(np.mean([t["net"] for t in trades])) if trades_count > 0 else 0.0
    avg_hold = float(np.mean([t["hold_days"] for t in trades])) if trades_count > 0 else 0.0

    # 简单 Sharpe: 日 PnL 序列 → 年化
    sharpe = _approx_sharpe(trades)

    # exit reason 计数
    tp_count = sum(1 for t in trades if t["exit_reason"] == "TP")
    sl_count = sum(1 for t in trades if t["exit_reason"] == "SL")
    time_count = sum(1 for t in trades if t["exit_reason"] == "time")

    return {
        "preset": cfg["_name"],
        "start": start,
        "end": end,
        "trades": trades,
        "trades_count": trades_count,
        "win_rate": float(win_rate),
        "final_capital": final_capital,
        "total_yield": float(total_yield),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": min(1.0, max(0.0, float(holder["max_dd"]))),
        "avg_pnl": avg_pnl,
        "avg_hold_days": avg_hold,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_count": time_count,
    }


def _approx_sharpe(trades: list[dict]) -> float:
    """无日 PnL 序列 → 用每笔 net 估算 sharpe（粗略，仅供排序）。"""
    if not trades:
        return 0.0
    arr = np.array([t["net"] for t in trades])
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    if std < 1e-9:
        return 0.0
    # 假设 ~250 笔/年，按交易频率缩放
    return float(mean / std * math.sqrt(min(len(arr), 250)))


def run_backtest_v3(
    preset: str,
    start: str,
    end: str,
    db_path: Path,
    min_bars: int = 200,
) -> dict:
    """跑 v3 引擎返回 metrics dict。

    参数:
      preset: PRESETS 里的 preset name
      start / end: 回测区间 (YYYY-MM-DD)
      db_path: DuckDB 文件路径
      min_bars: 每只票最少需要的 bar 数;2-month 滚动窗口期间 panel 跨春节可能
                只有 ~197 trading days,这时可下调到 150,NaN gate 会兜底。
    """
    cfg = dict(get_preset(preset))
    cfg["_name"] = preset

    universe = load_universe_asof(cfg["universe"], start, db_path)
    panel = _load_panel(db_path, start, end, universe)
    feeds = build_per_stock_feeds(panel, universe, min_bars=min_bars)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    cerebro.broker.setcommission(commission=0.0)  # 成本由 strategy 内扣

    holder: dict = {"cash": INITIAL_CAPITAL, "trades": [], "max_dd": 0.0}

    for code, feed in feeds:
        cerebro.adddata(feed, name=code)
    cerebro.addstrategy(
        Phase3V3Strategy,
        tp_pct=cfg["tp_pct"],
        sl_pct=cfg["sl_pct"],
        max_hold=cfg["max_hold"],
        position_fraction=1.0,
        pct_chg_low=cfg.get("pct_chg_low", 0.02),
        pct_chg_high=cfg.get("pct_chg_high", 0.06),
        a_condition=cfg.get("a_condition", "default"),
        up_streak_low=cfg.get("up_streak_low", 3),
        up_streak_high=cfg.get("up_streak_high", 10),
        liq_low=cfg.get("liq_low", 3e7),
        liq_high=cfg.get("liq_high", 3e8),
        below_ratio_60=cfg.get("below_ratio_60", 0.6),
        close_ma60_buffer=cfg.get("close_ma60_buffer", 0.0),
        d_mode=cfg.get("d_mode", "strict"),
        margin_rate=MARGIN_RATE,
        commission_rate=COMMISSION_RATE,
        stamp_duty_rate=STAMP_DUTY_RATE,
        initial_capital=INITIAL_CAPITAL,
        lot_size=100,
        min_cash_ratio=cfg.get("min_cash_ratio", 0.05),
        result_holder=holder,
    )
    cerebro.run()
    return _metrics_from_holder(holder, start, end, cfg)
