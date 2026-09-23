"""§0/§3 Cost Model Canonical Conformance — Verification (Tick 76).

CLAUDE.md §0 (verbatim):
  "**Pessimistic Default:** Always assume the worst-case scenario for
   market liquidity, execution price, and statistical significance."

CLAUDE.md §3 (verbatim):
  "ALWAYS use **Forward-Adjusted Prices** (`adj_close`) for mathematical
   indicators (MACD, Wyckoff mappings, Volatility).
   ALWAYS use **Raw Prices** (`raw_close`) for evaluating limit order
   triggers, stop-losses, and portfolio physical cash mark-to-market."

CLAUDE.md §0/§3 cost model standard (documented in
[[audit-2026-09-23-cost-model-undercount]]):
  - Commission: 万2.5 = 0.00025 (canonical)
  - Stamp duty: 万5 = 0.0005 (POST-Aug2023, current)
                  万10 = 0.001 (PRE-Aug2023, historical)
  - Min commission: ¥5 floor
  - Stamp duty: SELL-ONLY

**核心发现 (FRESH 2026-09-23):**

A. **Cost model values across 4 engines (FRESH 2026-09-23)**:

   | Engine             | Commission  | Stamp Duty  | Status                  |
   |--------------------|-------------|-------------|-------------------------|
   | chase_up           | 0.00025 ✓   | 0.0005 ✓   | CANONICAL               |
   | uptrend_pullback   | 0.00025 ✓   | 0.0005 ✓   | CANONICAL               |
   | cycle_price_action | 0.00025 ✓   | 0.001 ✗    | WRONG (pre-Aug2023)     |
   | short_reversal     | 0.0006 ✗   | 0.001 ✗    | WRONG (both wrong)      |

B. **Per CLAUDE.md §0 Pessimistic Default + §3 Raw Prices mandate**:
   - Commission MUST be 0.00025 (canonical, no override)
   - Stamp duty should be 0.0005 for post-Aug2023 backtests
   - 0.001 stamp duty was PRE-Aug2023 rate (historical only)
   - 0.0006 commission is FACTUALLY WRONG (no historical basis)

C. **Why this matters**:
   - Commission/stamp errors silently under-report trading costs
   - Net PnL overstated → false confidence in strategy
   - Cross-engine comparison invalid (different cost models)
   - Per [[audit-2026-09-23-cost-model-undercount]]: short_reversal
     short_reversal 0.0006+0.001 stamps wrong; cycle 0.001 stamps wrong

D. **Detection scope**:
   - AST scan Portfolio / ReplayStrategy for cost model constants
   - Pattern: `commission_rate` / `COMMISSION_RATE` / `comm_rate`
   - Pattern: `stamp_duty_rate` / `STAMP_TAX` / `stamp_duty`
   - Verify commission == 0.00025 (canonical)
   - Verify stamp_duty ∈ {0.0005, 0.001} (both valid for date ranges)
   - If 0.001 stamp duty used → check for date guard
"""
from __future__ import annotations

import ast
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]


# Portfolio / strategy files per engine
COST_MODEL_FILES = {
    "chase_up": REPO_ROOT / "chase_up" / "portfolio.py",
    "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "portfolio.py",
    "short_reversal": REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
    "cycle_price_action": REPO_ROOT / "cycle_price_action" / "portfolio.py",
}


# Canonical commission: 万2.5 = 0.00025
CANONICAL_COMMISSION = 0.00025

# Valid stamp duty values
# - 0.0005 = 万5 (POST-Aug2023, current A-share market)
# - 0.001 = 万10 (PRE-Aug2023, historical)
VALID_STAMP_DUTY = {0.0005, 0.001}


def _extract_numeric_value(node: ast.AST) -> float | None:
    """Extract numeric value from AST node (Constant or UnaryOp)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _extract_numeric_value(node.operand)
        if inner is not None:
            return -inner
    return None


def _scan_cost_constants(
    file_path: Path,
) -> tuple[float | None, float | None, dict[str, int]]:
    """Scan Portfolio / Strategy class for cost model constants.

    Returns (commission_value, stamp_duty_value, line_map).

    Detects 3 patterns:
    - Pattern 1: dataclass field (ast.AnnAssign at class body)
    - Pattern 2: class constant (ast.Assign at class body)
    - Pattern 3: function default argument (ast.arguments.kw_defaults
      in __init__)
    """
    if not file_path.exists():
        return (None, None, {})

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError, UnicodeDecodeError):
        return (None, None, {})

    commission_value: float | None = None
    stamp_duty_value: float | None = None
    line_map: dict[str, int] = {}

    # Patterns to match (lowercase for case-insensitive comparison)
    commission_names = {
        "commission_rate",
        "commissionrate",
        "comm_rate",
        "comission_rate",  # typo tolerance
    }
    stamp_duty_names = {
        "stamp_duty_rate",
        "stampduty",
        "stamp_tax",
        "stamp_tax_sell",
        "stampduty_rate",
    }

    def _check_and_record(attr_name: str, value_node: ast.AST, line: int) -> None:
        nonlocal commission_value, stamp_duty_value
        attr_lower = attr_name.lower()
        if attr_lower in commission_names:
            val = _extract_numeric_value(value_node)
            if val is not None:
                commission_value = val
                line_map["commission"] = line
        elif attr_lower in stamp_duty_names:
            val = _extract_numeric_value(value_node)
            if val is not None:
                stamp_duty_value = val
                line_map["stamp_duty"] = line

    for node in ast.walk(tree):
        if not hasattr(node, "lineno"):
            continue

        # Pattern 1: AnnAssign (annotated assignment) for dataclass fields
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                _check_and_record(node.target.id, node.value, node.lineno)

        # Pattern 2: Assign (bare assignment) for class constants
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                _check_and_record(target.id, node.value, node.lineno)

        # Pattern 3: Function default arguments (kw_defaults for
        # keyword-only args after `*`)
        elif isinstance(node, ast.FunctionDef):
            args = node.args
            # Positional arg defaults
            positional_defaults = args.defaults
            positional_args = args.args
            # Align defaults with positional args (last N args have defaults)
            n_pos_defaults = len(positional_defaults)
            for i, default in enumerate(positional_defaults):
                arg_idx = len(positional_args) - n_pos_defaults + i
                if 0 <= arg_idx < len(positional_args):
                    arg_name = positional_args[arg_idx].arg
                    line = getattr(default, "lineno", node.lineno)
                    _check_and_record(arg_name, default, line)
            # Keyword-only arg defaults (kw_defaults is list aligned with kwonlyargs)
            for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
                if kw_default is not None:
                    line = getattr(kw_default, "lineno", node.lineno)
                    _check_and_record(kw_arg.arg, kw_default, line)

    return (commission_value, stamp_duty_value, line_map)


def _engine_red_message(
    engine: str,
    commission: float | None,
    stamp_duty: float | None,
    issue: str,
) -> str:
    comm_str = f"{commission}" if commission is not None else "NOT FOUND"
    stamp_str = f"{stamp_duty}" if stamp_duty is not None else "NOT FOUND"
    return (
        f"§0/§3 COST MODEL VIOLATION: {engine} uses non-canonical cost "
        f"rates.\n"
        f"Commission: {comm_str} (canonical: {CANONICAL_COMMISSION})\n"
        f"Stamp duty: {stamp_str} (valid: {sorted(VALID_STAMP_DUTY)})\n"
        f"Issue: {issue}\n"
        f"Per CLAUDE.md §0 Pessimistic Default + §3 Raw Prices: cost "
        f"model must be canonical to ensure cross-engine consistency "
        f"and accurate net PnL reporting.\n"
        f"Per [[audit-2026-09-23-cost-model-undercount]]: 0.0006 "
        f"commission has no historical basis; 0.001 stamp duty is "
        f"pre-Aug2023 only."
    )


# ---------------------------------------------------------------------------
# Verification: each engine uses canonical cost model
# ---------------------------------------------------------------------------


def test_chase_up_cost_model_canonical() -> None:
    """§0/§3 PASS: chase_up uses canonical 0.00025 + 0.0005.

    Per portfolio.py:144-145: `commission_rate: float = 0.00025,
    stamp_duty_rate: float = 0.0005`.
    """
    commission, stamp_duty, lines = _scan_cost_constants(
        COST_MODEL_FILES["chase_up"]
    )

    if commission != CANONICAL_COMMISSION:
        raise AssertionError(
            _engine_red_message(
                "chase_up",
                commission,
                stamp_duty,
                f"commission must be {CANONICAL_COMMISSION}",
            )
        )

    if stamp_duty not in VALID_STAMP_DUTY:
        raise AssertionError(
            _engine_red_message(
                "chase_up",
                commission,
                stamp_duty,
                f"stamp_duty must be one of {sorted(VALID_STAMP_DUTY)}",
            )
        )


def test_uptrend_pullback_cost_model_canonical() -> None:
    """§0/§3 PASS: uptrend_pullback uses canonical 0.00025 + 0.0005.

    Per portfolio.py:128-129: `commission_rate: float = 0.00025,
    stamp_duty_rate: float = 0.0005`.
    """
    commission, stamp_duty, lines = _scan_cost_constants(
        COST_MODEL_FILES["uptrend_pullback"]
    )

    if commission != CANONICAL_COMMISSION:
        raise AssertionError(
            _engine_red_message(
                "uptrend_pullback",
                commission,
                stamp_duty,
                f"commission must be {CANONICAL_COMMISSION}",
            )
        )

    if stamp_duty not in VALID_STAMP_DUTY:
        raise AssertionError(
            _engine_red_message(
                "uptrend_pullback",
                commission,
                stamp_duty,
                f"stamp_duty must be one of {sorted(VALID_STAMP_DUTY)}",
            )
        )


def test_short_reversal_cost_model_canonical() -> None:
    """§0/§3 RED: short_reversal uses WRONG 0.0006 commission.

    Per replay_strategy_v3.py:69-70:
    `commission_rate=0.0006, stamp_duty_rate=0.001`.
    Commission 0.0006 has NO HISTORICAL BASIS — must be 0.00025.
    """
    commission, stamp_duty, lines = _scan_cost_constants(
        COST_MODEL_FILES["short_reversal"]
    )

    if commission != CANONICAL_COMMISSION:
        raise AssertionError(
            _engine_red_message(
                "short_reversal",
                commission,
                stamp_duty,
                f"commission 0.0006 has no historical basis (line "
                f"{lines.get('commission', '?')}); canonical is "
                f"{CANONICAL_COMMISSION}",
            )
        )


def test_cycle_price_action_cost_model_canonical() -> None:
    """§0/§3 RED: cycle_price_action uses 0.001 stamp duty (pre-Aug2023).

    Per portfolio.py:60-62:
    `COMMISSION_RATE = 0.00025, MIN_COMMISSION = 5.0,
    STAMP_TAX_SELL = 0.001`.
    Commission is canonical, but stamp duty is PRE-Aug2023 rate
    (0.001) without a date guard. For post-Aug2023 backtests, must
    be 0.0005.
    """
    commission, stamp_duty, lines = _scan_cost_constants(
        COST_MODEL_FILES["cycle_price_action"]
    )

    if commission != CANONICAL_COMMISSION:
        raise AssertionError(
            _engine_red_message(
                "cycle_price_action",
                commission,
                stamp_duty,
                f"commission must be {CANONICAL_COMMISSION}",
            )
        )

    # Stamp duty 0.001 is valid (pre-Aug2023) but needs date guard
    # for post-Aug2023 backtests. For now, accept both values; flag
    # as PASS for 0.0005, RED for 0.001 with note.
    if stamp_duty == 0.001:
        raise AssertionError(
            _engine_red_message(
                "cycle_price_action",
                commission,
                stamp_duty,
                f"stamp_duty 0.001 (pre-Aug2023) used without date "
                f"guard (line {lines.get('stamp_duty', '?')}); "
                f"post-Aug2023 backtests must use 0.0005",
            )
        )

    if stamp_duty not in VALID_STAMP_DUTY:
        raise AssertionError(
            _engine_red_message(
                "cycle_price_action",
                commission,
                stamp_duty,
                f"stamp_duty must be one of {sorted(VALID_STAMP_DUTY)}",
            )
        )
