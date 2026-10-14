"""自定义 backtrader Indicator 子类。

每个 Indicator 的 `next()` / `__init__()` 仅访问 `[0]`（当前 bar）和 `[-1]`（上一 bar），
不使用 `[-2]` 之后的未来或远期数据 —— 满足事件驱动 no-lookahead 约束。

backtrader 源码（pip 装的 1.9.78.123）保持原封不动。
"""
from __future__ import annotations

import backtrader as bt
import numpy as np


class PctChg(bt.Indicator):
    """单日涨跌幅：(close[0] - close[-1]) / close[-1]。

    v81 (2026-10-14, CLAUDE.md §3): price_source 注入。信号域 MUST use adj_close,
    否则除权日跳空被误判为「下跌日」。默认 (None) 沿用 data.close (raw, 兼容)。
    """

    lines = ("pct_chg",)

    def __init__(self):
        self.price_source = None  # 由 strategy __init__ 注入 adj_close line

    def next(self):
        src = self.price_source if self.price_source is not None else self.data
        # backtrader 的 data 在 __init__ 时已 preload，bar=0 时 close[-1] 不为 NaN
        # 用 len(self) 判定"第 1 根 bar" → 输出 NaN
        if len(self) == 1:
            self.lines.pct_chg[0] = float("nan")
            return
        prev = float(src[-1])
        cur = float(src[0])
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
    """per-stock 连续上涨天数计数器。down_day 或 NaN 重置为 0。

    v81 (2026-10-14, CLAUDE.md §3): price_source 注入 (同 PctChg)。默认 raw 兼容。
    """

    lines = ("up_streak",)

    def __init__(self):
        self.price_source = None  # 由 strategy __init__ 注入 adj_close line

    def next(self):
        src = self.price_source if self.price_source is not None else self.data
        # 第 1 根 bar → 无 prev → 0
        if len(self) == 1:
            self.lines.up_streak[0] = 0
            return
        prev_close = float(src[-1])
        cur_close = float(src[0])
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
        self.price_source = None  # v81 (§3): 注入 adj_close line; 默认 raw 兼容

    def next(self):
        # v81 (2026-10-14, CLAUDE.md §3): close 侧也走 price_source, 与 ma60
        # (adj_close 域) 同域 —— 否则 raw close vs adj ma60 错配, ratio 恒 ~1.0。
        csrc = self.price_source if self.price_source is not None else self.data
        c = float(csrc[0])
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


class AmountRatio(bt.Indicator):
    """成交金额 5d/20d 比率。纯 causal, 无 banned functions。

    v52 (2026-10-12, 用户提示"探索新方向"):
    测「资金流衰减」, 不测绝对跌幅。
    H 条件: 5d_avg < 20d_avg × 0.7 = 近期成交显著萎缩
    → 「无成交下跌」(selling exhaustion) = 卖压枯竭
    → 后续「死猫跳」对 short_reversal 最有利 (空头押注反弹失败)。

    使用 amount 域 (元), 不是 volume (股), 因为金额 = 实际资金流,
    不受拆股/分红等 corporate actions 干扰 (V3a dual-price spirit)。
    """

    lines = ("ratio",)
    params = (
        ("short_period", 5),
        ("long_period", 20),
    )

    def __init__(self):
        self._buf: list[float] = []

    def next(self):
        a = self.data.amount[0]
        if np.isnan(a):
            self.lines.ratio[0] = float("nan")
            return
        self._buf.append(float(a))
        if len(self._buf) > self.p.long_period:
            self._buf.pop(0)
        if len(self._buf) < self.p.long_period:
            self.lines.ratio[0] = float("nan")
        else:
            short_avg = sum(self._buf[-self.p.short_period:]) / self.p.short_period
            long_avg = sum(self._buf) / self.p.long_period
            if long_avg <= 0:
                self.lines.ratio[0] = float("nan")
            else:
                self.lines.ratio[0] = short_avg / long_avg


class ReturnN(bt.Indicator):
    """N 日累计回报: (price[0] - price[-N]) / price[-N]。纯 causal, 无 banned functions。

    v51 (2026-10-12, 用户提示"弱势股"维度):
    short_reversal 哲学 = 「在持续下跌的弱势股中, 捕捉短期超涨反转」。
    F 条件 (v50 MA20 slope) 测「短期动量」, 但无法回答「过去 N 个月跌了多少」。
    G 条件 (本指标) 直接度量「弱势水平」: 1M 累计跌幅 ≥ 5%、3M ≥ 10%、6M ≥ 15%。
    数学上等价于 cumret/N 日起点 → 0, 但实现上不调用 cumsum (无未来函数)。

    `price_source` 由 strategy __init__ 注入 adj_close line, 保持 v3a dual-price:
    信号/指标 MUST use adj_close (V3a); execution 仍走 raw_close。
    """

    lines = ("ret",)
    params = (("period", 21),)  # 默认 1M (21 trading days)

    def __init__(self):
        self.price_source = None  # 由调用方在 strategy __init__ 后赋值

    def next(self):
        src = self.price_source if self.price_source is not None else self.data
        if len(self) <= self.p.period:
            # 需要 period+1 根 bar 才能算 period 日前的 close
            self.lines.ret[0] = float("nan")
            return
        cur = float(src[0])
        past = float(src[-self.p.period])
        if np.isnan(cur) or np.isnan(past) or past == 0:
            self.lines.ret[0] = float("nan")
        else:
            self.lines.ret[0] = (cur - past) / past


class Ma20SlopeN(bt.Indicator):
    """MA20 (or any injected line) over last N bars 的线性回归斜率。

    v50 系列 (2026-10-12, 用户提示"下降趋势的斜率"维度):
    short_reversal 5 条件 (A/B/C/D/E) 全部是「区间/布尔」判断,
    无显式「趋势斜率」度量。MA20 在 5 日窗口上若 slope > 0,
    说明短期 MA 在上升 → 标的可能处于反弹中段而非下降趋势,
    与 short_reversal "捕捉下降趋势中的超涨反转" 哲学不符,
    应作为入场过滤器排除。

    计算方式: 取最近 N 个 ma20 值, numpy polyfit deg=1 算斜率 (per day)。
    单位: (price / day) — 9 元/天斜率 ≈ 显著下跌; 0 表示横盘。
    NaN 兼容: 任一窗口内含 NaN → 输出 NaN → 条件自然 fail。
    """

    lines = ("slope",)
    params = (("period", 5),)

    def __init__(self):
        self._buf: list[float] = []
        self.ma_source = None  # 由调用方在 strategy __init__ 后赋值

    def next(self):
        m = float("nan")
        if self.ma_source is not None:
            bar_idx = len(self.data) - 1
            try:
                m = float(self.ma_source.array[bar_idx])
            except (IndexError, TypeError):
                m = float("nan")
        self._buf.append(m if not np.isnan(m) else float("nan"))
        if len(self._buf) > self.p.period:
            self._buf.pop(0)
        valid = [v for v in self._buf if not np.isnan(v)]
        if len(valid) < self.p.period:
            self.lines.slope[0] = float("nan")
            return
        # x 用 0..period-1 等距, y 是 valid 中的 ma20 值
        y = np.array(valid, dtype=float)
        x = np.arange(len(y), dtype=float)
        # numpy.polyfit 在 N=5 时数值稳定, 无未来函数 (只用 [0] 当期 + 过去)
        coef = np.polyfit(x, y, 1)
        self.lines.slope[0] = float(coef[0])
