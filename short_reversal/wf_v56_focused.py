"""Walk-forward for v56_mh_10 (max_hold extension breakthrough, 2026-10-12).

4 windows of 6 months each, no overlap, full data per window.
Engine handles indicator warmup internally.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from dna_stats.deflated import deflated_sharpe_ratio  # noqa: E402
from hiagent_config import DB_PATH  # noqa: E402
from short_reversal.presets import get_preset  # §5: 取 n_comparisons

# §5 (audit P3, 2026-10-15): 6 个月窗口 ≈ 126 个交易日(参照 wf_v56 的既有取值)。
# 原实现硬编码 252(全年),与窗口长度不符 —— SE 项因此被低估。
WINDOW_TRADING_DAYS = 126

WINDOWS = [
    ("2024-09-18", "2025-03-18"),
    ("2025-03-18", "2025-09-18"),
    ("2025-09-18", "2026-03-18"),
    ("2026-03-18", "2026-09-18"),
]


def main():
    from short_reversal import presets as _p
    preset = sys.argv[1] if len(sys.argv) > 1 else "v56_mh_10"
    if preset not in _p.PRESETS:
        raise SystemExit(f"preset {preset!r} not in PRESETS")
    print(f"=== {preset} walk-forward ===")
    sharpes: list[float] = []
    yields: list[float] = []
    dds: list[float] = []
    for s, e in WINDOWS:
        t0 = time.time()
        m = run_backtest_v3(preset, s, e, DB_PATH)
        dt = time.time() - t0
        yield_actual = m["total_yield"] * 100
        sharpes.append(float(m["sharpe"]))
        yields.append(yield_actual)
        dds.append(m["max_dd"] * 100)
        print(f"  [{dt:>5.1f}s] {s} → {e}  n={m['trades_count']:>4} "
              f"win={m['win_rate']*100:>5.1f}% total_yield={yield_actual:>+10.2f}% "
              f"Sharpe={m['sharpe']:>5.2f} DD={m['max_dd']*100:>5.1f}% "
              f"TP/SL/T={m['tp_count']}/{m['sl_count']}/{m['time_count']}",
              flush=True)
    if sharpes:
        # §5 (audit 2026-10-15): DSR 的输入必须与 n_trials 描述**同一次选择**。
        # 此前是 `observed = max(sharpes)` —— 对**窗口**取最大,而 n_trials 计的是
        # **配置**数(n_comparisons)。分子="最好的那一个窗口",分母="试过多少配置",
        # 两者不是同一次选择,于是**窗口那一层选择完全没有被折减**。
        # 这与 deflated_sharpe_ratio 的契约直接冲突(docstring 原文:n_trials 是
        # "selecting the best Sharpe from k trials" 里的 k)。
        # 现取**跨窗口均值**(WFV 的无偏汇总),n_trials 仍为配置数 —— 分子分母
        # 描述同一次选择。逐窗口数值在上面已逐行打印,信息不丢失。
        observed = sum(sharpes) / len(sharpes)
        best_window_sharpe = max(sharpes)
        # §5 (audit P3, 2026-10-15): 改为**消费** preset 声明的累计试验数,而不是
        # 在脚本里再写一份。此处原本硬编码 `31  # 28 v55 + 3 v56`,而 v56 的 preset
        # 已声明 `n_comparisons=31` —— 同一个数两处维护,必然漂移;该字段此前被声明
        # 却无消费者,正是本文件在给它的用途打补丁。
        _cfg = get_preset(preset) if isinstance(preset, str) else preset
        dsr = deflated_sharpe_ratio(
            observed_sharpe=observed,
            n_trials=int(_cfg["n_comparisons"]),
            n_returns=WINDOW_TRADING_DAYS,
        )
        avg_yield = sum(yields) / len(yields)
        max_dd_peak = max(dds)
        print(
            f"\n=== {preset} WF summary ==="
            f"\n  4 windows: avg yield={avg_yield:>+8.2f}%  peak DD={max_dd_peak:>5.1f}%"
            f"\n  win count: {sum(1 for y in yields if y > 0)}/4 positive"
            f"\n  §5 DSR: mean_oos_sharpe={observed:.3f} | best_window={best_window_sharpe:.3f}(选中值,不作显著性输入) | n_trials={n_trials} | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"p_value={dsr['dsr_p_value']:.4f}"
        )


if __name__ == "__main__":
    main()
