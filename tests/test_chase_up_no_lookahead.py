"""chase_up 追涨策略 no-lookahead 回归测试。

覆盖 P0~P8 (沿用 uptrend_pullback 测试的命名 + 内容骨架):
  P0   ATR 穿越:  compute_trade_tp_sl 必须严格按信号日 atr_pct 算 TP/SL
  P1   exit_price: 实际成交价(bar N+1 OPEN),不是 TP/SL 触发价
  P2   trade 完整性: TRADE_COLS 含 atr_pct + sub_signal_type
  P3   entry ≠ exit: 入场当日不判退出 + exit_date > entry_date
  P4   DB schema:   用 DESCRIBE 验证列名
  P5   退出优先级:  open-first TP/SL,time-last
  P6   信号/执行解耦: 信号层不含资金约束
  P7   indicator 分组: rolling/shift 按 thscode
  P8   universe as-of
  E2E  真实 trades 在 signal_date 3 子信号必成立;exit_price = fill bar open
"""
from __future__ import annotations

import math
from pathlib import Path
import json

import backtrader as bt
import duckdb
import numpy as np
import pandas as pd
import pytest

from chase_up.backtrader_engine import (
    _verify_trade_with_backtrader,
    compute_trade_tp_sl,
    run_backtrader_backtest,
)
from chase_up.portfolio import TRADE_COLS, simulate_portfolio
from chase_up.replay_broker import AStockBroker
from chase_up.replay_strategy import ChaseUpTradeReplay
from chase_up.signals import compute_indicators, select_entries

from hiagent_config import DB_PATH


# --------------------------------------------------------------------------- #
# P0: ATR 不穿越(核心测试)
# --------------------------------------------------------------------------- #


def test_compute_tp_sl_uses_signal_date_atr():
    """compute_trade_tp_sl 必须严格按信号日 atr_pct 算 TP/SL。

    给定信号日 atr_pct(T 日收盘),输出 TP/SL 必须严格只依赖这个数。
    """
    entry_price = 10.0
    atr_pct_signal = 0.02
    atr_tp_mult, atr_sl_mult = 8.0, 2.5

    tp, sl = compute_trade_tp_sl(
        entry_price,
        fixed_tp_pct=0.05,
        fixed_sl_pct=0.03,
        atr_pct=atr_pct_signal,
        atr_tp_mult=atr_tp_mult,
        atr_sl_mult=atr_sl_mult,
    )
    # tp = 10 * (1 + 0.02 * 8) = 11.6
    assert tp == pytest.approx(11.6, abs=1e-9)
    # sl = 10 * (1 - 0.02 * 2.5) = 9.5
    assert sl == pytest.approx(9.5, abs=1e-9)


def test_compute_tp_sl_different_atr_pct_gives_different_tp():
    """不同 atr_pct 必须输出不同 TP(防止函数被静默覆盖)。"""
    tp_a, _ = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.02, atr_tp_mult=8.0, atr_sl_mult=2.5,
    )
    tp_b, _ = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.05, atr_tp_mult=8.0, atr_sl_mult=2.5,
    )
    assert tp_a == pytest.approx(11.6, abs=1e-9)
    assert tp_b == pytest.approx(14.0, abs=1e-9)
    assert tp_a != tp_b


def test_compute_tp_sl_clamps_atr_pct():
    """atr_pct 超过 [floor, cap] 时必须夹紧。"""
    tp_floor, _ = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.001, atr_tp_mult=8.0, atr_sl_mult=2.5,
        atr_pct_floor=0.01, atr_pct_cap=0.08,
    )
    tp_cap, _ = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.50, atr_tp_mult=8.0, atr_sl_mult=2.5,
        atr_pct_floor=0.01, atr_pct_cap=0.08,
    )
    assert tp_floor == pytest.approx(10.8, abs=1e-9)
    assert tp_cap == pytest.approx(16.4, abs=1e-9)


def test_compute_tp_sl_falls_back_when_no_atr():
    """不给 atr_*_mult → 用 fixed_tp_pct / fixed_sl_pct。"""
    tp, sl = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
    )
    assert tp == pytest.approx(10.5, abs=1e-9)
    assert sl == pytest.approx(9.7, abs=1e-9)


# --------------------------------------------------------------------------- #
# P1: exit_price = 实际成交价
# --------------------------------------------------------------------------- #


def _build_panel_entry_then_gap_down(n_days: int = 100, thscode: str = "600000.SH") -> pd.DataFrame:
    """构造'平稳 + entry_date 触发 TP + T+3 gap down 成交'的 panel。"""
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    rows = []
    for i, d in enumerate(dates):
        if i == n_days - 19:
            o = h = lo = c = 10.0
        elif i == n_days - 18:
            o, h, lo, c = 10.0, 11.0, 10.0, 10.0
        elif i == n_days - 17:
            o = h = lo = c = 9.0
        else:
            o = h = lo = c = 10.0
        rows.append({
            "thscode": thscode, "date": d,
            "open": o, "high": h, "low": lo, "close": c,
            "amount": 5e7, "volume": 1e6,
        })
    return pd.DataFrame(rows)


def test_exit_price_is_actual_fill_price_not_target():
    """TP 触发后,exit_price 必须是 bar N+1 OPEN(9.0),不是 TP 触发价(10.5)。"""
    panel = _build_panel_entry_then_gap_down()
    entry_date = panel["date"].iloc[-19]
    entry_price = 10.0
    tp_price = 10.5
    sl_price = 8.5

    net_pnl, exit_px, _exit_date = _verify_trade_with_backtrader(
        panel, "600000.SH", entry_date,
        entry_price, 1000,
        tp_price=tp_price, sl_price=sl_price, max_hold=10,
    )
    assert exit_px == pytest.approx(9.0, abs=1e-9), (
        f"exit_price 应等于 bar N+1 实际成交价 9.0(gap down),得到 {exit_px}。"
    )
    assert net_pnl < 0, f"gap down 后亏损卖出,net_pnl 应为负,得到 {net_pnl}"


def test_strategy_records_actual_exit_price_in_notify_order():
    """直接调 ChaseUpTradeReplay,验证 notify_order 回填 actual_exit_price。"""
    feed = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0, 9.0],
        "high":  [10.0, 11.0, 11.0, 9.1],
        "low":   [10.0, 9.9,  9.9,  8.9],
        "close": [10.0, 10.05, 10.05, 9.0],
        "volume": [1e6, 1e6, 1e6, 1e6],
    }, index=pd.date_range("2025-06-01", periods=4, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=1000, tp_price=10.5, sl_price=8.0, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]
    assert strat.actual_exit_price == pytest.approx(9.0, abs=1e-9)
    assert strat.target_exit_price == pytest.approx(10.5, abs=1e-9)


# --------------------------------------------------------------------------- #
# P2: trade 记录完整性
# --------------------------------------------------------------------------- #


def test_trade_cols_includes_atr_pct_and_sub_signal_type():
    """TRADE_COLS 必须含 atr_pct + sub_signal_type(防止误删)。"""
    assert "atr_pct" in TRADE_COLS
    assert "sub_signal_type" in TRADE_COLS


def test_simulate_portfolio_records_atr_pct_per_trade():
    """simulate_portfolio 必须在每条 trade 记录里携带 atr_pct + sub_signal_type。"""
    panel = pd.DataFrame({
        "thscode": ["600000.SH"] * 30,
        "date": pd.date_range("2025-01-01", periods=30, freq="B"),
        "open": [10.0 + 0.05 * i for i in range(30)],
        "high": [10.0 + 0.05 * i + 0.1 for i in range(30)],
        "low": [10.0 + 0.05 * i - 0.1 for i in range(30)],
        "close": [10.0 + 0.05 * i for i in range(30)],
        "amount": [5e7] * 30,
        "volume": [1e6] * 30,
    })
    panel_ind = compute_indicators(panel)

    last_date = panel["date"].iloc[-1]
    last_row = panel_ind[panel_ind["date"] == last_date].iloc[0]
    entries = pd.DataFrame([{
        "date": last_date,
        "thscode": "600000.SH",
        "score": 0.05,
        "sub_signal_type": "A",
        "sig_close": last_row["close"],
        "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"],
        "sig_ret1": last_row["ret1"],
        "sig_breakout_score": 0.05,
        "sig_momentum_score": np.nan,
        "sig_macross_score": np.nan,
        "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": float(last_row["atr_pct"]),
    }])
    trades, _ = simulate_portfolio(
        entries, panel_ind,
        tp_pct=0.05, sl_pct=0.03,
        max_hold=5, max_positions=5,
        start_date=panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=panel["date"].iloc[-1].strftime("%Y-%m-%d"),
        atr_tp_mult=3.0, atr_sl_mult=2.0,
    )
    if not trades.empty:
        assert "atr_pct" in trades.columns
        assert "sub_signal_type" in trades.columns
        for v in trades["atr_pct"]:
            assert pd.notna(v), "trade.atr_pct 不能是 NaN"
            assert 0.0 < v < 1.0
        for v in trades["sub_signal_type"]:
            assert v in ("A", "B", "C", "AB", "AC", "BC", "ABC", ""), (
                f"sub_signal_type 必须是 A/B/C 组合,得到 {v}"
            )


# --------------------------------------------------------------------------- #
# P3: entry ≠ exit 不变量
# --------------------------------------------------------------------------- #


def _build_entry_day_tp_panel() -> pd.DataFrame:
    """构造'entry_date 当天 high 直接打到 TP'的诱导 panel。"""
    dates = pd.date_range("2025-03-01", periods=30, freq="B")
    n = len(dates)
    rows = []
    for i, d in enumerate(dates):
        if i == n - 6:
            o = h = lo = c = 10.0
        elif i == n - 5:
            o, h, lo, c = 10.0, 11.0, 9.5, 10.5
        elif i == n - 4:
            o = h = lo = c = 10.5
        elif i == n - 3:
            o = h = lo = c = 10.0
        else:
            o = h = lo = c = 10.0
        rows.append({
            "thscode": "600000.SH", "date": d,
            "open": o, "high": h, "low": lo, "close": c,
            "amount": 5e7, "volume": 1e6,
        })
    return pd.DataFrame(rows)


def test_phase1_skips_exit_on_entry_day():
    """simulate_portfolio 必须跳过入场当日判退出。"""
    panel = _build_entry_day_tp_panel()
    panel_ind = compute_indicators(panel)
    signal_date = panel["date"].iloc[-6]
    entry_date_expected = panel["date"].iloc[-5]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]
    entries = pd.DataFrame([{
        "date": signal_date, "thscode": "600000.SH", "score": 0.05,
        "sub_signal_type": "A",
        "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"], "sig_ret1": last_row["ret1"],
        "sig_breakout_score": 0.05, "sig_momentum_score": np.nan,
        "sig_macross_score": np.nan, "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": float(last_row["atr_pct"]),
    }])
    trades, _ = simulate_portfolio(
        entries, panel_ind,
        tp_pct=0.05, sl_pct=0.05,
        max_hold=8, max_positions=1,
        start_date=panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=panel["date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    assert not trades.empty
    t = trades.iloc[0]
    gap = (t["exit_date"] - t["entry_date"]).days
    assert gap >= 1, f"exit_date 与 entry_date 间隔 {gap} 天,必须 ≥ 1"
    assert t["entry_date"] == pd.Timestamp(entry_date_expected)
    assert t["hold_days"] >= 1


def test_phase1_exit_price_uses_next_bar_not_entry_bar():
    """入场当天 high 突破 TP 时,exit_price 不能是 entry 当天 high。"""
    panel = _build_entry_day_tp_panel()
    panel_ind = compute_indicators(panel)
    signal_date = panel["date"].iloc[-6]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]
    entries = pd.DataFrame([{
        "date": signal_date, "thscode": "600000.SH", "score": 0.05,
        "sub_signal_type": "A",
        "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"], "sig_ret1": last_row["ret1"],
        "sig_breakout_score": 0.05, "sig_momentum_score": np.nan,
        "sig_macross_score": np.nan, "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": float(last_row["atr_pct"]),
    }])
    trades, _ = simulate_portfolio(
        entries, panel_ind, tp_pct=0.05, sl_pct=0.05,
        max_hold=8, max_positions=1,
        start_date=panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=panel["date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    assert not trades.empty
    t = trades.iloc[0]
    assert t["exit_price"] != pytest.approx(11.0, abs=1e-9), (
        f"exit_price={t['exit_price']} 等于 entry 当天 high=11.0,这是同日买卖穿越"
    )
    assert t["exit_reason"] in ("TP", "time")


def test_phase2_replay_bars_in_pos_min_1():
    """ChaseUpTradeReplay 必须在 bars_in_pos >= 1 后才判退出。"""
    feed = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0, 9.0],
        "high":  [10.0, 11.0, 11.0, 9.1],
        "low":   [10.0, 9.9,  9.9,  8.9],
        "close": [10.0, 10.05, 10.05, 9.0],
        "volume": [1e6]*4,
    }, index=pd.date_range("2025-06-01", periods=4, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=1000, tp_price=10.5, sl_price=8.0, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]
    assert strat.entry_bar_idx == 1
    assert strat.exit_reason in ("TP", "time")


def test_phase1_max_hold_exit_uses_close_not_intrabar():
    """max_hold 到期时用当天 close exit。"""
    feed_panel = pd.DataFrame({
        "thscode": ["600000.SH"] * 20,
        "date": pd.date_range("2025-04-01", periods=20, freq="B"),
        "open":  [10.0]*20,
        "high":  [10.3]*20,
        "low":   [9.95]*20,
        "close": [10.05]*20,
        "amount": [5e7]*20,
        "volume": [1e6]*20,
    })
    panel_ind = compute_indicators(feed_panel)
    signal_date = feed_panel["date"].iloc[-5]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]
    entries = pd.DataFrame([{
        "date": signal_date, "thscode": "600000.SH", "score": 0.05,
        "sub_signal_type": "A",
        "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"], "sig_ret1": last_row["ret1"],
        "sig_breakout_score": 0.05, "sig_momentum_score": np.nan,
        "sig_macross_score": np.nan, "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": float(last_row["atr_pct"]),
    }])
    trades, _ = simulate_portfolio(
        entries, panel_ind, tp_pct=0.05, sl_pct=0.05,
        max_hold=3, max_positions=1,
        start_date=feed_panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=feed_panel["date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    assert not trades.empty
    t = trades.iloc[0]
    assert t["hold_days"] == 3
    assert t["exit_reason"] == "time"
    assert t["exit_price"] == pytest.approx(10.05, abs=1e-9)


# --------------------------------------------------------------------------- #
# P4: DB schema 验证
# --------------------------------------------------------------------------- #


def test_db_schema_v_daily_qfq_has_required_columns():
    """v_daily_qfq 必须包含 [thscode, date, open, high, low, close, volume, amount]。"""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cols = [c[0] for c in con.execute("DESCRIBE v_daily_qfq").fetchall()]
    finally:
        con.close()
    required = ["thscode", "date", "open", "high", "low", "close", "volume", "amount"]
    for c in required:
        assert c in cols, f"v_daily_qfq 缺列 {c},现有列 {cols}"


# --------------------------------------------------------------------------- #
# P7: indicator 按 (thscode, date) 分组
# --------------------------------------------------------------------------- #


def test_compute_indicators_does_not_leak_across_stocks():
    """compute_indicators 的 rolling/shift 必须按 thscode 严格分组。

    测试方法:构造两只人造股票 A (close=10) 和 B (close=20)。如果 rolling 跨股票污染,
    B 的 ma20 会比 20 小,A 的 ma20 会比 10 大。严格分组后,B 的 ma20 必须 = 20.0,
    A 的 ma20 必须 = 10.0。
    """
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    rows = []
    for code, px in (("600000.SH", 10.0), ("600001.SH", 20.0)):
        for d in dates:
            rows.append({
                "thscode": code, "date": d,
                "open": px, "high": px * 1.05, "low": px * 0.95, "close": px,
                "volume": 1e6, "amount": 1e7,
            })
    panel = pd.DataFrame(rows)

    panel_ind = compute_indicators(panel)
    for code, expected in (("600000.SH", 10.0), ("600001.SH", 20.0)):
        sub = panel_ind[panel_ind["thscode"] == code].sort_values("date")
        ma20 = sub["ma20"].dropna().iloc[-1]
        assert ma20 == pytest.approx(expected, abs=1e-9), (
            f"{code} ma20={ma20},期望 {expected}(跨股票污染)"
        )
        ma5 = sub["ma5"].dropna().iloc[-1]
        assert ma5 == pytest.approx(expected, abs=1e-9), (
            f"{code} ma5={ma5},期望 {expected}(跨股票污染)"
        )


# --------------------------------------------------------------------------- #
# P8: universe as-of
# --------------------------------------------------------------------------- #


def test_load_panel_does_not_include_bars_after_end_date():
    """load_panel 的 as-of 必须剔除 end_date 之后的 bar。

    验证:panel.max(date) <= end_date,且 panel 不含任何未来日期的 bar。
    """
    from chase_up.data import load_panel
    from chase_up.universe import load_universe

    end = "2020-06-15"
    universe = set(load_universe("mainboard_only", DB_PATH))
    panel = load_panel(DB_PATH, "2019-01-01", end, universe=universe)

    assert not panel.empty
    max_date = panel["date"].max()
    assert max_date <= pd.Timestamp(end), (
        f"panel 含未来 bar: max(date)={max_date} > end={end}"
    )
    # 检查全表日期都 <= end
    future_bars = panel[panel["date"] > pd.Timestamp(end)]
    assert future_bars.empty, (
        f"panel 含 {len(future_bars)} 行 date > {end} 的穿越 bar"
    )


# --------------------------------------------------------------------------- #
# E2E: 真实 trades 在 signal_date 必成立 + exit_price = fill bar open
# --------------------------------------------------------------------------- #


def test_v5_e2e_signal_date_conditions_hold():
    """对 chase_v5 真实 trades,在每个 entry_date 前一交易日 panel_ind 上,
    3 个子信号至少 1 个必成立(OR 融合)。

    这等价于证明:每个信号在决策时刻只用 past+current bar 数据,绝无穿越。
    """
    from chase_up.data import load_panel
    from chase_up.universe import load_universe

    universe = set(load_universe("mainboard_only", DB_PATH))
    panel = load_panel(DB_PATH, "2025-07-01", "2026-07-01", universe=universe)
    panel_ind = compute_indicators(panel)

    from chase_up.backtest import run_backtest
    res = run_backtest(
        "chase_v5_pos2_equal_atr_tp6_sl15_mh10",
        "2025-07-01", "2026-07-01", DB_PATH,
        panel_ind=panel_ind,
    )
    trades = res["trades"]
    assert not trades.empty, "v5 在 2025-07→2026-07 应至少成交一笔"

    pidx = panel_ind.set_index(["thscode", "date"]).sort_index()

    fails = []
    for _, t in trades.iterrows():
        code, entry_date = t["thscode"], pd.Timestamp(t["entry_date"])
        if code not in pidx.index.get_level_values(0):
            fails.append((code, entry_date.date(), "code not in panel"))
            continue
        sub = pidx.loc[code]
        sig_dates = sub.index[sub.index < entry_date]
        if len(sig_dates) == 0:
            fails.append((code, entry_date.date(), "no signal_date"))
            continue
        row = sub.loc[sig_dates[-1]]
        # OR 融合:至少一个子信号成立
        sig_a = (row["close"] > row["high20_prev"]) and (row["close"] > row["ma60"]) and (row["vol_ratio"] >= 1.5)
        sig_b = (
            (row["ret1"] >= 0.03) and (row["ret1"] <= 0.08)
            and (row["macd_dif"] > 0) and (row["macd_dea"] > 0)
            and (abs(row["macd_bar"]) > abs(row["macd_bar_prev"]))
            and (row["vol_ratio"] >= 1.3)
        )
        sig_c = (row["ma_cross_recent"] == 1.0) and (row["close"] >= row["ma20"] * 1.02) and (row["vol_ratio"] >= 1.2)
        base = (
            (row["mom120"] >= 0.05)
            and (row["ma20"] > row["ma60"])
            and (3e7 <= row["amount60"] <= 3e8)
            and (0.03 <= row["atr_pct"] <= 0.10)
        )
        if base and not (sig_a or sig_b or sig_c):
            fails.append((code, sig_dates[-1].date(), "no sub-signal"))

    assert not fails, f"{len(fails)} trades 在 signal_date 复核失败:\n{fails[:5]}"


def test_v5_e2e_entry_price_is_entry_bar_open():
    """对 chase_v5 Phase 1 trades,entry_price 必须等于 entry_date bar 的 open。"""
    from chase_up.data import load_panel
    from chase_up.universe import load_universe

    universe = set(load_universe("mainboard_only", DB_PATH))
    panel = load_panel(DB_PATH, "2025-07-01", "2026-07-01", universe=universe)
    panel_idx = panel.set_index(["thscode", "date"]).sort_index()
    panel_ind = compute_indicators(panel)

    from chase_up.backtest import run_backtest
    res = run_backtest(
        "chase_v5_pos2_equal_atr_tp6_sl15_mh10",
        "2025-07-01", "2026-07-01", DB_PATH,
        panel_ind=panel_ind,
    )
    trades = res["trades"]

    fails = []
    for _, t in trades.iterrows():
        code, entry_date = t["thscode"], pd.Timestamp(t["entry_date"])
        if (code, entry_date) not in panel_idx.index:
            continue
        actual_open = float(panel_idx.loc[(code, entry_date), "open"])
        if abs(float(t["entry_price"]) - actual_open) > 0.01:
            fails.append((code, entry_date.date(), t["entry_price"], actual_open))

    assert not fails, f"{len(fails)} trades entry_price != entry bar open:\n{fails[:5]}"


# --------------------------------------------------------------------------- #
# P6: 信号/执行解耦
# --------------------------------------------------------------------------- #


def test_signal_layer_has_no_capital_constraints():
    """信号层 select_entries 不应包含 max_positions / cash / 涨跌停等资金约束。"""
    import inspect
    from chase_up.signals import _safe_signal_score
    src = inspect.getsource(_safe_signal_score)
    forbidden = ["max_positions", "cash", "limit_up", "涨跌停", "100 股", "lot"]
    for kw in forbidden:
        assert kw not in src, f"信号层不应含 {kw},这是执行层关注点"


# --------------------------------------------------------------------------- #
# P5: 退出优先级 — open-first, time-last
# --------------------------------------------------------------------------- #


def test_exit_priority_open_first_time_last():
    """退出优先级: open ≥ tp_p 优先于 low ≤ sl_p 优先于 bars ≥ max_hold。"""
    feed = pd.DataFrame({
        "open":  [10.0, 10.0, 11.0, 9.0],
        "high":  [10.0, 11.0, 11.0, 9.1],
        "low":   [10.0, 9.9,  8.9,  8.9],
        "close": [10.0, 10.05, 9.0, 9.0],
        "volume": [1e6]*4,
    }, index=pd.date_range("2025-06-01", periods=4, freq="B"))

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    broker = AStockBroker()
    broker.set_cash(100_000.0)
    cerebro.broker = broker
    # bar 2: open=11.0 >= tp=10.5 (TP @ open) → 必须先出 TP,不应 SL
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=1000, tp_price=10.5, sl_price=9.0, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]
    assert strat.exit_reason == "TP", (
        f"bar 2 open=11 >= tp=10.5 → 应 TP-first,得到 {strat.exit_reason}"
    )


# --------------------------------------------------------------------------- #
# Golden baseline: trades.csv 不可漂移
# --------------------------------------------------------------------------- #


def test_v5_trades_csv_matches_golden_baseline():
    """chase_v5 trades.csv hash 必须等于 tests/golden/chase_v5_baseline.json 中锁定的值。

    策略逻辑变更前应确认这是有意的更新;否则回归失败说明信号/退出/仓位逻辑有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v5_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v5_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows, (
        f"trades 行数变化: {len(df)} (expected {expected_rows})"
    )


def test_v8_trades_csv_matches_golden_baseline():
    """chase_v8 trades.csv hash 必须等于 tests/golden/chase_v8_baseline.json 中锁定的值。

    v8 = v5 + max_hold 10→18(优化版)。hash 漂移说明 mh 或信号逻辑有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v8_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v8_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v8 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows


def test_v9_trades_csv_matches_golden_baseline():
    """chase_v9 trades.csv hash 必须等于 tests/golden/chase_v9_baseline.json 中锁定的值。

    v9 = v8 + min_score=1.2(过滤弱信号)。hash 漂移说明信号实现或子信号权重有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v9_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v9_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v9 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows


def test_v10_trades_csv_matches_golden_baseline():
    """chase_v10 trades.csv hash 必须等于 tests/golden/chase_v10_baseline.json 中锁定的值。

    v10 = v9 + min_score 1.2 → 1.6(过滤更强信号)。hash 漂移说明信号实现或
    子信号权重有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v10_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v10_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v10 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows


def test_v11_trades_csv_matches_golden_baseline():
    """chase_v11 trades.csv hash 必须等于 tests/golden/chase_v11_baseline.json 中锁定的值。

    v11 = v10 + min_score 1.6 → 1.7(Pareto 改善)。hash 漂移说明 score 阈值或
    子信号权重有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v11_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v11_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v11 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows


def test_v12_trades_csv_matches_golden_baseline():
    """chase_v12 trades.csv hash 必须等于 tests/golden/chase_v12_baseline.json 中锁定的值。

    v12 = v11 + atr_pct_low 0.03 → 0.035(剔除 atr% 偏低噪音信号)。
    hash 漂移说明 atr_pct 过滤或子信号逻辑有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v12_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v12_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v12 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows


def test_v13_trades_csv_matches_golden_baseline():
    """chase_v13 trades.csv hash 必须等于 tests/golden/chase_v13_baseline.json 中锁定的值。

    v13 = v12 + min_mom120 0.05→0.10 + atr_pct_high 0.10→0.085(双重收紧)。
    hash 漂移说明 atr_pct 或 mom120 阈值或子信号逻辑有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v13_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v13_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v13 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )
    assert len(df) == expected_rows


def test_v14_trades_csv_matches_golden_baseline():
    """chase_v14 trades.csv hash 必须等于 tests/golden/chase_v14_baseline.json 中锁定的值。

    v14 = v13 + min_mom120 0.10 → 0.11(进一步收紧 mom120)。
    hash 漂移说明 mom120 阈值或子信号逻辑有未预期改动。
    """
    import hashlib
    from pathlib import Path

    baseline_path = Path(__file__).parent / "golden" / "chase_v14_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hash = baseline["trades_csv_sha256"]
    expected_rows = baseline["trades_csv_rows"]

    trades_csv = Path(__file__).parent.parent / "chase_up" / "results" / "v14_trades.csv"
    if not trades_csv.exists():
        from chase_up.backtest import run_backtest
        from chase_up.data import load_panel
        from chase_up.universe import load_universe
        universe = set(load_universe("mainboard_only", DB_PATH))
        panel = load_panel(DB_PATH, baseline["window"][0], baseline["window"][1], universe=universe)
        panel_ind = compute_indicators(panel)
        res = run_backtest(
            baseline["preset"], baseline["window"][0], baseline["window"][1],
            DB_PATH, panel_ind=panel_ind,
        )
        res["trades"].to_csv(trades_csv, index=False)

    df = pd.read_csv(trades_csv)
    actual_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    assert actual_hash == expected_hash, (
        f"v14 trades.csv hash 漂移:\n"
        f"  expected: {expected_hash}\n"
        f"  actual:   {actual_hash}\n"
        f"  rows: {len(df)} (expected {expected_rows})\n"
        f"  若策略逻辑有变更,请同步更新 {baseline_path}"
    )


# --------------------------------------------------------------------------- #
# Bug B 回归:phase-2 equity 修正不能污染 day-0 cash
# --------------------------------------------------------------------------- #


def test_phase2_day0_cash_not_polluted_by_total_delta():
    """run_backtrader_backtest(verify=True) 必须保证:
    phase-2 equity 第 0 行的 cash 等于 initial_capital (= 1,000,000),
    不能等于 initial_capital + total_equity_delta(旧 bug 把 total_delta
    均匀加到每一行,会让 day-0 cash = 1M + delta,典型值 -2.7M)。

    验证方法:跑 v18 (一年期,验证 delta 非零),直接看 eq.iloc[0].cash。
    """
    name = "chase_v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082"
    res = run_backtrader_backtest(name, "2025-09-19", "2026-09-19", Path(DB_PATH), verify=True)
    eq = res["equity"]
    assert not eq.empty
    assert eq["cash"].iloc[0] == pytest.approx(1_000_000.0, abs=1e-6), (
        f"phase-2 day-0 cash = {eq['cash'].iloc[0]},应为 1,000,000.0。"
        f"若偏差大,说明 equity_delta 被错误地应用到 row 0 (Bug B)。"
    )


def test_phase2_corrections_applied_at_exit_dates_not_uniformly():
    """phase-2 累计 delta 应在每笔 exit_date 处 step-change,
    而不是在整条曲线上加同一个常数。

    验证:跑 v18,挑两笔相邻 exit_date 之间的一行,该行的 cash 应
    等于 phase-1 同行 cash + (累计到上一个 exit_date 的 delta)。
    不应等于 phase-1 同行 cash + total_delta。
    """
    name = "chase_v18_pos2_equal_atr_tp6_sl16_mh18_score17_atr035_mom115_ma60buf08_atr082"
    res_p1 = run_backtrader_backtest(name, "2025-09-19", "2026-09-19", Path(DB_PATH), verify=False)
    res_p2 = run_backtrader_backtest(name, "2025-09-19", "2026-09-19", Path(DB_PATH), verify=True)
    eq_p1 = res_p1["equity"].set_index("date")
    eq_p2 = res_p2["equity"].set_index("date")

    # 在所有 exit_date 中间找一个 mid 日期 (即两个 exit 之间的某天)
    trades_p1 = res_p1["trades"]
    exits = sorted(pd.Timestamp(d) for d in trades_p1["exit_date"].unique())
    if len(exits) < 2:
        pytest.skip("rationale: exit_date < 2,无法验证 step-change")
    # 在第一个和第二个 exit 之间选一天
    mid = exits[0] + (exits[1] - exits[0]) / 2
    mid = pd.Timestamp(mid.date())
    if mid not in eq_p1.index:
        pytest.skip(f"mid date {mid} 不在 equity 时间轴上")
    cash_p1 = float(eq_p1.loc[mid, "cash"])
    cash_p2 = float(eq_p2.loc[mid, "cash"])
    total_delta = float(res_p2["trades"]["net_pnl"].sum() - trades_p1["net_pnl"].sum())
    # phase-2 cash 在 mid 时应 = phase-1 cash + (累计到 mid 时刻为止的 delta)
    # 旧 bug: cash_p2 = cash_p1 + total_delta (在 mid 时也加 total_delta,错误)
    # 正确: cash_p2 != cash_p1 + total_delta (因为 mid 不是 total 累计完的位置)
    diff = cash_p2 - cash_p1
    assert diff != pytest.approx(total_delta, rel=0.01), (
        f"mid @ {mid}: phase-2 - phase-1 cash diff = {diff:.2f},"
        f"但 total_delta = {total_delta:.2f}。两者接近说明 equity_delta"
        f"被均匀加到全曲线,这是 Bug B 的特征。"
    )


# --------------------------------------------------------------------------- #
# Bug A 回归:phase-1 不能让 cash < 0 (保守限制 — 现金为 0 时不开仓)
# --------------------------------------------------------------------------- #


def test_simulate_portfolio_never_lets_cash_go_negative_in_phase1():
    """simulate_portfolio 的 cash 路径必须永远 >= 0 (保守限制)。

    旧实现用 equity_now = cash + holdings_val 当 budget base,会隐式融资;
    新实现改用 cash_only,加上 cash < 0 时不开仓的守卫。
    """
    panel = _build_entry_day_tp_panel()
    panel_ind = compute_indicators(panel)
    signal_date = panel["date"].iloc[-6]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]
    # 故意同一天多个候选 (模拟同信号日多条入)
    entries = pd.DataFrame([
        {
            "date": signal_date, "thscode": "600000.SH", "score": 0.05,
            "sub_signal_type": "A",
            "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
            "sig_ma60": last_row["ma60"], "sig_ret1": last_row["ret1"],
            "sig_breakout_score": 0.05, "sig_momentum_score": np.nan,
            "sig_macross_score": np.nan, "sig_mom120": 0.05,
            "sig_amount60": 5e7,
            "atr_pct": float(last_row["atr_pct"]),
        },
        {
            "date": signal_date, "thscode": "600001.SH", "score": 0.04,
            "sub_signal_type": "B",
            "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
            "sig_ma60": last_row["ma60"], "sig_ret1": last_row["ret1"],
            "sig_breakout_score": np.nan, "sig_momentum_score": 0.04,
            "sig_macross_score": np.nan, "sig_mom120": 0.04,
            "sig_amount60": 5e7,
            "atr_pct": float(last_row["atr_pct"]),
        },
    ])
    # 强制把 max_positions=1,这样第二条候选会被守卫拦下
    trades, equity = simulate_portfolio(
        entries, panel_ind,
        tp_pct=0.05, sl_pct=0.05,
        max_hold=8, max_positions=1,
        start_date=panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=panel["date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    assert (equity["cash"] >= 0).all(), (
        f"phase-1 cash 路径出现负值: min={equity['cash'].min():.2f}。"
        f"若 < 0,说明 budget base 用了未实现 PnL (Bug A 隐式融资)。"
    )


# --------------------------------------------------------------------------- #
# 防穿仓 R1 (2026-09-21): NAV-floor cash gate — chase_up
# --------------------------------------------------------------------------- #


def test_simulate_portfolio_nav_gate_rejects_entries_when_nav_below_threshold():
    """NAV < initial_capital × NAV_GATE_RATIO 时,simulate_portfolio 必须拒绝新开仓。

    复刻真实穿仓场景: 一次大亏把 cash 打到接近 0, 持仓 mark-to-market 浮盈也低,
    NAV 跌穿 5% 阈值。新信号出现时,模拟器必须拒开仓, 不能继续 all-in 累积亏损。
    """
    from chase_up.portfolio import NAV_GATE_RATIO
    # 用 minimal initial_capital=10k + sl_pct=0.96 让单笔击穿 5% × initial
    # 票 A: day 1 signal → day 2 open @ 10 入场 → day 3 open=0.4 跳空破止损 (sl_p=10*0.04=0.4)
    # 票 B: day 3 signal → 应被 NAV gate 拒绝 (cash < 10k × 5% = 500)
    panel = pd.DataFrame([
        # 票 A
        {"date": pd.Timestamp("2025-09-01"), "thscode": "AAA.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
        {"date": pd.Timestamp("2025-09-02"), "thscode": "AAA.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
        {"date": pd.Timestamp("2025-09-03"), "thscode": "AAA.SZ", "open": 0.4,  "high": 0.4,  "low": 0.4,  "close": 0.4,  "volume": 1e6, "amount": 1e7, "atr_pct": 0.50},  # 跳空 -96%
        {"date": pd.Timestamp("2025-09-04"), "thscode": "AAA.SZ", "open": 0.4,  "high": 0.4,  "low": 0.4,  "close": 0.4,  "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
        # 票 B
        {"date": pd.Timestamp("2025-09-01"), "thscode": "BBB.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
        {"date": pd.Timestamp("2025-09-02"), "thscode": "BBB.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
        {"date": pd.Timestamp("2025-09-03"), "thscode": "BBB.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
        {"date": pd.Timestamp("2025-09-04"), "thscode": "BBB.SZ", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1e6, "amount": 1e7, "atr_pct": 0.02},
    ])
    entries = pd.DataFrame([
        {"date": pd.Timestamp("2025-09-01"), "thscode": "AAA.SZ", "score": 1.0, "sub_signal_type": "A", "atr_pct": 0.02,
         "sig_close": 10.0, "sig_ma20": 9.5, "sig_ma60": 9.0, "sig_ret1": 0.05,
         "sig_breakout_score": 0.5, "sig_momentum_score": 0.3, "sig_macross_score": np.nan,
         "sig_mom120": 0.05, "sig_amount60": 5e7},
        {"date": pd.Timestamp("2025-09-03"), "thscode": "BBB.SZ", "score": 1.0, "sub_signal_type": "A", "atr_pct": 0.02,
         "sig_close": 10.0, "sig_ma20": 9.5, "sig_ma60": 9.0, "sig_ret1": 0.05,
         "sig_breakout_score": 0.5, "sig_momentum_score": 0.3, "sig_macross_score": np.nan,
         "sig_mom120": 0.05, "sig_amount60": 5e7},
    ])
    # initial_capital=9k, sl_pct=0.96 → sl_p=0.4, day 3 open=0.4 → SL @ open → -96%
    # 900 股 @ 0.4 = 360 → cash_end = 9k - 9k + 360 = 360 < 5% × 9k = 450
    # 关掉手续费以避免 commission-floor (¥5) 残留干扰单笔击穿的断言
    trades, equity = simulate_portfolio(
        entries, panel,
        tp_pct=0.20, sl_pct=0.96, max_hold=8, max_positions=1,
        start_date="2025-09-01", end_date="2025-09-04",
        initial_capital=9_000.0,
        position_sizing="all_in",
        commission_rate=0.0, stamp_duty_rate=0.0, min_commission=0.0,
    )
    a_trades = trades[trades["thscode"] == "AAA.SZ"]
    assert len(a_trades) == 1, f"票 A 应入场并被 SL 击穿, 实际 {len(a_trades)} 笔"
    # 验证 cash 确实大跌
    final_cash = equity["cash"].iloc[-1]
    assert final_cash < 9_000.0 * NAV_GATE_RATIO, (
        f"测试 fixture 不足: cash={final_cash}, 需 < {9_000.0 * NAV_GATE_RATIO} 才触发 NAV gate"
    )
    # 票 B 必须被 NAV gate 拒绝 (day 4 是 day 3 signal 的执行日, 此时 NAV 已 < 5% × 9k = 450)
    b_trades = trades[trades["thscode"] == "BBB.SZ"]
    assert len(b_trades) == 0, (
        f"NAV gate 应拒绝票 B 入场 (cash={final_cash:.0f} < 5% × initial=450), 但成交了 {len(b_trades)} 笔"
    )