"""§0/§3 Cost Model Canonical Single-Source — Round 9 (2026-09-28).

CLAUDE.md §0 (verbatim):
  "**Pessimistic Default:** Always assume the worst-case scenario for
   market liquidity, execution price, and statistical significance."

CLAUDE.md §3 (verbatim):
  "Cash dividends must explicitly trigger a physical cash deposit into
   `Free_Cash`. Stock splits must trigger an atomic multiplier adjustment
   to `Position_Quantity` and `Average_Cost`."

Round 9 canonical cost model contract (CLAUDE.md §0/§3):
  - Commission: 万 2.5 = 0.00025 (canonical)
  - Stamp duty: 万 5 = 0.0005 (POST-Aug2023, sell-only)
  - Min commission: ¥5 floor

After the Round 9 single-source refactor:
  - core/dual_price.py is the SOLE source of cost model constants
  - 4 engines consume canonical values via `from core.dual_price import ...`
  - No engine hardcodes 0.00025/0.0005/0.0006/0.001 literals anymore
  - short_reversal commission rate 0.0006 (2.4x off canonical) is FIXED
  - cycle stamp duty 0.001 (pre-Aug2023) is FIXED to 0.0005 (post-Aug2023)

This module is a forward-defense guard: re-detects the regression
classes documented in [[cost-model-single-source-audit-2026-09-23]]
Tick 53, [[cost-constants-single-source-4engine-2026-09-23]] Tick 67,
and [[section0-cost-model-canonical-conformance-2026-09-23]] Tick 76.
"""
from __future__ import annotations

import ast
from pathlib import Path

from core.dual_price import (
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,
    STAMP_DUTY_SIDE,
    calc_commission,
    calc_stamp_duty,
)


# ----------------------------------------------------------- canonical constants


def test_core_dual_price_exports_canonical_constants() -> None:
    """§0/§3 PASS: core.dual_price exports canonical cost constants."""
    assert COMMISSION_RATE == 0.00025, (
        f"§0/§3 COST MODEL VIOLATION: COMMISSION_RATE={COMMISSION_RATE}, "
        f"expected canonical 0.00025 (万2.5)."
    )
    assert STAMP_DUTY_RATE == 0.0005, (
        f"§0/§3 COST MODEL VIOLATION: STAMP_DUTY_RATE={STAMP_DUTY_RATE}, "
        f"expected canonical 0.0005 (万5, post-Aug2023)."
    )
    assert MIN_COMMISSION == 5.0, (
        f"§0/§3 COST MODEL VIOLATION: MIN_COMMISSION={MIN_COMMISSION}, "
        f"expected canonical ¥5 floor."
    )
    assert STAMP_DUTY_SIDE == "sell", (
        f"§0/§3 COST MODEL VIOLATION: STAMP_DUTY_SIDE={STAMP_DUTY_SIDE!r}, "
        f"expected 'sell' (China A-share convention)."
    )


# ----------------------------------------------------------- canonical helpers


def test_calc_commission_min_floor() -> None:
    """§0/§3 PASS: calc_commission applies ¥5 min floor.

    notional=10000 → max(5.0, 10000 × 0.00025) = max(5.0, 2.5) = 5.0
    """
    assert calc_commission(10_000) == 5.0, (
        f"§0/§3 cost commission floor broken: calc_commission(10000) "
        f"= {calc_commission(10_000)}, expected 5.0 (¥5 floor)."
    )


def test_calc_commission_rate_scaled() -> None:
    """§0/§3 PASS: calc_commission scales linearly past min floor.

    notional=1_000_000 → max(5.0, 1_000_000 × 0.00025) = max(5.0, 250.0) = 250.0
    """
    assert calc_commission(1_000_000) == 250.0, (
        f"§0/§3 cost commission rate broken: calc_commission(1_000_000) "
        f"= {calc_commission(1_000_000)}, expected 250.0 (=1M × 0.00025)."
    )


def test_calc_stamp_duty_buy_zero() -> None:
    """§0/§3 PASS: stamp duty on buy side is zero (China A-share)."""
    assert calc_stamp_duty(1_000_000, "buy") == 0.0, (
        f"§0/§3 cost stamp duty buy-side broken: "
        f"calc_stamp_duty(1M, 'buy') = {calc_stamp_duty(1_000_000, 'buy')}, "
        f"expected 0.0 (China A-share convention)."
    )


def test_calc_stamp_duty_sell_nonzero() -> None:
    """§0/§3 PASS: stamp duty on sell side = notional × 0.0005."""
    assert calc_stamp_duty(1_000_000, "sell") == 500.0, (
        f"§0/§3 cost stamp duty sell-side broken: "
        f"calc_stamp_duty(1M, 'sell') = {calc_stamp_duty(1_000_000, 'sell')}, "
        f"expected 500.0 (=1M × 0.0005)."
    )


# ----------------------------------------------------------- forward-defense guards


def _contains_literal(path: Path, value: float) -> list[tuple[int, float]]:
    """Return [(line, value)] for every `ast.Constant` matching value."""
    if not path.exists():
        return []
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    hits: list[tuple[int, float]] = []
    for node in ast.walk(tree):
        if not hasattr(node, "lineno"):
            continue
        if isinstance(node, ast.Constant) and isinstance(
            node.value, (int, float)
        ) and float(node.value) == value:
            hits.append((node.lineno, float(node.value)))
    return hits


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_short_reversal_uses_canonical_commission_rate() -> None:
    """§0/§3 PASS forward-defense: short_reversal hardcodes 0.0006 nowhere.

    Per [[cost-model-single-source-audit-2026-09-23]] Tick 53:
    short_reversal COMMISSION_RATE = 0.0006 (2.4× canonical 0.00025)
    silently under-reported net PnL for many versions. After Round 9 fix,
    short_reversal production modules MUST NOT contain the literal 0.0006.
    """
    production_files = [
        REPO_ROOT / "short_reversal" / "engine.py",
        REPO_ROOT / "short_reversal" / "replay_strategy_v3.py",
        REPO_ROOT / "short_reversal" / "scan_signals.py",
        REPO_ROOT / "short_reversal" / "st_filter.py",
        REPO_ROOT / "short_reversal" / "grid_runner.py",
        REPO_ROOT / "short_reversal" / "indicators_bt.py",
    ]
    violations: list[str] = []
    for path in production_files:
        hits = _contains_literal(path, 0.0006)
        if hits:
            for line, val in hits:
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line} = {val}")
    assert not violations, (
        f"§0/§3 COST MODEL VIOLATION: short_reversal production code "
        f"contains literal 0.0006 (Round 9 fix was incomplete).\n"
        f"Per CLAUDE.md §0/§3: canonical commission rate is 0.00025.\n"
        f"Per [[audit-2026-09-23-cost-model-undercount]]: 0.0006 has no "
        f"historical basis and silently under-reports trading cost.\n"
        f"Violations: {violations}"
    )


def test_cycle_uses_canonical_stamp_rate() -> None:
    """§0/§3 PASS forward-defense: cycle PriceAction stamp literal ≠ 0.001.

    Per [[cost-model-single-source-audit-2026-09-23]] Tick 53:
    cycle_price_action STAMP_TAX_SELL = 0.001 (= 万10, PRE-Aug2023
    historical) is wrong for POST-Aug2023 backtests. After Round 9 fix,
    cycle production modules MUST NOT contain the literal 0.001 as a
    STAMP_DUTY_RATE-like value.
    """
    production_files = [
        REPO_ROOT / "cycle_price_action" / "portfolio.py",
        REPO_ROOT / "cycle_price_action" / "replay_broker.py",
        REPO_ROOT / "cycle_price_action" / "data_feed.py",
        REPO_ROOT / "cycle_price_action" / "signals.py",
    ]
    violations: list[str] = []
    for path in production_files:
        hits = _contains_literal(path, 0.001)
        for line, val in hits:
            snippet = path.read_text(encoding="utf-8").splitlines()[line - 1].strip()
            snippet_lower = snippet.lower()
            # Heuristic: only flag if the literal is in a cost/stamp/tax context
            if any(
                kw in snippet_lower
                for kw in ("stamp", "tax", "duty", "commission")
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{line} = {val}: {snippet[:80]}"
                )
    assert not violations, (
        f"§0/§3 COST MODEL VIOLATION: cycle_price_action production code "
        f"contains literal 0.001 in stamp/tax context (Round 9 fix was "
        f"incomplete).\n"
        f"Per CLAUDE.md §0/§3: canonical post-Aug2023 stamp rate is 0.0005.\n"
        f"0.001 = 万10 is PRE-Aug2023 (historical only); using it for "
        f"current backtests silently under-reports sell-side cost.\n"
        f"Violations: {violations}"
    )


# ----------------------------------------------------------- baseline pin: structures


def test_all_4_engines_import_canonical_cost_model() -> None:
    """§0/§3 PASS forward-defense: all 4 engines import from core.dual_price.

    Per [[dual-price-refactor-uncommitted]] claim: core.dual_price should be
    the single source of truth for cost model. After Round 9 refactor, each
    engine's primary cost-bearing file MUST import from canonical.
    """
    files = {
        "chase_up": REPO_ROOT / "chase_up" / "replay_broker.py",
        "uptrend_pullback": REPO_ROOT / "uptrend_pullback" / "replay_broker.py",
        "short_reversal": REPO_ROOT / "short_reversal" / "engine.py",
        "cycle_price_action": REPO_ROOT / "cycle_price_action" / "replay_broker.py",
    }
    missing: list[str] = []
    for engine, path in files.items():
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        if "from core.dual_price" not in source and "core.dual_price" not in source:
            missing.append(f"{engine}: {path.relative_to(REPO_ROOT)}")
    assert not missing, (
        f"§0/§3 SINGLE-SOURCE VIOLATION: {len(missing)} engine(s) do not "
        f"import canonical cost model from core.dual_price:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\nPer Round 9 (2026-09-28): all engines must consume "
        "core.dual_price.COMMISSION_RATE / STAMP_DUTY_RATE / MIN_COMMISSION."
    )
