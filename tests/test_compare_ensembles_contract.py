"""Schema and convention locks for the ensemble comparison harness.

These are cheap unit tests. The real comparison (Step 6) is a multi-hour batch;
nothing here may depend on it.
"""
from __future__ import annotations

import datetime as dt
import json
import math

import pytest

from dna_stats.deflated import (
    annualized_sharpe,
    bonferroni_correct,
    sharpe_significance_pvalue,
)
from tools.live.compare_ensembles import (
    _build_record,
    _windowed_returns,
    candidate_record,
    daily_sharpe_from_equity,
    honest_n_trials,
    write_json,
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
        cagr=0.2, max_dd=0.1, daily_sharpe=1.5,
        dsr=1.5, bonferroni_p=0.01,
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
        cagr=0.2, max_dd=0.1, daily_sharpe=1.0,
        dsr=1.0, bonferroni_p=0.02,
        benchmark_excess_cagr=0.04,
    )
    assert rec["is_reference"] is True


def test_n_trials_is_the_exact_documented_value():
    """spec §10: the honest bound is RESERVED(3) + len(PRESETS)(75) +
    widest_declared_sweep(41) = 119, and 119 is the number actually written into
    the artifacts' `n_trials` field (which drives the DSR/Bonferroni deflation).

    This pins the EXACT value, not a floor. A floor of 89 passed for an
    implementation that silently dropped the whole `len(PRESETS)` layer — 25% of
    the trials `n_trials` must account for — while still clearing 89. The
    documented number IS the contract; if the library is deliberately resized,
    update this pin alongside `honest_n_trials`.
    """
    assert honest_n_trials() == 119


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


def _capture_output_name(module, monkeypatch, tmp_path) -> str:
    """Run `module.main` with the DB/backtest boundary stubbed and return the
    `output_name` it actually hands to `write_json`."""
    captured: dict = {}

    def fake_write_json(payload, out_dir, output_name):
        captured["output_name"] = output_name
        return tmp_path / output_name

    monkeypatch.setattr(module, "run_comparison",
                        lambda *a, **k: {"window": ["a", "b"], "candidates": []})
    monkeypatch.setattr(module, "get_db_path", lambda: tmp_path / "db.duckdb")
    monkeypatch.setattr(module, "write_json", fake_write_json)
    assert module.main(["--out", str(tmp_path)]) == 0
    return captured["output_name"]


def test_each_main_writes_its_own_output_file(monkeypatch, tmp_path):
    """Step 6 launches BOTH scripts CONCURRENTLY against the same --out dir. The
    clobber race is real only if each `main` actually PASSES its own
    `OUTPUT_NAME` to `write_json` — the two module constants differing proves
    nothing about the call site. An edit that made
    `reproduce_2016_2023.main` write `_COMPARE_OUTPUT_NAME` (both scripts write
    `compare.json`, `repro.json` never appears, one run half-missing with no
    error) would keep a constants-only assertion green. Pin the write TARGET.
    """
    import tools.live.compare_ensembles as compare
    import tools.live.reproduce_2016_2023 as repro

    assert compare.OUTPUT_NAME == "compare.json"
    assert repro.OUTPUT_NAME == "repro.json"
    assert _capture_output_name(compare, monkeypatch, tmp_path) == "compare.json"
    assert _capture_output_name(repro, monkeypatch, tmp_path) == "repro.json"


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


# --- Finding 1: the per-period Sharpe unit ----------------------------------

def _equity_rows_from_returns(
    returns: list[float], start: dt.date = dt.date(2020, 1, 1),
) -> list[dict]:
    """Rows whose equity is the cumprod of `returns`, one row per day."""
    eq = 1_000_000.0
    rows = [{"date": start, "equity": eq}]
    for i, r in enumerate(returns, start=1):
        eq *= (1.0 + r)
        rows.append({"date": start + dt.timedelta(days=i), "equity": eq})
    return rows


def test_bonferroni_p_de_annualizes_the_sharpe_before_the_period_se():
    """§5 unit consistency: `sharpe_significance_pvalue`'s SE = 1/sqrt(T-1) is
    PER-PERIOD (its docstring: "for daily returns"), but `annualized_sharpe`
    returns an ANNUALIZED Sharpe. Passing the annualized value inflates z by
    sqrt(252) ~ 15.9 and saturates p to 0.0 — i.e. `bonferroni_p = 0.0`,
    "unconditionally family-wise significant", for a strategy the SAME record's
    `dsr` may call insignificant. `deflated_sharpe_ratio` already de-annualizes
    internally (dna_stats/deflated.py:158-165); this pins the same fix at the
    `sharpe_significance_pvalue` call site.

    The series below is tuned so the two conventions DISAGREE observably: the
    annualized call underflows to EXACTLY 0.0 while the per-period call is a
    real, non-significant p. (A series where both give p<0.001 — like the shared
    module's own `test_sharpe_significance_basic` — would pass under either
    convention and is worthless here.)
    """
    returns = [0.01 if i % 2 == 0 else -0.0096 for i in range(1600)]
    rows = _equity_rows_from_returns(returns)
    start, end = "2020-01-01", "2026-01-01"
    n_trials = 119

    rec = _build_record(
        "v63_ensemble", {"equity_curve": rows}, start, end,
        bench_cagr=0.0, n_trials=n_trials,
    )

    ann = annualized_sharpe(_windowed_returns(rows, start, end))
    n = len(_windowed_returns(rows, start, end))
    # Sanity: the two conventions genuinely disagree for THIS series.
    assert sharpe_significance_pvalue(ann, n) == 0.0            # buggy units
    assert sharpe_significance_pvalue(ann / math.sqrt(252), n) > 0.05  # correct

    expected = float(bonferroni_correct(
        [sharpe_significance_pvalue(ann / math.sqrt(252), n)], n_trials)[0])
    assert rec["bonferroni_p"] == pytest.approx(expected)
    # NOT the saturated 0.0 that the annualized call manufactures.
    assert rec["bonferroni_p"] != 0.0


# --- Finding 2: one horizon for every §5 field ------------------------------

def test_record_cagr_and_max_dd_come_from_the_in_window_slice():
    """The engine's `result["cagr"]`/`result["max_dd"]` mark the cash at the
    panel's LAST bar (`= end + PANEL_POST_BUFFER_DAYS` = end + 60d) yet divide by
    `(end - start)`, so they mix two horizons, while `bench_cagr` is strictly
    in-window. Deriving them from the same sliced equity that feeds the Sharpe
    makes `benchmark_excess_cagr = cagr - bench_cagr` an in-window figure.

    An equity series that spikes only AFTER `end` must not raise the reported
    in-window CAGR, nor inject a post-window drawdown.
    """
    start, end = "2024-01-01", "2025-01-01"
    rows: list[dict] = []
    # in-window: monotonically rising 1.0M -> 1.1M (running-peak max_dd == 0)
    for i in range(0, 11):
        rows.append({
            "date": dt.date(2024, 1, 1) + dt.timedelta(days=33 * i),
            "equity": 1_000_000.0 * (1.0 + 0.01 * i),
        })
    # post-window: a 50x spike then a crash — would dominate any un-sliced stat
    rows.append({"date": dt.date(2025, 2, 1), "equity": 50_000_000.0})
    rows.append({"date": dt.date(2025, 3, 1), "equity": 1_000_000.0})

    rec = _build_record(
        "v63_ensemble",
        # engine values are deliberately absurd + present: they MUST be ignored.
        {"cagr": 99.0, "max_dd": 0.9, "equity_curve": rows},
        start, end, bench_cagr=0.0, n_trials=119,
    )

    # max_dd is the in-window running-peak drawdown; in-window is monotone -> 0.
    assert rec["max_dd"] == 0.0
    # cagr is first/last of the in-window slice: 1.1M/1.0M over the window
    # (365.25-day year, matching the benchmark's `_window_years`).
    years = (dt.date(2025, 1, 1) - dt.date(2024, 1, 1)).days / 365.25
    assert rec["cagr"] == pytest.approx(1.1 ** (1.0 / years) - 1.0)
    assert rec["cagr"] < 0.2        # a post-window-inclusive CAGR would be huge
    assert math.isnan(rec["calmar"])  # max_dd == 0 -> Calmar undefined


def test_record_daily_sharpe_comes_from_the_in_window_slice():
    """COVERAGE REGRESSION GUARD — 578ae64.

    That commit split the equity slice out of `daily_sharpe_from_equity` so ONE
    slice feeds every §5 field, and made production compute the Sharpe inline
    (`_build_record`: `annualized_sharpe(_returns_from_slice(sliced))`). The two
    tests that pin window-slicing (`test_daily_sharpe_slices_to_the_requested_window`
    and the NaN case in `test_sharpe_delegates_to_the_single_source`) assert
    THROUGH `daily_sharpe_from_equity`, which the refactor left with no production
    caller. So the property the 578ae64 horizon fix was ABOUT — the record reports
    a Sharpe for the window it LABELS, not for the buffered span — stopped being
    pinned by ANY test: substituting the buffered-span returns at the production
    call site keeps all 12 tests green.

    This test drives the PRODUCTION path (`_build_record`) and both (a) pins the
    numeric in-window value and (b) couples it to the documented
    `daily_sharpe_from_equity` interface, so production and that interface cannot
    drift apart. The post-`end` tail is violent enough that leaking it moves
    `daily_sharpe` by ~540 (547.43 -> 5.87) — the assertion below is a real
    constraint, not a tautology (see the positive control at the end).
    """
    start, end = "2024-01-01", "2025-01-01"
    rows: list[dict] = []
    # in-window: mildly (but strictly) rising 1.0M -> 1.1M — a FINITE Sharpe, so
    # this is not just re-testing the NaN -> None branch.
    for i in range(0, 11):
        rows.append({
            "date": dt.date(2024, 1, 1) + dt.timedelta(days=33 * i),
            "equity": 1_000_000.0 * (1.0 + 0.01 * i),
        })
    # post-`end`: violent swings — leaking these MUST move the Sharpe visibly.
    rows.append({"date": dt.date(2025, 2, 1), "equity": 50_000_000.0})
    rows.append({"date": dt.date(2025, 3, 1), "equity": 1_000_000.0})
    rows.append({"date": dt.date(2025, 4, 1), "equity": 80_000_000.0})
    rows.append({"date": dt.date(2025, 5, 1), "equity": 200_000.0})

    rec = _build_record(
        "v63_ensemble", {"equity_curve": rows},
        start, end, bench_cagr=0.0, n_trials=119,
    )
    assert rec["daily_sharpe"] is not None

    # (a) production equals the IN-WINDOW-only Sharpe, re-derived here WITHOUT the
    # module's own slicing — an independent anchor for the numeric value.
    in_window = [r for r in rows
                 if dt.date(2024, 1, 1) <= r["date"] <= dt.date(2025, 1, 1)]
    in_window_only = annualized_sharpe(
        [b["equity"] / a["equity"] - 1.0
         for a, b in zip(in_window, in_window[1:])]
    )
    assert rec["daily_sharpe"] == pytest.approx(in_window_only)

    # (b) …and equals what the documented interface returns for the SAME rows, so
    # `_build_record` and `daily_sharpe_from_equity` are coupled by an invariant.
    assert rec["daily_sharpe"] == pytest.approx(
        daily_sharpe_from_equity(rows, start, end)
    )

    # POSITIVE CONTROL: the fixture discriminates. The pre-578ae64 inline form —
    # returns over the WHOLE buffered span — gives a wildly different answer, so
    # the equalities above bite. Relaxing this fixture (a tame post-window tail)
    # would make the regression slip through unnoticed.
    buffered_span = annualized_sharpe(
        [b["equity"] / a["equity"] - 1.0 for a, b in zip(rows, rows[1:])]
    )
    assert abs(rec["daily_sharpe"] - buffered_span) > 100.0


# --- M5: the written artifact must be strictly valid JSON --------------------

def test_write_json_emits_strictly_valid_json(tmp_path):
    """`_json_safe` maps every non-finite float to null. Without it `json.dump`
    emits bare `NaN`/`Infinity` tokens — invalid JSON that strict readers reject
    — for exactly the fields this harness produces: `calmar` when `max_dd == 0`,
    `dsr`/`bonferroni_p` on the non-finite branch, `bonferroni_p` when
    `n_returns < 2`. Step 7's evidence IS this artifact, so pin that it
    re-parses under a NaN-rejecting loader and that the fields are null.
    """
    payload = {
        "calmar": float("nan"), "dsr": float("inf"),
        "bonferroni_p": float("nan"),
        "nested": {"x": float("-inf")}, "lst": [float("nan"), 1.0], "n": 3,
    }
    path = write_json(payload, tmp_path, "x.json")

    def _reject(token):
        raise AssertionError(f"non-finite token {token!r} leaked into the JSON")

    parsed = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject)
    assert parsed["calmar"] is None
    assert parsed["dsr"] is None
    assert parsed["bonferroni_p"] is None
    assert parsed["nested"]["x"] is None
    assert parsed["lst"] == [None, 1.0]
    assert parsed["n"] == 3


# --- M6: the reproduction gate's verdict -------------------------------------

def test_decide_adopts_when_a_decision_candidate_is_significant():
    """`decide` is the script's entire deliverable. `adopt` iff some DECISION
    candidate reaches dsr >= 0.95 on the independent window."""
    from tools.live.reproduce_2016_2023 import decide

    payload = {"candidates": [
        {"preset": "v63_ensemble", "is_reference": False, "dsr": 0.96,
         "bonferroni_p": 1.0},
        {"preset": "v79_ens44", "is_reference": False, "dsr": 0.10,
         "bonferroni_p": 1.0},
    ]}
    assert decide(payload) == "adopt"


def test_decide_rejects_when_only_the_reference_candidate_is_significant():
    """The reference (`v81_adj`) is a water-mark, never a decision candidate: a
    significant reference must NOT flip the gate to adopt."""
    from tools.live.reproduce_2016_2023 import decide

    payload = {"candidates": [
        {"preset": "v63_ensemble", "is_reference": False, "dsr": 0.90,
         "bonferroni_p": 1.0},
        {"preset": "v81_adj", "is_reference": True, "dsr": 0.99,
         "bonferroni_p": 0.0},
    ]}
    assert decide(payload) == "reject"


def test_decide_rejects_when_a_decision_candidate_dsr_is_undefined():
    """An undefined DSR (non-finite Sharpe -> NaN -> null) is NOT significance."""
    from tools.live.reproduce_2016_2023 import decide

    payload = {"candidates": [
        {"preset": "v63_ensemble", "is_reference": False, "dsr": None,
         "bonferroni_p": None},
    ]}
    assert decide(payload) == "reject"
