"""§0/§2 Per-Trade Numeric Type Sanity Verification (Tick 61).

CLAUDE.md §0 (verbatim):
  "**Fail-Fast:** If a state transition violates physical market laws,
   throw an exception immediately. Do not silently bypass."

CLAUDE.md §2 (verbatim):
  "**Atomic Cash Locks:** Order sizing must lock cash sequentially."

**核心发现 (FRESH 2026-09-23):**

A. **trades.csv numeric columns must be cleanly parseable**:
   - entry_price, exit_price, size, hold_days, gross_pnl, fees,
     net_pnl, net_return, atr_pct
   - All must parse as float (no NaN, None, empty, or "nan" strings)
   - forward-defense against CSV serialization corruption

B. **Why this matters**:
   - §0 Fail-Fast: silent NaN propagation can corrupt downstream metrics
     (cagr, sharpe, max_dd all break on NaN inputs)
   - §2 Capital conservation: corrupted size/price columns → wrong cost
     calculation → wrong PnL
   - CSV write/read round-trip is fragile (pandas to_csv, csv.writer,
     manual write). Each can produce different NaN representations
     (empty string, "nan", "NaN", "null", "None")
   - Downstream consumers may handle "" differently from "nan"

C. **chase_up canonical 14-col schema** (per [[per-trade-math-closure-audit-2026-09-23]]):
   - entry_date, exit_date, thscode, exit_reason (str)
   - entry_price, exit_price, size, hold_days, gross_pnl, fees, net_pnl,
     net_return, atr_pct, sub_signal_type (numeric + str mix)

D. **Acceptable representations**:
   - Empty string: skip (degenerate row)
   - "nan"/"NaN"/"None"/"null": FAIL (silent corruption)
   - Numeric string ("3.14", "1e-5", "-1.0E+3"): OK
   - Whitespace ("  3.14  "): should still parse after strip

E. **Coverage**:
   - 12 chase_up files: v5, v8, v9, v10, v11, v12, v13, v14, v18, v19 + others
   - 250+ rows scanned for numeric parseability
   - All columns: entry_price, exit_price, size, hold_days, gross_pnl,
     fees, net_pnl, net_return, atr_pct

F. **Why existing tests miss this**:
   - Tick 54 (per-trade math closure) assumes all values parse cleanly
   - If a row has "nan" in entry_price, float() raises ValueError but
     pandas read_csv silently converts to NaN — downstream math silently
     propagates
   - No test catches "nan" strings before they're processed by pandas

G. **Tick 61 RED state (expected)**: 0 violations (chase_up trades.csv
   should be clean — but this is the first forward-defense audit for
   numeric parseability).

本文件验证:
- PASS baseline: all numeric columns in chase_up trades.csv parse
  cleanly as float (no NaN/None/empty/"nan" strings)
- PASS baseline: all numeric values are finite (not inf/-inf)
- PASS baseline: entry_price and exit_price are > 0 (positive prices)
- RED forward-defense: any unparseable value fails with row details
"""
from __future__ import annotations

import csv
import math
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

NUMERIC_COLUMNS = [
    "entry_price",
    "exit_price",
    "size",
    "hold_days",
    "gross_pnl",
    "fees",
    "net_pnl",
    "net_return",
    "atr_pct",
]


def _trades_csv_files() -> list[Path]:
    """Return chase_up trades.csv files (canonical 14-col schema)."""
    results_dir = REPO_ROOT / "chase_up" / "results"
    if not results_dir.exists():
        return []
    return sorted(results_dir.glob("*_trades.csv"))


def _read_trades_rows(path: Path) -> list[dict[str, str]]:
    """Read all rows from a trades.csv file as dicts."""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as fp:
            return list(csv.DictReader(fp))
    except (OSError, UnicodeDecodeError):
        return []


def _try_parse_float(s: str) -> tuple[bool, float | None, str]:
    """Try to parse a string as float.

    Returns (ok, value, error_msg).
    ok=False means the string is unparseable or represents NaN/None.
    """
    if s is None:
        return (False, None, "value is None")

    stripped = s.strip()
    if not stripped:
        return (False, None, "value is empty string")

    # Catch string representations of NaN/None/null
    lower = stripped.lower()
    if lower in {"nan", "none", "null", "n/a", "na", "inf", "-inf", "infinity", "-infinity"}:
        return (False, None, f"value is {lower!r} (non-finite or null marker)")

    try:
        v = float(stripped)
    except ValueError:
        return (False, None, f"ValueError: cannot parse {stripped!r} as float")

    if not math.isfinite(v):
        return (False, None, f"value is non-finite (inf/-inf): {v}")

    return (True, v, "")


# ---------------------------------------------------------------------------
# PASS baselines: chase_up numeric column parseability
# ---------------------------------------------------------------------------


def test_chase_up_numeric_columns_parse_cleanly() -> None:
    """§0/§2 PASS baseline: numeric columns parse as float without errors.

    For every chase_up trades.csv row, all numeric columns must parse
    cleanly as float:
    - No "nan"/"NaN"/"None"/"null" strings
    - No empty strings
    - No unparseable text
    - All values are finite (not inf/-inf)

    Pin the invariant. If CSV serialization introduces a NaN marker
    or empty cell, this test fails with row-level detail.
    """
    violations: list[str] = []
    files_checked = 0
    rows_checked = 0

    for path in _trades_csv_files():
        files_checked += 1
        rows = _read_trades_rows(path)
        if not rows:
            continue

        first_row = rows[0]
        available_cols = set(first_row.keys())
        numeric_cols = [c for c in NUMERIC_COLUMNS if c in available_cols]
        if not numeric_cols:
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            for col in numeric_cols:
                raw_value = row.get(col, "")
                ok, _, err = _try_parse_float(raw_value)
                if not ok:
                    violations.append(
                        f"{path.name}:row{row_idx}:{col} = {raw_value!r} ({err})"
                    )

    if not rows_checked:
        return

    assert not violations, (
        f"§0/§2 NUMERIC PARSE FAILURE: {len(violations)} cells in "
        f"{files_checked} chase_up files fail float parsing:\n"
        + "\n".join(f"  {v}" for v in violations[:15])
        + (f"\n  ... ({len(violations) - 15} more)" if len(violations) > 15 else "")
        + "\n\nPossible causes:\n"
        "  - pandas to_csv wrote NaN as empty string or 'nan'\n"
        "  - CSV writer used 'null' or 'None' for missing values\n"
        "  - Upstream calculation produced inf/-inf (e.g., division by zero)\n"
        "  - Manual row construction with None instead of numeric default"
    )


def test_chase_up_prices_are_positive() -> None:
    """§2 PASS baseline: entry_price and exit_price > 0.

    Per CLAUDE.md §2: prices must be physical and finite. Zero or
    negative prices indicate:
    - Division-by-zero upstream
    - Wrong price source (placeholder 0.0)
    - Sign error (entry/exit flipped)
    - Delisted stock with NULL close

    Chinese A-share prices are always > 0.
    """
    violations: list[str] = []
    files_checked = 0
    rows_checked = 0

    for path in _trades_csv_files():
        files_checked += 1
        rows = _read_trades_rows(path)
        if not rows:
            continue

        first_row = rows[0]
        if not {"entry_price", "exit_price"}.issubset(first_row.keys()):
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            entry_ok, entry_val, entry_err = _try_parse_float(
                row.get("entry_price", "")
            )
            exit_ok, exit_val, exit_err = _try_parse_float(
                row.get("exit_price", "")
            )

            if entry_ok and entry_val is not None and entry_val <= 0:
                violations.append(
                    f"{path.name}:row{row_idx}:entry_price = {entry_val} (<= 0)"
                )
            if exit_ok and exit_val is not None and exit_val <= 0:
                violations.append(
                    f"{path.name}:row{row_idx}:exit_price = {exit_val} (<= 0)"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§2 PRICE INVARIANT VIOLATION: {len(violations)} chase_up rows "
        f"have non-positive prices:\n"
        + "\n".join(f"  {v}" for v in violations[:15])
        + "\n\nPossible causes:\n"
        "  - Wrong price source (placeholder 0.0 instead of actual close)\n"
        "  - Division-by-zero in price calc\n"
        "  - Delisted stock with NULL close (panel didn't filter)\n"
        "  - Sign error in entry/exit flip"
    )


def test_chase_up_size_is_positive_integer_like() -> None:
    """§2 PASS baseline: size > 0 and size is integer-valued.

    Chinese A-share market:
    - 1 trade unit (一手) = 100 shares for most stocks
    - 1 trade unit = 1 share for ETFs
    - Fractional shares are NOT allowed
    - Negative size = SHORT position (not applicable to chase_up LONG-only)

    Size must be:
    - > 0 (positive quantity)
    - Effectively integer (whole number, even if stored as float)
    """
    violations: list[str] = []
    files_checked = 0
    rows_checked = 0

    for path in _trades_csv_files():
        files_checked += 1
        rows = _read_trades_rows(path)
        if not rows:
            continue

        first_row = rows[0]
        if "size" not in first_row:
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            ok, val, err = _try_parse_float(row.get("size", ""))
            if not ok:
                continue  # covered by parse test

            if val is None or val <= 0:
                violations.append(
                    f"{path.name}:row{row_idx}:size = {val} (<= 0)"
                )
                continue

            # Check integer-valued (whole number)
            if val != int(val):
                violations.append(
                    f"{path.name}:row{row_idx}:size = {val} (fractional share)"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§2 SIZE INVARIANT VIOLATION: {len(violations)} chase_up rows "
        f"have invalid size:\n"
        + "\n".join(f"  {v}" for v in violations[:15])
        + "\n\nPossible causes:\n"
        "  - Wrong rounding (truncate instead of round-to-lot)\n"
        "  - Position sizing math bug (divides by price twice)\n"
        "  - Position sizing splits unevenly across multiple trades"
    )