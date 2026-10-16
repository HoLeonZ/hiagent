"""Walk-forward for v35_agg_pctchg_04_09 (与 wf_v34_focused 同样的 4 窗口)。"""
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
    ("2024-09-12", "2025-03-12"),
    ("2025-03-12", "2025-09-12"),
    ("2025-09-12", "2026-03-12"),
    ("2026-03-12", "2026-09-12"),
]


def main():
    from short_reversal import presets as _p
    preset = "v35_agg_pctchg_04_09"
    if preset not in _p.PRESETS:
        raise SystemExit(f"preset {preset!r} 不在 PRESETS")
    print(f"=== {preset} walk-forward (6-month windows × {len(WINDOWS)}) ===")
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
        _cfg = get_preset(preset) if isinstance(preset, str) else preset
        dsr = deflated_sharpe_ratio(
            observed_sharpe=observed,
            n_trials=int(_cfg["n_comparisons"]),
            n_returns=WINDOW_TRADING_DAYS,
        )
        print(
            f"\n§5 DSR for v35_agg_pctchg_04_09 | mean_oos_sharpe={observed:.3f} | best_window={best_window_sharpe:.3f}(选中值,不作显著性输入) | "
            f"n_trials={int(_cfg['n_comparisons'])} | "
            f"deflated_sharpe={dsr['deflated_sharpe']:.3f} | "
            f"expected_max={dsr['expected_max_sharpe']:.3f} | "
            f"p_value={dsr['dsr_p_value']:.4f}"
        )



if __name__ == "__main__":
    main()