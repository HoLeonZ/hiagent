"""§4 Phase 2 limit-up skip guard for chase_up + uptrend_pullback replay (Tick N2).

CLAUDE.md §3 + §4 mandate (verbatim):
  - §3 "Reality Mapping": backtest must perfectly reconstruct historical
    reality — limit-up opens CANNOT be transacted (order queue locked at +10%).
  - §4 "Microstructure & Liquidity": Do not assume infinite market depth.

**核心发现 (FRESH 2026-09-28)**:
- chase_up/portfolio.py (Phase 1, line 384-386) DOES enforce limit-up skip:
    `if is_limit_up(pc, o, threshold=LIMIT_UP_THRESHOLD): continue`
- chase_up/replay_strategy.py (Phase 2) — `self.skipped` field is DECLARED
  (line 33) but **NEVER assigned True**. Phase 2 silently buys at limit-up.
- uptrend_pullback/replay_strategy.py — same gap (declared line 59, unused).
- uptrend_pullback/portfolio.py:373-375 already has Phase 1 limit-up guard.

**Test scope (Tick N2)**:
- Verify ChaseUpTradeReplay.next() sets self.skipped = True when bar 1
  open >= bar 0 close × (1 + LIMIT_UP_THRESHOLD).
- Verify UpullbackTradeReplay.next() same behavior.

**Reference**:
- `core.dual_price.is_limit_up(prev_close, open_price, threshold)` —
  single source of truth for both engines.
- chase_up LIMIT_UP_THRESHOLD = 0.098 (historical preset override).
- uptrend_pullback prev_close_limit param defaults to 0.098.
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd

from chase_up.replay_broker import AStockBroker
from chase_up.replay_strategy import ChaseUpTradeReplay
from uptrend_pullback.replay_strategy import UpullbackTradeReplay


# ---------------------------------------------------------------------------
# RED: chase_up Phase 2 must set skipped=True on limit-up open (Tick N2)
# ---------------------------------------------------------------------------


def test_chase_up_phase2_skipped_on_limit_up_open() -> None:
    """§4 Phase 2 limit-up skip: bar 1 open at +9.8% → skipped=True.

    Fixture:
      bar 0: signal bar, close = 10.0 (this becomes bar 1 prev_close)
      bar 1: entry bar, open = 10.98 (= 10.0 × 1.098) — limit-up
        → is_limit_up(10.0, 10.98, threshold=0.098) → True
        → MUST set self.skipped = True and return without accepting fill.

    Current behavior (RED before fix): self.skipped stays False forever.
    Expected (GREEN after fix): self.skipped == True after cerebro.run().
    """
    feed = pd.DataFrame({
        "open":  [10.0, 10.98, 10.0],
        "high":  [10.0, 10.98, 10.5],
        "low":   [10.0, 10.98, 10.0],
        "close": [10.0, 10.98, 10.1],
        "volume": [1e6, 1e6, 1e6],
    }, index=pd.date_range("2025-08-01", periods=3, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=1000, tp_price=11.0, sl_price=9.5, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    assert strat.skipped is True, (
        f"§4 LIMIT-UP SKIP VIOLATION: chase_up Phase 2 did not set "
        f"self.skipped = True when bar 1 open=10.98 is at limit-up "
        f"(prev_close=10.0 × 1.098 = 10.98, threshold=0.098). "
        f"chase_up/portfolio.py:384-386 enforces this in Phase 1; "
        f"Phase 2 must match (CLAUDE.md §3 Reality Mapping)."
    )
    # entry_done should NOT be set — strategy never accepted the fill.
    assert strat.entry_done is False, (
        "Phase 2 limit-up skip must NOT mark entry_done=True"
    )


def test_chase_up_phase2_not_skipped_when_open_below_limit() -> None:
    """§4 Phase 2: bar 1 open below limit-up threshold → skipped stays False.

    Sanity test: the limit-up guard must NOT false-positive on a normal bar.
    bar 0 close = 10.0, bar 1 open = 10.5 (+5%) — well below 0.098 threshold.
    """
    feed = pd.DataFrame({
        "open":  [10.0, 10.5, 10.6],
        "high":  [10.0, 11.0, 11.0],
        "low":   [10.0, 10.4, 10.5],
        "close": [10.0, 10.6, 10.7],
        "volume": [1e6, 1e6, 1e6],
    }, index=pd.date_range("2025-08-15", periods=3, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=1000, tp_price=11.5, sl_price=9.5, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    assert strat.skipped is False, (
        "Phase 2 limit-up guard false-positive: skipped=True on a normal "
        "+5% open bar (well below 0.098 threshold)"
    )
    assert strat.entry_done is True


# ---------------------------------------------------------------------------
# RED: uptrend_pullback Phase 2 must set skipped=True on limit-up open (Tick N2)
# ---------------------------------------------------------------------------


def test_uptrend_pullback_phase2_skipped_on_limit_up_open() -> None:
    """§4 Phase 2 limit-up skip: same fixture as chase_up, uptrend must match."""
    feed = pd.DataFrame({
        "open":  [10.0, 10.98, 10.0],
        "high":  [10.0, 10.98, 10.5],
        "low":   [10.0, 10.98, 10.0],
        "close": [10.0, 10.98, 10.1],
        "volume": [1e6, 1e6, 1e6],
    }, index=pd.date_range("2025-09-01", periods=3, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    cerebro.addstrategy(
        UpullbackTradeReplay,
        target_size=1000, tp_price=11.0, sl_price=9.5, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    assert strat.skipped is True, (
        f"§4 LIMIT-UP SKIP VIOLATION: uptrend_pullback Phase 2 did not set "
        f"self.skipped = True on limit-up open. uptrend_pullback/"
        f"portfolio.py:373-375 enforces in Phase 1; Phase 2 must match."
    )
    assert strat.entry_done is False


def test_uptrend_pullback_phase2_not_skipped_when_open_below_limit() -> None:
    """§4 Phase 2 sanity: normal +5% bar → skipped stays False."""
    feed = pd.DataFrame({
        "open":  [10.0, 10.5, 10.6],
        "high":  [10.0, 11.0, 11.0],
        "low":   [10.0, 10.4, 10.5],
        "close": [10.0, 10.6, 10.7],
        "volume": [1e6, 1e6, 1e6],
    }, index=pd.date_range("2025-09-15", periods=3, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    cerebro.addstrategy(
        UpullbackTradeReplay,
        target_size=1000, tp_price=11.5, sl_price=9.5, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    assert strat.skipped is False
    assert strat.entry_done is True
