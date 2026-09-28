"""CLI entry point for cycle_price_action."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

from hiagent_config import get_db_path
from core.trade_schema import TRADE_COLS
from cycle_price_action.backtest import run_backtest
from cycle_price_action.metrics import TradeRecord
from cycle_price_action.walkforward import walkforward_windows


def _resolve_window(start: str | None, end: str | None) -> tuple[date, date]:
    """Resolve CLI date window to concrete (start, end) dates.

    Defaults: end = today, start = end - 365 days. Either may be overridden.
    """
    e = date.fromisoformat(end) if end else date.today()
    if start:
        s = date.fromisoformat(start)
    else:
        s = date.fromordinal(e.toordinal() - 365)
    return s, e


def _write_trades_csv(path: Path, trades: list[TradeRecord]) -> None:
    """Write trades.csv with canonical 14-col schema (CLAUDE.md §3).

    Engine-specific columns (k_line_score, phase_score, calendar_score)
    are dropped from this output but remain available on the TradeRecord
    object and are NOT lost — they live in metrics.json or downstream
    decision_meta if needed. The single source of truth for the 14-col
    header is `core.trade_schema.TRADE_COLS`.

    cycle_price_action doesn't track `atr_pct` (NaN) or `sub_signal_type`
    (empty) per-trade; these are populated as defaults.
    """
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(TRADE_COLS))
        w.writeheader()
        for t in trades:
            gross_pnl = (t.exit_price - t.entry_price) * t.shares
            net_pnl = t.pnl
            fees = gross_pnl - net_pnl
            invested = t.entry_price * t.shares
            net_return = (net_pnl / invested) if invested > 0 else 0.0
            w.writerow({
                "entry_date": t.entry_date.isoformat(),
                "exit_date": t.exit_date.isoformat(),
                "thscode": t.thscode,
                "exit_reason": "",  # cycle_price_action doesn't tag exit reason
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "size": t.shares,
                "hold_days": t.hold_days,
                "gross_pnl": gross_pnl,
                "fees": fees,
                "net_pnl": net_pnl,
                "net_return": net_return,
                "atr_pct": "",  # engine-specific; not tracked per-trade
                "sub_signal_type": "",  # chase_up-only enum
            })


def _write_per_preset_metrics(out_dir: Path, metrics: dict, preset: str) -> None:
    """Write `results/<preset>_metrics.json` (Tick 58 fix).

    Engine-specific metrics from cycle_price_action/metrics.py:
      n_trades, n_wins, n_stocks, total_pnl, avg_hold_days, win_rate,
      cagr (None), sharpe (None), max_dd (None).

    Single-overwrite `metrics.json` is preserved for back-compat (last
    run only); per-preset file gives audit trail across preset runs.
    """
    safe_metrics = dict(metrics)
    out = out_dir / f"{preset}_metrics.json"
    out.write_text(json.dumps(safe_metrics, indent=2, default=str))


def _write_equity_curve(
    equity_path: Path,
    cash_walk_path: Path,
    equity_rows: list[dict],
) -> None:
    """Write `equity_curve.csv` + `cash_walk.csv` (Tick 51 fix).

    cycle_price_action runs per-stock independent accounts. The caller
    is expected to aggregate per-stock cash/holdings curves (e.g., by
    summing across stocks per calendar day). Until H5.1 implements
    proper 3-pool settlement, `free_cash` mirrors the single cash pool
    and `locked_margin` + `settling_funds` default to 0.
    """
    EQUITY_CURVE_COLS = ("date", "cash", "position_value",
                         "total_equity", "drawdown")
    CASH_WALK_COLS = ("date", "free_cash", "locked_margin",
                      "settling_funds", "nav", "total_equity")
    with equity_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(EQUITY_CURVE_COLS))
        w.writeheader()
        for row in equity_rows:
            holdings_value = float(row.get("holdings_value", 0.0)
                                   or row.get("holdings", 0.0))
            cash = float(row.get("cash", 0.0))
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
        for row in equity_rows:
            holdings_value = float(row.get("holdings_value", 0.0)
                                   or row.get("holdings", 0.0))
            cash = float(row.get("cash", 0.0))
            total_equity = float(row.get("equity", cash + holdings_value))
            w.writerow({
                "date": row.get("date"),
                "free_cash": cash,
                "locked_margin": 0.0,
                "settling_funds": 0.0,
                "nav": cash + holdings_value,
                "total_equity": total_equity,
            })


def _run_backtest(args) -> int:
    start, end = _resolve_window(args.start, args.end)
    out_dir = Path(args.out_dir) / f"run_{datetime.now():%Y%m%d_%H%M%S_%f}"
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = args.db if args.db else str(get_db_path())
    result = run_backtest(db_path=db_path, start=start, end=end, cash=args.cash)

    _write_trades_csv(out_dir / "trades.csv", result.trades)
    # Per-preset metrics audit trail (Tick 58 fix); single-overwrite
    # metrics.json below is preserved for back-compat (last run only).
    preset = getattr(args, "preset", "v1")
    _write_per_preset_metrics(out_dir, result.metrics, preset=preset)
    (out_dir / "metrics.json").write_text(json.dumps(result.metrics, indent=2))
    m = result.metrics
    print(f"wrote {out_dir}: n_trades={m['n_trades']}, "
          f"pnl={m['total_pnl']:.2f}, win_rate={m['win_rate']:.2%}")
    return 0


def _run_walkforward(args) -> int:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    windows = walkforward_windows(
        start, end,
        train_months=args.train_months,
        test_months=args.test_months,
        roll_months=args.roll_months,
    )
    for i, w in enumerate(windows, 1):
        print(f"[{i:02d}] train={w.train_start}..{w.train_end}"
              f" test={w.test_start}..{w.test_end}")
    print(f"total windows: {len(windows)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("cycle_price_action")
    p.add_argument("--db", default=str(get_db_path()))
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--preset", default="v1", choices=["v1"])

    sub = p.add_subparsers(dest="cmd", required=False)

    def add_wf_parser(parent):
        wf = parent.add_parser("walkforward")
        wf.add_argument("--train-months", type=int, default=12)
        wf.add_argument("--test-months", type=int, default=12)
        wf.add_argument("--roll-months", type=int, default=6)
        wf.set_defaults(func=_run_walkforward)
        return wf

    add_wf_parser(sub)

    def add_run_parser(parent):
        rp = parent.add_parser("run")
        # --start / --end / --db / --preset are inherited from the parent
        # parser. Re-defining them here would shadow the parent's namespace
        # entries with None (argparse subparser behavior).
        rp.add_argument("--cash", type=float, default=1_000_000)
        rp.add_argument("--out-dir", default="results")
        rp.set_defaults(func=_run_backtest)
        return rp

    add_run_parser(sub)

    args = p.parse_args(argv)
    if getattr(args, "cmd", None) == "walkforward":
        return args.func(args)
    if getattr(args, "cmd", None) == "run":
        return args.func(args)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    windows = walkforward_windows(start, end)
    print(f"preset={args.preset}; {len(windows)} walk-forward windows")
    return 0


if __name__ == "__main__":
    sys.exit(main())