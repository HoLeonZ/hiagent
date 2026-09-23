"""§6 Module-Level Side Effects — Import-Time Purity Audit (Tick 71).

CLAUDE.md §6 (verbatim):
  "**Strategy / Inference:** Pure function. Receives `State(T)`,
   returns `Signal(T)`. Has no network/DB access."

CLAUDE.md §6 (verbatim):
  "**Code Generation Architecture Check** ... 2. **Strategy / Inference:**
   Pure function. ... Has no network/DB access."

**核心发现 (FRESH 2026-09-23):**

A. **§6 Strategy purity mandate**:
   - Strategy modules MUST be pure functions: `State(T) → Signal(T)`
   - No DB access (duckdb.connect, sqlite3.connect)
   - No network (requests.get, urllib.request, http.client)
   - No file mutation (open('w'), os.remove, os.rename)
   - These side effects belong in **Control Plane / Orchestrator**
     and **Execution Broker**, NOT Strategy
   - Module-level side effects are worse than function-level: they
     execute at IMPORT time, leaking state across all consumers

B. **Why module-level matters MORE than function-level**:
   - Function-level side effects execute when called (controllable)
   - Module-level side effects execute at import time (uncontrollable):
     - pytest collection triggers them
     - Other modules importing the same module re-trigger them
     - Mock/patch becomes impossible
     - Test order becomes order-dependent
   - Pure module: only function definitions and constants

C. **Detection scope**:
   - Top-level ast.Expr calls (function calls at module scope, not
     inside functions/classes)
   - Specifically: duckdb.connect / sqlite3.connect / requests.get /
     file opens with mode='w'/'a' / os.remove / os.rename /
     os.system / subprocess.run
   - Skip: function definitions, class definitions, imports, assignments

D. **Expected outcome**:
   - 4 PASS baselines: each engine's Strategy / Broker modules have
     ZERO module-level side effects
   - 0 RED expected if all Strategy/Broker modules are pure

E. **Why this matters**:
   - §6 Strategy purity enables unit testing without mocks
   - Module-level side effects break test isolation
   - Module-level side effects trigger at import time (slow startup)
   - Module-level DB connections may leak file handles
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Strategy/Broker modules per engine (where §6 purity applies)
STRATEGY_BROKER_MODULES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
        REPO_ROOT / "chase_up" / "strategy.py",
        REPO_ROOT / "chase_up" / "main.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
        REPO_ROOT / "uptrend_pullback" / "strategy.py",
        REPO_ROOT / "uptrend_pullback" / "main.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "portfolio.py",
        REPO_ROOT / "short_reversal" / "engine.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
        REPO_ROOT / "cycle_price_action" / "backtest.py",
    ],
}


# Side-effect call patterns to detect at module level.
# IMPORTANT: avoid overly broad tokens like "get" (catches
# `logging.getLogger` which is idempotent and not a side effect).
# Use AST-aware patterns: only match call names that are leaf
# function names (not attribute chains).
SIDE_EFFECT_CALL_PATTERNS = (
    "connect",  # duckdb.connect, sqlite3.connect
    "execute",  # cursor.execute (DB query)
    "urlopen",  # urllib.request.urlopen
    "urlretrieve",  # urllib.request.urlretrieve
    "remove",
    "rename",
    "system",  # os.system
    "popen",
    "Popen",  # subprocess.Popen
    "write_text",
    "write_bytes",
    "unlink",
    "mkdir",
    "makedirs",
    "rmtree",
)

# Patterns that need attribute-chain match (e.g., `requests.get`,
# `subprocess.run`, `builtins.open`). Catch only if final attribute
# matches (not `logging.getLogger`).
ATTR_CHAIN_FINAL_NAMES = (
    "get",
    "post",
    "put",
    "delete",
    "head",
    "patch",
    "run",  # subprocess.run (leaf)
    "open",  # builtins.open (leaf)
    "call",
)


def _is_leaf_call(call_node: ast.Call, leaf_name: str) -> bool:
    """Check if a Call node is a leaf function call with given name.

    Examples that MATCH:
    - requests.get(...) → leaf is `get`
    - open(...) → leaf is `open`
    - subprocess.run(...) → leaf is `run`

    Examples that DO NOT MATCH:
    - logging.getLogger(...) → leaf is `getLogger` (not `get`)
    - duckdb.connect(...) → leaf is `connect` (already in
      SIDE_EFFECT_CALL_PATTERNS)
    """
    func = call_node.func
    if isinstance(func, ast.Attribute):
        return func.attr == leaf_name
    if isinstance(func, ast.Name):
        return func.id == leaf_name
    return False


def _scan_module_level_side_effects() -> dict[str, list[tuple[str, int, str]]]:
    """Scan Strategy/Broker modules for module-level side-effect calls.

    Module-level = statements directly in `tree.body` (top-level).
    NOT inside FunctionDef / AsyncFunctionDef / ClassDef.

    Returns dict[engine → list of (file, line, snippet)]
    """
    results: dict[str, list[tuple[str, int, str]]] = {}

    for engine, paths in STRATEGY_BROKER_MODULES.items():
        violations: list[tuple[str, int, str]] = []

        for path in paths:
            if not path.exists():
                continue

            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                source_lines = source.splitlines()
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue

            # Walk ONLY top-level statements (not inside functions/classes)
            for node in tree.body:
                if not hasattr(node, "lineno"):
                    continue

                # We only care about: Expr (expression statements like
                # bare function calls) and Assign (assignments that may
                # invoke side-effect constructors like DuckDBPyConnection)
                if isinstance(node, ast.Expr):
                    # Bare expression statement — typically a function call
                    if isinstance(node.value, ast.Call):
                        # Match either substring patterns OR leaf-name
                        # attribute-chain patterns.
                        call_str = ast.unparse(node.value)
                        if any(
                            pat in call_str
                            for pat in SIDE_EFFECT_CALL_PATTERNS
                        ) or any(
                            _is_leaf_call(node.value, leaf)
                            for leaf in ATTR_CHAIN_FINAL_NAMES
                        ):
                            line = node.lineno
                            snippet = (
                                source_lines[line - 1].strip()
                                if line <= len(source_lines)
                                else ""
                            )
                            violations.append(
                                (
                                    str(path.relative_to(REPO_ROOT)),
                                    line,
                                    snippet,
                                )
                            )

                # Module-level assignments invoking side-effect constructors
                # (e.g., `conn = duckdb.connect(...)` at module top level)
                if isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Call):
                        call_str = ast.unparse(node.value)
                        if any(
                            pat in call_str
                            for pat in SIDE_EFFECT_CALL_PATTERNS
                        ) or any(
                            _is_leaf_call(node.value, leaf)
                            for leaf in ATTR_CHAIN_FINAL_NAMES
                        ):
                            line = node.lineno
                            snippet = (
                                source_lines[line - 1].strip()
                                if line <= len(source_lines)
                                else ""
                            )
                            violations.append(
                                (
                                    str(path.relative_to(REPO_ROOT)),
                                    line,
                                    snippet,
                                )
                            )

        results[engine] = violations

    return results


# ---------------------------------------------------------------------------
# PASS baselines: no module-level side effects in Strategy/Broker modules
# ---------------------------------------------------------------------------


def test_chase_up_no_module_level_side_effects() -> None:
    """§6 PASS baseline: chase_up Strategy/Broker modules are pure at import.

    Per CLAUDE.md §6: Strategy modules are pure functions, no DB /
    network / file mutation at module level. Module-level side effects
    execute at import time and break test isolation.
    """
    results = _scan_module_level_side_effects()
    chase = results["chase_up"]

    if chase:
        raise AssertionError(
            f"§6 MODULE-LEVEL SIDE EFFECT: chase_up has "
            f"{len(chase)} module-level side-effect calls in Strategy/"
            f"Broker modules.\n"
            f"Per CLAUDE.md §6: Strategy/Broker modules must be pure at "
            f"import time. DB / network / file mutations belong in "
            f"Control Plane or inside functions, not at module top "
            f"level.\n"
            f"Violations: {chase[:5]}"
        )


def test_uptrend_pullback_no_module_level_side_effects() -> None:
    """§6 PASS baseline: uptrend_pullback Strategy/Broker modules pure."""
    results = _scan_module_level_side_effects()
    uptrend = results["uptrend_pullback"]

    if uptrend:
        raise AssertionError(
            f"§6 MODULE-LEVEL SIDE EFFECT: uptrend_pullback has "
            f"{len(uptrend)} module-level side-effect calls.\n"
            f"Violations: {uptrend[:5]}"
        )


def test_short_reversal_no_module_level_side_effects() -> None:
    """§6 PASS baseline: short_reversal Strategy/Broker modules pure."""
    results = _scan_module_level_side_effects()
    short = results["short_reversal"]

    if short:
        raise AssertionError(
            f"§6 MODULE-LEVEL SIDE EFFECT: short_reversal has "
            f"{len(short)} module-level side-effect calls.\n"
            f"Violations: {short[:5]}"
        )


def test_cycle_price_action_no_module_level_side_effects() -> None:
    """§6 PASS baseline: cycle_price_action Strategy/Broker modules pure."""
    results = _scan_module_level_side_effects()
    cycle = results["cycle_price_action"]

    if cycle:
        raise AssertionError(
            f"§6 MODULE-LEVEL SIDE EFFECT: cycle_price_action has "
            f"{len(cycle)} module-level side-effect calls.\n"
            f"Violations: {cycle[:5]}"
        )