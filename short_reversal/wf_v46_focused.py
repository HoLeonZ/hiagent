"""Walk-forward for v46_sl_0002."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from dna_stats.deflated import deflated_sharpe_ratio  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402

WINDOWS = [
    ("2024-09-12", "2025-03-12"),
    ("2025-03-12", "2025-09-12"),
    ("2025-09-12", "2026-03-12"),
    ("2026-03-12", "2026-09-12"),
]


def main():
    from short_reversal import presets as _p
    preset = "v46_sl_0002"
    if preset not in _p.PRESETS:
        raise SystemExit(f"preset {preset!r} 不在 PRESETS")
    print(f"=== {preset} walk-forward ===")
    sharpes: list[float] = []
    for s, e in WINDOWS:
        t0 = time.time()
        m = run_backtest_v3(preset, s, e, DB_PATH)
        dt = time.time() - t0
        yield_actual = m["total_yield"] * 100
        sharpes.append(float(m["sharpe"]))
        print(f"  [{dt:>5.1f}s] {s} → {e}  n={m['trades_count']:>4} "
              f"win={m['win_rate']*100:>5.1f}% total_yield={yield_actual:>+10.2f}% "
              f"Sharpe={m['sharpe']:>5.2f} DD={m['max_dd']*100:>5.1f}% "
              f"TP/SL/T={m['tp_count']}/{m['sl_count']}/{m['time_count']}",
              flush=True)
    if sharpes:
        observed = max(sharpes)
        dsr = deflated_sharpe_ratio(
            observed_sharpe=observed, n_trials=len(sharpes), n_returns=252,
        )
        print(
            f"\n§5 DSR for v46_sl_0002 | observed_sharpe={observed:.3f} | "
            f"n_trials={len(sharpes)} | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"p_value={dsr['dsr_p_value']:.4f}"
        )



if __name__ == "__main__":
    main()