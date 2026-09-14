"""行情读取 — 前复权价 v_daily_qfq。

关键点：
  - v_daily_qfq 实际 schema 直接叫 `amount`（成交额，DOUBLE），没有 turnover 列。
    早期注释误以为库内叫 turnover，写成 `turnover AS amount` 会触发
    "Referenced column 'turnover' not found" Binder Error，现已改为直接 SELECT amount。
  - 做多策略必须用前复权价：除权除息日 v_daily 的裸价会凭空跳空下跌，
    在多头回测里会被误判为止损。
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from uptrend_pullback import UptrendPullbackError

logger = logging.getLogger(__name__)

# 指标预热：MA120 + 动量窗口需要约 120 个交易日，留 400 自然日冗余
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
    按 (thscode, date) 排序。`amount` 直接取自 v_daily_qfq.amount（成交额）。
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
        raise UptrendPullbackError(f"DuckDB read failed: {e}") from e
    finally:
        con.close()

    if panel.empty:
        raise UptrendPullbackError(
            f"No rows for {load_start}..{end}; check db_path and date range"
        )

    panel["date"] = pd.to_datetime(panel["date"])
    if universe is not None:
        panel = panel[panel["thscode"].isin(universe)]

    # 停牌/异常行剔除：价格必须为正，最高 >= 最低
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
