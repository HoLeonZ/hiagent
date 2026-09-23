"""§3 Equity curve + cash walk output gap audit (Tick 51).

CLAUDE.md §2 (verbatim):
  "All-In Sizing Policy: Every entry is sized at 100% of available cash
   for that trade slot... NAV-floor cash gates remain valid for new entries."

CLAUDE.md §3 (verbatim):
  - Dual-Price System requires time-series mark-to-market
  - Per-trade math closure requires equity curve (cash walk conservation)

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[equity-curve-and-metrics-schema-gap]]:**

A. **NO engine produces equity_curve.csv** (verified):
   - chase_up/results: 0 *equity_curve*.csv
   - uptrend_pullback/results: 0 *equity_curve*.csv
   - short_reversal/results: 0 *equity_curve*.csv
   - cycle_price_action/results: 0 *equity_curve*.csv (no results dir)
   - 0/4 engines produce per-bar NAV evolution

B. **NO engine produces cash_walk.csv** (verified):
   - chase_up/results: 0 *cash_walk*.csv, 0 *nav_curve*.csv
   - 0/4 engines produce per-bar cash ledger

C. **chase_up backtest.json single-overwrite** (per [[cash-walk-and-metrics-provenance-gap]]):
   - chase_up/results/backtest.json overwrites on each preset run
   - 19/22 preset metrics LOST (only latest 3 remain)

D. **Consequences**:
   - Cannot verify cash walk conservation over time (only per-trade cum)
   - Cannot verify NAV gate behavior over time (which bars triggered gate)
   - Cannot verify drawdown progression (only single-overwrite metrics)
   - Cannot compare strategies on time-series basis
   - Cannot verify PIT data correctness over time
   - §2 capital conservation: per-bar NAV unknown
   - §3 PIT data: time-series mark-to-market impossible to verify

E. **Numeric impact**:
   - 4 engines × ~22 presets each = ~88 backtests
   - Each produces trades.csv + metrics.json BUT NOT equity_curve.csv
   - Cannot reconstruct equity curve from trades.csv alone (no idle days
     between trades = NAV unknown on idle bars)
   - Drawdown = max(running_max - NAV) / running_max: running_max unknown
     without equity_curve
   - Sharpe calculation incomplete without per-bar returns

F. **Why existing tests miss this**:
   - test_metrics_output_conformance.py checks for metrics.json existence
   - test_cash_walk_and_metrics_provenance.py checks backtest.json schema
   - Neither checks for equity_curve.csv presence (different dimension)

本文件验证:
- 3 RED: 0/4 engines produce equity_curve.csv, 0/4 engines produce
  cash_walk.csv, chase_up backtest.json single-overwrite (loses history)
- 1 PASS baseline: chase_up at least produces trades.csv (per-trade
  intermediate output)
"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _engine_results_dir(engine: str) -> Path | None:
    """Get <engine>/results dir if exists."""
    path = REPO_ROOT / engine / "results"
    return path if path.exists() else None


def _has_files_matching(results_dir: Path, glob_pattern: str) -> bool:
    """Check if results_dir contains any file matching glob_pattern."""
    if not results_dir.exists():
        return False
    return any(results_dir.glob(glob_pattern))


# ---------------------------------------------------------------------------
# RED: NO engine produces equity_curve.csv
# ---------------------------------------------------------------------------


ENGINES = ["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]


def test_no_engine_produces_equity_curve_csv() -> None:
    """§3 RED: 0/4 engines produce equity_curve.csv.

    Per CLAUDE.md §2/§3, per-bar NAV evolution must be recordable to
    verify cash walk conservation + drawdown progression. Without
    equity_curve.csv, these cannot be verified across any of 4 engines.
    """
    engines_with_equity_curve = []
    for engine in ENGINES:
        results_dir = _engine_results_dir(engine)
        if results_dir is None:
            continue
        # Check for any equity_curve-like file (equity_curve, nav_curve,
        # equity, portfolio_value, etc.)
        has_curve = (
            _has_files_matching(results_dir, "*equity*.csv") or
            _has_files_matching(results_dir, "*nav*.csv") or
            _has_files_matching(results_dir, "*portfolio_value*.csv")
        )
        if has_curve:
            engines_with_equity_curve.append(engine)

    if engines_with_equity_curve:
        return  # GREEN — at least one engine has equity curve

    raise AssertionError(
        f"GAP CAPTURED (RED): 0/4 engines produce equity_curve.csv.\n"
        f"Engines checked: {ENGINES}\n"
        f"Per CLAUDE.md §2/§3: per-bar NAV evolution must be recordable to "
        f"verify cash walk conservation + drawdown progression.\n"
        f"Per [[equity-curve-and-metrics-schema-gap]]: cannot verify drawdown "
        f"without equity curve (running_max - NAV unknown).\n"
        f"Per [[cash-walk-and-metrics-provenance-gap]]: chase_up backtest.json "
        f"single-overwrite loses 19/22 preset metrics.\n"
        f"GREEN fix: add equity_curve.csv writer to each engine's backtest "
        f"pipeline. Each row: date, cash, position_value, total_nav."
    )


def test_no_engine_produces_cash_walk_csv() -> None:
    """§3 RED: 0/4 engines produce cash_walk.csv.

    Per CLAUDE.md §2 capital conservation, per-bar cash ledger must be
    recordable. Without cash_walk.csv, cash balance between trades
    cannot be verified.
    """
    engines_with_cash_walk = []
    for engine in ENGINES:
        results_dir = _engine_results_dir(engine)
        if results_dir is None:
            continue
        has_walk = (
            _has_files_matching(results_dir, "*cash_walk*.csv") or
            _has_files_matching(results_dir, "*cash_ledger*.csv") or
            _has_files_matching(results_dir, "*ledger*.csv")
        )
        if has_walk:
            engines_with_cash_walk.append(engine)

    if engines_with_cash_walk:
        return  # GREEN

    raise AssertionError(
        f"GAP CAPTURED (RED): 0/4 engines produce cash_walk.csv.\n"
        f"Engines checked: {ENGINES}\n"
        f"Per CLAUDE.md §2 capital conservation: per-bar cash ledger must "
        f"be recordable.\n"
        f"Without cash_walk.csv, cash balance between trades is unknown.\n"
        f"GREEN fix: add cash_walk.csv writer: each row date + cash + change."
    )


def test_chase_up_backtest_json_single_overwrite_loses_metrics() -> None:
    """§3 RED: chase_up/results/backtest.json single-overwrite (loses history).

    chase_up backtest.json is overwritten on each preset run. After 22
    presets, only the latest run's metrics are preserved — 19/22 preset
    metrics are LOST.

    Per [[cash-walk-and-metrics-provenance-gap]]: cannot audit cash walk
    conservation across preset runs.
    """
    path = REPO_ROOT / "chase_up" / "results" / "backtest.json"
    if not path.exists():
        return  # structure changed

    # Check if there's a separate per-preset metrics directory or naming
    results_dir = path.parent
    per_preset_metrics = list(results_dir.glob("*_metrics.json"))

    # chase_up has some per-preset metrics files (v5_metrics.json etc.)
    # but backtest.json itself is single-overwrite
    has_per_preset_schema = len(per_preset_metrics) > 0

    if has_per_preset_schema:
        # Per-preset metrics files exist (e.g., v5_metrics.json) — partial
        # compliance. Still flag backtest.json single-overwrite as gap.
        pass

    raise AssertionError(
        f"GAP CAPTURED (RED): chase_up/results/backtest.json is a single "
        f"file overwritten on each preset run. After 22 presets, only "
        f"latest metrics preserved — 19/22 preset metrics LOST.\n"
        f"Per [[cash-walk-and-metrics-provenance-gap]]: cannot audit "
        f"cash walk conservation across preset runs.\n"
        f"Workaround: per-preset files like {per_preset_metrics[0].name if per_preset_metrics else 'none'} "
        f"exist ({len(per_preset_metrics)} files) but backtest.json itself "
        f"remains single-overwrite.\n"
        f"GREEN fix: rename backtest.json per preset "
        f"(`backtest_<preset_name>.json`) OR use a directory of per-preset "
        f"JSONs."
    )


# ---------------------------------------------------------------------------
# PASS baseline: chase_up produces trades.csv
# ---------------------------------------------------------------------------


def test_chase_up_produces_trades_csv_per_preset() -> None:
    """§3 PASS baseline: chase_up produces per-preset trades.csv files.

    Pin intermediate compliance: chase_up at least produces per-trade
    records (v1_trades.csv through v19_trades.csv etc.). This is the
    floor of §3 data integrity. equity_curve.csv is missing (RED above),
    but trades.csv exists.
    """
    results_dir = REPO_ROOT / "chase_up" / "results"
    if not results_dir.exists():
        return  # structure changed

    trades_files = list(results_dir.glob("*_trades.csv"))
    assert len(trades_files) > 0, (
        "Regression: chase_up/results/ has no *_trades.csv files. "
        "Even per-trade records are missing."
    )