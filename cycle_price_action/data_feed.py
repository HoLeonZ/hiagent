"""从 DuckDB v_daily 视图加载 universe,应用 P8 在市 + main-board + 流动性过滤。

§6 architecture (Tick 49, 2026-09-28): Control Plane owns all DuckDB I/O for
cycle_price_action. This module owns two responsibilities:

  1. `load_universe_data` — universe selection (P8 + liquidity filter).
     Already PIT-compliant.

  2. `ReplayDataProvider` — per-fill PIT data lookup (next trading date +
     open price bar). Owned here so the Execution Broker (`ReplayBroker`)
     stays DB-free per CLAUDE.md §6. The data_provider wraps a single
     duckdb.connect lifecycle; `ReplayBroker` receives it via injection.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from core.dual_price import (
    LAYOUT_CYCLE_PRICE,
    extract_execution_bar,
)
from cycle_price_action.universe import apply_liquidity_filter, is_main_board

logger = logging.getLogger(__name__)


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Check whether a table/view exists in the connected DB.

    Used to detect v_daily_hfq (Layout B/C adj_close source) at runtime —
    some test DBs only have raw v_daily. Without this fallback, the LEFT
    JOIN in load_universe_data would raise CatalogException.
    """
    row = con.execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = ? "
        "ORDER BY 1",
        [name],
    ).fetchone()
    return bool(row and row[0] > 0)


@dataclass(frozen=True)
class StockSlice:
    thscode: str
    df: pd.DataFrame  # date, open, high, low, close, volume, amount


class ReplayDataProvider:
    """Control Plane PIT data provider for `ReplayBroker` (CLAUDE.md §6).

    Owns the ONLY duckdb.connect in the cycle_price_action broker path.
    ReplayBroker receives this provider via constructor injection so the
    broker stays DB-free and trivially mockable in tests.

    Methods:
      next_trading_date(after) — calendar lookup (min(date) > after).
      open_price(thscode, on_date) — fill-price lookup (open col).
      open_bar(thscode, on_date) — full bar (open + high/low/close) routed
        through `extract_execution_bar` to enforce the partial-NaN invariant
        (consistent with chase_up + uptrend_pullback, Tick N3).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> str:
        return self._db_path

    def next_trading_date(self, after: date) -> date:
        con = duckdb.connect(self._db_path, read_only=True)
        try:
            row = con.execute(
                "SELECT MIN(date) FROM v_daily WHERE date > ?",
                [after],
            ).fetchone()
            if row is None or row[0] is None:
                raise RuntimeError(f"no trading date after {after}")
            return row[0]
        finally:
            con.close()

    def open_bar(self, thscode: str, on_date: date) -> dict[str, float]:
        """Read the full bar (open/high/low/close) for (thscode, on_date).

        Routed through `extract_execution_bar` so partial-NaN bars
        (open/high/low real, close=NaN) raise ValueError — consistent with
        chase_up / uptrend_pullback buy-fill path (Tick N3).

        Reads as raw duckdb values (None for NULL) instead of float()-casting
        so extract_execution_bar → _safe can detect None/NaN and produce the
        0.0 fallback that triggers the ExecutionBar phantom guard.
        """
        con = duckdb.connect(self._db_path, read_only=True)
        try:
            row = con.execute(
                # Tick 68 (2026-09-28, CLAUDE.md §1): explicit ORDER BY
                # for cross-run reproducibility by construction. The WHERE
                # composite-key (thscode, date) returns at most 1 row so
                # ORDER BY is semantically a no-op but documents intent
                # and satisfies the auditor.
                "SELECT open, high, low, close FROM v_daily "
                "WHERE thscode = ? AND date = ? "
                "ORDER BY thscode, date",
                [thscode, on_date],
            ).fetchone()
            if row is None:
                raise RuntimeError(f"no data for {thscode} on {on_date}")
            # Keep None as None; _safe() in core.dual_price converts to 0.0.
            bar_row = {"open": row[0], "high": row[1],
                       "low": row[2], "close": row[3]}
        finally:
            con.close()
        # extract_execution_bar enforces ExecutionBar invariants (close <= 0
        # when open > 0 → ValueError). Discard the wrapper; caller only needs
        # the validated scalar fields.
        exec_bar = extract_execution_bar(bar_row, LAYOUT_CYCLE_PRICE)
        return {
            "open": exec_bar.open,
            "high": exec_bar.high,
            "low": exec_bar.low,
            "close": exec_bar.close,
        }

    def open_price(self, thscode: str, on_date: date) -> float:
        """Read the fill price (open col) for (thscode, on_date).

        Thin wrapper over `open_bar` to preserve ReplayBroker's existing
        `_open_price` call signature; routes through ExecutionBar to enforce
        the partial-NaN guard.
        """
        return self.open_bar(thscode, on_date)["open"]


def load_universe_data(
    db_path: str, start: date, end: date, *, asof_date: date | None = None,
) -> dict[str, StockSlice]:
    """Load main-board stocks present on `asof_date` (PIT, §3) with enough liquidity.

    Round 14 (2026-09-28, CLAUDE.md §3): `asof_date` 显式参数化 universe 入选时点。
    若不传则回退到 `end` (保持旧行为), 但 caller 应显式传 `start` 或更早的
    PIT 时间点以避免 post-hoc constituents。
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        # §3 PIT: universe 在 asof_date 时仍在市 (i.e. MAX(date) >= asof_date)。
        # 若 caller 未传 asof_date, 回退到 `end` (旧行为)。
        # Use DB's actual last day as the in-DB reference — the data file
        # may lag the requested `asof_date` by a few days. Comparing against
        # the user-requested `asof_date` would silently drop the entire
        # universe when the DB is stale.
        db_last = con.execute("SELECT MAX(date) FROM v_daily").fetchone()[0]
        ref_pit = asof_date if asof_date is not None else end
        ref_end = min(ref_pit, db_last) if db_last else ref_pit
        listed_rows = con.execute(
            "SELECT thscode, MAX(date) AS last_date FROM v_daily GROUP BY thscode"
        ).fetchall()
        listed = {r[0] for r in listed_rows if r[1] is not None and r[1] >= ref_end}
        main_board = {c for c in listed if is_main_board(c)}
        if not main_board:
            return {}

        codes_sql = ", ".join(f"'{c}'" for c in main_board)
        # §3 Dual-Price (CLAUDE.md): LEFT JOIN v_daily_hfq 提供 adj_close 列,
        # signals.py k_line_score 在 adj_close 存在时优先使用 adj_close 计算 MA/Confluence。
        # close/open/high/low/amount/volume 仍走 v_daily (raw), 物理成交价不变。
        # v_daily_hfq 在某些测试 DB 中不存在 — 运行时探测, 缺则降级为 raw_only。
        has_hfq = _table_exists(con, "v_daily_hfq")
        if has_hfq:
            # Tick 68 (2026-09-28, CLAUDE.md §1): plain string template + .format()
            # so ORDER BY appears in the FIRST Constant child of the AST —
            # multi-line f-strings split into multiple Constants, hiding
            # ORDER BY from the AST-based auditor in test_sql_order_by_discipline.
            # The template lives inside the execute call so the text-based
            # test_duckdb_panel_queries_have_order_by also finds ORDER BY.
            panel = con.execute(
                (
                    "SELECT v.thscode, v.date, v.open, v.high, v.low, v.close, "
                    "v.volume, v.amount, h.close AS adj_close "
                    "FROM v_daily v "
                    "LEFT JOIN v_daily_hfq h ON v.thscode = h.thscode AND v.date = h.date "
                    "WHERE v.thscode IN ({codes_sql}) "
                    "AND v.date BETWEEN '{start}' AND '{end}' "
                    "ORDER BY v.thscode, v.date"
                ).format(codes_sql=codes_sql, start=start, end=end)
            ).fetchdf()
        else:
            panel = con.execute(
                (
                    "SELECT thscode, date, open, high, low, close, volume, amount "
                    "FROM v_daily WHERE thscode IN ({codes_sql}) "
                    "AND date BETWEEN '{start}' AND '{end}' "
                    "ORDER BY thscode, date"
                ).format(codes_sql=codes_sql, start=start, end=end)
            ).fetchdf()

        if panel.empty:
            return {}

        # Liquidity filter needs full history (60d rolling mean of amount).
        # Re-query without date filter for the universe codes.
        # Tick 68 (2026-09-28): explicit ORDER BY for cross-run reproducibility
        # by construction — apply_liquidity_filter is currently groupby/set-
        # semantic (order-independent), but the convention requires explicit
        # ORDER BY so future sequence-aware filters stay deterministic.
        liquidity_codes = con.execute(
            (
                "SELECT thscode, date, amount FROM v_daily "
                "WHERE thscode IN ({codes_sql}) "
                "ORDER BY thscode, date"
            ).format(codes_sql=codes_sql)
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
