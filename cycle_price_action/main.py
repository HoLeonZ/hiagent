"""CLI entry point for cycle_price_action."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

from hiagent_config import get_db_path
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
    cols = ["thscode", "entry_date", "exit_date", "entry_price",
            "exit_price", "shares", "pnl", "hold_days",
            "k_line_score", "phase_score", "calendar_score"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in trades:
            w.writerow({c: getattr(t, c) for c in cols})


def _run_backtest(args) -> int:
    start, end = _resolve_window(args.start, args.end)
    out_dir = Path(args.out_dir) / f"run_{datetime.now():%Y%m%d_%H%M%S_%f}"
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = args.db if args.db else str(get_db_path())
    result = run_backtest(db_path=db_path, start=start, end=end, cash=args.cash)

    _write_trades_csv(out_dir / "trades.csv", result.trades)
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