"""Ensemble comparison harness (spec §5 选型协议; CLAUDE.md §5 统计严谨).

Runs the three decision candidates plus one reference candidate on a single
fixed window and reports, per candidate, the CAGR / max_dd / Calmar, a
**daily-equity** Sharpe (replacing `engine.py`'s per-trade `_approx_sharpe`), and
the §5 statistical corrections (DSR + Bonferroni) under an honest `n_trials`.

Why a reference candidate: `v44_ratio02_buf07` is a leg of ALL THREE ensembles,
so without a reference the comparison is three constructs sharing one defect.
`v81_adj` — the §3 price-domain-corrected single-leg v44 — is reported alongside
as 基准水位 (`is_reference=True`), not as a fourth decision candidate.

Run:
    python3 -u -m tools.live.compare_ensembles --out /tmp/hiagent_live_runs \
        --start 2024-01-02 --end 2026-10-16

Output: `<out>/compare.json` (gitignored, §7). See `reproduce_2016_2023.py` for
the independent-window reproduction gate; the two scripts are launched
CONCURRENTLY against the same `--out` dir, so they must not share a filename.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import duckdb
import pandas as pd

from dna_stats.deflated import (
    annualized_sharpe,
    bonferroni_correct,
    deflated_sharpe_ratio,
    sharpe_significance_pvalue,
)
from hiagent_config import get_db_path
from short_reversal.engine import run_backtest_v3
from short_reversal.presets import PRESETS
from short_reversal.universe import load_universe_asof

# Each module owns its output filename so the contract test can pin that the two
# scripts (launched concurrently, sharing `--out`) do not race on one file.
OUTPUT_NAME: str = "compare.json"

# The three decision candidates (spec §5) plus the reference water-mark.
CANDIDATE_PRESETS: list[str] = ["v63_ensemble", "v64_ensemble_3leg", "v79_ens44"]
REFERENCE_PRESET: str = "v81_adj"
ALL_PRESETS: list[str] = CANDIDATE_PRESETS + [REFERENCE_PRESET]

DEFAULT_START: str = "2024-01-02"
DEFAULT_END: str = "2026-10-16"
MIN_BARS: int = 150

# spec §10 / CLAUDE.md §5 iterative-tuning accounting.
#   RESERVED(3) + len(PRESETS)(75) + widest_declared_sweep(41) = 119
# RESERVED = the three same-window decision candidates.
# len(PRESETS) = the historical search space the candidates were drawn FROM —
#     NOT the per-preset self-reported `n_comparisons` (11..45), which only counts
#     that preset's own sweep axis and hides the "75 presets were searched first"
#     layer. This is why `honest_n_trials` deliberately does not sum them.
# widest_declared_sweep = 41, the widest self-reported sweep among the four
#     candidates actually run (`v81_adj`; the reference counts, conservatively).
#     Written as a literal because the preset file's `n_comparisons` values are
#     inconsistent between presets and under separate review (R11); taking a
#     `max()` over them would silently track that inconsistency.
RESERVED: int = 3
WIDEST_DECLARED_SWEEP: int = 41


def honest_n_trials() -> int:
    """Lower bound on the number of configurations examined before this selection.

    The dominant layer is `len(PRESETS)` (the library was searched to produce
    the candidates), not each preset's self-reported `n_comparisons`.
    """
    return RESERVED + len(PRESETS) + WIDEST_DECLARED_SWEEP


def legs_of(preset: str) -> list[str]:
    """Sub-strategies of a preset; a plain (non-ensemble) preset is its own leg."""
    cfg = PRESETS[preset]
    subs = cfg.get("ensemble_substrategies")
    return list(subs) if subs else [preset]


# --- date / window handling -------------------------------------------------

def _as_date(value) -> dt.date:
    """Normalize a `datetime.date`, a `datetime.datetime` or an ISO string.

    Callers MUST have handled `None` before reaching here: `pd.Timestamp(None)`
    is `NaT`, and `NaT` compares `False` against every window bound, so a `None`
    would be *silently* dropped. That silence is exactly what CLAUDE.md §0
    forbids — so the drop is done explicitly (and counted) upstream.
    """
    if isinstance(value, dt.datetime):
        return value.date()
    return pd.Timestamp(value).date()


def _window_years(start: str, end: str) -> float:
    """Elapsed years over `[start, end]` — the ONE horizon annualization uses.

    Both the benchmark CAGR and every candidate's CAGR/stats enumerate over this
    same span, so `benchmark_excess_cagr = cagr - bench_cagr` subtracts two
    returns annualized over an identical horizon (CLAUDE.md §0 reproducibility).
    """
    return max(
        (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1.0 / 365.25
    )


def _sliced_equity(rows: list[dict], start: str, end: str) -> list[tuple[dt.date, float]]:
    """Sorted `(date, equity)` pairs inside `[start, end]`.

    The engine's `equity_curve` spans the BUFFERED panel window
    `[start-180d, end+60d]` (the engine sets no `feed.fromdate/todate` and
    `_metrics_from_holder` passes the recorder rows through unfiltered), so this
    slice is what makes EVERY stat reported here (Sharpe, CAGR, max_dd, Calmar)
    match the window the record is labelled with. The engine's own
    `result["cagr"]` annualizes the cash at the panel's LAST bar (`= end + 60d`)
    but divides by `(end - start)` — a horizon mismatch this slice removes.

    `date` may be `None` on the plain-preset path (`_metrics_from_holder` passes
    the recorder rows through; the recorder's date extraction catches broadly and
    can store `None`), while the ensemble path already filtered those out. A
    `None` is dropped EXPLICITLY and COUNTED here — "a day went missing with no
    one knowing" and "a day went missing and the log says so" are two different
    systems. Computed ONCE per candidate and reused for every derived stat.
    """
    lo = _as_date(start)
    hi = _as_date(end)
    kept: list[tuple[dt.date, float]] = []
    dropped_none = 0
    for row in rows:
        raw_date = row.get("date")
        if raw_date is None:
            dropped_none += 1
            continue
        d = _as_date(raw_date)
        if lo <= d <= hi:
            kept.append((d, float(row["equity"])))
    if dropped_none:
        print(
            f"[equity slice] WARNING: dropped {dropped_none} equity row(s) with "
            f"date=None (the plain-preset recorder path can store None); every "
            f"stat is computed on the rows that survived.",
            file=sys.stderr, flush=True,
        )
    kept.sort(key=lambda t: t[0])
    return kept


def _returns_from_slice(sliced: list[tuple[dt.date, float]]) -> list[float]:
    """Simple daily returns `equity[t]/equity[t-1] - 1` from a sorted slice."""
    return [b[1] / a[1] - 1.0 for a, b in zip(sliced, sliced[1:])]


def _windowed_returns(rows: list[dict], start: str, end: str) -> list[float]:
    """Daily returns inside `[start, end]` (slice then difference)."""
    return _returns_from_slice(_sliced_equity(rows, start, end))


def _window_cagr_max_dd(
    sliced: list[tuple[dt.date, float]], years: float,
) -> tuple[float, float]:
    """CAGR and max drawdown from the SAME sliced equity series.

    CAGR from first/last of the slice, annualized over `years`; max_dd from the
    running peak. Everything a record reports then shares one horizon. Returns
    `(nan, nan)` when the slice has fewer than two points (undefined).
    """
    if len(sliced) < 2:
        return float("nan"), float("nan")
    first = sliced[0][1]
    last = sliced[-1][1]
    cagr = (last / first) ** (1.0 / years) - 1.0 if first > 0 and years > 0 \
        else float("nan")
    peak = sliced[0][1]
    max_dd = 0.0
    for _, eq in sliced:
        if eq > peak:
            peak = eq
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    return cagr, max_dd


def daily_sharpe_from_equity(rows: list[dict], start: str, end: str) -> float:
    """Daily-equity Sharpe for `[start, end]`.

    Delegates the formula to `dna_stats.deflated.annualized_sharpe` — the single
    source — including its convention that an undefined Sharpe (constant equity)
    is NaN, not 0.0. Do NOT define a second Sharpe here (CLAUDE.md §6).
    """
    return annualized_sharpe(_windowed_returns(rows, start, end))


# --- JSON schema ------------------------------------------------------------

def candidate_record(
    *,
    preset: str,
    legs: list[str],
    is_reference: bool,
    cagr: float,
    max_dd: float,
    daily_sharpe: float | None,
    dsr: float,
    bonferroni_p: float,
    benchmark_excess_cagr: float,
) -> dict:
    """Assemble one `candidates[]` record from already-computed stats.

    A pure assembler: every numeric field is computed by `_build_record` from the
    ONE sliced equity series, so the record shares a single horizon. Extracted so
    the JSON schema can be unit-tested offline without running the multi-hour
    comparison batch.
    """
    calmar = (cagr / max_dd) if max_dd > 0 else float("nan")
    return {
        "preset": preset,
        "legs": list(legs),
        "is_reference": bool(is_reference),
        "cagr": float(cagr),
        "max_dd": float(max_dd),
        "calmar": calmar,
        "daily_sharpe": daily_sharpe,
        "dsr": float(dsr),
        "bonferroni_p": float(bonferroni_p),
        "benchmark_excess_cagr": float(benchmark_excess_cagr),
    }


def _json_safe(obj):
    """Recursively replace non-finite floats with None so the JSON is valid.

    `json.dump` would otherwise emit `NaN` / `Infinity`, which are not valid JSON
    and break strict readers.
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def write_json(payload: dict, out_dir: str | Path, output_name: str) -> Path:
    path = Path(out_dir) / output_name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


# --- mandatory guards (both scripts) ---------------------------------------

def _db_min_date(db_path: Path) -> object:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute("SELECT min(date) FROM raw_kline_daily").fetchone()[0]
    finally:
        con.close()


def guard_universes(presets: list[str], asof: str, db_path: Path) -> None:
    """Guard 1: every window's universe must be non-empty.

    `run_backtest_v3` does NOT trip the F-01 feed guard on an empty universe (an
    empty code list is a legal input) — it just returns 0 trades. Without this
    assertion the whole gate silently no-ops and the output *looks like* "the
    candidates don't work early", a false conclusion (spec §2.9).
    """
    modes = sorted({PRESETS[p]["universe"] for p in presets})
    for mode in modes:
        universe = load_universe_asof(mode, asof, db_path)
        if not universe:
            raise SystemExit(
                f"F-01 guard: universe mode {mode!r} at as-of {asof} is EMPTY "
                f"(db earliest date: {_db_min_date(db_path)}). An empty universe "
                f"is a legal run_backtest_v3 input and yields 0 trades, so the "
                f"run would be an invisible no-op."
            )
        print(f"universe[{mode}] @ {asof}: {len(universe)} codes", flush=True)


def guard_trades(preset: str, result: dict) -> None:
    """Guard 2: every candidate must produce > 0 trades.

    The three distinguishable zero-trade causes — empty universe, the `min_bars`
    cliff, and an F-01 feed guard trip — must not be collapsed into one silent 0.
    """
    if int(result.get("trades_count", 0)) == 0:
        raise SystemExit(
            f"F-01 guard: preset {preset!r} produced 0 trades (min_bars={MIN_BARS}). "
            f"Distinguish the cause: empty universe (see the universe guard line "
            f"above), a min_bars cliff, or an F-01 feed guard trip."
        )


# --- benchmark (§5 attribution) --------------------------------------------

def benchmark_cagr(db_path: Path, start: str, end: str) -> float:
    """Equal-weight buy-and-hold CAGR of the `mainboard_only` universe.

    §5 requires headline returns to be reported against a benchmark (index or
    style basket). The DB carries no index constituents (no HS300/CSI500 and no
    index daily series), so the honest available basket is an equal-weight
    buy-and-hold of the SAME point-in-time universe the candidates trade, valued
    on forward-adjusted close (`v_daily_hfq`), annualized over the window.
    """
    mode = PRESETS[CANDIDATE_PRESETS[0]]["universe"]
    universe = set(load_universe_asof(mode, start, db_path))
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT thscode, arg_min(close, date) AS c0, arg_max(close, date) AS c1, "
            "count(*) AS n FROM v_daily_hfq WHERE date BETWEEN ? AND ? "
            "GROUP BY thscode",
            [start, end],
        ).fetchall()
    finally:
        con.close()
    rets = [
        c1 / c0 - 1.0
        for code, c0, c1, n in rows
        if code in universe and n >= 2 and c0 and c0 > 0
    ]
    if not rets:
        raise SystemExit(
            f"benchmark guard: no usable prices for the {mode!r} universe over "
            f"[{start}, {end}] — cannot report §5 benchmark-relative excess."
        )
    mean_ret = sum(rets) / len(rets)
    years = _window_years(start, end)
    if mean_ret <= -1.0:
        return -1.0
    return (1.0 + mean_ret) ** (1.0 / years) - 1.0


# --- orchestration ----------------------------------------------------------

def _build_record(
    preset: str, result: dict, start: str, end: str,
    bench_cagr: float, n_trials: int,
) -> dict:
    # ONE slice of the ensemble's aggregated equity, reused for every §5 field.
    # The engine's `result["cagr"]`/`result["max_dd"]` are NOT used: they mark the
    # cash at the panel's LAST bar (`= end + PANEL_POST_BUFFER_DAYS`) but divide by
    # `(end - start)`, so they mix two horizons. Deriving from the slice makes
    # `benchmark_excess_cagr = cagr - bench_cagr` an in-window-vs-in-window figure.
    equity_rows = result["equity_curve"]
    sliced = _sliced_equity(equity_rows, start, end)
    rets = _returns_from_slice(sliced)
    daily_sharpe = annualized_sharpe(rets)
    n_returns = len(rets)
    cagr, max_dd = _window_cagr_max_dd(sliced, _window_years(start, end))

    if math.isfinite(daily_sharpe):
        # `sharpe_significance_pvalue`'s SE = 1/sqrt(T-1) is PER-PERIOD (its
        # docstring: "for daily returns") while `annualized_sharpe` returns an
        # ANNUALIZED Sharpe. Feeding the annualized value inflates z by sqrt(252)
        # and saturates p to 0.0 — "unconditionally family-wise significant" for a
        # series this same record's `dsr` can call insignificant. De-annualize at
        # the call site; this is the same §5 unit-consistency fix
        # `deflated_sharpe_ratio` already applies internally
        # (dna_stats/deflated.py:158-165). `deflated_sharpe_ratio` keeps the
        # annualized input because it de-annualizes internally.
        period_sharpe = daily_sharpe / math.sqrt(252)
        p = sharpe_significance_pvalue(period_sharpe, n_returns)
        dsr = deflated_sharpe_ratio(
            daily_sharpe, n_trials, n_returns=n_returns
        )["deflated_sharpe"]
        bonferroni_p = (
            float(bonferroni_correct([p], n_trials)[0])
            if math.isfinite(p) else float("nan")
        )
    else:
        dsr = float("nan")
        bonferroni_p = float("nan")

    # `annualized_sharpe` returns NaN for an undefined Sharpe; the schema says
    # `daily_sharpe` may be null, so NaN -> None (not 0.0).
    daily_sharpe_json = None if math.isnan(daily_sharpe) else float(daily_sharpe)

    return candidate_record(
        preset=preset,
        legs=legs_of(preset),
        is_reference=(preset == REFERENCE_PRESET),
        cagr=cagr,
        max_dd=max_dd,
        daily_sharpe=daily_sharpe_json,
        dsr=dsr,
        bonferroni_p=bonferroni_p,
        benchmark_excess_cagr=cagr - bench_cagr,
    )


def print_leg_overlap() -> None:
    """Explicit overlap table — spec R6: v44 is a leg of all three candidates, so
    the "three-way choice" is less independent than it looks."""
    print("candidate leg overlap (decision candidates only):", flush=True)
    legs_by_preset = {p: legs_of(p) for p in CANDIDATE_PRESETS}
    all_legs = sorted({leg for legs in legs_by_preset.values() for leg in legs})
    for leg in all_legs:
        owners = [p for p in CANDIDATE_PRESETS if leg in legs_by_preset[p]]
        marker = "  <-- shared by ALL three" if len(owners) == 3 else ""
        print(f"  {leg:<24} : {', '.join(owners)}{marker}", flush=True)
    for p in ALL_PRESETS:
        print(f"  {p:<20} legs = {legs_of(p)}", flush=True)


DECLARATION: str = (
    "DECLARATION (spec §5.7): 候选腿的参数选自 §3 价格域修复之前的搜索，其历史业绩"
    "数字在新语义下不成立。"
)


def run_comparison(
    start: str, end: str, db_path: Path, min_bars: int,
) -> dict:
    """Run all four presets on one window and assemble the compare payload."""
    guard_universes(ALL_PRESETS, start, db_path)
    bench = benchmark_cagr(db_path, start, end)
    print(f"benchmark (equal-weight mainboard basket, hfq) CAGR = {bench:.4f}",
          flush=True)

    n_trials = honest_n_trials()
    print(f"honest_n_trials = {n_trials} "
          f"(RESERVED {RESERVED} + len(PRESETS) {len(PRESETS)} + "
          f"widest_declared_sweep {WIDEST_DECLARED_SWEEP})", flush=True)

    candidates = []
    n_candidates = len(ALL_PRESETS)
    for i, preset in enumerate(ALL_PRESETS, 1):
        result = run_backtest_v3(preset, start, end, db_path, min_bars=min_bars)
        guard_trades(preset, result)
        rec = _build_record(preset, result, start, end, bench, n_trials)
        candidates.append(rec)
        # One line per candidate, flushed — for a ~3.6h unattended run this is the
        # only progress signal. Within a candidate (a single-leg backtest) there
        # is no output and that is normal; judge liveness by CPU, not by this.
        print(f"[{i}/{n_candidates}] {rec['preset']}: "
              f"cagr={rec['cagr']:.4f} max_dd={rec['max_dd']:.4f}", flush=True)

    return {
        "window": [start, end],
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_trials": n_trials,
        "candidates": candidates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--min-bars", type=int, default=MIN_BARS)
    args = parser.parse_args(argv)

    db_path = get_db_path()
    print(f"compare_ensembles: db={db_path} window=[{args.start}, {args.end}] "
          f"min_bars={args.min_bars}", flush=True)
    print_leg_overlap()
    print(DECLARATION, flush=True)

    payload = run_comparison(args.start, args.end, db_path, args.min_bars)
    path = write_json(payload, args.out, OUTPUT_NAME)
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
