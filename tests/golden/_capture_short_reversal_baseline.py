"""Capture short_reversal golden baselines (the engine previously had none).

Locks the trade list so Task 2's condition-function extraction can prove
"no behaviour change". Regenerate ONLY if a logic change is intended, and
justify the drift in the PR (CLAUDE.md §6).

Run: python3 tests/golden/_capture_short_reversal_baseline.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import get_db_path  # noqa: E402

# min_bars=150 (not the engine default 200): the panel spans start-180d..end+60d
# and the F-01 guard in feed_bt.py now raises when EVERY stock is dropped.
PRESETS = ["v50_slope", "v44_ratio02_buf07"]
START, END, MIN_BARS = "2025-09-12", "2026-09-12", 150
OUT_DIR = Path(__file__).parent


def trades_sha256(trades: list[dict]) -> str:
    """Canonical, order-stable hash of the trade list (CLAUDE.md §0)."""
    canon = json.dumps(trades, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def main() -> int:
    db = get_db_path()
    if not db.exists():
        raise SystemExit(f"DB not found at {db}  (skipping is the test's job, not this script's)")

    for preset in PRESETS:
        m = run_backtest_v3(preset, START, END, db, min_bars=MIN_BARS)
        payload = {
            "preset": m["preset"],
            "start": m["start"],
            "end": m["end"],
            "min_bars": MIN_BARS,
            "metrics": {
                k: m[k] for k in (
                    "trades_count", "win_rate", "final_capital", "total_yield",
                    "cagr", "sharpe", "max_dd", "avg_pnl", "avg_hold_days",
                    "tp_count", "sl_count", "time_count",
                )
            },
            "trades_sha256": trades_sha256(m["trades"]),
            "trades_rows": len(m["trades"]),
            "note": (
                "§6 golden baseline for short_reversal. Any change to the trade list "
                "MUST regenerate this file and justify the drift in the PR."
            ),
        }
        out = OUT_DIR / f"sr_{preset}_baseline.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"WROTE {out.name}: trades={m['trades_count']} "
              f"final={m['final_capital']:,.2f} max_dd={m['max_dd']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
