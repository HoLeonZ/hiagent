"""Capture trade JSON for all short_reversal presets to tests/golden/.

Each output is a self-contained trades.json usable by render_html_report.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/holeon/code/hiagent")

from short_reversal.engine import run_backtest_v3
from short_reversal.presets import PRESETS
from hiagent_config import get_db_path

START = "2025-09-12"
END = "2026-09-12"


def main() -> None:
    db = get_db_path()
    if not db.exists():
        raise SystemExit(f"DB not found at {db}")
    out_dir = Path(__file__).parent / "golden"
    for name in sorted(PRESETS.keys()):
        out = out_dir / f"{name}.json"
        print(f"=== {name} ===")
        m = run_backtest_v3(name, START, END, db)
        payload = {
            "preset": m["preset"],
            "start": m["start"],
            "end": m["end"],
            # flat top-level fields for render_html_report.py compatibility
            "trades_count": m["trades_count"],
            "win_rate": m["win_rate"],
            "final_capital": m["final_capital"],
            "total_yield": m["total_yield"],
            "cagr": m["cagr"],
            "sharpe": m["sharpe"],
            "max_dd": m["max_dd"],
            "avg_pnl": m["avg_pnl"],
            "avg_hold_days": m["avg_hold_days"],
            "tp_count": m["tp_count"],
            "sl_count": m["sl_count"],
            "time_count": m["time_count"],
            # nested copy for audit / parity reference
            "metrics": {
                "trades_count": m["trades_count"],
                "win_rate": m["win_rate"],
                "final_capital": m["final_capital"],
                "total_yield": m["total_yield"],
                "cagr": m["cagr"],
                "sharpe": m["sharpe"],
                "max_dd": m["max_dd"],
                "avg_pnl": m["avg_pnl"],
                "avg_hold_days": m["avg_hold_days"],
                "tp_count": m["tp_count"],
                "sl_count": m["sl_count"],
                "time_count": m["time_count"],
            },
            "trades": m["trades"],
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(
            f"  WROTE {out.name}: trades={m['trades_count']} CAGR={m['cagr']:.4f} "
            f"final={m['final_capital']:,.2f} max_dd={m['max_dd']:.4f}"
        )


if __name__ == "__main__":
    main()
