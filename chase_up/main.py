"""CLI 入口 — 追涨策略回测。

用法:
  python3 -m chase_up.main --preset chase_v1_atr_tp4_sl1 --start 2025-09-19 --end 2026-09-19
  python3 -m chase_up.main --engine simulate --preset chase_v1_atr_tp4_sl1 ...
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from chase_up.backtest import INITIAL_CAPITAL, run_backtest
from chase_up.backtrader_engine import run_backtrader_backtest

from hiagent_config import DB_PATH as DEFAULT_DB


def _fmt(metrics: dict) -> str:
    m = metrics
    return "\n".join([
        f"preset        : {m.get('preset', 'custom')}",
        f"区间          : {m['start']} → {m['end']}",
        f"信号数        : {m['signals']}",
        f"交易笔数      : {m['trades']}   胜率: {m['win_rate']*100:.1f}%",
        f"期末权益      : {m['final_equity']:,.0f}  (初始 {INITIAL_CAPITAL:,.0f})",
        f"总收益        : {m['total_return']*100:+.2f}%",
        f"年化 CAGR     : {m['cagr']*100:+.2f}%",
        f"Sharpe        : {m['sharpe']:.2f}",
        f"最大回撤      : {m['max_dd']*100:.2f}%",
        f"平均持仓天数  : {m['avg_hold_days']:.1f}  (最长 {m['max_hold_days']})",
        f"退出分布      : TP={m['tp_count']} SL={m['sl_count']} "
        f"time={m['time_count']} eod={m['eod_count']}",
        f"平均单笔净收益: {m['avg_net_return']*100:+.2f}%   盈亏比: {m['profit_factor']:.2f}",
        f"平均仓位占用  : {m['exposure']*100:.1f}%",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="chase_up 追涨回测入口")
    parser.add_argument("--preset", default="chase_v1_atr_tp4_sl1")
    parser.add_argument("--start", default="2025-09-19")
    parser.add_argument("--end", default="2026-09-19")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--out", default="chase_up/results/backtest.json")
    parser.add_argument("--save-trades", default="")
    parser.add_argument(
        "--engine",
        choices=("backtrader", "simulate"),
        default="backtrader",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="仅跑 Phase 1,跳过 backtrader 验证",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.engine == "simulate":
        res = run_backtest(args.preset, args.start, args.end, Path(args.db_path))
    else:
        res = run_backtrader_backtest(
            args.preset, args.start, args.end, Path(args.db_path),
            verify=not args.no_verify,
        )
    metrics, trades = res["metrics"], res["trades"]
    metrics["engine"] = args.engine + (
        "" if args.engine == "simulate" else (" (no-verify)" if args.no_verify else "")
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    if args.save_trades:
        tp = Path(args.save_trades)
        tp.parent.mkdir(parents=True, exist_ok=True)
        trades.assign(
            entry_date=lambda d: d["entry_date"].astype(str),
            exit_date=lambda d: d["exit_date"].astype(str),
        ).to_csv(tp, index=False)
        print(f"逐笔交易已保存: {tp}")

    print(_fmt(metrics))
    print(f"\n指标已保存: {out}")


if __name__ == "__main__":
    main()