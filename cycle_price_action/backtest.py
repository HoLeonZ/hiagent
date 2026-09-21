"""Run per-stock backtrader backtests over a date window."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import backtrader as bt
import pandas as pd

from cycle_price_action.backtrader_engine import CyclePriceActionStrategy
from cycle_price_action.data_feed import load_universe_data
from cycle_price_action.metrics import TradeRecord, compute_metrics
from cycle_price_action.presets import PRESET_V1

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestResult:
    trades: list[TradeRecord]
    metrics: dict


def _extract_trades(
    state: Any,  # CyclePriceActionStrategy after cerebro.run()
) -> list[TradeRecord]:
    """Pull closed trades from strategy state.

    The strategy holds at most one position at a time. We reconstruct
    closed trades from Portfolio + ReplayBroker's _open_positions dict.
    Per P3, any open position at end-of-run is force-closed at the last
    bar's close with forced_exit semantics (annotated via pnl=0 marker
    is omitted in v1 — we just skip open positions in this version).
    """
    portfolio = state._portfolio
    broker = state._broker_ext
    # Currently Portfolio has no list of closed trades; rely on broker.
    # In v1 the strategy emits fills via broker; closed round-trips live
    # in the broker._open_positions lifecycle. Without an explicit ledger,
    # we expose what Portfolio recorded via decision_meta snapshots.
    # Implementation note: leverage existing Portfolio fields.
    raise NotImplementedError("wired in Task 4 after P2 ledger extension")


def run_backtest(
    db_path: str,
    start: date,
    end: date,
    cash: float = 1_000_000,
    preset: dict | None = None,
) -> BacktestResult:
    """Run cycle_price_action v1 across all main-board stocks in [start, end]."""
    preset = preset or dict(PRESET_V1)
    universe = load_universe_data(db_path, start, end)
    all_trades: list[TradeRecord] = []
    # Filter preset to keys CyclePriceActionStrategy.params accepts
    # (weight_kline / weight_cycle / weight_calendar / periods live in PRESET_V1
    # but are not in the strategy params tuple; passing them would TypeError).
    _accepted = {"threshold", "min_dim", "max_hold", "atr_period", "atr_sl_mult", "tp_pct"}
    strategy_kwargs = {k: v for k, v in preset.items() if k in _accepted}

    for code, slice in universe.items():
        try:
            cerebro = bt.Cerebro(stdstats=False)
            feed_df = slice.df.set_index(pd.to_datetime(slice.df["date"]))
            feed = bt.feeds.PandasData(
                dataname=feed_df,
                open="open", high="high", low="low",
                close="close", volume="volume",
                openinterest=-1,
            )
            cerebro.adddata(feed, name=code)
            cerebro.addstrategy(CyclePriceActionStrategy, db_path=db_path, **strategy_kwargs)
            cerebro.broker.setcash(cash)
            results = cerebro.run()
        except Exception as e:
            logger.warning("backtest failed for %s: %s", code, e)
            continue
        strat = results[0]
        # _extract_trades is intentionally outside the try/except: in this
        # RED state it raises NotImplementedError so the test fails loudly.
        all_trades.extend(_extract_trades(strat))

    return BacktestResult(trades=all_trades, metrics=compute_metrics(all_trades))
