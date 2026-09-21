"""Walk-forward for v40_tp_07 and v40_tp_08."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402

WINDOWS = [
    ("2024-09-12", "2025-03-12"),
    ("2025-03-12", "2025-09-12"),
    ("2025-09-12", "2026-03-12"),
    ("2026-03-12", "2026-09-12"),
]


def run_one(preset: str) -> None:
    from short_reversal import presets as _p
    if preset not in _p.PRESETS:
        raise SystemExit(f"preset {preset!r} 不在 PRESETS")
    print(f"\n=== {preset} walk-forward ===")
    for s, e in WINDOWS:
        t0 = time.time()
        m = run_backtest_v3(preset, s, e, DB_PATH)
        dt = time.time() - t0
        yield_actual = m["total_yield"] * 100
        print(f"  [{dt:>5.1f}s] {s} → {e}  n={m['trades_count']:>4} "
              f"win={m['win_rate']*100:>5.1f}% total_yield={yield_actual:>+10.2f}% "
              f"Sharpe={m['sharpe']:>5.2f} DD={m['max_dd']*100:>5.1f}% "
              f"TP/SL/T={m['tp_count']}/{m['sl_count']}/{m['time_count']}",
              flush=True)


def main():
    run_one("v40_tp_07")
    run_one("v40_tp_08")


if __name__ == "__main__":
    main()