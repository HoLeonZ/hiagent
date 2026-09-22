"""V3a runtime integration test for uptrend_pullback (2026-09-22, CLAUDE.md §3).

Verifies that price_source_for_execution='raw_close' actually changes
the SL/TP trigger prices vs the default 'adj_close' (qfq-adjusted). This
proves the V3a dual-price declarations are not just metadata — they have
functional effect at runtime in actual strategy execution.

Setup:
  - Bar 50: signal (entry at T+1 = bar 51 open)
  - Bar 51 onwards: raw open drops 20% (simulating 除权除息 / dividend event)
  - adj close stays at 10.0 (forward-adjusted, ignores dividend)
  - raw close drops to 8.0

Expected behavior:
  - price_source_for_execution='adj_close' (default): entry at adj_open=10.0,
    SL triggers when adj_low ≤ 9.5 (0.95 * entry)
  - price_source_for_execution='raw_close': entry at raw_open=8.0,
    SL triggers when raw_low ≤ 7.6 (0.95 * entry)

This is exactly CLAUDE.md §3:
  - Indicators use adj_close (raw = 8.0 wouldn't be comparable across
    pre/post-dividend days, but adj = 10.0 is)
  - SL/TP triggers use raw_close (actual physical market event on day 51:
    raw price dropped to 8.0, not 10.0)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uptrend_pullback.portfolio import simulate_portfolio


def _build_panel(n: int = 100, dividend_at: int = 50) -> pd.DataFrame:
    """Build panel: adj (qfq) stays flat, raw drops 20% at dividend_at."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_post_div = i >= dividend_at
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            # adj (qfq) prices: stable across dividend (forward-adjusted)
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": 1e6,
            "amount": 1e7,
            # raw prices: drop 20% after dividend (physical market event)
            "raw_open": 8.0 if is_post_div else 10.0,
            "raw_high": 8.5 if is_post_div else 10.5,
            "raw_low": 7.5 if is_post_div else 9.5,
            "raw_close": 8.0 if is_post_div else 10.0,
            "raw_prev_close": 8.0 if is_post_div else 10.0,
        })
    return pd.DataFrame(rows)


def _build_entries(panel: pd.DataFrame, signal_bar: int) -> pd.DataFrame:
    """Build a single-entry signal on signal_bar (T day close → T+1 entry)."""
    return pd.DataFrame([{
        "date": panel.iloc[signal_bar]["date"],
        "thscode": "TEST.SH",
        "score": 1.0,
        "sig_close": 10.0,
        "sig_ma20": 9.5,
        "sig_ma60": 9.0,
        "sig_ret1": 0.05,
        "sig_breakout_score": 0.5,
        "sig_momentum_score": 0.3,
        "sig_macross_score": np.nan,
        "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": 0.03,
    }])


# ---------- happy path: dual-price divergence at runtime ----------

def test_price_source_raw_close_uses_raw_open_for_entry():
    """price_source_for_execution='raw_close' must use raw_open (8.0) for entry fill,
    not adj open (10.0)."""
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["entry_price"] == pytest.approx(8.0), (
        f"V3a runtime: raw_close source 必须用 raw_open=8.0 fill, "
        f"actual entry_price={trades.iloc[0]['entry_price']}"
    )


def test_price_source_adj_close_uses_adj_open_for_entry():
    """默认 'adj_close' 必须用 adj_open (10.0) for entry, baseline parity."""
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="adj_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["entry_price"] == pytest.approx(10.0), (
        f"adj_close 默认必须 baseline parity (entry at adj_open=10.0), "
        f"actual entry_price={trades.iloc[0]['entry_price']}"
    )


def test_raw_close_sl_trigger_uses_raw_low():
    """raw_close source 下 SL 触发价必须用 raw_low, 不是 adj_low。"""
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    # entry at bar 50 (raw_open=8.0). SL @ 0.95 * 8.0 = 7.6.
    # raw_low drops to 7.5 starting bar 50 → exits immediately on bar 50 SL.
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "SL"
    # SL fill = max(sl_p, open) per gap rule. open=8.0 > sl_p=7.6, so fill at open=8.0 (gap SL).
    # Or if intraday: raw_low=7.5 ≤ sl_p=7.6 → fill at sl_p=7.6.
    # The exact path depends on whether open first breaches; both must be raw-based.
    exit_px = float(trades.iloc[0]["exit_price"])
    assert exit_px == pytest.approx(8.0) or exit_px == pytest.approx(7.6), (
        f"raw_close SL 触发价应是 raw 域 (8.0 gap 或 7.6 盘内), got {exit_px}"
    )


def test_adj_close_sl_trigger_uses_adj_low():
    """adj_close 默认下 SL 触发必须用 adj_low, baseline parity。"""
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    # entry at adj_open=10.0. SL @ 0.95 * 10.0 = 9.5.
    # adj_low=9.5 starting bar 50 → triggers intraday SL.
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="adj_close",
    )
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "SL"
    exit_px = float(trades.iloc[0]["exit_price"])
    # adj SL @ 9.5 (low=sl_p intraday) or 10.0 gap (open=10 > sl_p=9.5)
    assert exit_px == pytest.approx(9.5) or exit_px == pytest.approx(10.0), (
        f"adj_close SL 应在 adj 域, got {exit_px}"
    )


# ---------- dual-price divergence: same signal, different outcomes ----------

def test_raw_close_vs_adj_close_different_entry_prices():
    """同一信号, raw_close 和 adj_close 必须产生不同 entry_price。

    这是 V3a dual-price runtime 的核心不变量: signal 用 adj (qfq), execution
    用 raw → entry 在两个 source 下用不同价格。
    """
    panel = _build_panel(n=100, dividend_at=50)
    entries = _build_entries(panel, signal_bar=49)
    trades_adj, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="adj_close",
    )
    trades_raw, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades_adj) == 1 and len(trades_raw) == 1
    ep_adj = float(trades_adj.iloc[0]["entry_price"])
    ep_raw = float(trades_raw.iloc[0]["entry_price"])
    assert ep_adj == pytest.approx(10.0)
    assert ep_raw == pytest.approx(8.0)
    assert ep_adj != ep_raw, (
        f"V3a dual-price runtime 失效: adj 和 raw 必须产生不同 entry, "
        f"但都 = {ep_adj}"
    )


# ---------- fallback: missing raw_* columns ----------

def test_raw_close_falls_back_to_adj_when_raw_missing():
    """panel 缺 raw_* 列时 (legacy loader), raw_close 必须回退到 adj close,
    不报错, 保持 baseline parity。"""
    # Build panel WITHOUT raw_* columns
    n = 60
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
        })
    panel = pd.DataFrame(rows)
    entries = _build_entries(panel, signal_bar=29)
    # Declare raw_close — should fallback to adj close since no raw_* cols
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    # entry at adj_open=10.0 (fallback)
    assert trades.iloc[0]["entry_price"] == pytest.approx(10.0)


def test_raw_close_uses_raw_open_even_when_raw_prev_close_nan():
    """V3a+ regression (CLAUDE.md §3): entry fill must use raw_open even when
    raw_prev_close is NaN (real DuckDB panel reality: raw_kline_daily.prev_close
    is NULL upstream).

    Per §3, entry fill is a cash mark-to-market operation and MUST use raw.
    prev_close is only used for LIMIT_UP noise filter and can fall back to adj.
    """
    n = 60
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        is_post_div = i >= 30
        rows.append({
            "thscode": "TEST.SH",
            "date": d,
            "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": 1e6, "amount": 1e7,
            "raw_open": 8.0 if is_post_div else 10.0,
            "raw_high": 8.5 if is_post_div else 10.5,
            "raw_low": 7.5 if is_post_div else 9.5,
            "raw_close": 8.0 if is_post_div else 10.0,
            "raw_prev_close": np.nan,  # upstream NULL — real panel reality
        })
    panel = pd.DataFrame(rows)
    entries = _build_entries(panel, signal_bar=29)
    trades, _ = simulate_portfolio(
        entries, panel,
        tp_pct=0.10, sl_pct=0.05, max_hold=10, max_positions=1,
        start_date=panel.iloc[0]["date"].strftime("%Y-%m-%d"),
        end_date=panel.iloc[-1]["date"].strftime("%Y-%m-%d"),
        initial_capital=100_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
        price_source_for_execution="raw_close",
    )
    assert len(trades) == 1
    # Entry fill MUST use raw_open (8.0), NOT adj_open (10.0)
    assert trades.iloc[0]["entry_price"] == pytest.approx(8.0)

# ---------- Phase 2 phantom TP prevention (2026-09-22) ----------

def test_phase2_backtrader_feed_uses_raw_when_price_source_is_raw_close():
    """Phase 2 backtrader 验证必须使用 raw_* 列, 而非 adj_* (Layout A §3).

    Bug (2026-09-22 audit): _verify_trade_with_backtrader 默认读 panel.open/high/low/close
    (adj_*, 来自 v_daily_qfq LEFT JOIN), 与 preset price_source_for_execution='raw_close'
    冲突 → phantom TP 触发在 adj 域 (e.g. v33_long_reverse_v20 Phase 2: 2/9 phantom).

    修复后: 当传入 price_source_for_execution='raw_close' 且 panel 含 raw_* 列,
    backtrader feed 用 raw_open/raw_high/raw_low/raw_close 重命名为 open/high/low/close,
    策略读到的就是 raw 域。
    """
    try:
        from uptrend_pullback.backtrader_engine import _verify_trade_with_backtrader
    except ImportError:
        pytest.skip("_verify_trade_with_backtrader not yet refactored to accept price_source")

    # 构造 panel: adj 与 raw 在 entry 后 2 根 bar 出现 divergence
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    rows = []
    for i, d in enumerate(dates):
        # Bar 1 (i=1) = entry_date, open=10.0, buy fills
        # Bar 3 (i=3): adj_high=10.95 (TP 触发 adj 域, 不会触发 raw 域)
        #               raw_high=10.30 (raw 域未触达 TP=10.50)
        if i == 1:
            o = h = lo = c = 10.0
            r_o = r_h = r_lo = r_c = 10.0
        elif i == 3:
            o, h, lo, c = 10.0, 10.95, 10.0, 10.0  # adj high > tp
            r_o, r_h, r_lo, r_c = 10.0, 10.30, 10.0, 10.0  # raw high < tp (phantom)
        else:
            o = h = lo = c = 10.0
            r_o = r_h = r_lo = r_c = 10.0
        rows.append({
            "thscode": "TEST.SH", "date": d,
            "open": o, "high": h, "low": lo, "close": c,
            "raw_open": r_o, "raw_high": r_h, "raw_low": r_lo, "raw_close": r_c,
            "raw_prev_close": r_c, "volume": 1e6, "amount": 1e7,
        })
    panel = pd.DataFrame(rows)
    entry_date = panel["date"].iloc[1]
    entry_price = 10.0
    tp_price = 10.50  # raw high=10.30 < tp → no TP trigger expected
    sl_price = 9.50

    net_pnl, exit_px, _ = _verify_trade_with_backtrader(
        panel, "TEST.SH", entry_date,
        entry_price, 1000,
        tp_price=tp_price, sl_price=sl_price, max_hold=10,
        price_source_for_execution="raw_close",  # ← 关键参数
    )
    # raw_high=10.30 < tp=10.50 → backtrader 不应触发 TP, exit 应为 time exit (close=10.0)
    assert exit_px == pytest.approx(10.0, abs=1e-6), (
        f"Phase 2 raw_close: TP 不应触发 (raw_high=10.30 < tp=10.50), "
        f"但 exit_price={exit_px}, 表明 feed 仍读 adj_high=10.95 → phantom TP"
    )
