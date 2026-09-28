"""回测编排 + 绩效指标 (沿用 uptrend_pullback/backtest.py 口径)。"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from chase_up.data import load_panel
from chase_up.portfolio import simulate_portfolio
from chase_up.presets import MAX_HOLD_LIMIT, get_preset
from chase_up.signals import compute_indicators, select_entries
from chase_up.universe import load_universe

logger = logging.getLogger(__name__)

INITIAL_CAPITAL = 1_000_000.0
TRADING_DAYS = 243


def compute_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    *,
    initial_capital: float = INITIAL_CAPITAL,
    max_hold: int = MAX_HOLD_LIMIT,
) -> dict:
    """由净值曲线与逐笔交易计算绩效指标。"""
    if equity_df.empty:
        return {
            "trades": 0, "win_rate": 0.0, "final_equity": initial_capital,
            "total_return": 0.0, "cagr": 0.0, "sharpe": 0.0, "max_dd": 0.0,
            "avg_hold_days": 0.0, "max_hold_days": 0, "overrun_count": 0,
            "tp_count": 0, "sl_count": 0, "time_count": 0, "eod_count": 0,
            "avg_net_return": 0.0, "profit_factor": 0.0, "exposure": 0.0,
        }

    eq = equity_df["equity"].to_numpy(dtype=float)
    final_equity = float(eq[-1])
    total_return = final_equity / initial_capital - 1.0

    n_days = len(eq)
    years = max(n_days / TRADING_DAYS, 1e-9)
    cagr = (final_equity / initial_capital) ** (1 / years) - 1 if final_equity > 0 else -1.0

    rets = np.diff(eq) / eq[:-1] if n_days > 1 else np.array([0.0])
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (float(np.mean(rets)) / std * math.sqrt(TRADING_DAYS)) if std > 0 else 0.0

    peak = np.maximum.accumulate(eq)
    max_dd = float(np.max((peak - eq) / peak)) if len(eq) else 0.0
    exposure = float((equity_df["holdings"] / equity_df["equity"]).mean())

    if trades_df.empty:
        return {
            "trades": 0, "win_rate": 0.0, "final_equity": final_equity,
            "total_return": total_return, "cagr": cagr, "sharpe": sharpe,
            "max_dd": max_dd, "avg_hold_days": 0.0, "max_hold_days": 0,
            "overrun_count": 0,
            "tp_count": 0, "sl_count": 0, "time_count": 0, "eod_count": 0,
            "avg_net_return": 0.0, "profit_factor": float("inf"), "exposure": exposure,
        }

    net = trades_df["net_pnl"].to_numpy(dtype=float)
    wins = net[net > 0]
    losses = net[net < 0]
    profit_factor = (
        float(wins.sum() / abs(losses.sum())) if losses.size and losses.sum() != 0 else float("inf")
    )

    return {
        "trades": int(len(trades_df)),
        "win_rate": float((net > 0).mean()),
        "final_equity": final_equity,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "avg_hold_days": float(trades_df["hold_days"].mean()),
        "max_hold_days": int(trades_df["hold_days"].max()),
        "overrun_count": int((trades_df["hold_days"] > max_hold).sum()),
        "tp_count": int((trades_df["exit_reason"] == "TP").sum()),
        "sl_count": int((trades_df["exit_reason"] == "SL").sum()),
        "time_count": int((trades_df["exit_reason"] == "time").sum()),
        "eod_count": int((trades_df["exit_reason"] == "eod").sum()),
        "avg_net_return": float(trades_df["net_return"].mean()),
        "profit_factor": profit_factor,
        "exposure": exposure,
    }


def run_backtest(
    preset: str | dict,
    start: str,
    end: str,
    db_path: Path,
    *,
    panel_ind: pd.DataFrame | None = None,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    """端到端回测 (Phase 1: pandas 自循环)。"""
    p = get_preset(preset) if isinstance(preset, str) else preset
    if p["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(f"max_hold={p['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}")

    if panel_ind is None:
        universe = set(load_universe(p["universe"], db_path, asof_date=start))
        panel = load_panel(db_path, start, end, universe=universe)
        panel_ind = compute_indicators(panel)

    sig_kwargs = dict(p["signal"])
    entries = select_entries(
        panel_ind,
        start_date=start, end_date=end,
        **sig_kwargs,
    )

    trades_df, equity_df = simulate_portfolio(
        entries, panel_ind,
        tp_pct=p["tp_pct"], sl_pct=p["sl_pct"],
        max_hold=p["max_hold"], max_positions=p["max_positions"],
        start_date=start, end_date=end,
        initial_capital=initial_capital,
        atr_tp_mult=p.get("atr_tp_mult"),
        atr_sl_mult=p.get("atr_sl_mult"),
        position_sizing=p.get("position_sizing", "equal"),
        kelly_fraction=p.get("kelly_fraction"),
        # V3a (2026-09-22, CLAUDE.md §3): Dual-Price System execution source。
        price_source_for_execution=p.get("price_source_for_execution", "adj_close"),
        # V8 (2026-09-22, CLAUDE.md §4): preset→strategy explicit plumbing。
        intraday_tiebreak=p.get("intraday_tiebreak", "sl_first"),
        max_volume_participation=p.get("max_volume_participation", 0.10),
    )

    metrics = compute_metrics(
        trades_df, equity_df, initial_capital=initial_capital, max_hold=p["max_hold"]
    )
    metrics.update({"start": start, "end": end, "signals": int(len(entries))})
    if isinstance(preset, str):
        metrics["preset"] = preset
    return {"metrics": metrics, "trades": trades_df, "equity": equity_df}