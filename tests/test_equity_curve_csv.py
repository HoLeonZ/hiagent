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

Per CLAUDE.md §2, `locked_margin` + `settling_funds` default to 0 and
free_cash mirrors the single cash pool until §2 settlement isolation
(H5.1) implements real 3-pool state.

**2026-10-15 更正**:上面这句"等 H5.1"的前提**已不成立** —— 三池早已落地
(`short_reversal/replay_strategy_v3.py` 与 `cycle_price_action/portfolio.py` 的 `__init__`
都有 free/locked/settling,并由 `settle()` 维护)。`short_reversal` 的 cash_walk 曾据此
把 locked/settling 写死为 0,那是**产出与账本不符的数据**,已改为如实落盘 + 缺字段 fail-fast。
(`cycle` 仍缺**组合级**逐 bar 序列 —— 那是另一条已登记的缺口,见审计 §8。)
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

EQUITY_CURVE_COLS = ("date", "cash", "position_value", "total_equity", "drawdown")
CASH_WALK_COLS = (
    "date", "free_cash", "locked_margin", "settling_funds", "nav", "total_equity",
)


# ---------------------------------------------------------------------------
# §2 (audit 2026-10-15): cash_walk 必须如实落盘三池,且 NAV 不含 locked_margin
# ---------------------------------------------------------------------------


def _one_row(**overrides) -> dict:
    row = {
        "date": "2025-01-01",
        "free_cash": 400.0, "locked_margin": 500.0, "settling_funds": 100.0,
        "holdings_value": 600.0, "equity": 1_100.0, "drawdown": 0.0,
    }
    row.update(overrides)
    return row


def test_short_reversal_cash_walk_records_the_real_three_pools(tmp_path: Path) -> None:
    """§2: 三池必须各自如实落盘 —— 此前的实现把它们写死为 0/total_cash。

    构造刻意让三池互不相等,这样"写死为 0"或"free_cash 填 total_cash"都会被抓到。
    """
    from short_reversal.main import _write_equity_curve

    eq, cw = tmp_path / "equity_curve.csv", tmp_path / "cash_walk.csv"
    _write_equity_curve(eq, cw, [_one_row()])
    with cw.open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    assert float(row["free_cash"]) == pytest.approx(400.0)
    assert float(row["locked_margin"]) == pytest.approx(500.0)
    assert float(row["settling_funds"]) == pytest.approx(100.0)


def test_short_reversal_cash_walk_nav_excludes_locked_margin(tmp_path: Path) -> None:
    """§2: NAV 走规范单源 `portfolio_nav` = free + settling + 持仓市值。

    **不含** `locked_margin` —— 它是持仓的**成本基础**,而 holdings_value 是同一持仓的
    **市值**;两者相加会把仓位计两次(审计 P0-1 的原始缺陷:持仓期间权益虚增一个入场
    成本,平仓后自动消失,故只在持仓期间出现、极易漏检)。

    夹具刻意让"含 locked"与"不含 locked"相差 500,使两种口径可分。
    """
    from core.dual_price import portfolio_nav
    from short_reversal.main import _write_equity_curve

    eq, cw = tmp_path / "equity_curve.csv", tmp_path / "cash_walk.csv"
    _write_equity_curve(eq, cw, [_one_row()])
    with cw.open(encoding="utf-8") as f:
        row = next(csv.DictReader(f))

    nav = float(row["nav"])
    assert nav == pytest.approx(portfolio_nav(400.0, 100.0, 600.0)) == pytest.approx(1_100.0)
    assert nav != pytest.approx(1_600.0), "NAV 把 locked_margin 也加进去了 —— P0 双计回归"


def test_short_reversal_cash_walk_fails_fast_when_pools_are_missing(tmp_path: Path) -> None:
    """§0: 缺三池字段时必须 fail-fast,而不是补 0 产出不实数据。"""
    from short_reversal.main import _write_equity_curve

    with pytest.raises(KeyError, match="三池"):
        _write_equity_curve(
            tmp_path / "e.csv", tmp_path / "c.csv", [{"date": "2025-01-01", "cash": 1.0}]
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

        # Synthetic equity_curve list of dicts.
        # 2026-10-15: 夹具补上三池 —— 写者现在**要求**它们(缺则 fail-fast,不再补 0)。
        # 本用例的意图(表头符合规范 schema)不变,只是夹具要与写者的契约对齐。
        equity_curve = [
            {"date": "2026-01-01", "cash": 1_000_000.0,
             "holdings_value": 0.0, "equity": 1_000_000.0,
             "free_cash": 1_000_000.0, "locked_margin": 0.0, "settling_funds": 0.0},
            {"date": "2026-01-02", "cash": 1_000_000.0,
             "holdings_value": 50_000.0, "equity": 1_000_000.0,
             "free_cash": 950_000.0, "locked_margin": 50_000.0, "settling_funds": 0.0},
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