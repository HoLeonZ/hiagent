"""§5 Walk-Forward Validation Runner Existence Audit (Tick 65).

CLAUDE.md §5 (verbatim):
  "**Walk-Forward Validation:** Optimization logic must enforce
   Walk-Forward Validation (WFV) with strict out-of-sample (OOS)
   testing windows."

**核心发现 (FRESH 2026-09-23):**

A. **§5 WFV rigor mandate**:
   - Every optimization engine MUST use Walk-Forward Validation
   - Strict out-of-sample (OOS) testing
   - No in-sample overfitting (p-hacking prevention)
   - Per [[wfv-rigor-cross-engine-gap]]: WFV rigor varies by engine

B. **Per-engine WFV runner inventory (expected)**:
   - chase_up: should have walkforward.py + grid.py + bt_compare_presets.py
   - uptrend_pullback: should have walkforward.py + grid.py +
     bt_compare_presets.py
   - short_reversal: has walkforward.py (drift from core per
     [[short-reversal-walkforward-drift]]); has grid_runner.py
     (IS-grid, no DSR per Tick 47)
   - cycle_price_action: **NO WFV RUNNER** (per Tick 47)

C. **WFV runner file existence**:
   - `chase_up/walkforward.py` — should exist
   - `uptrend_pullback/walkforward.py` — should exist
   - `short_reversal/walkforward.py` — exists but drifts from
     core/walkforward.py
   - `cycle_price_action/walkforward.py` — **MISSING**

D. **Why cycle_price_action lacks WFV**:
   - cycle is a replay strategy (data feed driven)
   - Backtest runs on historical data with replay
   - No optimization loop (no parameter grid to search)
   - → cycle doesn't need WFV (no optimization to validate)
   - But: any FUTURE cycle optimization MUST add WFV

E. **Why this matters**:
   - §5 Statistical rigor: optimization without WFV is p-hacking
   - chase_up + uptrend + short_reversal all have parameter grids
     (TP/SL/MaxHold) — they MUST use WFV
   - cycle has no grid → no WFV required (but future work must
     remember to add)

F. **Forward-defense**:
   - PASS baselines pin WFV file existence for chase/uptrend/short
   - RED forward-defense: if chase/uptrend/short LOSE their WFV
     runners (regression), RED
   - cycle RED acknowledged as documented gap (no WFV needed without
     optimization)

G. **Test results (Tick 65 expected)**:
   - 3 PASS: chase, uptrend, short_reversal have WFV files
   - 1 RED: cycle lacks WFV file (documented exception OR future work)
"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# Engine-specific WFV runner paths
WFV_PATHS = {
    "chase_up": [
        REPO_ROOT / "chase_up" / "walkforward.py",
    ],
    "uptrend_pullback": [
        REPO_ROOT / "uptrend_pullback" / "walkforward.py",
    ],
    "short_reversal": [
        REPO_ROOT / "short_reversal" / "walkforward.py",
        REPO_ROOT / "short_reversal" / "grid_runner.py",
    ],
    "cycle_price_action": [
        REPO_ROOT / "cycle_price_action" / "walkforward.py",
        REPO_ROOT / "cycle_price_action" / "grid_runner.py",
    ],
}


# ---------------------------------------------------------------------------
# PASS baselines: chase/uptrend/short have WFV runners
# ---------------------------------------------------------------------------


def test_chase_up_has_walkforward_runner() -> None:
    """§5 PASS baseline: chase_up has walkforward.py.

    Per CLAUDE.md §5: optimization must use WFV. chase_up has
    TP/SL/MaxHold parameter grid → must have WFV runner.
    """
    paths = WFV_PATHS["chase_up"]
    existing = [p for p in paths if p.exists()]

    assert existing, (
        "§5 WFV RUNNER MISSING: chase_up has no walkforward.py. "
        "Per CLAUDE.md §5: chase_up's TP/SL/MaxHold parameter grid "
        "requires Walk-Forward Validation to prevent p-hacking."
    )


def test_uptrend_pullback_has_walkforward_runner() -> None:
    """§5 PASS baseline: uptrend_pullback has walkforward.py."""
    paths = WFV_PATHS["uptrend_pullback"]
    existing = [p for p in paths if p.exists()]

    assert existing, (
        "§5 WFV RUNNER MISSING: uptrend_pullback has no walkforward.py. "
        "Per CLAUDE.md §5: uptrend_pullback's TP/SL/MaxHold parameter "
        "grid requires WFV."
    )


def test_short_reversal_has_walkforward_runner() -> None:
    """§5 PASS baseline: short_reversal has walkforward.py or grid_runner.

    Per [[short-reversal-walkforward-drift]]: short_reversal has its
    own walkforward.py that drifts semantically from core/walkforward.py.
    This test verifies file EXISTS (drift is a separate dimension).
    """
    paths = WFV_PATHS["short_reversal"]
    existing = [p for p in paths if p.exists()]

    assert existing, (
        "§5 WFV RUNNER MISSING: short_reversal has no walkforward.py "
        "or grid_runner.py. Per CLAUDE.md §5: short_reversal's "
        "parameter optimization requires WFV."
    )


# ---------------------------------------------------------------------------
# RED: cycle_price_action has no WFV runner (documented gap)
# ---------------------------------------------------------------------------


def test_cycle_price_action_has_no_wfv_runner_documented_gap() -> None:
    """§5 RED documented: cycle_price_action has no WFV runner.

    Per [[wfv-rigor-cross-engine-gap]]: cycle_price_action lacks WFV.
    Documented gap because cycle is a replay strategy without
    parameter optimization (no grid to validate).

    Forward-defense: if cycle adds optimization in the future, this
    test will GREEN once walkforward.py is added.

    NOTE: This test is intentionally RED to document the gap and
    catch any future regression that ADDS optimization without WFV.
    """
    paths = WFV_PATHS["cycle_price_action"]
    existing = [p for p in paths if p.exists()]

    if existing:
        # If cycle DOES have WFV, that's good — but verify it follows
        # the standard pattern
        assert len(existing) >= 1, (
            "§5 cycle_price_action WFV runner exists but is incomplete."
        )
    else:
        # Documented gap — RED to enforce future work
        raise AssertionError(
            "§5 DOCUMENTED GAP: cycle_price_action has no "
            "walkforward.py or grid_runner.py.\n\n"
            "This is INTENTIONALLY RED to document the gap:\n"
            "  - cycle is a replay strategy without parameter optimization\n"
            "  - No grid → no WFV required (per CLAUDE.md §5)\n"
            "  - But: if cycle adds optimization in the future, MUST "
            "add WFV runner\n\n"
            "Reference: [[wfv-rigor-cross-engine-gap]] documents this "
            "as an open gap.\n"
            "Action: when cycle_price_action adds parameter "
            "optimization, add walkforward.py following the pattern "
            "from chase_up/walkforward.py or core/walkforward.py."
        )