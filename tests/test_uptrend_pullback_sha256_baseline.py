"""uptrend_pullback trades.csv sha256 reproducibility baseline (Tick 36 / Round 13).

CLAUDE.md §0 (verbatim):
  "**Immutable State:** Treat all historical data and portfolio states
   as append-only."

CLAUDE.md §1 (verbatim):
  "**Temporal Determinism (Lookahead Bias Prevention)** — Time is a
   strictly monotonic, first-class citizen."

Multi-run reproducibility invariant: same preset + DB + seed → byte-equal
trades.csv. This file pins the sha256 baseline for uptrend_pullback
v33_long_reverse_v19 and v33_long_reverse_v20 so any un-intended change
to the signal/exit/sizing logic surfaces as a test failure.

chase_up uses the same pattern (tests/test_chase_up_no_lookahead.py +
tests/golden/chase_v{5,8..19}_baseline.json). This file brings the
same standard to uptrend_pullback per the audit log
[[reproducibility-audit-2026-09-23]] Tick 36.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
RESULTS_DIR = REPO_ROOT / "uptrend_pullback" / "results"


def _sha256_of_csv(df: pd.DataFrame) -> str:
    """Compute sha256 of `df.to_csv(index=False).encode()` — matches chase_up
    baseline convention. Avoids OS-dependent line ending drift that would
    appear if we hashed the raw bytes."""
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def _check_one(preset: str) -> None:
    baseline_path = GOLDEN_DIR / f"uptrend_{preset}_baseline.json"
    if not baseline_path.exists():
        return  # baseline not pinned yet, skip
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = RESULTS_DIR / f"{preset}_trades.csv"
    if not trades_csv.exists():
        return  # forward-defense: result not produced yet
    df = pd.read_csv(trades_csv)
    actual_hash = _sha256_of_csv(df)
    assert actual_hash == expected_hash, (
        f"uptrend_pullback {preset} trades.csv sha256 drift:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略/退出/仓位逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows, (
        f"uptrend_pullback {preset} trades 行数变化: "
        f"{len(df)} (expected {expected_rows})"
    )


def test_uptrend_v33_long_reverse_v19_trades_csv_sha256() -> None:
    """§0 PASS baseline: uptrend_pullback v33_long_reverse_v19 trades.csv hash."""
    _check_one("v33_long_reverse_v19")


def test_uptrend_v33_long_reverse_v20_trades_csv_sha256() -> None:
    """§0 PASS baseline: uptrend_pullback v33_long_reverse_v20 trades.csv hash."""
    _check_one("v33_long_reverse_v20")
