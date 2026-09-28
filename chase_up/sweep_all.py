"""跑 chase_up 全部 21 个 preset,汇总到一张对比表。

用法:
  python3 -m chase_up.sweep_all --start 2025-09-19 --end 2026-09-19
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import duckdb

from chase_up.backtrader_engine import run_backtrader_backtest
from chase_up.presets import PRESETS
from dna_stats.deflated import deflated_sharpe_ratio

from hiagent_config import DB_PATH as DEFAULT_DB


def _fmt_row(m: dict) -> str:
    return (
        f"{m['preset']:<60} "
        f"CAGR={m['cagr']*100:+8.2f}% "
        f"Sharpe={m['sharpe']:5.2f} "
        f"DD={m['max_dd']*100:6.2f}% "
        f"WR={m['win_rate']*100:5.1f}% "
        f"PF={m['profit_factor']:5.2f} "
        f"Trades={m['trades']:4d} "
        f"TP/SL/T/EOD={m['tp_count']}/{m['sl_count']}/{m['time_count']}/{m['eod_count']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="chase_up 全 preset 批量回测")
    parser.add_argument("--start", default="2025-09-19")
    parser.add_argument("--end", default="2026-09-19")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--no-verify", action="store_true",
                        help="跳过 backtrader 验证 (Phase 1 only,加速)")
    parser.add_argument("--out-dir", default="chase_up/results/sweep")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    failed: list[tuple[str, str]] = []

    print(f"=== chase_up sweep | {args.start} → {args.end} | "
          f"{len(PRESETS)} presets | engine=backtrader "
          f"{'(no-verify)' if args.no_verify else '(verified)'} ===\n")

    for name in sorted(PRESETS.keys()):
        print(f"[{len(rows)+1:2d}/{len(PRESETS)}] running {name} ...", flush=True)
        try:
            res = run_backtrader_backtest(
                name, args.start, args.end, Path(args.db_path),
                verify=not args.no_verify,
            )
            m = res["metrics"]
            m["preset"] = name
            m["start"] = args.start
            m["end"] = args.end
            m["engine"] = "backtrader" + (" (no-verify)" if args.no_verify else "")
            rows.append(m)

            # 每个 preset 单独一份 JSON
            single = out_dir / f"{name}.json"
            single.write_text(
                json.dumps(m, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print("    " + _fmt_row(m))
        except (duckdb.Error, ValueError, KeyError) as exc:  # noqa: BLE001 — 跑批需要继续推进
            failed.append((name, repr(exc)))
            print(f"    FAILED: {exc!r}")

    # 汇总表
    rows_sorted = sorted(rows, key=lambda r: r["cagr"], reverse=True)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(rows_sorted, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n=== sorted by CAGR ===")
    for m in rows_sorted:
        print(_fmt_row(m))

    if failed:
        print(f"\n!!! {len(failed)} preset(s) failed:")
        for n, err in failed:
            print(f"  - {n}: {err}")

    print(f"\n汇总 JSON: {summary_path}")

    # CLAUDE.md §5 Penalty Metrics: 多 trial sweep 必须报告 DSR
    # (selection-bias-corrected Sharpe). observed = max(sharpe) over n_trials.
    if rows:
        sharpes = [r.get("sharpe", 0.0) for r in rows if r.get("sharpe") is not None]
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
