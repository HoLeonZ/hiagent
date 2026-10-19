"""Backtrader strategy wiring for cycle_price_action.

Decision flow per bar:
    1.  Compute signal triple (k_line_score, cycle_score, calendar_score).
    2.  fusing → total_score.
    3.  If no position AND total_score ≥ threshold → submit_buy on next bar.
    4.  If position held → daily-bar V6'' SL-first check (worst-case):
          - open ≤ sl_p → SL @ open (gap-down)
          - open ≥ tp_p → TP @ open (gap-up)
          - low  ≤ sl_p → SL @ sl_p (intraday stop)         — SL-first
          - high ≥ tp_p → TP @ tp_p (intraday target)
    5.  Else if position held ≥ max_hold → time exit @ close.

P0–P8 are enforced via no_lookahead helpers + replay_broker.
"""
from __future__ import annotations

import pandas as pd

import backtrader as bt

from cycle_price_action.signals import (
    entry_signal,
    fuse_scores,
)
from cycle_price_action.portfolio import Portfolio
from cycle_price_action.replay_broker import ReplayBroker
from cycle_price_action.data_feed import ReplayDataProvider
from core.dual_price import (
    LAYOUT_CYCLE_PRICE,
    extract_execution_bar,
    is_limit_up,
)


class CyclePriceActionStrategy(bt.Strategy):
    params = dict(
        threshold=2.0,
        min_dim=1.0,
        max_hold=5,
        atr_period=14,
        atr_sl_mult=1.5,
        tp_pct=0.06,
        # V6'' (2026-09-22, CLAUDE.md §4): SL fraction applied to entry
        # price to compute daily-bar stop. Pessimistic default = atr_sl_mult ×
        # 0.05 = 7.5% stop, conservative for cycle strategy.
        sl_pct=0.05,
        # Round 10 (2026-09-28, CLAUDE.md §2): NAV gate anchor — plumbed
        # through to Portfolio constructor (initial_capital). Default 1M mirrors
        # chase_up + uptrend_pullback + short_reversal (all 1M baseline)。
        initial_capital=1_000_000.0,
        # Tick 49 (2026-09-28, CLAUDE.md §6): Broker no longer accepts db_path
        # directly. Control Plane (backtest.run_backtest) constructs a
        # ReplayDataProvider from db_path and injects it here. Strategy stays
        # DB-free per §6 (no db_path param).
        data_provider=None,
        # 信号三元组 {date: (k_line_score, phase_score, calendar_score)} —— 由
        # Control Plane (backtest.run_backtest) 每只票预计算一次后注入。
        # 逐 bar 重算是 O(n²), 实测占 cycle 回测总耗时的 87%。
        precomputed_signals=None,
        # V9 (2026-10-16): 三维融合权重。此前已在 PRESET_V1 声明, 但从未被
        # 读取 —— `next()` 调 entry_signal 时不传 weights, 走的是同一组默认值;
        # `backtest._accepted` 白名单也把它们过滤掉了。接通后声明才是真的
        # (默认值与声明值相同 ⇒ 零漂移)。
        weight_kline=1.0,
        weight_cycle=0.7,
        weight_calendar=0.5,
        # 同一类缺口: PRESET_V1 声明 periods=(3,5,8,13,21), 而 phase_score
        # 一直走 DEFAULT_PERIODS (同值)。接通后可由 preset 调周期组。
        periods=(3, 5, 8, 13, 21),
        # Round 15 (2026-09-28, CLAUDE.md §4): preset→strategy plumbing for
        # intraday_tiebreak. Default 'sl_first' preserves pre-R15 behavior。
        intraday_tiebreak="sl_first",
        # Round 30 (2026-09-28, CLAUDE.md §3): limit-up entry guard,
        # mirroring chase_up + uptrend_pullback + short_reversal conventions.
        # cycle_price_action was the ONLY engine without this guard — entering
        # at limit-up close would generate phantom PnL (no shares actually
        # available at limit-up open). Default 0.095 = 9.5% tolerance for
        # 10% A-share main-board limit-up; preset-overridable.
        # ⚠️ 2026-10-19 (§13.98): "preset-overridable" 这句**此前是假的** ——
        # `backtest.py` 的 `_accepted` 手工白名单没有列它 ⇒ preset 声明会被
        # **静默丢掉**。已把白名单改为**从本 params 派生**, 该声明现在成立。
        limit_up_threshold=0.095,
        # §4/§13.98 (2026-10-19): 执行滑点的系数。此前本族**连参数都到不了**
        # 任何执行路径 (三处断链): ① 不在本 params ⇒ 不在白名单; ②
        # `ReplayBroker(...)` 构造时不传 ⇒ 恒用默认 0.0; ③ 两个 submit 调用
        # 不传 `atr_pct`/`participation` ⇒ `_fee` 的 ATR 分支恒不触发。
        # ⚠️ 默认 0.0 保证**零漂移** (55/55 preset 未声明它)。
        # ⚠️ `cycle_price_action/portfolio.py` 里**还有一个同名参数**
        # (`Portfolio.__init__` 存了 `self.atr_slip_scale`) 而**从不读它** ——
        # 真正的滑点在 `ReplayBroker._fee`。那个参数是死的, 见 §13.98(f)。
        atr_slip_scale=0.0,
    )

    def __init__(self):
        # ----- §4/§0 fail-fast (§13.98, 2026-10-19) -----
        # 本族的执行滑点**在架构上不可能生效**, 故在此**立即拒绝**, 不静默无效。
        # 实测证据 (mutation test): `atr_slip_scale` 取 0 / 1 / **50** 三次回测,
        # `total_pnl` **逐位相同** —— 无论系数多大都不改变任何数字。
        # 根因: 本族有**两套并行的成本模型** ——
        #   ① `Portfolio._buy_cost` / `_sell_proceeds` —— 真正进现金的,
        #      **不含滑点** (它存了 `self.atr_slip_scale`, 但从不读);
        #   ② `ReplayBroker._fee` —— **含** ATR 滑点, 但它的返回值
        #      `TradeFill.fee` 在**整个 `cycle_price_action/` 包里零消费者**
        #      (调用方只用 `fill.date` / `fill.price`; `record_fill` 是 `pass`;
        #      `metrics.py` 也没有 `fee` 字段)。
        # ⇒ 把滑点接进 ② 等于把它算进一个**被丢弃**的数。§0 明令
        #   "Do not silently bypass" ⇒ 拿不到正确模型时**拒绝**, 而不是返回一个
        #   看起来合规的零 (与 §13 的 `COALESCE(...,1)` 同一处置精神)。
        if self.p.atr_slip_scale > 0:
            raise ValueError(
                "§4/§0: cycle_price_action 的 `atr_slip_scale` **不可能生效**。\n"
                "本族有两套并行成本模型: Portfolio 那套(真正进现金, **不含滑点**) "
                "与 ReplayBroker._fee(含 ATR 滑点, 但 `TradeFill.fee` **零消费者**)。\n"
                "把滑点写进被丢弃的那个, 系数多大都不会改变任何数字 "
                "(实测 0 / 1 / 50 三次的 total_pnl 逐位相同)。\n"
                "在把滑点接进 Portfolio 的**活跃**成本模型之前, 本旋钮只能拒绝。"
            )
        self._portfolio = Portfolio(
            cash=self.broker.getcash(),
            initial_capital=self.p.initial_capital,
            # Round 15 (2026-09-28, CLAUDE.md §4): preset→Portfolio plumbing
            # for intraday_tiebreak (181st dropped preset key gap)。
            # 与 chase_up + uptrend_pullback + short_reversal Portfolio 同口径。
            intraday_tiebreak=self.p.intraday_tiebreak,
        )
        # Tick 49: ReplayBroker receives pre-built data_provider from Control
        # Plane. If none was injected, raise — fail-fast rather than silently
        # fall back to DB-construction (which would re-introduce the §6
        # violation).
        if self.p.data_provider is None:
            raise ValueError(
                "CyclePriceActionStrategy requires `data_provider` to be "
                "injected by Control Plane (backtest.run_backtest). "
                "CLAUDE.md §6: Strategy has no direct DB access."
            )
        self._broker_ext = ReplayBroker(
            self.p.data_provider, atr_slip_scale=self.p.atr_slip_scale
        )
        # 信号三元组由 Control Plane 预计算后注入 (§6: Control Plane 拥有 PIT
        # 数据派发)。逐 bar 重算的旧路径是 O(n²) —— 每根 bar 都对"至今为止的
        # 全部 bar"重跑一次形态识别, 2990 只票的一年窗口实测 86 分钟, 其中
        # 87% 花在这里。预计算是逐位等价的 (见 backtest._precompute_scores)。
        self._signals = self.p.precomputed_signals
        if self._signals is None:
            raise ValueError(
                "CyclePriceActionStrategy requires `precomputed_signals` to be "
                "injected by Control Plane (backtest.run_backtest). "
                "CLAUDE.md §6: Strategy has no direct DB access."
            )
        # State for live bar evaluation.
        self._entry_day = None
        # §4/§13.98 (2026-10-19): 这里**曾**在策略内建过一条尾窗 TR(14) 供滑点用 ——
        # **已撤回**, 因为实测它的下游是一个**被丢弃的成本模型** (见本节上面的
        # fail-fast): 喂进去的 `atr_pct` 只到达 `ReplayBroker._fee`, 而那个返回值
        # 没有任何消费者。**留着它等于让代码假装 §4 已接通。**

    def next(self):
        bar = {
            "date": self.datas[0].datetime.date(0),
            "open": self.datas[0].open[0],
            "high": self.datas[0].high[0],
            "low": self.datas[0].low[0],
            "close": self.datas[0].close[0],
            "volume": self.datas[0].volume[0],
        }

        # ---- V6'' (2026-09-22, CLAUDE.md §4): Intraday SL-first check ----
        # If holding a position, evaluate daily-bar worst-case exit BEFORE
        # computing new signals. This guarantees that an existing position
        # always gets the most pessimistic exit decision (CLAUDE.md §4 "BOTH
        # SL and TP breached within the same bar → SL first").
        if self._portfolio.position is not None and self._entry_day is not None:
            if bar["date"] > self._entry_day:    # P3: no same-day exit
                # We must compute SL/TP levels from entry_price × (1 ± pct).
                # atr_sl_mult × tp_pct approximates the ATR-implied stop width
                # used elsewhere in the codebase.
                sl_pct_eff = self.p.sl_pct
                tp_pct_eff = self.p.tp_pct
                # V3a+ (2026-09-22, CLAUDE.md §3): Layout C 单价格域
                # 走 core.dual_price.extract_execution_bar 单一来源 —
                # 与 chase_up / uptrend_pullback / short_reversal 共用同一函数,
                # 未来若 Layout C 切到双价格域 (raw/adj split) 也能复用。
                bar_exec = extract_execution_bar(
                    {"open": bar["open"], "high": bar["high"],
                     "low": bar["low"], "close": bar["close"]},
                    LAYOUT_CYCLE_PRICE,
                )
                _, reason = self._portfolio.try_exit_with_intraday_check(
                    exit_date=bar["date"],
                    open_price=bar_exec.open,
                    high=bar_exec.high,
                    low=bar_exec.low,
                    close=bar_exec.close,
                    tp_pct=tp_pct_eff,
                    sl_pct=sl_pct_eff,
                )
                if reason in ("SL", "TP"):    # exit triggered
                    self._entry_day = None
                    return
                # reason == 'time' → fall through to max_hold check below

        try:
            kscore, cyc, cal = self._signals[bar["date"]]
        except KeyError as exc:
            # §0 Fail-Fast: 缺失的预计算 key 意味着 feed 与注入的信号不同源,
            # 静默跳过会变成一根"没有信号"的 bar —— 与"策略不发信号"同形。
            raise ValueError(
                f"no precomputed signals for {self.datas[0]._name} on "
                f"{bar['date']} — feed 与注入的 precomputed_signals 不同源"
            ) from exc
        sig = entry_signal(
            pd.Series([kscore]), pd.Series([cyc]), pd.Series([cal]),
            threshold=self.p.threshold, min_dim=self.p.min_dim,
            weights=(
                self.p.weight_kline,
                self.p.weight_cycle,
                self.p.weight_calendar,
            ),
        ).iloc[0]

        if self._portfolio.position is None and sig:
            # Round 30 (2026-09-28, CLAUDE.md §3): limit-up entry guard.
            # cycle_price_action was the ONLY engine without this guard.
            # Mirrors chase_up + uptrend_pullback (Portfolio-level) and
            # short_reversal (engine-level for LIMIT_DOWN). prev_close from
            # previous bar's close via backtrader feed; if feed too short,
            # close[-1] is None → is_limit_up returns False (best-effort).
            try:
                prev_close = float(self.datas[0].close[-1])
            except (IndexError, TypeError):
                prev_close = None
            if is_limit_up(
                prev_close=prev_close,
                open_price=bar["open"],
                threshold=self.p.limit_up_threshold,
            ):
                return  # skip entry: limit-up open, no shares available
            state = self._portfolio.try_enter(
                self.datas[0]._name,
                bar["close"],
                bar["date"],
                {"k_line_score": kscore, "phase_score": cyc, "calendar_score": cal},
                # R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
                # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。
                bar_volume=bar.get("volume"),
            )
            if state is None:
                return
            fill = self._broker_ext.submit_buy(
                thscode=state.thscode,
                qty=state.shares,
                decision_date=bar["date"],
            )
            if fill is not None:
                self._entry_day = fill.date
        elif self._portfolio.position is not None and self._portfolio.hold_days(bar["date"]) >= self.p.max_hold:
            fill = self._broker_ext.submit_sell(
                thscode=self._portfolio.position.thscode,
                qty=self._portfolio.position.shares,
                decision_date=bar["date"],
            )
            if fill is not None:
                # Portfolio exits at the fill date with the actual fill price.
                self._portfolio.try_exit(fill.date, fill.price)
                self._entry_day = None
