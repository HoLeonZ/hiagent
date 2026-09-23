"""§2 Cash Walk Conservation + §3 Metrics Provenance audit.

CLAUDE.md §2 Capital Determinism: per-trade net_pnl summed with
initial_cash MUST equal reported final_equity (cash walk conservation).

CLAUDE.md §3 Data Integrity: every backtest's metrics output must be
preserved per-preset (not single-overwrite), so cash walk can be
verified against the correct preset's trades.

§2/§3 Audit findings (FRESH 2026-09-23):

A. **backtest.json is single-overwrite** — only 1 file per engine
   (chase_up/results/backtest.json + uptrend_pullback/results/backtest.json).
   Each new run overwrites. Cannot audit cash walk for v3 trades
   against v3 metrics (v3 metrics were overwritten by v7).

B. **v3_trades.csv has 80 rows; current backtest.json shows 50 trades
   for v7 preset** — mismatch proves overwriting happened.

C. **No per-preset metrics directory structure** — results/ flat dumps
   trades.csv with preset name in filename but metrics.json doesn't
   follow same convention.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def test_chase_up_cash_walk_conservation() -> None:
    """§2 RED: chase_up cash walk conservation must hold.

    For each trades.csv in chase_up/results, verify:
      initial_cash + sum(trades.net_pnl) ≈ final_equity

    Cannot directly verify without per-preset metrics. Test must
    FIRST fix the metrics provenance issue (no per-preset metrics
    file exists). If we can't verify cash walk, this test stays RED.

    chase_up currently has only 1 backtest.json (overwritten). Cannot
    cross-check trades.csv against metrics.json. PASS criterion:
    each presets in results/ should have a corresponding
    `*_metrics.json` or similar per-preset file.
    """
    trades_files = sorted(Path("chase_up/results").glob("v*_trades.csv"))
    metrics_files = sorted(Path("chase_up/results").glob("v*_metrics.json"))

    if not trades_files:
        return

    # Per-preset metrics count must match per-preset trades count
    trades_preset_names = {f.stem.replace("_trades", "") for f in trades_files}
    metrics_preset_names = {f.stem.replace("_metrics", "") for f in metrics_files}

    missing_metrics = trades_preset_names - metrics_preset_names

    assert not missing_metrics, (
        "GAP CAPTURED: chase_up has trades.csv for "
        f"{len(trades_preset_names)} presets but only "
        f"{len(metrics_preset_names)} per-preset metrics files. "
        "Cannot verify cash walk conservation (per-preset metrics lost). "
        f"Missing metrics for: {sorted(missing_metrics)[:5]}..."
    )


def test_uptrend_pullback_cash_walk_conservation() -> None:
    """§2 RED: uptrend_pullback cash walk conservation must hold."""
    trades_files = sorted(Path("uptrend_pullback/results").glob("v*_trades.csv"))
    metrics_files = sorted(Path("uptrend_pullback/results").glob("v*_metrics.json"))

    if not trades_files:
        return

    trades_preset_names = {f.stem.replace("_trades", "") for f in trades_files}
    metrics_preset_names = {f.stem.replace("_metrics", "") for f in metrics_files}

    missing_metrics = trades_preset_names - metrics_preset_names

    assert not missing_metrics, (
        "GAP CAPTURED: uptrend_pullback has trades.csv for "
        f"{len(trades_preset_names)} presets but no per-preset metrics. "
        "Single backtest.json overwrites on each run — metrics "
        "provenance lost. Cannot audit cash walk."
    )


def test_short_reversal_cash_walk_verifiable() -> None:
    """§2 RED: short_reversal cash walk must be verifiable.

    short_reversal JSON uses `trades: [...]` LIST (per-trade dicts)
    per [[equity-curve-and-metrics-schema-gap]]. To verify cash walk,
    we need: initial_cash + sum(net_pnl) = final_equity, but
    `final_equity` is NOT in the JSON. Cannot compute cash walk.
    """
    sr_json_files = list(Path("short_reversal/results").glob("*.json"))
    if not sr_json_files:
        return

    sr_json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    sample = sr_json_files[0]
    data = _load_json(sample)
    if data is None:
        return

    has_final_equity = "final_equity" in data
    has_aggregated = "trades" in data and isinstance(data["trades"], int)

    if not has_final_equity and not has_aggregated:
        raise AssertionError(
            "GAP CAPTURED: short_reversal JSON has per-trade list "
            f"(`trades: [...]`) but NO aggregated metrics. Cannot "
            f"verify cash walk conservation (no final_equity field). "
            f"Sample: {sample.name}"
        )


def test_every_backtest_produces_metrics_with_same_preset_name() -> None:
    """§3 RED: backtest.json filename must encode preset for provenance.

    Currently backtest.json is a single fixed filename. After 22
    preset runs, only the LAST preset's metrics survive. This breaks
    §3 Data Integrity (cannot trace which metrics came from which
    trades).
    """
    engines_with_metrics = ["chase_up", "uptrend_pullback"]
    violations: list[tuple[str, Path]] = []

    for engine in engines_with_metrics:
        results_dir = Path(engine) / "results"
        if not results_dir.exists():
            continue
        # Look for any "backtest.json" or "metrics.json" that doesn't
        # encode preset name
        for json_path in results_dir.glob("*.json"):
            if json_path.name in {"backtest.json", "metrics.json"}:
                violations.append((engine, json_path))

    assert not violations, (
        "GAP CAPTURED: single-overwrite metrics.json files exist:\n"
        + "\n".join(f"  - {e}/{p.name}" for e, p in violations)
        + "\nEvery backtest run overwrites the previous metrics. "
        "Cannot audit cash walk or trace metrics provenance. "
        "GREEN fix: rename to `{preset_name}_metrics.json` or "
        "embed preset_name + timestamp in filename."
    )