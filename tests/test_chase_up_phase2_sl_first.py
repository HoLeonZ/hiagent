"""§4 Phase 2 SL-first tiebreak for chase_up replay (Tick N1).

CLAUDE.md §4 mandate (verbatim):
  "On daily bar data, if BOTH the Stop-Loss and Take-Profit limits are
   breached within the same bar, the engine MUST assume the worst-case
   scenario (Stop-Loss hit first)."

**核心发现 (FRESH 2026-09-28)**:
- chase_up/portfolio.py (Phase 1 canonical, line 300-307) uses **SL-first**:
    `if o <= sl_p: SL` THEN `elif o >= tp_p: TP`
- chase_up/replay_strategy.py (Phase 2, line 79-89) WRONGLY uses **TP-first**:
    `if o >= tp_p: TP` THEN `elif o <= sl_p: SL`
- Result: when both o <= sl_p AND o >= tp_p simultaneously (tiebreak),
  Phase 2 incorrectly selects TP, violating §4 Pessimistic Default.

**Test scope (Tick N1)**:
- Verify ChaseUpTradeReplay.next() picks SL when o == sl_p == tp_p
- uptrend_pullback/replay_strategy.py is already SL-first (passing baseline)

This test pins §4 compliance for Phase 2 chase_up replay.
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from chase_up.replay_broker import AStockBroker
from chase_up.replay_strategy import ChaseUpTradeReplay


# ---------------------------------------------------------------------------
# RED: chase_up Phase 2 must pick SL when both conditions tie (Tick N1)
# ---------------------------------------------------------------------------


def test_chase_up_phase2_picks_sl_on_tiebreak() -> None:
    """§4 Phase 2 SL-first tiebreak: o == sl_p == tp_p → exit SL (not TP).

    Fixture:
      bar 0: signal bar (open=high=low=close=10.0)
      bar 1: entry bar (open=10.0) — buy order fills here
      bar 2: tiebreak bar (open=10.0, sl_p=10.0, tp_p=10.0)
        → both `o <= sl_p` (10.0 <= 10.0) AND `o >= tp_p` (10.0 >= 10.0) are True
        → MUST pick SL per CLAUDE.md §4 Pessimistic Default.

    Current behavior (RED before fix): TP-first ordering → exit_reason == "TP"
    Expected (GREEN after fix): SL-first ordering → exit_reason == "SL"
    """
    feed = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0],
        "high":  [10.0, 10.0, 10.0],
        "low":   [10.0, 10.0, 10.0],
        "close": [10.0, 10.0, 10.0],
        "volume": [1e6, 1e6, 1e6],
    }, index=pd.date_range("2025-07-01", periods=3, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    # tp_p == sl_p == 10.0 — degenerate but exercises tiebreak ordering.
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=1000, tp_price=10.0, sl_price=10.0, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    assert strat.exit_reason == "SL", (
        f"§4 TIEBREAK VIOLATION: chase_up Phase 2 picked {strat.exit_reason!r} "
        f"when o == sl_p == tp_p == 10.0 (must be SL per CLAUDE.md §4 "
        f"Pessimistic Default). chase_up/portfolio.py:300-307 uses SL-first; "
        f"chase_up/replay_strategy.py:79-89 must match."
    )
    assert strat.target_exit_price == pytest.approx(10.0, abs=1e-9)
