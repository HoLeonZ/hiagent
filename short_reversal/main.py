"""v3 backtest CLI 入口。

跑 v3 事件驱动引擎（无 look-ahead），输出 metrics JSON。
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from short_reversal.engine import run_backtest_v3

from hiagent_config import DB_PATH as DEFAULT_DB

logger = logging.getLogger(__name__)


# §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv canonical schemas.
EQUITY_CURVE_COLS = ("date", "cash", "position_value",
                     "total_equity", "drawdown")
CASH_WALK_COLS = ("date", "free_cash", "locked_margin",
                  "settling_funds", "nav", "total_equity")


def _strip_trades_for_json(metrics: dict) -> dict:
    """Strip the `trades` per-trade list from metrics before JSON dump.

    short_reversal/engine.py _metrics_from_holder includes a full per-trade
    `trades` list inside the metrics dict. Without stripping, the metrics
    JSON file becomes huge and unparseable for downstream consumers that
    only want aggregate metrics.

    Per [[backtest-metrics-canonical-schema-2026-09-23]] Tick 58:
    per-preset metrics JSON MUST carry aggregate keys only; per-trade
    detail lives in the trades.csv (canonical 14-col, see Tick 50).
    """
    safe = {k: v for k, v in metrics.items() if k != "trades"}
    return safe


def _write_per_preset_metrics(
    out_dir: Path,
    metrics: dict,
    preset: str,
) -> Path:
    """Write per-preset audit-trail metrics JSON (§2/§3 Tick 58).

    Strips the embedded `trades` list (huge, redundant with trades.csv).
    Single-overwrite `backtest.json` is preserved for back-compat.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _strip_trades_for_json(metrics)
    out = out_dir / f"{preset}_metrics.json"
    out.write_text(
        json.dumps(safe, indent=2, default=str), encoding="utf-8"
    )
    return out


def _write_equity_curve(
    equity_path: Path,
    cash_walk_path: Path,
    equity_rows: list[dict] | object,
) -> None:
    """Write equity_curve.csv + cash_walk.csv (§2/§3 Tick 51).

    Accepts the `result_holder["equity_curve"]` list-of-dicts that
    Phase3V3Strategy populates per-bar. cash_walk defaults to single-pool
    (free_cash == cash, locked_margin == settling_funds == 0) until H5.1.
    """
    equity_path.parent.mkdir(parents=True, exist_ok=True)
    cash_walk_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(equity_rows or [])
    with equity_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(EQUITY_CURVE_COLS))
        w.writeheader()
        for row in rows:
            cash = float(row.get("cash", 0.0))
            holdings_value = float(row.get("holdings_value", 0.0))
            total_equity = float(row.get("equity", cash + holdings_value))
            w.writerow({
                "date": row.get("date"),
                "cash": cash,
                "position_value": holdings_value,
                "total_equity": total_equity,
                "drawdown": float(row.get("drawdown", 0.0)),
            })
    with cash_walk_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(CASH_WALK_COLS))
        w.writeheader()
        for row in rows:
            cash = float(row.get("cash", 0.0))
            holdings_value = float(row.get("holdings_value", 0.0))
            total_equity = float(row.get("equity", cash + holdings_value))
            w.writerow({
                "date": row.get("date"),
                "free_cash": cash,
                "locked_margin": 0.0,
                "settling_funds": 0.0,
                "nav": cash + holdings_value,
                "total_equity": total_equity,
            })


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
    # Aggregate-only metrics JSON (Tick 58 GREEN): strip embedded
    # per-trade list. The legacy `backtest.json` is the single-overwrite
    # last-run snapshot — keep it for back-compat.
    out_path.write_text(
        json.dumps(_strip_trades_for_json(m), indent=2, default=str),
        encoding="utf-8",
    )

    # §2/§3 Tick 58 GREEN: per-preset metrics audit trail.
    _write_per_preset_metrics(out_path.parent, m, preset=args.preset)

    # §2/§3 Tick 51 GREEN: equity_curve.csv + cash_walk.csv (driven by
    # the per-bar equity_curve list that Phase3V3Strategy populates
    # into result_holder).
    eq_rows = m.get("equity_curve") if isinstance(m, dict) else None
    if eq_rows:
        _write_equity_curve(
            out_path.parent / "equity_curve.csv",
            out_path.parent / "cash_walk.csv",
            eq_rows,
        )

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
