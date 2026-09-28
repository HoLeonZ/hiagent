"""cycle_price_action trades.csv sha256 reproducibility baseline (Tick 36 / Round 13).

CLAUDE.md §0 (verbatim):
  "**Immutable State:** Treat all historical data and portfolio states
   as append-only."

CLAUDE.md §1 (verbatim):
  "**Temporal Determinism (Lookahead Bias Prevention)** — Time is a
   strictly monotonic, first-class citizen."

Per [[reproducibility-audit-2026-09-23]] Tick 36 and
[[fail-fast-cycle-hot-path]] Round 12: cycle_price_action currently
produces NO trades.csv because the fail-fast guard at
cycle_price_action/backtest.py:86 raises before cerebro.run().

This file is a forward-defense baseline: it MUST pin a sha256 of any
future trades.csv the engine emits. chase_up and uptrend_pullback
already have their baselines (see tests/test_chase_up_no_lookahead.py
and tests/test_uptrend_pullback_sha256_baseline.py).

When cycle_price_action starts producing trades.csv:
  1. Run the engine to produce the canonical trades.csv
  2. Compute sha256 of `df.to_csv(index=False).encode()` (matches
     chase_up + uptrend_pullback baseline convention — avoids OS-
     dependent line ending drift)
  3. Pin the hash in tests/golden/cycle_<preset>_baseline.json
  4. Add a parametrized test here that asserts match
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
RESULTS_DIR = REPO_ROOT / "cycle_price_action" / "results"


def _baseline_paths() -> list[Path]:
    """All pinned cycle_price_action baselines under tests/golden/."""
    if not GOLDEN_DIR.exists():
        return []
    return sorted(GOLDEN_DIR.glob("cycle_*_baseline.json"))


def test_cycle_price_action_has_pinned_baseline_files() -> None:
    """§0 forward-defense: cycle_price_action baselines must exist.

    Currently this test RED-fails when no cycle_*_baseline.json exists,
    which is the documented gap from Tick 36. Once the engine produces
    output, this becomes the §0 PASS baseline guard.
    """
    paths = _baseline_paths()
    assert paths, (
        "GAP CAPTURED: cycle_price_action has NO pinned trades.csv "
        "sha256 baseline. Per [[reproducibility-audit-2026-09-23]] "
        "Tick 36 + [[fail-fast-cycle-hot-path]]: once the engine "
        "starts emitting trades.csv, compute sha256 and pin it under "
        "tests/golden/cycle_<preset>_baseline.json. This test exists "
        "as the forward-defense guard."
    )


def _check_one(preset: str) -> None:
    """Assert trades.csv hash matches the pinned baseline, if output exists.

    Skips silently if trades.csv not yet produced (forward-defense).
    """
    baseline_path = GOLDEN_DIR / f"cycle_{preset}_baseline.json"
    if not baseline_path.exists():
        return
    import json

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = RESULTS_DIR / f"{preset}_trades.csv"
    if not trades_csv.exists():
        return  # forward-defense: result not produced yet
    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()
    assert actual_hash == expected_hash, (
        f"cycle_price_action {preset} trades.csv sha256 drift:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})"
    )
    assert len(df) == expected_rows


def _parametrized_placeholder_test() -> None:
    """Forward-defense: when baselines exist, run all of them.

    Currently a no-op because no baseline files exist. Will become
    parametrized over all `cycle_*_baseline.json` files once output is
    produced. Stub kept to document the intended pattern.
    """
    for baseline_path in _baseline_paths():
        preset = baseline_path.stem.replace("cycle_", "").replace("_baseline", "")
        _check_one(preset)
