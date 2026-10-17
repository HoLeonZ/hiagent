"""Daily equity curve — the series that makes a daily Sharpe (and therefore a
defensible DSR, §5) possible.

The strategy ALREADY records it per bar (replay_strategy_v3.py:540-566); what
was missing is that `_metrics_from_holder` drops it (engine.py:85-102) while
main.py:168 reads m.get("equity_curve"), so equity_curve.csv has never been
produced. This file therefore tests a PASS-THROUGH, not a new recorder.

Skips (not errors) when the local DuckDB is absent — CLAUDE.md §6.
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pytest

from hiagent_config import get_db_path

PRESET = "v50_slope"
START, END, MIN_BARS = "2025-09-12", "2026-09-12", 150


@pytest.fixture(scope="module")
def metrics() -> dict:
    db = get_db_path()
    if not db.exists():
        pytest.skip(f"local DuckDB not present at {db} (§6: skip, do not error)")
    from short_reversal.engine import run_backtest_v3
    return run_backtest_v3(PRESET, START, END, db, min_bars=MIN_BARS)


def test_engine_return_dict_carries_equity_curve(metrics: dict):
    assert "equity_curve" in metrics, (
        "_metrics_from_holder dropped holder['equity_curve']; without a daily "
        "equity series there is no daily Sharpe and no defensible DSR (§5)"
    )


def test_equity_curve_is_non_empty_and_dated(metrics: dict):
    ec = metrics["equity_curve"]
    assert len(ec) > 0, "an all-in engine over a 1-year window cannot have an empty curve"
    dates = [row["date"] for row in ec]
    assert dates == sorted(dates), "equity curve must be in ascending date order"
    assert len(set(dates)) == len(dates), "exactly one row per trading day"


def test_equity_curve_first_row_is_initial_capital(metrics: dict):
    """No entry can fill before the second bar, so the first row is untouched."""
    assert metrics["equity_curve"][0]["equity"] == pytest.approx(1_000_000.0, abs=1.0)


def test_equity_curve_has_the_keys_the_reporting_path_reads(metrics: dict):
    """The row schema is the EXISTING one from replay_strategy_v3.py:559-566 —
    do not change it here. `main.py` already reads `cash` and holdings_value`."""
    for row in metrics["equity_curve"]:
        assert set(row) >= {"date", "cash", "holdings_value", "equity", "drawdown"}
        assert isinstance(row["date"], dt.date), (
            "the existing recorder stores a datetime.date; do not stringify it"
        )
        assert isinstance(row["equity"], float)
        # The recorder's own definition, true on every row whether or not
        # positions are open. This is the one structural invariant about the
        # numbers that does not depend on a market outcome.
        assert row["equity"] == pytest.approx(
            row["cash"] + row["holdings_value"], rel=1e-9, abs=1e-6
        )


def test_rows_carry_the_three_cash_pools(metrics: dict):
    """`main.py`'s cash_walk.csv reports the pools per row.

    This test exists because of a defect that shipped once: main.py read
    `row.get("locked_margin", 0.0)` while NO producer emitted that key, so the
    fallback always fired and the "fix" reproduced the hardcoded 0.0 it claimed
    to remove — with a different appearance. Assert the keys are produced, and
    that they reconcile with `cash`.
    """
    for row in metrics["equity_curve"]:
        assert {"free_cash", "locked_margin", "settling_funds"} <= set(row), (
            "the recorder must emit the three pools, or main.py's per-pool "
            "reporting silently falls back to the hardcoded zeros"
        )
        assert row["cash"] == pytest.approx(
            row["free_cash"] + row["locked_margin"] + row["settling_funds"],
            rel=1e-9, abs=1e-4,
        ), "the three pools must reconcile to total_cash (replay_strategy_v3.py:445)"


def test_equity_curve_reaches_the_end_of_the_requested_window(metrics: dict):
    """The curve must COVER the requested window's end — a curve ending before
    END means the metrics were computed over a different span than they are
    labelled with.

    Do NOT assert `dates[0] <= START`. An earlier revision did, on the
    assumption that `next()` fires from the panel's first bar. It does not:
    backtrader calls `next()` only once `len(self) >= minperiod`, and the
    SMA(60) wiring puts minperiod at 60, so the first recorded bar lands well
    after the panel start — for a window containing a recent listing, tens of
    trading days after START. Measured for Task 3's log on this same window:
    first evaluated bar ~45 trading days after START. That is an engine
    property, not a defect, and this test must not depend on it.

    The panel window and the metrics span are still both `[start-180d, end+60d]`
    (no feed.fromdate/todate, and `_metrics_from_holder` uses start/end only for
    the CAGR year count, engine.py:65-68) — but "the curve starts at the panel
    start" does not follow from that, because minperiod gates the first `next()`.
    """
    dates = [row["date"] for row in metrics["equity_curve"]]
    assert dates, "equity curve is empty"
    # `dates` holds datetime.date objects while END is a "YYYY-MM-DD" string.
    # Comparing them directly raises TypeError — it does not merely fail — so
    # convert one side. Do NOT "fix" this by comparing strings: the recorder's
    # date type is deliberate (see the schema test above).
    assert dates[-1] >= dt.date.fromisoformat(END), (
        f"curve ends {dates[-1]}, before END={END}"
    )
    assert len(set(dates)) >= 150, (
        f"only {len(set(dates))} distinct dates on the curve; a year-scale "
        f"window should record most trading days"
    )


def test_ensemble_path_also_carries_equity_curve():
    """_run_ensemble returns EARLY from run_backtest_v3 (engine.py:224-225) and
    builds its own result dict (engine.py:181-199), so it never passes through
    _metrics_from_holder. Unless it aggregates its legs' curves, ensembles have
    no equity_curve at all — and Task 8's whole job is comparing ensembles."""
    db = get_db_path()
    if not db.exists():
        pytest.skip(f"local DuckDB not present at {db} (§6: skip, do not error)")
    from short_reversal.engine import run_backtest_v3
    m = run_backtest_v3("v63_ensemble", START, END, db, min_bars=MIN_BARS)
    assert "equity_curve" in m, (
        "ensemble path bypasses _metrics_from_holder; it must aggregate its "
        "legs' equity curves itself"
    )
    ec = m["equity_curve"]
    assert len(ec) > 0
    dates = [row["date"] for row in ec]
    assert dates == sorted(dates), "ascending date order"
    assert len(set(dates)) == len(dates), "one row per date"

    # Assert STRUCTURE, not a market outcome.
    #
    # Do NOT assert `all(row["equity"] > 0)`: this is an all-in SHORT book, so
    # equity is `cash + Σ (entry - close) * size` and a position that moves far
    # enough against you drives it negative legitimately.
    #
    # Do NOT assert `ec[-1]["equity"] == m["final_capital"]` either. `equity` is
    # `_nav()` = total_cash + unrealised, while `final_capital` is `stop()`'s
    # `total_cash` ALONE (replay_strategy_v3.py:610-623 vs :1129-1139). They
    # coincide only when every leg happens to be flat on the last bar — a market
    # outcome, not a structural property. (An earlier revision of this test made
    # exactly that mistake, replacing one unverifiable runtime claim with a
    # stronger, more failure-prone one.)
    for row in ec:
        assert math.isfinite(row["equity"])
        # The recorder's OWN identity, true on every row regardless of whether
        # positions are open: equity is defined as cash + holdings_value.
        assert row["equity"] == pytest.approx(
            row["cash"] + row["holdings_value"], rel=1e-9, abs=1e-6
        ), "equity must equal cash + holdings_value on every row"
    # Weights sum to 1 and no entry can fill on the first recorded bar.
    assert ec[0]["equity"] == pytest.approx(1_000_000.0, abs=1.0)
