"""行情读取 — 前复权价 v_daily_qfq + 原始价 raw_kline_daily (V3a dual-price)。

关键点：
  - v_daily_qfq 实际 schema 直接叫 `amount`（成交额，DOUBLE），没有 turnover 列。
    早期注释误以为库内叫 turnover，写成 `turnover AS amount` 会触发
    "Referenced column 'turnover' not found" Binder Error，现已改为直接 SELECT amount。
  - 做多策略必须用前复权价：除权除息日 v_daily 的裸价会凭空跳空下跌，
    在多头回测里会被误判为止损。
  - V3a (2026-09-22, CLAUDE.md §3): LEFT JOIN raw_kline_daily 增加
    raw_open / raw_high / raw_low / raw_close 列。策略 signal 仍用 adj
    (open/high/low/close from v_daily_qfq), execution trigger (SL/TP) 可选用
    raw_*。raw_* 与 adj_* 在除权日会发散 (e.g. 002749.SZ 2025-09-05:
    qfq_close=12.108, raw_close=15.54 — 复权因子 ~0.78, 即除权除息历史)。
    - 缺 raw_* 的行 (LEFT JOIN miss, e.g. 停牌) → raw_* 列填 NaN,
      portfolio 在 preset 声明 price_source_for_execution="raw_close" 时
      自动回退到 adj close, 不破 baseline。
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
    """读取 [start - warmup, end] 区间的前复权日线 + raw K 线 (V3a dual-price)。

    返回 columns=[thscode, date,
                  open, high, low, close, volume, amount,           -- 前复权
                  raw_open, raw_high, raw_low, raw_close, raw_prev_close],
    按 (thscode, date) 排序。raw_* 列来自 raw_kline_daily LEFT JOIN, 缺失填 NaN。
    """
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).strftime("%Y-%m-%d")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        # V3a (2026-09-22, CLAUDE.md §3): LEFT JOIN raw_kline_daily 注入 raw_*
        # 保持 v_daily_qfq 行完整性 (signal-only panel 不能丢行)。
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
