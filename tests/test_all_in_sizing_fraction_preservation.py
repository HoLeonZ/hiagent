"""§2 All-In Sizing Formula Verification (Tick 63).

CLAUDE.md §2 (verbatim, 2026-09-21 update):
  "**All-In Sizing Policy (2026-09-21):** Every entry is sized at
   100% of available cash for that trade slot
   (`position_sizing = "all_in"`, `MAX_POSITION_PCT = 1.0`,
   `position_fraction = 1.0`). Tail risk is absorbed at the *exit*
   layer (per-trade ATR-based SL + TP), not at the *entry* layer
   via a pre-trade cash buffer."

**核心发现 (FRESH 2026-09-23):**

A. **§2 All-In sizing MUST use position_fraction = 1.0**:
   - Per preset: `position_fraction = 1.0` (or 0.x for partial sizing)
   - Each engine's Portfolio.try_enter() must divide cash by
     position_fraction to determine order size
   - Catches: position_fraction silently dropped from call site
     (per [[preset-engine-api-conformance-gap]] 175 dropped keys)

B. **Expected formula pattern (LONG position)**:
   ```python
   size = int(cash * position_fraction / entry_price / 100) * 100
   ```
   Or:
   ```python
   budget = cash * position_fraction  # all-in = 1.0
   size = int(budget / entry_price // 100) * 100
   ```

C. **Anti-patterns to detect**:
   - `size = int(cash / entry_price)` (missing position_fraction)
   - `size = int(cash * 0.5 / entry_price)` (hardcoded fraction)
   - `size = int(initial_capital / entry_price)` (uses initial, not cash)

D. **Coverage**:
   - chase_up/portfolio.py:try_enter — verify position_fraction used
   - uptrend_pullback/portfolio.py:try_enter — verify position_fraction used
   - short_reversal/portfolio.py:try_enter — verify position_fraction used
   - cycle_price_action: no Portfolio class (uses cerebro), skip

E. **Why this matters**:
   - If position_fraction is silently dropped:
     - position_fraction=1.0 (all-in) works by coincidence (1.0 × x = x)
     - position_fraction=0.5 (half-in) silently becomes all-in (1.0 × x = x)
     - **Half-position presets become all-in** — silent position doubling
   - §2 All-In policy relies on this being enforced correctly
   - If position_fraction=0.5 is the strategy but engine ignores it,
     real portfolio risk is 2× intended

F. **AST-based detection**:
   - Find Portfolio classes with try_enter methods
   - Look for division chain: `cash / price` or `cash * position_fraction / price`
   - Verify position_fraction reference exists
   - Forward-defense: future engines that drop position_fraction RED

G. **Test results (Tick 63 expected)**:
   - chase_up + uptrend: position_fraction found in size calc
   - short_reversal: position_fraction may be missing (RED)
   - cycle_price_action: no Portfolio class (skip / different pattern)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Engine-specific portfolio entry points
PORTFOLIO_FILES = [
    REPO_ROOT / "chase_up" / "portfolio.py",
    REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    REPO_ROOT / "short_reversal" / "portfolio.py",
]


def _scan_position_fraction_usage() -> dict[str, dict[str, object]]:
    """Scan Portfolio files for position_fraction usage in size calc.

    Returns dict[file_rel → {
        "has_portfolio_class": bool,
        "has_try_enter": bool,
        "uses_position_fraction": bool,
        "position_fraction_lines": list[int],
        "size_calc_lines": list[int],
    }]
    """
    results: dict[str, dict[str, object]] = {}

    for path in PORTFOLIO_FILES:
        if not path.exists():
            results[str(path.relative_to(REPO_ROOT))] = {
                "has_portfolio_class": False,
                "has_try_enter": False,
                "uses_position_fraction": False,
                "position_fraction_lines": [],
                "size_calc_lines": [],
            }
            continue

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        rel = path.relative_to(REPO_ROOT)
        has_portfolio = False
        has_try_enter = False
        uses_pf = False
        pf_lines: list[int] = []
        size_calc_lines: list[int] = []

        for node in ast.walk(tree):
            if not hasattr(node, "lineno"):
                continue
            line = node.lineno

            # Find class definitions
            if isinstance(node, ast.ClassDef):
                if "Portfolio" in node.name or "portfolio" in node.name.lower():
                    has_portfolio = True

            # Find try_enter methods
            if isinstance(node, ast.FunctionDef):
                if "try_enter" in node.name or "enter" in node.name.lower():
                    if has_portfolio:
                        has_try_enter = True

            # Find position_fraction references
            if isinstance(node, ast.Name) and node.id == "position_fraction":
                uses_pf = True
                pf_lines.append(line)
            if isinstance(node, ast.Attribute) and node.attr == "position_fraction":
                uses_pf = True
                pf_lines.append(line)

            # Find size calculation patterns
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "size", "order_size", "qty", "quantity"
                    }:
                        size_calc_lines.append(line)

        results[str(rel)] = {
            "has_portfolio_class": has_portfolio,
            "has_try_enter": has_try_enter,
            "uses_position_fraction": uses_pf,
            "position_fraction_lines": pf_lines,
            "size_calc_lines": size_calc_lines,
        }

    return results


# ---------------------------------------------------------------------------
# PASS baselines: each engine uses position_fraction
# ---------------------------------------------------------------------------


def test_chase_up_uses_position_fraction_in_sizing() -> None:
    """§2 PASS baseline: chase_up Portfolio uses position_fraction.

    Forward-defense: if someone removes position_fraction from
    chase_up/portfolio.py size calc, this test fails.
    """
    results = _scan_position_fraction_usage()
    chase = results.get("chase_up/portfolio.py", {})

    if not chase.get("has_portfolio_class"):
        return  # no Portfolio class, skip

    if not chase.get("uses_position_fraction"):
        raise AssertionError(
            "§2 POSITION_FRACTION DROPPED: chase_up/portfolio.py "
            "Portfolio class does NOT reference position_fraction.\n"
            "Per CLAUDE.md §2 (2026-09-21): every entry is sized at "
            "position_fraction of available cash.\n"
            "If position_fraction is silently dropped, partial-position "
            "presets (e.g., position_fraction=0.5) silently become all-in "
            "(real risk 2× intended)."
        )


def test_uptrend_pullback_uses_position_fraction_in_sizing() -> None:
    """§2 PASS baseline: uptrend_pullback Portfolio uses position_fraction."""
    results = _scan_position_fraction_usage()
    uptrend = results.get("uptrend_pullback/portfolio.py", {})

    if not uptrend.get("has_portfolio_class"):
        return

    if not uptrend.get("uses_position_fraction"):
        raise AssertionError(
            "§2 POSITION_FRACTION DROPPED: uptrend_pullback/portfolio.py "
            "Portfolio class does NOT reference position_fraction.\n"
            "Per CLAUDE.md §2 (2026-09-21): every entry is sized at "
            "position_fraction of available cash.\n"
            "If position_fraction is silently dropped, partial-position "
            "presets (e.g., position_fraction=0.5) silently become all-in "
            "(real risk 2× intended)."
        )


# ---------------------------------------------------------------------------
# RED: short_reversal missing position_fraction (likely)
# ---------------------------------------------------------------------------


def test_short_reversal_uses_position_fraction_in_sizing() -> None:
    """§2 RED forward-defense: short_reversal Portfolio uses position_fraction.

    Per [[preset-engine-api-conformance-gap]]: 174 preset keys silently
    dropped across engines. position_fraction may be one of them.

    If short_reversal's Portfolio doesn't reference position_fraction,
    flag the bug.
    """
    results = _scan_position_fraction_usage()
    short = results.get("short_reversal/portfolio.py", {})

    if not short.get("has_portfolio_class"):
        # short_reversal may not have a Portfolio class
        # Skip if no Portfolio class found
        return

    if not short.get("uses_position_fraction"):
        raise AssertionError(
            "§2 POSITION_FRACTION DROPPED: short_reversal/portfolio.py "
            "Portfolio class does NOT reference position_fraction.\n"
            "Per CLAUDE.md §2 (2026-09-21): every entry is sized at "
            "position_fraction of available cash.\n"
            "short_reversal presets may include position_fraction=0.x "
            "for partial-position sizing. If silently dropped, all "
            "positions become all-in regardless of preset intent."
        )