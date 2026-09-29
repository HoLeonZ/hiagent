"""短 walk-forward — v34 在 4 个代表性 6 个月窗口上跑 (覆盖 2024-09 → 2026-09)。

相比 walkforward.py 的 12 个 2-月窗口, 这个 focused 版本更省时间,
用于 cron-trigger 节奏下的"v34 是否跨冷窗口稳定"快速验证。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402
from dna_stats.deflated import deflated_sharpe_ratio  # noqa: E402

# 6-month windows covering bull/bear/sideways spans
WINDOWS = [
    ("2024-09-12", "2025-03-12"),  # Q4 2024 + Q1 2025 (震荡+拉涨)
    ("2025-03-12", "2025-09-12"),  # Q2+Q3 2025 (拉涨后期)
    ("2025-09-12", "2026-03-12"),  # Q4 2025 + Q1 2026 (拉涨)
    ("2026-03-12", "2026-09-12"),  # Q2+Q3 2026 (高位震荡)
]


def main():
    import time
    from short_reversal import presets as _p

    preset = "v34_mainboard_pctchg_tight"
    if preset not in _p.PRESETS:
        raise SystemExit(f"preset {preset!r} 不在 PRESETS")

    print(f"=== v34 walk-forward (6-month windows × {len(WINDOWS)}) ===")
    sharpes: list[float] = []
    for s, e in WINDOWS:
        t0 = time.time()
        m = run_backtest_v3(preset, s, e, DB_PATH)
        dt = time.time() - t0
        yield_pct = m["cagr"] * 100  # 6-month window, cagr ≈ total_yield (already annualized but at single-year scale; report total_yield)
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
            f"\n§5 DSR | observed_sharpe={observed:.3f} | "
            f"n_trials={len(sharpes)} | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"p_value={dsr['dsr_p_value']:.4f}"
        )


if __name__ == "__main__":
    main()