"""§2 Settlement Isolation — Cash State Machine Verification (Tick 74).

CLAUDE.md §2 (verbatim):
  "**Settlement Isolation:** Differentiate `Free_Cash`, `Locked_Margin`,
   and `Settling_Funds`. Do not assume funds from a sell order at $T$
   are available for a buy order at $T$ unless explicitly modeling
   margin borrowing with interest."

**核心发现 (FRESH 2026-09-23):**

A. **Background per existing audits**:
   - [[settlement-isolation-4-engine]] (2026-09-22): 4 engines普适违规 —
     all Portfolio classes have single `self.cash` field; no
     `Free_Cash` / `Locked_Margin` / `Settling_Funds` state machine
   - max_positions=1 implicitly blocks the issue (only one trade at a
     time), but this is IMPLICIT, not EXPLICIT — per §2 Pessimistic
     Default, state machine must be explicit
   - Tick 74 is the FORMAL AUDIT — RED tests pin the violation

B. **Why this matters**:
   - Per CLAUDE.md §0 Pessimistic Default: assume worst case (T+1
     settlement blocks same-day re-entry)
   - Per CLAUDE.md §2: "Atomic Cash Locks" requires capital segregation
   - A-share market reality: T 日 sell → T+1 可用 (T+1 settlement);
     single `self.cash` confuses settled vs unsettled funds
   - Forward-defense: if max_positions ever goes > 1 (or short_reversal
     adds sell→buy→sell cycle), current single-pool design silently
     miscounted available capital

C. **Detection scope**:
   - AST scan Portfolio class __init__ for self.X = ... attributes
   - Look for any of: free_cash / locked_margin / settling_funds /
     available_cash / unsettled_cash / in_transit / locked_cash
   - If NONE found → single-pool violation (RED)
   - If 2+ distinct cash-related fields → potentially compliant (PASS)

D. **Expected outcome**:
   - 4 RED tests (one per engine) confirming §2 settlement isolation
     is NOT modeled
   - Tests document the violation pattern + remediation guidance
   - Forward-defense: any future Portfolio that has only self.cash REDs
   - Any future Portfolio that adds free_cash + locked_margin PASSes

E. **Detector strategy**:
   - AST walk to find Portfolio class (class name matches /Portfolio/i)
   - Find __init__ method
   - Collect all `self.X = Y` assignments where X matches cash pattern
   - Check for required separation: free_cash / available_cash vs
     locked_margin / settling_funds

F. **Why this is a §2 violation, not just cosmetic**:
   - Without state machine, code can't distinguish "cash I have now"
     vs "cash I'll have tomorrow"
   - T+1 settlement is PHYSICAL market law per [[claudemd-t1-settlement]]
   - Conflating these means strategy may think it has more capital
     than reality allows (over-confidence in position sizing)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Portfolio files per engine (the source-of-truth cash state container)
PORTFOLIO_FILES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
    "cycle_price_action": REPO_ROOT / "cycle_price_action" / "portfolio.py",
}


# Cash-related attribute names that satisfy §2 separation
# Compliant: at least 2 of these patterns present, distinguishing
# free/available vs locked/settling
CASH_SEPARATION_PATTERNS = {
    # Free/available pool (can use immediately for new entries)
    "free_cash",
    "available_cash",
    "unlocked_cash",
    # Locked/committed pool (already committed to open positions)
    "locked_margin",
    "locked_cash",
    "committed_cash",
    "position_margin",
    # Settling/in-transit pool (sold today, not yet usable per T+1)
    "settling_funds",
    "unsettled_funds",
    "settled_cash",
    "in_transit_cash",
    "t1_settlement",
}


# Single-pool violation patterns (when only self.cash / self.balance)
SINGLE_POOL_PATTERNS = {
    "cash",
    "balance",
    "available",
}


def _find_portfolio_class(tree: ast.Module) -> ast.ClassDef | None:
    """Find the Portfolio class (or any class with cash state)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Match by class name containing 'portfolio' or 'replay'
            name_lower = node.name.lower()
            if (
                "portfolio" in name_lower
                or "replay" in name_lower
                or "strategy" in name_lower
            ):
                return node
    return None


def _collect_self_attrs_in_init(
    class_node: ast.ClassDef,
) -> dict[str, int]:
    """Collect all `self.X = Y` assignments in __init__.

    Returns dict[attr_name → line_number].
    """
    attrs: dict[str, int] = {}
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            for stmt in ast.walk(item):
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Attribute)
                    and isinstance(stmt.targets[0].value, ast.Name)
                    and stmt.targets[0].value.id == "self"
                ):
                    attr_name = stmt.targets[0].attr
                    if hasattr(stmt, "lineno"):
                        attrs[attr_name] = stmt.lineno
    return attrs


def _audit_cash_state_machine(
    file_path: Path,
) -> tuple[bool, list[str], list[str]]:
    """Audit Portfolio class for §2 Settlement Isolation compliance.

    Returns (compliant, found_free_pool, found_locked_settling_pool).
    """
    if not file_path.exists():
        return (False, [], ["file not found"])

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return (False, [], ["parse error"])

    portfolio_class = _find_portfolio_class(tree)
    if portfolio_class is None:
        return (False, [], ["no Portfolio class found"])

    attrs = _collect_self_attrs_in_init(portfolio_class)

    # Match attribute names case-insensitively against patterns
    attrs_lower = {a.lower() for a in attrs}

    free_pool = sorted(
        a
        for a in CASH_SEPARATION_PATTERNS
        if a in attrs_lower and (
            "free" in a
            or "available" in a
            or "unlocked" in a
        )
    )
    locked_settling_pool = sorted(
        a
        for a in CASH_SEPARATION_PATTERNS
        if a in attrs_lower
        and (
            "locked" in a
            or "committed" in a
            or "settling" in a
            or "settled" in a
            or "unsettled" in a
            or "in_transit" in a
            or "t1" in a
        )
    )

    # Compliant = has free pool AND (locked OR settling) pool distinct
    has_separation = bool(free_pool) and bool(locked_settling_pool)

    return (has_separation, free_pool, locked_settling_pool)


def _engine_red_message(
    engine: str,
    free_pool: list[str],
    locked_settling_pool: list[str],
) -> str:
    return (
        f"§2 SETTLEMENT ISOLATION VIOLATION: {engine} Portfolio uses "
        f"single cash pool (self.cash), no state machine.\n"
        f"Per CLAUDE.md §2: must differentiate Free_Cash, Locked_Margin, "
        f"and Settling_Funds.\n"
        f"Found free pool attrs: {free_pool}\n"
        f"Found locked/settling attrs: {locked_settling_pool}\n"
        f"max_positions=1 currently masks this, but per §0 Pessimistic "
        f"Default + §2 Settlement Isolation, state machine must be "
        f"explicit.\n"
        f"A-share T+1 settlement is physical market law — conflating "
        f"settled vs unsettled funds overstates available capital."
    )


# ---------------------------------------------------------------------------
# RED baselines: 4 engines violate §2 Settlement Isolation
# ---------------------------------------------------------------------------


def test_chase_up_settlement_isolation() -> None:
    """§2 RED: chase_up Portfolio has only self.cash, no Free_Cash/Locked_Margin split.

    Per CLAUDE.md §2: must differentiate Free_Cash, Locked_Margin, and
    Settling_Funds. Per [[settlement-isolation-4-engine]] (2026-09-22):
    4 engines普适违规.
    """
    compliant, free_pool, locked_settling_pool = _audit_cash_state_machine(
        PORTFOLIO_FILES["chase_up"]
    )

    if not compliant:
        raise AssertionError(_engine_red_message("chase_up", free_pool, locked_settling_pool))


def test_uptrend_pullback_settlement_isolation() -> None:
    """§2 RED: uptrend_pullback Portfolio has only self.cash."""
    compliant, free_pool, locked_settling_pool = _audit_cash_state_machine(
        PORTFOLIO_FILES["uptrend_pullback"]
    )

    if not compliant:
        raise AssertionError(
            _engine_red_message("uptrend_pullback", free_pool, locked_settling_pool)
        )


def test_short_reversal_settlement_isolation() -> None:
    """§2 RED: short_reversal ReplayStrategy has only self.cash.

    Per line 241: explicit comment '仅 self.cash' confirms single-pool design.
    """
    compliant, free_pool, locked_settling_pool = _audit_cash_state_machine(
        PORTFOLIO_FILES["short_reversal"]
    )

    if not compliant:
        raise AssertionError(
            _engine_red_message("short_reversal", free_pool, locked_settling_pool)
        )


def test_cycle_price_action_settlement_isolation() -> None:
    """§2 RED: cycle_price_action Portfolio has only self.cash."""
    compliant, free_pool, locked_settling_pool = _audit_cash_state_machine(
        PORTFOLIO_FILES["cycle_price_action"]
    )

    if not compliant:
        raise AssertionError(
            _engine_red_message(
                "cycle_price_action", free_pool, locked_settling_pool
            )
        )
