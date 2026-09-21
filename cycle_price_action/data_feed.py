"""从 DuckDB v_daily 视图加载 universe,应用 P8 在市 + main-board + 流动性过滤。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from cycle_price_action.universe import apply_liquidity_filter, is_main_board


@dataclass(frozen=True)
class StockSlice:
    thscode: str
    df: pd.DataFrame  # date, open, high, low, close, volume, amount


def load_universe_data(
    db_path: str, start: date, end: date,
) -> dict[str, StockSlice]:
    """Load main-board stocks present on `end` (P8) with enough liquidity."""
    con = duckdb.connect(db_path, read_only=True)
    try:
        # P8: only stocks with MAX(date) >= end are still listed.
        listed_rows = con.execute(
            "SELECT thscode, MAX(date) AS last_date FROM v_daily GROUP BY thscode"
        ).fetchall()
        listed = {r[0] for r in listed_rows if r[1] is not None and r[1] >= end}
        main_board = {c for c in listed if is_main_board(c)}
        if not main_board:
            return {}

        codes_sql = ", ".join(f"'{c}'" for c in main_board)
        panel = con.execute(
            f"SELECT thscode, date, open, high, low, close, volume, amount "
            f"FROM v_daily WHERE thscode IN ({codes_sql}) "
            f"AND date BETWEEN '{start}' AND '{end}' ORDER BY thscode, date"
        ).fetchdf()

        if panel.empty:
            return {}

        # Liquidity filter needs full history (60d rolling mean of amount).
        # Re-query without date filter for the universe codes.
        liquidity_codes = con.execute(
            f"SELECT thscode, date, amount FROM v_daily "
            f"WHERE thscode IN ({codes_sql})"
        ).fetchdf()
        liquid = apply_liquidity_filter(liquidity_codes, min_avg_turnover=5e7, lookback=60)
        final_codes = main_board & liquid

        universe: dict[str, StockSlice] = {}
        for code in sorted(final_codes):
            sub = panel[panel["thscode"] == code].drop(columns=["thscode"]).reset_index(drop=True)
            universe[code] = StockSlice(thscode=code, df=sub)
        return universe
    finally:
        con.close()
