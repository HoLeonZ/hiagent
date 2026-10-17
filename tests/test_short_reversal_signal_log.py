"""Signal bypass log: a read-only per-bar outlet from the real strategy.

The log is how the live signal job (Task 6) reads what the engine decided,
without re-implementing the panel, the eight custom indicator classes, or the
condition layer (§6). This file locks three properties: the hook is INERT when
unused, the log is COMPLETE with respect to the trades the engine took, and
ensemble entries are attributed to the leg that produced them.

Skips (not errors) when the local DuckDB is absent — CLAUDE.md §6.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from hiagent_config import get_db_path

PRESET = "v50_slope"
ENSEMBLE = "v63_ensemble"
START, END, MIN_BARS = "2025-09-12", "2026-09-12", 150


@pytest.fixture(scope="module")
def db_path() -> Path:
    db = get_db_path()
    if not db.exists():
        pytest.skip(f"local DuckDB not present at {db} (§6: skip, do not error)")
    return db


@pytest.fixture(scope="module")
def plain_run(db_path: Path) -> dict:
    """One run of the plain preset with no log attached."""
    from short_reversal.engine import run_backtest_v3
    return run_backtest_v3(PRESET, START, END, db_path, min_bars=MIN_BARS)


@pytest.fixture(scope="module")
def logged_run(db_path: Path) -> tuple[dict, list]:
    """One run of the same preset with a log attached."""
    from short_reversal.engine import run_backtest_v3
    log: list = []
    m = run_backtest_v3(PRESET, START, END, db_path, min_bars=MIN_BARS,
                        signal_log=log)
    return m, log


@pytest.fixture(scope="module")
def ensemble_log(db_path: Path) -> list:
    """One ensemble run; legs share the list and must be attributed."""
    from short_reversal.engine import run_backtest_v3
    log: list = []
    run_backtest_v3(ENSEMBLE, START, END, db_path, min_bars=MIN_BARS,
                    signal_log=log)
    return log


def test_log_hook_is_inert_when_unused(plain_run: dict, logged_run: tuple):
    """§0: a diagnostic outlet must not perturb the run."""
    m, log = logged_run
    assert log, "the hook produced no entries — it is not wired through"
    assert plain_run["trades"] == m["trades"], "the signal log perturbed the run"
    assert plain_run["final_capital"] == m["final_capital"]
    assert plain_run["max_dd"] == m["max_dd"]


def test_every_fill_has_a_logged_signal_bar_before_it(logged_run: tuple):
    """The engine's `entry_date` is the T+1 FILL date (replay_strategy_v3.py:795),
    not the signal date. Each fill must have a passed=True entry on the last bar
    of that stock strictly before the fill."""
    m, log = logged_run
    passed_by_code: dict[str, list] = {}
    for e in log:
        if e["passed"]:
            passed_by_code.setdefault(e["thscode"], []).append(e["date"])

    trades = m["trades"]
    assert trades, (
        "the engine took ZERO trades on this window — the check would be "
        "vacuous. Do NOT let it pass on an empty trade list."
    )
    missing = []
    for t in trades:
        code, fill = t["thscode"], t["entry_date"]
        earlier = [d for d in passed_by_code.get(code, []) if d < fill]
        if not earlier:
            missing.append((code, fill))
    assert not missing, (
        f"{len(missing)} fills have no passed signal bar before them — the log "
        f"is incomplete or the condition layer diverged. Sample: {missing[:5]}"
    )


def test_passed_and_failed_at_are_consistent(logged_run: tuple):
    """`failed_at is None` exactly when `passed` is True — the two fields come
    from one ConditionResult and must never disagree."""
    _, log = logged_run
    assert log
    bad = [e for e in log if e["passed"] != (e["failed_at"] is None)]
    assert not bad, f"{len(bad)} inconsistent entries, e.g. {bad[:3]}"


def test_log_covers_the_buffered_panel_not_just_the_window(logged_run: tuple):
    """The engine sets no feed.fromdate/todate, so it evaluates the whole panel
    `[start-180d, end+60d]`. The log inherits that span — assert it is wide,
    NOT that it is bounded by [START, END]."""
    _, log = logged_run
    dates = sorted({e["date"] for e in log})
    assert dates[0] <= dt.date.fromisoformat(START)
    assert dates[-1] >= dt.date.fromisoformat(END)


def test_ensemble_log_entries_carry_the_leg_name(ensemble_log: list):
    """Each ensemble leg runs its own run_backtest_v3(name, ...) and they share
    one log list. Without a per-entry leg tag, two legs that both pass on the
    same (thscode, date) collapse into one signal, and the per-leg capital split
    (INITIAL_CAPITAL / n) is wrong by a factor of n."""
    assert ensemble_log, "ensemble produced no log entries"
    tags = {e["preset"] for e in ensemble_log}
    assert tags == {"v50_slope", "v44_ratio02_buf07"}, (
        f"expected exactly one tag per v63_ensemble leg, got {sorted(tags)}"
    )


def test_plain_run_log_is_tagged_with_the_preset_name(logged_run: tuple):
    """A non-ensemble run tags every entry with the preset it was called with."""
    _, log = logged_run
    assert {e["preset"] for e in log} == {PRESET}
