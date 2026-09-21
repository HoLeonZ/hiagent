"""CLI entry point for cycle_price_action."""
from __future__ import annotations

import argparse
import sys
from datetime import date

from hiagent_config import get_db_path
from circle_price_action.walkforward import walkforward_windows


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
    p = argparse.ArgumentParser("circle_price_action")
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

    args = p.parse_args(argv)
    if getattr(args, "cmd", None) == "walkforward":
        return args.func(args)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    windows = walkforward_windows(start, end)
    print(f"preset={args.preset}; {len(windows)} walk-forward windows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
