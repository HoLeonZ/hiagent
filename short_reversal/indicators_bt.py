"""自定义 backtrader Indicator 子类。

每个 Indicator 的 `next()` / `__init__()` 仅访问 `[0]`（当前 bar）和 `[-1]`（上一 bar），
不使用 `[-2]` 之后的未来或远期数据 —— 满足事件驱动 no-lookahead 约束。

backtrader 源码（pip 装的 1.9.78.123）保持原封不动。
"""
from __future__ import annotations

import backtrader as bt
import numpy as np


class PctChg(bt.Indicator):
    """单日涨跌幅：(close[0] - close[-1]) / close[-1]。"""

    lines = ("pct_chg",)

    def next(self):
        # backtrader 的 data 在 __init__ 时已 preload，bar=0 时 close[-1] 不为 NaN
        # 用 len(self) 判定"第 1 根 bar" → 输出 NaN
        if len(self) == 1:
            self.lines.pct_chg[0] = float("nan")
            return
        prev = float(self.data.close[-1])
        cur = float(self.data.close[0])
        if np.isnan(prev) or prev == 0 or np.isnan(cur):
            self.lines.pct_chg[0] = float("nan")
        else:
            self.lines.pct_chg[0] = (cur - prev) / prev


class Am60(bt.Indicator):
    """成交额 N 日 SMA（rolling mean）。需要 AShareData 含 amount line。

    直接在 next() 内累加 buffer 计算 —— 不嵌套 SMA 子 indicator，
    避免 lines alias 绑定的副作用。
    """

    lines = ("am60",)
    params = (("period", 60),)

    def __init__(self):
        self._buf: list[float] = []

    def next(self):
        a = self.data.amount[0]
        if np.isnan(a):
            self.lines.am60[0] = float("nan")
            return
        self._buf.append(float(a))
        if len(self._buf) > self.p.period:
            self._buf.pop(0)
        if len(self._buf) < self.p.period:
            self.lines.am60[0] = float("nan")
        else:
            self.lines.am60[0] = sum(self._buf) / len(self._buf)


class UpStreak(bt.Indicator):
    """per-stock 连续上涨天数计数器。down_day 或 NaN 重置为 0。"""

    lines = ("up_streak",)

    def next(self):
        # 第 1 根 bar → 无 prev → 0
        if len(self) == 1:
            self.lines.up_streak[0] = 0
            return
        prev_close = float(self.data.close[-1])
        cur_close = float(self.data.close[0])
        if np.isnan(prev_close) or np.isnan(cur_close):
            self.lines.up_streak[0] = 0
        elif cur_close > prev_close:
            # 上一根就是上行则 +1，否则从 1 开始（今天上涨自身算 1）
            prev_streak = float(self.lines.up_streak[-1])
            self.lines.up_streak[0] = (prev_streak + 1) if not np.isnan(prev_streak) else 1
        else:
            self.lines.up_streak[0] = 0


class BelowMa60Ratio60(bt.Indicator):
    """过去 N 日 close<ma60 的比例（V1 A 条件用）。

    使用方法（实例属性注入 ma60 line）：
        ma60 = bt.indicators.SMA(d.close, period=60)
        ratio_ind = BelowMa60Ratio60(d, period=60)
        ratio_ind.ma60_source = ma60.lines.sma   # ← 在 strategy __init__ 设置
    next() 通过 self.ma60_source.array[len(self.data)-1] 取当前 ma60 值
    （绕开 LineBuffer 的 idx 在 warmup 期间停在 -1 的坑）。
    """

    lines = ("ratio",)
    params = (("period", 60),)

    def __init__(self):
        self._buf_close: list[float] = []
        self._buf_ma60: list[float] = []
        self.ma60_source = None  # 由调用方在 __init__ 后赋值

    def next(self):
        c = float(self.data.close[0])
        m = float("nan")
        if self.ma60_source is not None:
            # 用 data feed 的 bar idx 直接读 array —— LineBuffer.idx 在
            # 母 indicator（SMA）warmup 期间停在 -1，[0] 会读到 array[-1]（末值）
            bar_idx = len(self.data) - 1
            try:
                m = float(self.ma60_source.array[bar_idx])
            except (IndexError, TypeError):
                m = float("nan")
        self._buf_close.append(c if not np.isnan(c) else float("nan"))
        self._buf_ma60.append(m if not np.isnan(m) else float("nan"))
        if len(self._buf_close) > self.p.period:
            self._buf_close.pop(0)
            self._buf_ma60.pop(0)
        valid = [
            (cc < mm)
            for cc, mm in zip(self._buf_close, self._buf_ma60)
            if not (np.isnan(cc) or np.isnan(mm))
        ]
        self.lines.ratio[0] = (sum(valid) / len(valid)) if valid else 0.0


class AtrAdj(bt.Indicator):
    """ATR(period) on adj_close domain for slippage estimation (V5').

    Returns True Range averaged over `period` bars. Uses True Range =
    max(high-low, |high-prev_close|, |low-prev_close|) — standard ATR
    definition. On period-1 first bar, prev_close is NaN → return NaN.

    The `adj_close` semantic mirrors `chase_up` V3a dual-price: signal
    indicators operate on the FORWARD-ADJUSTED price domain (mathematical
    cleanliness), while execution broker uses the raw price domain.
    """

    lines = ("atr",)
    params = (("period", 14),)

    def __init__(self):
        self._tr_buf: list[float] = []

    def next(self):
        if len(self) == 1:
            self.lines.atr[0] = float("nan")
            return
        h = float(self.data.high[0])
        lo = float(self.data.low[0])
        prev_close = float(self.data.close[-1])
        if any(np.isnan(v) for v in (h, lo, prev_close)):
            self._tr_buf.append(float("nan"))
        else:
            tr = max(h - lo, abs(h - prev_close), abs(lo - prev_close))
            self._tr_buf.append(tr)
        if len(self._tr_buf) > self.p.period:
            self._tr_buf.pop(0)
        valid = [v for v in self._tr_buf if not np.isnan(v)]
        if len(valid) < self.p.period:
            self.lines.atr[0] = float("nan")
        else:
            self.lines.atr[0] = sum(valid) / len(valid)
