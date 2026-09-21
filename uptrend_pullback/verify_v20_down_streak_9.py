"""Backtrader verification of v20 candidate: max_down_streak 10→9 on v19 baseline.

Single preset: copy v33_long_reverse_v19, change max_down_streak: 10 → 9。
引擎:backtrader 真实承担 commission/stamp_duty/现金流记账。
窗口:12 个 2-month 月级窗口 (2024-09..2026-09),跟 v19 baseline 一致。
聚合:mean × Sharpe 与 v17/v18/v19 baseline 公式相同。
"""
from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.data import load_panel
from uptrend_pullback.presets import PRESETS
from uptrend_pullback.signals import compute_indicators
from uptrend_pullback.universe import load_universe
from uptrend_pullback.walkforward import monthly_windows, run_windows

START_MONTH = "2024-09"
END_MONTH = "2026-09"
WINDOW_MONTHS = 2
STEP_MONTHS = 2  # 不重叠

# v19 基线 (composite 0.9550, median +21.72%, mean +32.22%, Sharpe 2.96,
#          avg_dd 21.0%, worst_dd 48.1%, trades 8.30)
BASELINE = {
    "composite": 0.9550,
    "median": 0.2172,
    "mean": 0.3222,
    "sharpe": 2.96,
    "avg_dd": 0.210,
    "worst_dd": 0.481,
}


def aggregate(df: pd.DataFrame) -> dict:
    """跟 v19 baseline 完全一致的聚合口径。
    composite = mean(total_return) × mean(sharpe)
    median/mean 都对 total_return 列
    avg_dd = mean(max_dd)
    worst_dd = max(max_dd)
    trades = mean(trades)
    """
    r = df["total_return"]
    dds = df["max_dd"]
    composite = float(r.mean()) * float(df["sharpe"].mean())
    return {
        "n_windows": int(len(df)),
        "median": float(r.median()),
        "mean": float(r.mean()),
        "sharpe": float(df["sharpe"].mean()),
        "avg_dd": float(dds.mean()),
        "worst_dd": float(dds.max()),
        "trades": float(df["trades"].mean()),
        "composite": composite,
    }


def strict_pareto_check(agg: dict) -> tuple[bool, list[str]]:
    """composite ↑ AND median↑/tied AND avg_dd ≤ AND worst_dd ≤/tied."""
    fails = []
    if agg["composite"] <= BASELINE["composite"]:
        fails.append(f"composite {agg['composite']:.4f} <= {BASELINE['composite']:.4f}")
    if agg["median"] < BASELINE["median"] - 1e-6:
        fails.append(f"median {agg['median']:+.4f} < {BASELINE['median']:+.4f}")
    if agg["avg_dd"] > BASELINE["avg_dd"] + 1e-6:
        fails.append(f"avg_dd {agg['avg_dd']:.4f} > {BASELINE['avg_dd']:.4f}")
    if agg["worst_dd"] > BASELINE["worst_dd"] + 1e-6:
        fails.append(f"worst_dd {agg['worst_dd']:.4f} > {BASELINE['worst_dd']:.4f}")
    return (len(fails) == 0, fails)


def main():
    logging.basicConfig(level=logging.WARNING)

    windows = monthly_windows(START_MONTH, END_MONTH,
                              window_months=WINDOW_MONTHS,
                              step_months=STEP_MONTHS)
    print(f"[windows] {START_MONTH}..{END_MONTH}, "
          f"{WINDOW_MONTHS}m/step {STEP_MONTHS}m = {len(windows)} windows")
    for w in windows:
        print(f"   {w[0]} .. {w[1]}")

    # v20 candidate: copy v19, apply delta max_down_streak: 10 → 9
    base = deepcopy(PRESETS["v33_long_reverse_v19"])
    base["signal"]["max_down_streak"] = 9
    print(f"\n[preset] v20 candidate (max_down_streak={base['signal']['max_down_streak']}) "
          f"on v19 baseline (was {PRESETS['v33_long_reverse_v19']['signal']['max_down_streak']})")

    # 加载 universe 与 panel (复用 walkforward.run_windows 内部加载)
    universe = set(load_universe(base["universe"], DB_PATH))
    print(f"[universe] {len(universe)} 只")

    df = run_windows(base, windows, DB_PATH, engine="backtrader")
    if df.empty:
        print("!! run_windows returned empty DataFrame")
        return

    print("\n[per-window]")
    show = df.copy()
    for c in ("win_rate", "total_return", "max_dd"):
        show[c] = (show[c] * 100).round(2)
    show["sharpe"] = show["sharpe"].round(3)
    show["trades"] = show["trades"].round(1)
    show["tp_count"] = show["tp_count"].astype(int)
    show["sl_count"] = show["sl_count"].astype(int)
    show["time_count"] = show["time_count"].astype(int)
    cols = ["start", "end", "trades", "tp_count", "sl_count", "time_count",
            "total_return", "sharpe", "max_dd"]
    print(show[cols].to_string(index=False))

    agg = aggregate(df)
    print(f"\n=== v20 candidate aggregate (backtrader, 12 月级窗口) ===")
    print(f"  composite  {agg['composite']:.4f}   (v19 baseline {BASELINE['composite']:.4f}, "
          f"Δ {(agg['composite']-BASELINE['composite'])/BASELINE['composite']*100:+.2f}%)")
    print(f"  median     {agg['median']*100:+.2f}%  (v19 {BASELINE['median']*100:+.2f}%, "
          f"Δ {(agg['median']-BASELINE['median'])*100:+.2f}pp)")
    print(f"  mean       {agg['mean']*100:+.2f}%    (v19 {BASELINE['mean']*100:+.2f}%, "
          f"Δ {(agg['mean']-BASELINE['mean'])*100:+.2f}pp)")
    print(f"  sharpe     {agg['sharpe']:.3f}      (v19 {BASELINE['sharpe']:.2f}, "
          f"Δ {agg['sharpe']-BASELINE['sharpe']:+.3f})")
    print(f"  avg_dd     {agg['avg_dd']*100:.2f}%   (v19 {BASELINE['avg_dd']*100:.2f}%, "
          f"Δ {(agg['avg_dd']-BASELINE['avg_dd'])*100:+.2f}pp)")
    print(f"  worst_dd   {agg['worst_dd']*100:.2f}%   (v19 {BASELINE['worst_dd']*100:.2f}%, "
          f"Δ {(agg['worst_dd']-BASELINE['worst_dd'])*100:+.2f}pp)")
    print(f"  trades/win {agg['trades']:.2f}      (v19 8.30)")

    strict, fails = strict_pareto_check(agg)
    print(f"\n=== strict Pareto vs v19 baseline ===")
    print(f"  composite↑ AND median↑/tie AND avg_dd↓/tie AND worst_dd↓/tie")
    if strict:
        print("  strict Pareto: YES")
        comparison = f"STRICT_PARETO_UP: composite +{(agg['composite']-BASELINE['composite'])/BASELINE['composite']*100:.2f}%, " \
                     f"median {(agg['median']-BASELINE['median'])*100:+.2f}pp, " \
                     f"mean {(agg['mean']-BASELINE['mean'])*100:+.2f}pp"
    else:
        print("  strict Pareto: NO")
        for f in fails:
            print(f"   - {f}")
        comparison = f"NOT_STRICT_PARETO: {fails}"

    out = {
        "axis": "max_down_streak sweep for uptrend_pullback v19 (backtrader engine, 12 monthly windows 2024-09..2026-09)",
        "delta": {"max_down_streak": 9},
        "engine": "backtrader",
        "windows": len(windows),
        "aggregate": agg,
        "baseline": BASELINE,
        "strict_pareto": strict,
        "failures": fails,
        "comparison": comparison,
        "per_window": df.assign(
            win_rate=lambda d: (d["win_rate"]*100).round(2),
            total_return=lambda d: (d["total_return"]*100).round(2),
            max_dd=lambda d: (d["max_dd"]*100).round(2),
            sharpe=lambda d: d["sharpe"].round(3),
        ).to_dict(orient="records"),
    }
    out_path = Path("uptrend_pullback/results/verify_v20_down_streak_9.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n已保存: {out_path}")


if __name__ == "__main__":
    main()
