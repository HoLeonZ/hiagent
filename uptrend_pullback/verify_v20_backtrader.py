"""Backtrader verification of v20 candidate (max_down_streak=7)."""
from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.presets import get_preset
from uptrend_pullback.walkforward import monthly_windows, run_windows


START_MONTH = "2024-09"
END_MONTH = "2026-09"
WINDOW_MONTHS = 2
STEP_MONTHS = 2  # 不重叠


def aggregate(per_window_rows: list[dict]) -> dict:
    df = pd.DataFrame(per_window_rows)
    r = df["total_return"]
    dds = df["max_dd"]
    composite = float(r.mean()) * float(df["sharpe"].mean())
    return {
        "n_windows": len(df),
        "median": float(r.median()),
        "mean": float(r.mean()),
        "sharpe": float(df["sharpe"].mean()),
        "avg_dd": float(dds.mean()),
        "worst_dd": float(dds.max()),
        "trades_per_window": float(df["trades"].mean()),
        "composite": composite,
    }


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    windows = monthly_windows(
        START_MONTH, END_MONTH,
        window_months=WINDOW_MONTHS, step_months=STEP_MONTHS,
    )
    print(f"[windows] {len(windows)} windows")

    # Construct v20 candidate preset
    base = get_preset("v33_long_reverse_v19")
    v20 = copy.deepcopy(base)
    v20["signal"]["max_down_streak"] = 7

    print(f"\n=== v20 candidate (max_down_streak=7) ===")
    print(f"  preset signal: {v20['signal']}")

    # Run backtrader verification across all windows
    print(f"\n[run] backtrader engine on {len(windows)} windows...")
    df = run_windows(v20, windows, DB_PATH, engine="backtrader")

    print(f"\n[per-window results]")
    for _, row in df.iterrows():
        print(f"  {row['start']}..{row['end']}: ret={row['total_return']*100:+.2f}% "
              f"sharpe={row['sharpe']:.3f} dd={row['max_dd']*100:.2f}% "
              f"trades={row['trades']:.0f}")

    rows = df.to_dict("records")
    agg = aggregate(rows)

    print(f"\n=== aggregate ===")
    print(f"  median     {agg['median']*100:+.2f}%")
    print(f"  mean       {agg['mean']*100:+.2f}%")
    print(f"  sharpe     {agg['sharpe']:.3f}")
    print(f"  avg_dd     {agg['avg_dd']*100:.2f}%")
    print(f"  worst_dd   {agg['worst_dd']*100:.2f}%")
    print(f"  trades/win {agg['trades_per_window']:.2f}")
    print(f"  composite  {agg['composite']:.4f}")

    # Compare vs v19 baseline
    baseline = {
        "composite": 0.9550,
        "median": 0.2172,
        "mean": 0.3222,
        "sharpe": 2.96,
        "avg_dd": 0.210,
        "worst_dd": 0.481,
        "trades": 8.30,
    }
    print(f"\n=== vs v19 baseline ===")
    print(f"  composite  {agg['composite']:.4f} (Δ {(agg['composite']-baseline['composite'])/baseline['composite']*100:+.2f}%)")
    print(f"  median     {agg['median']*100:+.2f}%  (Δ {(agg['median']-baseline['median'])*100:+.2f}pp)")
    print(f"  mean       {agg['mean']*100:+.2f}%  (Δ {(agg['mean']-baseline['mean'])*100:+.2f}pp)")
    print(f"  sharpe     {agg['sharpe']:.3f}     (Δ {agg['sharpe']-baseline['sharpe']:+.3f})")
    print(f"  avg_dd     {agg['avg_dd']*100:.2f}%  (Δ {(agg['avg_dd']-baseline['avg_dd'])*100:+.2f}pp)")
    print(f"  worst_dd   {agg['worst_dd']*100:.2f}%  (Δ {(agg['worst_dd']-baseline['worst_dd'])*100:+.2f}pp)")
    print(f"  trades/win {agg['trades_per_window']:.2f}")

    # Strict Pareto check per task spec:
    # composite > 0.9550 AND median >= +21.72% AND avg_dd <= 21.0% AND worst_dd <= 48.1%
    strict = (
        agg["composite"] > baseline["composite"]
        and agg["median"] >= baseline["median"]
        and agg["avg_dd"] <= baseline["avg_dd"]
        and agg["worst_dd"] <= baseline["worst_dd"]
    )
    print(f"\n=== strict Pareto check ===")
    print(f"  composite {agg['composite']:.4f} > 0.9550: {agg['composite'] > baseline['composite']}")
    print(f"  median    {agg['median']*100:+.2f}% >= +21.72%: {agg['median'] >= baseline['median']}")
    print(f"  avg_dd    {agg['avg_dd']*100:.2f}% <= 21.0%: {agg['avg_dd'] <= baseline['avg_dd']}")
    print(f"  worst_dd  {agg['worst_dd']*100:.2f}% <= 48.1%: {agg['worst_dd'] <= baseline['worst_dd']}")
    print(f"  STRICT PARETO: {strict}")


if __name__ == "__main__":
    main()
