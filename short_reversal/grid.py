"""TP 单维网格搜索 — 固定 SL/up_streak/pct_chg/ma/universe，仅扫描 TP。"""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from short_reversal.presets import get_preset
from short_reversal.signals import compute_panel_indicators, select_entries
from short_reversal.trades import pre_simulate_trades
from short_reversal.universe import load_universe

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb")

_METRIC_COLS = ["tp_pct", "trades", "win_rate", "final_capital", "sharpe", "max_dd"]


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=_METRIC_COLS)


def run_grid(
    preset: str,
    tp_values: list[float],
    db_path: Path,
    start: str,
    end: str,
) -> pd.DataFrame:
    """对每个 TP 值跑 pre_simulate_trades，返回 metrics 表。

    sl_pct / max_hold 来自 preset（固定），universe 一次性预过滤。
    """
    if not tp_values:
        return _empty_result()

    p = get_preset(preset)
    universe = set(load_universe(p["universe"], db_path))

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        panel = con.execute(
            "SELECT thscode, date, open, high, low, close, turnover FROM v_daily "
            "WHERE date BETWEEN ? AND ? ORDER BY thscode, date",
            [start, pd.Timestamp(end).strftime("%Y-%m-%d")],
        ).fetchdf()
    finally:
        con.close()

    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["thscode"].isin(universe)].reset_index(drop=True)
    panel_ind = compute_panel_indicators(panel)

    rows = []
    for tp in tp_values:
        entries = select_entries(
            panel_ind, tp_pct=tp, start_date=start, end_date=end,
        )
        trades = pre_simulate_trades(
            entries, panel,
            tp_pct=tp, sl_pct=p["sl_pct"], max_hold=p["max_hold"],
        )
        if trades.empty:
            rows.append({
                "tp_pct": tp, "trades": 0, "win_rate": 0.0,
                "final_capital": 1.0, "sharpe": 0.0, "max_dd": 0.0,
            })
            continue

        cap = 1.0
        pnls = []
        peak = 1.0
        max_dd = 0.0
        for _, t in trades.iterrows():
            pnl = (t["entry_price"] - t["exit_price"]) / t["entry_price"]
            cap *= (1 + pnl)
            pnls.append(pnl)
            peak = max(peak, cap)
            dd = (peak - cap) / peak
            max_dd = max(max_dd, dd)
        n = len(pnls)
        mean_pnl = float(np.mean(pnls))
        std_pnl = float(np.std(pnls, ddof=1)) if n > 1 else 0.0
        sharpe = (mean_pnl / std_pnl * math.sqrt(n)) if std_pnl > 0 else 0.0

        rows.append({
            "tp_pct": tp, "trades": n,
            "win_rate": sum(1 for x in pnls if x > 0) / n,
            "final_capital": cap, "sharpe": sharpe, "max_dd": max_dd,
        })

    return pd.DataFrame(rows, columns=_METRIC_COLS)


def main() -> None:
    parser = argparse.ArgumentParser(description="short_reversal TP 网格搜索")
    parser.add_argument("--preset", default="v33_mainboard")
    parser.add_argument("--tp", required=True, help="逗号分隔 TP 值列表，如 0.02,0.03,0.04,0.05,0.06")
    parser.add_argument("--start", default="2025-09-01")
    parser.add_argument("--end", default="2026-09-01")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--out", default="short_reversal/results/grid_tp.json")
    args = parser.parse_args()

    tp_values = [float(x) for x in args.tp.split(",")]
    result = run_grid(args.preset, tp_values, Path(args.db_path), args.start, args.end)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.to_json(orient="records", force_ascii=False, indent=2),
                   encoding="utf-8")
    print(result.to_string(index=False))
    print(f"\n网格结果已保存: {out}")


if __name__ == "__main__":
    main()