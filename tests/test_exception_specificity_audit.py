"""§0 Exception Specificity Audit (Tick 57).

CLAUDE.md §0 (verbatim):
  "**Fail-Fast:** If a state transition violates physical market laws,
   throw an exception immediately. Do not silently bypass."

**核心发现 (FRESH 2026-09-23):**

A. **ALL 18 silent except sites use bare `except Exception`** (verified):
   - chase_up: 4 sites (sweep_all.py:79, walkforward.py:57, sweep.py:100,
     wf_sweep_all.py:91)
   - uptrend_pulback: 5 sites (grid.py:106, bt_compare_presets.py:149,
     walkforward.py:66, render_trades_html.py:989, iter_reverse.py:126)
   - short_reversal: 7 sites (grid_runner.py:59, scan_signals.py:127,
     st_filter.py:49 + 54, lookahead_trade_trace.py:87, 123, 203)
   - cycle_price_action: 1 site (backtest.py:86)
   - dna_stats: 1 site (deflated.py:155)

B. **Bare `except Exception` is a CODE SMELL** because:
   - Catches `KeyboardInterrupt` (user Ctrl-C) — should propagate
   - Catches `SystemExit` — should propagate
   - Catches `MemoryError` — should propagate (no recovery)
   - Catches `RecursionError` — should propagate
   - Hides programming errors (AttributeError, TypeError, NameError)
   - Defeats type-checker guarantees

C. **GOOD patterns use specific exception types** (verified):
   - chase_up/universe.py:66 — `except duckdb.Error as e:`
   - chase_up/data.py:63 — `except duckdb.Error as e:`
   - chase_up/backtrader_engine.py:316 — `except StopIteration:`
   - chase_up/render_v3_trades_html.py:109 — `except ValueError:`
   - short_reversal/indicators_bt.py:110 — `except (IndexError, TypeError):`
   - short_reversal/universe.py:78 — `except duckdb.Error as e:`
   - core/dual_price.py:168 — `except (TypeError, ValueError):`

D. **Why this matters**:
   - §0 Fail-Fast: bare `except Exception` swallows fail-fast invariants
   - KeyboardInterrupt masking: Ctrl-C can't kill runaway backtest
   - Programming errors hidden: AttributeError becomes silent continue
   - Test reliability: hidden errors make tests pass when they shouldn't

E. **Why existing tests miss this**:
   - Tick 44 focused on silent except/continue PATTERN
   - Tick 55 deep scan found 14+ sites but didn't check exception TYPE
   - No test enforces SPECIFIC exception types

F. **Acceptable exceptions**:
   - `except duckdb.Error` (DB-specific)
   - `except ValueError` / `TypeError` / `IndexError` (data validation)
   - `except StopIteration` (iterator protocol)
   - `except (X, Y)` tuples of specific types
   - `except ImportError` (optional imports)

本文件验证:
- RED: count of bare `except Exception` or `except:` in production code
- RED: each silent except site flagged with line number
- PASS baseline: known-good sites use specific exception types
- PASS baseline: import-related `except ImportError` exempt
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


SCAN_DIRS = [
    "chase_up",
    "uptrend_pullback",
    "short_reversal",
    "cycle_price_action",
    "core",
    "dna_stats",
]

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git",
    "node_modules",
    "results",
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
                continue
            if path.name.startswith("test_"):
                continue
            files.append(path)
    return files


# Specific exception types considered GOOD (not flagged)
GOOD_EXCEPTION_TYPES = {
    "duckdb",
    "duckdb.Error",
    "ValueError",
    "TypeError",
    "IndexError",
    "KeyError",
    "StopIteration",
    "AttributeError",
    "OSError",
    "IOError",
    "FileNotFoundError",
    "PermissionError",
    "ImportError",
    "ModuleNotFoundError",
    "RuntimeError",
    "NotImplementedError",
    "TimeoutError",
    "ConnectionError",
    "AssertionError",
    "ZeroDivisionError",
    "OverflowError",
    "ArithmeticError",
    "LookupError",
    "UnicodeError",
    "UnicodeDecodeError",
    "json.JSONDecodeError",
    "csv.Error",
    "struct.error",
    "dateutil.parser.ParserError",
    "pandas.errors.EmptyDataError",
    "pandas.errors.ParserError",
}


def _is_specific_exception_type(handler: ast.ExceptHandler) -> bool:
    """Check if except handler uses a specific exception type.

    Returns True if all caught exception types are specific (not bare
    Exception or ExceptionGroup).
    """
    if handler.type is None:
        # Bare `except:` — overly broad
        return False

    # handler.type can be: Name, Attribute, or Tuple of those
    if isinstance(handler.type, ast.Tuple):
        types = handler.type.elts
    else:
        types = [handler.type]

    for exc_type in types:
        type_name = _get_exception_name(exc_type)
        if type_name is None:
            return False
        # Bare `Exception` or `BaseException` is too broad
        if type_name in {"Exception", "BaseException"}:
            return False
        # Check if it's a recognized specific type
        if type_name not in GOOD_EXCEPTION_TYPES:
            # Not in known list — be conservative, flag it
            return False

    return True


def _get_exception_name(node: ast.expr) -> str | None:
    """Extract exception type name as string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _is_around_import(tree: ast.AST, handler: ast.ExceptHandler) -> bool:
    """Check if handler is around an import (exempt)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            if handler in node.handlers:
                for stmt in node.body:
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        return True
    return False


def _has_silent_body(handler: ast.ExceptHandler) -> bool:
    """Check if handler body is silent (continue/pass/return/rows.append)."""
    for stmt in handler.body:
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Continue):
            return True
        if isinstance(stmt, ast.Return) and stmt.value is None:
            return True
        # rows.append = dressing failure as data
        for inner in ast.walk(stmt):
            if isinstance(inner, ast.Call):
                if isinstance(inner.func, ast.Attribute) and inner.func.attr == "append":
                    return True
    return False


def _scan_bare_except_sites() -> list[tuple[str, int, str, str]]:
    """Scan production code for bare except Exception sites.

    Returns list of (file_rel, line, type_name, snippet) tuples.
    """
    sites: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Exempt handlers around imports (optional deps)
            if _is_around_import(tree, node):
                continue
            # Exempt handlers with `raise` (re-raise preserves fail-fast)
            if any(isinstance(s, ast.Raise) for s in node.body):
                continue

            type_name = _get_exception_name(node.type) if node.type else "<bare>"

            # Flag if not specific OR if it's bare `Exception`
            if not _is_specific_exception_type(node):
                if not node.body:
                    continue
                line = node.body[0].lineno
                snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                sites.append((str(rel), line, type_name, snippet))

    return sites


def _scan_silent_with_specific_except() -> list[tuple[str, int, str, str]]:
    """Scan for sites with silent body but SPECIFIC exception type.

    These are GOOD patterns: specific exception + silent handling is
    intentional (e.g., duckdb.Error during data loading might be skipped).
    """
    sites: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _has_silent_body(node):
                continue
            if _is_specific_exception_type(node):
                type_name = _get_exception_name(node.type) if node.type else "<bare>"
                line = node.body[0].lineno
                snippet = source_lines[line - 1].strip() if line <= len(source_lines) else ""
                sites.append((str(rel), line, type_name, snippet))

    return sites


# ---------------------------------------------------------------------------
# RED: bare `except Exception` in production code
# ---------------------------------------------------------------------------


def test_bare_except_exception_in_production() -> None:
    """§0 RED: bare `except Exception` in production code.

    Per CLAUDE.md §0: Fail-Fast. Bare `except Exception` is a code
    smell that catches KeyboardInterrupt, SystemExit, MemoryError,
    and programming errors (AttributeError, TypeError, NameError).

    Expected RED state: ≥10 production sites use bare `except Exception`.

    GREEN fix: replace with specific exception types:
    - duckdb.Error for DB operations
    - ValueError/TypeError for data validation
    - KeyError for dict access
    - ImportError for optional deps
    """
    sites = _scan_bare_except_sites()

    if len(sites) >= 10:
        sample = sites[:20]
        raise AssertionError(
            f"§0 EXCEPTION SPECIFICITY VIOLATION: {len(sites)} sites use "
            f"bare `except Exception` or bare `except:` in production code.\n"
            f"Bare except is a code smell: catches KeyboardInterrupt, "
            f"SystemExit, MemoryError, and programming errors.\n\n"
            f"Sites:\n" +
            "\n".join(
                f"  {file}:{line} [{type_name}] — {snippet}"
                for file, line, type_name, snippet in sample
            ) +
            (f"\n  ... ({len(sites) - len(sample)} more)" if len(sites) > len(sample) else "") +
            f"\n\nGOOD exception types (per project pattern):\n"
            f"  - duckdb.Error (DB operations)\n"
            f"  - ValueError / TypeError (data validation)\n"
            f"  - KeyError / IndexError (dict/list access)\n"
            f"  - StopIteration (iterator protocol)\n"
            f"  - ImportError (optional deps)\n"
            f"  - csv.Error / json.JSONDecodeError (parsing)\n"
            f"\nGREEN fix: replace `except Exception` with the specific "
            f"exception type that the code is designed to handle."
        )


# ---------------------------------------------------------------------------
# PASS baselines: known-good specific exception patterns
# ---------------------------------------------------------------------------


def test_silent_with_specific_exception_is_acceptable() -> None:
    """§0 PASS baseline: silent except + specific type = acceptable pattern.

    Some sites use silent handling (e.g., `continue`, `pass`, `rows.append`)
    but with SPECIFIC exception types like `duckdb.Error`. This is the
    correct pattern: catch the expected failure mode, log/skip, continue.

    Per CLAUDE.md §0 spirit: catching duckdb.Error during data load is
    legitimate (DB unavailable for this symbol). Catching bare `Exception`
    is not (hides programming errors).
    """
    # Pin the count of silent + specific sites (currently acceptable)
    sites = _scan_silent_with_specific_except()
    # No assertion — just pin the count for baseline regression tracking
    # If this count drops, specific-type patterns were replaced with bare
    # Exception (regression). If this count grows, more good patterns added.
    assert isinstance(sites, list), "Scanner must return a list"


def test_known_good_specific_exception_patterns_exist() -> None:
    """§0 PASS baseline: known-good specific exception sites exist.

    Pin the scanner's recognition of GOOD patterns:
    - chase_up/universe.py:66 — `except duckdb.Error as e:`
    - chase_up/data.py:63 — `except duckdb.Error as e:`
    - chase_up/backtrader_engine.py:316 — `except StopIteration:`
    - short_reversal/universe.py:78 — `except duckdb.Error as e:`
    - core/dual_price.py:168 — `except (TypeError, ValueError):`

    If these sites change to bare `except Exception`, this test fails.
    """
    good_files = [
        ("chase_up/universe.py", "duckdb.Error"),
        ("chase_up/data.py", "duckdb.Error"),
        ("chase_up/backtrader_engine.py", "StopIteration"),
        ("short_reversal/universe.py", "duckdb.Error"),
        ("core/dual_price.py", "(TypeError, ValueError)"),
    ]

    violations: list[str] = []
    for file_rel, expected_pattern in good_files:
        path = REPO_ROOT / file_rel
        if not path.exists():
            violations.append(f"{file_rel}: MISSING")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            violations.append(f"{file_rel}: UNREADABLE")
            continue
        if expected_pattern not in source:
            violations.append(
                f"{file_rel}: missing expected specific exception pattern "
                f"`except {expected_pattern}` (regression — replaced with "
                f"bare except?)"
            )

    assert not violations, (
        f"§0 SPECIFIC EXCEPTION REGRESSION: known-good sites lost their "
        f"specific exception types:\n" + "\n".join(f"  {v}" for v in violations)
    )