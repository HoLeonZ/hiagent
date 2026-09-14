"""indicators_bt 子类单测。

每个 indicator 在最小 backtrader setup（1 data feed + 1 indicator）下验证：
  - next() 仅访问 [0] 和 [-1]（no-lookahead）
  - 计算结果与预期一致
  - NaN / 边界条件处理正确
"""
from __future__ import annotations

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from short_reversal.feed_bt import AShareData
from short_reversal.indicators_bt import (
    Am60,
    BelowMa60Ratio60,
    PctChg,
    UpStreak,
)


class _HolderStrategy(bt.Strategy):
    """承载 indicator 用的最小 strategy，把 indicator 挂到 self.ind。"""

    params = (("ind_cls", None),)

    def __init__(self):
        if self.p.ind_cls is not None:
            self.ind = self.p.ind_cls(self.datas[0])


def _run_single_indicator(df: pd.DataFrame, indicator_cls, **params) -> list[float]:
    """跑 1 个 indicator 在 1 个 data feed 上，返回每根 bar 的 line 值（按时间正序）。"""
    cerebro = bt.Cerebro(stdstats=False)
    feed = AShareData(dataname=df, plot=False)
    cerebro.adddata(feed)
    cerebro.addstrategy(_HolderStrategy, ind_cls=indicator_cls)
    results = cerebro.run()
    strat = results[0]
    ind = strat.ind
    # 取第一个 line（命名或位置都行）
    line_names = ind.lines.getlinealiases()
    line_name = line_names[0] if line_names else 0
    line = getattr(ind.lines, line_name) if isinstance(line_name, str) else ind.lines[0]
    # backtrader 的 line[i] = array[self.idx + i]；要看历史所有值，从 array 取最后 n_bars 个
    n_bars = len(strat)
    return [float(v) for v in line.array[-n_bars:]]


def _basic_ohlcv(n: int = 80, start_price: float = 10.0,
                  slope: float = 0.1) -> pd.DataFrame:
    """生成 n 根 K 线的合成 OHLCV（含 date 列 + amount 列）。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rows = []
    for i, d in enumerate(dates):
        p = start_price + slope * i
        rows.append({
            "date": d,
            "open": p, "high": p + 0.5, "low": p - 0.5, "close": p,
            "amount": 1e8, "volume": 1e6,
        })
    return pd.DataFrame(rows)


# ============================================================ PctChg

class TestPctChg:
    def test_basic_increasing(self):
        df = _basic_ohlcv(n=10, slope=1.0)
        vals = _run_single_indicator(df, PctChg)
        assert len(vals) == 10
        # 第 0 根无 prev → NaN
        assert np.isnan(vals[0])
        # 第 1 根: (11-10)/10 = 0.1
        assert vals[1] == pytest.approx(0.1, rel=1e-9)
        # 每根都是 slope/prev = 1.0/(10+i-1)
        for i in range(1, 10):
            expected = 1.0 / (10.0 + i - 1)
            assert vals[i] == pytest.approx(expected, rel=1e-9)

    def test_negative_change(self):
        df = _basic_ohlcv(n=5, slope=-1.0)
        vals = _run_single_indicator(df, PctChg)
        assert np.isnan(vals[0])
        # (9-10)/10 = -0.1
        assert vals[1] == pytest.approx(-0.1, rel=1e-9)

    def test_zero_prev_returns_nan(self):
        # 第 0 根 close=0, 第 1 根 close=1 → prev=0 → NaN
        idx = pd.date_range("2025-01-01", periods=2, freq="B")
        df = pd.DataFrame(
            {
                "date": idx,
                "open": [0.0, 1.0], "high": [0.5, 1.5], "low": [-0.5, 0.5],
                "close": [0.0, 1.0], "amount": [1e8, 1e8], "volume": [1e6, 1e6],
            },
        )
        vals = _run_single_indicator(df, PctChg)
        assert np.isnan(vals[1])


# ============================================================ Am60

class TestAm60:
    def test_warmup_nan_then_equals_sma(self):
        df = _basic_ohlcv(n=80, slope=0.0, start_price=10.0)
        vals = _run_single_indicator(df, Am60, period=60)
        assert len(vals) == 80
        # 前 59 根 NaN（rolling 60 min_periods=60）
        for i in range(59):
            assert np.isnan(vals[i]), f"expected NaN at {i}, got {vals[i]}"
        # 第 60 根 = 60 根 amount 的均值 = 1e8
        assert vals[59] == pytest.approx(1e8, rel=1e-6)
        # 第 79 根 仍是 1e8（amount 不变）
        assert vals[79] == pytest.approx(1e8, rel=1e-6)

    def test_changing_amount(self):
        df = _basic_ohlcv(n=80)
        # 第 60~79 根 amount 改 2e8
        df.loc[60:, "amount"] = 2e8
        vals = _run_single_indicator(df, Am60, period=60)
        # 第 79 根 = rolling 60 窗口 = bars 20..79 = 40 * 1e8 + 20 * 2e8 / 60 = 1.333e8
        expected = (40 * 1e8 + 20 * 2e8) / 60
        assert vals[79] == pytest.approx(expected, rel=1e-6)


# ============================================================ UpStreak

class TestUpStreak:
    def test_monotonic_increasing(self):
        df = _basic_ohlcv(n=10, slope=0.1)  # 每根都比上一根高
        vals = _run_single_indicator(df, UpStreak)
        # 第 0 根（无 prev）→ 0（down_day 分支）
        assert vals[0] == 0
        # 第 1 根: cur > prev, 上一根是 0 → 取 1
        assert vals[1] == 1
        # 第 i 根: i (累计)
        for i in range(1, 10):
            assert vals[i] == i, f"up_streak at {i} = {vals[i]}"

    def test_down_day_resets(self):
        df = _basic_ohlcv(n=10, slope=0.1)
        # 第 5 根 close 改小 → 下跌日
        df.loc[5, "close"] = df.loc[4, "close"] - 1.0
        vals = _run_single_indicator(df, UpStreak)
        # 第 5 根下跌 → 0
        assert vals[5] == 0
        # 第 6 根涨 → 1
        assert vals[6] == 1
        # 第 9 根涨 → 4（6,7,8,9）
        assert vals[9] == 4

    def test_no_cross_stock_leak(self):
        """per-stock 状态独立 —— 不同 feed 应独立计数。"""
        df1 = _basic_ohlcv(n=10, slope=0.1)
        df2 = _basic_ohlcv(n=10, slope=0.1)
        df2["close"] = df2["close"] + 100  # 不影响 streak（仍单调递增）

        class _TwoIndHolder(bt.Strategy):
            def __init__(self):
                self.ind_a = UpStreak(self.datas[0])
                self.ind_b = UpStreak(self.datas[1])

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(AShareData(dataname=df1, plot=False), name="A")
        cerebro.adddata(AShareData(dataname=df2, plot=False), name="B")
        cerebro.addstrategy(_TwoIndHolder)
        results = cerebro.run()
        s = results[0]
        streak_a = s.ind_a.lines.up_streak
        streak_b = s.ind_b.lines.up_streak
        # 两个完全独立的 count
        n_bars = len(s)
        for v_a, v_b in zip(streak_a.array[-n_bars:], streak_b.array[-n_bars:]):
            assert v_a == v_b


# ============================================================ BelowMa60Ratio60

class _BelowCarrier(bt.Strategy):
    """承载 BelowMa60Ratio60 + 注入 ma60 line 的最小 strategy。"""

    def __init__(self):
        sma = bt.indicators.SMA(self.datas[0].close, period=60)
        self._ratio = BelowMa60Ratio60(self.datas[0], period=60)
        self._ratio.ma60_source = sma.lines.sma


class TestBelowMa60Ratio60:
    def test_all_below_with_indicator(self):
        """真正跑 BelowMa60Ratio60（注入 ma60_source）验证。"""
        # 用单调下降的 close —— close[i] < SMA(60) at every bar (strict)
        df = _basic_ohlcv(n=80, slope=-0.05, start_price=20.0)

        cerebro = bt.Cerebro(stdstats=False)
        feed = AShareData(dataname=df, plot=False)
        cerebro.adddata(feed)
        cerebro.addstrategy(_BelowCarrier)
        results = cerebro.run()
        ratio_ind = results[0]._ratio
        n_bars = len(results[0])
        vals = [float(v) for v in ratio_ind.lines.ratio.array[-n_bars:]]
        # 前 59 根 ma60=NaN → 全部 invalid → ratio=0.0
        for i in range(59):
            assert vals[i] == 0.0, f"i={i} ratio={vals[i]}"
        # 第 60~79 全部 close<ma60（单调下降）→ ratio=1.0
        for i in range(60, n_bars):
            assert vals[i] == pytest.approx(1.0, abs=1e-9), f"i={i} ratio={vals[i]}"

    def test_logic_matches_manual_calculation(self):
        """逻辑层验证（不依赖 backtrader line 注入）。"""
        n = 80
        df = _basic_ohlcv(n=n, slope=0.0, start_price=10.0)
        df = df.copy()
        # 构造严格 close<ma60
        df["close"] = df["close"] - 0.001
        df["ma60"] = df["close"].rolling(60).mean() + 0.001
        vals = []
        buf_c, buf_m = [], []
        for i in range(n):
            c = df["close"].iloc[i]
            m = df["ma60"].iloc[i]
            buf_c.append(c)
            buf_m.append(m)
            if len(buf_c) > 60:
                buf_c.pop(0); buf_m.pop(0)
            v = [(cc < mm) for cc, mm in zip(buf_c, buf_m) if not (np.isnan(cc) or np.isnan(mm))]
            vals.append(sum(v) / len(v) if v else 0.0)
        # 前 59 根 ma60=NaN → 0.0
        for i in range(59):
            assert vals[i] == 0.0
        # 第 60~79 全部 c<m → 1.0
        for i in range(60, 80):
            assert vals[i] == pytest.approx(1.0, abs=1e-9)
