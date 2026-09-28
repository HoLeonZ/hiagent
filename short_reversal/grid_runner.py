"""Short_reversal 单轴 grid runner（不落 PRESETS，仅临时构造 cfg）。

用途：在 P3+P5 修复后的 v3 引擎上做参数 grid，对比 n / win% / CAGR / Sharpe / DD。
NOT 用于 production — 仅作为探索性研究脚本。lock-by-file-location 即可,
不污染 PRESETS。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from short_reversal.engine import run_backtest_v3  # noqa: E402
from hiagent_config import DB_PATH as DEFAULT_DB  # noqa: E402

START = "2025-09-12"
END = "2026-09-12"


def _run(cfg: dict, name: str) -> dict:
    """临时 monkey-patch PRESETS dict,跑一次 v3 引擎。"""
    from short_reversal import presets as _p

    _p.PRESETS[name] = cfg
    try:
        m = run_backtest_v3(name, START, END, DEFAULT_DB)
    finally:
        _p.PRESETS.pop(name, None)
    return m


def grid(axis: str, base: dict, values: list, base_name: str) -> list[dict]:
    rows = []
    for v in values:
        cfg = dict(base)
        if axis == "tp_pct":
            cfg["tp_pct"] = v
        elif axis == "sl_pct":
            cfg["sl_pct"] = v
        elif axis == "max_hold":
            cfg["max_hold"] = v
        elif axis == "pct_chg_low":
            cfg["pct_chg_low"] = v
        elif axis == "pct_chg_high":
            cfg["pct_chg_high"] = v
        elif axis == "a_condition":
            cfg["a_condition"] = v
        else:
            raise ValueError(axis)
        name = f"_grid_{base_name}_{axis}_{str(v).replace('.', '_')}"
        import time
        t0 = time.time()
        try:
            m = _run(cfg, name)
        except (duckdb.Error, ValueError, KeyError) as e:
            # §0 Fail-Fast narrowed: IS-grid sweep is exploratory; keep
            # warn + error row + continue. Only catch data-shape/lookup
            # exceptions; programming errors / MemoryError propagate.
            print(f"  [ERR] {axis}={v}: {e}", flush=True)
            rows.append({"axis": axis, "value": v, "error": str(e)[:60]})
            continue
        dt = time.time() - t0
        rows.append({
            "axis": axis,
            "value": v,
            "name": name,
            "n": m["trades_count"],
            "win%": m["win_rate"] * 100,
            "CAGR%": m["cagr"] * 100,
            "Sharpe": m["sharpe"],
            "DD%": m["max_dd"] * 100,
            "TP/SL/T": f"{m['tp_count']}/{m['sl_count']}/{m['time_count']}",
        })
        print(f"  [{dt:>5.1f}s] {axis:>15}={str(v):<8} n={m['trades_count']:>4} "
              f"win={m['win_rate']*100:>5.1f}% CAGR={m['cagr']*100:>10.2f}% "
              f"Sharpe={m['sharpe']:>5.2f} DD={m['max_dd']*100:>5.1f}% "
              f"{m['tp_count']}/{m['sl_count']}/{m['time_count']}",
              flush=True)
    return rows


BASE_CONSERVATIVE = {
    "universe": "mainboard_only",
    "tp_pct": 0.02,
    "sl_pct": 0.005,
    "max_hold": 3,
}
BASE_AGGRESSIVE = {
    "universe": "mainboard_only",
    "tp_pct": 0.06,
    "sl_pct": 0.0005,
    "max_hold": 5,
    "pct_chg_low": 0.02,
    "pct_chg_high": 0.07,
}


def main():
    out_dir = Path("short_reversal/results/grid")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== CONSERVATIVE (tp2_sl05_dneg) GRID ===", flush=True)
    all_rows = []
    axes = {
        "tp_pct": [0.015, 0.020, 0.025, 0.030],
        "sl_pct": [0.003, 0.005, 0.007],
        "max_hold": [2, 3, 4],
        "pct_chg_high": [0.05, 0.07, 0.10],
    }
    for ax, vals in axes.items():
        rows = grid(ax, BASE_CONSERVATIVE, vals, "cons")
        all_rows.extend(rows)

    print()
    print("=== AGGRESSIVE (tp6_sl005_mh5_realistic) GRID ===", flush=True)
    axes_a = {
        "tp_pct": [0.05, 0.06, 0.07, 0.08],
        "sl_pct": [0.0003, 0.0005, 0.0008],
        "max_hold": [4, 5, 6, 7],
        "pct_chg_low": [0.015, 0.02, 0.025],
    }
    for ax, vals in axes_a.items():
        rows = grid(ax, BASE_AGGRESSIVE, vals, "agg")
        all_rows.extend(rows)

    csv_path = out_dir / "grid_v3_p3p5fix.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["axis", "value", "name", "n", "win%",
                                          "CAGR%", "Sharpe", "DD%", "TP/SL/T", "error"])
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"\n→ 落盘 {csv_path}")


if __name__ == "__main__":
    main()