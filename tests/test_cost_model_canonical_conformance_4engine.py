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



# ---------------------------------------------------------------------------
# §6 单源不变量（audit P2-11, 2026-10-15）
# ---------------------------------------------------------------------------


def _assert_cost_constants_single_sourced(engine: str) -> None:
    """引擎**不得自行声明**费率常量，必须从 core.dual_price 导入。

    本文件原先只比对**数值**是否等于 canonical —— 那允许"重复定义、数值相同"，
    而重复定义正是会静默漂移的形态：历史上 short_reversal 写成 0.0006+0.001、
    cycle 写成 0.001，都是"每个引擎各写一份"的直接后果。单源之后数值在构造上
    不可能漂移，所以断言改为更强的性质。
    """
    path = COST_MODEL_FILES[engine]
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.dual_price":
            imported |= {a.name for a in node.names}
    needed = {"COMMISSION_RATE", "STAMP_DUTY_RATE", "MIN_COMMISSION"}
    missing = needed - imported
    assert not missing, (
        f"§6 VIOLATION: {engine} 未从 core.dual_price 导入 {sorted(missing)}"
        " —— 费率常量必须单源"
    )

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in tgts:
                if isinstance(t, ast.Name) and t.id in needed:
                    assert not isinstance(node.value, ast.Constant), (
                        f"§6 VIOLATION: {engine} 在 line {node.lineno} 用字面量"
                        f"重新声明 {t.id} —— 必须引用 core 单源"
                    )

def test_chase_up_cost_model_canonical() -> None:
    """§6 单源不变量: chase_up 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("chase_up")


def test_uptrend_pullback_cost_model_canonical() -> None:
    """§6 单源不变量: uptrend_pullback 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("uptrend_pullback")


def test_short_reversal_cost_model_canonical() -> None:
    """§6 单源不变量: short_reversal 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("short_reversal")


def test_cycle_price_action_cost_model_canonical() -> None:
    """§6 单源不变量: cycle_price_action 必须从 core.dual_price 导入费率常量。

    audit P2-11 (2026-10-15): 原用例比对数值 == canonical —— 允许重复定义。
    """
    _assert_cost_constants_single_sourced("cycle_price_action")

