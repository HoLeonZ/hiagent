"""Smoke test: 验证 dna_strat 包能被导入。"""
from pathlib import Path

import duckdb
import importlib

import numpy as np
import pandas as pd
import pytest

from dna_strat.universe import load_universe
from dna_strat.signals import compute_macd, compute_panel_indicators, select_entries
from dna_strat.trades import pre_simulate_trades
from dna_strat.feed import build_synthetic_feed


def test_package_importable():
    pkg = importlib.import_module("dna_strat")
    assert hasattr(pkg, "__version__")
    assert pkg.__version__ == "0.1.0"


def test_load_universe_excludes_blacklist(tmp_path):
    # 准备一个最小 DuckDB：包含 4 只主板票 + 1 只黑名单
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE v_daily_qfq(thscode VARCHAR, date DATE, close DOUBLE)")
    rows = [
        ("600519.SH", "2024-01-02", 100.0),  # 白马主板，保留
        ("601398.SH", "2024-01-02", 5.0),    # 黑名单（工商），剔除
        ("000001.SZ", "2024-01-02", 10.0),   # 深主板，保留
        ("300033.SZ", "2024-01-02", 20.0),   # 创业板，剔除
        ("688981.SH", "2024-01-02", 30.0),   # 科创板，剔除
    ]
    con.executemany("INSERT INTO v_daily_qfq VALUES(?,?,?)", rows)
    con.close()

    exclude = tmp_path / "excl.txt"
    exclude.write_text("601398.SH\n")

    out = load_universe(db_path=db, exclude_path=exclude)
    assert out == ["000001.SZ", "600519.SH"]  # 主板保留，黑名单/创业板/科创板剔除


# ───────────────────────── MACD ──────────────────────────


def test_compute_macd_basic():
    # 30 行递增 close
    close = pd.Series(np.arange(1.0, 31.0), name="close")
    out = compute_macd(close)
    # 输出 2 列
    assert list(out.columns) == ["dif", "dea"]
    # 长周期 EMA 应小于 close（递增序列 EMA 平滑滞后）
    assert out["dif"].iloc[-1] < close.iloc[-1]
    assert out["dea"].iloc[-1] < close.iloc[-1]
    # EMA12 应大于 EMA26（递增）
    assert out["dif"].iloc[-1] > out["dea"].iloc[-1]


def test_compute_macd_constant():
    close = pd.Series([100.0] * 50)
    out = compute_macd(close)
    # 常数列上 EMA == close；DIF = EMA12 - EMA26 = 0，DEA = EMA9(0) = 0
    assert np.isclose(out["dif"].iloc[-1], 0.0, atol=1e-6)
    assert np.isclose(out["dea"].iloc[-1], 0.0, atol=1e-6)


# ───────────────── score_entries (5 条件) ─────────────────


def _build_panel():
    """
    构造一只 200 行的'理想空头反弹'票（A∧B∧C 三条件即可命中，D/E 已移除）：
    - 前 100 日大部分下跌（≥ 50 天 → 满足 A）
    - 主体下跌后 MA60 仍高、MA20 已下移、close 跌破 MA20（满足 B）
    - 末段连续 3 日上涨（满足 C）
    """
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    # 主体下行 1.00 → 0.60（前 100 日大部分下跌，后 100 日反弹）
    closes_main = np.linspace(1.00, 0.60, n)
    rng = np.random.default_rng(42)
    closes_main[:100] += rng.normal(0, 0.002, 100)  # 微抖动制造 down_days
    # 后 100 日反弹：先小涨 → 末段连续 3 日上涨
    closes_main[100:] += np.linspace(0, 0.30, 100)
    # 倒数第 3、2、1 日都上涨（+1%）
    closes_main[-3] = closes_main[-4] * 1.01
    closes_main[-2] = closes_main[-3] * 1.01
    closes_main[-1] = closes_main[-2] * 1.01
    prev_close = np.concatenate([[closes_main[0]], closes_main[:-1]])
    return pd.DataFrame({
        "thscode": "600000.SH",
        "date": dates,
        "close": closes_main,
        "prev_close": prev_close,
    })


def test_select_entries_picks_signal():
    panel = _build_panel()
    enriched = compute_panel_indicators(panel)
    entries = select_entries(enriched)
    assert not entries.empty, "A∧B∧C 全满足应当至少命中 1 个信号"
    assert entries.iloc[-1]["thscode"] == "600000.SH"
    assert entries.iloc[-1]["score"] == 0  # 无 MACD 打分，所有命中 score=0


def test_select_entries_no_signal():
    # 单调递增 100 日：down_days < 50，不命中
    n = 100
    closes = np.linspace(10, 20, n)
    prev_close = np.concatenate([[closes[0]], closes[:-1]])
    panel = pd.DataFrame({
        "thscode": "600000.SH",
        "date": pd.date_range("2025-01-01", periods=n, freq="B"),
        "close": closes, "prev_close": prev_close,
    })
    entries = select_entries(compute_panel_indicators(panel))
    assert entries.empty


# ─────────────── pre_simulate_trades (Phase 1 持仓循环) ───────────────


def test_pre_simulate_trades_tp():
    # 1 只票，entry 信号在 day 9（1-indexed = index 8, close=100），之后跌到 90 → TP
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    thscode = "600000.SH"
    closes = [100.0] * 9 + [90.0] * 6 + [80.0] * 5  # indices 0-8: 100; 9-14: 90; 15-19: 80
    panel = pd.DataFrame({"thscode": thscode, "date": dates, "close": closes})
    entries = pd.DataFrame({
        "date": [dates[8]], "thscode": [thscode], "score": [0],
    })
    trades = pre_simulate_trades(entries, panel)
    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["thscode"] == thscode
    assert row["entry_date"] == dates[8]
    assert row["entry_price"] == 100.0
    assert row["exit_reason"] == "TP"
    assert row["exit_price"] == 90.0
    assert row["hold_days"] == 1  # day 9 → day 10


def test_pre_simulate_trades_sl():
    # entry 1-indexed day 10 (= index 9, close=100)，之后涨到 106% → SL 触发
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    closes = [100.0] * 10 + [103.0, 106.0, 106.0, 106.0, 106.0] + [100.0] * 5
    panel = pd.DataFrame({"thscode": "600000.SH", "date": dates, "close": closes})
    entries = pd.DataFrame({"date": [dates[9]], "thscode": ["600000.SH"], "score": [0]})
    trades = pre_simulate_trades(entries, panel)
    row = trades.iloc[0]
    assert row["exit_reason"] == "SL"


def test_pre_simulate_trades_skip_when_holding():
    # entry 1 day 10, entry 2 day 12 (持仓中) → entry 2 被忽略
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    closes = [100.0] * 30
    panel = pd.DataFrame({"thscode": "600000.SH", "date": dates, "close": closes})
    entries = pd.DataFrame({
        "date": [dates[10], dates[12]],
        "thscode": ["600000.SH", "600000.SH"],
        "score": [0, 0],
    })
    trades = pre_simulate_trades(entries, panel)
    # 第一笔 entry day 10 退出（close=100=MA20 → TECH day 11），第二笔被忽略
    assert len(trades) == 1
    assert trades.iloc[0]["entry_date"] == dates[10]
    assert trades.iloc[0]["exit_reason"] == "TECH"


# ─────────────── build_synthetic_feed (Phase 2 backtrader feed) ───────────────


def test_build_synthetic_feed_carries_over():
    # 1 笔 trade: day 5~9 持仓 X，OHLCV 全 100
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    panel = pd.DataFrame({
        "thscode": ["600000.SH"] * 10,
        "date": dates,
        "open": [100.0] * 10,
        "high": [100.0] * 10,
        "low": [100.0] * 10,
        "close": [100.0] * 10,
        "volume": [1000.0] * 10,
    })
    trades = pd.DataFrame({
        "entry_date": [dates[5]],
        "thscode": ["600000.SH"],
        "exit_date": [dates[9]],
        "exit_reason": ["TP"],
        "entry_price": [100.0],
        "exit_price": [100.0],
        "hold_days": [4],
    })
    df = build_synthetic_feed(trades, panel)
    # 返回 DataFrame，index 是 date，列是 [open, high, low, close, volume]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    # 第 5~9 日（持仓）volume > 0
    held = df.loc[dates[5]:dates[9]]
    assert (held["volume"] > 0).all(), f"持仓日 volume 应 > 0，实际: {held['volume'].tolist()}"
    # 第 0~4 日（未持仓）volume = 0
    flat = df.loc[:dates[4]]
    assert (flat["volume"] == 0).all(), f"未持仓日 volume 应 = 0，实际: {flat['volume'].tolist()}"
    # 首日 prev_close bootstrap 自 panel 首根 close=100.0，所以 day 0 close=100.0,
    # day 1~4 (未持仓) close=100.0 继承
    assert (flat.loc[dates[1]:dates[4]]["close"] == 100.0).all()


# ─────────────── AShareBroker (A 股交易费用) ───────────────


import backtrader as bt
from dna_strat.broker import AShareBroker


def _flat_feed(n=2, price=100.0):
    df = pd.DataFrame({
        "open": [price] * n,
        "high": [price] * n,
        "low": [price] * n,
        "close": [price] * n,
        "volume": [1000.0] * n,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    return bt.feeds.PandasData(dataname=df)


def test_ashare_broker_subtracts_commission_on_buy():
    """buy 1000 股 @ 100，佣金 0.00025：cash 变化 -100025（-100000 notional -25 佣金，无印花税）"""
    cerebro = bt.Cerebro()
    cerebro.adddata(_flat_feed())
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)

    class Strat(bt.Strategy):
        def next(self):
            if not self.position:
                self.buy(data=self.datas[0], size=1000)

    cerebro.addstrategy(Strat)
    before = cerebro.broker.getcash()
    cerebro.run()
    after = cerebro.broker.getcash()
    delta = before - after  # 期望 ≈ 100025
    assert abs(delta - 100_025.0) < 1.0, f"buy 现金变化应 ~100025（成本 100000 + 佣金 25），实际 {delta:.2f}"


def test_ashare_broker_subtracts_stamp_on_sell():
    """sell 1000 股 @ 100（开空）：cash 变化 ≈ -99875（+100000 收入 -25 佣金 -100 印花税）"""
    cerebro = bt.Cerebro()
    cerebro.adddata(_flat_feed())
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)

    class Strat(bt.Strategy):
        def __init__(self):
            self.did = False
        def next(self):
            if not self.did:
                self.did = True
                self.sell(data=self.datas[0], size=1000)

    cerebro.addstrategy(Strat)
    before = cerebro.broker.getcash()
    cerebro.run()
    after = cerebro.broker.getcash()
    delta = after - before  # 期望 ≈ +99875
    assert abs(delta - 99_875.0) < 1.0, f"sell 现金变化应 ~+99875（+100000 -25 -100），实际 {delta:.2f}"


# ─────────────── TradeReplayStrategy (Phase 2 重放) ───────────────


from dna_strat.strategy import TradeReplayStrategy


def test_trade_replay_strategy_makes_trades():
    dates = pd.date_range("2025-01-01", periods=15, freq="B")
    feed = pd.DataFrame({
        "open":  [100.0]*15, "high": [100.0]*15, "low": [100.0]*15,
        "close": [100.0]*15, "volume": [1000.0]*15,
    }, index=dates)
    data = bt.feeds.PandasData(dataname=feed)

    trades = pd.DataFrame({
        "entry_date": [dates[3]],
        "thscode": ["600000.SH"],
        "exit_date": [dates[10]],
        "exit_reason": ["TP"],
        "entry_price": [100.0],
        "exit_price": [90.0],
        "hold_days": [7],
    })

    cerebro = bt.Cerebro()
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)
    cerebro.broker.set_coc(True)  # cheat_on_close: next() 时 close[0] 即当日 close
    cerebro.adddata(data)
    cerebro.addstrategy(TradeReplayStrategy, trades_df=trades)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="ta")

    res = cerebro.run()
    strat = res[0]
    ta = strat.analyzers.ta.get_analysis()
    closed = ta.total.closed
    assert closed == 1, f"应平仓 1 笔，实际 {closed}"


# ─────────────── TradeReplayStrategy 数值与边缘覆盖 ───────────────


def test_trade_replay_margin_fee_precision():
    """融券费按日扣 = |pos.size| × pos.price × margin_rate / 365（精确到 1 元）。

    场景：7 日持仓 (entry bar 3 → exit bar 10, flat price=100)，
    入场 sell 开空 (size=10,000)，出场 close 买回 (无印花税)。
    期望净 cash 变化 ≈ -3,149.32：
      - 入场 sell: +1,000,000 - 250 佣 - 1,000 印花 = +998,750
      - 持仓 7 日融券: -7 × 10,000 × 100 × 0.086/365 ≈ -1,649.3151
      - 出场 close: -1,000,000 - 250 佣 = -1,000,250
      - 净: +998,750 - 1,649.3151 - 1,000,250 = -3,149.3151 ≈ -3,149.32
    """
    dates = pd.date_range("2025-01-01", periods=15, freq="B")
    feed = pd.DataFrame({
        "open":  [100.0] * 15, "high": [100.0] * 15, "low": [100.0] * 15,
        "close": [100.0] * 15, "volume": [1000.0] * 15,
    }, index=dates)
    trades = pd.DataFrame({
        "entry_date": [dates[3]], "thscode": ["600000.SH"],
        "exit_date":  [dates[10]], "exit_reason": ["TP"],
        "entry_price": [100.0], "exit_price": [100.0], "hold_days": [7],
    })
    cerebro = bt.Cerebro()
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)
    cerebro.broker.set_coc(True)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    cerebro.addstrategy(TradeReplayStrategy, trades_df=trades)
    before = cerebro.broker.getcash()
    cerebro.run()
    after = cerebro.broker.getcash()
    delta = before - after  # 净支出（含入场 + 出场 + 融券），期望 ≈ 3,149.32
    assert abs(delta - 3_149.32) < 1.0, f"融券费数值不精确: delta={delta:.4f}（期望 ≈3,149.32）"


def test_trade_replay_skips_when_size_below_lot():
    """cash 不足以买 1 手 → size < 100 → 跳过该 entry（无成交）。

    场景：cash=9,000，price=100；int(9000/100/100)*100 = int(0.9)*100 = 0 < 100，
    ENTRY 时不触发 sell；无成交，TradeAnalyzer.total.closed == 0。
    """
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    feed = pd.DataFrame({
        "open":  [100.0] * 10, "high": [100.0] * 10, "low": [100.0] * 10,
        "close": [100.0] * 10, "volume": [1000.0] * 10,
    }, index=dates)
    trades = pd.DataFrame({
        "entry_date": [dates[3]], "thscode": ["600000.SH"],
        "exit_date":  [dates[6]], "exit_reason": ["TP"],
        "entry_price": [100.0], "exit_price": [100.0], "hold_days": [3],
    })
    cerebro = bt.Cerebro()
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(9_000)  # int(9000/100/100)*100 = 0
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)
    cerebro.broker.set_coc(True)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    cerebro.addstrategy(TradeReplayStrategy, trades_df=trades)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="ta")
    res = cerebro.run()
    ta = res[0].analyzers.ta.get_analysis()
    # 0 成交时 backtrader 仍可能 emit `total.closed == 0`；用 .get 兜底
    closed = ta.total.get("closed", 0) if hasattr(ta, "total") else 0
    assert closed == 0, f"买不起 1 手时应无成交，实际 closed={closed}"


def test_trade_replay_empty_trades_noop():
    """空 trades_df → actions 字典空 → 不报错，position 永远为 0。

    场景：trades_df = pd.DataFrame(columns=[...])（空 df，df.empty=True）。
    __init__ 中 `df is not None and not df.empty` 短路 → self.actions={}，
    next() 永远找不到 action、永远不开仓；持仓期不扣融券费（pos.size 永远 0）。
    """
    dates = pd.date_range("2025-01-01", periods=5, freq="B")
    feed = pd.DataFrame({
        "open":  [100.0] * 5, "high": [100.0] * 5, "low": [100.0] * 5,
        "close": [100.0] * 5, "volume": [1000.0] * 5,
    }, index=dates)
    empty = pd.DataFrame(columns=[
        "entry_date", "thscode", "exit_date", "exit_reason",
        "entry_price", "exit_price", "hold_days",
    ])
    cerebro = bt.Cerebro()
    cerebro.broker = AShareBroker()
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.00025, stocklike=True)
    cerebro.broker.set_coc(True)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed))
    cerebro.addstrategy(TradeReplayStrategy, trades_df=empty)
    res = cerebro.run()  # 不抛
    strat = res[0]
    assert strat.getposition().size == 0, "空 trades 时应保持 0 持仓"


def test_trade_replay_margin_rate_injectable():
    """margin_rate 参数可注入：0.20 vs 默认 0.086 的差额按比例体现在 cash 上。

    场景：3 日持仓，size=10,000（int(1,000,000/100/100)*100），price=100。
      - 高费率 0.20: 3 × 10,000 × 100 × 0.20 / 365 ≈ 1,643.8356
      - 默认费率 0.086: 3 × 10,000 × 100 × 0.086 / 365 ≈ 706.8493
      - 差: ≈ 936.9863（cash 上 delta_hi - delta_lo ≈ 936.99）
    入场/出场净 cash 相同，差异完全由融券费率注入产生。
    """
    dates = pd.date_range("2025-01-01", periods=8, freq="B")
    feed = pd.DataFrame({
        "open":  [100.0] * 8, "high": [100.0] * 8, "low": [100.0] * 8,
        "close": [100.0] * 8, "volume": [1000.0] * 8,
    }, index=dates)
    trades = pd.DataFrame({
        "entry_date": [dates[2]], "thscode": ["600000.SH"],
        "exit_date":  [dates[5]], "exit_reason": ["TP"],
        "entry_price": [100.0], "exit_price": [100.0], "hold_days": [3],
    })

    def run_with_rate(rate):
        c = bt.Cerebro()
        c.broker = AShareBroker()
        c.broker.setcash(1_000_000)
        c.broker.setcommission(commission=0.00025, stocklike=True)
        c.broker.set_coc(True)
        c.adddata(bt.feeds.PandasData(dataname=feed.copy()))
        c.addstrategy(TradeReplayStrategy, trades_df=trades, margin_rate=rate)
        before = c.broker.getcash()
        c.run()
        return before - c.broker.getcash()  # 净支出（含入场 + 出场 + 融券）

    delta_hi = run_with_rate(0.20)   # 融券更贵
    delta_lo = run_with_rate(0.086)  # 默认
    # 3 日 × 10,000 × 100 × (0.20-0.086) / 365 ≈ 936.99
    diff = delta_hi - delta_lo
    assert abs(diff - 936.99) < 5.0, f"margin_rate 注入差异常: diff={diff:.4f}（期望 ≈936.99）"


# ─────────────── 边缘 case 补充 ───────────────


def test_pre_simulate_trades_eod():
    """entry 在 panel 倒数第 2 根 → 后 1 根 EOD 退出 (no TP/SL/TECH hit)."""
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    closes = [100.0] * 10
    panel = pd.DataFrame({"thscode": "600000.SH", "date": dates, "close": closes})
    entries = pd.DataFrame({"date": [dates[8]], "thscode": ["600000.SH"], "score": [0]})
    trades = pre_simulate_trades(entries, panel)
    assert len(trades) == 1
    row = trades.iloc[0]
    assert row["entry_date"] == dates[8]
    assert row["exit_date"] == dates[9]
    assert row["exit_reason"] == "EOD"


def test_load_universe_no_blacklist_file(tmp_path):
    """黑名单文件不存在 → 返回所有主板 (无剔除)."""
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE v_daily_qfq(thscode VARCHAR, date DATE, close DOUBLE)")
    rows = [
        ("600519.SH", "2024-01-02", 100.0),
        ("000001.SZ", "2024-01-02", 10.0),
        ("300033.SZ", "2024-01-02", 20.0),
        ("688981.SH", "2024-01-02", 30.0),
    ]
    con.executemany("INSERT INTO v_daily_qfq VALUES(?,?,?)", rows)
    con.close()

    nonexistent = tmp_path / "no_such_file.txt"
    out = load_universe(db_path=db, exclude_path=nonexistent)
    assert "600519.SH" in out
    assert "000001.SZ" in out
    assert "300033.SZ" not in out
    assert "688981.SH" not in out


def test_select_entries_handles_nan_panel():
    """停牌票 close=NaN → 不进 signal."""
    panel = pd.DataFrame({
        "thscode": ["600000.SH"] * 5,
        "date": pd.date_range("2025-01-01", periods=5, freq="B"),
        "close": [10.0, float("nan"), 12.0, 13.0, 14.0],
        "prev_close": [10.0, 10.0, float("nan"), 12.0, 13.0],
    })
    enriched = compute_panel_indicators(panel)
    entries = select_entries(enriched)
    assert entries.empty, "NaN close 票不应命中信号"
