"""Short_reversal focused compare runner — 3 组 5 分钟对比,追求信息密度。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import DB_PATH as DEFAULT_DB  # noqa: E402

START = "2025-09-12"
END = "2026-09-12"


def _run(name: str, cfg: dict) -> dict:
    from short_reversal import presets as _p
    _p.PRESETS[name] = cfg
    try:
        m = run_backtest_v3(name, START, END, DEFAULT_DB)
    finally:
        _p.PRESETS.pop(name, None)
    # 写 trades JSON 落盘
    out = Path(f"short_reversal/results/focused_{name}.json")
    out.write_text(json.dumps(m, default=str), encoding="utf-8")
    return m


def main():
    base_cons = {
        "universe": "mainboard_only",
        "tp_pct": 0.02, "sl_pct": 0.005, "max_hold": 3,
    }
    base_agg = {
        "universe": "mainboard_only",
        "tp_pct": 0.06, "sl_pct": 0.0005, "max_hold": 5,
        "pct_chg_low": 0.02, "pct_chg_high": 0.07,
    }

    candidates = [
        # v35 系列: 在 v33 保守线基础上加 pct_chg 收紧 (v34 思路移植)
        ("v35_cons_pctchg_03_08",  {**base_cons, "pct_chg_low": 0.03, "pct_chg_high": 0.08}),
        ("v35_cons_pctchg_025_06", {**base_cons, "pct_chg_low": 0.025, "pct_chg_high": 0.06}),
        # v35 系列: 在 v34 基础上进一步收紧入场
        ("v35_agg_pctchg_04_09",   {**base_agg, "pct_chg_low": 0.04, "pct_chg_high": 0.09}),
        ("v35_agg_pctchg_035_075", {**base_agg, "pct_chg_low": 0.035, "pct_chg_high": 0.075}),
    ]

    for name, cfg in candidates:
        t0 = time.time()
        m = _run(name, cfg)
        dt = time.time() - t0
        print(f"  [{dt:>5.1f}s] {name:<30}  n={m['trades_count']:>4} "
              f"win={m['win_rate']*100:>5.1f}% CAGR={m['cagr']*100:>10.2f}% "
              f"Sharpe={m['sharpe']:>5.2f} DD={m['max_dd']*100:>5.1f}% "
              f"TP/SL/T={m['tp_count']}/{m['sl_count']}/{m['time_count']}",
              flush=True)


if __name__ == "__main__":
    main()