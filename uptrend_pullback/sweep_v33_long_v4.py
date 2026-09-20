"""v4 - 围绕 v3 最优点位 (signal pct_chg_low=-0.05, above_ma60=0.5/0.7) + 推宽 TP/SL。
目标: CAGR > 100%。
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
        if ps == "kelly":
            kwargs["kelly_fraction"] = cfg.get("kelly_fraction", 0.5)

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
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)

    print(f"[load] {START} .. {END}")
    base = {
        "universe": "mainboard_only",
        "tp_pct": 0.15,
        "sl_pct": 0.03,
        "max_hold": 10,
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

    grids = {
        # 推宽 TP/SL (在 v3 最优信号下)
        "wide_tp": {
            "tp_pct": [0.15, 0.18, 0.20, 0.25, 0.30, 0.40],
            "sl_pct": [0.02, 0.025, 0.03, 0.04, 0.05],
            "max_hold": [10, 12, 15, 20],
        },
        # 极限松信号 (高频)
        "ultra_loose": {
            "signal.pct_chg_low": [-0.10, -0.07, -0.05, -0.04, -0.03],
            "signal.pct_chg_high": [-0.02, -0.01, 0.0, 0.01, 0.02],
            "signal.min_above_ma60_ratio": [0.3, 0.4, 0.5, 0.6],
            "signal.min_down_streak": [2, 3, 4],
        },
        # 4 仓位全仓 (4 仓 100%/4 = 25% 单股,类似 4 个并发信号)
        "max_positions": {
            "max_positions": [2, 3, 4, 5],
            "tp_pct": [0.15, 0.20],
            "sl_pct": [0.02, 0.03],
        },
    }

    results = {}
    for name, grid in grids.items():
        combos = list(itertools.product(*grid.values()))
        print(f"\n=== sweep: {name} ({len(combos)} combos) ===")
        df = sweep(base, grid, panel_ind)
        if df.empty:
            print("  no signals")
            continue
        results[name] = df
        show = df.head(args.top).copy()
        for c in ("cagr", "win_rate", "max_dd", "sharpe", "total_return",
                  "avg_net_return", "exposure"):
            if c in show.columns:
                if c in ("cagr", "win_rate", "max_dd", "total_return",
                         "avg_net_return", "exposure"):
                    show[c] = (show[c] * 100).round(2)
                else:
                    show[c] = show[c].round(2)
        cols = [c for c in (
            list(grid.keys()) + ["signals", "trades", "cagr", "win_rate",
                                  "tp_count", "sl_count", "time_count",
                                  "max_dd", "sharpe", "avg_hold_days",
                                  "exposure", "final_equity"]
        ) if c in show.columns]
        print(show[cols].to_string(index=False))

    out = Path("uptrend_pullback/results/sweep_v33_long_v4.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {k: v.to_dict(orient="records") for k, v in results.items()},
        indent=2, default=str,
    ))
    print(f"\n已保存: {out}")


if __name__ == "__main__":
    main()