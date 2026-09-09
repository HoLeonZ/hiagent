"""主回测入口 — 两阶段：Phase 1 trades → Phase 2 backtrader。"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import backtrader as bt
import duckdb
import numpy as np
import pandas as pd

from short_reversal.replay_broker import AShareBroker
from short_reversal.replay_feed import build_synthetic_feed
from short_reversal.presets import get_preset
from short_reversal.signals import compute_panel_indicators, select_entries
from short_reversal.replay_strategy import TradeReplayStrategy
from short_reversal.trades import pre_simulate_trades
from short_reversal.universe import load_universe

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb")
INITIAL_CAPITAL = 1_000_000.0
MARGIN_RATE = 0.086
COMMISSION_RATE = 0.0006  # 万 0.6 双边
STAMP_DUTY_RATE = 0.001  # 万 1 单边（仅卖出方向：开空 = 卖）


def run_backtest(preset: str, start: str, end: str, db_path: Path) -> dict:
    p = get_preset(preset)
    universe = set(load_universe(p["universe"], db_path))

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        panel = con.execute(
            "SELECT thscode, date, open, high, low, close, turnover, volume FROM v_daily "
            "WHERE date BETWEEN ? AND ? ORDER BY thscode, date",
            [start, (pd.Timestamp(end) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")],
        ).fetchdf()
    finally:
        con.close()

    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["thscode"].isin(universe)].reset_index(drop=True)

    panel_ind = compute_panel_indicators(panel)
    entries = select_entries(
        panel_ind, tp_pct=p["tp_pct"], start_date=start, end_date=end,
        pct_chg_low=p.get("pct_chg_low", 0.02),
        pct_chg_high=p.get("pct_chg_high", 0.06),
    )
    trades_df = pre_simulate_trades(
        entries, panel,
        tp_pct=p["tp_pct"], sl_pct=p["sl_pct"], max_hold=p["max_hold"],
    )

    # Phase 2: backtrader 复盘
    feed_df = build_synthetic_feed(trades_df, panel)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(
        TradeReplayStrategy,
        trades_df=trades_df,
        margin_rate=MARGIN_RATE,
        initial_capital=INITIAL_CAPITAL,
        position_fraction=1.0,
    )
    cerebro.broker = AShareBroker(commission=0.0006, stamp_duty=0.001)
    cerebro.broker.setcash(INITIAL_CAPITAL)
    data = bt.feeds.PandasData(dataname=feed_df)
    cerebro.adddata(data)
    results = cerebro.run()
    final_capital = cerebro.broker.getvalue()

    metrics = _compute_metrics(trades_df, start, end)
    metrics["broker_final_value"] = final_capital  # 留作 backtrader 复盘验证用
    metrics["preset"] = preset
    metrics["start"] = start
    metrics["end"] = end
    trades_df = trades_df.assign(entry_date=trades_df["entry_date"].astype(str), exit_date=trades_df["exit_date"].astype(str))
    metrics["trades"] = trades_df.to_dict(orient="records")
    return metrics


def _compute_metrics(trades_df: pd.DataFrame, start: str, end: str) -> dict:
    """基于 trades 层计算指标，复利用 fixed fractional（每笔占用全 cash）。

    每笔净 pnl = 裸价差 - 真实成本
      真实成本 = 双边 commission + 单边 stamp_duty (仅开空) + 融券日费 × hold_days
    复利模型：每笔占用全 cash（即 position_fraction=1.0），cash *= (1 + net_pnl)

    注：Phase 2 backtrader 复盘留作 OHLCV 时点验证（broker_final_value 字段），
    CAGR / total_yield / final_capital 来自 trades 层精确计算 — backtrader 成交价
    用 next-bar open，跟 trades.py 里 entry_price (T+1 open) / exit_price (TP/SL
    阈值) 存在时点偏差，不能直接拿 broker.getvalue() 作 CAGR。
    """
    if trades_df.empty:
        return {
            "trades": 0, "win_rate": 0.0, "final_capital": INITIAL_CAPITAL,
            "total_yield": 0.0, "cagr": 0.0, "sharpe": 0.0, "max_dd": 0.0,
            "avg_pnl": 0.0, "avg_hold_days": 0.0,
            "tp_count": 0, "sl_count": 0, "time_count": 0,
        }

    gross_pnls = []
    net_pnls = []
    for _, t in trades_df.iterrows():
        gross = (t["entry_price"] - t["exit_price"]) / t["entry_price"]
        # 真实成本（占 notional 比例）
        cost_rate = (
            COMMISSION_RATE * 2          # 双边佣金
            + STAMP_DUTY_RATE            # 单边印花税（开空 = 卖）
            + MARGIN_RATE * t["hold_days"] / 365  # 融券日费
        )
        net = gross - cost_rate
        gross_pnls.append(gross)
        net_pnls.append(net)

    n = len(net_pnls)
    wins = sum(1 for x in gross_pnls if x > 0)
    years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 0.5)

    # Fixed fractional 复利：每笔占用全 cash
    cash = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    max_dd = 0.0
    for net in net_pnls:
        cash *= (1 + net)
        if cash > peak:
            peak = cash
        dd = (peak - cash) / peak
        if dd > max_dd:
            max_dd = dd

    final_capital = cash
    total_yield = final_capital / INITIAL_CAPITAL - 1
    cagr = (final_capital / INITIAL_CAPITAL) ** (1 / years) - 1
    avg_pnl = float(np.mean(gross_pnls))
    std_pnl = float(np.std(gross_pnls, ddof=1)) if n > 1 else 0.0
    sharpe = (avg_pnl / std_pnl * math.sqrt(n)) if std_pnl > 0 else 0.0
    avg_hold = float(trades_df["hold_days"].mean())
    tp_n = int((trades_df["exit_reason"] == "TP").sum())
    sl_n = int((trades_df["exit_reason"] == "SL").sum())
    time_n = int((trades_df["exit_reason"] == "time").sum())
    return {
        "trades": n, "win_rate": wins / n,
        "final_capital": final_capital, "total_yield": total_yield,
        "cagr": cagr, "sharpe": sharpe, "max_dd": max_dd,
        "avg_pnl": avg_pnl, "avg_hold_days": avg_hold,
        "tp_count": tp_n, "sl_count": sl_n, "time_count": time_n,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="short_reversal 主回测入口")
    parser.add_argument("--preset", default="v33_mainboard")
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end", default="2026-09-01")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--out", default="short_reversal/results/backtest.json")
    args = parser.parse_args()

    metrics = run_backtest(args.preset, args.start, args.end, Path(args.db_path))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")

    print(f"preset: {metrics['preset']}")
    print(f"trades: {metrics['trades']}, win_rate: {metrics['win_rate']*100:.1f}%")
    print(f"final_capital: {metrics['final_capital']:.2f}, total_yield: {metrics['total_yield']*100:+.2f}%")
    print(f"sharpe: {metrics['sharpe']:.2f}")
    print(f"输出: {out}")


if __name__ == "__main__":
    main()
