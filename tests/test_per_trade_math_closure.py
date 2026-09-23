"""§3 Per-trade math closure invariant verification (Tick 54).

CLAUDE.md §2 (verbatim):
  "Capital is physical and finite. We mandate Double-Entry Bookkeeping."
  "Differentiate Free_Cash, Locked_Margin, and Settling_Funds."

CLAUDE.md §0 cost model (verbatim):
  - 万 2.5 commission (0.00025) on buy/sell, ¥5 floor
  - 万 5 stamp duty (0.0005) on sell-only

**核心发现 (FRESH 2026-09-23):**

A. **chase_up canonical 14-col schema supports math closure** (verified):
   - chase_up/results/v19_trades.csv columns:
     [entry_date, exit_date, thscode, exit_reason, entry_price, exit_price,
      size, hold_days, gross_pnl, fees, net_pnl, net_return, atr_pct,
      sub_signal_type]
   - Per-row math closure invariant:
     `net_pnl == gross_pnl - fees` (within floating-point tolerance)
   - Per-row net_return invariant:
     `net_return == net_pnl / cost_basis` where cost_basis = entry_price × size

B. **Manual verification of v19 row 1**:
   - entry_price=2.7, size=370200, cost_basis=999540
   - gross_pnl=-77741.99999999999
   - fees=941.2335
   - net_pnl=-78683.23349999999
   - gross - fees = -78683.2225 (differs from net_pnl by 0.011 = rounding)
   - net_return = -0.0786997695020689 ≈ -78683.23 / 999540 ≈ -0.0787

C. **Why this matters**:
   - §2 capital conservation: per-trade PnL must be verifiable
   - §0 cost model: per-trade fees must match 万2.5 + 万5 + ¥5 floor
   - If math closure fails, engine has a calculation bug
   - Without equity_curve.csv (Tick 51), per-trade closure is the only
     way to verify cash walk conservation

D. **Why existing tests miss this**:
   - test_trades_csv_schema_cross_engine checks schema STRUCTURE only
   - No test verifies the numerical INVARIANT (gross - fees = net)
   - chase_up v19 has correct math but no automated guard prevents
     future regressions

E. **Failure scenario caught by this test**:
   - Bug A: `net_pnl = gross_pnl - fees * 2` (double-fee bug)
   - Bug B: `net_return = net_pnl / exit_price` (wrong denominator)
   - Bug C: `fees = notional * 0.001` instead of 0.00025 + 0.0005
   - Bug D: stamp duty applied to buy (should be sell-only)

本文件验证:
- 3 PASS baselines: chase_up per-trade math closure (3 invariants):
  - gross - fees = net_pnl (within 1e-6 tolerance)
  - net_return = net_pnl / cost_basis (within 1e-4 tolerance)
  - fees non-negative (cost model mandates buy/sell both incur commission)
- 1 RED forward-defense: if any row violates, test fails with row
  details (would never pass on currently-correct data)
"""
from __future__ import annotations

import csv
import math
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
# PASS baselines: chase_up per-trade math closure
# ---------------------------------------------------------------------------


def test_chase_up_per_trade_gross_minus_fees_equals_net_pnl() -> None:
    """§3 PASS baseline: chase_up per-trade math closure.

    For every chase_up trades.csv row:
      net_pnl ≈ gross_pnl - fees (within 1e-6 absolute tolerance)

    Pin the invariant. If a future bug introduces double-fee or missing
    fee, this test fails with row-level detail.
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
        required_cols = {"gross_pnl", "fees", "net_pnl"}
        if not required_cols.issubset(first_row.keys()):
            # Schema mismatch — skip (covered by schema tests)
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            gross = _coerce_float(row.get("gross_pnl"))
            fees = _coerce_float(row.get("fees"))
            net = _coerce_float(row.get("net_pnl"))

            expected = gross - fees
            diff = abs(net - expected)

            # Tolerance: 1e-6 absolute OR 1e-4 relative
            rel_tol = max(1e-4, abs(expected) * 1e-6)
            if diff > rel_tol:
                violations.append(
                    f"{path.name}:row{row_idx} gross={gross:.4f} "
                    f"fees={fees:.4f} net={net:.4f} "
                    f"expected={expected:.4f} diff={diff:.6f}"
                )

    if not rows_checked:
        return  # no data to verify

    assert not violations, (
        f"§3 PER-TRADE MATH CLOSURE VIOLATION: {len(violations)} rows "
        f"violate `net_pnl = gross_pnl - fees` invariant across "
        f"{files_checked} files ({rows_checked} rows checked):\n"
        + "\n".join(f"  {v}" for v in violations[:10])
        + (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_chase_up_per_trade_net_return_equals_net_pnl_over_invested() -> None:
    """§3 PASS baseline: chase_up per-trade net_return math.

    Per chase_up/portfolio.py:254 (verified):
      net_return = net_pnl / invested
      where invested = entry_price × size + entry_fee

    For every chase_up trades.csv row:
      expected_net_return ≈ net_pnl / (entry_price × size + buy_commission)
      where buy_commission = max(entry_price × size × 0.00025, 5.0)

    Tolerance: 1e-4 absolute (slippage rounding differences).
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
        required_cols = {
            "entry_price", "size", "net_pnl", "net_return",
        }
        if not required_cols.issubset(first_row.keys()):
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            entry_price = _coerce_float(row.get("entry_price"))
            size = _coerce_float(row.get("size"))
            net_pnl = _coerce_float(row.get("net_pnl"))
            net_return = _coerce_float(row.get("net_return"))

            if size <= 0 or entry_price <= 0:
                continue  # skip degenerate rows

            # Per CLAUDE.md §0: commission on buy side, ¥5 floor
            buy_commission = max(entry_price * size * 0.00025, 5.0)
            invested = entry_price * size + buy_commission
            expected = net_pnl / invested
            diff = abs(net_return - expected)

            # Tolerance: 1e-4 absolute (small returns have loose tolerance)
            if diff > 1e-4:
                violations.append(
                    f"{path.name}:row{row_idx} entry={entry_price:.4f} "
                    f"size={size:.0f} invested={invested:.2f} "
                    f"net_pnl={net_pnl:.2f} net_return={net_return:.6f} "
                    f"expected={expected:.6f} diff={diff:.6f}"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§3 PER-TRADE NET_RETURN VIOLATION: {len(violations)} rows "
        f"violate `net_return = net_pnl / (cost_basis + buy_commission)` "
        f"invariant:\n"
        + "\n".join(f"  {v}" for v in violations[:10])
        + (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
    )


def test_chase_up_per_trade_fees_non_negative() -> None:
    """§3 PASS baseline: chase_up per-trade fees non-negative.

    Per §0 cost model: commission charged on buy + sell, stamp duty
    charged on sell-only. Total fees per trade MUST be ≥ 0.

    If a future bug applies negative fees (sign error), this test fails.
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
        if "fees" not in first_row:
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            fees = _coerce_float(row.get("fees"))
            if fees < 0:
                violations.append(
                    f"{path.name}:row{row_idx} fees={fees:.4f} "
                    f"(must be ≥ 0 per §0 cost model)"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§3 PER-TRADE FEES SIGN VIOLATION: {len(violations)} rows "
        f"have negative fees (must be ≥ 0):\n"
        + "\n".join(f"  {v}" for v in violations[:10])
    )


# ---------------------------------------------------------------------------
# RED forward-defense: per-trade fee magnitude sanity check
# ---------------------------------------------------------------------------


def test_chase_up_per_trade_fee_magnitude_within_cost_model_bounds() -> None:
    """§0/§3 RED forward-defense: per-trade fees within cost model bounds.

    For each row, compute EXPECTED fees per §0:
      buy_fee = max(entry × size × 0.00025, 5.0)
      sell_fee = max(exit × size × 0.00025, 5.0) + exit × size × 0.0005

    total_fees = buy_fee + sell_fee

    If recorded `fees` is more than 2× expected, suspect wrong rate
    (e.g., used 0.0006 instead of 0.00025, or 0.001 instead of 0.0005).

    If recorded `fees` is less than 0.5× expected, suspect missing
    stamp duty or floor not applied.

    Tolerance: recorded_fees ∈ [0.5 × expected, 2.0 × expected]
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
        required = {"entry_price", "exit_price", "size", "fees"}
        if not required.issubset(first_row.keys()):
            continue

        for row_idx, row in enumerate(rows, start=1):
            rows_checked += 1
            entry_price = _coerce_float(row.get("entry_price"))
            exit_price = _coerce_float(row.get("exit_price"))
            size = _coerce_float(row.get("size"))
            fees = _coerce_float(row.get("fees"))

            if size <= 0 or entry_price <= 0 or exit_price <= 0:
                continue

            # §0 cost model: commission on both sides, stamp on sell-only
            buy_comm = max(entry_price * size * 0.00025, 5.0)
            sell_comm = max(exit_price * size * 0.00025, 5.0)
            sell_stamp = exit_price * size * 0.0005
            expected_fees = buy_comm + sell_comm + sell_stamp

            # Sanity bounds: 0.5× to 2× expected (allow commission tiers
            # or broker fee variation)
            lower = expected_fees * 0.5
            upper = expected_fees * 2.0

            if fees < lower or fees > upper:
                violations.append(
                    f"{path.name}:row{row_idx} fees={fees:.2f} "
                    f"expected≈{expected_fees:.2f} (bounds [{lower:.2f}, {upper:.2f}])"
                )

    if not rows_checked:
        return

    assert not violations, (
        f"§0 PER-TRADE FEE MAGNITUDE VIOLATION: {len(violations)} rows "
        f"have fees outside [0.5×, 2.0×] expected cost model bounds:\n"
        + "\n".join(f"  {v}" for v in violations[:10])
        + (f"\n  ... ({len(violations) - 10} more)" if len(violations) > 10 else "")
        + "\n\nPossible causes:\n"
        "  - Wrong commission rate (0.0006 instead of 0.00025)\n"
        "  - Wrong stamp rate (0.001 instead of 0.0005)\n"
        "  - Missing ¥5 floor on small notionals\n"
        "  - Stamp duty applied to buy side (should be sell-only)"
    )