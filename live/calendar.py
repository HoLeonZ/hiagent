"""Trading calendar for the live monitor.

The repo has no calendar; engines infer the next trading day from kline dates
(cycle_price_action/data_feed.py:75-84). That is unusable intraday: at 09:25 the
current day's bar does not exist yet. This module sources the calendar from the
hithink-finance CLI and caches it locally.

The provider is INJECTED so tests never touch the network.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

SESSION_TIMES: tuple[str, ...] = ("09:25", "10:30", "13:30", "14:45", "14:57")

# A one-year capability window (market.calendar); refresh when the cache does
# not cover today.
_CACHE_VERSION = 1


@dataclass(frozen=True)
class TradingCalendar:
    days: frozenset[date]
    fetched_at: datetime | None

    def covers(self, d: date) -> bool:
        if not self.days:
            return False
        return min(self.days) <= d <= max(self.days)


def _cli_provider() -> list[str]:
    """Default provider: hithink-finance market calendar (remote, needs API key).

    Real response shape (verified 2026-10-17 against
    ``hithink-finance market calendar --format json``, capability
    ``market.calendar``, one-year window)::

        {"ok": true, "command": "market.calendar",
         "data": {"item": [{"date_ms": 1760630400000, "date": "20251017"}, ...],
                  "timestamp": ...},
         "meta": {...}}

    The row's date field is keyed ``"date"`` (NOT ``trade_date`` /
    ``trading_day``) and formatted basic-ISO ``YYYYMMDD``; the rows live under
    ``data.item`` rather than directly under ``data``.
    """
    out = subprocess.run(
        ["hithink-finance", "market", "calendar", "--format", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    payload = json.loads(out)
    data = payload["data"]
    # Real CLI nests rows under data.item; tolerate a bare list as a fallback.
    rows: Iterable[dict] = data["item"] if isinstance(data, dict) else data
    days = []
    for r in rows:
        raw = r.get("date") or r.get("trade_date") or r.get("trading_day")
        if not raw:
            continue
        s = str(raw)[:10]
        # CLI emits basic ISO "YYYYMMDD"; normalise to "YYYY-MM-DD".
        if len(s) == 8 and s.isdigit():
            s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        days.append(s)
    return sorted(set(days))


def load_calendar(
    *,
    cache_path: Path,
    provider: Callable[[], list[str]] = _cli_provider,
    today: date,
) -> TradingCalendar:
    """Load the cached calendar, refetching only when today is not covered."""
    if cache_path.exists():
        try:
            blob = json.loads(cache_path.read_text(encoding="utf-8"))
            if blob.get("version") == _CACHE_VERSION:
                cal = TradingCalendar(
                    frozenset(date.fromisoformat(d) for d in blob["days"]),
                    datetime.fromisoformat(blob["fetched_at"]),
                )
                if cal.covers(today):
                    return cal
                logger.info("calendar cache does not cover %s; refetching", today)
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning("calendar cache unreadable at %s; refetching", cache_path)

    days = provider()
    if not days:
        raise ValueError("market calendar provider returned no days — refusing to run blind")
    fetched_at = datetime.now()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"version": _CACHE_VERSION, "days": days,
                    "fetched_at": fetched_at.isoformat()}, indent=2),
        encoding="utf-8",
    )
    return TradingCalendar(frozenset(date.fromisoformat(d) for d in days), fetched_at)


def is_trading_day(cal: TradingCalendar, d: date) -> bool:
    return d in cal.days


def next_trading_day(cal: TradingCalendar, d: date) -> date:
    later = [x for x in cal.days if x > d]
    if not later:
        raise ValueError(
            f"calendar exhausted: no trading day after {d} in [{min(cal.days)}..{max(cal.days)}]"
        )
    return min(later)


def prev_trading_day(cal: TradingCalendar, d: date) -> date:
    earlier = [x for x in cal.days if x < d]
    if not earlier:
        raise ValueError(
            f"calendar exhausted: no trading day before {d} in [{min(cal.days)}..{max(cal.days)}]"
        )
    return max(earlier)
