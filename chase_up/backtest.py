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

from core.dual_price import (  # §2 单源 (audit P2-11, 2026-10-15)
    resolve_atr_slip_scale,
    COMMISSION_RATE,
    MIN_COMMISSION,
    STAMP_DUTY_RATE,
)
from core.trade_schema import TRADING_DAYS_PER_YEAR  # §2 单源 (audit 2026-10-15)

logger = logging.getLogger(__name__)

INITIAL_CAPITAL = 1_000_000.0
#: 年化口径单源 —— 见 core.trade_schema.TRADING_DAYS_PER_YEAR 的说明
#: (日历日 vs 交易日会让同一窗口的 CAGR 差 8%~26%)。此处保留旧名以兼容调用方。
TRADING_DAYS = TRADING_DAYS_PER_YEAR


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
        # §5 (audit 2026-10-16): 观察数**随产物发布**。DSR 的 `n_returns` 参数是
        # "Sharpe 用了多少个收益观测"(T = len(eq) - 1,因为 rets = diff(eq)),
        # 而此前各 sweep 只能把这个数**硬编码**(多处写 252),窗口实际只有
        # 242~243 个交易日 ⇒ T 被高估约 4%,标准误被低估约 2%,DSR 系统性偏乐观。
        # 与 short_reversal 的 `n_trading_days` 是**两个量**:那个是"窗口有多少个
        # 交易日"(用于年化),这个是"有多少个收益观测"(用于标准误),差一个观测。
        "n_daily_returns": int(max(len(eq) - 1, 0)),
            "total_return": total_return, "cagr": cagr, "sharpe": sharpe,
            # §2 (audit 2026-10-15): sharpe 的定义随产物发布 —— 与 short_reversal
            # 的 `sharpe` 不是同一个量(那个是逐笔比率的近似)。
            "sharpe_kind": "daily_returns_annualized",
            "max_dd": max_dd, "avg_hold_days": 0.0, "max_hold_days": 0,
            "overrun_count": 0,
            "tp_count": 0, "sl_count": 0, "time_count": 0, "eod_count": 0,
            "avg_net_return": 0.0, "profit_factor": None, "exposure": exposure,
        }

    net = trades_df["net_pnl"].to_numpy(dtype=float)
    wins = net[net > 0]
    losses = net[net < 0]
    # §0/§7 (audit 2026-10-15): 无亏损笔数时 `profit_factor` **无定义**(分母 0),
    # 返回 None 而不是 `float("inf")` —— Python 的 `json.dumps(inf)` 会写出
    # `Infinity`,那不是 RFC 8259 的合法值:除 Python 自己的宽松 `json.loads`
    # (正因它能读回来,这个缺陷一直没被发现)之外,JS / Go / Rust / jq 一律拒绝。
    # 于是 `results/backtest.json` 在"全胜窗口"下是**非法 JSON**。None 既合法,
    # 也与本仓库既有的"算不出就 None"口径一致(max_dd=None / cagr=None / beta=None)。
    profit_factor = (
        float(wins.sum() / abs(losses.sum()))
        if losses.size and losses.sum() != 0
        else None
    )

    return {
        "trades": int(len(trades_df)),
        "win_rate": float((net > 0).mean()),
        "final_equity": final_equity,
        # §5 (audit 2026-10-16): 观察数**随产物发布**。DSR 的 `n_returns` 参数是
        # "Sharpe 用了多少个收益观测"(T = len(eq) - 1,因为 rets = diff(eq)),
        # 而此前各 sweep 只能把这个数**硬编码**(多处写 252),窗口实际只有
        # 242~243 个交易日 ⇒ T 被高估约 4%,标准误被低估约 2%,DSR 系统性偏乐观。
        # 与 short_reversal 的 `n_trading_days` 是**两个量**:那个是"窗口有多少个
        # 交易日"(用于年化),这个是"有多少个收益观测"(用于标准误),差一个观测。
        "n_daily_returns": int(max(len(eq) - 1, 0)),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "sharpe_kind": "daily_returns_annualized",  # §2 (audit 2026-10-15): 日收益序列的 Sharpe(mean/std × √243)。与 short_reversal 的 `sharpe` **不是**同一个量
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
        # R5 (2026-10-09, CLAUDE.md §2): NAV-floor cash gate, 与 backtrader_engine.py:223 保持一致。
        # portfolio.py:175-189 文档化 Round 14 (2026-09-28) 引入,默认 0.05。
        nav_gate_ratio=p.get("nav_gate_ratio", 0.05),
        # R6 (2026-10-09, CLAUDE.md §0/§4): cost model plumbing, 与 backtrader_engine.py:212-216 保持一致。
        # Round 15 (2026-09-28) 在 portfolio.py:247-254 引入 ATR-aware slippage 与成本参数。
        # 当前 0/22 preset 声明这些 key, 函数默认 0.00025/0.0005/5.0/0.0/0.0 与 backtrader_engine.py p.get 默认完全一致 (R5 nav_gate_ratio 同模式)。
        # 显式 plumb 防止未来 preset override 时两引擎 drift。
        commission_rate=p.get("commission_rate", COMMISSION_RATE),
        stamp_duty_rate=p.get("stamp_duty_rate", STAMP_DUTY_RATE),
        min_commission=p.get("min_commission", MIN_COMMISSION),
        slippage=p.get("slippage", 0.0),
        atr_slip_scale=resolve_atr_slip_scale(p, p.get("_name", "chase_up")),
    )

    metrics = compute_metrics(
        trades_df, equity_df, initial_capital=initial_capital, max_hold=p["max_hold"]
    )
    metrics.update({"start": start, "end": end, "signals": int(len(entries))})
    if isinstance(preset, str):
        metrics["preset"] = preset
    return {"metrics": metrics, "trades": trades_df, "equity": equity_df}