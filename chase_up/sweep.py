"""三维 sweep 工具 — TP×SL×max_hold 网格搜索 Pareto 前沿。

用法:
  python3 -m chase_up.sweep --preset chase_v1_atr_tp4_sl1 \
      --tp-mults 3,4,5 --sl-mults 1.0,1.5 --max-holds 10,15,18 \
      --start 2025-09-19 --end 2026-09-19
"""
from __future__ import annotations

import argparse
import json
import logging
from copy import deepcopy
from pathlib import Path

import duckdb
import pandas as pd

from chase_up.backtest import run_backtest
from chase_up.data import load_panel
from chase_up.signals import compute_indicators
from chase_up.universe import load_universe
from dna_stats.deflated import deflated_sharpe_ratio

from hiagent_config import DB_PATH

logger = logging.getLogger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description="chase_up 三维 sweep")
    ap.add_argument("--preset", default="chase_v1_atr_tp4_sl1")
    ap.add_argument("--tp-mults", default="3,4,5",
                    help="atr_tp_mult 候选列表,逗号分隔")
    ap.add_argument("--sl-mults", default="1.0,1.5",
                    help="atr_sl_mult 候选列表,逗号分隔")
    ap.add_argument("--max-holds", default="10,15,18",
                    help="max_hold 候选列表,逗号分隔")
    ap.add_argument("--start", default="2025-09-19")
    ap.add_argument("--end", default="2026-09-19")
    ap.add_argument("--db-path", default=str(DB_PATH))
    ap.add_argument("--out", default="chase_up/results/sweep.csv")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tp_mults = [float(x) for x in args.tp_mults.split(",")]
    sl_mults = [float(x) for x in args.sl_mults.split(",")]
    max_holds = [int(x) for x in args.max_holds.split(",")]

    from chase_up.presets import get_preset
    base = get_preset(args.preset)
    universe = set(load_universe(base["universe"], Path(args.db_path), asof_date=args.start))
    panel = load_panel(Path(args.db_path), args.start, args.end, universe=universe)
    panel_ind = compute_indicators(panel)
    print(f"[sweep] universe={len(universe)} panel={len(panel)} 行, "
          f"tp_mults={tp_mults} sl_mults={sl_mults} max_holds={max_holds}")

    rows = []
    total = len(tp_mults) * len(sl_mults) * len(max_holds)
    done = 0
    for tp_m in tp_mults:
        for sl_m in sl_mults:
            for mh in max_holds:
                cfg = deepcopy(base)
                cfg["atr_tp_mult"] = tp_m
                cfg["atr_sl_mult"] = sl_m
                cfg["max_hold"] = mh
                done += 1
                try:
                    res = run_backtest(
                        cfg, args.start, args.end, Path(args.db_path),
                        panel_ind=panel_ind,
                    )
                    m = res["metrics"]
                    rows.append({
                        "preset": args.preset,
                        "atr_tp_mult": tp_m,
                        "atr_sl_mult": sl_m,
                        "max_hold": mh,
                        "trades": m["trades"],
                        "win_rate": m["win_rate"],
                        "total_return": m["total_return"],
                        "cagr": m["cagr"],
                        "sharpe": m["sharpe"],
                        "max_dd": m["max_dd"],
                        "tp_count": m["tp_count"],
                        "sl_count": m["sl_count"],
                        "time_count": m["time_count"],
                        "profit_factor": m["profit_factor"],
                        "avg_net_return": m["avg_net_return"],
                        "exposure": m["exposure"],
                    })
                    print(f"  [{done}/{total}] tp={tp_m} sl={sl_m} mh={mh}: "
                          f"CAGR={m['cagr']*100:+.1f}% DD={m['max_dd']*100:.1f}% "
                          f"trades={m['trades']} WR={m['win_rate']*100:.1f}%")
                except (duckdb.Error, ValueError, KeyError) as e:
                    # §0 Fail-Fast narrowed: sweep is exploratory so we
                    # keep warn-log + continue + failure row, but only
                    # catch known-bad-data/lookup exceptions. KeyboardInterrupt,
                    # MemoryError, programming errors propagate.
                    print(f"  [{done}/{total}] tp={tp_m} sl={sl_m} mh={mh}: FAILED {e}")
                    rows.append({
                        "preset": args.preset,
                        "atr_tp_mult": tp_m,
                        "atr_sl_mult": sl_m,
                        "max_hold": mh,
                        "error": str(e),
                    })

    df = pd.DataFrame(rows)
    if "cagr" in df.columns:
        df = df.sort_values("cagr", ascending=False)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n已保存: {out}")
    if "cagr" in df.columns:
        print("\n=== Top 5 (CAGR) ===")
        show = df.head(5).copy()
        for c in ("total_return", "cagr", "max_dd", "win_rate"):
            if c in show.columns:
                show[c] = (show[c] * 100).round(2)
        show["sharpe"] = show["sharpe"].round(2)
        print(show.to_string(index=False))

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