"""A-share calendar effect scoring — pure function, deterministic.

Activations (anchored to actual calendar month-ends, not input-slice ends):
    turn_of_month (last 2 business days of month + first 2 of next): +0.5
    end_of_month (last 3 business days of month): +0.3
    spring_festival (Pre 5 business days & Post 10 business days of a holiday): +0.5
    quarterly_report (around 4/30, 8/31, 10/31 ±3 business days): +0.4

Uses only the date index — no peeking at future bars.
"""
from __future__ import annotations

import pandas as pd

QUARTERLY_ANCHORS = (("04-30", 3), ("08-31", 3), ("10-31", 3))


def _biz_month_end(d: pd.Timestamp) -> pd.Timestamp:
    """Last business day of d's calendar month."""
    last_cal = pd.Timestamp(d.year, d.month, 1) + pd.tseries.offsets.MonthEnd(0)
    return pd.Timestamp(pd.tseries.offsets.BDay(1).rollback(last_cal)).normalize()


def _biz_month_start(d: pd.Timestamp) -> pd.Timestamp:
    """First business day of d's calendar month."""
    first_cal = pd.Timestamp(d.year, d.month, 1)
    return pd.Timestamp(pd.tseries.offsets.BDay(1).rollforward(first_cal)).normalize()


def calendar_score(
    series: pd.Series,
    holidays: set[pd.Timestamp] | None = None,
) -> pd.Series:
    dates = pd.DatetimeIndex(series).normalize()
    score = pd.Series(0.0, index=series.index)

    if len(dates) == 0:
        return score

    # Business-day calendar used to compute offset to/from month ends/starts.
    # Pad ±60 BDays on each side so a date near the slice start still resolves
    # its month's BMonthStart, and a date near the slice end still resolves its
    # month's BMonthEnd (each can sit ~22 BDays outside the slice).
    bday_cal = pd.date_range(
        dates.min() - pd.tseries.offsets.BDay(60),
        dates.max() + pd.tseries.offsets.BDay(60),
        freq="B",
    ).normalize()
    pos = {d: i for i, d in enumerate(bday_cal)}

    for i, d in enumerate(dates):
        me = _biz_month_end(d)
        ms = _biz_month_start(d)
        if d not in pos or me not in pos or ms not in pos:
            continue
        off_end = pos[me] - pos[d]      # >0 if d is before month-end
        off_start = pos[d] - pos[ms]    # >0 if d is after month-start
        if 0 <= off_end <= 2:
            score.iloc[i] += 0.3          # end-of-month (last 3 BDays)
        if 0 <= off_end <= 1:
            score.iloc[i] += 0.5          # turn-of-month: last 2 of month
        if 0 <= off_start <= 1:
            score.iloc[i] += 0.5          # turn-of-month: first 2 of month

    if holidays:
        for h in sorted(holidays):
            h_ts = pd.Timestamp(h).normalize()
            mask = (dates >= h_ts - pd.tseries.offsets.BDay(5)) & (
                dates <= h_ts + pd.tseries.offsets.BDay(10)
            )
            score[mask] += 0.5

    for anchor, window in QUARTERLY_ANCHORS:
        month_day = int(anchor[:2])
        for year in dates.year.unique():
            ym = pd.Timestamp(year=year, month=month_day, day=int(anchor[3:]))
            lo = ym - pd.tseries.offsets.BDay(window)
            hi = ym + pd.tseries.offsets.BDay(window)
            mask = (dates >= lo) & (dates <= hi)
            score[mask] += 0.4

    return score.clip(-0.5, 2.0)