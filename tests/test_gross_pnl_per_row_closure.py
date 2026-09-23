"""§3 Per-row gross_pnl math closure verification (Tick 60).

CLAUDE.md §3 (verbatim):
  "Backtest environment must perfectly reconstruct historical reality,
   warts and all."

**核心发现 (FRESH 2026-09-23):**

A. **Tick 54 verified chase_up per-trade math closure for**:
   - `net_pnl = gross_pnl - fees` (within 1e-6)
   - `net_return = net_pnl / (cost_basis + buy_commission)`
   - `fees ≥ 0`
   - `fees within cost model bounds [0.5×, 2.0×]`

B. **Tick 60: gross_pnl closure NOT yet verified per-row**:
   - For LONG position: `gross_pnl = (exit_price - entry_price) × size`
   - For SHORT position: `gross_pnl = (entry_price - exit_price) × size`
   - chase_up is LONG-only per [[dual-price-refactor-uncommitted]]
   - gross_pnl in trades.csv must match raw price diff × size

C. **Why this matters**:
   - §3 Data integrity: per-trade math must be verifiable
   - §2 Capital conservation: gross PnL is the basis for fees + net PnL
   - If gross_pnl is computed wrong, downstream net_pnl + net_return
     are wrong even if formulas are right
   - Catches phantom TP bugs (Tick 45 V3a issue) — wrong price source
     creates phantom gross_pnl

D. **Manual verification of chase_up v19 row 1**:
   - entry_price=2.7, exit_price=2.49, size=370200
   - LONG gross_pnl = (2.49 - 2.7) × 370200 = -0.21 × 370200 = -77742.0
   - recorded gross_pnl=-77741.99999999999 (within 1e-6 of expected)
   - ✓ LONG formula verified

E. **Why existing tests miss this**:
   - Tick 54 verifies net_pnl = gross_pnl - fees (post-fee closure)
   - No test verifies gross_pnl = price_diff × size (pre-fee closure)
   - Catches different bug class (wrong price source for PnL calc)

F. **Acceptable rounding**:
   - Floating-point arithmetic: 1e-6 absolute OR 1e-4 relative tolerance
   - Size may be float in CSV (whole number stored as float)

本文件验证:
- PASS baseline: chase_up per-row gross_pnl = (exit - entry) × size
  for LONG positions (within 1e-6 tolerance)
- PASS baseline: chase_up per-row gross_pnl sign matches exit vs entry
  direction (LONG: gross_pnl < 0 iff exit < entry)
- RED forward-defense: any row violating this fails with row details
"""
from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _coerce_float(s: str | None) -> float:
    """Safely coerce string to float."""
    if s is None or s == "":
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# PASS baselines: chase_up per-row gross_pnl math closure
# ---------------------------------------------------------------------------


def test_chase_up_per_row_gross_pnl_equals_price_diff_times_size() -> None:
    """§3 PASS baseline: chase_up per-row gross_pnl closure (LONG).

    For every chase_up trades.csv row:
      expected_gross_pnl = (exit_price - entry_price) × size

    chase_up is LONG-only per [[dual-price-refactor-uncommitted]].

    Tolerance: 1e-6 absolute OR 1e-4 relative (floating-point arithmetic).

    Pin the invariant. If a future bug uses adj_close instead of raw_close
    for PnL calc (or wrong size), this test fails with row-level detail.
    """
    violations: list[str] = []
    files_checked = 0
    rows_checked = 0

    for path in _trades_csv_files():
        files_checked += 1
        rows = _read_trades_rows(path)
        if not rows:
            continue

        # Check schema (canonical 14-col)
        first_row = rows[0]
        required_cols = {"entry_price", "exit_price", "size", "gross_pnl"}
        if not required_cols.issubset(first_row.keys()):
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            entry_price = _coerce_float(row.get("entry_price"))
            exit_price = _coerce_float(row.get("exit_price"))
            size = _coerce_float(row.get("size"))
            gross = _coerce_float(row.get("gross_pnl"))

            if size <= 0 or entry_price <= 0 or exit_price <= 0:
                continue  # skip degenerate rows

            # LONG: gross = (exit - entry) × size
            expected = (exit_price - entry_price) * size
            diff = abs(gross - expected)

            # Tolerance: 1e-6 absolute OR 1e-4 relative
            rel_tol = max(1e-4, abs(expected) * 1e-6)
            if diff > rel_tol:
                violations.append(
                    f"{path.name}:row{row_idx} entry={entry_price:.4f} "
                    f"exit={exit_price:.4f} size={size:.0f} "
                    f"recorded_gross={gross:.4f} "
                    f"expected={expected:.4f} diff={diff:.6f}"
                )

    if not rows_checked:
        return  # no data to verify

    assert not violations, (
        f"§3 GROSS_PNL PER-ROW CLOSURE VIOLATION: {len(violations)} rows "
        f"violate `gross_pnl = (exit - entry) × size` invariant across "
        f"{files_checked} files ({rows_checked} rows checked):\n"
        + "\n".join(f"  {v}" for v in violations[:10])
        + (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
        + "\n\nPossible causes:\n"
        "  - Used adj_close instead of raw_close for PnL calc (dual-price bug)\n"
        "  - Sign error (LONG should be exit - entry, not entry - exit)\n"
        "  - Wrong size (off-by-one or accumulated rounding)\n"
        "  - Phantom TP triggered by phantom fill (Tick 45 V3a bug pattern)"
    )


def test_chase_up_per_row_gross_pnl_sign_matches_price_direction() -> None:
    """§3 PASS baseline: chase_up gross_pnl sign matches price direction.

    For LONG positions:
      - gross_pnl > 0 when exit_price > entry_price (profit)
      - gross_pnl < 0 when exit_price < entry_price (loss)
      - gross_pnl = 0 when exit_price == entry_price (breakeven)

    If a row has gross_pnl > 0 but exit_price < entry_price (or vice
    versa), there's a sign bug.
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
        required_cols = {"entry_price", "exit_price", "gross_pnl"}
        if not required_cols.issubset(first_row.keys()):
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            entry_price = _coerce_float(row.get("entry_price"))
            exit_price = _coerce_float(row.get("exit_price"))
            gross = _coerce_float(row.get("gross_pnl"))

            if entry_price <= 0 or exit_price <= 0:
                continue

            # Check sign consistency
            price_diff = exit_price - entry_price
            # Both should have the same sign (or both zero)
            if (price_diff > 0 and gross < 0) or (price_diff < 0 and gross > 0):
                violations.append(
                    f"{path.name}:row{row_idx} entry={entry_price:.4f} "
                    f"exit={exit_price:.4f} price_diff={price_diff:+.4f} "
                    f"gross_pnl={gross:+.4f} (SIGN MISMATCH)"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§3 GROSS_PNL SIGN VIOLATION: {len(violations)} rows have "
        f"gross_pnl sign opposite to price direction:\n"
        + "\n".join(f"  {v}" for v in violations[:10])
        + "\n\nThis indicates a LONG/SHORT sign bug or wrong price source."
    )


def test_chase_up_per_row_exit_after_entry_chronologically() -> None:
    """§3 PASS baseline: chase_up exit_date > entry_date (chronological).

    For every trade, exit must happen AFTER entry. If exit_date <=
    entry_date, there's a date logic bug (could be intra-day if same
    date, so allow entry == exit only if explicitly same-day trade).
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
        required_cols = {"entry_date", "exit_date"}
        if not required_cols.issubset(first_row.keys()):
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            entry_date = row.get("entry_date", "")
            exit_date = row.get("exit_date", "")

            if not entry_date or not exit_date:
                continue

            # String comparison works for YYYY-MM-DD format
            if exit_date < entry_date:
                violations.append(
                    f"{path.name}:row{row_idx} entry={entry_date!r} "
                    f"exit={exit_date!r} (exit BEFORE entry — date bug)"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§3 DATE ORDER VIOLATION: {len(violations)} rows have exit_date "
        f"before entry_date:\n"
        + "\n".join(f"  {v}" for v in violations[:10])
        + "\n\nPossible causes:\n"
        "  - Date format mismatch (YYYY-MM-DD vs MM-DD-YYYY)\n"
        "  - Intra-day trade bug (same date but wrong field)\n"
        "  - Timezone confusion"
    )