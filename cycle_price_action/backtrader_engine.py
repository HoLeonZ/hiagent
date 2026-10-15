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
    detect_k_patterns,
    entry_signal,
    fuse_scores,
    k_line_score,
)
from cycle_price_action.cycle import phase_score
from cycle_price_action.time_windows import calendar_score
from cycle_price_action.portfolio import Portfolio
from cycle_price_action.replay_broker import ReplayBroker
from cycle_price_action.data_feed import ReplayDataProvider
from cycle_price_action.no_lookahead import bars_up_to
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
        # Round 15 (2026-09-28, CLAUDE.md §4): preset→strategy plumbing for
        # intraday_tiebreak. Default 'sl_first' preserves pre-R15 behavior。
        intraday_tiebreak="sl_first",
        # Round 30 (2026-09-28, CLAUDE.md §3): limit-up entry guard,
        # mirroring chase_up + uptrend_pullback + short_reversal conventions.
        # cycle_price_action was the ONLY engine without this guard — entering
        # at limit-up close would generate phantom PnL (no shares actually
        # available at limit-up open). Default 0.095 = 9.5% tolerance for
        # 10% A-share main-board limit-up; preset-overridable.
        limit_up_threshold=0.095,
        # §4 (audit P1-B2, 2026-10-15): 滑点标定值由 Control Plane
        # 经 core.dual_price.resolve_atr_slip_scale 解析后注入
        # (缺声明在那里 fail-fast)。此前本引擎从不读取 preset 的该值,
        # broker 恒用 0.0 —— 与其余三引擎的"静默默认"同型。
        atr_slip_scale=0.0,
    )

    def __init__(self):
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
            self.p.data_provider, atr_slip_scale=self.p.atr_slip_scale,
        )
        # State for live bar evaluation.
        self._bar_cache: list[dict] = []
        self._entry_day = None

    def _bars_as_df(self) -> pd.DataFrame:
        return pd.DataFrame(self._bar_cache)

    def next(self):
        bar = {
            "date": self.datas[0].datetime.date(0),
            "open": self.datas[0].open[0],
            "high": self.datas[0].high[0],
            "low": self.datas[0].low[0],
            "close": self.datas[0].close[0],
            "volume": self.datas[0].volume[0],
        }
        # §3 (audit P2-10, 2026-10-15): 读当 bar 的公司行为事件(feed lines)。
        # 缺 line(旧测试 feed)→ 视为无事件,而非 NaN。
        _d0 = self.datas[0]
        for _col in ("div_per_share", "bonus_ratio", "rights_ratio"):
            try:
                bar[_col] = float(getattr(_d0, _col)[0])
            except (AttributeError, TypeError, ValueError, IndexError):
                bar[_col] = 0.0
        self._bar_cache.append(bar)

        # §2 (audit P0-2, 2026-10-15): A 股 T+1 结算 —— 把上一根 bar 的
        # Settling_Funds 结转为 Free_Cash。此前 `Portfolio.settle()` **在包内
        # 没有任何调用点**,于是出场回款永久滞留在 settling 池,free_cash 只减
        # 不增,引擎在首次出场后即逐渐停止开仓(账实不符)。三个兄弟引擎均在
        # 每根 bar 起始调用(见 chase_up/portfolio.py:387、
        # uptrend_pullback/portfolio.py:365、short_reversal/replay_strategy_v3.py:496)。
        self._portfolio.settle()

        # §3 (audit P2-10, 2026-10-15): 除权日先应用公司行为(分红入 Free_Cash /
        # 送股调量),再做出场判定与建仓 —— 否则除权缺口会被当成真实盈亏。
        # 位置在**建仓分支之前**,故除权日当天新建的仓位不会被误记分红
        # (权益归属:除权日买入不享有本次分红)。
        def _ev(name: str) -> float:
            v = bar.get(name, 0.0)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return 0.0
            return 0.0 if v != v else v  # NaN → 0.0

        self._portfolio.apply_corporate_action(
            dividend_per_share=_ev("div_per_share"),
            bonus_ratio=_ev("bonus_ratio"),
            rights_ratio=_ev("rights_ratio"),
        )

        df = self._bars_as_df()
        bars_until_today = bars_up_to(df, bar["date"])

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

        kscore = k_line_score(bars_until_today, detect_k_patterns(bars_until_today)).iloc[-1]
        cyc = phase_score(bars_until_today["date"]).iloc[-1]
        cal = calendar_score(bars_until_today["date"]).iloc[-1]
        sig = entry_signal(
            pd.Series([kscore]), pd.Series([cyc]), pd.Series([cal]),
            threshold=self.p.threshold, min_dim=self.p.min_dim,
        ).iloc[0]

        if self._portfolio.position is None and sig:
            # §6 (audit P3, 2026-10-15): 涨停守卫**已移入 Portfolio**(执行层)。
            # 此前它在这里(strategy 层),而另外三个引擎都在 portfolio 层 ——
            # §6 单层归属要求一条规则只有一处归属,否则两处会各自演化。
            # 这里只负责把 prev_close 传下去(前一根 bar 的收盘;feed 太短则为 None,
            # 由 Portfolio 按 best-effort 处理)。
            try:
                prev_close = float(self.datas[0].close[-1])
            except (IndexError, TypeError):
                prev_close = None
            # §1/§4 (2026-10-15): 先确认次根 bar 可成交,再让 Portfolio 建仓。
            # 顺序反了会让组合持有一个 broker 无从卖出的仓位(停牌 → 买入无成交
            # → 出场 submit_sell 抛 "cannot sell more than held")。
            if not self._broker_ext.can_fill(self.datas[0]._name, bar["date"]):
                return
            state = self._portfolio.try_enter(
                self.datas[0]._name,
                bar["close"],
                bar["date"],
                {"k_line_score": kscore, "phase_score": cyc, "calendar_score": cal},
                # R8 (2026-09-21): Volume Participation Limit (CLAUDE.md §4)。
                # 单笔最大成交量 = Bar_Volume × MAX_VOL_PARTICIPATION。
                bar_volume=bar.get("volume"),
                prev_close=prev_close,
            )
            if state is None:
                return
            fill = self._broker_ext.submit_buy(
                thscode=state.thscode,
                qty=state.shares,
                decision_date=bar["date"],
            )
            if fill is None:
                # 前置 can_fill 已确认可成交,走到这里说明组合与 broker 状态
                # 不一致 —— 那是真正的矛盾状态,按 §0 fail-fast,不静默留一个
                # 卖不掉的仓位。
                raise RuntimeError(
                    f"§0 fail-fast: portfolio entered {state.thscode} but broker "
                    f"returned no fill on a bar that can_fill() accepted"
                )
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
