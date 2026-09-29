"""行情读取 — 前复权价 v_daily_qfq + 原始价 raw_kline_daily (V3a dual-price)。

V3a (2026-09-22, CLAUDE.md §3): LEFT JOIN raw_kline_daily 增加
raw_open / raw_high / raw_low / raw_close / raw_prev_close 列。
策略 signal 仍用 adj (open/high/low/close from v_daily_qfq), execution
trigger (SL/TP) 可选用 raw_*。除权日 raw_* 与 adj 发散 (002749.SZ
2025-09-05: qfq_close=12.108, raw_close=15.54 — 复权因子 ~0.78)。
raw_* 缺失 (NaN, LEFT JOIN miss, 停牌等) → portfolio 在 preset 声明
price_source_for_execution="raw_close" 时自动回退到 adj, 不破 baseline。
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from chase_up import ChaseUpError

logger = logging.getLogger(__name__)

# MA120 + 动量 120 + MA 金叉近 5 日 warmup + buffer
WARMUP_DAYS = 400


def load_panel(
    db_path: Path,
    start: str,
    end: str,
    *,
    universe: set[str] | None = None,
    warmup_days: int = WARMUP_DAYS,
) -> pd.DataFrame:
    """读取 [start - warmup, end] 区间的前复权日线 + raw K 线 (V3a dual-price)。

    返回 columns=[thscode, date,
                  open, high, low, close, volume, amount,           -- 前复权
                  raw_open, raw_high, raw_low, raw_close, raw_prev_close],
    按 (thscode, date) 排序。raw_* 缺失填 NaN (LEFT JOIN miss)。
    """
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        panel = con.execute(
            """
            SELECT q.thscode, q.date,
                   q.open, q.high, q.low, q.close, q.volume, q.amount,
                   r.open  AS raw_open,
                   r.high  AS raw_high,
                   r.low   AS raw_low,
                   r.close AS raw_close,
                   -- Round 23 (2026-09-28, CLAUDE.md §3 truthfulness):
                   -- raw_kline_daily.prev_close is NULL (0% populated per data layer audit).
                   -- v_daily_dual view uses LAG(...) which is 99.95% populated.
                   -- Inline LAG keeps qfq schema compatibility for open/high/low/close.
                   LAG(r.close, 1) OVER (
                       PARTITION BY r.thscode ORDER BY r.date
                   ) AS raw_prev_close
            FROM v_daily_qfq q
            LEFT JOIN raw_kline_daily r
              ON q.thscode = r.thscode AND q.date = r.date
            WHERE q.date BETWEEN ? AND ?
            ORDER BY q.thscode, q.date
            """,
            [load_start, end],
        ).fetchdf()
    except duckdb.Error as e:
        raise ChaseUpError(f"DuckDB read failed: {e}") from e
    finally:
        con.close()

    if panel.empty:
        raise ChaseUpError(
            f"No rows for {load_start}..{end}; check db_path and date range"
        )

    panel["date"] = pd.to_datetime(panel["date"])
    if universe is not None:
        panel = panel[panel["thscode"].isin(universe)]

    # 停牌/异常行剔除：adj 价格必须为正，最高 >= 最低
    panel = panel[
        (panel["open"] > 0)
        & (panel["high"] > 0)
        & (panel["low"] > 0)
        & (panel["close"] > 0)
        & (panel["high"] >= panel["low"])
    ]

    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)
    logger.info(
        "panel loaded: %d rows, %d codes, %s..%s (raw_*: %.1f%% non-null)",
        len(panel), panel["thscode"].nunique(),
        panel["date"].min().date(), panel["date"].max().date(),
        100.0 * panel["raw_close"].notna().mean(),
    )
    return panel