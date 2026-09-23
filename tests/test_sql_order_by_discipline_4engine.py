"""§1 SQL ORDER BY Discipline in Production Control Plane (Tick 68).

CLAUDE.md §1 (verbatim):
  "Time is a strictly monotonic, first-class citizen."

CLAUDE.md §6 (verbatim):
  "**Control Plane / Orchestrator:** Manages time-stepping and PIT data
   dispatching."

**核心发现 (FRESH 2026-09-23):**

A. **§1 SQL time-series monotonicity mandate**:
   - Any SQL query that produces time-series data MUST end with
     ORDER BY timestamp (or equivalent monotonic column)
   - Without ORDER BY, row order is implementation-defined (often
     insertion order, not temporal order)
   - If Control Plane ingests unordered rows:
     - iterrows() iterates in arbitrary order
     - Strategy may compute today's signal using yesterday's data
     - PIT mandate silently violated

B. **Per [[reproducibility-audit-2026-09-23]] Tick 36**:
   - cycle_price_action/data_feed.py:52 — MISSING ORDER BY
   - This is the EXECUTABLE FINDING that motivates this tick
   - Other engines' SQL queries need similar audit

C. **Detector scope (Tick 68)**:
   - Scan production files for SQL query patterns
   - Look for SELECT statements (regex on string literals)
   - For each SELECT, verify ORDER BY is present
   - PASS if all time-series queries have ORDER BY
   - RED if any time-series query lacks ORDER BY

D. **SQL pattern detection**:
   - Detect via Python string literals (triple-quoted SELECT blocks)
   - Look for `ORDER BY` clause
   - Identify "time-series" queries (queries selecting date/timestamp
     columns from kline/bar/trade tables)

E. **Out-of-scope (deferred)**:
   - Aggregation queries (COUNT/SUM/AVG) — naturally don't need ORDER BY
   - Lookup queries (WHERE single id) — don't need ORDER BY
   - Tick 68 focuses on time-series producing queries only

F. **Why this matters**:
   - §1 Temporal Determinism: time is strictly monotonic
   - §6 Control Plane: PIT data dispatching must be ordered
   - Without ORDER BY, SQL is non-deterministic across DB engines
   - SQLite vs DuckDB vs PostgreSQL return different orderings
   - Backtest becomes non-reproducible across DBs

G. **Tick 68 expected results**:
   - 4 PASS: each engine's SQL queries (when time-series) have ORDER BY
   - 0 RED expected (chase/uptrend/short_reversal may be compliant;
     cycle has 1 known missing ORDER BY per Tick 36)
   - If cycle RED found, that's CONFIRMED the Tick 36 finding
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production files with SQL queries (per-engine)
SQL_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "data.py",
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "data.py",
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "data.py",
        REPO_ROOT / "short_reversal" / "engine.py",
        REPO_ROOT / "short_reversal" / "scan_signals.py",
        REPO_ROOT / "short_reversal" / "scan_signals_fast.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "data_feed.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
    ],
}


# SQL query extraction regex (matches triple-quoted strings with SELECT)
SQL_TRIPLE_QUOTE_RE = re.compile(
    r'"""(.*?SELECT[^"]*?)"""',
    re.DOTALL | re.IGNORECASE,
)
SQL_SINGLE_QUOTE_RE = re.compile(
    r"'''(.*?SELECT.*?)'''",
    re.DOTALL | re.IGNORECASE,
)


def _is_time_series_query(query: str) -> bool:
    """Determine if a SQL query produces time-series output.

    Heuristic:
    - Extract SELECT clause (between SELECT and FROM)
    - If SELECT clause has bare `date` / `timestamp` column (not
      wrapped in MAX/MIN/SUM/AVG/COUNT) → time-series
    - Pure aggregation queries (no bare date column in SELECT) →
      not time-series (output is scalar or per-group aggregate)
    """
    q_lower = query.lower()
    if "select" not in q_lower:
        return False

    # Find SELECT clause: between first SELECT and FROM
    select_match = re.search(r"\bselect\b(.*?)\bfrom\b", q_lower, re.DOTALL)
    if not select_match:
        # SELECT without FROM (e.g., SELECT 1) — not time-series
        return False
    select_clause = select_match.group(1)

    # Find time-series tables
    time_series_table = any(
        kw in q_lower
        for kw in (
            "kline",
            "bar",
            "trade",
            "ohlc",
            "raw_kline",
            "v_daily",
            "panel",
            "universe",
        )
    )

    # Look for bare `date` / `timestamp` column (not aggregated)
    # Strip aggregation function calls first
    select_no_aggs = re.sub(
        r"\b(?:MAX|MIN|SUM|AVG|COUNT)\s*\([^)]*\)",
        "",
        select_clause,
        flags=re.IGNORECASE,
    )
    has_bare_date = bool(re.search(
        r"\b(?:date|timestamp|trade_date|bar_date)\b",
        select_no_aggs,
    ))

    # Time-series iff: queries a time-series table AND selects bare date
    return time_series_table and has_bare_date


def _has_order_by(query: str) -> bool:
    """Check if SQL query has ORDER BY clause."""
    return bool(re.search(r"\bORDER\s+BY\b", query, re.IGNORECASE))


def _scan_sql_queries() -> dict[str, list[tuple[str, int, str, bool]]]:
    """Scan production files for SQL queries lacking ORDER BY.

    Uses AST to find string literals (ast.Constant with str value)
    that contain SELECT statements — avoiding docstring false positives.

    Returns dict[engine → list of (file, line, query_snippet, has_order_by)]
    """
    import ast

    results: dict[str, list[tuple[str, int, str, bool]]] = {}

    for engine, paths in SQL_FILES.items():
        violations: list[tuple[str, int, str, bool]] = []

        for path in paths:
            if not path.exists():
                continue

            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            # Find docstring range to skip
            docstring_end = 0
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                docstring_end = tree.body[0].end_lineno or 0

            for node in ast.walk(tree):
                if not hasattr(node, "lineno"):
                    continue
                line = node.lineno

                # Skip docstrings (top-level module docstring)
                if line <= docstring_end:
                    continue

                # Only consider ast.Constant strings
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    query = node.value
                    # Skip short strings (likely not SQL)
                    if len(query) < 20:
                        continue
                    # Check if it's a SQL query (starts with SELECT)
                    stripped = query.strip().lower()
                    if not (
                        stripped.startswith("select")
                        or stripped.startswith("with ")
                    ):
                        continue
                    if _is_time_series_query(query):
                        snippet = query.strip()[:120].replace("\n", " ")
                        has_order = _has_order_by(query)
                        violations.append(
                            (
                                str(path.relative_to(REPO_ROOT)),
                                line,
                                snippet,
                                has_order,
                            )
                        )

        results[engine] = violations

    return results


# ---------------------------------------------------------------------------
# PASS baselines: time-series SQL queries have ORDER BY
# ---------------------------------------------------------------------------


def test_chase_up_sql_queries_have_order_by() -> None:
    """§1 PASS baseline: chase_up SQL queries (time-series) have ORDER BY.

    Per CLAUDE.md §1: SQL queries producing time-series data must
    end with ORDER BY timestamp to guarantee monotonic delivery.
    """
    results = _scan_sql_queries()
    chase = results["chase_up"]

    # Filter to time-series queries WITHOUT order by
    missing = [v for v in chase if not v[3]]

    assert not missing, (
        f"§1 MISSING ORDER BY: chase_up has {len(missing)} time-series "
        f"SQL queries without ORDER BY clause.\n"
        f"Per CLAUDE.md §1: time-series queries MUST end with "
        f"ORDER BY timestamp for monotonic delivery.\n"
        f"Per CLAUDE.md §6: Control Plane requires ordered PIT data.\n"
        f"Violations: {missing[:5]}"
    )


def test_uptrend_pullback_sql_queries_have_order_by() -> None:
    """§1 PASS baseline: uptrend_pullback SQL queries have ORDER BY."""
    results = _scan_sql_queries()
    uptrend = results["uptrend_pullback"]

    missing = [v for v in uptrend if not v[3]]

    assert not missing, (
        f"§1 MISSING ORDER BY: uptrend_pullback has {len(missing)} "
        f"time-series SQL queries without ORDER BY.\n"
        f"Violations: {missing[:5]}"
    )


def test_short_reversal_sql_queries_have_order_by() -> None:
    """§1 PASS baseline: short_reversal SQL queries have ORDER BY."""
    results = _scan_sql_queries()
    short = results["short_reversal"]

    missing = [v for v in short if not v[3]]

    assert not missing, (
        f"§1 MISSING ORDER BY: short_reversal has {len(missing)} "
        f"time-series SQL queries without ORDER BY.\n"
        f"Violations: {missing[:5]}"
    )


def test_cycle_price_action_sql_queries_have_order_by() -> None:
    """§1 RED documented: cycle_price_action data_feed.py:52 missing ORDER BY.

    Per [[reproducibility-audit-2026-09-23]] Tick 36:
    cycle_price_action/data_feed.py:52 — MISSING ORDER BY.

    This is an EXECUTABLE VERIFICATION of the documented finding.
    """
    results = _scan_sql_queries()
    cycle = results["cycle_price_action"]

    missing = [v for v in cycle if not v[3]]

    if missing:
        raise AssertionError(
            f"§1 MISSING ORDER BY (CONFIRMED per Tick 36): "
            f"cycle_price_action has {len(missing)} time-series SQL "
            f"queries without ORDER BY.\n"
            f"Per CLAUDE.md §1: time-series queries MUST end with "
            f"ORDER BY timestamp for monotonic delivery.\n"
            f"Per [[reproducibility-audit-2026-09-23]]: cycle/data_feed.py:52 "
            f"is documented missing ORDER BY.\n"
            f"Violations: {missing[:5]}"
        )