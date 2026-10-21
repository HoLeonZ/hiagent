"""Run per-stock backtrader backtests over a date window."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import backtrader as bt
import duckdb
import pandas as pd

from cycle_price_action.backtrader_engine import CyclePriceActionStrategy
from cycle_price_action.cycle import DEFAULT_PERIODS, phase_score
from cycle_price_action.data_feed import ReplayDataProvider, load_universe_data
from cycle_price_action.metrics import TradeRecord, compute_metrics
from cycle_price_action.presets import PRESET_V1, resolve_score_weights
from cycle_price_action.signals import detect_k_patterns, k_line_score
from cycle_price_action.time_windows import calendar_score
from cycle_price_action.feed_bt import CyclePandasData
from cycle_price_action.portfolio import Portfolio
from core.dual_price import resolve_atr_slip_scale  # §4 (audit P1-B2)
from core.preset_contract import (
    ALL_IN,
    EXECUTION_PRICE_SOURCE,
    resolve_execution_price_source,
    resolve_max_positions,
    resolve_position_fraction,
    resolve_position_sizing,
    resolve_volume_participation,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestResult:
    trades: list[TradeRecord]
    metrics: dict


def _extract_trades(
    state: Any,  # CyclePriceActionStrategy after cerebro.run()
) -> list[TradeRecord]:
    """Build TradeRecord list from strategy's Portfolio ledger.

    strategy._portfolio.closed_trades stores dicts with all P2 meta fields
    (k_line_score / phase_score / calendar_score via decision_meta).
    """
    portfolio = state._portfolio
    out: list[TradeRecord] = []
    for rec in portfolio.closed_trades:
        meta = rec["decision_meta"]
        out.append(TradeRecord(
            thscode=rec["thscode"],
            entry_date=rec["entry_date"],
            exit_date=rec["exit_date"],
            entry_price=rec["entry_price"],
            exit_price=rec["exit_price"],
            shares=rec["shares"],
            pnl=rec["pnl"],
            hold_days=rec["hold_days"],
            k_line_score=float(meta["k_line_score"]),
            phase_score=float(meta["phase_score"]),
            calendar_score=float(meta["calendar_score"]),
        ))
    return out


def _precompute_scores(
    df: pd.DataFrame,
    periods: tuple[int, ...] | None = None,
) -> dict[date, tuple[float, float, float]]:
    """每只票一次性算出每根 bar 的信号三元组 (§6: Control Plane 负责派发)。

    与"逐 bar 对至今为止的 bar 重算"**逐位等价** —— 三个函数都只看当前及
    之前的 bar:
      * `detect_k_patterns` / `k_line_score`: 全为 rolling/shift 的后向窗口,
        在前缀 `df.iloc[:i+1]` 的第 i 行与在全表第 i 行取值相同;
      * `calendar_score`: 纯日期函数 (锚点是自然日历月末/季报日, 不是切片端点);
      * `phase_score`: 只用到序列**长度**的 `np.arange(n)`, 第 i 位与 n 无关 ——
        唯一例外是 `len < max(periods)` 时整体返回 0, 故此处显式复刻该分支。

    旧路径是 O(n²): 2990 只票 × ~235 bar 的一年窗口实测 86 分钟, 其中 87%
    花在这个重算上。零漂移由 /tmp 的 40 只票对照脚本 (trades sha256) 锁定。
    """
    patterns = detect_k_patterns(df)
    ks = k_line_score(df, patterns)
    cy = phase_score(df["date"], periods=periods)
    cal = calendar_score(df["date"])

    min_bars = max(periods or DEFAULT_PERIODS)
    out: dict[date, tuple[float, float, float]] = {}
    for i, d in enumerate(df["date"]):
        cyc = 0.0 if (i + 1) < min_bars else float(cy.iloc[i])
        out[pd.Timestamp(d).date()] = (
            float(ks.iloc[i]), cyc, float(cal.iloc[i]),
        )
    return out


def run_backtest(
    db_path: str,
    start: date,
    end: date,
    cash: float = 1_000_000,
    preset: dict | None = None,
) -> BacktestResult:
    """Run cycle_price_action v1 across all main-board stocks in [start, end]."""
    preset = preset or dict(PRESET_V1)
    # Round 14 (2026-09-28, CLAUDE.md §3): PIT-compliant universe at `start`
    # (not `end`) — 避免 post-hoc constituents 入选。
    universe = load_universe_data(db_path, start, end, asof_date=start)
    all_trades: list[TradeRecord] = []
    # ⚠️ 2026-10-19 (§13.98): 这里**原来是一份手工白名单** —— 与
    # `CyclePriceActionStrategy.params` 重复维护, 于是**任何新加的 param 都会
    # 被静默丢掉**, 而注释还写着 "preset-overridable"。实测它已经吃掉了一个:
    # `limit_up_threshold` 在 params 里、不在白名单里 ⇒ 声明它**无效**。
    # (本文件自己的注释就记着 Round 15 修过一次同类事故 —— 修的是**实例**,
    #  没修**机制**。)
    # ⇒ 改为**从 params 派生**: 不存在"忘了同步"这回事。
    # `_INJECTED` 是 Control Plane 显式传的, 不得出现在 **strategy_kwargs 里
    # (否则 `addstrategy` 收到重复关键字 ⇒ TypeError)。
    # §0/§2/§3/§4 (audit 2026-10-15, 与分支合并): 下列键同样由 Control Plane
    # 逐名注入 —— 八项需要 `resolve_*` 解析 (weight_* / position_* / max_positions
    # / max_volume_participation / price_source_for_execution / atr_slip_scale),
    # 两项由本函数自己构造 (data_provider / precomputed_signals)。它们都必须排除
    # 在派生集合之外: 否则 preset 的**原值**会先进入 strategy_kwargs ——
    # 值虽与被解析后相同, 但"声明 → 落点"之间会多出一条看不见的路径
    # (§13.98 的同一形状: 两处各持一半真相)。
    _INJECTED = {
        "data_provider", "precomputed_signals",
        "atr_slip_scale",
        "weight_kline", "weight_cycle", "weight_calendar",
        "position_fraction", "position_sizing", "max_positions",
        "max_volume_participation", "price_source_for_execution",
    }
    _accepted = set(CyclePriceActionStrategy.params._getkeys()) - _INJECTED
    strategy_kwargs = {k: v for k, v in preset.items() if k in _accepted}
    preset_name = preset.get("name", "cycle_price_action")
    # §4 (audit P1-B2): 滑点标定值必须显式声明,缺声明 fail-fast。
    strategy_kwargs["atr_slip_scale"] = resolve_atr_slip_scale(preset, preset_name)
    # §0/§2/§3/§4 (audit 2026-10-15): 其余被声明却无人读取的键,一律经规范
    # 契约解析后再注入 —— 缺声明/值越界/超出引擎容量都在此 fail-fast,而不是
    # 让策略退回一个"看起来合理"的默认值(那正是缺口靠沉默存在的形态)。
    # §0 (audit 2026-10-15): 三个评分维度权重。此前硬编码在 signals.fuse_scores
    # 的**默认参数**里(与 PRESET_V1 声明同值),于是改预设什么都不会发生。
    # 现在逐名注入,与其余 preset 键同一条管线。
    _weight_kline, _weight_cycle, _weight_calendar = resolve_score_weights(
        preset, preset_name
    )
    strategy_kwargs["weight_kline"] = _weight_kline
    strategy_kwargs["weight_cycle"] = _weight_cycle
    strategy_kwargs["weight_calendar"] = _weight_calendar
    strategy_kwargs["position_fraction"] = resolve_position_fraction(preset, preset_name)
    strategy_kwargs["position_sizing"] = resolve_position_sizing(
        preset, preset_name, allowed=frozenset({ALL_IN})
    )
    strategy_kwargs["max_positions"] = resolve_max_positions(
        preset, preset_name, capacity=Portfolio.MAX_POSITIONS_CAPACITY
    )
    strategy_kwargs["max_volume_participation"] = resolve_volume_participation(
        preset, preset_name
    )
    strategy_kwargs["price_source_for_execution"] = resolve_execution_price_source(
        preset, preset_name, supported=frozenset({EXECUTION_PRICE_SOURCE})
    )

    # Tick 49 (2026-09-28, CLAUDE.md §6): Control Plane owns DuckDB I/O.
    # 一条连接服务整个回测 (旧实现每只票新建一条 → 实测每次 connect+execute+close
    # 约 21 ms, 占满 cycle 回测耗时的六成)。provider 在循环外构造、在 finally 里
    # 关闭 —— 与 precomputed_signals 同属本层派发的 PIT 数据 (§6)。
    data_provider = ReplayDataProvider(db_path)
    try:
        for code, slice in universe.items():
            try:
                cerebro = bt.Cerebro(stdstats=False)
                feed_df = slice.df.set_index(pd.to_datetime(slice.df["date"]))
                # §3 (audit P2-10, 2026-10-15): 改用携带事件列的自定义 feed
                feed = CyclePandasData(
                    dataname=feed_df,
                    open="open", high="high", low="low",
                    close="close", volume="volume",
                    openinterest=-1,
                )
                cerebro.adddata(feed, name=code)
                cerebro.addstrategy(
                    CyclePriceActionStrategy,
                    data_provider=data_provider,
                    # 信号三元组每只票预计算一次 (逐 bar 重算是 O(n²), 实测占
                    # cycle 回测总耗时的 87%)。periods 只此一个来源: 与
                    # strategy_kwargs 里流下去的是**同一个值**。
                    precomputed_signals=_precompute_scores(
                        slice.df, periods=strategy_kwargs.get("periods"),
                    ),
                    **strategy_kwargs,
                )
                cerebro.broker.setcash(cash)
                results = cerebro.run()
            except (duckdb.Error, ValueError, KeyError) as e:
                # §0 Fail-Fast: per-stock failure MUST propagate, not silently
                # bypass. Scan/grid loops (per prior # noqa: BLE001 patterns)
                # allow warn-log + continue; here in cycle_price_action the
                # outer caller depends on full coverage.
                raise RuntimeError(
                    f"backtest failed for {code}: {e}"
                ) from e
            strat = results[0]
            # _extract_trades is intentionally outside the try/except: decision-
            # extraction bugs must fail loudly rather than be silently skipped.
            all_trades.extend(_extract_trades(strat))
    finally:
        data_provider.close()

    # §2 (audit 2026-10-15): 账户数 = **universe 成员数**,不是成交过的股票数 ——
    # 每个成员都开了一个账户(即使那笔账户一笔未成交),故"本金"分母是前者。
    # 两个参数是 compute_metrics 的必填项:产出一个不带口径的 total_pnl 会误导
    # 读者把它当成单个 100 万组合的盈亏(实测 472 个账户时相差两个数量级)。
    return BacktestResult(
        trades=all_trades,
        metrics=compute_metrics(
            all_trades, cash_per_account=cash, n_accounts=len(universe),
        ),
    )
