"""§0/§3 ExecutionBar invariant on cycle_price_action BUY path (Tick N3).

CLAUDE.md §0 (Fail-Fast) + §3 (Dual-Price System): partial-NaN bar (open/high/low
real, close=NaN) MUST raise ValueError on the buy-fill path, not silently
fallback to a phantom close=0 exit.

Regression chain (3cb6d7c fixed for chase/uptrend; cycle BUY was missed):
- chase_up + uptrend_pullback: extract_execution_bar → ExecutionBar invariant
  → raise when raw_close=NaN.
- cycle_price_action: _open_price() reads raw `open` only (NOT through
  ExecutionBar). Buy fill path therefore bypasses the partial-NaN guard.
- cycle_price_action backtrader_engine.py: entry path passes raw `bar["close"]`
  to Portfolio.try_enter, again bypassing ExecutionBar.

This test pins both call sites so the bug cannot re-emerge silently.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycle_price_action.data_feed import ReplayDataProvider
from cycle_price_action.replay_broker import ReplayBroker


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def partial_nan_db(tmp_path):
    """DB containing one normal bar + one partial-NaN bar (close=NaN, others real)."""
    db = tmp_path / "partial_nan.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE,"
        "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
        "amount DOUBLE, volume DOUBLE)"
    )
    # 2024-06-03 healthy bar
    con.execute(
        "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
        ["600000.SH", date(2024, 6, 3), 10.0, 10.5, 9.8, 10.2, 1e7, 1e6],
    )
    # 2024-06-04 partial-NaN: open/high/low real, close=NaN
    con.execute(
        "INSERT INTO v_daily VALUES (?,?,?,?,?,?,?,?)",
        ["600000.SH", date(2024, 6, 4), 10.3, 10.7, 10.1, None, 1e7, 1e6],
    )
    con.close()
    return db


# ---------------------------------------------------------------- tests


def test_replay_broker_open_price_raises_on_partial_nan(partial_nan_db):
    """N3.1: ReplayBroker._open_price() must go through ExecutionBar.

    With open/high/low real and close=NaN, _open_price() must raise
    ValueError (per ExecutionBar.__post_init__ invariant). Before fix,
    _open_price() SELECTed only `open` and bypassed the invariant, returning
    10.3 silently. After fix, the SELECT also reads high/low/close and
    routes through extract_execution_bar → raise.

    Tick 49 (CLAUDE.md §6): ReplayBroker receives ReplayDataProvider
    (Control Plane), not db_path.
    """
    provider = ReplayDataProvider(str(partial_nan_db))
    b = ReplayBroker(provider)
    with pytest.raises(ValueError, match="close"):
        b._open_price("600000.SH", date(2024, 6, 4))


def test_replay_broker_submit_buy_propagates_partial_nan(partial_nan_db):
    """N3.2: submit_buy() must propagate the ExecutionBar raise.

    End-to-end: when fill_date's bar is partial-NaN, submit_buy() must raise
    (not return a TradeFill with phantom price). The buy path is the
    production entry; silent phantom fill at fill_date is the bug.

    Tick 49 (CLAUDE.md §6): ReplayBroker receives ReplayDataProvider.
    """
    provider = ReplayDataProvider(str(partial_nan_db))
    b = ReplayBroker(provider)
    # decision_date=2024-06-03 → fill_date=2024-06-04 (partial-NaN day)
    with pytest.raises(ValueError, match="close"):
        b.submit_buy("600000.SH", 100, decision_date=date(2024, 6, 3))


def test_replay_broker_open_price_passes_for_clean_bar(partial_nan_db):
    """Regression: clean bars (no NaN) must still flow normally through
    ExecutionBar. _open_price(2024-06-03) returns 10.0.

    Tick 49 (CLAUDE.md §6): ReplayBroker receives ReplayDataProvider.
    """
    provider = ReplayDataProvider(str(partial_nan_db))
    b = ReplayBroker(provider)
    assert b._open_price("600000.SH", date(2024, 6, 3)) == 10.0


def test_replay_broker_open_price_raises_on_missing_row(tmp_path):
    """_open_price() must still raise RuntimeError when no data exists for
    (thscode, date). Verifies fix doesn't accidentally suppress the
    pre-existing 'no data' guard.

    Tick 49 (CLAUDE.md §6): ReplayBroker receives ReplayDataProvider.
    """
    db = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE v_daily (thscode VARCHAR, date DATE,"
        "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,"
        "amount DOUBLE, volume DOUBLE)"
    )
    con.close()
    provider = ReplayDataProvider(str(db))
    b = ReplayBroker(provider)
    with pytest.raises(RuntimeError, match="no data"):
        b._open_price("600000.SH", date(2024, 6, 3))


def test_backtrader_engine_entry_branch_wraps_close_via_execution_bar():
    """N3.3: backtrader_engine entry branch must wrap bar via ExecutionBar.

    CyclePriceActionStrategy.next()'s entry branch (the `if ... and sig:`
    section ending in try_enter) MUST route `close` through extract_execution_bar
    so the partial-NaN invariant fires before Portfolio.try_enter is called.

    The exit branch already wraps (lines 91-95 of backtrader_engine.py); this
    test targets the entry branch specifically. We slice the source at the
    entry-branch opener (`if self._portfolio.position is None and sig:`) and
    assert that:
      (a) extract_execution_bar is called within the entry branch, AND
      (b) the close passed to try_enter is `bar_exec.close`, not `bar["close"]`.
    """
    from cycle_price_action import backtrader_engine as engine_mod

    import inspect

    source = inspect.getsource(engine_mod.CyclePriceActionStrategy.next)
    entry_branch_start = source.find(
        "if self._portfolio.position is None and sig:"
    )
    assert entry_branch_start != -1, (
        "N3.3 FAIL: cannot locate entry branch opener in backtrader_engine."
    )
    entry_branch = source[entry_branch_start:]

    # (a) extract_execution_bar must be called in the entry branch.
    entry_branch_extract_calls = entry_branch.count("extract_execution_bar")
    assert entry_branch_extract_calls >= 1, (
        "N3.3 FAIL: backtrader_engine entry branch must call "
        "extract_execution_bar to wrap the close used by try_enter."
    )

    # (b) Strip comments + whitespace to verify the CALL to try_enter uses
    # `bar_exec.close` (or similar), NOT `bar["close"]`. Comments may
    # legitimately reference `bar["close"]` so a plain substring check is
    # too strict — we strip line comments first.
    code_lines = []
    for line in entry_branch.splitlines():
        # Drop trailing comments.
        if "#" in line:
            code = line.split("#", 1)[0]
        else:
            code = line
        code_lines.append(code)
    code_only = "\n".join(code_lines)

    # The try_enter(...) call must reference bar_exec.close, not bar["close"].
    import re as _re

    enter_call = _re.search(r"try_enter\(([^)]*)\)", code_only, flags=_re.DOTALL)
    assert enter_call is not None, "N3.3 FAIL: cannot locate try_enter call."
    args_text = enter_call.group(1)
    assert 'bar["close"]' not in args_text, (
        "N3.3 FAIL: try_enter receives raw bar['close']. Must route through "
        "ExecutionBar (bar_exec.close)."
    )
    assert "bar_exec.close" in args_text, (
        "N3.3 FAIL: try_enter must receive bar_exec.close (ExecutionBar-wrapped)."
    )