"""v6 — 单独精扫 TP × SL 二维网格。

冻结参数:
  signal.min_above_ma60_ratio=0.55
  max_hold=15, signal.min_down_streak=3, signal.max_down_streak=10
  pct_chg=[-0.05,-0.02], min_amount=3e7, max_amount=3e8
  universe=mainboard_only, max_positions=1, position_sizing=all_in

扫的参数:
  tp_pct ∈ {0.20, 0.25, 0.30, 0.35, 0.40}    (5)
  sl_pct ∈ {0.012, 0.015, 0.018, 0.021, 0.024}  (5)
  total: 25 组合

评估窗口: 2025-09-16 .. 2026-09-16 (12 月)
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

        trades, equity = simulate_portfolio(entries, panel_ind, **kwargs)
        m = compute_metrics(trades, equity, max_hold=cfg["max_hold"])
        rows.append({**combo, **m, "signals": int(len(entries))})

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _format_pct_cols(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = (out[c] * 100).round(2)
    return out


def _print_view(label: str, df: pd.DataFrame, sort_col: str, ascending: bool,
                top: int, extra: tuple[str, ...] = ()) -> None:
    if sort_col not in df.columns:
        print(f"\n=== {label} ===")
        print(f"  (skip: column {sort_col!r} missing)")
        return
    sub = df.sort_values(sort_col, ascending=ascending).head(top).copy()
    sub = _format_pct_cols(sub, ("cagr", "win_rate", "max_dd", "total_return",
                                  "avg_net_return", "exposure"))
    cols = [c for c in (
        ("tp_pct", "sl_pct", "signals", "trades", "cagr", "win_rate",
         "tp_count", "sl_count", "time_count", "max_dd", "sharpe",
         "profit_factor", "avg_hold_days") + extra
    ) if c in sub.columns]
    print(f"\n=== {label} ===")
    print(sub[cols].to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--min-trades", type=int, default=40,
                    help="ranking 过滤门槛 (默认 40)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)

    print(f"[load] {START} .. {END}")
    base = {
        "universe": "mainboard_only",
        "tp_pct": 0.30,
        "sl_pct": 0.018,
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
            "min_above_ma60_ratio": 0.55,
        },
    }

    universe = set(load_universe(base["universe"], Path(args.db_path)))
    panel = load_panel(Path(args.db_path), START, END, universe=universe)
    panel_ind = compute_indicators(panel)

    grid = {
        "tp_pct": [0.20, 0.25, 0.30, 0.35, 0.40],
        "sl_pct": [0.012, 0.015, 0.018, 0.021, 0.024],
    }

    combos = list(itertools.product(*grid.values()))
    print(f"[sweep] {len(combos)} combos (tp×sl 二维)")
    df = sweep(base, grid, panel_ind)
    if df.empty:
        print("no signals")
        return

    # 上一档基准 (tp=0.30, sl=0.018) 单独标出,对比 SL 放宽到 0.021 的收益
    prev = df[(df["tp_pct"] == 0.30) & (df["sl_pct"] == 0.018)]
    if not prev.empty:
        print(f"\n[prev SL=0.018] tp=0.30 sl=0.018 → "
              f"trades={int(prev['trades'].iloc[0])} "
              f"CAGR={prev['cagr'].iloc[0]*100:.2f}% "
              f"Sharpe={prev['sharpe'].iloc[0]:.3f} "
              f"DD={prev['max_dd'].iloc[0]*100:.2f}% "
              f"Win={prev['win_rate'].iloc[0]*100:.2f}% "
              f"PF={prev['profit_factor'].iloc[0]:.3f}")

    # trades 过滤
    df_min = df[df["trades"] >= args.min_trades].copy()
    print(f"\n[filter] trades >= {args.min_trades}: "
          f"{len(df_min)}/{len(df)} combos survive")

    # Pareto 多视图
    _print_view("Top by CAGR", df_min, "cagr", ascending=False, top=args.top)
    _print_view("Top by Sharpe", df_min, "sharpe", ascending=False, top=args.top)
    _print_view("Top by lowest DD", df_min, "max_dd", ascending=True, top=args.top)
    _print_view("Top by Profit Factor", df_min, "profit_factor",
                ascending=False, top=args.top)
    _print_view("Top by Win Rate", df_min, "win_rate", ascending=False, top=args.top)

    # 综合分 (与 v5 同口径)
    df_min["score"] = df_min["cagr"] + df_min["sharpe"] - df_min["max_dd"]
    _print_view("Top by Score (CAGR+Sharpe-DD)", df_min, "score",
                ascending=False, top=args.top)

    # 全网格热图 (CAGR × {tp, sl})
    print("\n=== Full Grid (CAGR %) ===")
    pivot = df.pivot_table(index="tp_pct", columns="sl_pct", values="cagr")
    pivot = (pivot * 100).round(1)
    print(pivot.to_string())

    out = Path("uptrend_pullback/results/sweep_v33_long_v6.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        df.to_dict(orient="records"), indent=2, default=str,
    ))
    print(f"\n已保存: {out}")


if __name__ == "__main__":
    main()