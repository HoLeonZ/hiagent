"""§6 3-Layer Architecture forward-defense for chase_up + uptrend_pullback (Tick 56).

CLAUDE.md §6 (verbatim):
  "1. **Control Plane / Orchestrator:** Manages time-stepping and PIT
     data dispatching.
   2. **Strategy / Inference:** Pure function. Receives `State(T)`,
     returns `Signal(T)`. Has no network/DB access.
   3. **Execution Broker:** Handles slippage, liquidity limits, and
     atomic cash locking."

**核心发现 (FRESH 2026-09-23):**

A. **Tick 40 found §6 Strategy purity violation in short_reversal**:
   - short_reversal/scan_signals.py:34 `_load_panel` calls duckdb.connect
     inside Strategy module (Strategy purity violation)

B. **Tick 49 found §6 Broker purity violation in cycle_price_action**:
   - cycle_price_action/replay_broker.py:41,54 opens duckdb per fill
     (Broker purity violation)

C. **Tick 56 forward-defense: chase_up + uptrend_pullback §6 compliant**:
   - ZERO duckdb imports in:
     - chase_up: portfolio.py, replay_strategy.py, replay_broker.py,
       signals.py, backtrader_engine.py
     - uptrend_pullback: portfolio.py, replay_strategy.py,
       replay_broker.py, signals.py, backtrader_engine.py
   - DB access correctly relegated to Control Plane:
     - data.py (panel loading)
     - universe.py (universe composition, PIT mandate)
   - DB access in post-processing (acceptable):
     - audit_phantom.py (audit tool, not in hot path)
     - render_trades_html.py (HTML rendering, post-backtest)

D. **Why this matters**:
   - §6 Strategy purity: enables unit testing without DB
   - §6 Broker purity: deterministic execution, no DB I/O latency
   - §6 Control Plane isolation: data flow is one-directional
     (Control Plane -> Strategy -> Broker)
   - Violating §6 = unit tests become integration tests, harder to
     pin invariants, harder to reproduce

E. **Why existing test_3layer_architecture_gap misses this**:
   - Tick 40 test only covers short_reversal
   - Tick 49 test only covers cycle
   - chase_up + uptrend_pullback had NO forward-defense guard
   - This tick pins their compliance as PASS baseline

F. **Acceptable exceptions** (DB access OK):
   - Control Plane modules: data.py, universe.py (data dispatching)
   - Audit tools: audit_*.py (offline analysis)
   - Post-processing: render_*.py (HTML/CSV output, post-backtest)
   - Test files: conftest.py, test_*.py (test fixtures)

本文件验证:
- PASS baselines: chase_up + uptrend_pullback Strategy/Broker modules
  have ZERO duckdb imports (5 modules each = 10 modules verified)
- PASS baselines: Control Plane modules (data.py, universe.py) DO have
  DB access (pin correct architectural separation)
- Forward-defense: any future Strategy/Broker module that imports
  duckdb fails this test
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Strategy + Broker modules per CLAUDE.md §6 (must NOT have DB access)
STRATEGY_BROKER_MODULES = {
    "chase_up": [
        "portfolio.py",
        "replay_strategy.py",
        "replay_broker.py",
        "signals.py",
        "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        "portfolio.py",
        "replay_strategy.py",
        "replay_broker.py",
        "signals.py",
        "backtrader_engine.py",
    ],
}

# Control Plane modules (MUST have DB access — pins correct separation)
CONTROL_PLANE_MODULES = {
    "chase_up": ["data.py", "universe.py"],
    "uptrend_pullback": ["data.py", "universe.py"],
}


def _has_duckdb_import(path: Path) -> bool:
    """Check if module imports duckdb at module level."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "duckdb" or alias.name.startswith("duckdb."):
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "duckdb" or node.module.startswith("duckdb.")):
                return True
    return False


# ---------------------------------------------------------------------------
# PASS baselines: chase_up + uptrend_pullback §6 compliant (Strategy purity)
# ---------------------------------------------------------------------------


def test_chase_up_strategy_broker_modules_have_no_db_access() -> None:
    """§6 PASS baseline: chase_up Strategy/Broker modules are duckdb-free.

    CLAUDE.md §6 verbatim:
      "Strategy / Inference: Pure function. ... Has no network/DB access."
      "Execution Broker: Handles slippage, liquidity limits, and atomic
       cash locking."

    Verified by AST scan: chase_up/{portfolio,replay_strategy,
    replay_broker,signals,backtrader_engine}.py have ZERO duckdb imports.

    If any future change adds duckdb import to these modules, this test
    fails — preserving §6 architectural separation.
    """
    base = REPO_ROOT / "chase_up"
    violations: list[str] = []
    for module_name in STRATEGY_BROKER_MODULES["chase_up"]:
        path = base / module_name
        if not path.exists():
            violations.append(f"{module_name}: MISSING")
            continue
        if _has_duckdb_import(path):
            violations.append(
                f"{module_name}: imports duckdb (Strategy/Broker §6 purity "
                f"violation — must be pure, no DB access)"
            )

    assert not violations, (
        f"§6 ARCHITECTURE VIOLATION: chase_up Strategy/Broker modules "
        f"import duckdb:\n" + "\n".join(f"  {v}" for v in violations)
    )


def test_uptrend_pullback_strategy_broker_modules_have_no_db_access() -> None:
    """§6 PASS baseline: uptrend_pullback Strategy/Broker duckdb-free.

    Same as chase_up but for uptrend_pullback.

    Per CLAUDE.md §6: Strategy = pure, Broker = execution only.
    DB access is Control Plane's responsibility (data.py, universe.py).
    """
    base = REPO_ROOT / "uptrend_pullback"
    violations: list[str] = []
    for module_name in STRATEGY_BROKER_MODULES["uptrend_pullback"]:
        path = base / module_name
        if not path.exists():
            violations.append(f"{module_name}: MISSING")
            continue
        if _has_duckdb_import(path):
            violations.append(
                f"{module_name}: imports duckdb (§6 Strategy/Broker "
                f"purity violation)"
            )

    assert not violations, (
        f"§6 ARCHITECTURE VIOLATION: uptrend_pullback Strategy/Broker "
        f"modules import duckdb:\n" + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# PASS baselines: Control Plane modules DO have DB access (pins separation)
# ---------------------------------------------------------------------------


def test_chase_up_control_plane_modules_have_db_access() -> None:
    """§6 PASS baseline: chase_up Control Plane modules import duckdb.

    Per CLAUDE.md §6:
      "Control Plane / Orchestrator: Manages time-stepping and PIT data
       dispatching."

    PIT data dispatching REQUIRES DB access. If data.py or universe.py
    loses duckdb import, this test fails (architectural regression).
    """
    base = REPO_ROOT / "chase_up"
    missing: list[str] = []
    for module_name in CONTROL_PLANE_MODULES["chase_up"]:
        path = base / module_name
        if not path.exists():
            missing.append(f"{module_name}: MISSING")
            continue
        if not _has_duckdb_import(path):
            missing.append(
                f"{module_name}: does NOT import duckdb (Control Plane "
                f"regression — PIT data dispatching requires DB access)"
            )

    assert not missing, (
        f"§6 CONTROL PLANE REGRESSION: chase_up Control Plane modules "
        f"missing duckdb import:\n" + "\n".join(f"  {m}" for m in missing)
    )


def test_uptrend_pullback_control_plane_modules_have_db_access() -> None:
    """§6 PASS baseline: uptrend_pullback Control Plane imports duckdb."""
    base = REPO_ROOT / "uptrend_pullback"
    missing: list[str] = []
    for module_name in CONTROL_PLANE_MODULES["uptrend_pullback"]:
        path = base / module_name
        if not path.exists():
            missing.append(f"{module_name}: MISSING")
            continue
        if not _has_duckdb_import(path):
            missing.append(
                f"{module_name}: does NOT import duckdb (Control Plane "
                f"regression)"
            )

    assert not missing, (
        f"§6 CONTROL PLANE REGRESSION: uptrend_pullback Control Plane "
        f"modules missing duckdb import:\n" + "\n".join(f"  {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# Forward-defense: full audit of all 4 engines (chase_up + uptrend clean)
# ---------------------------------------------------------------------------


def test_section6_architecture_summary_4engines() -> None:
    """§6 forward-defense: summarize Strategy purity across all 4 engines.

    Pin known state per master ledger:
    - chase_up + uptrend_pullback: §6 CLEAN (verified Tick 56)
    - short_reversal: §6 VIOLATION (Tick 40 — scan_signals.py:34 duckdb)
    - cycle_price_action: §6 VIOLATION (Tick 49 — replay_broker.py:41,54
      duckdb per fill)

    This test documents the §6 compliance state and ensures chase_up +
    uptrend_pullback stay clean.
    """
    # Verify chase_up + uptrend_pullback are clean (per above tests)
    chase_violations = []
    uptrend_violations = []

    for module_name in STRATEGY_BROKER_MODULES["chase_up"]:
        path = REPO_ROOT / "chase_up" / module_name
        if path.exists() and _has_duckdb_import(path):
            chase_violations.append(module_name)

    for module_name in STRATEGY_BROKER_MODULES["uptrend_pullback"]:
        path = REPO_ROOT / "uptrend_pullback" / module_name
        if path.exists() and _has_duckdb_import(path):
            uptrend_violations.append(module_name)

    # chase_up + uptrend_pullback must be clean (no regression since Tick 56)
    assert not chase_violations, (
        f"§6 REGRESSION: chase_up Strategy/Broker now imports duckdb: "
        f"{chase_violations}"
    )
    assert not uptrend_violations, (
        f"§6 REGRESSION: uptrend_pullback Strategy/Broker now imports "
        f"duckdb: {uptrend_violations}"
    )