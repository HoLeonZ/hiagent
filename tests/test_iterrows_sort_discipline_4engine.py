"""§1 Lookahead Bias — iterrows() Future-Peek Risk Audit (Tick 66).

CLAUDE.md §1 (verbatim):
  "**Banned Global State:** NEVER normalize data using global `.mean()`
   or `.std()` prior to splitting. Use causal `.expanding()` or `.rolling()`
   statistics exclusively."

CLAUDE.md §0 (verbatim):
  "**Immutable State:** Treat all historical data and portfolio states as
   append-only."

**核心发现 (FRESH 2026-09-23):**

A. **§1 Lookahead Bias risk via iterrows()**:
   - pandas `df.iterrows()` does NOT preserve row order by default
     when called on unsorted DataFrames
   - If a Strategy/Portfolio iterates rows in arbitrary order, the
     "current row" can be from ANY timestamp, not strictly past
   - Per [[reproducibility-audit-2026-09-23]] Tick 36: backtrader_engine.py
     uses iterrows at lines 70, 225 (fragile — depends on caller ordering)

B. **Sort discipline may live OUTSIDE iterrows() function**:
   - chase_up/backtrader_engine.py:108 → `code_data.sort_values("date")`
     precedes iterrows at :70 (sort at caller, NOT in same function)
   - chase_up/backtrader_engine.py:225 → `trades_p1` is sorted by CSV
     write order (chronological by entry_date, per Tick 60)
   - This is COMPLIANT but invisible to same-FunctionDef sort scan

C. **REAL §1 risk = future peek via .shift(-N)**:
   - `df.shift(-1)` peeks at next row's value
   - `df.shift(-N)` peeks N rows ahead
   - Per CLAUDE.md §1: "Banned Functions: NEVER use df.bfill(),
     df.shift(-x), or df.rolling(center=True)"
   - These are banned GLOBALLY (per Tick 52)
   - But paired with iterrows(), they're an especially dangerous
     pattern (silent temporal leak in iteration)

D. **Detector scope**:
   - For each engine: scan production hot paths for `.shift(-N)`
     ANYWHERE in the file
   - iterrows() count + future_peek violation count
   - PASS if no `.shift(-N)` violations exist
   - Sort discipline is acknowledged as caller-responsibility

E. **Why this matters**:
   - §1 Temporal Determinism: time is strictly monotonic
   - §0 Pessimistic Default: must assume worst case
   - If row order is non-monotonic AND shift(-N) is used:
     - Strategy effectively peeks at next bar's data
     - PIT mandate silently violated
     - Backtest results inflated

F. **Test results (Tick 66 expected)**:
   - 4 PASS baselines: zero `.shift(-N)` violations across 4 engines
   - 0 RED expected (Tick 52 already verified banned functions = 0)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production hot-path files per engine (where iterrows() would be risky)
ITERROWS_SEARCH_PATHS = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "strategy.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "strategy.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "portfolio.py",
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "engine.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
        REPO_ROOT / "cycle_price_action" / "data_feed.py",
    ],
}


def _scan_iterrows_pattern() -> dict[str, dict[str, object]]:
    """Scan production files for iterrows() + future_peek patterns.

    Returns dict[engine → {
        "iterrows_count": int,
        "shift_negative_count": int,  # .shift(-N) — banned by §1
        "future_peek_violations": list[tuple[file, line, snippet]],
    }]
    """
    results: dict[str, dict[str, object]] = {}

    for engine, paths in ITERROWS_SEARCH_PATHS.items():
        iterrows_count = 0
        shift_negative_count = 0
        future_peek_violations: list[tuple[str, int, str]] = []

        for path in paths:
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
                line = node.lineno

                # Detect `.iterrows()` call
                if isinstance(node, ast.Call):
                    func_node = node.func
                    attr_name = ""
                    if isinstance(func_node, ast.Attribute):
                        attr_name = func_node.attr
                    elif (
                        isinstance(func_node, ast.Call)
                        and isinstance(func_node.func, ast.Attribute)
                    ):
                        attr_name = func_node.func.attr
                    if attr_name == "iterrows":
                        iterrows_count += 1

                # Detect `.shift(-N)` future peek (banned by §1)
                # Pattern: .shift(-1), .shift(-2), .shift(-N)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "shift":
                        if node.args and isinstance(node.args[0], ast.UnaryOp):
                            if isinstance(node.args[0].op, ast.USub):
                                shift_negative_count += 1
                                snippet = (
                                    source_lines[line - 1].strip()
                                    if line <= len(source_lines)
                                    else ""
                                )
                                future_peek_violations.append(
                                    (str(path.relative_to(REPO_ROOT)), line, snippet)
                                )

        results[engine] = {
            "iterrows_count": iterrows_count,
            "shift_negative_count": shift_negative_count,
            "future_peek_violations": future_peek_violations,
        }

    return results


# ---------------------------------------------------------------------------
# PASS baselines: zero .shift(-N) violations across 4 engines
# ---------------------------------------------------------------------------


def test_chase_up_iterrows_no_future_peek() -> None:
    """§1 PASS baseline: chase_up has no iterrows() + .shift(-N) violation.

    Per CLAUDE.md §1: .shift(-N) is BANNED. iterrows() paired with
    shift(-N) is especially dangerous (silent temporal leak in iteration).
    Per [[reproducibility-audit-2026-09-23]]: backtrader_engine.py uses
    iterrows at lines 70, 225. Sort discipline is caller-level
    (line 108: code_data.sort_values("date")).

    This test verifies the ABSENCE of shift(-N) which is the actual
    §1 lookahead risk in iteration context.
    """
    results = _scan_iterrows_pattern()
    chase = results["chase_up"]

    violations = chase["future_peek_violations"]
    shift_neg = chase["shift_negative_count"]

    assert shift_neg == 0, (
        f"§1 LOOKAHEAD VIOLATION: chase_up has {shift_neg} "
        f".shift(-N) calls in production hot paths.\n"
        f"Per CLAUDE.md §1: shift(-N) is BANNED (peeks future rows).\n"
        f"Per Tick 52: banned functions should be 0 across all engines.\n"
        f"Violations: {violations}"
    )


def test_uptrend_pullback_iterrows_no_future_peek() -> None:
    """§1 PASS baseline: uptrend_pullback has no shift(-N) violation."""
    results = _scan_iterrows_pattern()
    uptrend = results["uptrend_pullback"]

    shift_neg = uptrend["shift_negative_count"]
    violations = uptrend["future_peek_violations"]

    assert shift_neg == 0, (
        f"§1 LOOKAHEAD VIOLATION: uptrend_pullback has {shift_neg} "
        f".shift(-N) calls. Per CLAUDE.md §1: shift(-N) is BANNED.\n"
        f"Violations: {violations}"
    )


def test_short_reversal_iterrows_no_future_peek() -> None:
    """§1 PASS baseline: short_reversal has no shift(-N) violation."""
    results = _scan_iterrows_pattern()
    short = results["short_reversal"]

    shift_neg = short["shift_negative_count"]
    violations = short["future_peek_violations"]

    assert shift_neg == 0, (
        f"§1 LOOKAHEAD VIOLATION: short_reversal has {shift_neg} "
        f".shift(-N) calls. Per CLAUDE.md §1: shift(-N) is BANNED.\n"
        f"Violations: {violations}"
    )


def test_cycle_price_action_iterrows_no_future_peek() -> None:
    """§1 PASS baseline: cycle_price_action has no shift(-N) violation."""
    results = _scan_iterrows_pattern()
    cycle = results["cycle_price_action"]

    shift_neg = cycle["shift_negative_count"]
    violations = cycle["future_peek_violations"]

    assert shift_neg == 0, (
        f"§1 LOOKAHEAD VIOLATION: cycle_price_action has {shift_neg} "
        f".shift(-N) calls. Per CLAUDE.md §1: shift(-N) is BANNED.\n"
        f"Violations: {violations}"
    )