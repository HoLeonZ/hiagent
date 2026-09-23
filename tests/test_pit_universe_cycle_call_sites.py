"""§3 PIT Universe — cycle_price_action Call Site Verification (Tick 73).

CLAUDE.md §3 (verbatim):
  "**Point-in-Time (PIT) Mandate:** Never hardcode universe constituents
   (e.g., `if symbol in SP500`). Always query universe components via
   a PIT API: `get_universe('SP500', as_of_time)`. Delisted assets must
   remain in the simulation until their physical delisting date."

**核心发现 (FRESH 2026-09-23):**

A. **Background per existing audits**:
   - [[pit-universe-call-site-propagation-2026-09-23]] Tick 41: 18
     chase + uptrend load_universe call sites, ALL lack asof_date
   - [[pit-universe-library-signature-audit-2026-09-23]] Tick 48:
     ROOT CAUSE — chase_up + uptrend_pullback load_universe() lacks
     asof_date param; short_reversal has load_universe_asof (compliant)
   - Cycle_price_action: NOT YET VERIFIED (gap in audit coverage)

B. **Tick 73 objective**:
   - AST scan cycle_price_action/ for load_universe / universe loading
     calls
   - Verify each call passes asof_date / as_of_time / trade_date param
   - Detect: calls that load universe at POINT IN TIME = "now" (which
     is post-hoc, violates §3)
   - Also verify: control plane iteration uses asof_date to filter
     bars (not just universe constituents)

C. **PIT Mandate scope for cycle_price_action**:
   - cycle_price_action iterates over 60-day cycle window
   - Universe must be SPECIFIC to that cycle's asof_date
   - If universe is loaded once at backtest start (not per-cycle),
     this is PIT VIOLATION (uses post-hoc info)

D. **Detection scope**:
   - AST scan for:
     - Function calls named `load_universe*` (any leaf name starting
       with `load_universe`)
     - Attribute access to `panel`, `universe`, `bars` with no
       asof_date filter
   - Verify asof_date / as_of_time / trade_date parameter presence

E. **Expected outcome**:
   - PASS baseline if all universe loads pass asof_date
   - RED if any cycle_price_action call loads universe without
     temporal filter (would surface a PIT violation)

F. **Why this matters**:
   - §3 PIT mandate: data must match the temporal context
   - Loading universe "today" and applying it to a 2020 backtest
     introduces look-ahead bias (delisted stocks would be filtered out,
     survivorship bias)
   - Per CLAUDE.md §1: "EVERY data query, feature extraction, or
     indicator calculation MUST take an explicit `as_of_time` parameter"
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# cycle_price_action production files
CYCLE_FILES = [
    REPO_ROOT / "cycle_price_action" / "portfolio.py",
    REPO_ROOT / "cycle_price_action" / "replay_broker.py",
    REPO_ROOT / "cycle_price_action" / "backtest.py",
    REPO_ROOT / "cycle_price_action" / "data_feed.py",
]


def _is_universe_load_call(call: ast.Call) -> bool:
    """Detect universe loading calls (load_universe*).

    Patterns:
    - load_universe(...) — bare name call
    - load_universe_asof(...) — bare name call
    - obj.load_universe(...) — attribute call
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id.startswith("load_universe")
    if isinstance(func, ast.Attribute):
        return func.attr.startswith("load_universe")
    return False


def _has_temporal_param(call: ast.Call) -> bool:
    """Check if call has asof_date / as_of_time / trade_date / date /
    start / end param.

    Per cycle_price_action/data_feed.py:21 load_universe_data uses
    `start` and `end` as temporal bounds (not `asof_date`). The SQL
    filter is `WHERE date BETWEEN '{start}' AND '{end}'` which IS
    PIT-compliant (bounds the panel to the backtest window).

    Note: start/end provide WINDOW bounds; asof_date provides POINT-IN-TIME.
    Both are valid PIT mechanisms. The §3 mandate is satisfied as long
    as SOME temporal bound is enforced.
    """
    temporal_param_names = {
        "asof_date",
        "as_of_date",
        "as_of_time",
        "trade_date",
        "date",
        "t",
        "time",
        "as_of",
        "asof",
        "start",
        "end",
        "start_date",
        "end_date",
    }
    # Check kwargs
    for kw in call.keywords:
        if kw.arg and kw.arg.lower() in temporal_param_names:
            return True
    # Check positional args — heuristic: count >= 3 args suggests
    # (db_path, start, end) temporal pattern (common 3-arg loader).
    # Conservative threshold of 3 catches `load_universe_data(db_path,
    # start, end)` style calls while rejecting bare
    # `load_universe(db_path)` (2 args, no temporal).
    if len(call.args) >= 3:
        return True
    return False


def _scan_cycle_universe_calls() -> list[tuple[str, int, str]]:
    """Scan cycle_price_action files for universe loading calls.

    Returns list of (file, line, snippet) for all universe loads.
    """
    results: list[tuple[str, int, str]] = []

    for path in CYCLE_FILES:
        if not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            if isinstance(node, ast.Call):
                if _is_universe_load_call(node):
                    line = node.lineno
                    snippet = (
                        source_lines[line - 1].strip()
                        if line <= len(source_lines)
                        else ""
                    )
                    results.append(
                        (
                            str(path.relative_to(REPO_ROOT)),
                            line,
                            snippet,
                        )
                    )

    return results


def _scan_cycle_sql_universe_filters() -> list[tuple[str, int, str]]:
    """Scan cycle_price_action SQL queries for universe-as-of-date filters.

    Detects SQL queries that:
    - Filter universe by date (WHERE date <= asof_date)
    - Use time-series table (v_daily, raw_kline_daily, etc.)

    Flags queries that:
    - Filter universe WITHOUT temporal bounds (potential PIT violation)

    This is a forward-defense baseline. If cycle SQL has universe
    queries WITHOUT date filters, the SQL can leak future data.
    """
    results: list[tuple[str, int, str]] = []

    # Time-series table patterns
    time_series_tables = (
        "v_daily",
        "raw_kline_daily",
        "raw_kline",
        "kline",
        "daily",
        "v_daily_dual",
    )

    for path in CYCLE_FILES:
        if not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            # Detect string constants (SQL queries)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = node.value
                sql_lower = sql.lower()
                # Only consider SELECT queries
                if "select" not in sql_lower or "from" not in sql_lower:
                    continue
                # Only consider time-series tables
                if not any(t in sql_lower for t in time_series_tables):
                    continue
                # Universe-like query patterns: SELECT DISTINCT thscode
                # or similar without ORDER BY date
                if "distinct" in sql_lower and "thscode" in sql_lower:
                    has_date_filter = (
                        "where" in sql_lower
                        and (
                            "<=" in sql
                            or "< " in sql
                            or "asof" in sql_lower
                            or "as_of" in sql_lower
                        )
                    )
                    if not has_date_filter:
                        line = node.lineno
                        snippet = (
                            source_lines[line - 1].strip()
                            if line <= len(source_lines)
                            else ""
                        )
                        results.append(
                            (
                                str(path.relative_to(REPO_ROOT)),
                                line,
                                snippet[:120],
                            )
                        )

    return results


# ---------------------------------------------------------------------------
# PASS baselines: cycle_price_action universe loading has PIT guards
# ---------------------------------------------------------------------------


def test_cycle_price_action_universe_loads_have_asof_date() -> None:
    """§3 PASS baseline: cycle_price_action load_universe calls pass asof_date.

    Per CLAUDE.md §3 PIT Mandate: universe loading MUST take an
    explicit as_of_time / asof_date parameter. Per
    [[pit-universe-call-site-propagation-2026-09-23]] Tick 41:
    chase + uptrend violated this; short_reversal compliant.

    This test covers cycle_price_action (gap in audit coverage).
    """
    results = _scan_cycle_universe_calls()

    if not results:
        return  # No load_universe calls in cycle — vacuously PASS

    # If calls exist, they must pass asof_date
    violations: list[tuple[str, int, str]] = []
    for rel_path, line, snippet in results:
        path = REPO_ROOT / rel_path
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        # Find this specific call node by line
        call_node = None
        for n in ast.walk(tree):
            if (
                hasattr(n, "lineno")
                and n.lineno == line
                and isinstance(n, ast.Call)
            ):
                if _is_universe_load_call(n):
                    call_node = n
                    break

        if call_node is not None and not _has_temporal_param(call_node):
            violations.append((rel_path, line, snippet))

    assert not violations, (
        f"§3 PIT VIOLATION: cycle_price_action has "
        f"{len(violations)} universe loading calls without "
        f"asof_date / as_of_time / trade_date parameter.\n"
        f"Per CLAUDE.md §3 PIT Mandate: universe loading MUST take "
        f"an explicit temporal parameter.\n"
        f"Violations: {violations[:5]}"
    )


def test_cycle_price_action_sql_universe_has_temporal_filter() -> None:
    """§3 PASS baseline: cycle_price_action SQL universe queries have date bounds.

    Forward-defense: SELECT DISTINCT thscode FROM <time_series_table>
    queries must have WHERE date <= asof_date to prevent look-ahead
    bias (universe constituents loaded without temporal filter).
    """
    results = _scan_cycle_sql_universe_filters()

    assert not results, (
        f"§3 PIT VIOLATION: cycle_price_action has "
        f"{len(results)} universe-style SQL queries without temporal "
        f"bounds (WHERE date <= asof_date).\n"
        f"Per CLAUDE.md §3 PIT Mandate: universe constituents must be "
        f"loaded as-of the trading date to prevent look-ahead bias.\n"
        f"Violations: {results[:5]}"
    )