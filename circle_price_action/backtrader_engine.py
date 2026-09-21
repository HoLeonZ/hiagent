"""Backtrader strategy wiring for cycle_price_action.

Decision flow per bar:
    1.  Compute signal triple (k_line_score, cycle_score, calendar_score).
    2.  fusing → total_score.
    3.  If no position AND total_score ≥ threshold → submit_buy on next bar.
    4.  If position held ≥ max_hold → submit_sell on next bar + try_exit.

P0–P8 are enforced via no_lookahead helpers + replay_broker.
"""
from __future__ import annotations

import pandas as pd

import backtrader as bt

from circle_price_action.signals import (
    detect_k_patterns,
    entry_signal,
    fuse_scores,
    k_line_score,
)
from circle_price_action.cycle import phase_score
from circle_price_action.time_windows import calendar_score
from circle_price_action.portfolio import Portfolio
from circle_price_action.replay_broker import ReplayBroker
from circle_price_action.no_lookahead import bars_up_to


class CirclePriceActionStrategy(bt.Strategy):
    params = dict(
        threshold=2.0,
        min_dim=1.0,
        max_hold=5,
        atr_period=14,
        atr_sl_mult=1.5,
        tp_pct=0.06,
    )

    def __init__(self):
        self._portfolio = Portfolio(cash=self.broker.getcash())
        self._broker_ext = ReplayBroker(self.params.db_path)
        # State for live bar evaluation.
        self._bar_cache: list[dict] = []
        self._entry_day = None

    def _bars_as_df(self) -> pd.DataFrame:
        return pd.DataFrame(self._bar_cache)

    def next(self):
        bar = {
            "date": self.datas[0].datetime.date(0),
            "open": self.datas[0].open[0],
            "high": self.datas[0].high[0],
            "low": self.datas[0].low[0],
            "close": self.datas[0].close[0],
            "volume": self.datas[0].volume[0],
        }
        self._bar_cache.append(bar)
        df = self._bars_as_df()
        bars_until_today = bars_up_to(df, bar["date"])

        kscore = k_line_score(bars_until_today, detect_k_patterns(bars_until_today)).iloc[-1]
        cyc = phase_score(bars_until_today["date"]).iloc[-1]
        cal = calendar_score(bars_until_today["date"]).iloc[-1]
        sig = entry_signal(
            pd.Series([kscore]), pd.Series([cyc]), pd.Series([cal]),
            threshold=self.p.threshold, min_dim=self.p.min_dim,
        ).iloc[0]

        if self._portfolio.position is None and sig:
            state = self._portfolio.try_enter(
                self.datas[0]._name,
                bar["close"],
                bar["date"],
                {"k_line_score": kscore, "phase_score": cyc, "calendar_score": cal},
            )
            if state is None:
                return
            fill = self._broker_ext.submit_buy(
                thscode=state.thscode,
                qty=state.shares,
                decision_date=bar["date"],
            )
            if fill is not None:
                self._entry_day = fill.date
        elif self._portfolio.position is not None and self._portfolio.hold_days(bar["date"]) >= self.p.max_hold:
            fill = self._broker_ext.submit_sell(
                thscode=self._portfolio.position.thscode,
                qty=self._portfolio.position.shares,
                decision_date=bar["date"],
            )
            if fill is not None:
                # Portfolio exits at the fill date with the actual fill price.
                self._portfolio.try_exit(fill.date, fill.price)
                self._entry_day = None
