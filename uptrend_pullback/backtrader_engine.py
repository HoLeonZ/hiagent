"""backtrader 回测引擎 — Phase 1 (候选) + Phase 2 (backtrader 验证)。

架构：
  Phase 1：portfolio.py:simulate_portfolio 决定 slot 分配、entry/exit 时机与价格
  Phase 2：对 Phase 1 产生的每一笔 trade，独立跑一次 backtrader 实例，
           让 AStockBroker + AStockCommInfo 真实承担佣金/印花税/现金流记账。

每笔 backtrader run：
  - feed 起始 = signal_date 前一根 K 线 → bar 1 = entry_date，买单在 bar 1 开盘成交
  - 策略 UpullbackTradeReplay 按 OHLC 优先级判 TP/SL/time，记 target_exit_price
  - net_pnl 直接读 broker 状态：final_cash - initial_cash

为什么两阶段而非单阶段：
  backtrader 的天然模型是 per-feed-per-stock，~5000 只股票的多仓位组合 +
  ATR 自适应止损 + 仓位抢占 用单 cerebro 难以表达。两阶段用 portfolio.py 的
  成熟算法做决策（已与 v6 目标年 +86.66% 对齐），用 backtrader 做执行验证，
  既满足"必须使用 backtrader"的硬约束，又保留 portfolio.py 的速度与可读性。

与 portfolio.py 的差异：
  - commission / stamp_duty 由 backtrader AStockCommInfo 算出（带最低 ¥5）
  - 净 PnL = backtrader final_cash - initial_cash（地真值）
  - gross_pnl 与 fees 由 trade 数据反推（fees = gross - net）
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from uptrend_pullback.backtest import INITIAL_CAPITAL, compute_metrics
from uptrend_pullback.portfolio import TRADE_COLS, simulate_portfolio
from uptrend_pullback.presets import MAX_HOLD_LIMIT, get_preset
from uptrend_pullback.replay_broker import AStockBroker
from uptrend_pullback.replay_strategy import UpullbackTradeReplay

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
    """由信号日 atr_pct 计算 TP/SL 宽度。

    与 portfolio.py:simulate_portfolio 完全一致：
      - 默认用 fixed_tp_pct / fixed_sl_pct
      - 若给了 atr_*_mult，则按信号日 ATR% 自适应：
        tp = entry_price × (1 + a × atr_tp_mult)
        sl = entry_price × (1 - a × atr_sl_mult)
      - atr_pct 先夹到 [floor, cap]

    为什么是「信号日 ATR」：
      signals.py 在 T 日收盘时算 atr_pct（T 的 high/low/close 此时已知）。
      T+1 开盘时 atr_pct 已可用，但 T+1 的 high/low 还没发生。
      用 entry_date(T+1) 当根的 atr_pct 会引入 1 根 bar 的 look-ahead。
    """
    if atr_tp_mult is not None and atr_sl_mult is not None and atr_pct is not None \
            and not (isinstance(atr_pct, float) and math.isnan(atr_pct)):
        a = min(max(float(atr_pct), atr_pct_floor), atr_pct_cap)
        return entry_price * (1 + a * atr_tp_mult), entry_price * (1 - a * atr_sl_mult)
    return entry_price * (1 + fixed_tp_pct), entry_price * (1 - fixed_sl_pct)


def _verify_trade_with_backtrader(
    panel: pd.DataFrame,
    thscode: str,
    entry_date: pd.Timestamp,
    entry_price: float,
    target_size: int,
    tp_price: float,
    sl_price: float,
    max_hold: int,
) -> tuple[float, float, pd.Timestamp | None]:
    """对单笔交易跑 backtrader，返回 (net_pnl, exit_price_actual, exit_date_actual)。

    若 backtrader 因数据不足或被策略 skip 而未真正下单，
    返回 (0.0, entry_price, None)。

    exit_price_actual 取自 strategy.actual_exit_price（notify_order 在卖出单
    成交时回填的真实成交价，即 bar N+1 OPEN），与 net_pnl 的口径完全一致。
    exit_date_actual 取自 strategy.actual_exit_date（bar N+1 的 date），
    用于把 trades.exit_date 从"决策日"回填为"实际成交日"，消除 1 天口径差。
    若订单已提交但 feed 跑完仍未成交（极少见，给的 max_hold+5 buffer 不够），
    则退回到 target_exit_price 并记 warning。
    """
    code_data = panel[panel["thscode"] == thscode].sort_values("date")
    if code_data.empty:
        return 0.0, entry_price, None

    # feed 起始 = entry_date 前一根 K 线（保证 bar 1 = entry_date）
    future = code_data[code_data["date"] < entry_date].tail(1)
    if future.empty:
        return 0.0, entry_price, None
    feed_start = pd.Timestamp(future.iloc[0]["date"])
    span = code_data[code_data["date"] >= feed_start].head(max_hold + 5)
    if span.empty:
        return 0.0, entry_price, None
    feed_df = span[["date", "open", "high", "low", "close", "volume"]].copy()
    feed_df["date"] = pd.to_datetime(feed_df["date"])
    feed_df = feed_df.set_index("date").sort_index().astype(float)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed_df))
    # initial_cash 必须仅覆盖「买入本金 + 佣金缓冲」。若给 ×2 冗余，
    # 一旦 sell 在 feed 耗尽时未成交（warning 路径），broker 不会回补卖出款，
    # final_cash = initial_cash - buy_notional，导致 -notional 的虚假亏损被
    # 当作真实 PnL 上报，触发 equity_delta 累计爆炸（实测一次 -918k delta）。
    initial_cash = max(target_size * entry_price * 1.0025, 100_000.0)
    cerebro.broker = AStockBroker()
    cerebro.broker.set_cash(initial_cash)
    cerebro.addstrategy(
        UpullbackTradeReplay,
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

    # 优先用实际成交价（bar N+1 OPEN），保证 exit_price 与 net_pnl 口径一致
    if strat.actual_exit_price is not None:
        actual_exit = float(strat.actual_exit_price)
        actual_exit_date = strat.actual_exit_date
        net_pnl = final_cash - initial_cash
    else:
        # 订单已提交但 feed 耗尽未成交（max_hold+5 buffer 不够）：
        # broker 此时已扣买入本金但未收到卖出款，final_cash ≈ initial_cash - notional。
        # 这种情况下 net_pnl 视作 0（成交未发生，不计入已实现盈亏），
        # 改用 Phase 1 的 exit_price/exit_date/n_pnl 作为口径兜底。
        logger.warning(
            "_verify_trade_with_backtrader: thscode=%s exit_reason=%s 但订单未成交 "
            "（feed 长度不足），actual_exit 退回 entry_price，net_pnl 兜底为 0",
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
    regime_df: pd.DataFrame | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    verify: bool = True,
    position_sizing: str = "equal",
    kelly_fraction: float | None = None,
    max_positions: int | None = None,
) -> dict:
    """端到端回测（backtrader 验证版）。

    verify=True（默认）：对 Phase 1 产生的每笔 trade 跑 backtrader，用 backtrader
                        返回的 net_pnl / exit_price 覆盖 Phase 1 的值。
    verify=False     ：直接返回 Phase 1（portfolio.py）的结果，跳过 backtrader。
    """
    p = get_preset(preset) if isinstance(preset, str) else preset
    if p["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(f"max_hold={p['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}")

    # ---------- Phase 1: portfolio.py 跑出候选 trade 列表 ----------
    from uptrend_pullback.data import load_panel
    from uptrend_pullback.regime import compute_regime
    from uptrend_pullback.signals import compute_indicators, select_entries
    from uptrend_pullback.universe import load_universe

    if panel_ind is None:
        universe = set(load_universe(p["universe"], db_path))
        panel = load_panel(db_path, start, end, universe=universe)
        panel_ind = compute_indicators(panel)
    else:
        panel = panel_ind[["thscode", "date", "open", "high", "low", "close", "volume", "amount"]]

    reg = None
    if p.get("regime"):
        reg = regime_df if regime_df is not None else compute_regime(panel_ind, **p["regime"])

    # 路由: entry_mode == "v33_long_mirror" → 走镜像信号选择器
    if p["signal"].get("entry_mode") == "v33_long_mirror":
        from uptrend_pullback.signals import select_entries_v33_long_mirror
        sig_kwargs = {k: v for k, v in p["signal"].items() if k != "entry_mode"}
        entries = select_entries_v33_long_mirror(
            panel_ind, start_date=start, end_date=end, regime_df=reg, **sig_kwargs
        )
    else:
        entries = select_entries(
            panel_ind, start_date=start, end_date=end, regime_df=reg, **p["signal"]
        )

    trades_p1, equity_p1 = simulate_portfolio(
        entries,
        panel_ind,
        tp_pct=p["tp_pct"],
        sl_pct=p["sl_pct"],
        max_hold=p["max_hold"],
        max_positions=max_positions if max_positions is not None else p["max_positions"],
        start_date=start,
        end_date=end,
        initial_capital=initial_capital,
        atr_tp_mult=p.get("atr_tp_mult"),
        atr_sl_mult=p.get("atr_sl_mult"),
        position_sizing=position_sizing,
        kelly_fraction=kelly_fraction,
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System execution source。
        price_source_for_execution=p.get("price_source_for_execution", "adj_close"),
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

    # ---------- Phase 2: 每笔 trade 用 backtrader 验证 ----------
    max_hold = p["max_hold"]
    atr_tp = p.get("atr_tp_mult")
    atr_sl = p.get("atr_sl_mult")
    use_atr = atr_tp is not None and atr_sl is not None

    panel_idx = (
        panel.set_index(["thscode", "date"]).sort_index()
        if "thscode" in panel.columns else panel_ind
    )

    new_rows: list[dict] = []
    equity = equity_p1.set_index("date") if not equity_p1.empty else None
    equity_delta = 0.0  # sum(net_pnl_p2 - net_pnl_p1)，用于修正 equity 曲线

    for _, t in trades_p1.iterrows():
        entry_price = float(t["entry_price"])
        size = int(t["size"])
        if size <= 0:
            new_rows.append(t.to_dict())
            continue
        # 用 compute_trade_tp_sl 取 tp/sl 宽度 —— 单点修复，去掉"读 entry_date atr_pct"的穿越路径
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
        )
        phase1_pnl = float(t["net_pnl"])
        # warning 路径（exit_px == entry_price 且 exit_date is None）意味着 backtrader
        # 没真正成交，net_pnl_bt 已被函数兜底为 0；但 equity_delta 不能因此把
        # Phase 1 的真实盈亏从曲线里扣掉，否则 equity_p2 会突然塌陷。用 Phase 1
        # 的 net_pnl 兜底，gross/fees 全部按 Phase 1 的口径重算，保持自洽。
        if exit_date_bt is None and exit_px_bt == entry_price:
            net_pnl_bt = phase1_pnl
        gross_pnl = (exit_px_bt - entry_price) * size
        fees = gross_pnl - net_pnl_bt
        invested = entry_price * size
        net_return = net_pnl_bt / invested if invested > 0 else 0.0
        # 用 backtrader 实际成交日回填 exit_date (消除 "决策日 vs 成交日" 1 天口径差),
        # 若 verify 退回 entry_price (即 actual_exit_price is None) 则保留 Phase 1 的 exit_date。
        if exit_date_bt is not None:
            actual_exit_date = exit_date_bt
            # 按 exit_date 与 entry_date 之间日历天数重算 hold_days
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
        })
        equity_delta += net_pnl_bt - float(t["net_pnl"])

    trades_p2 = pd.DataFrame(new_rows, columns=TRADE_COLS) if new_rows else trades_p1.iloc[:0].copy()
    if equity is not None and equity_delta != 0.0:
        equity_p2 = equity_p1.copy()
        equity_p2["equity"] = equity_p2["equity"] + equity_delta
        equity_p2["cash"] = equity_p2["cash"] + equity_delta
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
