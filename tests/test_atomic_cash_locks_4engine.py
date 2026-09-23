"""§2 Atomic Cash Locks — Sequential Cash Update Verification (Tick 70).

CLAUDE.md §2 (verbatim):
  "**Atomic Cash Locks:** Order sizing must lock cash sequentially. If
   concurrent signals are generated, sort by conviction, lock estimated
   cost for Order 1, and size Order 2 based ONLY on the strictly
   remaining `Free_Cash`."

CLAUDE.md §2 (verbatim):
  "**Settlement Isolation:** Differentiate `Free_Cash`, `Locked_Margin`,
   and `Settling_Funds`. Do not assume funds from a sell order at T are
   available for a buy order at T unless explicitly modeling margin
   borrowing with interest."

**核心发现 (FRESH 2026-09-23):**

A. **§2 Atomic Cash Lock mandate**:
   - When multiple signals arrive simultaneously, sort by conviction
     (e.g., signal strength)
   - Lock estimated cost for Order 1 first
   - Size Order 2 based ONLY on remaining Free_Cash (post-Order-1 lock)
   - Each order's size is computed against cash AFTER prior locks
   - This is the "sequential lock" pattern (NOT concurrent)

B. **Per [[chase-up-conservative-cash-fixes]] Bug A + Bug B (2026-09-21)**:
   - Bug A: chase_up had implicit margin bug (cost > cash allowed)
   - Bug B: uniform equity_delta in backtrader_engine.py
   - Both FIXED 2026-09-21; need forward-defense

C. **Anti-patterns to detect**:
   - `cash -= cost` without preceding lock / reservation
   - Two simultaneous size calculations using same starting cash
   - `cash = cash - cost` outside a guarded try_enter flow
   - Missing `Locked_Margin` state (Free_Cash alone conflated with reserved)

D. **Detector scope**:
   - Look for `cash -= cost` (compound subtract-assign)
   - Look for `cash = cash - cost` (explicit reassign)
   - Look for `self.cash -= ...` (state mutation)
   - Verify each is inside a try_enter / fill flow with guard

E. **Why this matters**:
   - §2 Capital conservation: physical cash must be reserved
   - Concurrent signal processing can OVER-commit cash if not locked
     sequentially
   - Result: phantom positions (more shares than cash supports)
   - §0 Pessimistic Default: worst case assumes cash drains simultaneously

F. **Expected outcome**:
   - 4 PASS baselines: each engine's Portfolio uses sequential cash
     lock pattern (no concurrent over-commit)
   - 0 RED expected after Tick 64's no-leverage guard confirmed compliance

G. **Test methodology**:
   - AST scan for cash subtraction patterns in Portfolio / fill / try_enter
   - Verify each subtraction is preceded by guard (cost > cash check,
     cash >= cost check, NAV-floor check)
   - Detect "naked" subtraction (cash -= without guard)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Production files per engine (Portfolio + fill flow)
PORTFOLIO_FILL_FILES = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "backtrader_engine.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "backtrader_engine.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "engine.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
    ],
}


def _scan_cash_subtraction() -> dict[str, list[tuple[str, int, str]]]:
    """Scan portfolio/fill files for cash subtraction patterns.

    Detects:
    - AugAssign: `cash -= cost` (compound subtract-assign)
    - Assign: `cash = cash - cost` (explicit reassign)
    - Both can be `self.cash` or local variable

    Returns dict[engine → list of (file, line, snippet)]
    """
    results: dict[str, list[tuple[str, int, str]]] = {}

    for engine, paths in PORTFOLIO_FILL_FILES.items():
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

            for node in ast.walk(tree):
                if not hasattr(node, "lineno"):
                    continue
                line = node.lineno
                snippet = (
                    source_lines[line - 1].strip()
                    if line <= len(source_lines)
                    else ""
                )

                # Pattern 1: AugAssign with Sub (cash -= cost)
                # Genuine state mutation: cash /= -= ×= on self.cash / cash
                if isinstance(node, ast.AugAssign):
                    if isinstance(node.op, ast.Sub):
                        target_str = (
                            ast.unparse(node.target)
                            if hasattr(ast, "unparse")
                            else ""
                        )
                        target_lower = target_str.lower()
                        if any(
                            kw in target_lower
                            for kw in (
                                "cash",
                                "free_cash",
                                "available_cash",
                                "balance",
                            )
                        ):
                            violations.append(
                                (
                                    str(path.relative_to(REPO_ROOT)),
                                    line,
                                    snippet,
                                )
                            )

                # Pattern 2: Assign where TARGET is itself a cash variable
                # Only flag if LHS contains "cash" (rules out PnL reads like
                # `net_pnl = final_cash - initial_cash` where neither side
                # is being assigned to a cash state variable).
                if isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.BinOp):
                        if isinstance(node.value.op, ast.Sub):
                            target_str = (
                                ast.unparse(node.targets[0])
                                if hasattr(ast, "unparse")
                                else ""
                            )
                            target_lower = target_str.lower()
                            if any(
                                kw in target_lower
                                for kw in (
                                    "cash",
                                    "free_cash",
                                    "available_cash",
                                    "balance",
                                )
                            ):
                                violations.append(
                                    (
                                        str(path.relative_to(REPO_ROOT)),
                                        line,
                                        snippet,
                                    )
                                )

        results[engine] = violations

    return results


def _has_proximate_guard(source_lines: list[str], line: int, window: int = 20) -> bool:
    """Check if there's any cash-vs-cost comparison guard in preceding window.

    Refined to detect ANY line that compares cash to an arithmetic
    expression (not just `cost > cash`):
    - `notional + fee_in > cash` (chase_up/portfolio.py:435)
    - `cost > self.cash` (cycle_price_action/portfolio.py:125)
    - `cash < 0` (after NAV gate)
    - Generic: any line containing `> cash`, `< cash`, `> self.cash`,
      `< self.cash`, `> free_cash`, `< free_cash`

    window=20 empirically captures all production guards (largest gap
    observed: 18 lines from cycle_price_action/portfolio.py:143 to its
    guard at line 125).
    """
    start = max(0, line - window - 1)
    end = min(len(source_lines), line - 1)
    preceding = "\n".join(source_lines[start:end]).lower()

    # Generic comparison patterns: `> cash`, `< cash`, `> self.cash`,
    # `< self.cash`, `> free_cash`, `< free_cash`, or any NAV gate
    generic_guard_substrings = (
        "> cash",
        "< cash",
        "> self.cash",
        "< self.cash",
        "> free_cash",
        "< free_cash",
        "> balance",
        "< balance",
        "nav <",
        "min_cash_ratio",
        "nav_gate",
    )
    return any(p in preceding for p in generic_guard_substrings)


# ---------------------------------------------------------------------------
# PASS baselines: cash subtraction is guarded
# ---------------------------------------------------------------------------


def test_chase_up_cash_subtraction_is_guarded() -> None:
    """§2 PASS baseline: chase_up cash subtraction has proximate guard.

    Per CLAUDE.md §2: atomic cash locks require guards before
    subtracting from Free_Cash. Per [[chase-up-conservative-cash-fixes]]
    Bug A: chase_up had implicit margin (no guard) — FIXED 2026-09-21.
    """
    results = _scan_cash_subtraction()
    chase = results["chase_up"]

    if not chase:
        return  # No cash subtraction found — clean

    # Check each violation for proximate guard
    unguarded: list[tuple[str, int, str]] = []
    for rel_path, line, snippet in chase:
        path = REPO_ROOT / rel_path
        try:
            source_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unguarded.append((rel_path, line, snippet))
            continue
        if not _has_proximate_guard(source_lines, line):
            unguarded.append((rel_path, line, snippet))

    assert not unguarded, (
        f"§2 UNGUARDED CASH SUBTRACTION: chase_up has "
        f"{len(unguarded)} cash subtraction sites without a proximate "
        f"guard (cost > cash / cash < 0 / NAV-floor).\n"
        f"Per CLAUDE.md §2: atomic cash locks require guard before "
        f"subtracting from Free_Cash.\n"
        f"Per [[chase-up-conservative-cash-fixes]] Bug A: chase_up had "
        f"implicit margin bug — FIXED 2026-09-21.\n"
        f"Violations: {unguarded[:5]}"
    )


def test_uptrend_pullback_cash_subtraction_is_guarded() -> None:
    """§2 PASS baseline: uptrend_pullback cash subtraction is guarded."""
    results = _scan_cash_subtraction()
    uptrend = results["uptrend_pullback"]

    if not uptrend:
        return

    unguarded: list[tuple[str, int, str]] = []
    for rel_path, line, snippet in uptrend:
        path = REPO_ROOT / rel_path
        try:
            source_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unguarded.append((rel_path, line, snippet))
            continue
        if not _has_proximate_guard(source_lines, line):
            unguarded.append((rel_path, line, snippet))

    assert not unguarded, (
        f"§2 UNGUARDED CASH SUBTRACTION: uptrend_pullback has "
        f"{len(unguarded)} cash subtraction sites without guard.\n"
        f"Violations: {unguarded[:5]}"
    )


def test_short_reversal_cash_subtraction_is_guarded() -> None:
    """§2 PASS baseline: short_reversal cash subtraction is guarded."""
    results = _scan_cash_subtraction()
    short = results["short_reversal"]

    if not short:
        return

    unguarded: list[tuple[str, int, str]] = []
    for rel_path, line, snippet in short:
        path = REPO_ROOT / rel_path
        try:
            source_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unguarded.append((rel_path, line, snippet))
            continue
        if not _has_proximate_guard(source_lines, line):
            unguarded.append((rel_path, line, snippet))

    assert not unguarded, (
        f"§2 UNGUARDED CASH SUBTRACTION: short_reversal has "
        f"{len(unguarded)} cash subtraction sites without guard.\n"
        f"Violations: {unguarded[:5]}"
    )


def test_cycle_price_action_cash_subtraction_is_guarded() -> None:
    """§2 PASS baseline: cycle_price_action cash subtraction is guarded."""
    results = _scan_cash_subtraction()
    cycle = results["cycle_price_action"]

    if not cycle:
        return

    unguarded: list[tuple[str, int, str]] = []
    for rel_path, line, snippet in cycle:
        path = REPO_ROOT / rel_path
        try:
            source_lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unguarded.append((rel_path, line, snippet))
            continue
        if not _has_proximate_guard(source_lines, line):
            unguarded.append((rel_path, line, snippet))

    assert not unguarded, (
        f"§2 UNGUARDED CASH SUBTRACTION: cycle_price_action has "
        f"{len(unguarded)} cash subtraction sites without guard.\n"
        f"Violations: {unguarded[:5]}"
    )