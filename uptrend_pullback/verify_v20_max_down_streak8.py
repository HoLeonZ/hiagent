"""Backtrader verification of v20 candidate: max_down_streak 10 → 8 (v19 → v20).

评估:12 个 2-month 非重叠窗口 (2024-09..2026-09),backtrader 引擎。
Composite = mean × Sharpe (与 v17/v18/v19 baseline 一致)。

Strict Pareto check vs v19 baseline:
  composite > 0.9550 AND median >= +21.72% AND avg_dd <= 21.0% AND worst_dd <= 48.1%
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

import pandas as pd

from hiagent_config import DB_PATH

from uptrend_pullback.backtrader_engine import run_backtrader_backtest
from uptrend_pullback.data import load_panel
from uptrend_pullback.signals import compute_indicators
from uptrend_pullback.universe import load_universe


START_MONTH = "2024-09"
END_MONTH = "2026-09"
WINDOW_MONTHS = 2
STEP_MONTHS = 2

# v19 baseline (backtrader, 12 月窗口)
V19_BASELINE = {
    "composite": 0.9550,
    "median": 0.2172,
    "mean": 0.3222,
    "sharpe": 2.96,
    "avg_dd": 0.210,
    "worst_dd": 0.481,
    "trades": 8.30,
}


def _monthly_windows() -> list[tuple[str, str]]:
    def add(y, m, k):
        t = y * 12 + (m - 1) + k
        return t // 12, (t % 12) + 1
    sy, sm = map(int, START_MONTH.split("-"))
    ey, em = map(int, END_MONTH.split("-"))
    out = []
    cy, cm = sy, sm
    while True:
        wy, wm = add(cy, cm, WINDOW_MONTHS - 1)
        ny, nm = add(wy, wm, 1)
        if (ny, nm) > (ey, em):
            break
        out.append((f"{cy:04d}-{cm:02d}-01", f"{ny:04d}-{nm:02d}-01"))
        cy, cm = add(cy, cm, STEP_MONTHS)
    return out


def build_v20_preset(v19_preset: dict) -> dict:
    """Copy v19, apply delta: max_down_streak 10 → 8 (signal 维度)。"""
    p = copy.deepcopy(v19_preset)
    p["signal"]["max_down_streak"] = 8
    return p


def run_window(preset: dict, panel_ind: pd.DataFrame,
               start: str, end: str) -> dict:
    """跑单窗口(backtrader 引擎),返回 metrics dict。

    panel_ind 包含 raw OHLCV + amount 列,backtrader_engine 内部会从 panel_ind
    派生 panel 列。"""
    out = run_backtrader_backtest(
        preset, start, end, DB_PATH,
        panel_ind=panel_ind, verify=True,
    )
    m = out["metrics"]
    return m


def aggregate(per_window: list[dict]) -> dict:
    df = pd.DataFrame(per_window)
    r = df["total_return"]
    dds = df["max_dd"]
    trades_mean = df["trades"].mean()
    composite = float(r.mean()) * float(df["sharpe"].mean())
    return {
        "n_windows": len(df),
        "median": float(r.median()),
        "mean": float(r.mean()),
        "sharpe": float(df["sharpe"].mean()),
        "avg_dd": float(dds.mean()),
        "worst_dd": float(dds.max()),
        "trades_per_window": float(trades_mean),
        "composite": composite,
    }


def main():
    logging.basicConfig(level=logging.WARNING)

    windows = _monthly_windows()
    print(f"[windows] {START_MONTH}..{END_MONTH}, {WINDOW_MONTHS}m×{STEP_MONTHS} step")
    print(f"[windows] {len(windows)} windows:")
    for w in windows:
        print(f"  {w[0]} .. {w[1]}")

    # v19 baseline 完整 dict (与 presets.py 一致)
    v19 = {
        "universe": "mainboard_only",
        "tp_pct": 0.305,
        "sl_pct": 0.0293,
        "max_hold": 15,
        "max_positions": 1,
        "position_sizing": "all_in",
        "signal": {
            "entry_mode": "v33_long_mirror",
            "min_down_streak": 3,
            "max_down_streak": 10,
            "pct_chg_low": -0.065,
            "pct_chg_high": -0.02,
            "min_amount": 3e7,
            "max_amount": 3e8,
            "min_above_ma60_ratio": 0.65,
            "close_ma60_buffer": 0.02,
            "min_mom120": 0.18,
        },
    }

    v20 = build_v20_preset(v19)
    print(f"\n[v20 delta] signal.max_down_streak: 10 → {v20['signal']['max_down_streak']}")

    # Load 完整 panel 一次 (后续每个窗口复用)
    universe = set(load_universe(v19["universe"], DB_PATH))
    load_start = windows[0][0]
    load_end = windows[-1][1]
    print(f"[load] {load_start} .. {load_end}")
    panel = load_panel(DB_PATH, load_start, load_end, universe=universe)
    panel_ind = compute_indicators(panel)
    print(f"[load] {len(panel)} 行, {panel['thscode'].nunique()} 只股票")

    # 跑 v20 候选
    v20_per_window = []
    for start, end in windows:
        m = run_window(v20, panel_ind, start, end)
        v20_per_window.append(m)
        print(f"  v20 {start}..{end}: total_return {m['total_return']*100:+.2f}% "
              f"trades {int(m['trades'])} sharpe {m['sharpe']:.3f} "
              f"max_dd {m['max_dd']*100:.2f}%")

    agg = aggregate(v20_per_window)

    print("\n" + "=" * 70)
    print("v20 candidate aggregate (backtrader, 12 monthly windows)")
    print("=" * 70)
    print(f"  median     {agg['median']*100:+.2f}%")
    print(f"  mean       {agg['mean']*100:+.2f}%")
    print(f"  sharpe     {agg['sharpe']:.3f}")
    print(f"  avg_dd     {agg['avg_dd']*100:.2f}%")
    print(f"  worst_dd   {agg['worst_dd']*100:.2f}%")
    print(f"  trades/win {agg['trades_per_window']:.2f}")
    print(f"  composite  {agg['composite']:.4f}")

    # 严格 Pareto 比较
    strict = (
        agg["composite"] > V19_BASELINE["composite"]
        and agg["median"] >= V19_BASELINE["median"] - 1e-6
        and agg["avg_dd"] <= V19_BASELINE["avg_dd"] + 1e-6
        and agg["worst_dd"] <= V19_BASELINE["worst_dd"] + 1e-6
    )
    composite_delta_pct = (
        (agg["composite"] - V19_BASELINE["composite"]) / abs(V19_BASELINE["composite"]) * 100
    )

    print("\n" + "=" * 70)
    print("Strict Pareto vs v19 baseline")
    print("=" * 70)
    print(f"  composite  {agg['composite']:.4f}  "
          f"(Δ {composite_delta_pct:+.2f}% vs baseline {V19_BASELINE['composite']:.4f})  "
          f"{'> 0.9550' if agg['composite'] > V19_BASELINE['composite'] else '✗'}")
    print(f"  median     {agg['median']*100:+.2f}%  "
          f"(baseline {V19_BASELINE['median']*100:+.2f}%, "
          f"Δ {(agg['median']-V19_BASELINE['median'])*100:+.2f}pp)  "
          f"{'≥ baseline' if agg['median'] >= V19_BASELINE['median']-1e-6 else '✗'}")
    print(f"  mean       {agg['mean']*100:+.2f}%  "
          f"(baseline {V19_BASELINE['mean']*100:+.2f}%, "
          f"Δ {(agg['mean']-V19_BASELINE['mean'])*100:+.2f}pp)")
    print(f"  sharpe     {agg['sharpe']:.3f}  "
          f"(baseline {V19_BASELINE['sharpe']:.2f}, "
          f"Δ {agg['sharpe']-V19_BASELINE['sharpe']:+.3f})")
    print(f"  avg_dd     {agg['avg_dd']*100:.2f}%  "
          f"(baseline {V19_BASELINE['avg_dd']*100:.2f}%, "
          f"Δ {(agg['avg_dd']-V19_BASELINE['avg_dd'])*100:+.2f}pp)  "
          f"{'≤ baseline' if agg['avg_dd'] <= V19_BASELINE['avg_dd']+1e-6 else '✗'}")
    print(f"  worst_dd   {agg['worst_dd']*100:.2f}%  "
          f"(baseline {V19_BASELINE['worst_dd']*100:.2f}%, "
          f"Δ {(agg['worst_dd']-V19_BASELINE['worst_dd'])*100:+.2f}pp)  "
          f"{'≤ baseline' if agg['worst_dd'] <= V19_BASELINE['worst_dd']+1e-6 else '✗'}")
    print(f"  trades/win {agg['trades_per_window']:.2f}  "
          f"(baseline {V19_BASELINE['trades']:.2f}, "
          f"Δ {agg['trades_per_window']-V19_BASELINE['trades']:+.2f})")
    print(f"\n  STRICT PARETO: {'YES' if strict else 'NO'}")

    # 保存
    out_path = Path("uptrend_pullback/results/verify_v20_max_down_streak8.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {
            "axis": "max_down_streak sweep for uptrend_pullback v19",
            "delta": {"signal.max_down_streak": "10 → 8"},
            "engine": "backtrader",
            "windows": f"{START_MONTH}..{END_MONTH}, {WINDOW_MONTHS}m×{STEP_MONTHS} step",
            "v19_baseline": V19_BASELINE,
            "v20_aggregate": agg,
            "v20_per_window": v20_per_window,
            "strict_pareto": strict,
        },
        indent=2, default=str,
    ))
    print(f"\n已保存: {out_path}")


if __name__ == "__main__":
    main()