"""§5 WFV rigor cross-engine audit RED tests.

CLAUDE.md §5 mandates:
  - Banned In-Sample Grids — refuse simple grid-search returning "best by Sharpe"
  - Walk-Forward Validation (WFV) with strict OOS testing
  - Penalty Metrics — DSR or Bonferroni on multi-param sweeps

VIOLATIONS (FRESH 2026-09-23 audit):

A. **short_reversal/grid_runner.py — In-Sample grid, NO DSR, NO WFV**:
   - Loops over tp_pct, sl_pct, max_hold, pct_chg_low/high, a_condition
   - ~30 trials, outputs short_reversal/results/grid/grid_v3_p3p5fix.csv
   - 0 references to deflated_sharpe_ratio / bonferroni / dna_stats.deflated
   - CLAUDE.md §5 explicitly forbids this pattern
   - Glob test coverage: existing test_sweep_scripts_dsr.py uses
     **/sweep*.py + **/wf_sweep*.py — MISSES **/grid*.py

B. **short_reversal/walkforward.py — STANDALONE, semantic drift from core**:
   - short_reversal/walkforward.py:29-50 `build_windows` — uses
     `pd.Timestamp(start)` as initial cur, then rolls by `window_months`.
     Day-of-month preserved from input start.
   - core/walkforward.py:73-102 `monthly_windows` — uses `(cur_y, cur_m)`
     and constructs dates from year/month components. Day-of-month = 01.
   - Same intent, different implementation, DIFFERENT dates generated.

C. **cycle_price_action has NO WFV or DSR for single preset**:
   - cycle_price_action/walkforward.py is just a re-export of core
   - No sweep/grid runner. Cycle strategy parameters are taken from
     PRESET_V1 default dict. No parameter sweep at all → §5 vacuously
     satisfied for cycle BUT no parameter robustness check either.
"""
from __future__ import annotations

import re
from pathlib import Path


def test_short_reversal_grid_runner_has_dsr_call() -> None:
    """§5 RED: grid_runner.py must compute DSR, not just raw Sharpe.

    Per §5, any multi-trial sweep must report DSR (or Bonferroni) to
    correct for selection bias. grid_runner.py runs ~30 trials and
    outputs raw Sharpe/CAGR with NO penalty metric.

    This test:
      (1) pin that grid_runner.py exists (matches **/grid*.py glob)
      (2) pin that it MUST call `deflated_sharpe_ratio(` (not just import)
    """
    path = Path("short_reversal/grid_runner.py")
    assert path.exists(), "grid_runner.py not found — verify path"
    src = path.read_text(encoding="utf-8")

    # GREEN requirement: actually CALL deflated_sharpe_ratio
    has_dsr_call = bool(re.search(r"deflated_sharpe_ratio\s*\(", src))
    assert has_dsr_call, (
        "GAP CAPTURED: short_reversal/grid_runner.py — §5 violation. "
        "Loops over tp_pct/sl_pct/max_hold/pct_chg_low_high/a_condition "
        "axes (~30 trials) but NEVER calls deflated_sharpe_ratio. "
        "Selection-bias uncorrected. GREEN fix: import dna_stats.deflated, "
        "compute DSR over all trial sharpes, log p-value. "
        "OR refactor to use WFV (walkforward_windows from core)."
    )


def test_short_reversal_grid_runner_has_walkforward() -> None:
    """§5 RED: grid_runner must use WFV, not in-sample grid.

    §5 Banned In-Sample Grids: simple grid-search returning best
    params by max Sharpe is forbidden. Must split train/test (OOS).
    """
    path = Path("short_reversal/grid_runner.py")
    assert path.exists()
    src = path.read_text(encoding="utf-8")

    has_wfv = "walkforward" in src.lower() or "WalkForward" in src or "core.walkforward" in src
    assert has_wfv, (
        "GAP CAPTURED: short_reversal/grid_runner.py — §5 Banned In-Sample "
        "Grid. Loops over 30 param configs and selects by max Sharpe on "
        "the SAME in-sample data. Must split train/test via "
        "core.walkforward.walkforward_windows() or "
        "core.walkforward.monthly_windows()."
    )


def test_sweep_dsr_test_coverage_catches_grid_runner() -> None:
    """§5 Test coverage: existing sweep DSR test must extend glob to catch
    grid_runner.py and any other IS-grid scripts.

    Currently `tests/test_sweep_scripts_dsr.py` globs `**/sweep*.py` +
    `**/wf_sweep*.py` — misses `**/grid*.py`. A script that runs an
    IS grid under a different name would pass the existing test.
    """
    test_path = Path("tests/test_sweep_scripts_dsr.py")
    if not test_path.exists():
        return  # Skip if test file removed
    src = test_path.read_text(encoding="utf-8")

    has_grid_glob = bool(re.search(r"\*\*?/grid\*?\.py", src))
    assert has_grid_glob, (
        "GAP CAPTURED: tests/test_sweep_scripts_dsr.py — glob misses "
        "**/grid*.py. short_reversal/grid_runner.py (real §5 IS grid) "
        "evades detection. GREEN fix: extend glob to **/grid*.py."
    )


def test_short_reversal_walkforward_uses_core() -> None:
    """§5 RED: short_reversal/walkforward.py must use core/walkforward.

    Currently short_reversal/walkforward.py has its own `build_windows`
    function with semantic drift from core/walkforward.py:
      - short_reversal: preserves day-of-month from input start
      - core.monthly_windows: forces day = 01
    Two parallel implementations → bug surface, divergence risk.
    """
    path = Path("short_reversal/walkforward.py")
    if not path.exists():
        return
    src = path.read_text(encoding="utf-8")

    uses_core = "from core.walkforward import" in src
    has_own_build_windows = bool(re.search(r"^def build_windows\(", src, re.MULTILINE))

    assert uses_core or not has_own_build_windows, (
        "GAP CAPTURED: short_reversal/walkforward.py — has own "
        "build_windows() with semantic drift from core/walkforward.py "
        "(day-of-month preservation differs). GREEN fix: re-export "
        "from core.walkforward.monthly_windows to share single source."
    )


def test_cycle_has_wfv_runner_or_documents_absence() -> None:
    """§5 cycle_price_action: must have WFV runner OR documented reason.

    cycle_price_action only has walkforward.py (re-export). No sweep/grid
    runner exists. §5 mandates WFV for any parameter exploration.
    Cycle has multiple strategy params (threshold, min_dim, atr_period,
    atr_sl_mult) but no robustness check.
    """
    sweep_files = list(Path("cycle_price_action").glob("sweep*.py"))
    grid_files = list(Path("cycle_price_action").glob("grid*.py"))
    wf_files = list(Path("cycle_price_action").glob("walkforward*.py"))

    assert len(sweep_files) > 0 or len(grid_files) > 0, (
        "GAP CAPTURED: cycle_price_action has no sweep/grid runner. "
        "Strategy has 5+ tunable params but no parameter robustness "
        "check. §5 mandates WFV for any non-default param config. "
        "GREEN fix: add cycle_price_action/walkforward_sweep.py that "
        "runs WFV over (threshold, min_dim, atr_sl_mult) and reports "
        "DSR per window."
    )
    assert len(wf_files) > 0, "cycle_price_action must keep walkforward.py"