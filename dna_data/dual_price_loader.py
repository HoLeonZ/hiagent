"""V3a (2026-09-22, CLAUDE.md §3): Dual-Price System loader.

Module renamed from ``dual_price.py`` → ``dual_price_loader.py`` to
disambiguate from ``core.dual_price`` (domain layer, pure functions).
This module is the **data access layer**: DuckDB I/O for ``v_daily_dual``
view. The companion domain-layer module ``core.dual_price`` defines
``ExecutionBar`` / ``extract_execution_bar`` / ``is_limit_up`` /
``volume_cap_fill`` / cost-model constants (zero I/O).

Loads v_daily_dual view (adj + raw prices joined) for strategies that need
both adjusted prices (for indicators) and raw prices (for SL/TP triggers
and portfolio mark-to-market). See sql/migrate_v_daily_dual.sql.

Default columns returned:
    thscode, date,
    adj_open, adj_high, adj_low, adj_close,   — forward-adjusted (for indicators)
    raw_open, raw_high, raw_low, raw_close,   — raw (for execution)
    raw_prev_close,                           — for limit-up detection
    volume, amount                            — shared

The column naming convention follows CLAUDE.md §3:
  * "ALWAYS use Forward-Adjusted Prices (adj_close) for mathematical
     indicators (MACD, Wyckoff mappings, Volatility)."
  * "ALWAYS use Raw Prices (raw_close) for evaluating limit order triggers,
     stop-losses, and portfolio physical cash mark-to-market."
"""
from __future__ import annotations

import duckdb
import pandas as pd

from hiagent_config import DB_PATH


def load_dual_price_panel(
    start: str,
    end: str,
    universe: set[str] | None = None,
    db_path: str | None = None,
) -> pd.DataFrame:
    """Load v_daily_dual for [start, end] optionally filtered to universe.

    Returns DataFrame sorted by (thscode, date) with all 13 columns.
    Caller picks adj_* or raw_* columns based on their purpose
    (signal vs execution).
    """
    db = db_path or str(DB_PATH)
    con = duckdb.connect(db, read_only=True)
    try:
        if universe:
            codes_sql = ",".join(f"'{c}'" for c in universe)
            sql = f"""
                SELECT thscode, date,
                       adj_open, adj_high, adj_low, adj_close,
                       raw_open, raw_high, raw_low, raw_close,
                       raw_prev_close, volume, amount
                FROM v_daily_dual
                WHERE date BETWEEN ? AND ?
                  AND thscode IN ({codes_sql})
                ORDER BY thscode, date
            """
            df = con.execute(sql, [start, end]).fetchdf()
        else:
            sql = """
                SELECT thscode, date,
                       adj_open, adj_high, adj_low, adj_close,
                       raw_open, raw_high, raw_low, raw_close,
                       raw_prev_close, volume, amount
                FROM v_daily_dual
                WHERE date BETWEEN ? AND ?
                ORDER BY thscode, date
            """
            df = con.execute(sql, [start, end]).fetchdf()
        return df
    finally:
        con.close()
