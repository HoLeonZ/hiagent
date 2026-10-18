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
            # §5 (audit 2026-10-16): T 必须来自本次运行 —— 本脚本不持有 panel,
            # 故取引擎随 metrics 发布的 `n_daily_returns`(见 backtest.compute_metrics)。
            # 取不到即 fail-fast,不用常数兜底(兜底值正是本项要修的缺陷)。
            t_obs = [int(r["n_daily_returns"]) for r in rows if "n_daily_returns" in r]
            if not t_obs:
                raise ValueError(
                    "§5: metrics 缺 n_daily_returns,无法确定 DSR 的观测数 T —— "
                    "不许用常数兜底"
                )
            # §5 (附八十二): 失败的 preset 走 except 分支进了 `failed`,**没进 `rows`**
            # ⇒ `len(sharpes)` 只数了成功的那批 ⇒ n_trials 少计、DSR 偏乐观。
            # §5 Iterative-Tuning Accounting:"每一次迭代都计入" —— 崩掉的那次也是迭代。
            _n_tried = int(len(rows) + len(failed))
            _n_ok = int(len(sharpes))
            dsr = deflated_sharpe_ratio(
                observed_sharpe=observed, n_trials=_n_tried,
                n_returns=max(t_obs),
            )
            print(
                f"\n§5 DSR | observed_sharpe={observed:.3f} | "
                f"n_trials={_n_tried} | "
                f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
                f"expected_max={dsr['expected_max_sharpe']:.3f} | "
                f"p_value={dsr['dsr_p_value']:.4f}"
            )
            if _n_tried != _n_ok:
                print(
                    f"  ⚠️ 其中 {_n_tried - _n_ok} 个 preset **抛异常**(见上方 FAILED 清单)"
                    f"—— 它们同样计入 n_trials(§5:每次迭代都算)"
                )
            # §5 (audit 2026-10-15): 同 `sweep.py` —— 单一窗口选优必须显式声明,
            # 并把读者引向本仓库已有的滚动窗口版本。
            print(
                f"  ⚠️ in-sample selection:本榜是在单一窗口 {args.start} → {args.end} 上\n"
                f"     从 {len(sharpes)} 个配置里选出的。DSR 不能替代样本外验证 ——\n"
                f"     要把某个 config 当结论,请用滚动窗口的 chase_up/wf_sweep_all.py,\n"
                f"     或在本榜**未参与选择**的窗口上复跑(§5 WFV)。"
            )


if __name__ == "__main__":
    main()
