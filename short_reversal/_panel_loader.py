"""Control Plane panel loader for short_reversal (CLAUDE.md §6).

§6 architecture mandate:
  - Control Plane / Orchestrator owns PIT data dispatching (this module).
  - Strategy / Inference must NOT have direct DB access (no duckdb.connect
    inside scan_signals_fast._scan_preset / engine._load_panel).
  - Execution Broker must NOT have direct DB access (no per-fill DB queries).

This module is the SINGLE SOURCE for short_reversal DuckDB panel loading.
It exposes two helpers:

  load_panel_for_signal(db_path, signal_date, lookback_days=400)
    - Used by orchestrator (main loop) in scan_signals_fast.py.
    - Pulls a single rolling window (T - lookback_days → T) from v_daily.

  load_panel_for_backtest(db_path, start, end, universe)
    - Used by orchestrator (run_backtest_v3) in engine.py.
    - Pulls a per-stock panel with PANEL_FORWARD_BUFFER_DAYS pre-buffer
      (for MA60 warmup + insurance) and 60-day post-buffer (for in-flight
      closes — entries must NOT extend into post-buffer; see LAHEAD-001).

Both helpers own the duckdb.connect lifecycle internally; callers receive
a pure pd.DataFrame.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
from core.data_coverage import assert_adjusted_coverage  # §3/§0 因子覆盖单源 (附一百零四)
import pandas as pd

logger = logging.getLogger(__name__)


# Pre-buffer: MA60 + 30-day insurance. Post-buffer: 60-day in-flight close.
# Buffer contract is locked by tests/test_short_reversal_no_lookahead.py
# (LAHEAD-001) + tests/golden/*. Any change must regenerate golden baselines.
PANEL_FORWARD_BUFFER_DAYS: int = 180
PANEL_POST_BUFFER_DAYS: int = 60


def load_panel_for_signal(
    db_path: Path, signal_date: str, lookback_days: int = 400,
) -> pd.DataFrame:
    """Pull panel from v_daily for [signal_date - lookback_days, signal_date].

    Used by orchestrator (scan_signals_fast.main) to load panel BEFORE
    calling the pure-compute `_scan_preset(panel, preset, signal_date)`.

    Returns: pd.DataFrame with cols thscode, date, open, high, low, close,
    amount, volume (date is pd.Timestamp).
    """
    start = (
        pd.Timestamp(signal_date) - pd.Timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        # §3 (audit 2026-10-17): **信号扫描也必须带 adj_* 列**。
        # 此前这里只 SELECT v_daily(raw),于是 `scan_signals` / `scan_signals_fast`
        # 的 5 条件(A/B/C/D/E)以及 F–K 全部在**原始价**上评估,而回测引擎
        # (`load_panel_for_backtest` 有 LEFT JOIN v_daily_hfq)用的是**复权价**
        # —— V5 在引擎侧修好的"原始 close 与复权 MA60 混域"问题,在扫描侧被漏下。
        # 实测暴露面:近 250 个交易日内有公司行为的标的有 **3775 只 / 5143 个事件**
        # (几乎所有 A 股都有分红/送股)⇒ 扫描器给出的名单与回测实际会进场的名单
        # 在**大半个市场**上不同。
        # 与 `load_panel_for_backtest` 同一 JOIN 口径(v_daily = raw, v_daily_hfq = adj)。
        # 复权视图存在才 JOIN —— 合成夹具(只建 v_daily)里没有它。
        # 缺它时给出 **NULL 的 adj_*** 而不是报错:列形状保持一致,而策略侧
        # ("adj_close 全 NaN ⇒ 回退 d.close")与扫描器侧("逐行回退 close")
        # 都已定义好这条回退,所以"没有复权数据"是一个**已声明**的状态,不是崩溃。
        has_hfq = bool(
            con.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'v_daily_hfq'"
            ).fetchone()[0]
        )
        if has_hfq:
            df = con.execute(
                "SELECT v.thscode, v.date, "
                "       v.open, v.high, v.low, v.close, v.amount, v.volume, "
                "       h.open  AS adj_open, "
                "       h.high  AS adj_high, "
                "       h.low   AS adj_low, "
                "       h.close AS adj_close "
                "FROM v_daily v "
                "LEFT JOIN v_daily_hfq h "
                "  ON v.thscode = h.thscode AND v.date = h.date "
                "WHERE v.date BETWEEN ? AND ? "
                "ORDER BY v.thscode, v.date",
                [start, signal_date],
            ).fetchdf()
        else:
            df = con.execute(
                "SELECT v.thscode, v.date, "
                "       v.open, v.high, v.low, v.close, v.amount, v.volume, "
                "       CAST(NULL AS DOUBLE) AS adj_open, "
                "       CAST(NULL AS DOUBLE) AS adj_high, "
                "       CAST(NULL AS DOUBLE) AS adj_low, "
                "       CAST(NULL AS DOUBLE) AS adj_close "
                "FROM v_daily v "
                "WHERE v.date BETWEEN ? AND ? "
                "ORDER BY v.thscode, v.date",
                [start, signal_date],
            ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_panel_for_backtest(
    db_path: Path, start: str, end: str, universe: list[str],
) -> pd.DataFrame:
    """Pull per-stock panel for backtest window [start, end].

    Pre/post buffers:
      - Pre (PANEL_FORWARD_BUFFER_DAYS=180): MA60 warmup + 30-day insurance
      - Post (PANEL_POST_BUFFER_DAYS=60): in-flight close buffer — exits may
        extend here, entries MUST NOT (LAHEAD-001 invariant).

    LEFT JOINs v_daily_hfq to expose adj_* columns (V3a, 2026-09-22).
    Strategy reads adj_close for indicator math, raw close for execution.

    Returns: pd.DataFrame with cols thscode, date, open, high, low, close,
    amount, volume, adj_open, adj_high, adj_low, adj_close,
    div_per_share, bonus_ratio, rights_ratio.
    """
    panel_start = (
        pd.Timestamp(start) - pd.Timedelta(days=PANEL_FORWARD_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")
    panel_end = (
        pd.Timestamp(end) + pd.Timedelta(days=PANEL_POST_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        assert_adjusted_coverage(con, start, end, source="short_reversal/_panel_loader.load_panel_for_backtest")
        df = con.execute(
            """
            SELECT v.thscode, v.date,
                   v.open, v.high, v.low, v.close, v.amount, v.volume,
                   h.open  AS adj_open,
                   h.high  AS adj_high,
                   h.low   AS adj_low,
                   h.close AS adj_close,
                   -- §3 (audit P2-10, 2026-10-15): 事件化公司行为(与 chase_up 同口径)。
                   -- 做空方向:现金分红是**付出**,由引擎在除权日从该仓位的
                   -- locked_margin 扣出(见 _apply_corporate_action)。
                   COALESCE(ev.dividend_per_share, 0.0) AS div_per_share,
                   COALESCE(ev.per_share_bonus, 0.0)    AS bonus_ratio,
                   COALESCE(ev.rights_ratio, 0.0)       AS rights_ratio
            FROM v_daily v
            LEFT JOIN (
                SELECT thscode, ex_date,
                       SUM(dividend_per_share) AS dividend_per_share,
                       SUM(per_share_bonus)    AS per_share_bonus,
                       SUM(rights_ratio)       AS rights_ratio
                FROM raw_adjustment_events
                GROUP BY thscode, ex_date
            ) ev ON v.thscode = ev.thscode AND v.date = ev.ex_date
            LEFT JOIN v_daily_hfq h
              ON v.thscode = h.thscode AND v.date = h.date
            WHERE v.date BETWEEN ? AND ? AND v.thscode = ANY(?)
            ORDER BY v.thscode, v.date
            """,
            [panel_start, panel_end, universe],
        ).fetchdf()
    finally:
        con.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df
