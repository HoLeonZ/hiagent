"""T+1 next-bar-matching broker for cycle_price_action.

Order semantics:
    - Order is queued at decision_date close.
    - Fill occurs on the next trading day's open price.
    - P3 guard: same-day exits are rejected at queue time.

§6 architecture (Tick 49, 2026-09-28): Execution Broker is DB-free.
ReplayBroker receives a `ReplayDataProvider` (from Control Plane
`cycle_price_action.data_feed`) and delegates all per-fill PIT lookups
to it. This broker contains zero `duckdb.connect` calls — pure
slippage / cost / position bookkeeping.
"""
from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import date
from typing import Optional

from core.dual_price import (
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,  # Round 9 (2026-09-28): canonical 万5 sell-only stamp duty
    # 附八十一: `_fee()` 在 `atr_slip_scale > 0` 的分支里调用它,而这个名字**此前没被 import**
    # ⇒ 一旦打开 ATR 滑点(§4 原则上有此要求,现为待决口径:全库 preset 的 atr_slip_scale
    # 都是 0),broker 会在**第一笔成交**上 `NameError`。之所以没人发现:那段代码从未被执行。
    effective_slippage,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeFill:
    date: date
    thscode: str
    side: str         # "buy" | "sell"
    qty: int
    price: float
    fee: float


class ReplayBroker:
    def __init__(
        self,
        data_provider,  # cycle_price_action.data_feed.ReplayDataProvider
        # R5' (2026-09-23, CLAUDE.md §4): ATR-aware slippage opt-in.
        # atr_slip_scale = 0.0 (default) → no slippage applied (back-compat).
        # atr_slip_scale > 0 → slippage = max(static_slip, atr_pct × participation × scale).
        atr_slip_scale: float = 0.0,
    ) -> None:
        self._data_provider = data_provider
        self.atr_slip_scale = atr_slip_scale
        self._open_positions: dict[str, int] = {}

    def _next_trading_date(self, after: date) -> date:
        # Tick 49: delegate to Control Plane data_provider (DB-free broker).
        return self._data_provider.next_trading_date(after)

    def _open_price(self, thscode: str, on_date: date) -> float | None:
        # Tick 49 + N3: delegate to data_provider.open_price which routes
        # through extract_execution_bar to enforce partial-NaN guard
        # (open>0 + close=NaN raises ValueError).
        return self._data_provider.open_price(thscode, on_date)

    def can_fill(self, thscode: str, decision_date: date) -> bool:
        """次根 bar 是否可成交(停牌 → False)。

        §1/§4 (2026-10-15): 入场必须**先确认能成交、再让 Portfolio 建仓**。
        组合账本与 broker 的 `_open_positions` 是两套状态:若走出
        `try_enter()` 但 `submit_buy()` 因停牌未成交,组合就持有一个 broker
        认不到的仓位,后续 `submit_sell()` 会抛 "cannot sell more than held"
        (实测 000639.SZ)。该顺序问题在 `submit_buy` 改成"停牌返回 None"之后
        才暴露出来。
        未知标的(库中完全无 bar)仍由 `_open_price` fail-fast 抛错。
        """
        return self._open_price(thscode, self._next_trading_date(decision_date)) is not None

    def _fee(
        self,
        side: str,
        qty: int,
        price: float,
        atr_pct: float | None = None,
        participation: float = 0.0,
        static_slip: float = 0.0,
    ) -> float:
        notional = qty * price
        # §2 (audit P2-11, 2026-10-15): core 单源
        commission = max(MIN_COMMISSION, notional * COMMISSION_RATE)
        # Round 9 (2026-09-28, CLAUDE.md §0/§3): canonical STAMP_DUTY_RATE (万5
        # post-Aug2023); was 0.001 = 万10 pre-Aug2023 historical.
        tax = notional * STAMP_DUTY_RATE if side == "sell" else 0.0
        # R5' (2026-09-23, CLAUDE.md §4): ATR-aware slippage.
        # Effective slip = max(static_slip, atr_pct × participation × scale) when scale > 0
        # and atr_pct provided; else static_slip only.
        if (
            self.atr_slip_scale > 0
            and atr_pct is not None
            and not _is_nan(atr_pct)
        ):
            # §4 (audit P1-B, 2026-10-15): 滑点策略单源(core)。
            slip_eff = effective_slippage(
                static_slip, atr_pct, participation, self.atr_slip_scale,
            )
        else:
            slip_eff = static_slip
        return commission + tax + notional * slip_eff

    def submit_buy(
        self,
        thscode: str,
        qty: int,
        decision_date: date,
        atr_pct: float | None = None,
        participation: float = 0.0,
    ) -> Optional[TradeFill]:
        if qty <= 0 or qty % 100 != 0:
            raise ValueError("qty must be positive multiple of 100")
        fill_date = self._next_trading_date(decision_date)
        price = self._open_price(thscode, fill_date)
        if price is None:
            # §1 (audit, 2026-10-15): 停牌(当日缺 bar)→ **本次不成交**。
            # 不合成 bar、不排队到下一 bar(§4 IOC)。持仓/挂单状态不变,
            # 复牌后由引擎的下一次决策重新评估。
            logger.warning(
                "[suspend] %s 在 %s 无 bar(停牌),买入不成交", thscode, fill_date
            )
            return None
        fee = self._fee("buy", qty, price, atr_pct=atr_pct, participation=participation)
        self._open_positions[thscode] = self._open_positions.get(thscode, 0) + qty
        return TradeFill(fill_date, thscode, "buy", qty, price, fee)

    def record_fill(self, fill: TradeFill) -> None:
        pass  # for future instrumentation

    def submit_sell(
        self,
        thscode: str,
        qty: int,
        decision_date: date,
        atr_pct: float | None = None,
        participation: float = 0.0,
    ) -> Optional[TradeFill]:
        # P3: same-day exit forbidden.
        held = self._open_positions.get(thscode, 0)
        # §0 (附五十五): 这里**不能**对 `held` 做硬断言 —— 它是一条**影子账**,
        # 有两条合法路径会让它与组合账本分叉:
        #   (a) 送股/配股把组合的持股数放大(§3 要求的物理调整),broker 在买入时
        #       只记了**除权前**的数量 ⇒ 全仓卖出时 `qty > held`;
        #   (b) SL/TP 出场走 `Portfolio.try_exit_with_intraday_check`,**不经过**
        #       `submit_sell` ⇒ 那些平仓从不减少 `held`(实测同一标的上 `held`
        #       已累积到 1,050,900 而组合实际只持 346,612)。
        # 之前它是 `raise ValueError("cannot sell more than held")` —— 在上述任一
        # 情形下都会把一次**合法**的全仓平仓变成整轮回测的中止。
        # 组合账本才是持股数的权威;此处降级为不一致告警(仍可见,不再中止)。
        if held < qty:
            logger.warning(
                "[broker-shadow] %s 卖出 %d 股 > 影子账 %d 股 —— 影子账与组合账本"
                "分叉(送股调整 或 SL/TP 出场未经过 broker);按组合账本执行",
                thscode, qty, held,
            )
        if qty <= 0:
            raise ValueError("qty must be positive")
        # A 股规则(附五十五):**买入**必须是 100 股整数倍;**卖出**不必 ——
        # 送股/配股会把持仓变成非整手,而 A 股允许(且要求)把零股以**一笔**
        # 全部卖出。此前这里对卖出也要求 100 的整数倍,于是该 bar 直接抛
        # ValueError,被 `backtest.run_backtest` 包成 RuntimeError
        # **中止整轮回测**(实测:000793.SZ 于 2026-06-22 除权,送股比率
        # 0.0478,330,800 → 346,612 股,非整手 ⇒ 整轮 backtest 崩掉)。
        # 本引擎只做**整仓平仓**(唯一的卖出调用传的就是 `position.shares`),
        # 故非整手在这里只可能是"含零股的全仓卖出"。
        if qty % 100 != 0:
            logger.info(
                "[odd-lot] 全仓卖出含零股 %s qty=%d(送股/配股产生;A 股允许整笔卖出)",
                thscode, qty,
            )
        fill_date = self._next_trading_date(decision_date)
        price = self._open_price(thscode, fill_date)
        if price is None:
            # §1 (audit, 2026-10-15): 停牌无法卖出 → 持仓**必须保留**,
            # 复牌前不产生成交(旧实现直接 RuntimeError 中止整个回测)。
            logger.warning(
                "[suspend] %s 在 %s 无 bar(停牌),卖出不成交,持仓保留",
                thscode, fill_date,
            )
            return None
        fee = self._fee("sell", qty, price, atr_pct=atr_pct, participation=participation)
        # 影子账可能已落后于组合(见上方分叉说明)⇒ 不能直接 -=,否则会变负
        # 且永不清除。夹到 0 即视为清空。
        # §0 (不可变性):**重建**一个新 dict 再 rebind,而不是原地 `pop` ——
        # 原地 `pop` 会被 `tests/test_immutable_state_4engine.py` 的扫描器命中
        # (该扫描器只看 `self.<attr>.<mutable_method>()`,所以 `del d[k]` 与
        # 下标赋值不被它看见;**不绕它,改成语法上就合规的写法**)。
        _remaining = max(0, self._open_positions.get(thscode, 0) - qty)
        _book = {c: n for c, n in self._open_positions.items() if c != thscode}
        if _remaining:
            _book[thscode] = _remaining
        self._open_positions = _book
        return TradeFill(fill_date, thscode, "sell", qty, price, fee)


def _is_nan(x: float) -> bool:
    return x != x