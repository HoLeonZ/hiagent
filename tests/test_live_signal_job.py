"""Signal job: pure parts tested offline; DB parts skip when absent (§6)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from hiagent_config import get_db_path
from live.signal_job import (
    SignalRecord, append_record, assert_feeds_nonempty, load_records,
    panel_end_for_as_of, panel_start_for,
)

AS_OF = "2026-10-16"


def test_assert_feeds_nonempty_raises_when_universe_fully_dropped():
    """F-01 defence: 'feed count 0' must never be conflated with 'no signal'."""
    with pytest.raises(ValueError, match="universe"):
        assert_feeds_nonempty(["600000.SH", "000001.SZ"], [])


def test_the_empty_usable_message_names_all_three_possible_causes():
    """An empty `usable` has three causes and they point at different
    investigations. All raise, so the message is what tells an operator which to
    chase — and the third is the most common misuse: this job does NOT check the
    calendar, so running it on a non-trading day yields an empty log for that
    date while the universe is still non-empty.

    The third clause is easy to lose when the message is reworded (this plan's
    first revision omitted it), so pin all three phrases.
    """
    with pytest.raises(ValueError) as ei:
        assert_feeds_nonempty(["600000.SH"], [])
    msg = str(ei.value)
    assert "min_bars" in msg
    assert "require_market_breadth_bear" in msg
    assert "trading day" in msg


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


def test_every_ensemble_has_a_uniform_leg_universe():
    """The job resolves `universe_size` and the F-01 guard from the ENSEMBLE
    preset's own `universe`, not per leg. That is correct only while every leg
    of an ensemble declares the same universe — so assert it rather than assume
    it. A future ensemble mixing leg universes would report a `universe_size` no
    leg actually used, and gate against the wrong list, with nothing failing.

    Iterate the LIBRARY, not a hardcoded list of the three candidates: a fourth
    ensemble added later is precisely the failure this docstring describes, and
    a literal list would let it slip through the very test written to catch it.
    """
    from short_reversal.presets import PRESETS

    ensembles = sorted(n for n, c in PRESETS.items() if "ensemble_substrategies" in c)
    assert ensembles, "no ensembles in the library — its shape changed unexpectedly"
    for name in ensembles:
        outer = PRESETS[name]["universe"]
        leg_modes = {
            PRESETS[leg]["universe"]
            for leg in PRESETS[name]["ensemble_substrategies"]
        }
        assert leg_modes == {outer}, (
            f"{name}: legs declare {sorted(leg_modes)} but the preset declares "
            f"{outer!r} — the job's universe_size would describe a universe no "
            f"leg used"
        )


@pytest.fixture
def job_run(monkeypatch):
    """Run the job once, exposing the engine's UNFILTERED signal log.

    `run_signal_job` filters the log to `date == as_of` BEFORE building
    `candidates` (live/signal_job.py), so the returned record can never expose a
    future-dated row: asserting anything over `rec.candidates` degrades to
    `x <= x` and is vacuous when there are no candidates. To check §1 at all we
    must see the whole log the engine produced. Wrap
    `live.signal_job.run_backtest_v3` (which the job imported by name) to stash
    the `signal_log` list it was handed, then delegate to the real engine.

    Returns a dict: `rec` (the job's record), `log` (the raw engine log),
    `start` / `end` / `kwargs` (what the job actually passed the engine).
    """
    db = get_db_path()
    if not db.exists():
        pytest.skip(f"local DuckDB not present at {db} (§6: skip, do not error)")

    import tempfile

    import short_reversal.engine as engine_mod
    from live.signal_job import run_signal_job

    captured: dict = {}
    real = engine_mod.run_backtest_v3

    def spy(preset, start, end, db_path, **kwargs):
        captured["start"], captured["end"] = start, end
        captured["kwargs"] = kwargs
        try:
            return real(preset, start, end, db_path, **kwargs)
        finally:
            # `signal_log` is the SAME list the strategy appends to during the
            # run, so after `real` returns it is fully populated.
            captured["log"] = kwargs["signal_log"]

    monkeypatch.setattr("live.signal_job.run_backtest_v3", spy)

    with tempfile.TemporaryDirectory() as td:
        rec = run_signal_job(preset="v50_slope", signal_date=AS_OF, db_path=db,
                             state_dir=Path(td), as_of_time=AS_OF)
    captured["rec"] = rec
    return captured


def test_run_signal_job_uses_the_universe_as_of_the_signal_date(job_run):
    """The job must resolve the universe as-of signal_date, NOT as-of
    panel_start (= signal_date - 400d).

    run_backtest_v3 defaults `universe_as_of` to `start`, and load_universe_asof
    means "first appearance <= as-of". Using the default therefore drops every
    stock listed in the 400 days before the signal date — measured at 36 names
    (.001220.SZ and 35 others) for T=2026-10-16, and they are precisely the
    recently-listed cohort.

    `rec.universe_size` alone does NOT catch a regression here: the job computes
    it from its OWN `load_universe_asof(mode, signal_date, ...)` call, which is
    independent of the `universe_as_of` it hands the engine. So this test ALSO
    pins the log's distinct `thscode` set against what the engine actually saw —
    the recently-listed names exist only in the as-of-signal_date universe, so
    excluding them (the mutation) empties the intersection below.
    """
    from short_reversal.universe import load_universe_asof

    db = get_db_path()
    rec = job_run["rec"]
    assert rec is not None
    expected = len(load_universe_asof("mainboard_only", AS_OF, db))
    assert rec.universe_size == expected, (
        f"universe_size={rec.universe_size} but as-of-{AS_OF} is {expected} — "
        f"the job fell back to the as-of-panel_start universe"
    )

    # Behavioural pin: the engine must have SEEN the as-of-signal_date universe.
    universe_signal = set(load_universe_asof("mainboard_only", AS_OF, db))
    universe_panel = set(
        load_universe_asof("mainboard_only", panel_start_for(AS_OF), db)
    )
    recent = universe_signal - universe_panel
    assert recent, (
        "fixture sanity: expected names listed after panel_start — without them "
        "this test pins nothing"
    )
    log_codes = {e["thscode"] for e in job_run["log"]}
    assert recent & log_codes, (
        f"none of the {len(recent)} names listed after panel_start appeared in "
        f"the engine's log — the job resolved the universe as-of panel_start "
        f"(run_backtest_v3's default) instead of signal_date"
    )


def test_run_signal_job_never_reads_a_row_after_the_as_of(job_run):
    """End-to-end §1 check on the UNFILTERED log: the engine produced no row
    dated after signal_date, so the signal set for that date cannot depend on
    the future.

    The old form asserted over `rec.candidates`, which `run_signal_job` has
    already filtered to `date == as_of` — a tautology (`x <= x`), and vacuous
    when there are no candidates. The raw log is the honest witness. This is what
    catches the `panel_end_for_as_of` regression (returning signal_date
    unchanged): run_backtest_v3 then loads 60 days of FUTURE bars, which changes
    the log rows (different stocks clear min_bars) with `signals.jsonl` still
    looking normal.
    """
    as_of = date.fromisoformat(AS_OF)
    log = job_run["log"]
    assert log, "non-vacuity: the engine produced no log rows at all"
    latest = max(e["date"] for e in log)
    assert latest <= as_of, (
        f"the engine logged a row dated {latest} after the as-of {as_of} — the "
        f"panel end was miscomputed. run_backtest_v3 loads [start-180d, end+60d], "
        f"so the job must pass end = signal_date - PANEL_POST_BUFFER_DAYS"
    )
