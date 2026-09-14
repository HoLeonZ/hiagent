"""4 种仓位模式对比 — 用同一份 v6 信号，跑 4 种 sizing。

模式：
  equal_5    : V6 默认（max_positions=5, 等额 20%/只）
  all_in     : 单只满仓（max_positions=1, 100%/只）
  full_kelly : 单只按 Full Kelly（24.5%）
  half_kelly : 单只按 Half Kelly（12.2%）

Kelly 系数从 v6 79 笔实测计算：
  p=54.43%, avg_win=14.10%, avg_loss=9.28%
  b=W/L=1.52, Kelly=(bp-q)/b=24.46%
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from uptrend_pullback.backtest import compute_metrics
from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.presets import get_preset
from uptrend_pullback.regime import compute_regime
from uptrend_pullback.signals import compute_indicators, select_entries
from uptrend_pullback.universe import load_universe

START = "2025-09-12"
END = "2026-09-12"
DB_PATH = Path.home() / "code/Financial-API/data/market.duckdb"

# Kelly 实测（v6 79 笔）：
# p=54.43%, avg_win=14.10%, avg_loss=9.28%, b=W/L=1.52
# f* = (bp-q)/b = 0.2446
MODES = [
    ("equal_5 (默认)", dict(position_sizing="equal",  max_positions=5)),
    ("all_in (100%)", dict(position_sizing="all_in", max_positions=1)),
    ("full_kelly 24.5%", dict(position_sizing="kelly",  max_positions=1, kelly_fraction=0.245)),
    ("half_kelly 12.2%", dict(position_sizing="kelly",  max_positions=1, kelly_fraction=0.122)),
]


def main() -> None:
    t0 = time.time()
    p = get_preset("v6")

    # ---------- 一次性加载 + 计算 entries ----------
    print(f"加载 panel + 算 entries...", flush=True)
    universe = set(load_universe(p["universe"], DB_PATH))
    panel = load_panel(DB_PATH, START, END, universe=universe)
    panel_ind = compute_indicators(panel)
    reg = compute_regime(panel_ind, **p["regime"]) if p.get("regime") else None
    entries = select_entries(
        panel_ind, start_date=START, end_date=END,
        regime_df=reg, **p["signal"],
    )
    print(f"  panel: {len(panel)} 行, entries: {len(entries)} 个候选信号\n", flush=True)

    # ---------- 4 种 sizing 跑同一份 entries ----------
    rows = []
    for label, kwargs in MODES:
        t1 = time.time()
        trades, equity = simulate_portfolio(
            entries, panel_ind,
            tp_pct=p["tp_pct"], sl_pct=p["sl_pct"],
            max_hold=p["max_hold"],
            max_positions=kwargs["max_positions"],
            start_date=START, end_date=END,
            atr_tp_mult=p.get("atr_tp_mult"),
            atr_sl_mult=p.get("atr_sl_mult"),
            position_sizing=kwargs["position_sizing"],
            kelly_fraction=kwargs.get("kelly_fraction"),
        )
        m = compute_metrics(trades, equity, max_hold=p["max_hold"])
        m["preset"] = label
        m["elapsed_sec"] = round(time.time() - t1, 1)
        m["trades"] = int(m.get("trades", len(trades)))
        rows.append(m)

    # ---------- 输出对比表 ----------
    print("=" * 100)
    print(f"V6 仓位模式对比 | {START} → {END} (12 个月)")
    print("=" * 100)
    hdr = (
        f"{'mode':18s} | {'CAGR%':>8s} | {'Sharpe':>6s} | {'maxDD%':>7s} | "
        f"{'win%':>5s} | {'trades':>6s} | {'avgHold':>7s} | {'expo%':>6s} | {'PF':>5s}"
    )
    print(hdr)
    print("-" * 100)
    for m in rows:
        print(
            f"{m['preset']:18s} | {m.get('cagr', 0)*100:>+7.2f}% | "
            f"{m.get('sharpe', 0):>6.2f} | {m.get('max_dd', 0)*100:>6.2f}% | "
            f"{m.get('win_rate', 0)*100:>4.1f}% | {m['trades']:>6d} | "
            f"{m.get('avg_hold_days', 0):>6.1f}d | {m.get('exposure', 0)*100:>5.1f}% | "
            f"{m.get('profit_factor', 0):>5.2f}"
        )
    print("=" * 100)
    print(f"总耗时: {time.time()-t0:.1f}s（共享 entries，只跑 4 次 simulate_portfolio）")


if __name__ == "__main__":
    main()
