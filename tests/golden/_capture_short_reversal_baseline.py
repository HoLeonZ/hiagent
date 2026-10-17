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
PRESETS = ["v50_slope", "v44_ratio02_buf07", "v81_adj"]
START, END, MIN_BARS = "2025-09-12", "2026-09-12", 150
OUT_DIR = Path(__file__).parent


def trades_sha256(trades: list[dict]) -> str:
    """Canonical, order-stable hash of the trade list (CLAUDE.md §0)."""
    canon = json.dumps(trades, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def equity_sha256(equity_curve: list[dict]) -> str:
    """Canonical, order-stable hash of the per-bar `(date, equity)` series.

    The equity path is SEPARATE from the fills that produce the trade list:
    `max_dd` comes from the per-bar NAV tracker (`replay_strategy_v3.py` marks
    holdings at the current close) and `final_capital` from `holder["cash"]`
    (`engine.py`). So a change to the mark-to-market price source leaves the
    trade list — and therefore `trades_sha256` — byte-identical while moving
    `max_dd`/`cagr` and the per-bar curve that feeds the ensemble Sharpe and the
    gate's DSR. This hash is what locks that second path (CLAUDE.md §0/§6).

    A hash is not a performance number, so committing it satisfies §7 (we do NOT
    commit the curve or any metric value). MUST stay byte-identical to
    `tests/test_short_reversal_golden_reproducibility.py::equity_sha256`.
    """
    canon = json.dumps(
        [[str(r["date"]), float(r["equity"])] for r in equity_curve],
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def main() -> int:
    db = get_db_path()
    if not db.exists():
        raise SystemExit(f"DB not found at {db}  (skipping is the test's job, not this script's)")

    for preset in PRESETS:
        m = run_backtest_v3(preset, START, END, db, min_bars=MIN_BARS)
        if not m["trades"]:
            raise SystemExit(
                f"{preset}: 0 trades on {START}..{END} (min_bars={MIN_BARS}) — "
                f"refusing to write a degenerate golden baseline. A zero-trade "
                f"result here means the window is too short for min_bars, the "
                f"universe came back empty, or the F-01 guard was bypassed — "
                f"investigate before regenerating."
            )
        payload = {
            "preset": m["preset"],
            "start": m["start"],
            "end": m["end"],
            "min_bars": MIN_BARS,
            # §7: NO `metrics` block. results/, trades.csv and metrics JSON are
            # run artifacts and must stay gitignored — a committed metrics block
            # is a historical performance claim a fresh clone would carry. Only
            # the BEHAVIOUR lock (trades_sha256 + trades_rows + equity_sha256)
            # belongs here (§6). The equity hash locks the MARK-TO-MARKET path,
            # which the trade list does not observe (see equity_sha256 docstring).
            "trades_sha256": trades_sha256(m["trades"]),
            "trades_rows": len(m["trades"]),
            "equity_sha256": equity_sha256(m["equity_curve"]),
            "note": (
                "§6 golden baseline for short_reversal. Any change to the trade "
                "list OR the per-bar equity curve MUST regenerate this file and "
                "justify the drift in the PR. §7: no metrics/performance block "
                "may be committed here — only the behaviour locks (trades sha256 "
                "+ row count, and the equity-curve sha256) belong in git."
            ),
        }
        out = OUT_DIR / f"sr_{preset}_baseline.json"
        # Trailing newline so the file is byte-identical to what a fresh capture
        # produces (§0 reproducibility) and to the committed baselines.
        out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"WROTE {out.name}: trades={m['trades_count']} "
              f"final={m['final_capital']:,.2f} max_dd={m['max_dd']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
