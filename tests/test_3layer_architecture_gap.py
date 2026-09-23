"""§6 3-Layer Architecture audit RED tests.

CLAUDE.md §6 mandates:
  1. Control Plane / Orchestrator — time-stepping + PIT data dispatching.
  2. Strategy / Inference — pure function. Receives State(T), returns Signal(T).
     Has no network/DB access.
  3. Execution Broker — handles slippage, liquidity, atomic cash locking.

VIOLATIONS (FRESH 2026-09-23 audit):

A. **short_reversal signal layer HAS DB access** (§6 Strategy purity):
   - short_reversal/scan_signals.py:27 `import duckdb`
   - short_reversal/scan_signals.py:44-48 `duckdb.connect(db_path)` inside `_latest_trade_date`
   - short_reversal/scan_signals.py:54-72 `duckdb.connect` + `con.execute` inside `_load_panel_for_codes`
   - short_reversal/scan_signals_fast.py:21 `import duckdb`
   - short_reversal/scan_signals_fast.py:32-40 `duckdb.connect` + `con.execute` inside `_load_panel`

   Other 3 engines' signal files are pure (no DB):
     - chase_up/signals.py (compute_indicators, select_entries take panel: pd.DataFrame)
     - uptrend_pullback/signals.py (same)
     - cycle_price_action/signals.py (same)

B. **cycle_price_action Execution Broker has redundant DB access** (§6 separation):
   - cycle_price_action/replay_broker.py:41,54 — opens `duckdb.connect` on every
     `_next_trading_date` and `_open_price` call
   - cycle_price_action/backtrader_engine.py:54,130,138 — Strategy constructs
     ReplayBroker with `db_path` and calls `submit_buy/submit_sell` per fill
   - Data is ALREADY loaded by `cycle_price_action/backtest.py:63` via
     `load_universe_data(...)` → passed to backtrader as feed. So broker
     re-querying DB is redundant.
   - Practical impact: each cycle backtest opens ~2N DB connections
     (N=fill count). Slow, leak-prone, NOT pure execution layer.

C. **cycle_price_action orchestator swallows failures** (§0 Fail-Fast,
   already in fail-fast-cycle-hot-path.md):
   - cycle_price_action/backtest.py:86-88 `except Exception as e: ... continue`
   - RED test already exists at tests/test_cycle_backtest_fail_fast.py
"""
from __future__ import annotations

import re
from pathlib import Path


def test_short_reversal_signal_layer_has_no_db_access() -> None:
    """§6 Strategy purity: short_reversal signal scanners must not query DB.

    Short_reversal's scan_signals.py / scan_signals_fast.py currently
    directly call duckdb.connect() to load panels. Per §6, signal
    generation is a pure function — orchestrator loads panel and passes
    it in. Refactor: extract a `core/signals.py` PIT loader, leave
    `_scan_preset` / `_load_panel` as orchestrator helpers.
    """
    for fname in (
        "short_reversal/scan_signals.py",
        "short_reversal/scan_signals_fast.py",
    ):
        src = Path(fname).read_text(encoding="utf-8")
        # Strategy/scanner code should not have direct DB access
        has_db_import = bool(re.search(r"^import duckdb|^from duckdb", src, re.MULTILINE))
        assert not has_db_import, (
            f"GAP CAPTURED ({fname}): §6 violation — signal layer has "
            f"`import duckdb`. Strategy must be pure. Refactor: extract "
            f"DB-loading to orchestrator."
        )


def test_chase_up_signal_layer_pure_for_comparison() -> None:
    """§6 Strategy purity baseline: chase_up signals.py has no DB access.

    Pins the COMPLIANT state for chase_up — if this fails, chase_up
    regressed into the same violation as short_reversal.
    """
    src = Path("chase_up/signals.py").read_text(encoding="utf-8")
    has_db_import = bool(re.search(r"^import duckdb|^from duckdb|^import sqlite3", src, re.MULTILINE))
    assert not has_db_import, "chase_up/signals.py regressed — DB access added"


def test_uptrend_pullback_signal_layer_pure_for_comparison() -> None:
    """§6 baseline: uptrend_pullback signals.py has no DB access."""
    src = Path("uptrend_pullback/signals.py").read_text(encoding="utf-8")
    has_db_import = bool(re.search(r"^import duckdb|^from duckdb|^import sqlite3", src, re.MULTILINE))
    assert not has_db_import, "uptrend_pullback/signals.py regressed"


def test_cycle_price_action_signal_layer_pure_for_comparison() -> None:
    """§6 baseline: cycle_price_action signals.py has no DB access."""
    src = Path("cycle_price_action/signals.py").read_text(encoding="utf-8")
    has_db_import = bool(re.search(r"^import duckdb|^from duckdb|^import sqlite3", src, re.MULTILINE))
    assert not has_db_import, "cycle_price_action/signals.py regressed"


def test_cycle_execution_broker_no_per_fill_db_connect() -> None:
    """§6 execution layer purity: ReplayBroker must not open DB on every fill.

    cycle_price_action/replay_broker.py:41,54 opens `duckdb.connect` for
    each `_next_trading_date` and `_open_price` call. The data is already
    loaded into backtrader's feed by orchestrator — broker should accept
    the panel/feed as input, not re-query.
    """
    src = Path("cycle_price_action/replay_broker.py").read_text(encoding="utf-8")
    # Count duckdb.connect calls in module
    db_connect_count = len(re.findall(r"duckdb\.connect\(", src))
    # GREEN expectation: 0 — broker uses pre-loaded data, no DB
    # RED actual: 2+ (one in _next_trading_date, one in _open_price)
    assert db_connect_count == 0, (
        f"GAP CAPTURED: cycle_price_action/replay_broker.py has "
        f"{db_connect_count} `duckdb.connect(` calls. Per §6 execution "
        f"layer purity, broker must accept panel/feed as input. Refactor: "
        f"pass bar data via parameter, eliminate DB queries."
    )


def test_strategy_layer_no_db_path_param() -> None:
    """§6: Strategy class params must not include `db_path` (network/DB
    access leakage into pure inference layer).

    cycle_price_action/backtrader_engine.py:49 stores `db_path` as a
    Strategy param and passes it to ReplayBroker. This couples the
    Strategy to the DB. Per §6, Strategy has no network/DB access.
    """
    src = Path("cycle_price_action/backtrader_engine.py").read_text(encoding="utf-8")
    # GREEN: db_path removed from params, broker accepts panel/feed
    has_db_path_in_params = bool(re.search(r'db_path\s*[:=]\s*str\(', src))
    assert not has_db_path_in_params, (
        "GAP CAPTURED: cycle_price_action Strategy has `db_path` param. "
        "§6 violation: Strategy has no network/DB access. GREEN fix: "
        "remove db_path param, pass data via ReplayBroker constructor."
    )


def test_orchestrator_dispatches_pit_data_to_strategy() -> None:
    """§6: Orchestrator loads panel via PIT API and passes to pure Strategy.

    short_reversal/_scan_preset currently calls duckdb directly inside
    the scan function. Refactor: orchestrator (main loop) loads panel
    via load_universe_asof + load_panel_for_codes, then calls pure
    scan function with panel as input.
    """
    src = Path("short_reversal/scan_signals.py").read_text(encoding="utf-8")
    # Look for duckdb.connect inside the scanner (not in main(), which is the orchestrator)
    # If present, strategy layer is doing DB access
    has_db_in_scanner = bool(re.search(
        r"def _scan_preset|def _load_panel_for_codes",
        src,
    )) and bool(re.search(r"^import duckdb", src, re.MULTILINE))
    assert not has_db_in_scanner, (
        "GAP CAPTURED: short_reversal scan_signals.py — _scan_preset or "
        "_load_panel_for_codes has DB access. §6 mandates pure Strategy. "
        "Refactor: orchestrator loads panel, passes as parameter."
    )