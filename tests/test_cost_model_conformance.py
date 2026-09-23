"""§0/§3 Cost Model cross-engine conformance RED tests.

CLAUDE.md §0 + §3 mandates:
- Commission: 万 2.5 = 0.00025 (buy + sell both charged)
- Stamp duty: 万 5 = 0.0005 (post-Aug 2023, sell-only on A-share long side;
  on short side, sell = open, so stamp applies there too)
- Min commission: ¥ 5 floor (max of floor or rate-based)

VIOLATIONS CONFIRMED (2026-09-23):
1. cycle_price_action/portfolio.py:62 STAMP_TAX_SELL = 0.001 → should be 0.0005 (2x)
2. short_reversal/engine.py:24 COMMISSION_RATE = 0.0006 → should be 0.00025 (2.4x)
3. short_reversal/engine.py:25 STAMP_DUTY_RATE = 0.001 → should be 0.0005 (2x)

Companion to [[audit-2026-09-23-cost-model-undercount]] (already in memory).

RED tests pin canonical cost values. GREEN aligns 5-file violations + 2
test locks per memory entry.
"""
from __future__ import annotations

import importlib


# Canonical CLAUDE.md §0/§3 cost model values
CANONICAL = {
    "commission_rate": 0.00025,
    "stamp_duty_rate": 0.0005,
    "min_commission": 5.0,
}


def _get_constant(module_name: str, attr_candidates: list[str]):
    """Look up constant from module, trying each candidate name.

    Supports three patterns:
      (a) Module-level constant (e.g. short_reversal.engine.COMMISSION_RATE)
      (b) Class-level constant (e.g. cycle_price_action.portfolio.Portfolio.COMMISSION_RATE)
      (c) Function default argument (e.g. simulate_portfolio(commission_rate=0.00025))

    For (c), Python parameter names are lowercase-snake_case. We match
    case-insensitively so callers can pass either COMMISSION_RATE or
    commission_rate.
    """
    import inspect
    mod = importlib.import_module(module_name)

    # Pattern (a): module-level constant — case-sensitive (matches actual attr name)
    for attr in attr_candidates:
        if hasattr(mod, attr):
            value = getattr(mod, attr)
            if isinstance(value, (int, float)):
                return value

    # Pattern (b): class-level constant — scan all classes in module
    for name in dir(mod):
        obj = getattr(mod, name)
        if inspect.isclass(obj):
            for attr in attr_candidates:
                if hasattr(obj, attr):
                    value = getattr(obj, attr)
                    if isinstance(value, (int, float)):
                        return value

    # Pattern (c): function default argument — case-insensitive match
    # Python kwargs are lowercase by convention, callers may pass either case
    for name in dir(mod):
        try:
            obj = getattr(mod, name)
        except AttributeError:
            continue
        if callable(obj) and not inspect.isclass(obj):
            try:
                sig = inspect.signature(obj)
                param_keys_lower = {k.lower(): k for k in sig.parameters}
                for attr in attr_candidates:
                    actual_key = param_keys_lower.get(attr.lower())
                    if actual_key is None:
                        continue
                    default = sig.parameters[actual_key].default
                    if isinstance(default, (int, float)):
                        return default
            except (ValueError, TypeError):
                continue

    raise AttributeError(
        f"None of {attr_candidates} found in {module_name}. "
        f"Module has: {[a for a in dir(mod) if not a.startswith('_')][:20]}"
    )


def test_chase_up_cost_model_compliant() -> None:
    """chase_up: commission 0.00025, stamp 0.0005, min ¥5 — must match canonical."""
    commission = _get_constant("chase_up.portfolio", ["COMMISSION_RATE"])
    stamp = _get_constant("chase_up.portfolio", ["STAMP_DUTY_RATE", "STAMP_TAX_SELL"])
    min_comm = _get_constant("chase_up.portfolio", ["MIN_COMMISSION"])

    assert commission == CANONICAL["commission_rate"], (
        f"chase_up commission {commission} != canonical "
        f"{CANONICAL['commission_rate']}"
    )
    assert stamp == CANONICAL["stamp_duty_rate"], (
        f"chase_up stamp {stamp} != canonical {CANONICAL['stamp_duty_rate']}"
    )
    assert min_comm == CANONICAL["min_commission"]


def test_uptrend_pullback_cost_model_compliant() -> None:
    """uptrend_pullback: identical canonical values."""
    commission = _get_constant("uptrend_pullback.portfolio", ["COMMISSION_RATE"])
    stamp = _get_constant("uptrend_pullback.portfolio", ["STAMP_DUTY_RATE", "STAMP_TAX_SELL"])
    min_comm = _get_constant("uptrend_pullback.portfolio", ["MIN_COMMISSION"])

    assert commission == CANONICAL["commission_rate"]
    assert stamp == CANONICAL["stamp_duty_rate"]
    assert min_comm == CANONICAL["min_commission"]


def test_cycle_price_action_stamp_must_be_0_0005() -> None:
    """cycle_price_action STAMP_TAX_SELL = 0.001 → MUST be 0.0005.

    Bug: cycle_price_action/portfolio.py:62 sets stamp to 0.001 (double).
    This overstates sell-side costs by 2x, suppressing reported returns.
    """
    stamp = _get_constant("cycle_price_action.portfolio", ["STAMP_TAX_SELL"])
    assert stamp == CANONICAL["stamp_duty_rate"], (
        f"cycle_price_action STAMP_TAX_SELL = {stamp} != canonical "
        f"{CANONICAL['stamp_duty_rate']}. §0/§3 mandates 0.0005 post-Aug 2023."
    )


def test_cycle_price_action_commission_compliant() -> None:
    """cycle_price_action commission = 0.00025 ✓ (already correct)."""
    commission = _get_constant("cycle_price_action.portfolio", ["COMMISSION_RATE"])
    assert commission == CANONICAL["commission_rate"]


def test_short_reversal_commission_must_be_0_00025() -> None:
    """short_reversal COMMISSION_RATE = 0.0006 → MUST be 0.00025.

    Bug: short_reversal/engine.py:24 sets commission to 0.0006 (2.4x).
    Overstates entry/exit costs.
    """
    commission = _get_constant("short_reversal.engine", ["COMMISSION_RATE"])
    assert commission == CANONICAL["commission_rate"], (
        f"short_reversal COMMISSION_RATE = {commission} != canonical "
        f"{CANONICAL['commission_rate']}. §0/§3 mandates 0.00025."
    )


def test_short_reversal_stamp_must_be_0_0005() -> None:
    """short_reversal STAMP_DUTY_RATE = 0.001 → MUST be 0.0005."""
    stamp = _get_constant("short_reversal.engine", ["STAMP_DUTY_RATE"])
    assert stamp == CANONICAL["stamp_duty_rate"], (
        f"short_reversal STAMP_DUTY_RATE = {stamp} != canonical "
        f"{CANONICAL['stamp_duty_rate']}. §0/§3 mandates 0.0005."
    )


def test_all_engines_share_canonical_cost_model() -> None:
    """All 4 engines must use identical canonical commission + stamp + min floor."""
    modules_and_attrs = [
        ("chase_up.portfolio", ["COMMISSION_RATE"], ["STAMP_DUTY_RATE", "STAMP_TAX_SELL"], ["MIN_COMMISSION"]),
        ("uptrend_pullback.portfolio", ["COMMISSION_RATE"], ["STAMP_DUTY_RATE", "STAMP_TAX_SELL"], ["MIN_COMMISSION"]),
        ("cycle_price_action.portfolio", ["COMMISSION_RATE"], ["STAMP_TAX_SELL"], ["MIN_COMMISSION"]),
        ("short_reversal.engine", ["COMMISSION_RATE"], ["STAMP_DUTY_RATE"], []),
    ]
    failures: list[str] = []
    for module, comm_attrs, stamp_attrs, min_attrs in modules_and_attrs:
        try:
            comm = _get_constant(module, comm_attrs)
            stamp = _get_constant(module, stamp_attrs)
            if comm != CANONICAL["commission_rate"]:
                failures.append(f"{module}: commission {comm}")
            if stamp != CANONICAL["stamp_duty_rate"]:
                failures.append(f"{module}: stamp {stamp}")
            if min_attrs:
                min_comm = _get_constant(module, min_attrs)
                if min_comm != CANONICAL["min_commission"]:
                    failures.append(f"{module}: min_commission {min_comm}")
        except AttributeError as e:
            failures.append(f"{module}: {e}")
    assert not failures, (
        "Cost model violations:\n  " + "\n  ".join(failures)
    )
