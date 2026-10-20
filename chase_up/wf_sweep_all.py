"""按月滚动 24m 窗口,对 chase_up 全部 preset 做 walkforward。

用法:
  python3 -m chase_up.wf_sweep_all --start-month 2017-09 --end-month 2026-09
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import duckdb
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
    universe = set(load_universe(p["universe"], db_path, asof_date=start))
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
            except (duckdb.Error, ValueError, KeyError) as exc:  # noqa: BLE001
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
    if not summary.empty and "mean_sharpe" in summary.columns:
        # §5 (audit 2026-10-15): DSR 的 `observed_sharpe` 必须是**年化 Sharpe**
        # —— deflated_sharpe_ratio 的 docstring 原文:"Annualized Sharpe from
        # backtest (mean/std × sqrt(252))"。
        #
        # 此处原为 `median_return_pct / 100`:把**窗口中位总收益**的百分比当成
        # Sharpe 传进去。这不是数值误差而是**结论错误** —— 收益率(0.1~1)比典型
        # Sharpe 量级低一到两个数量级,于是 DSR / p 值会系统性地判成"毫无优势",
        # 而它照样被打印出来,读者会把它当作显著性结论。
        #
        # 汇总表里本来就有 `mean_sharpe`(每个 preset 跨窗口的 Sharpe 均值),
        # 直接用它:max over presets + n_trials = preset 数,正是本函数的契约
        # (docstring: "selecting the best Sharpe from k trials")。
        sharpes = summary["mean_sharpe"].dropna().tolist()
        if sharpes:
            observed = max(sharpes)
            # §5 (audit 2026-10-16): 本处的 observed 是 preset 跨**多个窗口**的
            # mean_sharpe,故代表性 T 取各窗口日收益数的均值(每窗一个观测集)。
            # 此前写死 252 ⇒ 而 WF 窗口实际只有 242~243 个交易日,T 高估约 4%、
            # 标准误低估约 2% ⇒ DSR 偏乐观。缺字段即 fail-fast,不用常数兜底。
            if "n_daily_returns" not in df.columns:
                raise ValueError(
                    "§5: detail 缺 n_daily_returns,无法确定 DSR 的观测数 T —— 不许用常数兜底"
                )
            # §5 (附八十二): `n_trials` 是"**试过多少个 preset**",不是"有多少个 preset
            # 的 mean_sharpe 不是 NaN"。某个 preset 的所有窗口都失败时它的 `mean_sharpe`
            # 是 NaN,会被 `dropna()` 剔除 ⇒ n_trials 少计、DSR 偏乐观。
            # §5 Iterative-Tuning Accounting:"每一次迭代都计入"。
            _n_tried = int(len(summary))
            _n_ok = int(len(sharpes))
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed, n_trials=_n_tried,
                n_returns=int(df["n_daily_returns"].mean()),
            )
            print(
                f"\n§5 DSR (across-presets sweep) | "
                f"observed_sharpe={observed:.3f} | "
                f"n_trials={_n_tried} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"p_value={dsr['dsr_p_value']:.4f}"
            )
            if _n_tried != _n_ok:
                print(
                    f"  ⚠️ 其中 {_n_tried - _n_ok} 个 preset 的 mean_sharpe 是 NaN"
                    f"(全部窗口失败)—— 它们同样计入 n_trials(§5:每次迭代都算)"
                )


if __name__ == "__main__":
    main()
