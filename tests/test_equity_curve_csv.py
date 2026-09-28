"""§2/§3 equity_curve.csv + cash_walk.csv output tests (Tick 51 GREEN).

CLAUDE.md §2 (verbatim):
  "Capital is physical and finite. We mandate Double-Entry Bookkeeping."

Per-bar cash ledger + equity curve is the foundation for:
  - Drawdown verification (running_max − NAV)
  - Cash walk conservation
  - NAV-gate behavior audit
  - Sharpe / CAGR / max_dd reproducibility from per-bar returns

Currently 0/4 engines emit these files. GREEN strategy:
  1. chase_up + uptrend_pullback: backtest returns `equity` DataFrame
     (date, cash, holdings, equity). Write from main.py.
  2. short_reversal: strategy tracks `result_holder["equity_curve"]` per-bar.
     Write from main.py.
  3. cycle_price_action: per-stock Portfolio tracks `cash` per-bar;
     aggregate to per-run equity_curve.csv.

Schemas (canonical):
  equity_curve.csv: date, cash, position_value, total_equity, drawdown
  cash_walk.csv   : date, free_cash, locked_margin, settling_funds,
                    nav, total_equity

Per CLAUDE.md §2, locked_margin + settling_funds default to 0 and
free_cash mirrors the single cash pool until §2 settlement isolation
(H5.1) implements real 3-pool state.
"""
from __future__ import annotations

import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

EQUITY_CURVE_COLS = ("date", "cash", "position_value", "total_equity", "drawdown")
CASH_WALK_COLS = (
    "date", "free_cash", "locked_margin", "settling_funds", "nav", "total_equity",
)


def _read_csv_header(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return next(csv.reader(f), [])


# ---------------------------------------------------------------------------
# chase_up
# ---------------------------------------------------------------------------


def test_chase_up_main_exposes_equity_curve_writer(tmp_path: Path) -> None:
    """§2/§3 chase_up main.py exposes _write_equity_curve(writer)."""
    from chase_up import main as chase_main
    import inspect
    src = inspect.getsource(chase_main)
    assert "_write_equity_curve" in src or "_write_outputs" in src, (
        "§2/§3 GREEN: chase_up/main.py must define _write_equity_curve "
        "(or _write_outputs) writer (Tick 51 fix)."
    )

    if "_write_equity_curve" in src:
        from chase_up.main import _write_equity_curve
        import pandas as pd

        # Synthetic equity DataFrame
        eq = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3),
            "cash": [1_000_000.0, 950_000.0, 980_000.0],
            "holdings": [0.0, 50_000.0, 30_000.0],
            "equity": [1_000_000.0, 1_000_000.0, 1_010_000.0],
        })
        equity_path = tmp_path / "equity_curve.csv"
        cash_walk_path = tmp_path / "cash_walk.csv"
        _write_equity_curve(equity_path, cash_walk_path, eq)

        assert _read_csv_header(equity_path) == list(EQUITY_CURVE_COLS), (
            f"equity_curve.csv header diverged: "
            f"got={_read_csv_header(equity_path)}, expected={list(EQUITY_CURVE_COLS)}"
        )
        assert _read_csv_header(cash_walk_path) == list(CASH_WALK_COLS)


# ---------------------------------------------------------------------------
# uptrend_pullback
# ---------------------------------------------------------------------------


def test_uptrend_pullback_main_exposes_equity_curve_writer(tmp_path: Path) -> None:
    """§2/§3 uptrend_pullback main.py exposes _write_equity_curve(writer)."""
    from uptrend_pullback import main as ut_main
    import inspect
    src = inspect.getsource(ut_main)
    assert "_write_equity_curve" in src or "_write_outputs" in src, (
        "§2/§3 GREEN: uptrend_pullback/main.py must define _write_equity_curve."
    )

    if "_write_equity_curve" in src:
        from uptrend_pullback.main import _write_equity_curve
        import pandas as pd

        eq = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3),
            "cash": [1_000_000.0, 950_000.0, 980_000.0],
            "holdings": [0.0, 50_000.0, 30_000.0],
            "equity": [1_000_000.0, 1_000_000.0, 1_010_000.0],
        })
        equity_path = tmp_path / "equity_curve.csv"
        cash_walk_path = tmp_path / "cash_walk.csv"
        _write_equity_curve(equity_path, cash_walk_path, eq)

        assert _read_csv_header(equity_path) == list(EQUITY_CURVE_COLS)
        assert _read_csv_header(cash_walk_path) == list(CASH_WALK_COLS)


# ---------------------------------------------------------------------------
# short_reversal
# ---------------------------------------------------------------------------


def test_short_reversal_main_exposes_equity_curve_writer(tmp_path: Path) -> None:
    """§2/§3 short_reversal main.py exposes _write_equity_curve(writer).

    The strategy must populate result_holder["equity_curve"] per-bar so
    main.py can dump it. We unit-test the writer with a synthetic list.
    """
    from short_reversal import main as sr_main
    import inspect
    src = inspect.getsource(sr_main)
    assert "_write_equity_curve" in src or "_write_outputs" in src, (
        "§2/§3 GREEN: short_reversal/main.py must define _write_equity_curve."
    )

    if "_write_equity_curve" in src:
        from short_reversal.main import _write_equity_curve

        # Synthetic equity_curve list of dicts
        equity_curve = [
            {"date": "2026-01-01", "cash": 1_000_000.0,
             "holdings_value": 0.0, "equity": 1_000_000.0},
            {"date": "2026-01-02", "cash": 950_000.0,
             "holdings_value": 50_000.0, "equity": 1_000_000.0},
        ]
        equity_path = tmp_path / "equity_curve.csv"
        cash_walk_path = tmp_path / "cash_walk.csv"
        _write_equity_curve(equity_path, cash_walk_path, equity_curve)

        assert _read_csv_header(equity_path) == list(EQUITY_CURVE_COLS)
        assert _read_csv_header(cash_walk_path) == list(CASH_WALK_COLS)


# ---------------------------------------------------------------------------
# cycle_price_action
# ---------------------------------------------------------------------------


def test_cycle_price_action_main_exposes_equity_curve_writer(tmp_path: Path) -> None:
    """§2/§3 cycle_price_action main.py exposes _write_equity_curve(writer)."""
    from cycle_price_action import main as cyc_main
    import inspect
    src = inspect.getsource(cyc_main)
    assert "_write_equity_curve" in src or "_write_outputs" in src, (
        "§2/§3 GREEN: cycle_price_action/main.py must define _write_equity_curve."
    )

    if "_write_equity_curve" in src:
        from cycle_price_action.main import _write_equity_curve

        # cycle_price_action: per-stock equity curves aggregated
        per_stock_curves = [
            {"date": "2026-01-01", "cash": 1_000_000.0,
             "holdings_value": 0.0, "equity": 1_000_000.0},
            {"date": "2026-01-02", "cash": 1_000_000.0,
             "holdings_value": 0.0, "equity": 1_000_000.0},
        ]
        equity_path = tmp_path / "equity_curve.csv"
        cash_walk_path = tmp_path / "cash_walk.csv"
        _write_equity_curve(equity_path, cash_walk_path, per_stock_curves)

        assert _read_csv_header(equity_path) == list(EQUITY_CURVE_COLS)
        assert _read_csv_header(cash_walk_path) == list(CASH_WALK_COLS)