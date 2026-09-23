"""§5 DSR sweep contract cross-engine audit (Tick 47).

CLAUDE.md §5 铁律 (verbatim):
  "Penalty Metrics: Evaluation scripts must output Deflated Sharpe Ratio
   (DSR) or apply Bonferroni corrections when reporting backtest results
   from multi-parameter sweeps."

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[sweep-contract-test-coverage-gap]]:**

A. **Existing test_sweep_scripts_dsr.py glob gap** (verified):
   - glob patterns: `**/sweep*.py` + `**/wf_sweep*.py`
   - catches 9 scripts: 3 chase_up + 6 uptrend_pullback (all have DSR)
   - **MISSES** 17 sweep-like scripts in short_reversal + cycle_price_action

B. **short_reversal has 15 sweep-like scripts with ZERO DSR**:
   - short_reversal/grid_runner.py — IS-grid (per memory [[wfv-rigor-cross-engine-gap]])
   - short_reversal/walkforward.py — walkforward runner (semantic drift per memory)
   - short_reversal/wf_v34_focused.py through wf_v46_focused.py (13 files)
   - 15/15 scripts: `dna_stats.deflated` import: ABSENT
   - 15/15 scripts: `deflated_sharpe_ratio`/`bonferroni_correct` reference: ABSENT

C. **cycle_price_action has 2 sweep-like scripts with ZERO DSR**:
   - cycle_price_action/walkforward.py
   - cycle_price_action/main.py (sweep-like backtest runner)
   - 2/2 scripts: `dna_stats.deflated` import: ABSENT

D. **Consequence**:
   - All 17 scripts run multi-parameter sweeps and report raw Sharpe
   - Without DSR/Bonferroni, selection bias from sweep trials inflates
     reported Sharpe (per CLAUDE.md §5: p-hacking facilitation)
   - **17 sweep runners violate §5 penalty metrics mandate**

E. **Why existing test misses this**:
   - test_sweep_scripts_dsr.py:30-37 glob patterns hardcode `sweep*` /
     `wf_sweep*` prefixes
   - short_reversal/grid_runner.py + walkforward.py use `grid_*` /
     `walkforward.py` prefixes — NOT matched
   - short_reversal/wf_v34_focused.py through wf_v46_focused.py use
     `wf_v*_focused.py` pattern — NOT matched (prefix is `wf_v` not
     `wf_sweep`)
   - cycle_price_action/walkforward.py + main.py use `walkforward.py`
     + `main.py` prefixes — NOT matched

F. **Numeric impact**:
   - short_reversal: ~30 grid trials × 13 walkforward focused variants
     = ~390 sweep runs without DSR correction
   - cycle_price_action: 2 sweep runners without DSR
   - Total: 17 scripts × N trials each = potentially hundreds of
     under-corrected Sharpe reports

本文件验证:
- 3 RED: short_reversal/grid_runner.py, short_reversal/walkforward*.py (15),
  cycle_price_action/walkforward.py + main.py (2) all lack DSR
- 2 PASS baseline: dna_stats/deflated.py module exists + 9 existing glob-matched
  scripts (chase_up + uptrend_pullback) have DSR
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# RED: short_reversal sweep-like scripts missing DSR
# ---------------------------------------------------------------------------


# Tick 47 inventory: 15 short_reversal scripts
SHORT_REVERSAL_SWEEP_LIKE = [
    "short_reversal/grid_runner.py",
    "short_reversal/walkforward.py",
    "short_reversal/wf_v34_focused.py",
    "short_reversal/wf_v35_focused.py",
    "short_reversal/wf_v36_focused.py",
    "short_reversal/wf_v37_focused.py",
    "short_reversal/wf_v38_focused.py",
    "short_reversal/wf_v39_focused.py",
    "short_reversal/wf_v40_focused.py",
    "short_reversal/wf_v41_focused.py",
    "short_reversal/wf_v42_focused.py",
    "short_reversal/wf_v43_focused.py",
    "short_reversal/wf_v44_focused.py",
    "short_reversal/wf_v45_focused.py",
    "short_reversal/wf_v46_focused.py",
]


@pytest.mark.parametrize("rel_path", SHORT_REVERSAL_SWEEP_LIKE,
                         ids=lambda p: p)
def test_short_reversal_sweep_like_script_has_dsr(rel_path: str) -> None:
    """§5 RED: short_reversal sweep-like scripts must reference dna_stats.deflated.

    Per CLAUDE.md §5, every multi-parameter sweep must output DSR or
    Bonferroni-corrected metrics. short_reversal/grid_runner.py runs a
    literal IS-grid (per [[wfv-rigor-cross-engine-gap]]); walkforward.py
    + 13 wf_v*_focused.py scripts run walkforward variants. None of the
    15 reference dna_stats.deflated.
    """
    path = REPO_ROOT / rel_path
    if not path.exists():
        return  # structure changed

    text = path.read_text(encoding="utf-8")
    has_dsr_import = (
        "from dna_stats.deflated" in text or
        "import dna_stats.deflated" in text
    )
    has_dsr_call = (
        "deflated_sharpe_ratio" in text or
        "bonferroni_correct" in text or
        "DSR" in text
    )

    if has_dsr_import or has_dsr_call:
        return  # GREEN

    raise AssertionError(
        f"GAP CAPTURED (RED): {rel_path} is a multi-parameter sweep runner "
        f"but does NOT reference dna_stats.deflated (DSR / Bonferroni). "
        f"CLAUDE.md §5 violation: every sweep must output Deflated Sharpe "
        f"Ratio or Bonferroni-corrected metrics.\n"
        f"Per [[sweep-contract-test-coverage-gap]], the existing "
        f"test_sweep_scripts_dsr.py glob (`sweep*.py` / `wf_sweep*.py`) "
        f"misses short_reversal scripts with `grid_*` / `walkforward.py` / "
        f"`wf_v*_focused.py` prefixes.\n"
        f"GREEN fix: add `from dna_stats.deflated import deflated_sharpe_ratio, "
        f"bonferroni_correct` import + use in results reporting.\n"
        f"Per [[wfv-rigor-cross-engine-gap]], short_reversal/grid_runner.py "
        f"is a literal IS-grid (30 trials) with 0 DSR — primary suspect."
    )


# ---------------------------------------------------------------------------
# RED: cycle_price_action sweep-like scripts missing DSR
# ---------------------------------------------------------------------------


CYCLE_SWEEP_LIKE = [
    "cycle_price_action/walkforward.py",
    "cycle_price_action/main.py",
]


@pytest.mark.parametrize("rel_path", CYCLE_SWEEP_LIKE, ids=lambda p: p)
def test_cycle_price_action_sweep_like_script_has_dsr(rel_path: str) -> None:
    """§5 RED: cycle_price_action sweep-like scripts must reference DSR.

    cycle_price_action/walkforward.py + main.py both run multi-parameter
    sweeps but neither references dna_stats.deflated.
    """
    path = REPO_ROOT / rel_path
    if not path.exists():
        return  # structure changed

    text = path.read_text(encoding="utf-8")
    has_dsr_import = (
        "from dna_stats.deflated" in text or
        "import dna_stats.deflated" in text
    )
    has_dsr_call = (
        "deflated_sharpe_ratio" in text or
        "bonferroni_correct" in text or
        "DSR" in text
    )

    if has_dsr_import or has_dsr_call:
        return  # GREEN

    raise AssertionError(
        f"GAP CAPTURED (RED): {rel_path} runs a sweep but does NOT "
        f"reference dna_stats.deflated. CLAUDE.md §5 violation.\n"
        f"GREEN fix: add DSR/Bonferroni import + use in reporting."
    )


# ---------------------------------------------------------------------------
# PASS baselines: DSR module exists + existing 9 glob-matched scripts
# ---------------------------------------------------------------------------


def test_dna_stats_deflated_module_exists() -> None:
    """§5 PASS baseline: dna_stats/deflated.py module exists.

    Pin compliance: DSR module is in place. If migration removes it,
    all 9 existing sweep scripts break.
    """
    path = REPO_ROOT / "dna_stats" / "deflated.py"
    assert path.exists(), (
        "Regression: dna_stats/deflated.py removed. CLAUDE.md §5 "
        "requires DSR module to exist for sweep reporting."
    )


EXISTING_DSR_COMPLIANT_SCRIPTS = [
    "chase_up/sweep.py",
    "chase_up/sweep_all.py",
    "chase_up/wf_sweep_all.py",
    "uptrend_pullback/sweep_v33_long.py",
    "uptrend_pullback/sweep_v33_long_v2.py",
    "uptrend_pullback/sweep_v33_long_v3.py",
    "uptrend_pullback/sweep_v33_long_v4.py",
    "uptrend_pullback/sweep_v33_long_v5.py",
    "uptrend_pullback/sweep_v33_long_v6.py",
]


@pytest.mark.parametrize("rel_path", EXISTING_DSR_COMPLIANT_SCRIPTS,
                         ids=lambda p: p)
def test_existing_sweep_script_has_dsr_pinned(rel_path: str) -> None:
    """§5 PASS baseline: 9 existing glob-matched sweep scripts have DSR.

    Per test_sweep_scripts_dsr.py glob, these 9 scripts are flagged as
    compliant. Pin baseline so regression is caught.
    """
    path = REPO_ROOT / rel_path
    if not path.exists():
        return  # structure changed

    text = path.read_text(encoding="utf-8")
    has_dsr = (
        "from dna_stats.deflated" in text or
        "import dna_stats.deflated" in text or
        "deflated_sharpe_ratio" in text or
        "bonferroni_correct" in text or
        "DSR" in text
    )
    assert has_dsr, (
        f"Regression: {rel_path} removed DSR reference. CLAUDE.md §5 "
        f"violation: every sweep must reference dna_stats.deflated."
    )