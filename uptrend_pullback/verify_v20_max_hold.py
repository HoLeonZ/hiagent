"""Backtrader verification of v20 candidate: max_hold 15→16.

构造 v33_long_reverse_v19 baseline 的副本,只把 max_hold 从 15 改为 16,
然后用 backtrader 引擎跑 12 个 2-month 月级窗口 (2024-09..2026-09),
最后与 v19 baseline 比较 strict Pareto。
"""
from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.presets import get_preset
from uptrend_pullback.walkforward import monthly_windows, run_windows


START_MONTH = "2024-09"
END_MONTH = "2026-09"
WINDOW_MONTHS = 2
STEP_MONTHS = 2


def aggregate(per_window: pd.DataFrame) -> dict:
    if per_window.empty:
        return {
            "n_windows": 0,
            "median": 0.0,
            "mean": 0.0,
            "sharpe": 0.0,
            "avg_dd": 0.0,
            "worst_dd": 0.0,
            "trades_per_window": 0.0,
            "composite": 0.0,
        }
    r = per_window["total_return"]
    dds = per_window["max_dd"]
    trades_mean = per_window["trades"].mean()
    composite = float(r.mean()) * float(per_window["sharpe"].mean())
    return {
        "n_windows": len(per_window),
        "median": float(r.median()),
        "mean": float(r.mean()),
        "sharpe": float(per_window["sharpe"].mean()),
        "avg_dd": float(dds.mean()),
        "worst_dd": float(dds.max()),
        "trades_per_window": float(trades_mean),
        "composite": composite,
    }


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    windows = monthly_windows(
        START_MONTH, END_MONTH,
        window_months=WINDOW_MONTHS, step_months=STEP_MONTHS,
    )
    print(f"[windows] {START_MONTH}..{END_MONTH}, "
          f"{WINDOW_MONTHS}m×{STEP_MONTHS} step = {len(windows)} 窗")
    for w in windows:
        print(f"  {w[0]} .. {w[1]}")

    # v19 baseline (从 presets 拿,避免硬编码漂移)
    base_preset = get_preset("v33_long_reverse_v19")
    print(f"\n[v19 baseline] max_hold={base_preset['max_hold']}")
    df_baseline = run_windows(base_preset, windows, DB_PATH, engine="backtrader")
    base_agg = aggregate(df_baseline)
    print(f"  median     {base_agg['median']*100:+.2f}%")
    print(f"  mean       {base_agg['mean']*100:+.2f}%")
    print(f"  sharpe     {base_agg['sharpe']:.3f}")
    print(f"  avg_dd     {base_agg['avg_dd']*100:.2f}%")
    print(f"  worst_dd   {base_agg['worst_dd']*100:.2f}%")
    print(f"  trades/win {base_agg['trades_per_window']:.2f}")
    print(f"  composite  {base_agg['composite']:.4f}")

    # v20 candidate: max_hold 15 → 16
    cand_preset = deepcopy(base_preset)
    cand_preset["max_hold"] = 16
    print(f"\n[v20 candidate] max_hold={cand_preset['max_hold']}")
    df_cand = run_windows(cand_preset, windows, DB_PATH, engine="backtrader")
    cand_agg = aggregate(df_cand)
    print(f"  median     {cand_agg['median']*100:+.2f}%")
    print(f"  mean       {cand_agg['mean']*100:+.2f}%")
    print(f"  sharpe     {cand_agg['sharpe']:.3f}")
    print(f"  avg_dd     {cand_agg['avg_dd']*100:.2f}%")
    print(f"  worst_dd   {cand_agg['worst_dd']*100:.2f}%")
    print(f"  trades/win {cand_agg['trades_per_window']:.2f}")
    print(f"  composite  {cand_agg['composite']:.4f}")

    # strict Pareto check vs v19 baseline
    strict = (
        cand_agg["composite"] > base_agg["composite"]
        and cand_agg["median"] >= base_agg["median"] - 1e-6
        and cand_agg["avg_dd"] <= base_agg["avg_dd"] + 1e-6
        and cand_agg["worst_dd"] <= base_agg["worst_dd"] + 1e-6
    )
    composite_delta = (cand_agg["composite"] - base_agg["composite"]) / abs(base_agg["composite"]) * 100
    print("\n=== Pareto strict vs v19 baseline ===")
    print(f"  composite   {cand_agg['composite']:.4f}  ({composite_delta:+.2f}% vs baseline)")
    print(f"  median      {cand_agg['median']*100:+.2f}%  (Δ {(cand_agg['median']-base_agg['median'])*100:+.2f}pp)")
    print(f"  mean        {cand_agg['mean']*100:+.2f}%  (Δ {(cand_agg['mean']-base_agg['mean'])*100:+.2f}pp)")
    print(f"  sharpe      {cand_agg['sharpe']:.3f}     (Δ {cand_agg['sharpe']-base_agg['sharpe']:+.3f})")
    print(f"  avg_dd      {cand_agg['avg_dd']*100:.2f}%  (Δ {(cand_agg['avg_dd']-base_agg['avg_dd'])*100:+.2f}pp)")
    print(f"  worst_dd    {cand_agg['worst_dd']*100:.2f}%  (Δ {(cand_agg['worst_dd']-base_agg['worst_dd'])*100:+.2f}pp)")
    print(f"  trades/win  {cand_agg['trades_per_window']:.2f}  (Δ {cand_agg['trades_per_window']-base_agg['trades_per_window']:+.2f})")
    print(f"  strict Pareto: {'YES' if strict else 'NO'}")

    # 保存完整结果
    out = Path("uptrend_pullback/results/verify_v20_max_hold.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "axis": "max_hold (v33_long_reverse_v19 baseline)",
        "delta": {"max_hold": 16},
        "baseline": {
            "name": "v33_long_reverse_v19",
            "aggregate": base_agg,
            "per_window": df_baseline.to_dict(orient="records"),
        },
        "candidate": {
            "name": "v20_max_hold_16",
            "preset": cand_preset,
            "aggregate": cand_agg,
            "per_window": df_cand.to_dict(orient="records"),
        },
        "strict_pareto": strict,
    }, indent=2, default=str))
    print(f"\n已保存: {out}")


if __name__ == "__main__":
    main()