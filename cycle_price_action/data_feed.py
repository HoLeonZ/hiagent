"""从 DuckDB v_daily 视图加载 universe,应用 P8 在市 + main-board + 流动性过滤。

§6 architecture (Tick 49, 2026-09-28): Control Plane owns all DuckDB I/O for
cycle_price_action. This module owns two responsibilities:

  1. `load_universe_data` — universe selection (P8 + liquidity filter).
     §3 (audit, 2026-10-15): 此前本行写作 "Already PIT-compliant",**该声明不实**
     —— 成员判定曾要求 `MAX(date) >= 参考日`(排除窗口内退市标的 = 幸存者偏差),
     流动性均值又取自无日期上界的全历史(用到 `end` 之后的数据)。两处均已修正,
     现由 `tests/test_cycle_survivorship_bias.py` 与流动性因果上界用例守卫。

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

    def has_any_bar(self, thscode: str) -> bool:
        """该标的在库中是否**存在任何** bar。

        §1 (audit, 2026-10-15): 用来区分两种「缺行」——
          - **停牌**:该标的在别的日期有 bar → 合法市场状态,不得中止引擎;
          - **数据缺口 / 未知标的**:完全没有任何 bar → 数据完整性问题,应 fail-fast。
        只在缺行路径上多一次查询(不是每次成交都查),故不加剧 §6 关注的
        逐笔 DB 访问。
        """
        con = duckdb.connect(self._db_path, read_only=True)
        try:
            row = con.execute(
                # Tick 68 convention: row-returning query carries explicit
                # ORDER BY for cross-run reproducibility by construction
                # (guarded by tests/test_reproducibility_audit.py).
                "SELECT 1 FROM v_daily WHERE thscode = ? "
                "ORDER BY thscode, date LIMIT 1",
                [thscode],
            ).fetchone()
            return row is not None
        finally:
            con.close()

    def open_bar(self, thscode: str, on_date: date) -> dict[str, float] | None:
        """Read the full bar (open/high/low/close) for (thscode, on_date).

        Routed through `extract_execution_bar` so partial-NaN bars
        (open/high/low real, close=NaN) raise ValueError — consistent with
        chase_up / uptrend_pullback buy-fill path (Tick N3).

        Reads as raw duckdb values (None for NULL) instead of float()-casting
        so extract_execution_bar → _safe can detect None/NaN and produce the
        0.0 fallback that triggers the ExecutionBar phantom guard.

        §1 (audit, 2026-10-15): 该日期无 bar 时返回 **None**,不再 raise。
        停牌在日线上就表现为缺 bar —— 旧实现直接 `RuntimeError`,导致任何
        含停牌标的的窗口把整个回测中止(实测 000639.SZ @ 2026-04-29),
        与 §1「Trading halts produce missing bars... MUST NOT generate fills
        until trading resumes」直接冲突。是否算数据完整性错误,由
        `open_price` 用 `has_any_bar` 区分。
        存在但字段非法的 bar 仍然 fail-fast(ExecutionBar 不变量不受影响)。
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
                return None
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

    def open_price(self, thscode: str, on_date: date) -> float | None:
        """Read the fill price (open col) for (thscode, on_date).

        Thin wrapper over `open_bar` to preserve ReplayBroker's existing
        `_open_price` call signature; routes through ExecutionBar to enforce
        the partial-NaN guard.

        §1 (audit, 2026-10-15) 返回 Optional:
          - `None` = 该标的当日停牌(缺 bar)→ 本次不成交,引擎继续;
          - 若该标的在库中**完全无 bar**(数据缺口 / 未知标的)→ 仍 fail-fast
            抛 RuntimeError。两者都是「缺行」,但前者是合法市场状态,后者是
            数据完整性问题 —— 由 `has_any_bar` 区分,避免把停牌当成数据错误。
        """
        bar = self.open_bar(thscode, on_date)
        if bar is None:
            if not self.has_any_bar(thscode):
                raise RuntimeError(
                    f"no data for {thscode} on {on_date} — symbol has no bars at all "
                    f"(data gap / unknown symbol)"
                )
            return None
        return bar["open"]


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
        # §3 PIT: 成员判定 = 「在请求窗口内至少有一个交易日」。
        # §3 (audit P1-C2, 2026-10-15): 旧实现要求
        # `MAX(date) >= min(asof_date or end, db_last)`,即「必须活到参考日」——
        # 窗口中途退市的标的被整个剔除,其在窗口内已发生的盈亏被静默丢弃 =
        # 幸存者偏差,与 §3 "Delisted assets must remain in the simulation until
        # their physical delisting date" 直接冲突(见
        # tests/test_cycle_survivorship_bias.py::test_includes_delisted_stocks_with_data_in_window)。
        # asof_date 参数保留 —— 它约束的是**流动性**回看的因果上界(见下方
        # liquidity 查询),不再用于「活到参考日」判定。
        ref_pit = asof_date if asof_date is not None else end
        listed_rows = con.execute(
            "SELECT thscode, MAX(date) AS last_date FROM v_daily GROUP BY thscode"
        ).fetchall()
        listed = {r[0] for r in listed_rows if r[1] is not None and r[1] >= start}
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

        # Liquidity filter needs history (rolling mean of amount),但**只允许
        # 参考日之前的历史**。
        # §1/§3 (audit P1-C2, 2026-10-15): 旧实现 "Re-query without date
        # filter" —— 整张全历史表(含 end 之后的行)喂给 apply_liquidity_filter
        # 的 `groupby().mean()`,于是**宇宙成员由窗口之后的成交额决定**,
        # 是典型的未来函数。现按 asof(ref_pit)加上因果上界;`date < start`
        # 的历史仍然可用(那是合法的过去数据)。
        _asof_sql = (
            ref_pit.isoformat() if hasattr(ref_pit, "isoformat") else str(ref_pit)
        )
        liquidity_codes = con.execute(
            (
                "SELECT thscode, date, amount FROM v_daily "
                "WHERE thscode IN ({codes_sql}) "
                "AND date <= '{asof}' "
                "ORDER BY thscode, date"
            ).format(codes_sql=codes_sql, asof=_asof_sql)
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


def load_bars_by_code(
    db_path: str,
    codes: list[str],
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    """拉取指定代码 [start, end] 的 v_daily 原始日线(供统一交易报告渲染)。

    SQL 含 ORDER BY(Tick 68 纪律); 与 load_universe_data 相同的 .format 模板风格。
    """
    if not codes:
        return {}
    con = duckdb.connect(db_path, read_only=True)
    try:
        codes_sql = ", ".join(f"'{c}'" for c in codes)
        panel = con.execute(
            (
                "SELECT thscode, date, open, high, low, close, volume, amount "
                "FROM v_daily WHERE thscode IN ({codes_sql}) "
                "AND date BETWEEN '{start}' AND '{end}' "
                "ORDER BY thscode, date"
            ).format(codes_sql=codes_sql, start=start, end=end)
        ).fetchdf()
    finally:
        con.close()
    if panel.empty:
        return {}
    panel["date"] = pd.to_datetime(panel["date"])
    return {c: g.reset_index(drop=True) for c, g in panel.groupby("thscode")}
