"""今日信号扫描 — CLI + run_scan() 函数。"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import duckdb
import pandas as pd

from short_reversal.presets import get_preset
from short_reversal.signals import compute_panel_indicators, select_entries
from short_reversal.universe import load_universe

logger = logging.getLogger(__name__)

DEFAULT_DB = Path(
    "/Users/holeon/Library/Application Support/hithink-finance/data/market.duckdb"
)


def _next_trade_day(d: pd.Timestamp) -> pd.Timestamp:
    """跳过周末（>=5 即周六/周日）；不处理 A 股节假日（按 brief 简化）。"""
    cur = d + pd.Timedelta(days=1)
    while cur.weekday() >= 5:
        cur += pd.Timedelta(days=1)
    return cur


def run_scan(preset: str, date: str, db_path: Path) -> dict:
    """加载 DuckDB + 计算特征 + 应用 v33 五条件，返回信号 JSON dict。"""
    p = get_preset(preset)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        # 拉窗口：start_date 拉 1 年历史以满足 MA60 预热
        target = pd.Timestamp(date)
        start_window = (target - pd.DateOffset(days=365)).strftime("%Y-%m-%d")
        sql = (
            "SELECT thscode, date, open, high, low, close, amount "
            "FROM v_daily "
            f"WHERE date BETWEEN '{start_window}' AND ? "
            "ORDER BY thscode, date"
        )
        panel = con.execute(sql, [target.strftime("%Y-%m-%d")]).fetchdf()
        panel["date"] = pd.to_datetime(panel["date"])

        if panel.empty:
            raise RuntimeError(
                f"DuckDB 在 {start_window} ~ {date} 之间无 v_daily 数据"
            )
    finally:
        con.close()

    # universe 过滤
    universe = set(load_universe(p["universe"], db_path))
    panel = panel[panel["thscode"].isin(universe)].reset_index(drop=True)

    panel_ind = compute_panel_indicators(panel)
    entries = select_entries(
        panel_ind, tp_pct=p["tp_pct"],
        start_date=date, end_date=date,
    )

    # 把 am60 从 panel_ind merge 回来（select_entries 返回的 sig_* 不含 am60）
    am60_lookup = panel_ind.set_index(["thscode", "date"])["am60"]
    entries = entries.merge(
        am60_lookup.rename("am60").reset_index(),
        on=["thscode", "date"], how="left",
    )

    next_day = _next_trade_day(target)

    out_signals = []
    for _, r in entries.iterrows():
        am60_val = r.get("am60", math.nan)
        am60_yi: float | None
        if pd.notna(am60_val):
            am60_yi = float(am60_val) / 1e8
        else:
            am60_yi = None
        out_signals.append({
            "thscode": r["thscode"],
            "signal_date": date,
            "close": float(r["sig_close"]),
            "ma60": float(r["sig_ma60"]),
            "pct_chg_pct": float(r["sig_pct_chg"] * 100),
            "up_streak": int(r["sig_up_streak"]),
            "dif": float(r["sig_dif"]),
            "dea": float(r["sig_dea"]),
            "macd_bar": float(r["sig_macd_bar"]),
            "am60_yi": am60_yi,
        })

    return {
        "strategy": f"{preset} (v33 五条件)",
        "signal_date": date,
        "next_trade_date_open": next_day.strftime("%Y-%m-%d"),
        "tp_pct": p["tp_pct"],
        "sl_pct": p["sl_pct"],
        "max_hold": p["max_hold"],
        "universe_mode": p["universe"],
        "count": len(out_signals),
        "signals": out_signals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="short_reversal 今日信号扫描")
    parser.add_argument("--preset", default="v33_mainboard")
    parser.add_argument("--date", required=True, help="信号日 (YYYY-MM-DD)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB))
    parser.add_argument("--out", default="short_reversal/results/today_signals.json")
    args = parser.parse_args()

    result = run_scan(args.preset, args.date, Path(args.db_path))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"扫描完成: {result['count']} 个信号 → {out}")


if __name__ == "__main__":
    main()