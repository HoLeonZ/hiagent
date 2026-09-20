"""行情读取 — 前复权价 v_daily_qfq (沿用 uptrend_pullback/data.py 的口径)。"""
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
    """读取 [start - warmup, end] 区间的前复权日线。

    返回 columns=[thscode, date, open, high, low, close, volume, amount]，
    按 (thscode, date) 排序。
    """
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        panel = con.execute(
            """
            SELECT thscode, date, open, high, low, close, volume, amount
            FROM v_daily_qfq
            WHERE date BETWEEN ? AND ?
            ORDER BY thscode, date
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

    # 停牌/异常行剔除
    panel = panel[
        (panel["open"] > 0)
        & (panel["high"] > 0)
        & (panel["low"] > 0)
        & (panel["close"] > 0)
        & (panel["high"] >= panel["low"])
    ]

    panel = panel.sort_values(["thscode", "date"]).reset_index(drop=True)
    logger.info(
        "panel loaded: %d rows, %d codes, %s..%s",
        len(panel), panel["thscode"].nunique(),
        panel["date"].min().date(), panel["date"].max().date(),
    )
    return panel