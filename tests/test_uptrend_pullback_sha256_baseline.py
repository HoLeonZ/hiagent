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

2026-10-13 (baseline hardening): the original version read
``uptrend_pullback/results/{preset}_trades.csv`` — a gitignored path — and
returned early when it was absent. In a clean checkout / CI it therefore
reported PASS while asserting nothing at all (§6 守卫形同虚设). It now recomputes
the trade list in-test and only skips when the local DuckDB is unavailable.
The pins were regenerated at the same time (see the ``repinned`` block in each
golden file for the drift justification and its attribution).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _sha256_of_csv(df: pd.DataFrame) -> str:
    """Compute sha256 of `df.to_csv(index=False).encode()` — matches chase_up
    baseline convention. Avoids OS-dependent line ending drift that would
    appear if we hashed the raw bytes."""
    return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()


def _regenerate_trades(preset: str, start: str, end: str) -> pd.DataFrame:
    """Recompute the simulate-engine trade list from preset + DB.

    Deliberately does NOT read ``uptrend_pullback/results/{preset}_trades.csv``:
    that directory is gitignored, so depending on it made this whole file vacuous
    in a clean checkout — it returned early and reported PASS while asserting
    nothing (§6 守卫形同虚设)。
    """
    from hiagent_config import DB_PATH as _DB
    from uptrend_pullback.backtest import run_backtest

    return run_backtest(preset, start, end, Path(_DB))["trades"]


def _check_one(preset: str) -> None:
    baseline_path = GOLDEN_DIR / f"uptrend_{preset}_baseline.json"
    if not baseline_path.exists():
        pytest.skip(f"baseline not pinned yet: {baseline_path.name}")

    from hiagent_config import DB_PATH as _DB
    if not Path(_DB).exists():
        pytest.skip(f"§6 baseline check 需要本机 DuckDB: {_DB}")

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    start, end = baseline["window"]
    df = _regenerate_trades(preset, start, end)
    actual_hash = _sha256_of_csv(df)

    assert actual_hash == baseline["trades_csv_sha256"], (
        f"uptrend_pullback {preset} trades.csv sha256 drift ({start}..{end}):\n"
        f"  expected: {baseline['trades_csv_sha256']}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {baseline['trades_csv_rows']})\n"
        f"  CLAUDE.md §6: 改变 trade list 的逻辑必须重新生成基线, "
        f"并在 PR 中说明漂移原因 ({baseline_path.name})。"
    )
    assert len(df) == baseline["trades_csv_rows"], (
        f"uptrend_pullback {preset} trades 行数变化: "
        f"{len(df)} (expected {baseline['trades_csv_rows']})"
    )
    assert list(df.columns) == baseline["trades_csv_cols"], (
        f"uptrend_pullback {preset} trades 列变化:\n"
        f"  expected: {baseline['trades_csv_cols']}\n"
        f"  actual:   {list(df.columns)}"
    )


def test_uptrend_v33_long_reverse_v19_trades_csv_sha256() -> None:
    """§0 PASS baseline: uptrend_pullback v33_long_reverse_v19 trades.csv hash."""
    _check_one("v33_long_reverse_v19")


def test_uptrend_v33_long_reverse_v20_trades_csv_sha256() -> None:
    """§0 PASS baseline: uptrend_pullback v33_long_reverse_v20 trades.csv hash."""
    _check_one("v33_long_reverse_v20")
