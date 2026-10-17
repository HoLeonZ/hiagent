"""Trading calendar: pure logic tested with an injected provider (no network)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from live.calendar import (
    SESSION_TIMES, TradingCalendar, is_trading_day, load_calendar,
    next_trading_day, prev_trading_day,
)

DAYS = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16",
        "2026-10-19", "2026-10-20"]


def test_load_populates_and_caches(tmp_path: Path):
    cache = tmp_path / "cal.json"
    calls = []

    def provider():
        calls.append(1)
        return DAYS

    cal = load_calendar(cache_path=cache, provider=provider, today=date(2026, 10, 17))
    assert len(calls) == 1
    assert is_trading_day(cal, date(2026, 10, 16))
    assert cache.exists()
    assert json.loads(cache.read_text())["days"] == DAYS

    # Second call inside the cache window must NOT hit the provider again.
    load_calendar(cache_path=cache, provider=provider, today=date(2026, 10, 17))
    assert len(calls) == 1


def test_non_trading_day_is_false():
    cal = TradingCalendar(frozenset(date.fromisoformat(d) for d in DAYS), None)
    assert is_trading_day(cal, date(2026, 10, 17)) is False   # Saturday
    assert is_trading_day(cal, date(2026, 10, 18)) is False   # Sunday


def test_next_and_prev_skip_weekend():
    cal = TradingCalendar(frozenset(date.fromisoformat(d) for d in DAYS), None)
    assert next_trading_day(cal, date(2026, 10, 16)) == date(2026, 10, 19)
    assert prev_trading_day(cal, date(2026, 10, 19)) == date(2026, 10, 16)


def test_next_beyond_calendar_raises_not_silently_wraps():
    """§0 fail-fast: an exhausted calendar must not pretend."""
    cal = TradingCalendar(frozenset(date.fromisoformat(d) for d in DAYS), None)
    with pytest.raises(ValueError, match="calendar"):
        next_trading_day(cal, date(2026, 10, 20))


def test_session_times_are_the_agreed_set():
    assert SESSION_TIMES == ("09:25", "10:30", "13:30", "14:45", "14:57")


def test_stale_cache_triggers_a_refetch(tmp_path: Path):
    """Freshness is TIME-based, because the remote calendar is trailing: a
    coverage test against `today` is unsatisfiable on every calendar day, so a
    coverage-based cache would be read but never used and the CLI would be
    shelled out on every call.

    The boundary that matters is Δ=1, and it is pinned explicitly: the source
    always trails by at least one session, so serving a D-day fetch on D+1 would
    hide the session that completed ON D.
    """
    cache = tmp_path / "cal.json"
    calls = []

    def provider():
        calls.append(1)
        return DAYS

    load_calendar(cache_path=cache, provider=provider, today=date(2026, 10, 17))
    assert len(calls) == 1

    # Δ=0 — same day — served from cache.
    load_calendar(cache_path=cache, provider=provider, today=date(2026, 10, 17))
    assert len(calls) == 1, "a same-day cache must be served"

    # Δ=1 — the boundary — must NOT be served.
    load_calendar(cache_path=cache, provider=provider, today=date(2026, 10, 18))
    assert len(calls) == 2, (
        "a cache from a previous day must not be served: the source trails, so "
        "a D-day fetch served on D+1 hides the session that completed on D"
    )

    # Δ=1 again, from the refreshed cache — still refetches.
    load_calendar(cache_path=cache, provider=provider, today=date(2026, 10, 19))
    assert len(calls) == 3


def test_trailing_calendar_cannot_answer_the_present_day():
    """A property of the REMOTE SOURCE, asserted so that a future change making
    this True is recognised as either a source change or synthesised data — not
    as a fix.

    DAYS ends at 2026-10-16; a caller asking about 2026-10-17 gets False.
    Intraday this is the whole point: today's session has not completed, so it
    is not listed. The present-day question must come from a live source.
    """
    cal = TradingCalendar(frozenset(date.fromisoformat(d) for d in DAYS), None)
    assert is_trading_day(cal, date(2026, 10, 17)) is False


def test_empty_calendar_raises_a_usable_message():
    """`min()` on an empty set raises "min() arg is an empty sequence", which is
    not an operator-facing message. `load_calendar` cannot produce an empty
    calendar, but `TradingCalendar` is public, so the guard belongs here."""
    empty = TradingCalendar(frozenset(), None)
    with pytest.raises(ValueError) as ei:
        next_trading_day(empty, date(2026, 10, 20))
    assert "calendar" in str(ei.value), (
        f"message must name the calendar, got: {ei.value}"
    )
    # The sibling helper needs the same guard — assert it too, or a future edit
    # can regress it silently.
    with pytest.raises(ValueError) as ei2:
        prev_trading_day(empty, date(2026, 10, 20))
    assert "calendar" in str(ei2.value), (
        f"message must name the calendar, got: {ei2.value}"
    )
