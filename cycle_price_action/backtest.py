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
    """Build TradeRecord list from strategy's Portfolio ledger.

    strategy._portfolio.closed_trades stores dicts with all P2 meta fields
    (k_line_score / phase_score / calendar_score via decision_meta).
    """
    portfolio = state._portfolio
    out: list[TradeRecord] = []
    for rec in portfolio.closed_trades:
        meta = rec["decision_meta"]
        out.append(TradeRecord(
            thscode=rec["thscode"],
            entry_date=rec["entry_date"],
            exit_date=rec["exit_date"],
            entry_price=rec["entry_price"],
            exit_price=rec["exit_price"],
            shares=rec["shares"],
            pnl=rec["pnl"],
            hold_days=rec["hold_days"],
            k_line_score=float(meta["k_line_score"]),
            phase_score=float(meta["phase_score"]),
            calendar_score=float(meta["calendar_score"]),
        ))
    return out


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
        # _extract_trades is intentionally outside the try/except: decision-
        # extraction bugs must fail loudly rather than be silently skipped.
        all_trades.extend(_extract_trades(strat))

    return BacktestResult(trades=all_trades, metrics=compute_metrics(all_trades))
