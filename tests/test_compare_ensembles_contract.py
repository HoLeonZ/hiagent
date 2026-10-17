"""Schema and convention locks for the ensemble comparison harness.

These are cheap unit tests. The real comparison (Step 6) is a multi-hour batch;
nothing here may depend on it.
"""
from __future__ import annotations

import datetime as dt
import math

import pytest

from tools.live.compare_ensembles import (
    candidate_record, daily_sharpe_from_equity, honest_n_trials,
)


def _rows(flat: bool = False) -> list[dict]:
    """Rows carry a `datetime.date`, NOT a string — that is what
    replay_strategy_v3.py:556-560 actually stores, and a string-only
    implementation must not be able to pass these tests."""
    eq = (lambda i: 1_000_000.0) if flat else (lambda i: 1_000_000.0 + i * 1000)
    return [{"date": dt.date(2026, 1, i), "cash": eq(i),
             "holdings_value": 0.0, "equity": eq(i), "drawdown": 0.0}
            for i in range(1, 6)]


def test_candidate_record_has_exactly_the_required_schema():
    """The JSON schema is a contract with whoever reads compare.json. Build one
    record directly rather than running the harness — the harness is a
    multi-hour batch and must not be a prerequisite for a schema check."""
    rec = candidate_record(
        preset="v63_ensemble",
        legs=["v50_slope", "v44_ratio02_buf07"],
        is_reference=False,
        equity_rows=_rows(),
        start="2026-01-01", end="2026-01-31",
        cagr=0.2, max_dd=0.1, dsr=1.5, bonferroni_p=0.01,
        benchmark_excess_cagr=0.05,
    )
    assert set(rec) == {
        "preset", "legs", "is_reference", "cagr", "max_dd", "calmar",
        "daily_sharpe", "dsr", "bonferroni_p", "benchmark_excess_cagr",
    }
    assert rec["calmar"] == pytest.approx(0.2 / 0.1)
    assert rec["is_reference"] is False
    assert rec["legs"] == ["v50_slope", "v44_ratio02_buf07"]


def test_candidate_record_marks_the_reference():
    """spec §5: v81_adj is reported alongside the three ensembles as a
    REFERENCE, not a fourth decision candidate — v44 is a leg of all three, so
    without it the comparison is three constructs sharing one defect."""
    rec = candidate_record(
        preset="v81_adj", legs=["v81_adj"], is_reference=True,
        equity_rows=_rows(), start="2026-01-01", end="2026-01-31",
        cagr=0.2, max_dd=0.1, dsr=1.0, bonferroni_p=0.02,
        benchmark_excess_cagr=0.04,
    )
    assert rec["is_reference"] is True


def test_n_trials_is_at_least_the_library_floor():
    """spec §10: the honest bound is RESERVED(3) + len(PRESETS)(75) +
    widest_declared_sweep(41) = 119. This asserts a FLOOR of 89 — an
    implementation returning less has dropped the "75 presets were searched to
    produce the library" layer, which is a §5 violation, not a rounding
    difference."""
    assert honest_n_trials() >= 89


def test_sharpe_delegates_to_the_single_source():
    """Do NOT define a second Sharpe.

    `dna_stats/deflated.py:82` already ships a battle-tested `annualized_sharpe`,
    and its documented convention for an undefined Sharpe (constant returns) is
    NaN — not 0.0. A second implementation with a conflicting convention for the
    same edge case is exactly the duplication CLAUDE.md §6 forbids.
    """
    from dna_stats.deflated import annualized_sharpe

    assert math.isnan(daily_sharpe_from_equity(_rows(flat=True),
                                               "2026-01-01", "2026-01-31")), (
        "constant equity must yield NaN, matching annualized_sharpe, not 0.0"
    )

    rising = _rows()
    rets = [b["equity"] / a["equity"] - 1.0 for a, b in zip(rising, rising[1:])]
    assert daily_sharpe_from_equity(rising, "2026-01-01", "2026-01-31") == \
        pytest.approx(annualized_sharpe(rets))


def test_the_two_scripts_do_not_share_an_output_file():
    """Step 6 launches both scripts CONCURRENTLY against the same --out dir. If
    they wrote the same filename, the later writer would silently clobber the
    earlier one and the comparison would be half-missing with no error.

    A prose "do not share a file" is exactly the kind of constraint that gets
    violated silently, so pin it.
    """
    from tools.live.compare_ensembles import OUTPUT_NAME as A
    from tools.live.reproduce_2016_2023 import OUTPUT_NAME as B
    assert A != B, f"both scripts write {A!r} — concurrent runs would race"


def test_daily_sharpe_slices_to_the_requested_window():
    """The engine's equity curve spans [start-180d, end+60d]; the harness must
    report a Sharpe for the window it LABELS, not for the buffered span.

    NOTE — this test deliberately builds rows with **string** dates, while the
    `_rows` helper above builds them with `datetime.date`. Together they pin the
    requirement that the slice accepts BOTH: production rows carry `datetime.date`
    (replay_strategy_v3.py:556-560) while `start`/`end` are `"YYYY-MM-DD"`
    strings, so an implementation that only handles one throws `TypeError` in the
    other. Do not "unify" the two fixtures — the duplication is the coverage.
    """
    saw = [1_000_000.0, 1_010_000.0, 990_000.0, 1_030_000.0, 1_000_000.0,
           1_050_000.0, 1_010_000.0, 1_070_000.0, 1_020_000.0, 1_090_000.0]
    full = [{"date": f"2026-01-{i:02d}", "equity": v}
            for i, v in enumerate(saw, start=1)]

    narrow = daily_sharpe_from_equity(full, "2026-01-01", "2026-01-04")
    wide = daily_sharpe_from_equity(full, "2026-01-01", "2026-01-10")
    assert not math.isnan(narrow) and not math.isnan(wide)

    # Slicing changes the series, so it MUST change the answer. If it does not,
    # the window is not being applied and a buffered-span Sharpe is being
    # reported under a [start, end] label.
    assert not math.isclose(narrow, wide), "the slice is not being applied"

    # One point inside the window -> fewer than two returns -> undefined.
    assert math.isnan(daily_sharpe_from_equity(full, "2026-01-01", "2026-01-01"))
