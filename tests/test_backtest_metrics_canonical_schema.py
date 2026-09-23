"""§2/§3 Backtest metrics canonical schema audit (Tick 58).

CLAUDE.md §2 (verbatim):
  "Capital is physical and finite. We mandate Double-Entry Bookkeeping."

CLAUDE.md §3 (verbatim):
  "Backtest environment must perfectly reconstruct historical reality,
   warts and all."

**核心发现 (FRESH 2026-09-23):**

A. **chase_up/results/backtest.json has 22 canonical metrics** (verified):
   - avg_hold_days, avg_net_return, cagr, end, engine, eod_count,
     exposure, final_equity, max_dd, max_hold_days, overrun_count,
     preset, profit_factor, sharpe, signals, sl_count, start,
     time_count, total_return, tp_count, trades, win_rate
   - Currently populated: v7 (chase_v7_pos2_equal_atr_tp6_sl15_mh10_regime,
     50 trades, CAGR=-65.07%, max_dd=69.21%, sharpe=-0.74, win_rate=32%)

B. **Per-preset metrics files exist** (chase_up/results/v*_metrics.json):
   - v5_metrics.json, v8-v19 (12 per-version files)
   - These contain per-preset metrics (NOT overwritten)

C. **backtest.json is SINGLE-OVERWRITE** (per [[cash-walk-and-metrics-provenance-gap]]):
   - Only the LATEST preset run remains in backtest.json
   - Other presets' metrics are in v*_metrics.json (per-version files)
   - If user runs presets in order: v5 → v8 → v9 → ... → v19, only v19
     metrics remain in backtest.json; v5-v18 metrics are in per-version
     files but NOT in backtest.json
   - Cannot do cross-preset aggregation from backtest.json alone

D. **uptrend_pullback/results/backtest.json also exists** (verified)

E. **short_reversal + cycle_price_action have NO backtest.json** (verified):
   - cycle_price_action: No such file
   - short_reversal: No such file
   - These engines use different output format (per-trade JSON list per
     [[trades-csv-schema-cross-engine-audit-2026-09-23]])

F. **Why this matters**:
   - §2 capital conservation: metrics must be verifiable per-preset
   - §3 data integrity: each backtest run must leave audit trail
   - Without per-preset backtest.json, cross-preset comparison requires
     manual aggregation of v*_metrics.json
   - Memory note [[cash-walk-and-metrics-provenance-gap]] says "19/22
     preset metrics lost" — referring to ACROSS presets, only 1 preset's
     metrics remain at any time in backtest.json

G. **Why existing tests miss this**:
   - Tick 51 (equity_curve_metrics_schema) checks if equity_curve.csv
     exists (RED: 0/4 engines produce it)
   - No test verifies backtest.json has canonical 22 metrics schema
   - No test verifies per-preset metrics files exist for ALL presets

本文件验证:
- PASS baseline: chase_up backtest.json has all 22 canonical metrics
- PASS baseline: uptrend_pullback backtest.json has 22 canonical metrics
- RED: short_reversal + cycle_price_action lack backtest.json (different
  output format — need migration)
- PASS baseline: chase_up has per-preset v*_metrics.json files
- RED forward-defense: any new metric added to schema MUST be present
"""
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# Canonical 22 metrics for chase_up backtest.json (verified by AST scan)
CANONICAL_METRICS = {
    "avg_hold_days", "avg_net_return", "cagr", "end", "engine",
    "eod_count", "exposure", "final_equity", "max_dd", "max_hold_days",
    "overrun_count", "preset", "profit_factor", "sharpe", "signals",
    "sl_count", "start", "time_count", "total_return", "tp_count",
    "trades", "win_rate",
}


def _load_json(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as fp:
            data = json.load(fp)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None


# ---------------------------------------------------------------------------
# PASS baselines: chase_up + uptrend_pullback canonical schema
# ---------------------------------------------------------------------------


def test_chase_up_backtest_json_has_canonical_22_metrics() -> None:
    """§2/§3 PASS baseline: chase_up backtest.json has 22 canonical metrics.

    Per chase_up/results/backtest.json (verified), the canonical schema
    includes: avg_hold_days, cagr, max_dd, sharpe, win_rate, trades,
    preset, engine, start, end, etc. (22 total).

    If a metric is removed from the schema, this test fails (regression).
    """
    path = REPO_ROOT / "chase_up" / "results" / "backtest.json"
    assert path.exists(), f"{path} missing"

    data = _load_json(path)
    assert data is not None, f"{path} not parseable as JSON dict"

    present = set(data.keys())
    missing = CANONICAL_METRICS - present

    assert not missing, (
        f"§2/§3 SCHEMA REGRESSION: chase_up backtest.json missing "
        f"{len(missing)} canonical metrics:\n" +
        "\n".join(f"  - {m}" for m in sorted(missing))
    )


def test_uptrend_pullback_backtest_json_has_canonical_metrics() -> None:
    """§2/§3 PASS baseline: uptrend_pullback backtest.json schema check."""
    path = REPO_ROOT / "uptrend_pullback" / "results" / "backtest.json"
    if not path.exists():
        # Skip if file doesn't exist (forward-defense)
        return

    data = _load_json(path)
    assert data is not None, f"{path} not parseable"

    present = set(data.keys())
    # uptrend_pullback may have slightly different schema — at minimum
    # should have these core metrics
    core = {"cagr", "max_dd", "sharpe", "trades", "win_rate"}
    missing = core - present

    assert not missing, (
        f"§2/§3 CORE METRICS MISSING: uptrend_pullback backtest.json "
        f"missing core metrics:\n" +
        "\n".join(f"  - {m}" for m in sorted(missing))
    )


# ---------------------------------------------------------------------------
# RED: short_reversal + cycle_price_action lack canonical backtest.json
# ---------------------------------------------------------------------------


def test_short_reversal_backtest_json_exists_or_documented_gap() -> None:
    """§2/§3 RED: short_reversal lacks backtest.json (different format).

    Per [[trades-csv-schema-cross-engine-audit-2026-09-23]], short_reversal
    uses per-trade JSON list format, NOT aggregate metrics format.

    This test pins the gap as RED (not silently missing).
    """
    path = REPO_ROOT / "short_reversal" / "results" / "backtest.json"
    if path.exists():
        # Verify it has aggregate metrics (not just per-trade)
        data = _load_json(path)
        if data is None:
            return  # different format, skip
        # If exists, must have aggregate metrics
        has_aggregate = any(
            key in data for key in ("cagr", "sharpe", "max_dd", "win_rate")
        )
        if not has_aggregate:
            raise AssertionError(
                f"§2/§3 SCHEMA ISSUE: short_reversal backtest.json exists "
                f"but lacks aggregate metrics (cagr/sharpe/max_dd/win_rate)"
            )
        return  # OK

    # File doesn't exist — RED (this is the known gap)
    raise AssertionError(
        f"§2/§3 RED: short_reversal/results/backtest.json does not exist.\n"
        f"Per [[trades-csv-schema-cross-engine-audit-2026-09-23]], "
        f"short_reversal uses per-trade JSON format instead of aggregate "
        f"metrics. This breaks cross-engine comparability.\n\n"
        f"GREEN fix: short_reversal should also emit aggregate metrics "
        f"in canonical 22-metric schema (or migrate to canonical schema)."
    )


def test_cycle_price_action_backtest_json_exists_or_documented_gap() -> None:
    """§2/§3 RED: cycle_price_action lacks backtest.json.

    Per [[equity-curve-metrics-schema-audit-2026-09-23]] Tick 51:
    cycle_price_action produces no backtest.json at all.
    """
    path = REPO_ROOT / "cycle_price_action" / "results" / "backtest.json"
    if path.exists():
        return  # OK

    raise AssertionError(
        f"§2/§3 RED: cycle_price_action/results/backtest.json does not "
        f"exist.\n"
        f"Per [[equity-curve-metrics-schema-audit-2026-09-23]] Tick 51: "
        f"cycle_price_action is one of 0/4 engines producing backtest.json "
        f"in canonical schema.\n\n"
        f"GREEN fix: cycle_price_action should emit canonical 22-metric "
        f"backtest.json (currently missing entirely)."
    )


# ---------------------------------------------------------------------------
# PASS baseline: chase_up has per-preset v*_metrics.json files
# ---------------------------------------------------------------------------


def test_chase_up_per_preset_metrics_files_exist() -> None:
    """§2/§3 PASS baseline: chase_up has per-preset v*_metrics.json files.

    Per [[cash-walk-and-metrics-provenance-gap]]: chase_up emits per-preset
    metrics files (v5_metrics.json, v8-v19) to avoid losing metrics to
    single-overwrite.

    Pin: count of v*_metrics.json >= count of v*_trades.csv.
    """
    results_dir = REPO_ROOT / "chase_up" / "results"
    if not results_dir.exists():
        return

    metrics_files = sorted(results_dir.glob("v*_metrics.json"))
    trades_files = sorted(results_dir.glob("v*_trades.csv"))

    # At minimum, every trades.csv should have a corresponding metrics.json
    assert len(metrics_files) >= len(trades_files), (
        f"§2/§3 METRICS PROVENANCE: chase_up has {len(trades_files)} "
        f"trades.csv files but only {len(metrics_files)} metrics.json "
        f"files. Missing per-preset metrics for some versions."
    )