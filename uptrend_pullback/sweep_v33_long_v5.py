"""v5 - 在 v33_long_reverse 最优点附近精扫,找 Pareto front。

目标 (v33_long_reverse 基准):
  CAGR 280.27% | Sharpe 2.704 | DD 34.27% | Win 38.60% | PF 1.629 | Trades 57

优化方向:
  - 信号收紧 (min_above_ma60_ratio↑): Win rate↑ / PF↑
  - max_hold↓ (10 vs 15): DD↓ (砍 stale 单)
  - sl_pct↓ (0.015-0.02): DD↓
  - tp_pct↑ (0.30-0.40): 单笔胜率不变下,赢更多

维度:
  signal.min_above_ma60_ratio: [0.5, 0.55, 0.6, 0.65, 0.7]   (5)
  signal.min_down_streak:        [3, 4]                          (2)
  max_hold:                     [8, 10, 12]                     (3)
  tp_pct:                       [0.25, 0.30, 0.40]              (3)
  sl_pct:                       [0.015, 0.02]                   (2)

总数: 5 × 2 × 3 × 3 × 2 = 180 组合
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
from copy import deepcopy
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.backtest import compute_metrics
from uptrend_pullback.data import load_panel
from uptrend_pullback.portfolio import simulate_portfolio
from uptrend_pullback.signals import compute_indicators, select_entries_v33_long_mirror
from dna_stats.deflated import deflated_sharpe_ratio
from uptrend_pullback.universe import load_universe

START, END = "2025-09-16", "2026-09-16"


def _set(cfg: dict, path: str, val) -> None:
    if "." in path:
        head, tail = path.split(".", 1)
        cfg.setdefault(head, {})[tail] = val
    else:
        cfg[path] = val


def sweep(base: dict, grid: dict, panel_ind) -> pd.DataFrame:
    keys = sorted(grid)
    combos = [dict(zip(keys, vals))
              for vals in itertools.product(*(grid[k] for k in keys))]
    rows = []
    for combo in combos:
        cfg = deepcopy(base)
        for k, v in combo.items():
            _set(cfg, k, v)

        sig_kwargs = {k: v for k, v in cfg["signal"].items() if k != "entry_mode"}
        entries = select_entries_v33_long_mirror(
            panel_ind,
            start_date=START, end_date=END,
            regime_df=None,
            **sig_kwargs,
        )
        if entries.empty:
            continue

        kwargs = dict(
            tp_pct=max(cfg["tp_pct"], 0.0001),
            sl_pct=max(cfg["sl_pct"], 0.0001),
            max_hold=cfg["max_hold"],
            max_positions=cfg["max_positions"],
            start_date=START, end_date=END,
        )
        ps = cfg.get("position_sizing", "equal")
        if ps != "equal":
            kwargs["position_sizing"] = ps

        trades, equity = simulate_portfolio(entries, panel_ind, **kwargs)
        m = compute_metrics(trades, equity, max_hold=cfg["max_hold"])
        rows.append({**combo, **m, "signals": int(len(entries))})

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        "cagr", ascending=False
    ).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)

    print(f"[load] {START} .. {END}")
    base = {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.02,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.05,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.5,
        },
    }

    universe = set(load_universe(base["universe"], Path(args.db_path)))
    panel = load_panel(Path(args.db_path), START, END, universe=universe)
    panel_ind = compute_indicators(panel)

    grid = {
        "signal.min_above_ma60_ratio": [0.5, 0.55, 0.6, 0.65, 0.7],
        "signal.min_down_streak":       [3, 4],
        "max_hold":                    [8, 10, 12],
        "tp_pct":                      [0.25, 0.30, 0.40],
        "sl_pct":                      [0.015, 0.02],
    }

    combos = list(itertools.product(*grid.values()))
    print(f"[sweep] {len(combos)} combos")
    df = sweep(base, grid, panel_ind)
    if df.empty:
        print("no signals")
        return

    # Pareto-front style ranking: 综合得分 = CAGR + Sharpe - DD
    # 不直接优化 Win rate (依赖分布),而是让 trade 数 ≥ 40 的进入候选
    df["score"] = df["cagr"] + df["sharpe"] - df["max_dd"]

    out = Path("uptrend_pullback/results/sweep_v33_long_v5.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        df.to_dict(orient="records"), indent=2, default=str,
    ))
    print(f"\n已保存: {out}")

    # 输出多个 view
    print("\n=== Top 30 by CAGR ===")
    show = df.head(args.top).copy()
    for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
              "avg_net_return", "exposure", "score"):
        if c in show.columns:
            if c in ("cagr", "win_rate", "max_dd", "total_return",
                     "avg_net_return", "exposure"):
                show[c] = (show[c] * 100).round(2)
            else:
                show[c] = show[c].round(2)
    cols = [c for c in (
        list(grid.keys()) + ["signals", "trades", "cagr", "win_rate",
                              "tp_count", "sl_count", "time_count",
                              "max_dd", "sharpe", "profit_factor",
                              "avg_hold_days", "score", "final_equity"]
    ) if c in show.columns]
    print(show[cols].to_string(index=False))

    print("\n=== Top 20 by Score (CAGR + Sharpe - DD, min 40 trades) ===")
    df_min = df[df["trades"] >= 40]
    show2 = df_min.sort_values("score", ascending=False).head(20).copy()
    for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
              "avg_net_return", "exposure", "score"):
        if c in show2.columns:
            if c in ("cagr", "win_rate", "max_dd", "total_return",
                     "avg_net_return", "exposure"):
                show2[c] = (show2[c] * 100).round(2)
            else:
                show2[c] = show2[c].round(2)
    print(show2[cols].to_string(index=False))

    print("\n=== Top 10 by DD (lowest), trades >= 40 ===")
    show3 = df_min.sort_values("max_dd", ascending=True).head(10).copy()
    for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
              "avg_net_return", "exposure", "score"):
        if c in show3.columns:
            if c in ("cagr", "win_rate", "max_dd", "total_return",
                     "avg_net_return", "exposure"):
                show3[c] = (show3[c] * 100).round(2)
            else:
                show3[c] = show3[c].round(2)
    print(show3[cols].to_string(index=False))

    print("\n=== Top 10 by Sharpe, trades >= 40 ===")
    show4 = df_min.sort_values("sharpe", ascending=False).head(10).copy()
    for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
              "avg_net_return", "exposure", "score"):
        if c in show4.columns:
            if c in ("cagr", "win_rate", "max_dd", "total_return",
                     "avg_net_return", "exposure"):
                show4[c] = (show4[c] * 100).round(2)
            else:
                show4[c] = show4[c].round(2)
    print(show4[cols].to_string(index=False))

    print("\n=== Top 10 by Profit Factor, trades >= 40 ===")
    show5 = df_min.sort_values("profit_factor", ascending=False).head(10).copy()
    for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
              "avg_net_return", "exposure", "score"):
        if c in show5.columns:
            if c in ("cagr", "win_rate", "max_dd", "total_return",
                     "avg_net_return", "exposure"):
                show5[c] = (show5[c] * 100).round(2)
            else:
                show5[c] = show5[c].round(2)
    print(show5[cols].to_string(index=False))

    # CLAUDE.md §5 Penalty Metrics: 多 trial sweep 必须报告 DSR
    if not df.empty and "sharpe" in df.columns:
        sharpes = df["sharpe"].dropna().tolist()
        if sharpes:
            observed = max(sharpes)
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed, n_trials=len(sharpes), n_returns=252
            )
            print(
                f"\n§5 DSR | observed_sharpe={observed:.3f} | "
                f"n_trials={len(sharpes)} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"expected_max={dsr['expected_max_sharpe']:.3f} | "
                f"p_value={dsr['p_value']:.4f}"
            )


if __name__ == "__main__":
    main()