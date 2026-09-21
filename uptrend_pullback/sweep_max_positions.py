"""max_positions sweep for uptrend_pullback v19 strategy.

基于 v33_long_reverse_v19 baseline,扫 max_positions ∈ {1, 2, 3}。
v19 默认 position_sizing="all_in";max_positions>1 时必须切换到 "equal"
才能同时开仓,所以组合为:
  (max_positions=1, all_in)   — v19 baseline
  (max_positions=2, equal)    — 分散到 2 只
  (max_positions=3, equal)    — 分散到 3 只

评估:12 个 2-month 非重叠窗口 (2024-09..2026-09),simulate 引擎。
Composite = mean × Sharpe (与 v17/v18/v19 一致)。
"""
from __future__ import annotations

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


START_MONTH = "2024-09"
END_MONTH = "2026-09"
WINDOW_MONTHS = 2
STEP_MONTHS = 2  # 不重叠


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
        # 窗口结束下个月首日
        ny, nm = add(wy, wm, 1)
        if (ny, nm) > (ey, em):
            break
        out.append((f"{cy:04d}-{cm:02d}-01", f"{ny:04d}-{nm:02d}-01"))
        cy, cm = add(cy, cm, STEP_MONTHS)
    return out


def _set(d: dict, k: str, v):
    d[k] = v


def run_one(preset: dict, panel_ind, universe, start: str, end: str,
            max_positions: int, position_sizing: str) -> dict:
    cfg = deepcopy(preset)
    _set(cfg, "max_positions", max_positions)
    _set(cfg, "position_sizing", position_sizing)

    sig_kwargs = {k: v for k, v in cfg["signal"].items() if k != "entry_mode"}
    entries = select_entries_v33_long_mirror(
        panel_ind,
        start_date=start, end_date=end,
        regime_df=None,
        **sig_kwargs,
    )

    trades, equity = simulate_portfolio(
        entries, panel_ind,
        tp_pct=cfg["tp_pct"], sl_pct=cfg["sl_pct"],
        max_hold=cfg["max_hold"], max_positions=max_positions,
        start_date=start, end_date=end,
        position_sizing=position_sizing,
    )
    m = compute_metrics(trades, equity, max_hold=cfg["max_hold"])
    m["signals"] = int(len(entries))
    m["start"] = start
    m["end"] = end
    return m


def aggregate(per_window: list[dict]) -> dict:
    df = pd.DataFrame(per_window)
    r = df["total_return"]
    dds = df["max_dd"]
    trades_mean = df["trades"].mean()
    # composite = mean × Sharpe (与 v17/v18/v19 baseline 一致)
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

    print(f"[windows] {START_MONTH}..{END_MONTH}, "
          f"{WINDOW_MONTHS}m×{STEP_MONTHS} step")
    windows = _monthly_windows()
    print(f"[windows] {len(windows)} windows: {windows}")

    # v19 baseline
    preset = {
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

    # 加载最大覆盖区间 (用 [windows[0][0], windows[-1][1]]) 并缓存;
    # simulate_portfolio 内部只用 start_date/end_date 过滤,但 panel 越大越占内存。
    # 取 [start - 60 天 warmup, end + 60 天余量]。
    universe = set(load_universe(preset["universe"], DB_PATH))
    load_start = windows[0][0]
    load_end = windows[-1][1]
    print(f"[load] {load_start} .. {load_end}")
    panel = load_panel(DB_PATH, load_start, load_end, universe=universe)
    panel_ind = compute_indicators(panel)
    print(f"[load] {len(panel)} 行, {panel['thscode'].nunique()} 只股票")

    # configs: v19 baseline + (max_positions=2/3, equal)
    configs = [
        ("v19 baseline", 1, "all_in"),
        ("pos=2 equal", 2, "equal"),
        ("pos=3 equal", 3, "equal"),
    ]

    results = {}
    for name, max_pos, sizing in configs:
        per_window = []
        for start, end in windows:
            m = run_one(preset, panel_ind, universe, start, end, max_pos, sizing)
            per_window.append(m)
        agg = aggregate(per_window)
        agg["max_positions"] = max_pos
        agg["position_sizing"] = sizing
        results[name] = {"aggregate": agg, "per_window": per_window}
        print(f"\n=== {name} (max_positions={max_pos}, sizing={sizing}) ===")
        print(f"  median   {agg['median']*100:+.2f}%")
        print(f"  mean     {agg['mean']*100:+.2f}%")
        print(f"  sharpe   {agg['sharpe']:.3f}")
        print(f"  avg_dd   {agg['avg_dd']*100:.2f}%")
        print(f"  worst_dd {agg['worst_dd']*100:.2f}%")
        print(f"  trades   {agg['trades_per_window']:.2f}/窗口")
        print(f"  composite (mean×sharpe)  {agg['composite']:.4f}")

    # Pareto strict analysis
    base_agg = results["v19 baseline"]["aggregate"]
    print("\n=== Pareto strict vs v19 baseline ===")
    print(f"baseline composite = {base_agg['composite']:.4f}")
    for name, r in results.items():
        if name == "v19 baseline":
            continue
        a = r["aggregate"]
        # strict Pareto: composite ↑ AND median↑/tied AND mean↑ AND sharpe↑ AND avg_dd ↓ AND worst_dd ↓/tied
        strict = (
            a["composite"] > base_agg["composite"]
            and a["median"] >= base_agg["median"] - 1e-6
            and a["mean"] > base_agg["mean"]
            and a["sharpe"] > base_agg["sharpe"]
            and a["avg_dd"] < base_agg["avg_dd"]
            and a["worst_dd"] <= base_agg["worst_dd"] + 1e-6
        )
        composite_delta = (a["composite"] - base_agg["composite"]) / abs(base_agg["composite"]) * 100
        print(f"\n{name}:")
        print(f"  composite   {a['composite']:.4f} ({composite_delta:+.2f}% vs baseline)")
        print(f"  median      {a['median']*100:+.2f}%  (Δ {(a['median']-base_agg['median'])*100:+.2f}pp)")
        print(f"  mean        {a['mean']*100:+.2f}%  (Δ {(a['mean']-base_agg['mean'])*100:+.2f}pp)")
        print(f"  sharpe      {a['sharpe']:.3f}     (Δ {a['sharpe']-base_agg['sharpe']:+.3f})")
        print(f"  avg_dd      {a['avg_dd']*100:.2f}%  (Δ {(a['avg_dd']-base_agg['avg_dd'])*100:+.2f}pp)")
        print(f"  worst_dd    {a['worst_dd']*100:.2f}%  (Δ {(a['worst_dd']-base_agg['worst_dd'])*100:+.2f}pp)")
        print(f"  trades/win  {a['trades_per_window']:.2f}  (Δ {a['trades_per_window']-base_agg['trades_per_window']:+.2f})")
        print(f"  strict Pareto: {'YES' if strict else 'NO'}")

    # 可执行性检查
    print("\n=== axis actionability ===")
    for name, r in results.items():
        if name == "v19 baseline":
            continue
        a = r["aggregate"]
        composite_drop = a["composite"] / base_agg["composite"]
        trades_explode = a["trades_per_window"] > base_agg["trades_per_window"] * 2
        if composite_drop < 0.95:
            print(f"  {name}: DROPPED (composite {composite_drop:.2%} < 0.95)")
        elif trades_explode:
            print(f"  {name}: DROPPED (trades exploded: {a['trades_per_window']:.1f} vs baseline {base_agg['trades_per_window']:.1f})")
        else:
            print(f"  {name}: actionable (composite {composite_drop:.2%}, trades {a['trades_per_window']:.1f})")

    # 保存
    out = Path("uptrend_pullback/results/sweep_max_positions_v19.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {k: {"aggregate": v["aggregate"], "per_window": v["per_window"]}
         for k, v in results.items()},
        indent=2, default=str,
    ))
    print(f"\n已保存: {out}")


if __name__ == "__main__":
    main()
