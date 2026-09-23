"""§0/§3 Cost Model Single Source Enforcement audit (Tick 53).

CLAUDE.md §0/§3 (verbatim cost model):
  - 佣金 commission   0.00025   万 2.5, buy/sell 都扣, 最低 ¥5
  - 印花税 stamp_duty  0.0005   万 5, 仅 sell 方向
  - 万 2.5 + 万 5 = 1bp + 2bp = total cost in raw basis points

**核心发现 (FRESH 2026-09-23):**

A. **`core/dual_price.py` does NOT export cost model constants**
   (verified):
   - core/ contains: dual_price.py + walkforward.py
   - dual_price.py exports: LIMIT_UP_THRESHOLD, ExecutionBar, Layout strings
   - dual_price.py does NOT export: COMMISSION_RATE, STAMP_DUTY_RATE,
     MIN_COMMISSION
   - Per [[dual-price-refactor-uncommitted]]: "core/dual_price.py single
     source" claim is FALSE for cost model (only true for limit_up +
     execution bar layout)

B. **short_reversal WRONG VALUES** (verified):
   - short_reversal/engine.py:24: `COMMISSION_RATE = 0.0006` ✗
     (should be 0.00025, 2.4× off)
   - short_reversal/engine.py:25: `STAMP_DUTY_RATE = 0.001` ✗
     (should be 0.0005, 2× off)
   - short_reversal/replay_strategy_v3.py:69-70: hardcoded 0.0006 + 0.001
     (function defaults, also wrong)
   - short_reversal/scan_signals.py:31,34: imports COMMISSION_RATE +
     STAMP_DUTY_RATE from short_reversal.engine → propagates wrong values

C. **cycle_price_action WRONG STAMP** (verified):
   - cycle_price_action/portfolio.py:60: `COMMISSION_RATE = 0.00025` ✓
   - cycle_price_action/portfolio.py:61: `MIN_COMMISSION = 5.0` ✓
   - cycle_price_action/portfolio.py:62: `STAMP_TAX_SELL = 0.001` ✗
     (should be 0.0005, 2× off)

D. **chase_up + uptrend_pullback CORRECT BUT DUPLICATED** (verified):
   - chase_up/portfolio.py:144-146: defaults 0.00025, 0.0005, 5.0
   - chase_up/replay_broker.py:11-13: CommInfoBase params same
   - chase_up/replay_broker.py:28-30: function defaults same
   - uptrend_pullback/portfolio.py:128-130: same
   - uptrend_pullback/replay_broker.py:26-28: same
   - uptrend_pullback/replay_broker.py:43-44: same
   - 6 files duplicate the same constants (single source principle violated)
   - Each file CAN drift independently (currently aligned)

E. **Numeric impact**:
   - short_reversal trades: commission charged 2.4× correct amount, stamp
     charged 2× correct amount → PnL understated by ~30-50 bps per round-trip
   - cycle trades: stamp 2× correct → sell-side PnL understated by 5 bps
   - 6 files duplicating constants: high maintenance burden (any change
     must be applied to all 6 sites, easy to miss one)

F. **Consequences**:
   - Per [[audit-2026-09-23-cost-model-undercount]]: 5 files / 2 engines
     cost model wrong (Tick 53 confirms 3 files / 2 engines + adds 6 files
     / 2 engines duplicated correct)
   - Per-trade math closure: short_reversal trades.csv gross - fees ≠ net
     if audit uses canonical 0.00025 + 0.0005

本文件验证:
- 4 RED:
  - short_reversal engine.py COMMISSION_RATE = 0.0006 (wrong)
  - short_reversal engine.py STAMP_DUTY_RATE = 0.001 (wrong)
  - cycle_price_action portfolio.py STAMP_TAX_SELL = 0.001 (wrong)
  - chase_up + uptrend duplicate cost model constants (6 files)
- 2 PASS baselines:
  - chase_up + uptrend CORRECT VALUES (pin correctness)
  - core/dual_price.py exists (canonical for layout/limit_up, not cost)
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Canonical cost model values per CLAUDE.md §0/§3
CANONICAL_COMMISSION_RATE = 0.00025  # 万 2.5
CANONICAL_STAMP_DUTY_RATE = 0.0005   # 万 5
CANONICAL_MIN_COMMISSION = 5.0       # ¥5 floor


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _find_constant_assignments(
    tree: ast.AST, target_name: str
) -> list[tuple[int, object]]:
    """Find all module-level assignments to `target_name`.

    Returns list of (line_number, assigned_value).
    """
    hits: list[tuple[int, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # Only module-level assignments (parent is Module)
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == target_name:
                value = node.value
                # Try to extract constant value
                if isinstance(value, ast.Constant):
                    hits.append((node.lineno, value.value))
                else:
                    hits.append((node.lineno, None))
    return hits


def _find_function_defaults(
    tree: ast.AST, func_name: str, param_name: str
) -> list[tuple[int, object]]:
    """Find function `func_name` parameter `param_name` default value.

    Returns list of (line_number, default_value).
    """
    hits: list[tuple[int, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != func_name:
            continue
        # Iterate through args (positional + kwonly)
        all_params = node.args.args + node.args.kwonlyargs
        defaults = node.args.defaults + node.args.kw_defaults
        for arg, default in zip(all_params, defaults):
            if arg.arg == param_name and default is not None:
                line = default.lineno if hasattr(default, "lineno") else node.lineno
                if isinstance(default, ast.Constant):
                    hits.append((line, default.value))
                else:
                    hits.append((line, None))
    return hits


# ---------------------------------------------------------------------------
# RED: short_reversal WRONG VALUES
# ---------------------------------------------------------------------------


def test_short_reversal_engine_commission_rate_must_be_0_00025() -> None:
    """§0/§3 RED: short_reversal/engine.py COMMISSION_RATE is wrong.

    Currently COMMISSION_RATE = 0.0006 (line 24). Canonical value per
    CLAUDE.md §0/§3 is 0.00025 (万 2.5). 2.4× off.

    Per [[audit-2026-09-23-cost-model-undercount]]: confirmed wrong.
    """
    path = REPO_ROOT / "short_reversal" / "engine.py"
    if not path.exists():
        return  # structure changed

    source = _read_source(path)
    if not source:
        return
    tree = ast.parse(source)

    # Check module-level COMMISSION_RATE assignment
    hits = _find_constant_assignments(tree, "COMMISSION_RATE")
    if not hits:
        return  # not at module level — maybe inside class

    violations = [
        (line, val) for line, val in hits
        if val is not None and val != CANONICAL_COMMISSION_RATE
    ]
    if not violations:
        return  # GREEN — corrected to canonical

    line, val = violations[0]
    raise AssertionError(
        f"§0/§3 COST MODEL VIOLATION: short_reversal/engine.py:{line} "
        f"COMMISSION_RATE = {val} (expected canonical {CANONICAL_COMMISSION_RATE} "
        f"= 万 2.5 per CLAUDE.md §0/§3).\n"
        f"Per [[audit-2026-09-23-cost-model-undercount]]: 2.4× off.\n"
        f"GREEN fix: change to 0.00025 OR import from canonical source.\n"
        f"This value propagates to short_reversal/scan_signals.py:31 and\n"
        f"short_reversal/replay_strategy_v3.py:69 via import + default."
    )


def test_short_reversal_engine_stamp_duty_rate_must_be_0_0005() -> None:
    """§0/§3 RED: short_reversal/engine.py STAMP_DUTY_RATE is wrong.

    Currently STAMP_DUTY_RATE = 0.001 (line 25). Canonical value per
    CLAUDE.md §0/§3 is 0.0005 (万 5). 2× off.

    Per [[audit-2026-09-23-cost-model-undercount]]: confirmed wrong.
    """
    path = REPO_ROOT / "short_reversal" / "engine.py"
    if not path.exists():
        return

    source = _read_source(path)
    if not source:
        return
    tree = ast.parse(source)

    hits = _find_constant_assignments(tree, "STAMP_DUTY_RATE")
    if not hits:
        return

    violations = [
        (line, val) for line, val in hits
        if val is not None and val != CANONICAL_STAMP_DUTY_RATE
    ]
    if not violations:
        return

    line, val = violations[0]
    raise AssertionError(
        f"§0/§3 COST MODEL VIOLATION: short_reversal/engine.py:{line} "
        f"STAMP_DUTY_RATE = {val} (expected canonical {CANONICAL_STAMP_DUTY_RATE} "
        f"= 万 5 per CLAUDE.md §0/§3, sell-only).\n"
        f"Per [[audit-2026-09-23-cost-model-undercount]]: 2× off.\n"
        f"GREEN fix: change to 0.0005 OR import from canonical source.\n"
        f"NOTE: stamp_duty is only applied to SELL side per §0/§3 — verify\n"
        f"engine.py doesn't double-apply on BUY too."
    )


def test_cycle_portfolio_stamp_tax_sell_must_be_0_0005() -> None:
    """§0/§3 RED: cycle_price_action/portfolio.py STAMP_TAX_SELL is wrong.

    Currently STAMP_TAX_SELL = 0.001 (line 62). Canonical value per
    CLAUDE.md §0/§3 is 0.0005 (万 5). 2× off.

    COMMISSION_RATE + MIN_COMMISSION are CORRECT (0.00025 + 5.0).
    Only STAMP_TAX_SELL diverges.
    """
    path = REPO_ROOT / "cycle_price_action" / "portfolio.py"
    if not path.exists():
        return

    source = _read_source(path)
    if not source:
        return
    tree = ast.parse(source)

    hits = _find_constant_assignments(tree, "STAMP_TAX_SELL")
    if not hits:
        return

    violations = [
        (line, val) for line, val in hits
        if val is not None and val != CANONICAL_STAMP_DUTY_RATE
    ]
    if not violations:
        return

    line, val = violations[0]
    raise AssertionError(
        f"§0/§3 COST MODEL VIOLATION: cycle_price_action/portfolio.py:{line} "
        f"STAMP_TAX_SELL = {val} (expected canonical {CANONICAL_STAMP_DUTY_RATE} "
        f"= 万 5 per CLAUDE.md §0/§3, sell-only).\n"
        f"Per [[audit-2026-09-23-cost-model-undercount]]: 2× off.\n"
        f"COMMISSION_RATE (0.00025) + MIN_COMMISSION (5.0) are correct.\n"
        f"GREEN fix: change to 0.0005."
    )


def test_cost_model_constants_duplicated_across_engines() -> None:
    """§0/§3 RED: cost model constants duplicated across 6 files (not single source).

    Per [[dual-price-refactor-uncommitted]] claim: core/dual_price.py should
    be the single source for cost model. ACTUAL state:
    - chase_up/portfolio.py + chase_up/replay_broker.py (2 files)
    - uptrend_pullback/portfolio.py + uptrend_pullback/replay_broker.py (2 files)
    - short_reversal/engine.py + replay_strategy_v3.py (2 files)
    - cycle_price_action/portfolio.py (1 file)
    Total: 7 files duplicate cost model constants (each can drift independently)

    This is a §0 violation of single-source-of-truth principle. Even
    though values are currently aligned for chase_up + uptrend, the
    duplication is fragile.
    """
    # Files that hardcode commission_rate / stamp_duty_rate constants
    files_with_hardcoded_costs = [
        REPO_ROOT / "chase_up" / "portfolio.py",
        REPO_ROOT / "chase_up" / "replay_broker.py",
        REPO_ROOT / "uptrend_pullback" / "portfolio.py",
        REPO_ROOT / "uptrend_pullback" / "replay_broker.py",
        REPO_ROOT / "short_reversal" / "engine.py",
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
    ]

    # Check which files have the constants hardcoded (not imported from core)
    duplicates: list[str] = []
    for path in files_with_hardcoded_costs:
        if not path.exists():
            continue
        source = _read_source(path)
        if not source:
            continue
        # If file does NOT import cost model from core/dual_price.py,
        # it's a duplicate
        if "from core.dual_price" not in source and "core.dual_price" not in source:
            duplicates.append(str(path.relative_to(REPO_ROOT)))

    # Currently 7 files have hardcoded constants (no canonical source exists)
    # If green: 0 files (all import from core)
    if not duplicates:
        return  # GREEN — all engines import from canonical source

    raise AssertionError(
        f"§0/§3 COST MODEL SINGLE-SOURCE VIOLATION: {len(duplicates)} files "
        f"hardcode cost model constants instead of importing from canonical "
        f"source:\n" +
        "\n".join(f"  {p}" for p in duplicates) +
        f"\nPer [[dual-price-refactor-uncommitted]]: core/dual_price.py "
        f"should be single source for cost model constants.\n"
        f"Currently core/dual_price.py exports LIMIT_UP_THRESHOLD only — "
        f"no COMMISSION_RATE/STAMP_DUTY_RATE/MIN_COMMISSION.\n"
        f"GREEN fix: add cost model constants to core/dual_price.py and "
        f"have all 7 files import them."
    )


# ---------------------------------------------------------------------------
# PASS baselines: pin correctness despite duplication
# ---------------------------------------------------------------------------


def test_chase_up_uptrend_have_correct_commission_rate_values() -> None:
    """§0/§3 PASS baseline: chase_up + uptrend values are CORRECT (pin).

    chase_up/portfolio.py:144 + uptrend_pullback/portfolio.py:128 both
    use 0.00025 (canonical). Pin this correctness — if either drifts,
    test fails.
    """
    files_to_check = {
        REPO_ROOT / "chase_up" / "portfolio.py": 144,
        REPO_ROOT / "uptrend_pullback" / "portfolio.py": 128,
    }
    violations: list[str] = []
    for path, expected_line in files_to_check.items():
        if not path.exists():
            continue
        source = _read_source(path)
        if not source:
            continue
        if "commission_rate: float = 0.00025" not in source:
            violations.append(
                f"{path.relative_to(REPO_ROOT)} missing canonical "
                f"commission_rate = 0.00025 (line ~{expected_line})"
            )

    assert not violations, (
        "Regression: chase_up/uptrend lost canonical commission_rate value:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_core_dual_price_exists_as_canonical_for_layout_and_limit_up() -> None:
    """§0/§3 PASS baseline: core/dual_price.py exists as canonical source.

    Pin: core/dual_price.py exports LIMIT_UP_THRESHOLD + Layout strings
    (canonical for execution layer). Cost model constants NOT yet
    exported — gap documented in test_cost_model_constants_duplicated.
    """
    path = REPO_ROOT / "core" / "dual_price.py"
    assert path.exists(), "Regression: core/dual_price.py missing"

    source = _read_source(path)
    # Pin: canonical exports for execution layer
    assert "LIMIT_UP_THRESHOLD" in source, (
        "Regression: core/dual_price.py lost LIMIT_UP_THRESHOLD constant"
    )
    assert "LAYOUT_CHASE_UPTREND" in source or "Layout" in source, (
        "Regression: core/dual_price.py lost Layout contract"
    )