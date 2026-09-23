"""§1 Banned functions audit (Tick 52).

CLAUDE.md §1 (verbatim):
  - **Banned Functions:** NEVER use `df.bfill()`, `df.shift(-x)`, or
    `df.rolling(center=True)`.
  - **Banned Global State:** NEVER normalize data using global `.mean()`
    or `.std()` prior to splitting. Use causal `.expanding()` or
    `.rolling()` statistics exclusively.

**核心发现 (FRESH 2026-09-23):**

A. **Manual scan: 0 hits** (verified 2026-09-23):
   - `.bfill()`, `.ffill()`, `.shift(-N)`, `.rolling(center=True)`:
     0 occurrences across chase_up/ + uptrend_pullback/ + short_reversal/
     + cycle_price_action/ + core/ + dna_stats/

B. **Test coverage gap** (this audit):
   - test_*_no_lookahead.py files cover 8 dimensions (P0-P8) per engine:
     P0 ATR TP/SL, P1 exit_price, P2 trade completeness, P3 entry≠exit,
     P4 DB schema, P5 exit priority, P6 signal/exec decoupling,
     P7 indicator grouping, P8 universe as-of
   - NONE of these tests scan for the §1 banned function PATTERNS
     (`.bfill()`, `.shift(-x)`, `.rolling(center=True)`)
   - "CLEAN — 0 hits" in master ledger is a MANUAL check, not automated
   - If a contributor adds `.bfill()` tomorrow, nothing catches it

C. **AST static analysis**:
   - Walk every .py file in 4 engines + core + dna_stats
   - For every Call node, check if it's:
     - `df.bfill()` / `.ffill()` — method call to bfill/ffill
     - `.shift(-N)` — method call with negative arg
     - `.rolling(..., center=True)` — keyword arg `center=True`
   - Report file:line for each hit

D. **Why this matters**:
   - §1 violation = lookahead bias = catastrophic (backtest looks great
     but live trading loses money)
   - Automated guard prevents regression on §1
   - Pin the current clean state with PASS baselines
   - If a future contributor adds the pattern, the test catches it
     BEFORE merge

E. **Why test_*_no_lookahead.py misses this**:
   - They test specific dimensions (P0-P8), not general patterns
   - They use hardcoded test cases, not static analysis
   - §1 banned functions are a static analysis dimension

本文件验证:
- 4 PASS baselines (pin §1 cleanliness):
  - No `.bfill()` calls in any .py file
  - No `.ffill()` calls in any .py file
  - No `.shift(-N)` calls in any .py file
  - No `.rolling(center=True)` calls in any .py file
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories to scan for §1 violations
SCAN_DIRS = [
    "chase_up",
    "uptrend_pullback",
    "short_reversal",
    "cycle_price_action",
    "core",
    "dna_stats",
]

# Excluded subdirs (tests, __pycache__, etc.)
EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    "results",
}


def _iter_python_files() -> list[Path]:
    """Yield all .py files in SCAN_DIRS, excluding tests + cache dirs."""
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            # Skip excluded dirs
            if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
                continue
            # Skip test files (test_*.py)
            if path.name.startswith("test_"):
                continue
            files.append(path)
    return files


def _find_bfill_calls(tree: ast.AST, source_lines: list[str]) -> list[tuple[int, str]]:
    """Find all .bfill() and .ffill() method calls.

    Returns list of (line_number, method_name).
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {"bfill", "ffill"}:
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
            hits.append((line, node.func.attr, snippet))
    return hits


def _find_negative_shift_calls(
    tree: ast.AST, source_lines: list[str]
) -> list[tuple[int, str]]:
    """Find all .shift(-N) calls (negative shift = lookahead).

    Returns list of (line_number, snippet).
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "shift":
            continue
        # Check first positional arg is negative
        if not node.args:
            continue
        first_arg = node.args[0]
        is_negative = False
        # UnaryOp(-Constant(N))
        if isinstance(first_arg, ast.UnaryOp) and isinstance(first_arg.op, ast.USub):
            if isinstance(first_arg.operand, ast.Constant):
                is_negative = True
        # Constant negative number (rare in Python AST)
        elif isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, (int, float)):
            if first_arg.value < 0:
                is_negative = True
        if is_negative:
            line = node.lineno
            snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
            hits.append((line, snippet))
    return hits


def _find_center_true_rolling(
    tree: ast.AST, source_lines: list[str]
) -> list[tuple[int, str]]:
    """Find all .rolling(..., center=True) calls.

    Returns list of (line_number, snippet).
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "rolling":
            continue
        # Check keyword args for center=True
        for kw in node.keywords:
            if kw.arg == "center":
                if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    line = node.lineno
                    snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                    hits.append((line, snippet))
    return hits


def _scan_file_for_pattern(pattern_name: str) -> list[str]:
    """Scan all .py files for the named banned pattern.

    Returns list of "file:line: snippet" strings.
    """
    violations: list[str] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT)
        if pattern_name == "bfill":
            hits = _find_bfill_calls(tree, source_lines)
            for line, method, snippet in hits:
                violations.append(f"{rel}:{line}: .{method}() — {snippet}")
        elif pattern_name == "shift_negative":
            hits = _find_negative_shift_calls(tree, source_lines)
            for line, snippet in hits:
                violations.append(f"{rel}:{line}: .shift(-N) — {snippet}")
        elif pattern_name == "rolling_center":
            hits = _find_center_true_rolling(tree, source_lines)
            for line, snippet in hits:
                violations.append(f"{rel}:{line}: .rolling(center=True) — {snippet}")
    return violations


# ---------------------------------------------------------------------------
# PASS baselines — pin §1 cleanliness
# ---------------------------------------------------------------------------


def test_no_bfill_calls_in_production_code() -> None:
    """§1 PASS baseline: No `.bfill()` calls in any production .py file.

    Per CLAUDE.md §1: NEVER use df.bfill(). Current scan: 0 hits.

    Pin the clean state — if a contributor adds `.bfill()` tomorrow,
    this test will fail and alert them to the §1 violation.
    """
    violations = _scan_file_for_pattern("bfill")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} .bfill()/.ffill() "
        f"calls found in production code:\n" +
        "\n".join(f"  {v}" for v in violations[:10]) +
        (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_no_negative_shift_calls_in_production_code() -> None:
    """§1 PASS baseline: No `.shift(-N)` calls in any production .py file.

    Per CLAUDE.md §1: NEVER use df.shift(-x). Current scan: 0 hits.

    Pin the clean state — negative shift = lookahead = catastrophic.
    """
    violations = _scan_file_for_pattern("shift_negative")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} .shift(-N) "
        f"calls found in production code (negative shift = lookahead):\n" +
        "\n".join(f"  {v}" for v in violations[:10]) +
        (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_no_rolling_center_true_in_production_code() -> None:
    """§1 PASS baseline: No `.rolling(center=True)` calls in production.

    Per CLAUDE.md §1: NEVER use df.rolling(center=True). Current scan:
    0 hits.

    Pin the clean state — symmetric rolling window = lookahead.
    """
    violations = _scan_file_for_pattern("rolling_center")
    assert not violations, (
        f"§1 BANNED FUNCTION VIOLATION: {len(violations)} "
        f".rolling(center=True) calls found in production code (symmetric "
        f"window = lookahead):\n" +
        "\n".join(f"  {v}" for v in violations[:10]) +
        (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_section1_no_lookahead_test_files_exist_per_engine() -> None:
    """§1 PASS baseline: no_lookahead test files exist for all 4 engines.

    Pin the test infrastructure exists. test_*_no_lookahead.py covers
    dimensions P0-P8 per engine but doesn't scan for banned patterns
    (that's what tests 1-3 above do).
    """
    expected = [
        "tests/test_chase_up_no_lookahead.py",
        "tests/test_uptrend_pullback_no_lookahead.py",
        "tests/test_short_reversal_no_lookahead.py",
        "tests/test_cycle_price_action_no_lookahead.py",
    ]
    missing = [p for p in expected if not (REPO_ROOT / p).exists()]
    assert not missing, (
        f"Regression: missing §1 no_lookahead test files: {missing}"
    )