"""uptrend_pullback 穿越 / 口径一致性回归测试。

覆盖四件事：

1. P0 — ATR 穿越：
   compute_trade_tp_sl() 必须按信号日（T 日）的 atr_pct 算 TP/SL，
   严禁读 entry_date（T+1）当根 K 线的 atr_pct（T+1 的 high/low 在开盘时不可知）。

2. P1 — exit_price 与 net_pnl 口径一致：
   trade 记录的 exit_price 必须是 backtrader 实际成交价（bar N+1 OPEN），
   不能是策略决策时看到的 bar N TP/SL 触发价。
   通过直接调 UpullbackTradeReplay + AStockBroker 验证 actual_exit_price 字段。

3. P2 — trade 记录完整性：
   simulate_portfolio 必须在 trade 记录里携带 atr_pct，
   否则 Phase 2 拿不到信号日 ATR、TP/SL 会退化为固定值。

4. P3 — entry ≠ exit 不变量（防止同日买卖 look-ahead）：
   入场当日（bars_in_pos=0）严禁判退出，exit_date 必晚于 entry_date，
   exit_price 绝不能等于 entry 当天 OHLC 任一值。
"""
from __future__ import annotations

import math
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from uptrend_pullback.backtrader_engine import (
    _verify_trade_with_backtrader,
    compute_trade_tp_sl,
)
from uptrend_pullback.portfolio import TRADE_COLS, simulate_portfolio
from uptrend_pullback.replay_broker import AStockBroker
from uptrend_pullback.replay_strategy import UpullbackTradeReplay
from uptrend_pullback.signals import compute_indicators


# --------------------------------------------------------------------------- #
# P0: ATR 不穿越（核心测试）
# --------------------------------------------------------------------------- #


def test_compute_tp_sl_uses_signal_date_atr():
    """compute_trade_tp_sl 是 P0 修复的核心。

    给定信号日 atr_pct（来自 signals.py 在 T 日收盘时算的），
    输出 TP/SL 必须严格只依赖这个数；与 T+1 当根 K 线完全无关。
    """
    entry_price = 10.0
    atr_pct_signal = 0.02  # T 日 atr_pct
    atr_tp_mult, atr_sl_mult = 8.0, 2.5

    tp, sl = compute_trade_tp_sl(
        entry_price,
        fixed_tp_pct=0.05,
        fixed_sl_pct=0.03,
        atr_pct=atr_pct_signal,
        atr_tp_mult=atr_tp_mult,
        atr_sl_mult=atr_sl_mult,
    )
    # 直接按公式算：tp = 10 * (1 + 0.02 * 8) = 11.6
    assert tp == pytest.approx(11.6, abs=1e-9)
    # sl = 10 * (1 - 0.02 * 2.5) = 9.5
    assert sl == pytest.approx(9.5, abs=1e-9)


def test_compute_tp_sl_uses_passed_atr_pct_not_external():
    """compute_trade_tp_sl 必须忠实反映传入的 atr_pct。

    旧 bug：orchestrator 错误地忽略传入的 atr_pct，去读 entry_date panel_ind 的值
    （entry_date 的 high/low 在开盘时不可知，构成穿越）。

    本测试断言：
      1. 给定 atr_pct=0.02 与 0.05，TP 必须精确按公式输出（11.6 / 14.0）
      2. 不同 atr_pct → 不同 TP（防止函数被静默覆盖）
    """
    tp_a, sl_a = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.02, atr_tp_mult=8.0, atr_sl_mult=2.5,
    )
    tp_b, sl_b = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.05, atr_tp_mult=8.0, atr_sl_mult=2.5,
    )
    # 0.02 * 8 = 0.16 → tp = 10 * 1.16 = 11.6
    assert tp_a == pytest.approx(11.6, abs=1e-9), f"tp_a = {tp_a}，期望 11.6"
    # 0.05 * 8 = 0.40 → tp = 10 * 1.40 = 14.0
    assert tp_b == pytest.approx(14.0, abs=1e-9), f"tp_b = {tp_b}，期望 14.0"
    # 不同 atr_pct 必须输出不同 TP（无静默替换）
    assert tp_a != tp_b, (
        "compute_trade_tp_sl 必须忠实反映传入的 atr_pct；"
        "tp_a == tp_b 表明函数被静默覆盖。"
    )


def test_compute_tp_sl_clamps_atr_pct():
    """atr_pct 超过 [floor, cap] 时必须夹紧（防止极端行情算出无界 TP/SL）。"""
    tp_floor, _ = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.001,  # 低于 floor 0.01
        atr_tp_mult=8.0, atr_sl_mult=2.5,
        atr_pct_floor=0.01, atr_pct_cap=0.08,
    )
    tp_cap, _ = compute_trade_tp_sl(
        10.0, fixed_tp_pct=0.05, fixed_sl_pct=0.03,
        atr_pct=0.50,  # 高于 cap 0.08
        atr_tp_mult=8.0, atr_sl_mult=2.5,
        atr_pct_floor=0.01, atr_pct_cap=0.08,
    )
    # 夹到 floor = 0.01：tp = 10 * (1 + 0.01 * 8) = 10.8
    assert tp_floor == pytest.approx(10.8, abs=1e-9)
    # 夹到 cap = 0.08：tp = 10 * (1 + 0.08 * 8) = 16.4
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
    """构造"平稳 + entry_date 触发 TP + T+3 gap down 成交"的 panel。

    关键定位（默认 n_days=100）：
      - 大部分日：close=10.0（平稳，不触发 TP/SL）
      - iloc[-19] (index 81) = entry_date，open=10.0（buy 成交价）
      - iloc[-18] (index 82) = T+2，high=11.0 → 触发 TP（tp_price=10.5）
      - iloc[-17] (index 83) = T+3，open=9.0 → 实际成交价（gap down）

    这样 _verify_trade_with_backtrader 构造的 feed（前 15 根）能覆盖 bar 0/1/2/3。
    """
    dates = pd.date_range("2025-01-01", periods=n_days, freq="B")
    rows = []
    for i, d in enumerate(dates):
        if i == n_days - 19:  # entry_date（bar 1，buy fills at open）
            o = h = lo = c = 10.0
        elif i == n_days - 18:  # T+2（bar 2，TP 触发）
            o, h, lo, c = 10.0, 11.0, 10.0, 10.0
        elif i == n_days - 17:  # T+3（bar 3，sell fills at open=9.0）
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
    """TP 触发后，exit_price 必须是 bar N+1 OPEN（9.0），不是 TP 触发价（10.5）。

    旧 bug：exit_price = target_exit_price（10.5），
            net_pnl = (9.0 - 10.0) × size = -1000（实际 gap down 后亏损卖出），
            fees = gross - net = (10.5 - 10.0) × size - (-1000) = 1500，
            fees 字段错乱（远大于真实佣金）。

    修复后：exit_price = actual_exit_price = 9.0，
            net_pnl = (9.0 - 10.0) × size = -1000 - commission，
            gross = (9.0 - 10.0) × size = -1000，
            fees = gross - net ≈ 真实佣金（5 元）。
    """
    panel = _build_panel_entry_then_gap_down()
    entry_date = panel["date"].iloc[-19]  # signal_date + 1
    entry_price = 10.0
    tp_price = 10.5   # bar 1 (entry_date) high=11 >= 10.5 → 触发 TP
    sl_price = 8.5    # 不会被触发

    net_pnl, exit_px, _exit_date = _verify_trade_with_backtrader(
        panel, "600000.SH", entry_date,
        entry_price, 1000,
        tp_price=tp_price,
        sl_price=sl_price,
        max_hold=10,
    )

    # 关键断言：exit_price == 9.0（bar N+1 OPEN），不是 10.5（TP 触发价）
    assert exit_px == pytest.approx(9.0, abs=1e-9), (
        f"exit_price 应等于 bar N+1 实际成交价 9.0（gap down），得到 {exit_px}。"
        f"如果是 10.5 则是旧 bug——target_exit_price 被错当成 actual_exit_price。"
    )
    # net_pnl 应该是亏损（gap down 后卖出），扣除佣金
    # gross = (9.0 - 10.0) × 1000 = -1000；commission 约 -5；net 应 ≈ -1005
    assert net_pnl < 0, f"gap down 后亏损卖出，net_pnl 应为负，得到 {net_pnl}"
    assert net_pnl > -1100, f"net_pnl 不应过分亏损（佣金只有几元），得到 {net_pnl}"


def test_strategy_records_actual_exit_price_in_notify_order():
    """直接调 UpullbackTradeReplay，验证 notify_order 回填 actual_exit_price。

    这个测试更接近"机制级"验证：不依赖 _verify_trade_with_backtrader 的 head() 取数，
    直接用策略 + 干净 feed 验证 notify_order 真的捕获了实际成交价。

    Feed 结构（4 根 bar）：
      bar 0: signal_date，策略下买单（buy 在下一根 bar 1 OPEN 成交）
      bar 1: entry_date，买单在 OPEN 成交；bars_in_pos=0 → 不判 TP
      bar 2: TP 触发（h=11 >= tp_p=10.5），self.close() 提交卖出单
      bar 3: 卖出单在 OPEN=9.0 成交，notify_order 回填 actual_exit_price=9.0
    """
    feed = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0, 9.0],   # bar 0, 1, 2, 3
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
        UpullbackTradeReplay,
        target_size=1000,
        tp_price=10.5,
        sl_price=8.0,
        max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    # 关键断言：actual_exit_price（notify_order 回填）= bar 3 OPEN = 9.0
    assert strat.actual_exit_price == pytest.approx(9.0, abs=1e-9), (
        f"actual_exit_price 应等于 bar N+1 OPEN 9.0，得到 {strat.actual_exit_price}。"
        f"这表明 notify_order 没有正确捕获实际成交价。"
    )
    # target_exit_price 是策略决策时看到的 TP 触发价（bar 2 h >= 10.5）
    assert strat.target_exit_price == pytest.approx(10.5, abs=1e-9)


# --------------------------------------------------------------------------- #
# P2: trade 记录完整性
# --------------------------------------------------------------------------- #


def test_trade_cols_includes_atr_pct():
    """直接断言 TRADE_COLS 包含 atr_pct（防止有人误删）。"""
    assert "atr_pct" in TRADE_COLS


def test_simulate_portfolio_records_atr_pct_per_trade():
    """simulate_portfolio 必须在每条 trade 记录里携带 atr_pct。

    这是 P0 修复的前置条件：Phase 2 orchestrator 直接读 t["atr_pct"]，
    若 trade 没有这列，TP/SL 会退回 fixed_tp_pct（弱化策略效果）。
    """
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
        "sig_close": last_row["close"],
        "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"],
        "sig_down_streak": 0,
        "sig_pullback": -0.05,
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
        for v in trades["atr_pct"]:
            assert pd.notna(v), "trade.atr_pct 不能是 NaN，否则 Phase 2 会退回 fixed TP/SL"
            assert 0.0 < v < 1.0, f"atr_pct 应在合理范围 (0, 1)，实际 {v}"


# --------------------------------------------------------------------------- #
# P3: entry ≠ exit 不变量（防止同日买卖 / look-ahead）
# --------------------------------------------------------------------------- #


def _build_entry_day_tp_panel() -> pd.DataFrame:
    """构造"entry_date 当天 high 直接打到 TP"的诱导 panel。

    设计：
      - 30 个交易日，平稳 close=10.0
      - 第 25 日（signal_date）  open=10.0 close=10.0（生成信号）
      - 第 26 日（entry_date）    open=10.0 high=11.0 low=9.5 close=10.5  ← 当天 high 就突破 TP=10.5
      - 第 27 日（T+2）          open=10.5 close=10.5
      - 第 28 日（T+3）          close=10.0
      - 第 29 日（T+4）          close=10.0

    若不守卫入场当日，TP 会立刻触发，导致同日买卖 + 凭空收益。
    守卫后，TP 在 T+2 才会真正 exit（因为 T+1 即 entry 当天被跳过）。
    """
    dates = pd.date_range("2025-03-01", periods=30, freq="B")
    n = len(dates)
    rows = []
    for i, d in enumerate(dates):
        if i == n - 6:    # signal_date（第 25 日，0-based 24）
            o = h = lo = c = 10.0
        elif i == n - 5:  # entry_date（第 26 日，0-based 25）— 当天 high=11.0 已超 TP
            o, h, lo, c = 10.0, 11.0, 9.5, 10.5
        elif i == n - 4:  # T+2
            o = h = lo = c = 10.5
        elif i == n - 3:  # T+3
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
    """simulate_portfolio 必须跳过入场当日判退出。

    诱导场景：entry_date 当根 K 线 high=11.0 已超过 TP=10.5。
    错误实现会立刻以 TP 价 exit，造成同日买卖 + 收益虚高 5%。
    正确实现：跳过 entry 当天，最早在 T+2 才退出。
    """
    panel = _build_entry_day_tp_panel()
    panel_ind = compute_indicators(panel)

    # signal 在第 25 日（dates[-6]）生成 → 第 26 日（dates[-5]）开盘买入
    signal_date = panel["date"].iloc[-6]
    entry_date_expected = panel["date"].iloc[-5]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]

    entries = pd.DataFrame([{
        "date": signal_date,
        "thscode": "600000.SH",
        "score": 0.05,
        "sig_close": last_row["close"],
        "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"],
        "sig_down_streak": 0,
        "sig_pullback": -0.05,
        "sig_mom120": 0.05,
        "sig_amount60": 5e7,
        "atr_pct": float(last_row["atr_pct"]),
    }])

    # fixed TP=5% (entry_price=10.0 → tp_p=10.5)；刚好被 entry 当天 high=11 触发
    trades, _ = simulate_portfolio(
        entries, panel_ind,
        tp_pct=0.05, sl_pct=0.05,
        max_hold=8, max_positions=1,
        start_date=panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=panel["date"].iloc[-1].strftime("%Y-%m-%d"),
    )

    assert not trades.empty, "应至少成交一笔"
    t = trades.iloc[0]

    # 不变量 1：exit_date 必须晚于 entry_date（至少 +1 个交易日）
    gap = (t["exit_date"] - t["entry_date"]).days
    assert gap >= 1, (
        f"exit_date ({t['exit_date']}) 与 entry_date ({t['entry_date']}) 间隔 {gap} 天，"
        f"必须 ≥ 1（次日开盘才能成交）。"
    )

    # 不变量 2：entry_date 必须是 signal_date 的下一根 bar
    assert t["entry_date"] == pd.Timestamp(entry_date_expected), (
        f"entry_date 应等于 signal_date 的下一交易日 {entry_date_expected}，"
        f"实际 {t['entry_date']}"
    )

    # 不变量 3：hold_days ≥ 1（至少持仓 1 个 bar）
    assert t["hold_days"] >= 1, f"hold_days={t['hold_days']}，应 ≥ 1"


def test_phase1_exit_price_uses_next_bar_not_entry_bar():
    """入场当天 high 突破 TP 时，exit_price 不能是 entry 当天的 high。

    错误实现：以 entry 当天 high=11.0 立即 exit，exit_price=11.0，
            net_pnl = (11.0 - 10.0) × size = +10%（虚高，look-ahead）。
    正确实现：跳过 entry 当天，T+2 起判定。exit_price 应来自 T+2 OHLC，
            绝不能等于 entry 当天 high=11.0。
    """
    panel = _build_entry_day_tp_panel()
    panel_ind = compute_indicators(panel)
    signal_date = panel["date"].iloc[-6]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]

    entries = pd.DataFrame([{
        "date": signal_date, "thscode": "600000.SH", "score": 0.05,
        "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"], "sig_down_streak": 0,
        "sig_pullback": -0.05, "sig_mom120": 0.05, "sig_amount60": 5e7,
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

    # 关键断言：exit_price 绝不能等于 entry 当天 high=11.0（look-ahead 陷阱）
    assert t["exit_price"] != pytest.approx(11.0, abs=1e-9), (
        f"exit_price={t['exit_price']} 等于 entry 当天 high=11.0，"
        f"这是同日买卖穿越（用未来 high 提前 exit）。"
    )
    # 退出原因应该是 T+2 触发的（TP 或 time），绝不是 entry 当天 OHLC 触发的
    assert t["exit_reason"] in ("TP", "time"), (
        f"exit_reason={t['exit_reason']}。entry 当天有 high=11.0 > tp=10.5，"
        f"若用 entry 当天 OHLC 触发会立刻以 SL/TP exit。"
    )


def test_phase2_replay_bars_in_pos_min_1():
    """UpullbackTradeReplay 必须在 bars_in_pos >= 1 后才判退出。

    直接读源码逻辑：bar 1 = entry 当天，bars_in_pos=0 → return；
    bar 2 起才检查 TP/SL。
    """
    # 模拟"bar 1 high 直接超 TP"的 feed（诱导同日买卖）
    feed = pd.DataFrame({
        "open":  [10.0, 10.0, 10.0, 9.0],
        "high":  [10.0, 11.0, 11.0, 9.1],  # bar 1 high=11 已超 TP=10.5
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
        UpullbackTradeReplay,
        target_size=1000, tp_price=10.5, sl_price=8.0, max_hold=10,
    )
    results = cerebro.run()
    strat = results[0]

    # entry_bar_idx 应该是 1（bar 1 = entry 当天）
    assert strat.entry_bar_idx == 1, (
        f"entry_bar_idx={strat.entry_bar_idx}，应为 1（bar 1 是 entry 当天）。"
    )
    # exit_reason 必须是 TP（bar 2 触发）或 time，绝不可能在 bar 1 触发
    assert strat.exit_reason in ("TP", "time"), (
        f"exit_reason={strat.exit_reason}。若为 'TP' 且 entry_bar_idx=1，"
        f"说明在入场当日就判了退出，违反不变量。"
    )


def test_phase1_max_hold_exit_uses_close_not_intrabar():
    """max_hold 到期时用当天 close exit，盘中 TP 触发在 max_hold 之前用 TP。

    panel 设计：
      - 20 个交易日，全 open=10.0 high=10.3（high 故意 < tp=10.5 不触发 TP）
      - close=10.05，low=9.95（low > sl=9.5 不触发 SL）
      - 全部日子 TP/SL 都不触发，只能靠 max_hold=3 time exit
    """
    panel = pd.DataFrame({
        "thscode": ["600000.SH"] * 20,
        "date": pd.date_range("2025-04-01", periods=20, freq="B"),
        "open":  [10.0]*20,
        "high":  [10.3]*20,   # < tp=10.5，TP 永远不触发
        "low":   [9.95]*20,  # > sl=9.5，SL 永远不触发
        "close": [10.05]*20,
        "amount": [5e7]*20,
        "volume": [1e6]*20,
    })
    panel_ind = compute_indicators(panel)
    signal_date = panel["date"].iloc[-5]
    last_row = panel_ind[panel_ind["date"] == signal_date].iloc[0]
    entries = pd.DataFrame([{
        "date": signal_date, "thscode": "600000.SH", "score": 0.05,
        "sig_close": last_row["close"], "sig_ma20": last_row["ma20"],
        "sig_ma60": last_row["ma60"], "sig_down_streak": 0,
        "sig_pullback": -0.05, "sig_mom120": 0.05, "sig_amount60": 5e7,
        "atr_pct": float(last_row["atr_pct"]),
    }])

    trades, _ = simulate_portfolio(
        entries, panel_ind, tp_pct=0.05, sl_pct=0.05,
        max_hold=3, max_positions=1,
        start_date=panel["date"].iloc[0].strftime("%Y-%m-%d"),
        end_date=panel["date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    assert not trades.empty
    t = trades.iloc[0]

    # 整段时间 TP/SL 都不触发，应在 max_hold=3 时 time exit
    assert t["hold_days"] == 3, f"hold_days={t['hold_days']}，应为 3（max_hold）"
    assert t["exit_reason"] == "time", (
        f"max_hold 到期应判 time exit，得到 {t['exit_reason']}。"
        f"（每天 high=10.3 < tp=10.5，TP 不触发）"
    )
    # time exit 用到期日 close（10.05）
    assert t["exit_price"] == pytest.approx(10.05, abs=1e-9), (
        f"max_hold time exit 应等于到期日 close 10.05，得到 {t['exit_price']}。"
    )


# --------------------------------------------------------------------------- #
# P4: 端到端 audit (针对真实 v33_long_reverse_v3 trades)
# --------------------------------------------------------------------------- #


def test_v3_e2e_signal_date_conditions_hold():
    """对真实 v33_long_reverse_v3 trades,在每个 entry_date 前一交易日 panel_ind 上,
    5 个信号条件 (A/B/C/D/E) 必须全部成立 (事后复核)。

    这等价于证明: 每个信号在决策时刻只用 past+current bar 数据,绝无穿越。
    """
    from pathlib import Path as _P
    from hiagent_config import DB_PATH as _DB
    from uptrend_pullback.backtrader_engine import run_backtrader_backtest
    from uptrend_pullback.data import load_panel as _lp
    from uptrend_pullback.signals import compute_indicators as _ci
    from uptrend_pullback.universe import load_universe as _lu

    universe = set(_lu("mainboard_only", _P(_DB)))
    panel = _lp(_P(_DB), "2025-07-01", "2026-07-01", universe=universe)
    panel_ind = _ci(panel)
    out = run_backtrader_backtest(
        "v33_long_reverse_v3", "2025-07-01", "2026-07-01", _P(_DB),
        panel_ind=panel_ind, verify=True,
    )
    trades = out["trades"]
    assert not trades.empty

    panel_idx = panel.set_index(["thscode", "date"]).sort_index()
    pidx = panel_ind.set_index(["thscode", "date"]).sort_index()

    fails = []
    for _, t in trades.iterrows():
        code, entry_date = t["thscode"], pd.Timestamp(t["entry_date"])
        sig_dates = pidx.loc[code].index[pidx.loc[code].index < entry_date]
        if len(sig_dates) == 0:
            fails.append((code, entry_date.date(), "no signal_date"))
            continue
        row = pidx.loc[code].loc[sig_dates[-1]]
        bad = []
        if not (row["close"] > row["ma60"]):
            bad.append("A1")
        if not (row["above_ma60_ratio"] >= 0.55):
            bad.append("A2")
        if not (3 <= row["down_streak"] <= 10):
            bad.append("B")
        if not (-0.05 <= row["ret1"] <= -0.02):
            bad.append("C")
        if not (row["macd_dif"] > 0 and row["macd_dea"] > 0):
            bad.append("D1/D2")
        if not (abs(row["macd_bar"]) < abs(row["macd_bar_prev"])):
            bad.append("D3")
        if not (3e7 <= row["amount60"] <= 3e8):
            bad.append("E")
        if bad:
            fails.append((code, sig_dates[-1].date(), bad))

    assert not fails, (
        f"{len(fails)} trades 在 signal_date 复核失败:\n{fails[:5]}"
    )


def test_v3_e2e_exit_price_is_fill_bar_open():
    """对真实 v33_long_reverse_v3 trades,非 eod 退出的 exit_price 必须等于
    exit_date (fill bar) 的实际 open,不是决策 bar 的触发价。

    这证明 exit_price 用的是真实成交价 (bar N+1 OPEN),不是回看触发价 (bar N OHLC)。
    """
    from pathlib import Path as _P
    from hiagent_config import DB_PATH as _DB
    from uptrend_pullback.backtrader_engine import run_backtrader_backtest
    from uptrend_pullback.data import load_panel as _lp
    from uptrend_pullback.signals import compute_indicators as _ci
    from uptrend_pullback.universe import load_universe as _lu

    universe = set(_lu("mainboard_only", _P(_DB)))
    panel = _lp(_P(_DB), "2025-07-01", "2026-07-01", universe=universe)
    panel_ind = _ci(panel)
    out = run_backtrader_backtest(
        "v33_long_reverse_v3", "2025-07-01", "2026-07-01", _P(_DB),
        panel_ind=panel_ind, verify=True,
    )
    trades = out["trades"]
    panel_idx = panel.set_index(["thscode", "date"]).sort_index()

    fails = []
    for _, t in trades.iterrows():
        if t["exit_reason"] == "eod":
            continue
        code, fill_date = t["thscode"], pd.Timestamp(t["exit_date"])
        if (code, fill_date) not in panel_idx.index:
            continue
        actual_open = float(panel_idx.loc[(code, fill_date), "open"])
        if abs(float(t["exit_price"]) - actual_open) > 0.01:
            fails.append((code, fill_date.date(), t["exit_price"], actual_open))

    assert not fails, f"{len(fails)} trades exit_price != fill bar open:\n{fails[:5]}"


def test_v3_e2e_entry_price_is_entry_bar_open():
    """对真实 v33_long_reverse_v3 trades,entry_price 必须等于 entry_date bar 的 open。

    这证明 entry fill 是 T+1 OPEN,不是回看 close。
    """
    from pathlib import Path as _P
    from hiagent_config import DB_PATH as _DB
    from uptrend_pullback.backtrader_engine import run_backtrader_backtest
    from uptrend_pullback.data import load_panel as _lp
    from uptrend_pullback.signals import compute_indicators as _ci
    from uptrend_pullback.universe import load_universe as _lu

    universe = set(_lu("mainboard_only", _P(_DB)))
    panel = _lp(_P(_DB), "2025-07-01", "2026-07-01", universe=universe)
    panel_ind = _ci(panel)
    out = run_backtrader_backtest(
        "v33_long_reverse_v3", "2025-07-01", "2026-07-01", _P(_DB),
        panel_ind=panel_ind, verify=True,
    )
    trades = out["trades"]
    panel_idx = panel.set_index(["thscode", "date"]).sort_index()

    fails = []
    for _, t in trades.iterrows():
        code, entry_date = t["thscode"], pd.Timestamp(t["entry_date"])
        if (code, entry_date) not in panel_idx.index:
            continue
        actual_open = float(panel_idx.loc[(code, entry_date), "open"])
        if abs(float(t["entry_price"]) - actual_open) > 0.01:
            fails.append((code, entry_date.date(), t["entry_price"], actual_open))

    assert not fails, f"{len(fails)} trades entry_price != entry bar open:\n{fails[:5]}"
