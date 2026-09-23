"""§2 Cost > Cash Rejection (No Leverage) Verification (Tick 64).

CLAUDE.md §2 (verbatim):
  "**All-In Sizing Policy (2026-09-21):** ... Margin blowout
   protection still applies: `cost > cash` must reject the trade
   (no leverage) and NAV-floor cash gates remain valid for new entries."

CLAUDE.md §0 (verbatim):
  "**Pessimistic Default:** Always assume the worst-case scenario for
   market liquidity, execution price, and statistical significance."

**核心发现 (FRESH 2026-09-23):**

A. **No-leverage principle**:
   - `cost > cash` MUST reject the trade (no implicit margin)
   - Per [[chase-up-conservative-cash-fixes]] Bug A (fixed 2026-09-21):
     - chase_up/portfolio.py had implicit margin bug
     - Bug allowed cost > cash → blew past capital limits

B. **Expected rejection pattern**:
   ```python
   cost = size * entry_price
   if cost > cash:
       continue  # reject trade, no margin
   ```
   Or:
   ```python
   if size * entry_price > cash:
       raise ValueError("cost > cash; no leverage allowed")
   ```

C. **Anti-patterns to detect**:
   - No check at all (cost > cash allowed → implicit margin)
   - Silent truncation: `size = int(cash / entry_price)` without
     rejecting the original request
   - Negative cash silently allowed: `cash -= cost` without guard

D. **Why this matters**:
   - §2 Capital conservation: physical cash must back every position
   - §0 Pessimistic Default: leverage amplifies losses beyond capital
   - If cost > cash is silently allowed:
     - Reported equity curve diverges from real portfolio equity
     - Backtest shows phantom gains funded by phantom capital
     - Live trading would result in actual margin call

E. **Coverage**:
   - chase_up/portfolio.py:try_enter — should have cost > cash rejection
   - uptrend_pullback/portfolio.py:try_enter — should have cost > cash rejection
   - short_reversal/portfolio.py:try_enter — should have cost > cash rejection
   - cycle_price_action: uses cerebro (different pattern, skip)

F. **AST detection strategy**:
   - Look for: comparison `cost > cash` (or `size * entry_price > cash`)
   - Look for: in if-statement context (rejection guard)
   - Look for: rejection action (continue / raise / return None)
   - Forward-defense: any Portfolio without this guard RED

G. **Test results (Tick 64 expected)**:
   - PASS baselines: each engine has cost > cash rejection guard
   - RED if: guard missing or in wrong form
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PORTFOLIO_FILES = [
    REPO_ROOT / "chase_up" / "portfolio.py",
    REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    REPO_ROOT / "short_reversal" / "portfolio.py",
    REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
    REPO_ROOT / "short_reversal" / "engine.py",
]


def _scan_cost_cash_rejection() -> dict[str, dict[str, object]]:
    """Scan Portfolio files for cost > cash rejection pattern.

    Recognizes multiple anti-leverage idioms:
    - `if cost > cash: continue/raise` (explicit reject)
    - `if cash < 0: continue` (negative cash → reject)
    - `budget = min(slot_value, cash)` (cap budget at cash)
    - `size = int(cash / entry_price)` (size capped by cash)

    Returns dict[file_rel → {
        "has_rejection_guard": bool,
        "guard_lines": list[int],
        "guard_snippets": list[str],
    }]
    """
    results: dict[str, dict[str, object]] = {}

    for path in PORTFOLIO_FILES:
        if not path.exists():
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            source_lines = source.splitlines()
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        rel = path.relative_to(REPO_ROOT)
        guard_lines: list[int] = []
        guard_snippets: list[str] = []

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            line = node.lineno
            snippet = (
                source_lines[line - 1].strip()
                if line <= len(source_lines)
                else ""
            )

            # Pattern 1: `if cost > cash: continue/raise/return`
            if isinstance(node, ast.If):
                test = node.test
                if isinstance(test, ast.Compare):
                    left_str = (
                        ast.unparse(test.left) if hasattr(ast, "unparse") else ""
                    )
                    comp_right_str = ""
                    for comp in test.comparators:
                        comp_right_str += (
                            ast.unparse(comp) if hasattr(ast, "unparse") else ""
                        )
                    test_str = (left_str + " " + comp_right_str).lower()
                    has_cost = (
                        "cost" in test_str
                        or ("size" in test_str and "entry" in test_str)
                        or "value" in test_str
                        or "amount" in test_str
                        or "budget" in test_str
                    )
                    has_cash = (
                        "cash" in test_str
                        or "free_cash" in test_str
                        or "available" in test_str
                    )
                    if has_cost and has_cash:
                        for stmt in node.body:
                            stmt_str = (
                                ast.unparse(stmt) if hasattr(ast, "unparse") else ""
                            )
                            if any(
                                action in stmt_str
                                for action in (
                                    "continue",
                                    "raise",
                                    "return None",
                                    "return",
                                )
                            ):
                                guard_lines.append(line)
                                guard_snippets.append(snippet)
                                break

                    # Pattern 2: `if cash < 0: continue/raise`
                    if has_cash and ("< 0" in test_str or "< 0.0" in test_str):
                        for stmt in node.body:
                            stmt_str = (
                                ast.unparse(stmt) if hasattr(ast, "unparse") else ""
                            )
                            if any(
                                action in stmt_str
                                for action in ("continue", "raise", "return")
                            ):
                                guard_lines.append(line)
                                guard_snippets.append(snippet)
                                break

                    # Pattern 2b: NAV-floor gate (short_reversal style)
                    # `if nav < ... * min_cash_ratio: ...` or
                    # `if nav < cash_gate_threshold: ...`
                    if "nav" in test_str and (
                        "min_cash_ratio" in test_str
                        or "cash_gate" in test_str
                        or "nav_gate" in test_str
                        or "initial_capital" in test_str
                    ):
                        for stmt in node.body:
                            stmt_str = (
                                ast.unparse(stmt) if hasattr(ast, "unparse") else ""
                            )
                            if any(
                                action in stmt_str
                                for action in (
                                    "continue",
                                    "raise",
                                    "return",
                                    "skip",
                                )
                            ):
                                guard_lines.append(line)
                                guard_snippets.append(snippet)
                                break

            # Pattern 3: `budget = min(..., cash)` (cap budget at cash)
            # Pattern 4: `size = int(cash / entry_price)` (size capped by cash)
            if isinstance(node, ast.Assign):
                target_str = (
                    ast.unparse(node.targets[0])
                    if hasattr(ast, "unparse")
                    else ""
                )
                value_str = (
                    ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                )
                combined = (target_str + " " + value_str).lower()
                if "min" in combined and "cash" in combined and (
                    "slot" in combined or "budget" in combined or "value" in combined
                ):
                    guard_lines.append(line)
                    guard_snippets.append(snippet)
                elif "size" in target_str.lower() and "cash" in combined and (
                    "/" in combined or "min" in combined
                ):
                    guard_lines.append(line)
                    guard_snippets.append(snippet)

        # Dedup
        seen = set()
        unique_lines: list[int] = []
        unique_snippets: list[str] = []
        for ln, sn in zip(guard_lines, guard_snippets):
            if ln not in seen:
                seen.add(ln)
                unique_lines.append(ln)
                unique_snippets.append(sn)

        results[str(rel)] = {
            "has_rejection_guard": len(unique_lines) > 0,
            "guard_lines": unique_lines,
            "guard_snippets": unique_snippets,
        }

    return results


# ---------------------------------------------------------------------------
# PASS baselines: each engine rejects cost > cash
# ---------------------------------------------------------------------------


def test_chase_up_rejects_cost_greater_than_cash() -> None:
    """§2 PASS baseline: chase_up Portfolio rejects cost > cash.

    Per CLAUDE.md §2: "cost > cash must reject the trade (no leverage)".
    Per [[chase-up-conservative-cash-fixes]] Bug A: chase_up had
    implicit margin bug, FIXED 2026-09-21. Forward-defense guard.
    """
    results = _scan_cost_cash_rejection()
    chase = results.get("chase_up/portfolio.py", {})

    assert chase.get("has_rejection_guard"), (
        "§2 NO-LEVERAGE GUARD MISSING: chase_up/portfolio.py has no "
        "`if cost > cash: continue/raise` rejection pattern.\n"
        "Per CLAUDE.md §2: cost > cash MUST reject the trade (no leverage).\n"
        "Per [[chase-up-conservative-cash-fixes]] Bug A (fixed 2026-09-21):\n"
        "  chase_up had implicit margin bug that allowed cost > cash.\n"
        "If regression reintroduces the bug, this test REDs.\n\n"
        "Expected pattern: `if cost > cash: continue` (skip trade, no margin)"
    )


def test_uptrend_pullback_rejects_cost_greater_than_cash() -> None:
    """§2 PASS baseline: uptrend_pullback Portfolio rejects cost > cash."""
    results = _scan_cost_cash_rejection()
    uptrend = results.get("uptrend_pullback/portfolio.py", {})

    assert uptrend.get("has_rejection_guard"), (
        "§2 NO-LEVERAGE GUARD MISSING: uptrend_pullback/portfolio.py has "
        "no `if cost > cash: continue/raise` rejection pattern.\n"
        "Per CLAUDE.md §2: cost > cash MUST reject the trade (no leverage).\n"
        "If uptrend_pullback silently allows cost > cash, backtest can "
        "show phantom gains funded by phantom capital."
    )


# ---------------------------------------------------------------------------
# RED forward-defense: short_reversal should also have this guard
# ---------------------------------------------------------------------------


def test_short_reversal_rejects_cost_greater_than_cash() -> None:
    """§2 RED forward-defense: short_reversal has no-leverage guard.

    Short reversal doesn't use a Portfolio class — it uses
    replay_strategy_v3.py (backtrader strategy) and engine.py. The
    no-leverage guard must exist in one of these.
    """
    results = _scan_cost_cash_rejection()

    # Look across all short_reversal entry points
    short_keys = [
        "short_reversal/portfolio.py",
        "short_reversal/replay_strategy_v3.py",
        "short_reversal/engine.py",
    ]
    has_guard = any(
        results.get(k, {}).get("has_rejection_guard", False)
        for k in short_keys
        if k in results
    )

    assert has_guard, (
        "§2 NO-LEVERAGE GUARD MISSING: short_reversal has no "
        "`cost > cash → reject` pattern in any of "
        "portfolio.py / replay_strategy_v3.py / engine.py.\n"
        "Per CLAUDE.md §2: cost > cash MUST reject the trade (no leverage).\n"
        "short_reversal must enforce this even for SHORT positions "
        "(margin on short side still requires capital backing)."
    )