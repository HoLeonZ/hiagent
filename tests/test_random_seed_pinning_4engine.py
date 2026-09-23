"""§1 Random Seed Pinning — Determinism Verification (Tick 72).

CLAUDE.md §1 (verbatim):
  "**Temporal Determinism (Lookahead Bias Prevention)** — Time is a
   strictly monotonic, first-class citizen."

CLAUDE.md §0 (verbatim):
  "**Immutable State:** Treat all historical data and portfolio states
   as append-only."

**核心发现 (FRESH 2026-09-23):**

A. **Random seed pinning rationale**:
   - Per §1 Temporal Determinism: backtest results must be REPRODUCIBLE
   - Any `np.random.*` or `random.*` call without a preceding seed
     produces different output each run → backtest non-reproducible
   - Per [[reproducibility-audit-2026-09-23]] Tick 36: 3 engines lack
     sha256 baselines (only chase_up has v5+v8-v19). Random seed
     pinning is the OTHER pillar of reproducibility.

B. **Why this matters**:
   - Two runs of same backtest with same data should produce IDENTICAL
     results (modulo float precision). Without seed pinning, ANY
     randomness in Strategy / Broker / Portfolio breaks this.
   - §0 Pessimistic Default: we must know the exact output of a
     given input; randomness violates this
   - §1 Lookahead Bias Prevention: if `np.random.choice` is used
     for signal sampling without seed, audit trail broken

C. **Detection scope**:
   - Find `np.random.X(...)` or `random.X(...)` calls in production
     hot paths (Strategy / Broker / Portfolio / backtest)
   - Verify there's a preceding `np.random.seed(N)` or `random.seed(N)`
     call in same FunctionDef, OR seed is set at module load time
   - Flag: bare `np.random.choice` / `np.random.randint` / etc. without
     preceding seed

D. **Expected outcome**:
   - 4 PASS baselines: each engine's random calls are pinned
   - 0 RED expected (most production code is deterministic; the test
     verifies there are NO random calls at all, OR they are seeded)
   - This is forward-defense: future code that adds randomness without
     seeding will RED

E. **Detector strategy**:
   - AST scan for `np.random.X(...)` calls (Attribute.attr is in
     {'choice', 'randint', 'random', 'normal', 'uniform', 'shuffle',
      'permutation', 'sample', 'rand', 'randn'})
   - Track seed calls (np.random.seed, random.seed) at module scope
   - Flag np.random.X without seed context
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production hot-path files per engine
PRODUCTION_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
        REPO_ROOT / "chase_up" / "main.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
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


# Random function leaves that REQUIRE seed pinning
RANDOM_FUNCTIONS = (
    "choice",
    "randint",
    "random",
    "normal",
    "uniform",
    "shuffle",
    "permutation",
    "sample",
    "rand",
    "randn",
    "beta",
    "binomial",
    "chisquare",
    "exponential",
    "f",
    "gamma",
    "geometric",
    "gumbel",
    "laplace",
    "logistic",
    "lognormal",
    "multinomial",
    "multivariate_normal",
    "negative_binomial",
    "noncentral_chisquare",
    "noncentral_f",
    "pareto",
    "poisson",
    "power",
    "rayleigh",
    "standard_cauchy",
    "standard_exponential",
    "standard_gamma",
    "standard_normal",
    "standard_t",
    "triangular",
    "vonmises",
    "wald",
    "weibull",
    "zipf",
)


def _is_np_random_leaf(call: ast.Call) -> bool:
    """Check if Call is np.random.X(...) where X is a random function."""
    func = call.func
    if isinstance(func, ast.Attribute):
        # Pattern: np.random.choice / np.random.randint / ...
        if func.attr in RANDOM_FUNCTIONS:
            # Verify receiver is np.random (Attribute chain: np → random)
            receiver = func.value
            if isinstance(receiver, ast.Attribute):
                if receiver.attr == "random":
                    if isinstance(receiver.value, ast.Name):
                        if receiver.value.id == "np":
                            return True
    return False


def _is_random_leaf(call: ast.Call) -> bool:
    """Check if Call is random.X(...) (stdlib random module)."""
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr in RANDOM_FUNCTIONS:
            receiver = func.value
            if isinstance(receiver, ast.Name):
                if receiver.id == "random":
                    return True
    return False


def _is_seed_call(call: ast.Call) -> bool:
    """Check if Call is np.random.seed(N) or random.seed(N)."""
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr == "seed":
            receiver = func.value
            if isinstance(receiver, ast.Attribute):
                if receiver.attr == "random":
                    if isinstance(receiver.value, ast.Name):
                        if receiver.value.id == "np":
                            return True
            if isinstance(receiver, ast.Name):
                if receiver.id == "random":
                    return True
    return False


def _scan_random_calls() -> dict[str, list[tuple[str, int, str]]]:
    """Scan production files for unseeded random calls.

    Returns dict[engine → list of (file, line, snippet)]
    """
    results: dict[str, list[tuple[str, int, str]]] = {}

    for engine, paths in PRODUCTION_FILES.items():
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

            # First pass: collect seed calls (module-level + nested)
            seed_lines: set[int] = set()
            random_call_lines: list[tuple[int, str]] = []

            for node in ast.walk(tree):
                if not hasattr(node, "lineno"):
                    continue
                if isinstance(node, ast.Call):
                    if _is_seed_call(node):
                        seed_lines.add(node.lineno)
                    elif _is_np_random_leaf(node) or _is_random_leaf(node):
                        snippet = (
                            source_lines[node.lineno - 1].strip()
                            if node.lineno <= len(source_lines)
                            else ""
                        )
                        random_call_lines.append((node.lineno, snippet))

            # Second pass: flag random calls without preceding seed
            # within 50 lines (generous window for module-level seeding)
            for call_line, snippet in random_call_lines:
                preceding_seed = any(
                    seed_line <= call_line
                    and call_line - seed_line <= 50
                    for seed_line in seed_lines
                )
                if not preceding_seed:
                    violations.append(
                        (
                            str(path.relative_to(REPO_ROOT)),
                            call_line,
                            snippet,
                        )
                    )

        results[engine] = violations

    return results


# ---------------------------------------------------------------------------
# PASS baselines: random calls are seeded (or no random calls at all)
# ---------------------------------------------------------------------------


def test_chase_up_random_calls_are_seeded() -> None:
    """§1 PASS baseline: chase_up random calls have proximate seed.

    Per CLAUDE.md §1 + §0: random calls must be seed-pinned for
    reproducible backtests. Per [[reproducibility-audit-2026-09-23]]:
    sha256 baselines provide determinism EXCEPT when randomness is
    involved.
    """
    results = _scan_random_calls()
    chase = results["chase_up"]

    if chase:
        raise AssertionError(
            f"§1 UNSEEDED RANDOM: chase_up has "
            f"{len(chase)} np.random.* / random.* calls without a "
            f"proximate seed.\n"
            f"Per CLAUDE.md §1: backtest must be reproducible. Random "
            f"calls without seed pinning produce different output each "
            f"run, breaking sha256 baseline verification.\n"
            f"Violations: {chase[:5]}"
        )


def test_uptrend_pullback_random_calls_are_seeded() -> None:
    """§1 PASS baseline: uptrend_pullback random calls have proximate seed."""
    results = _scan_random_calls()
    uptrend = results["uptrend_pullback"]

    if uptrend:
        raise AssertionError(
            f"§1 UNSEEDED RANDOM: uptrend_pullback has "
            f"{len(uptrend)} unseeded random calls.\n"
            f"Violations: {uptrend[:5]}"
        )


def test_short_reversal_random_calls_are_seeded() -> None:
    """§1 PASS baseline: short_reversal random calls have proximate seed."""
    results = _scan_random_calls()
    short = results["short_reversal"]

    if short:
        raise AssertionError(
            f"§1 UNSEEDED RANDOM: short_reversal has "
            f"{len(short)} unseeded random calls.\n"
            f"Violations: {short[:5]}"
        )


def test_cycle_price_action_random_calls_are_seeded() -> None:
    """§1 PASS baseline: cycle_price_action random calls have proximate seed."""
    results = _scan_random_calls()
    cycle = results["cycle_price_action"]

    if cycle:
        raise AssertionError(
            f"§1 UNSEEDED RANDOM: cycle_price_action has "
            f"{len(cycle)} unseeded random calls.\n"
            f"Violations: {cycle[:5]}"
        )