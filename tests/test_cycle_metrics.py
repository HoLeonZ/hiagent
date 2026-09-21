"""TradeRecord + compute_metrics tests."""
from __future__ import annotations

from datetime import date

import pytest

from cycle_price_action.metrics import TradeRecord, compute_metrics


def _t(pnl: float, hold: int = 5) -> TradeRecord:
    return TradeRecord(
        thscode="600000.SH",
        entry_date=date(2025, 1, 1),
        exit_date=date(2025, 1, 1 + hold),
        entry_price=10.0,
        exit_price=11.0 if pnl > 0 else 9.0,
        shares=100,
        pnl=pnl,
        hold_days=hold,
        k_line_score=1.5,
        phase_score=0.3,
        calendar_score=0.8,
    )


def test_compute_metrics_basic():
    trades = [_t(100.0), _t(-50.0), _t(200.0)]
    m = compute_metrics(trades)
    assert m["n_trades"] == 3
    assert m["n_wins"] == 2
    assert m["total_pnl"] == pytest.approx(250.0)
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["avg_hold_days"] == pytest.approx(5.0)
    assert m["n_stocks"] == 1


def test_compute_metrics_empty_no_crash():
    m = compute_metrics([])
    assert m["n_trades"] == 0
    assert m["total_pnl"] == 0
    assert m["win_rate"] == 0
    assert m["cagr"] is None
    assert m["sharpe"] is None
    assert m["max_dd"] is None
