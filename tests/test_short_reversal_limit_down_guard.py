"""§4 Limit-Down Guard for short_reversal (Tick N3).

CLAUDE.md §3 Reality Mapping + §4 Microstructure:
- Limit-down opens (-10%) cannot be transacted (order queue locked at -10%).
- short_reversal (做空) MUST reject limit-down opens — selling at the open is
  impossible because the stock is locked DOWN.

Pre-fix: 0 limit_down / is_limit_up references in short_reversal/ (per
[[limit-up-guard-cross-engine-gap]]). Note: short_reversal 做空, so the
mirror function is `is_limit_down` (open <= prev_close × (1 - threshold)).

Pattern (mirror of chase_up/portfolio.py:384-386):
    if is_limit_down(prev_close, entry_price, threshold=...): skip entry
"""
from __future__ import annotations

import sys
from pathlib import Path

import backtrader as bt
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.dual_price import is_limit_down
from short_reversal.feed_bt import AShareData
from short_reversal.replay_strategy_v3 import Phase3V3Strategy


# ---------------------------------------------------------------------------
# Pure-function RED: core.dual_price.is_limit_down must exist + work
# ---------------------------------------------------------------------------


def test_is_limit_down_detects_minus_10_percent() -> None:
    """is_limit_down(10.0, 9.0) → True (-10% exact limit-down)."""
    assert is_limit_down(prev_close=10.0, open_price=9.0) is True


def test_is_limit_down_rejects_normal_minus_5_percent() -> None:
    """is_limit_down(10.0, 9.5) → False (-5%, above limit)."""
    assert is_limit_down(prev_close=10.0, open_price=9.5) is False


def test_is_limit_down_handles_missing_prev_close() -> None:
    """prev_close=None → False (best-effort, no rejection)."""
    assert is_limit_down(prev_close=None, open_price=9.0) is False


def test_is_limit_down_handles_zero_prev_close() -> None:
    """prev_close<=0 (data anomaly) → False (avoid div-by-zero semantics)."""
    assert is_limit_down(prev_close=0.0, open_price=9.0) is False


def test_is_limit_down_uses_default_threshold_095() -> None:
    """Default threshold = 0.095 (CLAUDE.md §3 standard, mirror of is_limit_up).

    -9.4% (10.0 → 9.06) → below 0.095 → False (not yet limit-down).
    -9.51% (10.0 → 9.049) → above 0.095 → True.
    -10% (10.0 → 9.0) → True.
    """
    assert is_limit_down(prev_close=10.0, open_price=9.06) is False
    assert is_limit_down(prev_close=10.0, open_price=9.049) is True
    assert is_limit_down(prev_close=10.0, open_price=9.0) is True


def test_is_limit_down_custom_threshold() -> None:
    """is_limit_down honors custom threshold parameter."""
    # threshold=0.05: -5% triggers
    assert is_limit_down(prev_close=10.0, open_price=9.5, threshold=0.05) is True
    assert is_limit_down(prev_close=10.0, open_price=9.6, threshold=0.05) is False


# ---------------------------------------------------------------------------
# Strategy-level RED: short_reversal must skip limit-down opens
# ---------------------------------------------------------------------------


def _build_panel_with_single_signal_bar(target_bar_idx: int,
                                          target_open: float,
                                          n: int = 80) -> pd.DataFrame:
    """Build a panel where _all_conditions returns True ONLY at the first
    next() call (after SMA(60) warmup).

    backtrader semantics (verified empirically):
      - SMA(60) requires 60 prior bars; first next() fires when len(d)=60.
      - At next() with len(d)=N, d.open[0] = bar[N-1]'s open (current bar).
      - Signal triggers at len(d)=60 (bar 59 processed).
      - _fill_pending_entries runs at len(d)=61 (bar 60 processed); fill
        uses bar 60's open as entry_price and bar 59's close as prev_close.

    So target_bar_idx MUST be 60 for the fill bar — open=target_open, and
    bar 59's close=10.0 becomes prev_close.
    """
    dates = pd.date_range("2025-09-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        if i == target_bar_idx:
            p = target_open
        else:
            p = 10.0
        rows.append({
            "thscode": "600000.SH",
            "date": d,
            "open": p,
            "high": p + 0.001,
            "low": p - 0.001,
            "close": p,
            "volume": 1e6,
            "amount": 5e7,
        })
    return pd.DataFrame(rows)


# backtrader SMA(60) warmup: next() first fires at len(d)=60 (bar 59).
# The signal bar is bar 59; the FILL bar (limit-down check fires) is bar 60.
# So target_bar_idx = 60.
_FILL_BAR_IDX = 60


def test_short_reversal_skips_limit_down_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 RED→GREEN: Phase3V3Strategy skips entry when limit-down (-10%).

    Strategy timing:
      - bar 59 (len(d)=60): _all_conditions=True → pending_entries["600000.SH"] = True
      - bar 60 (len(d)=61): _fill_pending_entries → prev_close=10.0 (bar 59),
        entry_price=9.0 (bar 60)
        → is_limit_down(10.0, 9.0) = True → must SKIP entry (no position).

    Without the limit-down guard, the strategy would open a position at
    price 9.0 on a locked-down day (impossible transaction).

    Cash is sized so that at price=9.0 the trade WOULD succeed if the
    guard didn't fire: lots = 100000 // 900 = 111, shares = 11100,
    cost = 11100 × 9.0 + commission ≈ 99,925 < 100,000. So the only
    reason _holds remains empty is the limit-down guard.
    """
    panel = _build_panel_with_single_signal_bar(
        target_bar_idx=_FILL_BAR_IDX, target_open=9.0,
    )

    # Trigger signal ONLY at the first next() call (bar 59 / len=60).
    state = {"called": False}

    def first_bar_only(self, d):
        if not state["called"]:
            state["called"] = True
            return True
        return False

    monkeypatch.setattr(Phase3V3Strategy, "_all_conditions", first_bar_only)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    cerebro.broker.setcommission(commission=0.0)
    feed = AShareData(dataname=panel, plot=False)
    cerebro.adddata(feed, name="600000.SH")
    holder: dict = {"cash": 100_000.0, "trades": [], "max_dd": 0.0}
    # Round 14 (2026-09-28): min_cash_ratio 默认 None (fail-fast)。测试直接调用
    # strategy 时必须显式传 0.05 才能跑过 cash gate (line 369) 进入 limit-down 守卫。
    cerebro.addstrategy(
        Phase3V3Strategy, result_holder=holder, min_cash_ratio=0.05,
    )
    results = cerebro.run()
    strat = results[0]

    # 必须检查 holder["trades"] 而非 strat._holds: 后者会在 max_hold=5
    # (默认) 后于 bar 65 被清空, 与"是否开仓"无关。Round 23 (2026-09-28)
    # 修复: 把此 test 改用 trade ledger 断言。
    assert holder["trades"] == [], (
        f"§4 LIMIT-DOWN VIOLATION: short_reversal opened position on "
        f"-10% open (prev_close=10.0, open=9.0). Stock is locked at "
        f"limit-down — cannot sell (CLAUDE.md §3 Reality Mapping). "
        f"trades={holder['trades']}"
    )


def test_short_reversal_accepts_normal_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 GREEN: short_reversal accepts normal -5% open (no false-positive).

    Bar 59 (len=60): signal triggers (close=10.0)
    Bar 60 (len=61): fill bar, open=9.5 (only -5%, well above 0.095
                     limit-down threshold). Strategy SHOULD open a position
                     at 9.5.

    Cash is sized so entry succeeds: 100000 // (9.5 × 100) = 105 lots,
    shares = 10500, cost ≈ 99,775 < 100,000.

    Sanity check: limit-down guard must NOT block non-limit-down opens.
    """
    panel = _build_panel_with_single_signal_bar(
        target_bar_idx=_FILL_BAR_IDX, target_open=9.5,
    )

    state = {"called": False}

    def first_bar_only(self, d):
        if not state["called"]:
            state["called"] = True
            return True
        return False

    monkeypatch.setattr(Phase3V3Strategy, "_all_conditions", first_bar_only)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    cerebro.broker.setcommission(commission=0.0)
    feed = AShareData(dataname=panel, plot=False)
    cerebro.adddata(feed, name="600000.SH")
    holder: dict = {"cash": 100_000.0, "trades": [], "max_dd": 0.0}
    # Round 14 (2026-09-28): min_cash_ratio 默认 None (fail-fast)。测试直接调用
    # strategy 时必须显式传 0.05 才能跑过 cash gate (line 369) 进入 limit-down 守卫。
    cerebro.addstrategy(
        Phase3V3Strategy, result_holder=holder, min_cash_ratio=0.05,
    )
    results = cerebro.run()
    strat = results[0]

    # The position may already have time-exited by end-of-panel, so
    # check holder["trades"] for the entry record. limit-down guard
    # should NOT have skipped it.
    assert len(holder["trades"]) >= 1, (
        "Sanity regression: short_reversal did NOT open position on a "
        "normal -5% open (well below 0.095 limit-down threshold). "
        "Limit-down guard is firing as a false-positive. "
        f"trades={holder['trades']}"
    )
    trade = holder["trades"][0]
    assert abs(trade["entry_price"] - 9.5) < 1e-6, (
        f"Entry price mismatch: expected 9.5 (bar 60 open), got "
        f"{trade['entry_price']}"
    )