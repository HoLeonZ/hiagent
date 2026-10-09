"""回测编排 + 绩效指标。

run_backtest — universe → panel → indicators → entries → portfolio → metrics
指标全部基于日频净值曲线计算（max_dd / Sharpe 用净值，不用逐笔）。
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.presets import MAX_HOLD_LIMIT, get_preset
from uptrend_pullback.regime import compute_regime
from uptrend_pullback.signals import compute_indicators, select_entries
from uptrend_pullback.universe import load_universe

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
    """由净值曲线与逐笔交易计算绩效指标。

    overrun_count 统计持仓超过 max_hold 的笔数——只可能由停牌导致
    （停牌日无法卖出，策略在复牌首日离场）。
    """
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

    # 日收益 → 年化 Sharpe（无风险利率取 0）
    rets = np.diff(eq) / eq[:-1] if n_days > 1 else np.array([0.0])
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
    sharpe = (float(np.mean(rets)) / std * math.sqrt(TRADING_DAYS)) if std > 0 else 0.0

    # 最大回撤
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.max((peak - eq) / peak)) if len(eq) else 0.0

    # 资金占用��
    exposure = float((equity_df["holdings"] / equity_df["equity"]).mean())

    if trades_df.empty:
        return {
            "trades": 0, "win_rate": 0.0, "final_equity": final_equity,
            "total_return": total_return, "cagr": cagr, "sharpe": sharpe,
            "max_dd": max_dd, "avg_hold_days": 0.0, "max_hold_days": 0,
            "overrun_count": 0,
            "tp_count": 0, "sl_count": 0, "time_count": 0, "eod_count": 0,
            "avg_net_return": 0.0, "profit_factor": 0.0, "exposure": exposure,
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
    regime_df: pd.DataFrame | None = None,
    initial_capital: float = INITIAL_CAPITAL,
) -> dict:
    """端到端回测。

    panel_ind / regime_df 可复用（网格搜索时避免重复算指标）。
    """
    p = get_preset(preset) if isinstance(preset, str) else preset
    if p["max_hold"] > MAX_HOLD_LIMIT:
        raise ValueError(f"max_hold={p['max_hold']} 超过硬约束 {MAX_HOLD_LIMIT}")

    if panel_ind is None:
        universe = set(load_universe(p["universe"], db_path, asof_date=start))
        panel = load_panel(db_path, start, end, universe=universe)
        panel_ind = compute_indicators(panel)

    reg = None
    if p.get("regime"):
        reg = regime_df if regime_df is not None else compute_regime(panel_ind, **p["regime"])

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

    trades_df, equity_df = simulate_portfolio(
        entries,
        panel_ind,
        tp_pct=p["tp_pct"],
        sl_pct=p["sl_pct"],
        max_hold=p["max_hold"],
        max_positions=p["max_positions"],
        start_date=start,
        end_date=end,
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
        # R7 (2026-10-09, CLAUDE.md §2): NAV-floor cash gate, 与 backtrader_engine.py:266 保持一致。
        # portfolio.py:148 文档化 Round 14 (2026-09-28) 引入,默认 0.05。
        nav_gate_ratio=p.get("nav_gate_ratio", 0.05),
        # R7 (2026-10-09, CLAUDE.md §0/§4): cost model plumbing, 与 backtrader_engine.py:255-259 保持一致。
        # Round 15 (2026-09-28) 在 portfolio.py:217-221 引入 ATR-aware slippage 与成本参数。
        # 当前 0/2 preset 声明这些 key, 函数默认 0.00025/0.0005/5.0/0.0/0.0 与 backtrader_engine.py p.get 默认完全一致 (R5/R6 同模式)。
        # 显式 plumb 防止未来 preset override 时两引擎 drift。
        commission_rate=p.get("commission_rate", 0.00025),
        stamp_duty_rate=p.get("stamp_duty_rate", 0.0005),
        min_commission=p.get("min_commission", 5.0),
        slippage=p.get("slippage", 0.0),
        atr_slip_scale=p.get("atr_slip_scale", 0.0),
    )

    metrics = compute_metrics(
        trades_df, equity_df, initial_capital=initial_capital, max_hold=p["max_hold"]
    )
    metrics.update({"start": start, "end": end, "signals": int(len(entries))})
    if isinstance(preset, str):
        metrics["preset"] = preset
    return {"metrics": metrics, "trades": trades_df, "equity": equity_df}
