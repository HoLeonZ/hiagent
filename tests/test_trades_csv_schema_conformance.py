"""§3 Backtest output schema conformance audit.

CLAUDE.md §3 Data Integrity: every backtest must produce a canonical
trades.csv with consistent schema across engines. Downstream analysis
(trade_report, render_html, sweep aggregation) cannot function if
columns differ.

CANONICAL schema (the chase_up/uptrend_pullback columns minus sub_signal_type):
  - entry_date, exit_date, thscode, exit_reason
  - entry_price, exit_price, size, hold_days
  - gross_pnl, fees, net_pnl, net_return
  - atr_pct (optional but documented)

Sub-signal_type is chase_up-specific (BREAKOUT/MOMENTUM/MACROSS) and
documented as such — accept its presence/absence.

§3 Audit matrix (FRESH 2026-09-23):

| Engine | Schema | PnL cols | Dates | Status |
|---|---|---|---|---|
| chase_up | 14 cols | ✓ gross/fees/net/return | ✓ entry+exit | ✓ CANONICAL+ |
| uptrend_pullback | 13 cols | ✓ gross/fees/net/return | ✓ entry+exit | ✓ CANONICAL |
| short_reversal v35-v43 | 8 cols | ✗ NO PnL | ✓ entry+exit | ✗ PnL DROPPED |
| short_reversal v44-v46 | 7 cols | net only | ✗ NO DATES | ✗ DIFFERENT SCHEMA |
| cycle_price_action | (none) | — | — | (no output produced) |

VIOLATIONS:
A. short_reversal v35-v43 trades.csv: 0 PnL columns — downstream
   analysis cannot compute Sharpe/CAGR/maxDD from trades.csv alone.
   Must include gross_pnl, fees, net_pnl, net_return.
B. short_reversal v44-v46 trades.csv: DIFFERENT schema (no dates,
   uses `net` not `net_pnl`). Should be deprecated or migrated.
C. chase_up has `sub_signal_type` (BREAKOUT/MOMENTUM/MACROSS) which
   is engine-specific. Should be either documented as optional or
   removed for cross-engine consistency.
"""
from __future__ import annotations

import csv
from pathlib import Path

# CANONICAL schema — required for downstream analysis
CANONICAL_REQUIRED = {
    "entry_date",
    "exit_date",
    "thscode",
    "exit_reason",
    "entry_price",
    "exit_price",
    "size",
    "hold_days",
    "gross_pnl",
    "fees",
    "net_pnl",
    "net_return",
}

CANONICAL_OPTIONAL = {"atr_pct", "sub_signal_type", "exit_time", "signal_date"}


def _read_csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        return next(reader, [])


def test_short_reversal_trades_have_pnl_columns() -> None:
    """§3 RED: short_reversal trades.csv MUST include PnL columns.

    v35-v43 trades.csv only has 8 columns (entry/exit metadata).
    No gross_pnl, fees, net_pnl, net_return. Downstream analysis
    cannot compute Sharpe/CAGR/maxDD from these files alone.
    """
    sr_trades_files = sorted(Path("short_reversal/results").glob("v3[5-9]_*trades*.csv"))
    sr_trades_files += sorted(Path("short_reversal/results").glob("v4[0-3]_*trades*.csv"))

    if not sr_trades_files:
        return  # No trades files to check

    missing_pnl_files: list[Path] = []
    for path in sr_trades_files:
        if not path.exists():
            continue
        header = _read_csv_header(path)
        pnl_cols = {"gross_pnl", "fees", "net_pnl", "net_return"}
        if not pnl_cols.intersection(header):
            missing_pnl_files.append(path)

    assert not missing_pnl_files, (
        "GAP CAPTURED: short_reversal v35-v43 trades.csv missing "
        "PnL columns (gross_pnl, fees, net_pnl, net_return). "
        "Downstream trade_report.py / render_html cannot compute "
        "Sharpe/CAGR/maxDD without these columns. Affected files:\n"
        + "\n".join(f"  - {p.name}" for p in missing_pnl_files[:10])
        + f"\n  ({len(missing_pnl_files)} total)"
    )


def test_short_reversal_v44_plus_use_canonical_schema() -> None:
    """§3 RED: short_reversal v44+ trades.csv should use canonical schema.

    v44+ files use `thscode,entry_price,exit_price,exit_reason,size,net,hold_days`
    — NO dates, `net` instead of `net_pnl`. This is a different schema.
    Either migrate to canonical OR document why v44+ is exception.
    """
    v44_files = sorted(Path("short_reversal/results").glob("v4[4-9]_*trades*.csv"))

    if not v44_files:
        return

    canonical_deviations: list[tuple[Path, set[str]]] = []
    canonical = {
        "entry_date", "exit_date", "thscode", "exit_reason",
        "entry_price", "exit_price", "size", "hold_days",
        "gross_pnl", "fees", "net_pnl", "net_return",
    }

    for path in v44_files:
        if not path.exists():
            continue
        header = set(_read_csv_header(path))
        missing = canonical - header
        if missing:
            canonical_deviations.append((path, missing))

    assert not canonical_deviations, (
        "GAP CAPTURED: short_reversal v44+ trades.csv uses non-canonical "
        "schema. Missing canonical columns:\n"
        + "\n".join(
            f"  - {p.name}: missing {sorted(m)}"
            for p, m in canonical_deviations[:5]
        )
    )


def test_chase_up_trades_canonical_with_optional_subsignal() -> None:
    """§3 PASS baseline: chase_up trades.csv uses canonical schema + sub_signal_type.

    Pin that chase_up is the canonical reference. It has all required
    columns PLUS `sub_signal_type` (engine-specific BREAKOUT/MOMENTUM/MACROSS).
    """
    canonical_files = sorted(Path("chase_up/results").glob("v*_trades.csv"))

    if not canonical_files:
        return

    # Pick first available
    sample = canonical_files[0]
    header = set(_read_csv_header(sample))

    missing = CANONICAL_REQUIRED - header
    extra = header - CANONICAL_REQUIRED - CANONICAL_OPTIONAL

    assert not missing, (
        f"Regression: chase_up {sample.name} missing canonical columns: {missing}"
    )
    # Allow `sub_signal_type` as documented engine-specific
    assert extra <= CANONICAL_OPTIONAL, (
        f"chase_up {sample.name} has undocumented extra columns: {extra}"
    )


def test_uptrend_pullback_trades_canonical_schema() -> None:
    """§3 PASS baseline: uptrend_pullback trades.csv uses canonical schema."""
    canonical_files = sorted(Path("uptrend_pullback/results").glob("v*_trades.csv"))

    if not canonical_files:
        return

    sample = canonical_files[0]
    header = set(_read_csv_header(sample))

    missing = CANONICAL_REQUIRED - header
    assert not missing, (
        f"Regression: uptrend_pullback {sample.name} missing canonical: {missing}"
    )


def test_no_engine_has_sub_signal_type_outside_chase_up() -> None:
    """§3 audit: sub_signal_type is chase_up-specific.

    Pin that no other engine emits sub_signal_type (it's BREAKOUT/
    MOMENTUM/MACROSS — semantic for chase_up only). If other engines
    emit it without semantics, downstream will misinterpret.
    """
    engines_with_trades = {
        "chase_up": list(Path("chase_up/results").glob("*trades*.csv")),
        "uptrend_pullback": list(Path("uptrend_pullback/results").glob("*trades*.csv")),
        "short_reversal": list(Path("short_reversal/results").glob("*trades*.csv")),
        "cycle_price_action": list(Path("cycle_price_action/results").glob("*trades*.csv")),
    }

    violations: list[tuple[str, Path]] = []
    for engine, paths in engines_with_trades.items():
        if engine == "chase_up":
            continue  # documented exception
        for path in paths:
            if not path.exists():
                continue
            header = _read_csv_header(path)
            if "sub_signal_type" in header:
                violations.append((engine, path))

    assert not violations, (
        "GAP CAPTURED: sub_signal_type is chase_up-specific (BREAKOUT/"
        "MOMENTUM/MACROSS) but emitted by other engines. Risk of "
        "downstream misinterpretation:\n"
        + "\n".join(f"  - {e}/{p.name}" for e, p in violations[:5])
    )