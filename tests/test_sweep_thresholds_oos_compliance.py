"""§5 WFV OOS Compliance for cycle_price_action/sweep_thresholds.py (Round 24).

CLAUDE.md §5 WFV mandate:
  - walkforward_windows returns WalkForwardWindow(train_start, train_end,
    test_start, test_end) with train_end < test_start (OOS).
  - Any sweep using these windows MUST evaluate on the TEST half, else
    the WFV contract is silently violated and reported numbers are
    in-sample (defeats walkforward's entire purpose).

Pre-fix (Round 24, 2026-09-28): sweep_thresholds.py:40-41 passed
start=w.train_start, end=w.train_end — pure in-sample. Sweep reports
labeled as WFV+DSR+Bonferroni were in-sample + multi-trial corrected
(correction cannot save an in-sample metric).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.walkforward import WalkForwardWindow, walkforward_windows
from cycle_price_action import sweep_thresholds


# ---------------------------------------------------------------------------
# Pure RED: walkforward_windows must produce windows with train_end < test_start
# (this is the data contract; sweep_thresholds must consume test_*).
# ---------------------------------------------------------------------------


def test_walkforward_windows_train_end_strictly_lt_test_start() -> None:
    """§5: train_end < test_start invariant (out-of-sample)."""
    windows = walkforward_windows(date(2024, 1, 1), date(2026, 9, 1))
    assert len(windows) >= 1
    for w in windows:
        assert w.train_end < w.test_start, (
            f"§5 violation: train_end={w.train_end} >= test_start={w.test_start}"
        )


def test_sweep_thresholds_calls_run_backtest_with_test_window() -> None:
    """§5 RED→GREEN: sweep_thresholds must pass test_start/test_end to run_backtest.

    Mock walkforward_windows to return a single deterministic window so
    we can assert exactly which (start, end) are forwarded to run_backtest.
    Without the fix, this test fails because (start, end) = (train_start,
    train_end) (in-sample). With the fix, (start, end) = (test_start,
    test_end) (OOS).
    """
    fixed_window = WalkForwardWindow(
        train_start=date(2024, 1, 1),
        train_end=date(2024, 12, 31),
        test_start=date(2025, 1, 1),
        test_end=date(2025, 12, 31),
    )

    captured: list[tuple[str, str]] = []

    def fake_run_backtest(*, db_path, start, end, cash, preset):
        captured.append((str(start), str(end)))
        from types import SimpleNamespace
        return SimpleNamespace(metrics={"sharpe": 0.5, "total_pnl": 100.0})

    with patch.object(sweep_thresholds, "walkforward_windows",
                       return_value=[fixed_window]), \
         patch.object(sweep_thresholds, "run_backtest", side_effect=fake_run_backtest):
        sweep_thresholds._sweep_one_threshold(
            threshold=2.0,
            windows=[fixed_window],
            db_path=":memory:",
            cash=1_000_000,
        )

    assert captured == [("2025-01-01", "2025-12-31")], (
        f"§5 WFV violation: sweep_thresholds must call run_backtest with "
        f"test_start/test_end (OOS). Got {captured} — "
        f"train_* (in-sample) makes WFV a no-op."
    )


def test_sweep_thresholds_wfv_docstring_honored() -> None:
    """§5: docstring claims 'Walk-Forward Validation'; behavior must match.

    Static check that the source file references test_start/test_end in the
    run_backtest call site (not train_start/train_end). Direct text scan
    because the file is small and the contract is one line.
    """
    src = Path(sweep_thresholds.__file__).read_text()
    # Find lines inside _sweep_one_threshold that pass start=/end= to run_backtest.
    # The line must reference w.test_start and w.test_end, not w.train_start.
    assert "w.test_start" in src and "w.test_end" in src, (
        "§5: sweep_thresholds source must reference w.test_start / "
        "w.test_end in the run_backtest call site (OOS)."
    )
    # And must NOT pass train_* to run_backtest (would be in-sample).
    sweep_block = src[src.index("def _sweep_one_threshold"):src.index("def main")]
    assert "w.train_start" not in sweep_block, (
        "§5: _sweep_one_threshold must NOT use w.train_start — "
        "that's in-sample, defeating WFV."
    )
    assert "w.train_end" not in sweep_block, (
        "§5: _sweep_one_threshold must NOT use w.train_end — "
        "that's in-sample, defeating WFV."
    )