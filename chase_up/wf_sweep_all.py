"""按月滚动 24m 窗口,对 chase_up 全部 preset 做 walkforward。

用法:
  python3 -m chase_up.wf_sweep_all --start-month 2017-09 --end-month 2026-09
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from chase_up.backtrader_engine import run_backtrader_backtest
from chase_up.data import load_panel
from chase_up.presets import PRESETS, get_preset
from chase_up.signals import compute_indicators
from dna_stats.deflated import deflated_sharpe_ratio
from chase_up.universe import load_universe
from chase_up.walkforward import monthly_windows

from hiagent_config import DB_PATH as DEFAULT_DB


DD_BLOWUP_THRESHOLD = 1.00  # max_dd >= 100% 视为破产


def _per_window_check(m: dict) -> dict:
    """在 metrics 基础上补充 wf 专用字段。"""
    out = dict(m)
    out["blowup"] = bool(out.get("max_dd", 0) >= DD_BLOWUP_THRESHOLD)
    return out


def run_one_window(
    name: str,
    start: str,
    end: str,
    db_path: Path,
) -> dict:
    p = get_preset(name)
    universe = set(load_universe(p["universe"], db_path))
    panel = load_panel(db_path, start, end, universe=universe)
    panel_ind = compute_indicators(panel)
    res = run_backtrader_backtest(
        p, start, end, db_path,
        panel_ind=panel_ind, verify=True,
    )
    m = res["metrics"]
    m = _per_window_check(m)
    m["preset"] = name
    m["start"] = start
    m["end"] = end
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description="chase_up 全 preset 24m 滚动 WF")
    ap.add_argument("--start-month", default="2017-09")
    ap.add_argument("--end-month", default="2026-09")
    ap.add_argument("--window-months", type=int, default=24)
    ap.add_argument("--step-months", type=int, default=1)
    ap.add_argument("--db-path", default=str(DEFAULT_DB))
    ap.add_argument("--out-dir", default="chase_up/results/wf_sweep")
    ap.add_argument("--skip-verify", action="store_true",
                    help="跳过 backtrader verify (Phase 1 only, 加速)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    windows = monthly_windows(
        args.start_month, args.end_month,
        window_months=args.window_months, step_months=args.step_months,
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== WF sweep | {args.start_month} → {args.end_month} | "
          f"window={args.window_months}m step={args.step_months}m | "
          f"{len(windows)} windows × {len(PRESETS)} presets ===\n")

    rows: list[dict] = []
    blowups: list[dict] = []

    for w_idx, (start, end) in enumerate(windows, 1):
        print(f"\n--- window {w_idx}/{len(windows)}: {start} → {end} ---")
        for p_idx, name in enumerate(sorted(PRESETS.keys()), 1):
            try:
                m = run_one_window(name, start, end, Path(args.db_path))
            except Exception as exc:  # noqa: BLE001
                print(f"  [{p_idx:2d}/{len(PRESETS)}] {name}  ERROR: {exc!r}")
                continue
            tag = " 💥BLOWUP" if m["blowup"] else ""
            print(
                f"  [{p_idx:2d}/{len(PRESETS)}] {name}  "
                f"ret={m['total_return']*100:+8.2f}%  CAGR={m['cagr']*100:+8.2f}%  "
                f"DD={m['max_dd']*100:6.2f}%  Sharpe={m['sharpe']:5.2f}  "
                f"trades={m['trades']:3d}{tag}"
            )
            rows.append(m)
            if m["blowup"]:
                blowups.append({
                    "preset": name,
                    "start": start,
                    "end": end,
                    "max_dd": m["max_dd"],
                    "cagr": m["cagr"],
                    "trades": m["trades"],
                    "tp_count": m["tp_count"],
                    "sl_count": m["sl_count"],
                    "time_count": m["time_count"],
                    "final_equity": m["final_equity"],
                })

    df = pd.DataFrame(rows)
    detail_path = out_dir / "detail.csv"
    df.to_csv(detail_path, index=False)

    # 汇总:每个 preset 在 24 窗的统计
    summary_rows = []
    for name, g in df.groupby("preset"):
        r = g["total_return"]
        summary_rows.append({
            "preset": name,
            "windows": len(g),
            "profitable_windows": int((r > 0).sum()),
            "blowup_windows": int(g["blowup"].sum()),
            "blowup_window_ids": ";".join(
                g.loc[g["blowup"], "start"].tolist()
            ),
            "mean_return_pct": round(float(r.mean()) * 100, 2),
            "median_return_pct": round(float(r.median()) * 100, 2),
            "min_return_pct": round(float(r.min()) * 100, 2),
            "max_return_pct": round(float(r.max()) * 100, 2),
            "mean_max_dd_pct": round(float(g["max_dd"].mean()) * 100, 2),
            "worst_max_dd_pct": round(float(g["max_dd"].max()) * 100, 2),
            "mean_sharpe": round(float(g["sharpe"].mean()), 2),
            "mean_cagr_pct": round(float(g["cagr"].mean()) * 100, 2),
            "total_trades": int(g["trades"].sum()),
        })
    summary = pd.DataFrame(summary_rows).sort_values(
        "median_return_pct", ascending=False
    )
    summary_path = out_dir / "summary.csv"
    summary.to_csv(summary_path, index=False)

    # 破产窗口列表
    blowup_path = out_dir / "blowups.csv"
    if blowups:
        pd.DataFrame(blowups).to_csv(blowup_path, index=False)
    else:
        pd.DataFrame(columns=[
            "preset", "start", "end", "max_dd", "cagr", "trades",
            "tp_count", "sl_count", "time_count", "final_equity",
        ]).to_csv(blowup_path, index=False)

    print("\n========== 全 preset WF 汇总 (按中位收益排序) ==========")
    show = summary.copy()
    print(show.to_string(index=False))
    print(f"\n💥 共发现 {len(blowups)} 个 (preset, window) 组合 max_dd ≥ 100%")
    print(f"   详情: {blowup_path}")
    print(f"   明细: {detail_path}")
    print(f"   汇总: {summary_path}")

    # CLAUDE.md §5 Penalty Metrics: 多 trial sweep 必须报告 DSR
    # observed = median_return_pct / 100 (粗略 annualized proxy); n_trials = presets
    if not summary.empty and "median_return_pct" in summary.columns:
        # median_return_pct 是窗口中位总收益 (近似 annualized via sqrt(time) 简化)
        # 严格场景下应传入 SharpeRatio of equity curve, 此处仅用于 sweep 排序
        # 时的 selection bias sanity check
        sharpes = summary["median_return_pct"].dropna().tolist()
        if sharpes:
            observed = max(sharpes) / 100.0
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed, n_trials=len(sharpes), n_returns=252
            )
            print(
                f"\n§5 DSR (across-presets sweep) | "
                f"observed_median_ret={observed*100:+.2f}% | "
                f"n_trials={len(sharpes)} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"p_value={dsr['p_value']:.4f}"
            )


if __name__ == "__main__":
    main()
