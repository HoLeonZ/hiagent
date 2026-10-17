"""Trading calendar for the live monitor.

The repo has no calendar; engines infer the next trading day from kline dates
(cycle_price_action/data_feed.py:75-84). That is unusable intraday: at 09:25 the
current day's bar does not exist yet. This module sources the calendar from the
hithink-finance CLI and caches it locally.

TRAILING SOURCE — READ BEFORE USING `today`. `market.calendar` lists only
COMPLETED sessions: it contains no present or future date and takes no window
parameter (`one-year` is the lookback length). So `is_trading_day(cal, today)`
is necessarily False intraday (today's session has not completed) and
`next_trading_day(cal, today)` runs off the end and raises. The present-day
question must be answered from a LIVE source (`market.auction-snapshot` /
`market.snapshot` returning rows proves today is a session) — never from
synthesised dates (§0/§1 forbid fabricating data). See spec §3.1 and risk R8.

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

# A one-year capability window (market.calendar). The cache is refreshed on TIME
# staleness, not on coverage — see load_calendar for why coverage cannot work.
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

    The source is TRAILING: it lists only completed sessions and ends at the
    last completed trading day (e.g. 2026-10-17 returned rows ending 2026-10-16).
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
    max_staleness_days: int = 0,
    force_refresh: bool = False,
) -> TradingCalendar:
    """Load the calendar, refetching when the cache was fetched before `today`.

    FRESHNESS IS TIME-BASED, NOT COVERAGE-BASED — deliberately.

    The remote source is TRAILING: `market.calendar` lists only COMPLETED
    sessions and contains no present or future date (the capability takes no
    window parameter; `one-year` is the lookback length). A coverage test such
    as `max(days) >= today` is therefore unsatisfiable on EVERY calendar day —
    intraday, at a weekend, or on a holiday. A coverage-based cache would be
    read but never used, and the CLI would be shelled out on every call while
    the module claimed to cache: the cache-hit branch would be unreachable in
    production, which an earlier revision of this module actually shipped.

    WHY THE DEFAULT IS 0, NOT 1 — read before changing it.

    A cache fetched on D and served on D+1 is STALE IN THE TAIL: the source
    always trails by at least one session, so a D-day fetch ends at D-1 (or
    earlier), and serving it on D+1 hides the session that completed ON D.
    `is_trading_day(cal, D)` then returns False on D+1 and the navigation
    helpers are off by one session near the tail. Before this cache was
    time-based it refetched unconditionally, so the tail was always fresh —
    i.e. a nonzero default is a window THIS design opens rather than one it
    inherits. The cache buys repeated-call avoidance WITHIN a day (intraday
    ticks, a re-run of the 15:30 job), which 0 preserves; serving across a day
    saves one CLI call and costs tail correctness. Do not raise it without a
    consumer that needs it.

    Consequence for callers: `is_trading_day(cal, today)` is necessarily False
    intraday (today's session has not completed, so it is not listed), and
    `next_trading_day(cal, today)` runs off the end and raises. The present-day
    question must be answered from a LIVE source (`market.auction-snapshot` /
    `market.snapshot` returning rows proves today is a session), not from this
    calendar. Do NOT synthesise future sessions — §0/§1 forbid fabricating data.

    RESIDUAL WINDOW, AND WHEN TO PASS `force_refresh=True`.

    `max_staleness_days=0` closes the CROSS-DAY lag, but a SAME-DAY window
    remains and is bounded only by an assumption this module cannot verify:
    whether the remote source republishes a session at/near the 15:00 close.

    If it does, then on a trading day D a 09:25 fetch caches `days` ending at
    D-1, and a 15:30 call the same day is served that cache — so `max(days)` is
    D-1 when it should be D. Same off-by-one, compressed into one day.

    No consumer in this design needs tail freshness: the 15:30 signal job takes
    `signal_date` as a parameter and does not gate on this calendar, and the
    intraday monitor's "is today a session" question is answered by the live
    source (see above), because this calendar cannot answer it at all. So the
    window is documented rather than worked around. A future consumer that DOES
    need a calendar including the just-completed session must pass
    `force_refresh=True` (or call `_cli_provider` directly) — the same-day cache
    will otherwise be served, and `max_staleness_days` cannot express "always
    refetch" because its floor is 0.

    Reference: spec §3.1 and risk R8.
    """
    if cache_path.exists() and not force_refresh:
        try:
            blob = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(blob, dict):
                raise TypeError(f"cache is not a JSON object: {type(blob).__name__}")
            if blob.get("version") == _CACHE_VERSION:
                fetched_on = date.fromisoformat(blob["fetched_on"])
                if (today - fetched_on).days <= max_staleness_days:
                    return TradingCalendar(
                        frozenset(date.fromisoformat(d) for d in blob["days"]),
                        datetime.fromisoformat(blob["fetched_at"]),
                    )
                logger.info(
                    "calendar cache fetched on %s is stale for today=%s; refetching",
                    fetched_on, today,
                )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "calendar cache unreadable at %s (%s); refetching", cache_path, exc
            )

    days = provider()
    if not days:
        raise ValueError("market calendar provider returned no days — refusing to run blind")
    fetched_at = datetime.now()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({
            "version": _CACHE_VERSION,
            "days": days,
            "fetched_at": fetched_at.isoformat(),
            # Freshness is decided on THIS (the injected `today`), not on the
            # wall clock, so the decision stays testable and reproducible.
            "fetched_on": today.isoformat(),
        }, indent=2),
        encoding="utf-8",
    )
    return TradingCalendar(frozenset(date.fromisoformat(d) for d in days), fetched_at)


def is_trading_day(cal: TradingCalendar, d: date) -> bool:
    return d in cal.days


def next_trading_day(cal: TradingCalendar, d: date) -> date:
    later = [x for x in cal.days if x > d]
    if not later:
        span = (
            f"[{min(cal.days)}..{max(cal.days)}]" if cal.days
            else "the calendar is empty"
        )
        raise ValueError(f"calendar exhausted: no trading day after {d} in {span}")
    return min(later)


def prev_trading_day(cal: TradingCalendar, d: date) -> date:
    earlier = [x for x in cal.days if x < d]
    if not earlier:
        span = (
            f"[{min(cal.days)}..{max(cal.days)}]" if cal.days
            else "the calendar is empty"
        )
        raise ValueError(f"calendar exhausted: no trading day before {d} in {span}")
    return max(earlier)
