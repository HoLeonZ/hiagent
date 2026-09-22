"""backtrader 验证引擎 — Phase 1 (候选) + Phase 2 (backtrader 撮合验证)。

照搬 uptrend_pullback/backtrader_engine.py 口径,只换策略类 (ChaseUpTradeReplay)
+ compute_trade_tp_sl 调用方 (chase_up 的 preset 不区分 long_mirror)。
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from chase_up.backtest import INITIAL_CAPITAL, compute_metrics
from chase_up.data import load_panel
from chase_up.portfolio import TRADE_COLS, simulate_portfolio
from chase_up.presets import MAX_HOLD_LIMIT, get_preset
from chase_up.replay_broker import AStockBroker
from chase_up.replay_strategy import ChaseUpTradeReplay
from chase_up.signals import compute_indicators, select_entries
from chase_up.universe import load_universe

logger = logging.getLogger(__name__)


def compute_trade_tp_sl(
    entry_price: float,
    *,
    fixed_tp_pct: float,
    fixed_sl_pct: float,
    atr_pct: float | None = None,
    atr_tp_mult: float | None = None,
    atr_sl_mult: float | None = None,
    atr_pct_floor: float = 0.01,
    atr_pct_cap: float = 0.08,
) -> tuple[float, float]:
    """由信号日 atr_pct 计算 TP/SL 宽度 (与 portfolio.py:simulate_portfolio 完全一致)。

    P0 核心:必须严格用 T 日 atr_pct,严禁读 entry_date (T+1) 当根 K 线的 atr_pct。
    """
    if atr_tp_mult is not None and atr_sl_mult is not None and atr_pct is not None \
            and not (isinstance(atr_pct, float) and math.isnan(atr_pct)):
        a = min(max(float(atr_pct), atr_pct_floor), atr_pct_cap)
        return entry_price * (1 + a * atr_tp_mult), entry_price * (1 - a * atr_sl_mult)
    return entry_price * (1 + fixed_tp_pct), entry_price * (1 - fixed_sl_pct)


def _build_bt_feed(
    span: pd.DataFrame,
    price_source_for_execution: str,
) -> pd.DataFrame:
    """V3a+ (2026-09-22, CLAUDE.md §3): backtrader feed 必须遵循 price_source_for_execution。

    Layout A 行为 (与 uptrend_pullback/backtrader_engine.py:115-132 同构):
      - raw_close: 用 extract_execution_bar(LAYOUT_CHASE_UPTREND) 重映射 open/high/low/close
        → raw_* 优先, raw_* 缺失时回退 adj_*, 防 phantom TP/SL
      - adj_close (默认): 用 span[open/high/low/close] (qfq 列,backtrader 跑在 qfq 域)
      - raw_* 列缺失时: best-effort 回退到 span[*],与 portfolio.py 行为一致

    复现的 bug: 旧版无条件用 span[*] (qfq),与 portfolio.py Phase 1 entry 用 raw_open
    (commit 86832f7) 口径不一 → Phase 2 backtrader ChaseUpTradeReplay 跑在 qfq 域,
    在 `o <= sl_p` 判定上以 qfq_open 与 raw_sl 比较,qfq_open << raw_sl → 误触发 SL,
    exit_price = qfq_open → phantom loss (v3 backtrader output: 4/59 SL phantom)。
    """
    if price_source_for_execution == "raw_close" and "raw_open" in span.columns:
        from core.dual_price import LAYOUT_CHASE_UPTREND, extract_execution_bar
        rows = []
        for _, row in span.iterrows():
            bar = extract_execution_bar(
                {k: row.get(k) for k in (
                    "open", "high", "low", "close", "prev_close",
                    "raw_open", "raw_high", "raw_low", "raw_close", "raw_prev_close",
                )},
                LAYOUT_CHASE_UPTREND,
            )
            rows.append({
                "open": bar.open, "high": bar.high,
                "low": bar.low, "close": bar.close,
            })
        feed_df = pd.DataFrame(rows)
        feed_df["date"] = pd.to_datetime(span["date"].values)
        feed_df["volume"] = span["volume"].values
    else:
        feed_df = span[["date", "open", "high", "low", "close", "volume"]].copy()
    feed_df["date"] = pd.to_datetime(feed_df["date"])
    feed_df = feed_df.set_index("date").sort_index().astype(float)
    return feed_df


def _verify_trade_with_backtrader(
    panel: pd.DataFrame,
    thscode: str,
    entry_date: pd.Timestamp,
    entry_price: float,
    target_size: int,
    tp_price: float,
    sl_price: float,
    max_hold: int,
    price_source_for_execution: str = "adj_close",
) -> tuple[float, float, pd.Timestamp | None]:
    """对单笔交易跑 backtrader,返回 (net_pnl, exit_price_actual, exit_date_actual)。

    V3a+ (2026-09-22, CLAUDE.md §3): price_source_for_execution 控制 feed 价格域。
    与 portfolio.py Phase 1 口径对齐,防 Phase 2 backtrader 跑在 qfq 域 → phantom。
    """
    code_data = panel[panel["thscode"] == thscode].sort_values("date")
    if code_data.empty:
        return 0.0, entry_price, None

    future = code_data[code_data["date"] < entry_date].tail(1)
    if future.empty:
        return 0.0, entry_price, None
    feed_start = pd.Timestamp(future.iloc[0]["date"])
    span = code_data[code_data["date"] >= feed_start].head(max_hold + 5)
    if span.empty:
        return 0.0, entry_price, None
    feed_df = _build_bt_feed(span, price_source_for_execution)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed_df))
    initial_cash = max(target_size * entry_price * 1.0025, 100_000.0)
    cerebro.broker = AStockBroker()
    cerebro.broker.set_cash(initial_cash)
    cerebro.addstrategy(
        ChaseUpTradeReplay,
        target_size=target_size,
        tp_price=tp_price,
        sl_price=sl_price,
        max_hold=max_hold,
    )
    results = cerebro.run()
    strat = results[0]
    if strat.skipped or strat.exit_reason is None:
        return 0.0, entry_price, None

    final_cash = cerebro.broker.getcash()

    if strat.actual_exit_price is not None:
        actual_exit = float(strat.actual_exit_price)
        actual_exit_date = strat.actual_exit_date
        net_pnl = final_cash - initial_cash
    else:
        logger.warning(
            "_verify_trade_with_backtrader: thscode=%s exit_reason=%s 但订单未成交, "
            "actual_exit 退回 entry_price, net_pnl 兜底为 0",
            thscode, strat.exit_reason,
        )
        actual_exit = entry_price
        actual_exit_date = None
        net_pnl = 0.0
    return float(net_pnl), float(actual_exit), actual_exit_date


def run_backtrader_backtest(
    preset: str | dict,
    start: str,
    end: str,
    db_path: Path,
    *,
    panel_ind: pd.DataFrame | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    verify: bool = True,
) -> dict:
    """端到端回测 (backtrader 验证版)。"""
    p = get_preset(preset) if isinstance(preset, str) else preset
    if p["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(f"max_hold={p['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}")

    if panel_ind is None:
        universe = set(load_universe(p["universe"], db_path))
        panel = load_panel(db_path, start, end, universe=universe)
        panel_ind = compute_indicators(panel)
    else:
        panel = panel_ind[["thscode", "date", "open", "high", "low", "close", "volume", "amount"]]

    entries = select_entries(
        panel_ind,
        start_date=start, end_date=end,
        **p["signal"],
    )

    atr_tp = p.get("atr_tp_mult")
    atr_sl = p.get("atr_sl_mult")
    use_atr = atr_tp is not None and atr_sl is not None

    trades_p1, equity_p1 = simulate_portfolio(
        entries, panel_ind,
        tp_pct=p["tp_pct"], sl_pct=p["sl_pct"],
        max_hold=p["max_hold"], max_positions=p["max_positions"],
        start_date=start, end_date=end,
        initial_capital=initial_capital,
        atr_tp_mult=atr_tp, atr_sl_mult=atr_sl,
        position_sizing=p.get("position_sizing", "equal"),
        kelly_fraction=p.get("kelly_fraction"),
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System execution source。
        price_source_for_execution=p.get("price_source_for_execution", "adj_close"),
        # V8 (2026-09-22, CLAUDE.md §4): preset→strategy explicit plumbing。
        intraday_tiebreak=p.get("intraday_tiebreak", "sl_first"),
        max_volume_participation=p.get("max_volume_participation", 0.10),
    )

    if not verify or trades_p1.empty:
        metrics = compute_metrics(
            trades_p1, equity_p1,
            initial_capital=initial_capital, max_hold=p["max_hold"],
        )
        metrics.update({"start": start, "end": end, "signals": int(len(entries))})
        if isinstance(preset, str):
            metrics["preset"] = preset
        return {"metrics": metrics, "trades": trades_p1, "equity": equity_p1}

    max_hold = p["max_hold"]

    panel_idx = (
        panel.set_index(["thscode", "date"]).sort_index()
        if "thscode" in panel.columns else panel_ind
    )

    new_rows: list[dict] = []
    equity = equity_p1.set_index("date") if not equity_p1.empty else None
    equity_delta = 0.0

    for _, t in trades_p1.iterrows():
        entry_price = float(t["entry_price"])
        size = int(t["size"])
        if size <= 0:
            new_rows.append(t.to_dict())
            continue
        atr_pct_trade = float(t.get("atr_pct", np.nan)) if "atr_pct" in trades_p1.columns else np.nan
        tp_p, sl_p = compute_trade_tp_sl(
            entry_price,
            fixed_tp_pct=p["tp_pct"],
            fixed_sl_pct=p["sl_pct"],
            atr_pct=atr_pct_trade,
            atr_tp_mult=atr_tp if use_atr else None,
            atr_sl_mult=atr_sl if use_atr else None,
        )

        net_pnl_bt, exit_px_bt, exit_date_bt = _verify_trade_with_backtrader(
            panel, t["thscode"], pd.Timestamp(t["entry_date"]),
            entry_price, size, tp_p, sl_p, max_hold,
            # V3a+ (2026-09-22, CLAUDE.md §3): feed 必须与 portfolio.py Phase 1
            # 同价格域, 否则 backtrader strategy 跑在 qfq 域 → phantom SL/TP
            # (audit 揭露 v3 backtrader output: 4/59 SL phantom, exit_px ≈ qfq_open)。
            price_source_for_execution=p.get("price_source_for_execution", "adj_close"),
        )
        phase1_pnl = float(t["net_pnl"])
        if exit_date_bt is None and exit_px_bt == entry_price:
            net_pnl_bt = phase1_pnl
        gross_pnl = (exit_px_bt - entry_price) * size
        fees = gross_pnl - net_pnl_bt
        invested = entry_price * size
        net_return = net_pnl_bt / invested if invested > 0 else 0.0
        if exit_date_bt is not None:
            actual_exit_date = exit_date_bt
            entry_ts = pd.Timestamp(t["entry_date"])
            actual_hold_days = max(int((actual_exit_date - entry_ts).days), 1)
        else:
            actual_exit_date = t["exit_date"]
            actual_hold_days = int(t["hold_days"])

        new_rows.append({
            "entry_date": t["entry_date"],
            "exit_date": actual_exit_date,
            "thscode": t["thscode"],
            "exit_reason": t["exit_reason"],
            "entry_price": entry_price,
            "exit_price": float(exit_px_bt),
            "size": size,
            "hold_days": actual_hold_days,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl_bt,
            "net_return": net_return,
            "atr_pct": float(t.get("atr_pct", np.nan)) if "atr_pct" in trades_p1.columns else np.nan,
            "sub_signal_type": t.get("sub_signal_type", ""),
        })
        equity_delta += net_pnl_bt - float(t["net_pnl"])

    trades_p2 = pd.DataFrame(new_rows, columns=TRADE_COLS) if new_rows else trades_p1.iloc[:0].copy()
    # 修正 Bug B:旧实现把 equity_delta 均匀加到 equity_p1 每一行(含 row 0),
    # 会让 phase-2 day0 cash = initial_capital + total_delta (= 错误起始现金),
    # 并把 peak 拉低,让 max_dd 虚高。
    # 正确做法:把每笔 phase-2 修正 (p2_pnl - p1_pnl) 在该笔实际 exit_date
    # 起向前填充。day0 cash = initial_capital 不变。
    if equity is not None and equity_delta != 0.0 and len(equity_p1) > 0 and len(trades_p2) > 0:
        equity_p2 = equity_p1.copy()
        # 收集每笔 (exit_date, cumulative_delta),按日期累计
        deltas_by_exit: dict[pd.Timestamp, float] = {}
        cumulative = 0.0
        # 按 phase-1 顺序遍历 trades_p1,与上一步累加逻辑一致
        p1_pnl_map = trades_p1.set_index(
            [trades_p1["thscode"], trades_p1["entry_date"]]
        )["net_pnl"].to_dict()
        for row in new_rows:
            key = (row["thscode"], row["entry_date"])
            p1_pnl = float(p1_pnl_map.get(key, 0.0))
            cumulative += float(row["net_pnl"]) - p1_pnl
            ed = pd.Timestamp(row["exit_date"])
            deltas_by_exit[ed] = deltas_by_exit.get(ed, 0.0) + cumulative
        # 把累计 delta 按 exit_date 前向填充到 cash / equity
        running_delta = 0.0
        delta_events = sorted(deltas_by_exit.items())
        event_iter = iter(delta_events)
        next_event = next(event_iter, None)
        cash_arr = equity_p2["cash"].to_numpy(dtype=float).copy()
        eq_arr = equity_p2["equity"].to_numpy(dtype=float).copy()
        for i, d in enumerate(equity_p2["date"].tolist()):
            d_ts = pd.Timestamp(d)
            while next_event is not None and d_ts >= next_event[0]:
                running_delta = next_event[1]
                try:
                    next_event = next(event_iter)
                except StopIteration:
                    next_event = None
            if running_delta != 0.0:
                cash_arr[i] = cash_arr[i] + running_delta
                eq_arr[i] = eq_arr[i] + running_delta
        equity_p2 = equity_p2.copy()
        equity_p2["cash"] = cash_arr
        equity_p2["equity"] = eq_arr
    else:
        equity_p2 = equity_p1

    metrics = compute_metrics(
        trades_p2, equity_p2,
        initial_capital=initial_capital, max_hold=p["max_hold"],
    )
    metrics.update({"start": start, "end": end, "signals": int(len(entries))})
    if isinstance(preset, str):
        metrics["preset"] = preset
    return {"metrics": metrics, "trades": trades_p2, "equity": equity_p2}