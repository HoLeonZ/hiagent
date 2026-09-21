"""CLI entry point for cycle_price_action."""
from __future__ import annotations

import argparse
import sys
from datetime import date

from hiagent_config import get_db_path
from circle_price_action.presets import PRESET_V1
from circle_price_action.walkforward import walkforward_windows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("cycle_price_action")
    p.add_argument("--db", default=str(get_db_path()))
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--preset", default="v1", choices=["v1"])
    args = p.parse_args(argv)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    windows = walkforward_windows(start, end)
    print(f"preset={args.preset}; {len(windows)} walk-forward windows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
