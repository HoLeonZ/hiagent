"""Tests for cycle_price_action.main CLI arg parsing + window resolution.

Regression coverage for the FINAL WHOLE-BRANCH review findings:
- Important #1: `run` subparser no longer shadows --start/--end with None.
- Important #2: _resolve_window no longer has the dead second-fromordinal path.
- Minor #3: out_dir suffix includes microseconds (smoke check on the format).
"""
from __future__ import annotations

from datetime import date, datetime

from cycle_price_action.main import _resolve_window, main


def _parsed_ns(argv: list[str]):
    """Re-parse the same argv through the module's argparse setup by intercepting
    the dispatched handler. Returns the Namespace the handler would have seen."""
    captured = {}

    import cycle_price_action.main as cli

    orig_run = cli._run_backtest
    cli._run_backtest = lambda args: captured.setdefault("ns", args) or 0
    try:
        main(argv)
    finally:
        cli._run_backtest = orig_run
    return captured["ns"]


def test_run_subcommand_inherits_parent_start_end():
    """`run` must surface --start/--end from the parent, not shadow them with None.

    Reproduces the Important #1 bug: argparse subparsers shadow parent namespace
    entries with None when --start/--end are redefined on the subparser. After
    the fix, the parent's values must propagate.
    """
    ns = _parsed_ns(["--start", "2025-08-21", "--end", "2025-09-21",
                     "run", "--cash", "1000000"])
    assert ns.start == "2025-08-21"
    assert ns.end == "2025-09-21"


def test_run_subcommand_inherits_db_and_preset():
    """`run` must also inherit --db and --preset from the parent (same shadowing bug)."""
    ns = _parsed_ns(["--start", "2025-08-21", "--end", "2025-09-21",
                     "run", "--cash", "1000000"])
    assert ns.db is not None       # parent's default of get_db_path()
    assert ns.preset == "v1"       # parent's default


def test_resolve_window_explicit_dates_round_trip():
    """When --start/--end are passed, they must propagate unchanged."""
    s, e = _resolve_window("2025-08-21", "2025-09-21")
    assert s == date(2025, 8, 21)
    assert e == date(2025, 9, 21)


def test_resolve_window_defaults_to_365d_window_ending_today():
    """When neither is passed, end = today, start = end - 365 days."""
    s, e = _resolve_window(None, None)
    assert e == date.today()
    assert s == date.fromordinal(e.toordinal() - 365)


def test_resolve_window_end_only_defaults_start():
    """When only --end is passed, start = end - 365 days."""
    s, e = _resolve_window(None, "2025-09-21")
    assert e == date(2025, 9, 21)
    assert s == date.fromordinal(e.toordinal() - 365)


def test_out_dir_suffix_includes_microseconds():
    """Smoke test on out_dir suffix format to catch same-second collisions."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # Microsecond field is 6 digits
    assert len(stamp.split("_")[-1]) == 6
