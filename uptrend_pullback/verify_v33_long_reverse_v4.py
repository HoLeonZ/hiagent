"""v4 = v3a + v3c 组合 — 信号收紧 + SL 略紧。

预期:
  - v3a: CAGR 326.97%, DD 31.33%, Sharpe 2.779, Win 39.29%, PF 1.818
  - v4: DD 可能再降 1-3%, CAGR 可能微降 (sl 更紧砍得快)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from hiagent_config import DB_PATH

from uptrend_pullback.backtrader_engine import run_backtrader_backtest

START, END = "2025-09-16", "2026-09-16"

# v3a (min_above_ma60=0.55) + v3c (sl=0.018) 组合
V4 = {
    "universe": "mainboard_only",
    "tp_pct": 0.30,
    "sl_pct": 0.018,
    "max_hold": 15,
    "max_positions": 1,
    "position_sizing": "all_in",
    "signal": {
        "entry_mode": "v33_long_mirror",
        "min_down_streak": 3,
        "max_down_streak": 10,
        "pct_chg_low": -0.05,
        "pct_chg_high": -0.02,
        "min_amount": 3e7,
        "max_amount": 3e8,
        "min_above_ma60_ratio": 0.55,
    },
}

# 同时再试 v4b: min_above_ma60=0.60 + sl=0.02 (信号再紧一档)
V4B = {
    **V4,
    "sl_pct": 0.02,
    "signal": {**V4["signal"], "min_above_ma60_ratio": 0.60},
}


def main():
    logging.basicConfig(level=logging.WARNING)
    print(f"[verify] {START} .. {END} (backtrader Phase 2)")

    results = {}
    for name, preset in [("v4", V4), ("v4b", V4B)]:
        print(f"\n=== {name} ===")
        out = run_backtrader_backtest(
            preset, START, END, Path(DB_PATH),
            verify=True,
            position_sizing="all_in",
            kelly_fraction=None,
            max_positions=1,
        )
        m = out["metrics"]
        results[name] = m
        print(f"  CAGR:    {m['cagr']*100:.2f}%")
        print(f"  Sharpe:  {m['sharpe']:.3f}")
        print(f"  DD:      {m['max_dd']*100:.2f}%")
        print(f"  Win:     {m['win_rate']*100:.2f}%")
        print(f"  PF:      {m['profit_factor']:.3f}")
        print(f"  TP/SL/t: {m['tp_count']}/{m['sl_count']}/{m['time_count']}")
        print(f"  Trades:  {m['trades']}")

    print("\n=== 汇总 ===")
    print(f"{'config':<10} {'CAGR':>8} {'Sharpe':>7} {'DD':>7} {'Win':>6} {'PF':>5} {'Trades':>7}")
    base = {"CAGR": 2.8027, "Sharpe": 2.704, "DD": 0.3427, "Win": 0.3860, "PF": 1.629, "Trades": 57}
    print(f"{'baseline':<10} {base['CAGR']*100:>7.2f}% {base['Sharpe']:>7.3f} {base['DD']*100:>6.2f}% {base['Win']*100:>5.2f}% {base['PF']:>5.3f} {base['Trades']:>7d}")
    for name, m in results.items():
        print(f"{name:<10} {m['cagr']*100:>7.2f}% {m['sharpe']:>7.3f} {m['max_dd']*100:>6.2f}% {m['win_rate']*100:>5.2f}% {m['profit_factor']:>5.3f} {m['trades']:>7d}")

    out_path = Path("uptrend_pullback/results/v33_long_reverse_v4.json")
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n已保存: {out_path}")


if __name__ == "__main__":
    main()