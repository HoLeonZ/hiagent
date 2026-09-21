"""事件驱动 no-lookahead backtrader 策略（v3）。

Phase3V3Strategy：
  - next() 每根 bar 评估 5 条件（A/B/C/D/E），不再离线预生成 trades_df
  - 信号在 T 日 close 触发 → T+1 日 open 成交（cheat-on-open 模式）
  - TP/SL 在 next() 用 self.data.high[0]/low[0] 实时判断
  - 持仓/成本 self-maintain（不依赖 broker 撮合）
  - 所有判断只用 self.data.X[0] 和 [-1] —— 无未来引用

backtrader 源码（pip 装的 1.9.78.123）保持原封不动，只走子类化扩展。
"""
from __future__ import annotations

import logging
import backtrader as bt
import numpy as np

logger = logging.getLogger(__name__)

from short_reversal.indicators_bt import (
    Am60,
    BelowMa60Ratio60,
    PctChg,
    UpStreak,
)

# 流动性窗口：am60 ∈ [3e7, 3e8]
LIQ_LOW = 3e7
LIQ_HIGH = 3e8

# B 条件：连阳天数范围
UP_STREAK_LOW = 3
UP_STREAK_HIGH = 10


class Phase3V3Strategy(bt.Strategy):
    """事件驱动做空策略。"""

    params = dict(
        tp_pct=0.06,
        sl_pct=0.0005,
        max_hold=5,
        position_fraction=1.0,
        pct_chg_low=0.02,
        pct_chg_high=0.07,
        a_condition="default",  # 'default' (V1) | 'cascade_price' (V5)
        # B 条件: 连阳天数范围 (默认 [3, 10], 模块常量 UP_STREAK_LOW/HIGH)
        up_streak_low=3,
        up_streak_high=10,
        # E 条件: am60 流动性窗口 (默认 [3e7, 3e8], 模块常量 LIQ_LOW/HIGH)
        liq_low=3e7,
        liq_high=3e8,
        # A 条件: default 模式下 close<MA60 + below_ratio_60 阈值
        below_ratio_60=0.6,           # v3 默认 0.6
        close_ma60_buffer=0.0,        # 允许 close > ma60 的 buffer (默认 0, 即严格 close < ma60)
        # D 条件 MACD 阈值 (默认严格: DIF<0 & DEA<0 & |bar|<|prev_bar|)
        # 'strict' (V3 默认) | 'd_only' (D|dif|<0 only) | 'converge_strict' (|bar|<|prev_bar|*0.5)
        d_mode="strict",
        margin_rate=0.086,
        commission_rate=0.0006,
        stamp_duty_rate=0.001,
        initial_capital=1_000_000.0,
        lot_size=100,
        min_cash_ratio=0.05,
        result_holder=None,
    )

    def __init__(self):
        # per-data 指标字典（避免多 data 共享 indicator）
        self.indi: dict[str, dict] = {}
        # 关键：只迭代 data feed，不迭代后续 __init__ 期间被加进来的 indicator
        # backtrader 的 Lines_LineSeries __slots__ 不允许任意属性注入
        for d in self.datas:
            name = getattr(d, "_name", None)
            if not name:
                # indicator 没有 _name（或 _name 为 None/空），跳过
                continue
            ma5 = bt.indicators.SMA(d.close, period=5)
            ma10 = bt.indicators.SMA(d.close, period=10)
            ma20 = bt.indicators.SMA(d.close, period=20)
            ma60 = bt.indicators.SMA(d.close, period=60)
            below_ratio = BelowMa60Ratio60(d, period=60)
            below_ratio.ma60_source = ma60.lines.sma  # ← 注入 ma60 line
            self.indi[name] = {
                "ma5": ma5,
                "ma10": ma10,
                "ma20": ma20,
                "ma60": ma60,
                "macd": bt.indicators.MACD(d.close),
                "pct_chg": PctChg(d),
                "am60": Am60(d, period=60),
                "up_streak": UpStreak(d),
                "below_ma60_ratio_60": below_ratio,
            }

        # 持仓/账户状态
        self.cash = self.p.initial_capital
        # code -> {'entry_price', 'size', 'entry_bar'}
        self._holds: dict[str, dict] = {}
        # code -> True（T+1 待成交）
        self.pending_entries: dict[str, bool] = {}
        # 已成交 trades
        self.trades: list[dict] = []
        # 风险指标
        self.peak = self.p.initial_capital
        self.max_dd = 0.0

    # ------------------------------------------------------------------ next

    def next(self):
        # 1) 给所有持仓扣今天的融券日费
        self._charge_margin_fees()

        # 2) 把 T 日 queue 的 pending entries 在今天的 open 成交
        self._fill_pending_entries()

        # 3) 遍历所有 data：持仓检查出场；空仓且不在 pending 中则评估入场
        for d in self.datas:
            code = d._name
            if code in self._holds:
                self._check_exit(d)
            elif code not in self.pending_entries:
                if self._all_conditions(d):
                    self.pending_entries[code] = True

        # 4) 更新回撤（NAV-based：cash + 持仓 mark-to-market 浮盈）
        nav = self._nav()
        self.peak = max(self.peak, nav)
        dd = (self.peak - nav) / self.peak if self.peak > 0 else 0.0
        self.max_dd = max(self.max_dd, dd)

    def _nav(self) -> float:
        """账户净值：cash + 所有做空持仓按当前 close 的 mark-to-market 浮盈。

        做空仓浮盈 = (entry_price - current_close) × size
        """
        nav = self.cash
        for code, pos in self._holds.items():
            d = self.getdatabyname(code)
            current_close = float(d.close[0])
            nav += (pos["entry_price"] - current_close) * pos["size"]
        return nav

    # ------------------------------------------------------------- entry/exit

    def _fill_pending_entries(self) -> None:
        """T+1 日 open 成交。

        NAV-based 记账：cash 表示账户净值（自有 + 持仓浮盈）。
        做空不把 sale proceeds 加到 cash —— 而是把持仓 P&L 在 _close() 加到 cash。
        这里只扣 entry fee。

        Cash gate (2026-09-21): NAV 跌到初始资金 × MIN_CASH_RATIO 以下时拒绝新开仓,
        已持仓仍允许正常 SL/TP/time exit。这是防止 cash → 0 触底破产的 P6 守卫。
        """
        if not self.pending_entries:
            return
        # NAV-based cash gate: 用 cash + 当前持仓 mark-to-market 浮盈 估算真实净值
        nav = self._nav()
        cash_gate_threshold = self.p.initial_capital * self.p.min_cash_ratio
        if nav < cash_gate_threshold:
            if not getattr(self, "_cash_gate_logged", False):
                logger.warning(
                    "[cash-gate] NAV=%.2f < threshold=%.2f, 拒绝 %d 个 pending entries",
                    nav, cash_gate_threshold, len(self.pending_entries),
                )
                self._cash_gate_logged = True
            # 拒绝所有 pending entries (保留在 pending 让下一根 bar 重新评估)
            self.pending_entries.clear()
            return
        for d in self.datas:
            code = d._name
            if code not in self.pending_entries:
                continue
            entry_price = float(d.open[0])
            # 防穿仓 (R4, 2026-09-21): budget base 用 NAV (cash + 持仓浮盈) 而非
            # 仅 self.cash。前一笔大亏会让 cash 跌至初始资金一小部分, 若仍按
            # self.cash all-in, 后续每笔名义资金随 cash 缩水 — 这等同于"现金自适应"
            # sizing, 会让 cash gate 在 cash-only 维度上失守 (NAV 含浮盈可能仍 > 5%
            # initial)。改用 NAV 后, cash gate 与 sizing 同口径, 防止 NAV 触底 0
            # 路径上的盲区。
            nav_for_budget = self._nav()
            target_value = nav_for_budget * self.p.position_fraction
            size = (
                int(target_value / entry_price / self.p.lot_size) * self.p.lot_size
            )
            if size < self.p.lot_size:
                self.pending_entries.pop(code, None)
                continue
            entry_fee = size * entry_price * (
                self.p.commission_rate + self.p.stamp_duty_rate
            )
            self.cash -= entry_fee
            self._holds[code] = {
                "entry_price": entry_price,
                "size": size,
                "entry_bar": len(self),
            }
            self.pending_entries.pop(code, None)

    def _check_exit(self, d) -> None:
        code = d._name
        pos = self._holds[code]
        ep = pos["entry_price"]
        tp_p = ep * (1 - self.p.tp_pct)
        sl_p = ep * (1 + self.p.sl_pct)
        held = len(self) - 1 - pos["entry_bar"]
        # CRITICAL: exit 必须滞后 entry → 至少 1 完整 bar 后才允许出场
        # (CLAUDE.md P3: exit_date > entry_date, ≥ 1 日历日 / ≥ 1 bar)
        if held < 1:
            return
        # 防穿仓 (R2, 2026-09-21): NAV-gate 强制 close。
        # 当 NAV 已跌到 cash_gate_threshold 以下 (cash gate 已拒绝新开仓),
        # 已持仓继续按 SL/TP/time 退出可能让 NAV 在持仓期内进一步跌穿 0。
        # 此时强制用 close 平掉所有持仓, 阻止浮亏继续扩大。
        # 与 chase_up / uptrend_pullback 的 NAV gate 入口 (R1) 同口径:
        # cash gate 拦 entry, NAV-gate 拦 active close。
        nav = self._nav()
        if nav < self.p.initial_capital * self.p.min_cash_ratio:
            self._close(d, float(d.close[0]), "nav_gate_eod")
            return
        low, high, close = float(d.low[0]), float(d.high[0]), float(d.close[0])
        open_p = float(d.open[0])
        reason, price = None, None
        # gap-aware：short 仓 TP/SL
        # CLAUDE.md P5 要求 SL-first：开盘同时穿越 TP/SL 时优先 SL（保 loss cap）。
        # 此实现已对齐 P5；保留 v33 baseline parity 的"gap SL 用 sl_p, gap TP 用 open_p"
        # 由 _run_single_stock_scenario 测试 (test_short_reversal_no_lookahead.py
        # :131/:160) 锁定，不允许 flip 到 open_p（参 presets.py 注释 "SL gap 不放
        # 大单笔损失" 的设计选择）。
        if open_p >= sl_p:
            reason, price = "SL", sl_p
        elif high >= sl_p:
            reason, price = "SL", sl_p
        elif open_p <= tp_p:
            reason, price = "TP", open_p
        elif low <= tp_p:
            reason, price = "TP", tp_p
        elif held >= self.p.max_hold:
            reason, price = "time", close
        if reason is not None:
            self._close(d, price, reason)

    def _close(self, d, price: float, reason: str) -> None:
        code = d._name
        pos = self._holds.pop(code)
        ep = pos["entry_price"]
        size = pos["size"]
        # 做空盈亏：(entry - exit) × size，扣 exit 佣金
        pnl = (ep - price) * size
        exit_fee = size * price * self.p.commission_rate
        self.cash += pnl - exit_fee
        gross = (ep - price) / ep
        net = gross - self.p.commission_rate
        self.trades.append(
            {
                "thscode": code,
                "entry_price": ep,
                "exit_price": float(price),
                "exit_reason": reason,
                "size": size,
                "net": float(net),
                "hold_days": len(self) - pos["entry_bar"],
            }
        )

    def _charge_margin_fees(self) -> None:
        for code, pos in list(self._holds.items()):
            fee = (
                pos["size"]
                * pos["entry_price"]
                * self.p.margin_rate
                / 365
            )
            self.cash -= fee

    # ----------------------------------------------------------- 5 conditions

    def _all_conditions(self, d) -> bool:
        indi = self.indi[d._name]

        # E 流动性（最便宜的先过滤）
        am60 = indi["am60"][0]
        if np.isnan(am60) or not (self.p.liq_low <= am60 <= self.p.liq_high):
            return False

        # A 条件
        ma60_v = indi["ma60"][0]
        if np.isnan(ma60_v):
            return False
        close_v = float(d.close[0])
        if self.p.a_condition == "cascade_price":
            ma5_v = indi["ma5"][0]
            ma10_v = indi["ma10"][0]
            ma20_v = indi["ma20"][0]
            if np.isnan(ma5_v) or np.isnan(ma10_v) or np.isnan(ma20_v):
                return False
            if not (ma5_v < ma10_v < ma20_v < ma60_v and close_v < ma20_v):
                return False
        else:  # 'default' (V1)
            ratio = indi["below_ma60_ratio_60"][0]
            if np.isnan(ratio):
                return False
            # close < ma60 (允许 close_ma60_buffer 上浮)
            if close_v >= ma60_v * (1.0 + self.p.close_ma60_buffer):
                return False
            # below_ratio_60: close 在 60 根 bar 中低于 MA60 的比例 (v3 默认 0.6)
            if ratio < self.p.below_ratio_60:
                return False

        # B 连阳
        us = indi["up_streak"][0]
        if np.isnan(us) or not (self.p.up_streak_low <= us <= self.p.up_streak_high):
            return False

        # C pct_chg
        pc = indi["pct_chg"][0]
        if np.isnan(pc) or not (
            self.p.pct_chg_low <= pc <= self.p.pct_chg_high
        ):
            return False

        # D MACD（backtrader 的 MACD 只有 macd/signal 两条线，histogram = macd - signal）
        macd = indi["macd"]
        dif = float(macd.macd[0])
        dea = float(macd.signal[0])
        bar = dif - dea
        prev_dif = float(macd.macd[-1])
        prev_dea = float(macd.signal[-1])
        prev_bar = prev_dif - prev_dea
        if np.isnan(dif) or np.isnan(dea) or np.isnan(prev_bar):
            return False
        # D 模式 (2026-09-21 引入参数化):
        #   'strict'          = DIF<0 & DEA<0 & |bar|<|prev_bar|        (v3 默认)
        #   'd_only'          = DIF<0 only (放开 DEA 与 bar 收敛)        (v36 候选)
        #   'converge_strict' = DIF<0 & DEA<0 & |bar|<|prev_bar|*0.5    (v36 候选)
        if self.p.d_mode == "d_only":
            if not (dif < 0):
                return False
        elif self.p.d_mode == "converge_strict":
            if not (dif < 0 and dea < 0 and abs(bar) < abs(prev_bar) * 0.5):
                return False
        else:  # 'strict' (默认)
            if not (dif < 0 and dea < 0 and abs(bar) < abs(prev_bar)):
                return False

        return True

    # ------------------------------------------------------------------ stop

    def stop(self):
        if self.p.result_holder is None:
            return
        self.p.result_holder.update(
            {
                "cash": self.cash,
                "trades": list(self.trades),
                "max_dd": self.max_dd,
            }
        )
