"""Capture v33_mainboard_tp6_sl005_mh5_realistic baseline to tests/golden/.

Lock the 591-trade run as the parity-locked reference. Any future change that
alters metrics bytewise must update this file deliberately + document delta.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/Users/holeon/code/hiagent")

from short_reversal.engine import run_backtest_v3
from hiagent_config import get_db_path

PRESET = "v33_mainboard_tp6_sl005_mh5_realistic"
START = "2025-09-12"
END = "2026-09-12"
OUT = Path(__file__).parent / f"{PRESET}_baseline.json"


def main():
    db = get_db_path()
    if not db.exists():
        raise SystemExit(f"DB not found at {db}")

    m = run_backtest_v3(PRESET, START, END, db)

    payload = {
        "preset": m["preset"],
        "start": m["start"],
        "end": m["end"],
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
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"WROTE {OUT}: trades={m['trades_count']} CAGR={m['cagr']:.4f} "
        f"final={m['final_capital']:,.2f} max_dd={m['max_dd']:.4f}"
    )


if __name__ == "__main__":
    main()