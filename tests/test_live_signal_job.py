"""Signal job: pure parts tested offline; DB parts skip when absent (§6)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from hiagent_config import get_db_path
from live.signal_job import (
    SignalRecord, append_record, assert_feeds_nonempty, load_records,
    panel_end_for_as_of,
)

AS_OF = "2026-10-16"


def test_assert_feeds_nonempty_raises_when_universe_fully_dropped():
    """F-01 defence: 'feed count 0' must never be conflated with 'no signal'."""
    with pytest.raises(ValueError, match="universe"):
        assert_feeds_nonempty(["600000.SH", "000001.SZ"], [])


def test_assert_feeds_nonempty_allows_empty_universe():
    assert assert_feeds_nonempty([], []) is None


def test_panel_end_lands_exactly_on_the_as_of_date():
    """run_backtest_v3 loads [start-180d, end+60d], so passing end=signal_date
    would load 60 days of FUTURE data. The job must pass
    end = signal_date - PANEL_POST_BUFFER_DAYS, and must express it via the
    constant so that a change to the constant cannot silently reintroduce
    lookahead."""
    from short_reversal._panel_loader import PANEL_POST_BUFFER_DAYS

    assert panel_end_for_as_of(AS_OF) == (
        pd.Timestamp(AS_OF) - pd.Timedelta(days=PANEL_POST_BUFFER_DAYS)
    ).strftime("%Y-%m-%d")


def test_append_record_is_idempotent_on_same_signal_id(tmp_path: Path):
    rec = SignalRecord(
        signal_id="2026-10-16|v50_slope", signal_date="2026-10-16",
        preset="v50_slope", leg="v50_slope", candidates=[],
        universe_size=3190, engine_git_sha="deadbeef",
        n_trials_at_generation=78, as_of_time="2026-10-16",
    )
    p = tmp_path / "signals.jsonl"
    assert append_record(p, rec) is True
    assert append_record(p, rec) is False, "duplicate signal_id must be rejected, not appended"
    assert len(load_records(p)) == 1


def test_append_record_keeps_two_dates(tmp_path: Path):
    p = tmp_path / "signals.jsonl"
    for d in ("2026-10-15", "2026-10-16"):
        append_record(p, SignalRecord(
            signal_id=f"{d}|v50_slope", signal_date=d, preset="v50_slope",
            leg="v50_slope", candidates=[], universe_size=1,
            engine_git_sha="x", n_trials_at_generation=78,
            as_of_time=d))
    assert [r.signal_date for r in load_records(p)] == ["2026-10-15", "2026-10-16"]


def test_load_records_on_missing_file_returns_empty(tmp_path: Path):
    assert load_records(tmp_path / "nope.jsonl") == []


def test_run_signal_job_uses_the_universe_as_of_the_signal_date():
    """The job must resolve the universe as-of signal_date, NOT as-of
    panel_start (= signal_date - 400d).

    run_backtest_v3 defaults `universe_as_of` to `start`, and load_universe_asof
    means "first appearance <= as-of". Using the default therefore drops every
    stock listed in the 400 days before the signal date — measured at 36 names
    (1.13%) for T=2026-10-16, and they are precisely the recently-listed cohort.
    That narrowing is an artifact of the panel arithmetic, not a strategy rule,
    so the job must override it.
    """
    db = get_db_path()
    if not db.exists():
        pytest.skip(f"local DuckDB not present at {db} (§6: skip, do not error)")

    from short_reversal.universe import load_universe_asof
    from live.signal_job import run_signal_job
    import tempfile

    expected = len(load_universe_asof("mainboard_only", AS_OF, db))
    with tempfile.TemporaryDirectory() as td:
        rec = run_signal_job(preset="v50_slope", signal_date=AS_OF, db_path=db,
                             state_dir=Path(td), as_of_time=AS_OF)
    assert rec is not None
    assert rec.universe_size == expected, (
        f"universe_size={rec.universe_size} but as-of-{AS_OF} is {expected} — "
        f"the job fell back to the as-of-panel_start universe"
    )


def test_run_signal_job_never_reads_a_row_after_the_as_of():
    """End-to-end §1 check: the engine sees no bar after signal_date, so the
    signal set for that date cannot depend on the future."""
    db = get_db_path()
    if not db.exists():
        pytest.skip(f"local DuckDB not present at {db} (§6: skip, do not error)")

    from live.signal_job import run_signal_job
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        rec = run_signal_job(preset="v50_slope", signal_date=AS_OF, db_path=db,
                             state_dir=Path(td), as_of_time=AS_OF)
    assert rec is not None
    assert all(c["date"] <= date.fromisoformat(AS_OF) for c in rec.candidates), (
        "a candidate dated after the as-of means the panel end was miscomputed"
    )
