"""行情读取 — 前复权价 v_daily_qfq。

关键点：
  - 本库 v_daily* 的成交额列名是 `turnover`（不是 `amount`）。
    short_reversal/main.py 与 grid.py 里写的是 `amount`，对本库会直接报
    Binder Error，属于既有 bug，本模块不复制该错误。
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
    按 (thscode, date) 排序。`amount` 由库内 `turnover` 重命名而来。
    """
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        panel = con.execute(
            """
            SELECT thscode, date, open, high, low, close, volume,
                   turnover AS amount
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
