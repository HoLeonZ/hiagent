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
from cycle_price_action.presets import PRESET_V1
from cycle_price_action.signals import detect_k_patterns, k_line_score
from cycle_price_action.time_windows import calendar_score

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
    _INJECTED = {"data_provider", "precomputed_signals"}
    _accepted = set(CyclePriceActionStrategy.params._getkeys()) - _INJECTED
    strategy_kwargs = {k: v for k, v in preset.items() if k in _accepted}

    # Tick 49 (2026-09-28, CLAUDE.md §6): Control Plane owns DuckDB I/O.
    # 一条连接服务整个回测 (旧实现每只票新建一条 → 实测每次 connect+execute+close
    # 约 21 ms, 占满 cycle 回测耗时的六成)。
    data_provider = ReplayDataProvider(db_path)
    try:
        for code, slice in universe.items():
            try:
                cerebro = bt.Cerebro(stdstats=False)
                feed_df = slice.df.set_index(pd.to_datetime(slice.df["date"]))
                feed = bt.feeds.PandasData(
                    dataname=feed_df,
                    open="open", high="high", low="low",
                    close="close", volume="volume",
                    openinterest=-1,
                )
                cerebro.adddata(feed, name=code)
                cerebro.addstrategy(
                    CyclePriceActionStrategy,
                    data_provider=data_provider,
                    precomputed_signals=_precompute_scores(
                        slice.df, periods=preset.get("periods"),
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

    return BacktestResult(trades=all_trades, metrics=compute_metrics(all_trades))
