"""TradeRecord dataclass + aggregate metrics for cycle_price_action backtests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TradeRecord:
    thscode: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    hold_days: int
    k_line_score: float
    phase_score: float
    calendar_score: float


def compute_metrics(trades: list[TradeRecord]) -> dict:
    """Aggregate trade-level metrics.

    sharpe / max_dd are returned as None because cycle_price_action runs
    per-stock independent accounts and cannot synthesize a portfolio
    equity curve in v1.
    """
    n = len(trades)
    if n == 0:
        return dict(
            n_trades=0, n_wins=0, n_stocks=0,
            total_pnl=0.0, avg_hold_days=0.0,
            win_rate=0.0, cagr=None, sharpe=None, max_dd=None,
        )

    n_wins = sum(1 for t in trades if t.pnl > 0)
    total_pnl = sum(t.pnl for t in trades)
    avg_hold = sum(t.hold_days for t in trades) / n
    return dict(
        n_trades=n,
        n_wins=n_wins,
        n_stocks=len({t.thscode for t in trades}),
        total_pnl=total_pnl,
        avg_hold_days=avg_hold,
        win_rate=n_wins / n,
        cagr=None,        # see docstring
        sharpe=None,
        max_dd=None,
    )
