"""统一交易报告的数据加载 — 仅供 short_reversal/main.py(Control Plane)调用。

渲染器 core.trade_report 是纯函数不查库; 本模块是唯一 DB 接触点。
SQL 含 ORDER BY(Tick 68 纪律)。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

BAR_PAD_DAYS = 75  # 窗口前回望(覆盖 MA60/MACD 暖机)


def load_bars_by_code(
    db_path: Path,
    codes: list[str],
    start: str,
    end: str,
) -> dict[str, pd.DataFrame]:
    """拉取指定代码 [start - pad, end] 的 v_daily 原始日线,按 code 分组。"""
    if not codes:
        return {}
    start_pad = (pd.Timestamp(start) - pd.Timedelta(days=BAR_PAD_DAYS)).strftime("%Y-%m-%d")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        df = con.execute(
            "SELECT thscode, date, open, high, low, close, volume, amount "
            "FROM v_daily "
            "WHERE thscode = ANY(?) AND date BETWEEN ? AND ? "
            "ORDER BY thscode, date",
            [list(codes), start_pad, end],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    return {c: g.reset_index(drop=True) for c, g in df.groupby("thscode")}
