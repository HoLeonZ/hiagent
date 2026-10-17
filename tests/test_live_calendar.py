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
