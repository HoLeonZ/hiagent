"""§2/§3 Backtest metrics output + equity curve audit.

CLAUDE.md §2 Capital Determinism: every backtest must produce an
equity_curve.csv (NAV trajectory) so that NAV Gate behavior can be
verified, maxDD can be computed from the series (not from PnL alone),
and cash walk conservation can be audited.

CLAUDE.md §3 Data Integrity: aggregated metrics.json schema must be
canonical across engines for downstream comparison.

§2/§3 Audit matrix (FRESH 2026-09-23):

| Engine | aggregated metrics.json | equity_curve.csv | Schema |
|---|---|---|---|
| chase_up | ✓ backtest.json | ✗ MISSING | ✓ CANONICAL |
| uptrend_pullback | ✓ backtest.json | ✗ MISSING | ✓ CANONICAL |
| short_reversal | ✗ trades:[{net: ...}] | ✗ MISSING | ✗ DIFFERENT (no aggregated metrics) |
| cycle_price_action | ✗ NO OUTPUT | ✗ NO OUTPUT | (fail-fast blocks) |

VIOLATIONS:
A. NO engine produces equity_curve.csv — cannot verify cash walk,
   cannot compute accurate maxDD series, cannot audit NAV Gate.
B. short_reversal JSON has `trades: [...]` LIST instead of aggregated
   metrics — cannot compare Sharpe/CAGR across engines via JSON.
C. cycle_price_action produces NO output (fail-fast blocks).
"""
from __future__ import annotations

import json
from pathlib import Path


# CANONICAL aggregated metrics — required for cross-engine comparison
CANONICAL_METRICS = {
    "trades",
    "win_rate",
    "final_equity",
    "total_return",
    "cagr",
    "sharpe",
    "max_dd",
}


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def test_every_engine_produces_equity_curve_csv() -> None:
    """§2 RED: every engine must produce equity_curve.csv for NAV audit.

    Currently NO engine produces equity_curve.csv. Without it:
    - Cannot verify NAV floor / NAV Gate behavior over time
    - Cannot compute true maxDD from time series
    - Cannot audit cash walk conservation (sum(trades.pnl) = final_equity - initial_cash)
    """
    engines = ["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]
    missing: list[tuple[str, Path]] = []

    for engine in engines:
        results_dir = Path(engine) / "results"
        if not results_dir.exists():
            missing.append((engine, results_dir))
            continue
        equity_files = list(results_dir.glob("**/equity*.csv"))
        if not equity_files:
            # Also accept any CSV with "equity" or "nav" in the name
            any_equity = [
                p for p in results_dir.rglob("*.csv")
                if "equity" in p.name.lower() or "nav" in p.name.lower()
            ]
            if not any_equity:
                missing.append((engine, results_dir))

    assert not missing, (
        "GAP CAPTURED: NO engine produces equity_curve.csv. §2 NAV "
        "audit impossible. Cannot verify cash walk conservation, "
        "accurate maxDD series, or NAV Gate behavior. Engines affected:\n"
        + "\n".join(f"  - {e}: {p}" for e, p in missing)
    )


def test_short_reversal_json_has_aggregated_metrics() -> None:
    """§3 RED: short_reversal JSON output should have aggregated metrics.

    Currently short_reversal emits `trades: [...]` LIST (per-trade dicts).
    No aggregated metrics like `trades, win_rate, final_equity, cagr,
    sharpe, max_dd`. Cannot compare across engines via JSON.

    chase_up + uptrend_pullback use canonical aggregated metrics schema.
    short_reversal should match.
    """
    sr_json_files = list(Path("short_reversal/results").glob("*.json"))
    if not sr_json_files:
        return

    # Find most recent (newest)
    sr_json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    sample = sr_json_files[0]
    data = _load_json(sample)
    if data is None:
        return

    has_aggregated = "trades" in data and isinstance(data["trades"], int)
    # If "trades" is int → aggregated count. If list → per-trade dicts.
    has_trade_list = "trades" in data and isinstance(data["trades"], list)

    if has_trade_list and not has_aggregated:
        raise AssertionError(
            "GAP CAPTURED: short_reversal JSON output uses `trades: [...]` "
            "LIST schema (per-trade dicts). No aggregated metrics like "
            f"`final_equity, cagr, sharpe, max_dd`. Sample: {sample.name}. "
            "GREEN fix: emit both — aggregated metrics at top level + "
            "trades array (or canonical metrics + separate trades.csv)."
        )


def test_canonical_metrics_schema_pinned() -> None:
    """§3 PASS baseline: chase_up + uptrend_pullback backtest.json use
    canonical aggregated metrics schema with required fields.

    chase_up backtest.json keys: trades, win_rate, final_equity, total_return,
    cagr, sharpe, max_dd, avg_hold_days, max_hold_days, overrun_count,
    tp_count, sl_count, time_count, eod_count, avg_net_return,
    profit_factor, exposure, start, end, signals, preset, engine
    """
    canonical_files = [
        Path("chase_up/results/backtest.json"),
        Path("uptrend_pullback/results/backtest.json"),
    ]

    for path in canonical_files:
        if not path.exists():
            continue
        data = _load_json(path)
        if data is None:
            continue

        missing = CANONICAL_METRICS - set(data.keys())
        assert not missing, (
            f"Regression: {path} no longer has canonical metrics. "
            f"Missing: {missing}"
        )


def test_no_engine_emits_per_trade_dicts_only() -> None:
    """§3 audit: no engine should ONLY emit per-trade dicts.

    Pin that every engine emitting JSON should include aggregated
    metrics at top level (even if it also includes trades list).

    This is forward-defense: future versions of any engine emitting
    only per-trade dicts would fail this test.
    """
    engines = ["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]
    violations: list[tuple[str, Path]] = []

    for engine in engines:
        results_dir = Path(engine) / "results"
        if not results_dir.exists():
            continue
        json_files = list(results_dir.glob("*.json"))
        for path in json_files:
            data = _load_json(path)
            if data is None:
                continue
            # If only has `trades` as list (no aggregated fields) → violation
            if (
                isinstance(data.get("trades"), list)
                and "final_equity" not in data
                and "sharpe" not in data
            ):
                violations.append((engine, path))

    assert not violations, (
        "GAP CAPTURED: engines emitting per-trade dicts without "
        "aggregated metrics:\n"
        + "\n".join(f"  - {e}/{p.name}" for e, p in violations)
    )