"""v3 backtest CLI 入口。

跑 v3 事件驱动引擎（无 look-ahead），输出 metrics JSON。
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from short_reversal.engine import run_backtest_v3

from hiagent_config import DB_PATH as DEFAULT_DB

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="short_reversal v3 事件驱动 backtest（无 look-ahead）"
    )
    parser.add_argument("--preset", default="v33_mainboard_tp6_sl005_mh5_realistic")
    parser.add_argument("--start", default="2025-09-12")
    parser.add_argument("--end", default="2026-09-12")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument(
        "--out",
        default="short_reversal/results/backtest.json",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"DB 不存在: {db_path}")

    m = run_backtest_v3(args.preset, args.start, args.end, db_path)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")

    print(f"preset: {m['preset']}")
    print(
        f"trades: {m['trades_count']}, win_rate: {m['win_rate'] * 100:.1f}%"
    )
    print(
        f"final_capital: {m['final_capital']:.2f}, "
        f"total_yield: {m['total_yield'] * 100:+.2f}%"
    )
    print(f"cagr: {m['cagr'] * 100:+.2f}%, sharpe: {m['sharpe']:.2f}, "
          f"max_dd: {m['max_dd'] * 100:.2f}%")
    print(f"TP/SL/time: {m['tp_count']}/{m['sl_count']}/{m['time_count']}")
    print(f"输出: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
