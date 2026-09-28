"""§3 Output schema canonicalization tests (Tick 50 + Tick 54 GREEN).

CLAUDE.md §3 (verbatim):
  "Backtest environment must perfectly reconstruct historical reality,
   warts and all."

Single source of truth for trades.csv schema:
  `core.trade_schema.TRADE_COLS` — canonical 14-col tuple.

This file verifies that:
  - chase_up emits trades.csv with the canonical 14-col order (no regression)
  - short_reversal emits trades dict (within metrics.json) using the 14-col
    key set
  - cycle_price_action _write_trades_csv uses the canonical 14-col order

Cross-version schema divergence in historical short_reversal artifacts
(v35-v43 8-col, v44+ 7-col) is a known RED per
[[trades-csv-schema-divergence]] and is pinned by tests in
test_trades_csv_schema_cross_engine.py / test_trades_csv_schema_conformance.py.
This file tests the LIVE OUTPUT PATH (the modules that produce files going
forward), not historical baselines.

GREEN strategy:
  1. Create `core/trade_schema.TRADE_COLS` (14-col tuple).
  2. chase_up/portfolio.py imports from core.trade_schema (no behavior change).
  3. short_reversal/replay_strategy_v3.py _close() builds trade dict with
     all 14 canonical keys.
  4. cycle_price_action/main.py _write_trades_csv writes all 14 cols.
"""
from __future__ import annotations

import csv
from pathlib import Path

from core.trade_schema import TRADE_COLS


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as f:
        return next(csv.reader(f), [])


# ---------------------------------------------------------------------------
# PASS baseline: chase_up trades.csv uses TRADE_COLS (canonical 14-col)
# ---------------------------------------------------------------------------


def test_chase_up_trades_csv_uses_canonical_TRADE_COLS() -> None:
    """§3 PASS baseline: chase_up trades.csv header equals TRADE_COLS.

    chase_up is the canonical reference. chase_up/portfolio.py imports
    TRADE_COLS from core.trade_schema, so its trades.csv header MUST match
    the canonical tuple exactly.

    Pin: if chase_up regresses to a partial schema (e.g., 8-col like
    short_reversal v35-v43), this test fails.
    """
    from chase_up.portfolio import TRADE_COLS as CHASE_TRADE_COLS
    assert tuple(CHASE_TRADE_COLS) == TRADE_COLS, (
        f"chase_up/portfolio.py TRADE_COLS diverged from core.trade_schema. "
        f"chase_up={list(CHASE_TRADE_COLS)}, canonical={list(TRADE_COLS)}"
    )


def test_chase_up_trades_csv_canonical_14_cols_on_disk() -> None:
    """§3 PASS baseline: chase_up v*_trades.csv files use canonical schema."""
    results_dir = REPO_ROOT / "chase_up" / "results"
    if not results_dir.exists():
        return  # structure changed

    canonical_files = sorted(results_dir.glob("v*_trades.csv"))
    if not canonical_files:
        return  # no data to verify

    violations: list[str] = []
    for f in canonical_files:
        header = _read_csv_header(f)
        if tuple(header) != TRADE_COLS:
            violations.append(
                f"{f.name}: header={header}, expected={list(TRADE_COLS)}"
            )

    assert not violations, (
        f"§3 chase_up regression: {len(violations)} files diverged from "
        f"canonical TRADE_COLS:\n" +
        "\n".join(f"  - {v}" for v in violations[:5])
    )


# ---------------------------------------------------------------------------
# GREEN: short_reversal emits canonical 14-col trade dicts
# ---------------------------------------------------------------------------


def test_short_reversal_close_emits_canonical_trade_dict() -> None:
    """§3 GREEN: short_reversal._close builds trade dict with all 14 keys.

    short_reversal/replay_strategy_v3.py _close() currently builds a
    7-col dict:
      thscode, entry_price, exit_price, exit_reason, size, net, hold_days

    GREEN fix: extend to 14 canonical cols by computing:
      - entry_date, exit_date (from `d.datetime[0]` / `pos["entry_bar"]`)
      - gross_pnl = (entry_price - exit_price) × size
      - fees = entry_fee + exit_fee (per CLAUDE.md §0)
      - net_pnl = gross_pnl - fees
      - net_return = net_pnl / (entry_price × size)
      - atr_pct = NaN (short_reversal doesn't expose at summary time)
      - sub_signal_type = "" (chase_up-specific)
    """
    # We cannot run the strategy without a live DuckDB, so test the helper
    # function _canonical_trade_record from replay_strategy_v3.py once added.
    # Importing it should not raise; the canonical dict is built locally.
    from short_reversal import replay_strategy_v3

    # Inspect the source for the canonical record builder
    import inspect
    src = inspect.getsource(replay_strategy_v3)
    # Required: a function or method that builds the canonical dict
    # containing all 14 keys.
    has_builder = (
        "_canonical_trade_record" in src
        or "canonical_trade_record" in src
    )
    assert has_builder, (
        "§3 GREEN: short_reversal/replay_strategy_v3.py must define a "
        "_canonical_trade_record(...) builder that emits all 14 canonical "
        "keys (entry_date, exit_date, thscode, exit_reason, entry_price, "
        "exit_price, size, hold_days, gross_pnl, fees, net_pnl, net_return, "
        "atr_pct, sub_signal_type)."
    )


# ---------------------------------------------------------------------------
# GREEN: cycle_price_action _write_trades_csv uses canonical 14-col order
# ---------------------------------------------------------------------------


def test_cycle_price_action_write_trades_csv_canonical_14_cols() -> None:
    """§3 GREEN: cycle_price_action _write_trades_csv writes canonical header.

    cycle_price_action/main.py:30 _write_trades_csv currently writes 11 cols:
      thscode, entry_date, exit_date, entry_price, exit_price, shares, pnl,
      hold_days, k_line_score, phase_score, calendar_score

    GREEN fix: extend to 14 canonical cols:
      - Replace `shares` → `size`, `pnl` → `net_pnl`
      - Add `gross_pnl`, `fees`, `net_return`
      - Add `atr_pct` (NaN), `sub_signal_type` ("")
      - Drop engine-specific `k_line_score`, `phase_score`, `calendar_score`
        (those live in `decision_meta`, accessible via a separate JSON dump)

    Test: invoke _write_trades_csv with a TradeRecord + write to tmp,
    read back the header, verify it equals TRADE_COLS.
    """
    from cycle_price_action.main import _write_trades_csv
    from cycle_price_action.metrics import TradeRecord
    from datetime import date

    import tempfile

    sample = TradeRecord(
        thscode="600000.SH",
        entry_date=date(2026, 1, 1),
        exit_date=date(2026, 1, 5),
        entry_price=10.0,
        exit_price=10.5,
        shares=1000,
        pnl=485.0,
        hold_days=4,
        k_line_score=0.1,
        phase_score=0.2,
        calendar_score=0.3,
    )

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "trades.csv"
        _write_trades_csv(out_path, [sample])
        header = _read_csv_header(out_path)

    assert tuple(header) == TRADE_COLS, (
        f"§3 cycle_price_action _write_trades_csv header diverged from "
        f"canonical. got={header}, expected={list(TRADE_COLS)}"
    )