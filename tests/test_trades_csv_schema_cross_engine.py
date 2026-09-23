"""§3 Trades CSV schema divergence cross-engine audit (Tick 50).

CLAUDE.md §3 铁律 (relevant parts):
  - "Cash dividends must explicitly trigger a physical cash deposit into
    `Free_Cash`."
  - Cash walk conservation requires gross_pnl/fees/net_pnl/net_return
    columns to verify per-trade math closure.

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[trades-csv-schema-divergence]]:**

A. **short_reversal/results/ has 2 distinct schemas** (verified):
   - **8 files (v35-v43)**: 8 columns:
     [entry_date, exit_date, thscode, exit_reason, entry_price, exit_price,
      size, hold_days]
     - **MISSING** PnL columns: gross_pnl, fees, net_pnl, net_return
   - **3 files (v44+)**: 7 columns:
     [thscode, entry_price, exit_price, exit_reason, size, net, hold_days]
     - **MISSING** dates: entry_date, exit_date
     - **MISSING** canonical PnL: gross_pnl, fees, net_pnl, net_return

B. **Canonical schema (chase_up)** (verified):
   - 14 columns:
     [entry_date, exit_date, thscode, exit_reason, entry_price, exit_price,
      size, hold_days, gross_pnl, fees, net_pnl, net_return, atr_pct,
      sub_signal_type]
   - All v5 + v8-v19 chase_up files: 14 cols (consistent)

C. **Schema divergence quantified**:
   - 11/11 short_reversal trades.csv files: NON-CANONICAL
   - 8/11 files: 8-col (missing 6 cols from chase_up baseline)
   - 3/11 files: 7-col (missing 8 cols from chase_up baseline)
   - Internal drift: short_reversal itself diverges between v35-v43 (8-col)
     vs v44+ (7-col) — 2 different schemas in same engine

D. **Consequences**:
   - Per-trade math closure cannot be verified for short_reversal
     (no gross_pnl/fees/net_pnl → cannot check gross-fees-net=0 invariant)
   - Cash walk conservation cannot be verified for short_reversal
     (no per-trade breakdown)
   - v44+: cannot reconstruct timeline (no entry_date/exit_date)
   - v35-v43: cannot validate PnL magnitude (only prices + size)
   - Cross-engine comparison impossible (different column semantics)

E. **Numeric impact**:
   - Per [[cash-walk-and-metrics-provenance-gap]]: chase_up loses 19/22
     preset metrics (backtest.json single-overwrite)
   - short_reversal loses all per-trade PnL columns (cannot reconstruct)
   - Cannot verify CLAUDE.md §2 capital conservation per trade

本文件验证:
- 3 RED: short_reversal v35-v43 missing PnL cols, short_reversal v44+
  missing dates, short_reversal has 2 divergent schemas
- 2 PASS baseline: chase_up 14-col canonical schema + chase_up internal
  consistency
"""
from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trades_csv_files_in(engine: str) -> list[Path]:
    """Return all *trades*.csv files in <engine>/results/."""
    results_dir = REPO_ROOT / engine / "results"
    if not results_dir.exists():
        return []
    return sorted(results_dir.glob("*trades*.csv"))


def _read_header(path: Path) -> list[str]:
    """Read first row (header) of a CSV file. Returns empty list on empty file."""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as fp:
            reader = csv.reader(fp)
            return next(reader, [])
    except (OSError, UnicodeDecodeError):
        return []


# Canonical chase_up schema (14 columns)
CANONICAL_COLUMNS = {
    "entry_date", "exit_date", "thscode", "exit_reason",
    "entry_price", "exit_price", "size", "hold_days",
    "gross_pnl", "fees", "net_pnl", "net_return",
    "atr_pct", "sub_signal_type",
}


# ---------------------------------------------------------------------------
# RED: short_reversal schema divergence
# ---------------------------------------------------------------------------


def test_short_reversal_v35_v43_trades_missing_pnl_columns() -> None:
    """§3 RED: short_reversal v35-v43 trades.csv lack PnL columns.

    8 files (v35-v43) have 8-col schema:
      [entry_date, exit_date, thscode, exit_reason, entry_price,
       exit_price, size, hold_days]
    MISSING from canonical: gross_pnl, fees, net_pnl, net_return (4 cols)

    Without PnL columns, per-trade math closure (gross - fees = net)
    cannot be verified for short_reversal v35-v43 results.
    """
    files = _trades_csv_files_in("short_reversal")
    if not files:
        return  # structure changed

    # Group files by schema column count
    v35_v43_files = []  # 8-column schema
    for f in files:
        header = _read_header(f)
        if len(header) == 8:
            v35_v43_files.append((f, header))

    if not v35_v43_files:
        return  # GREEN — all files have richer schema

    # Check if all 8-col files are missing the 4 PnL columns
    missing_pnl = {"gross_pnl", "fees", "net_pnl", "net_return"}
    violations = []
    for f, header in v35_v43_files:
        header_set = set(header)
        absent = missing_pnl - header_set
        if absent:
            violations.append((f.name, sorted(absent)))

    if not violations:
        return  # GREEN — all 8-col files now have PnL cols

    sample = violations[0]
    raise AssertionError(
        f"GAP CAPTURED (RED): short_reversal has {len(violations)} trades.csv "
        f"files with 8-col schema missing PnL columns.\n"
        f"Sample: {sample[0]} missing {sample[1]}\n"
        f"Per [[trades-csv-schema-divergence]]: cannot verify per-trade "
        f"math closure for short_reversal v35-v43 results.\n"
        f"Compare chase_up canonical 14-col schema:\n"
        f"  {sorted(CANONICAL_COLUMNS)}\n"
        f"GREEN fix: add gross_pnl, fees, net_pnl, net_return columns to "
        f"short_reversal/portfolio.py trade recording logic."
    )


def test_short_reversal_v44_plus_trades_missing_date_columns() -> None:
    """§3 RED: short_reversal v44+ trades.csv lack entry_date/exit_date.

    3 files (v44, v45, v46) have 7-col schema:
      [thscode, entry_price, exit_price, exit_reason, size, net, hold_days]
    MISSING: entry_date, exit_date (and 6 other canonical cols)

    Without dates, cannot reconstruct trade timeline or verify temporal
    determinism (CLAUDE.md §1).
    """
    files = _trades_csv_files_in("short_reversal")
    if not files:
        return  # structure changed

    v44_plus_files = []
    for f in files:
        header = _read_header(f)
        if len(header) == 7 and "entry_date" not in header:
            v44_plus_files.append((f, header))

    if not v44_plus_files:
        return  # GREEN

    missing_dates = {"entry_date", "exit_date"}
    violations = []
    for f, header in v44_plus_files:
        absent = missing_dates - set(header)
        if absent:
            violations.append((f.name, sorted(absent)))

    if not violations:
        return  # GREEN

    sample = violations[0]
    raise AssertionError(
        f"GAP CAPTURED (RED): short_reversal has {len(violations)} trades.csv "
        f"files with 7-col schema missing date columns.\n"
        f"Sample: {sample[0]} missing {sample[1]}\n"
        f"Without dates, cannot reconstruct trade timeline or verify "
        f"CLAUDE.md §1 temporal determinism.\n"
        f"GREEN fix: add entry_date, exit_date columns to v44+ short_reversal "
        f"trade recording logic."
    )


def test_short_reversal_trades_schema_diverges_across_versions() -> None:
    """§3 RED: short_reversal trades.csv has 2 distinct schemas (internal drift).

    11 files split into 2 schemas (8-col vs 7-col) — same engine produces
    different CSV formats across versions. Cross-version comparison
    impossible without schema normalization.
    """
    files = _trades_csv_files_in("short_reversal")
    if not files:
        return  # structure changed

    schemas: dict[tuple[int, ...], list[str]] = {}
    for f in files:
        header = tuple(_read_header(f))
        if header:
            schemas.setdefault(header, []).append(f.name)

    if len(schemas) <= 1:
        return  # GREEN — all files have unified schema

    schema_summary = [
        (len(files_in_schema), header, files_in_schema[0])
        for header, files_in_schema in schemas.items()
    ]
    raise AssertionError(
        f"GAP CAPTURED (RED): short_reversal has {len(schemas)} distinct "
        f"trades.csv schemas across {len(files)} files. Internal drift.\n"
        f"Schemas:\n" +
        "\n".join(
            f"  {count}× files, {len(cols)} cols, sample={sample}\n"
            f"    cols: {list(cols)}"
            for count, cols, sample in schema_summary
        ) +
        f"\nGREEN fix: unify on canonical 14-col schema "
        f"(see chase_up canonical)."
    )


# ---------------------------------------------------------------------------
# PASS baselines: chase_up canonical schema + consistency
# ---------------------------------------------------------------------------


def test_chase_up_trades_schema_is_canonical_14_cols() -> None:
    """§3 PASS baseline: chase_up trades.csv has canonical 14-col schema.

    chase_up/results/v5_trades.csv + v8-v19 all have 14 cols:
      [entry_date, exit_date, thscode, exit_reason, entry_price, exit_price,
       size, hold_days, gross_pnl, fees, net_pnl, net_return, atr_pct,
       sub_signal_type]

    Pin compliance so chase_up doesn't accidentally regress to a
    short_reversal-style partial schema.
    """
    files = _trades_csv_files_in("chase_up")
    if not files:
        return  # structure changed

    # Check at least one file has canonical schema
    canonical_found = False
    for f in files:
        header = set(_read_header(f))
        if CANONICAL_COLUMNS.issubset(header):
            canonical_found = True
            break

    assert canonical_found, (
        "Regression: chase_up trades.csv no longer has canonical 14-col "
        "schema. CLAUDE.md §3 per-trade math + cash walk conservation "
        "requires gross_pnl, fees, net_pnl, net_return columns."
    )


def test_chase_up_trades_schema_consistent_across_versions() -> None:
    """§3 PASS baseline: chase_up trades.csv schema consistent across versions.

    chase_up internal consistency: all trades.csv files use same schema.
    No drift between v5, v8-v19. Anti-drift pin.
    """
    files = _trades_csv_files_in("chase_up")
    if not files:
        return  # structure changed

    schemas: dict[tuple[int, ...], list[str]] = {}
    for f in files:
        header = tuple(_read_header(f))
        if header:
            schemas.setdefault(header, []).append(f.name)

    # chase_up currently has 1 schema across all files
    assert len(schemas) == 1, (
        f"Regression: chase_up trades.csv has {len(schemas)} distinct "
        f"schemas across {len(files)} files. Internal drift detected."
    )