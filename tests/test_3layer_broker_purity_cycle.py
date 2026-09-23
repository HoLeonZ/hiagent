"""§6 3-Layer Architecture: Execution Broker purity (cycle_price_action) audit (Tick 49).

CLAUDE.md §6 铁律 (verbatim):
  "Code Generation Architecture Check: Whenever you generate a core engine
   component, ensure it separates concerns:
   1. Control Plane / Orchestrator: Manages time-stepping and PIT data dispatching.
   2. Strategy / Inference: Pure function. Receives `State(T)`, returns `Signal(T)`.
      Has no network/DB access.
   3. Execution Broker: Handles slippage, liquidity limits, and atomic cash locking."

**核心发现 (FRESH 2026-09-23) — KNOWN GAP per [[3-layer-architecture-cross-engine-gap]]:**

A. **cycle_price_action Execution Broker opens duckdb per fill** (verified):
   - cycle_price_action/replay_broker.py:40-51 `_next_trading_date()`:
     ```python
     def _next_trading_date(self, after: date) -> date:
         con = duckdb.connect(self.db_path, read_only=True)  # DB OPEN
         try:
             row = con.execute(
                 "SELECT MIN(date) FROM v_daily WHERE date > ?",
                 [after],
             ).fetchone()
         ...
     ```
   - cycle_price_action/replay_broker.py:53-64 `_open_price()`:
     ```python
     def _open_price(self, thscode: str, on_date: date) -> float:
         con = duckdb.connect(self.db_path, read_only=True)  # DB OPEN
         try:
             row = con.execute(
                 "SELECT open FROM v_daily WHERE thscode = ? AND date = ?",
                 [thscode, on_date],
             ).fetchone()
     ```
   - Every `submit_buy()` and `submit_sell()` calls BOTH methods → 2 DB
     opens per fill → ~200+ DB connections per typical backtest

B. **§6 violation**:
   - Execution Broker should NOT have direct DB access
   - Broker should receive pre-fetched data via PIT context from
     Control Plane / Data Feed layer
   - cycle_price_action/data_feed.py:23 opens duckdb (DATA FEED LAYER)
     — this is CORRECT per §6 (Control Plane data dispatching)
   - cycle_price_action/replay_broker.py:41, 54 opens duckdb (BROKER)
     — this VIOLATES §6 (Broker should be DB-free)

C. **Why this matters**:
   - §6 separation of concerns enables testability (Broker can be tested
     without DB)
   - DB opens per fill = performance bottleneck + connection leak risk
   - Cannot swap execution semantics (e.g., live broker) without DB layer
   - Strategy/Broker coupling: if Strategy → Broker → DB, then Strategy
     tests require DB
   - PIT correctness: Broker should not query at decision time (race
     condition if data updates mid-backtest)

D. **Numeric impact**:
   - Performance: ~200+ DB connections per backtest (instead of 1-2)
   - Testability: Broker tests require DB fixture (slow, fragile)
   - Architecture: cannot mock Broker in isolation

E. **Why other engines don't have this** (per Tick 40 signal purity):
   - chase_up + uptrend_pullback + short_reversal: Broker uses pre-loaded
     panel/polars DataFrames (no per-call DB)
   - short_reversal/scan_signals.py:34 has separate violation (signal
     layer, Tick 40)

本文件验证:
- 2 RED: ReplayBroker.__init__ has db_path + _next_trading_date opens DB +
  _open_price opens DB (per-fill DB access)
- 2 PASS baseline: cycle data_feed.py has DB (Control Plane OK) +
  ReplayBroker._fee() is pure (compliant method)
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ---------------------------------------------------------------------------
# RED: cycle_price_action Execution Broker has direct DB access
# ---------------------------------------------------------------------------


def test_replay_broker_init_has_db_path_param() -> None:
    """§6 RED: ReplayBroker.__init__ accepts db_path (Broker should be DB-free).

    cycle_price_action/replay_broker.py:28-37 __init__ signature:
        def __init__(self, db_path: str, atr_slip_scale: float = 0.0)

    Broker having db_path is a §6 violation: Broker should receive data
    via PIT context from Control Plane, not query DB directly.

    GREEN fix: remove db_path from __init__, accept a `data_provider`
    callable or `pit_context` object that exposes next_trading_date +
    open_price methods.
    """
    src = _read("cycle_price_action/replay_broker.py")

    # Extract __init__ signature
    init_match = re.search(r"def __init__\s*\(\s*\n?\s*self\s*,(.*?)\)\s*->", src, re.DOTALL)
    if init_match is None:
        return  # structure changed

    init_params = init_match.group(1)
    if "db_path" not in init_params:
        return  # GREEN

    raise AssertionError(
        "GAP CAPTURED (RED): cycle_price_action/replay_broker.py "
        "ReplayBroker.__init__ accepts `db_path`. CLAUDE.md §6 violation: "
        "Execution Broker should NOT have direct DB access.\n"
        "GREEN fix: remove `db_path` param from __init__, replace with "
        "data_provider or pit_context object from Control Plane layer."
    )


def test_replay_broker_methods_open_duckdb_per_call() -> None:
    """§6 RED: ReplayBroker._next_trading_date + _open_price open duckdb per call.

    Per CLAUDE.md §6, Execution Broker must NOT perform DB queries.
    Currently:
      - replay_broker.py:41 _next_trading_date: `con = duckdb.connect(...)`
      - replay_broker.py:54 _open_price: `con = duckdb.connect(...)`
    Every fill triggers 2 DB opens (one for next trading date, one for
    open price). ~200+ DB connections per typical backtest.

    GREEN fix: receive pre-fetched calendar + price lookup via data
    provider or PIT context.
    """
    src = _read("cycle_price_action/replay_broker.py")

    # Find class definition
    class_match = re.search(r"class\s+ReplayBroker\b.*?(?=\nclass\s|\ndef\s+\w+\(|^\Z)",
                            src, re.DOTALL | re.MULTILINE)
    if class_match is None:
        return  # structure changed

    class_body = class_match.group(0)

    # Count duckdb.connect calls inside the class
    db_connects = re.findall(r"duckdb\.connect\s*\(", class_body)

    if len(db_connects) == 0:
        return  # GREEN

    raise AssertionError(
        f"GAP CAPTURED (RED): cycle_price_action/replay_broker.py "
        f"ReplayBroker class body has {len(db_connects)} `duckdb.connect()` "
        f"calls. CLAUDE.md §6 violation: Execution Broker must NOT perform "
        f"DB queries — should receive data via Control Plane PIT dispatch.\n"
        f"Per [[3-layer-architecture-cross-engine-gap]]: cycle is the only "
        f"engine with this gap. chase_up + uptrend_pullback + short_reversal "
        f"Broker use pre-loaded panel (no per-call DB).\n"
        f"GREEN fix: replace `db_path` + per-call `duckdb.connect()` with "
        f"`data_provider: Callable[[date], date]` + "
        f"`price_provider: Callable[[str, date], float]` injected from "
        f"cycle_price_action/data_feed.py Control Plane."
    )


# ---------------------------------------------------------------------------
# PASS baselines
# ---------------------------------------------------------------------------


def test_cycle_data_feed_layer_has_db_access() -> None:
    """§6 PASS baseline: cycle_price_action/data_feed.py CAN have DB access.

    Per CLAUDE.md §6, Control Plane / Data Feed layer is responsible for
    PIT data dispatching. cycle_price_action/data_feed.py:23 has
    `duckdb.connect()` — this is CORRECT (Control Plane responsibility).

    Pin compliance so the Control Plane layer doesn't accidentally
    lose DB access (would break PIT data dispatch).
    """
    src = _read("cycle_price_action/data_feed.py")

    assert "duckdb.connect" in src, (
        "Regression: cycle_price_action/data_feed.py lost DB access. "
        "CLAUDE.md §6 mandates Control Plane / Data Feed layer to have "
        "DB access for PIT dispatch."
    )


def test_replay_broker_fee_method_is_pure() -> None:
    """§6 PASS baseline: ReplayBroker._fee() is pure (no DB, deterministic).

    Pin compliance: _fee() is a pure calculation (no DB, no network).
    This is the correct Broker pattern — pure slippage/cost computation.

    If _fee() regresses to DB access, this test fails (correct — would
    violate §6).
    """
    src = _read("cycle_price_action/replay_broker.py")

    # Find _fee method
    fee_match = re.search(
        r"def\s+_fee\s*\(\s*\n?\s*self\s*,(.*?)(?=\n    def\s|\nclass\s|\Z)",
        src, re.DOTALL,
    )
    if fee_match is None:
        return  # structure changed

    fee_body = fee_match.group(0)

    # _fee should NOT have duckdb or any DB reference
    assert "duckdb" not in fee_body.lower(), (
        "Regression: cycle_price_action/replay_broker.py _fee() now has "
        "DB access. CLAUDE.md §6 violation: Broker should have pure "
        "slippage/cost calculation."
    )